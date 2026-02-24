"""POKEY VQ Tracker - Audio Engine

ALL playback uses cycle-accurate POKEY emulation:
  - Song/pattern play (F5/F6/F7): VQPlayer drives 4-channel POKEY output
  - Note preview (key press): Renders note through POKEY, plays result
  - Sample editor preview: Renders through POKEY in RAW mode at target rate
  - WAV export: Renders entire song through POKEY

Before VQ conversion:
  Instruments are converted on-the-fly to RAW POKEY bytes (resample to
  target rate → quantize to 4-bit POKEY levels → 0x10|nibble AUDC bytes).
  This lets you hear *exactly* what the Atari will produce at the configured
  sample rate, including the 4-bit quantization artifacts.

After VQ conversion:
  Uses the actual VQ-compressed data from the converter output.
  Identical to what the .xex plays on real hardware.
"""
import threading
import numpy as np
import logging
from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass
from constants import MAX_CHANNELS, MAX_VOLUME, PAL_HZ, DEFAULT_LENGTH, DEFAULT_SPEED

logger = logging.getLogger("tracker.audio")

try:
    import sounddevice as sd
    AUDIO_OK = True
    logger.info("sounddevice imported successfully")
except (ImportError, OSError) as e:
    AUDIO_OK = False
    logger.warning(f"sounddevice not available, audio disabled: {e}")

# POKEY emulator (pure Python — always available)
try:
    from pokey_emulator.vq_player import (
        VQPlayer, SongData, InstrumentData,
        PAL_CLOCK, NTSC_CLOCK,
    )
    POKEY_EMU_OK = True
    logger.info("POKEY emulator loaded")
except ImportError as e:
    POKEY_EMU_OK = False
    logger.warning(f"POKEY emulator not available: {e}")

SAMPLE_RATE = 44100
BUFFER_SIZE = 512

# Default VQ settings when none provided
_DEFAULT_RATE = 3958
_DEFAULT_VECTOR_SIZE = 8

# POKEY voltage table (16 levels, matching real hardware measurements)
# Same table used by pokey_vq/core/pokey_table.py
_POKEY_VOLTAGES = np.array([
    0.000000, 0.032677, 0.068621, 0.101298, 0.143778, 0.176455,
    0.212399, 0.245076, 0.300626, 0.333303, 0.369247, 0.401924,
    0.444404, 0.477081, 0.513025, 0.545702,
], dtype=np.float32)


def _wav_to_pokey_raw(audio: np.ndarray, src_rate: int,
                      target_rate: int) -> bytes:
    """Convert WAV float32 audio to POKEY RAW bytes.

    Resamples to target_rate and quantizes to 4-bit POKEY volume levels
    using the measured hardware voltage table (nearest-neighbor).
    Each output byte is 0x10 | nibble (AUDC volume-only format).

    Args:
        audio: float32 array in [-1, 1]
        src_rate: source sample rate (Hz)
        target_rate: POKEY playback rate (Hz), e.g. 3958

    Returns:
        bytes of AUDC values, one per sample period.
    """
    # Resample via linear interpolation
    if src_rate != target_rate and len(audio) > 1:
        num_out = max(1, int(len(audio) * target_rate / src_rate))
        x_in = np.linspace(0, 1, len(audio))
        x_out = np.linspace(0, 1, num_out)
        resampled = np.interp(x_out, x_in, audio)
    else:
        resampled = np.asarray(audio, dtype=np.float32)

    # Scale audio [-1,1] to voltage range [0, Vmax]
    v_max = _POKEY_VOLTAGES[-1]
    scaled = ((resampled + 1.0) * 0.5) * v_max
    scaled = np.clip(scaled, 0, v_max)

    # Quantize to nearest POKEY voltage level (0-15)
    indices = np.searchsorted(_POKEY_VOLTAGES, scaled)
    indices = np.clip(indices, 0, 15)
    # Check if the level below is closer
    left = np.clip(indices - 1, 0, 15)
    err_right = np.abs(scaled - _POKEY_VOLTAGES[indices])
    err_left = np.abs(scaled - _POKEY_VOLTAGES[left])
    indices = np.where(err_left < err_right, left, indices).astype(np.uint8)

    # Pack as AUDC volume-only bytes: 0x10 | nibble
    return bytes(0x10 | int(v) for v in indices)


@dataclass
class Channel:
    """Audio channel state — used for VU levels and enabled flags."""
    active: bool = False
    note: int = 0
    volume: int = MAX_VOLUME
    enabled: bool = True
    vu_level: float = 0.0

    # WAV fields kept only for preview channel compatibility
    sample_data: Optional[np.ndarray] = None
    sample_rate: int = SAMPLE_RATE
    position: float = 0.0
    pitch: float = 1.0

    def reset(self):
        self.active = False
        self.sample_data = None
        self.position = 0.0


class AudioEngine:
    """Real-time audio playback engine — all paths through POKEY emulation.

    Uses a SINGLE OutputStream for all audio.  Never use sd.play() anywhere
    in the application — it creates a second OutputStream that kills this one
    on many audio backends (WASAPI exclusive, ALSA without PulseAudio, etc.).
    """

    def __init__(self):
        self.running = False
        self.stream = None
        self.channels = [Channel() for _ in range(MAX_CHANNELS)]
        self.lock = threading.RLock()

        # Preview channel (sample editor preview PCM — pre-rendered through POKEY)
        self._preview = Channel()

        # Playback state
        self.playing = False
        self.mode = 'stop'  # 'stop', 'pattern', 'song'
        self.song = None

        # Position
        self.songline = 0
        self.row = 0
        self.tick = 0
        self.speed = DEFAULT_SPEED
        self.hz = PAL_HZ
        self.samples_per_tick = SAMPLE_RATE // PAL_HZ
        self.sample_count = 0

        # Pattern info
        self.patterns = list(range(MAX_CHANNELS))
        self.lengths = [DEFAULT_LENGTH] * MAX_CHANNELS

        # Callbacks
        self.on_row: Optional[Callable[[int, int], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self._pending_callbacks: List[Tuple] = []

        self.master_volume = 0.8

        # FFT capture buffer
        self._fft_size = 2048
        self._fft_buf = np.zeros(self._fft_size, dtype=np.float32)
        self._fft_write_pos = 0

        # ================================================================
        # POKEY Emulation State
        # ================================================================
        self._vq_player: Optional[object] = None
        self._pokey_buf = np.zeros(0, dtype=np.float32)
        self._pokey_buf_pos = 0
        self._pokey_buf_avail = 0
        self._vq_state = None   # Reference to VQState
        self._pokey_row_cb_cycle = 0

    # ====================================================================
    # Stream Management
    # ====================================================================

    def start(self) -> bool:
        if not AUDIO_OK:
            return False
        if self.running and self.stream and self.stream.active:
            return True
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            self.running = False
        try:
            self.stream = sd.OutputStream(
                samplerate=SAMPLE_RATE, channels=2, dtype='float32',
                blocksize=BUFFER_SIZE, callback=self._audio_callback, latency='low'
            )
            self.stream.start()
            self.running = True
            logger.info("Audio stream started (stereo)")
            return True
        except Exception as e:
            logger.error(f"Audio start error: {e}")
            return False

    def stop(self):
        self.stop_playback()
        self.stop_preview()
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.warning(f"Error closing audio stream: {e}")
        self.stream = None
        self.running = False

    def ensure_stream(self):
        if not AUDIO_OK:
            return
        if self.running and self.stream:
            try:
                if self.stream.active:
                    return
            except Exception:
                pass
            logger.warning("Audio stream died — restarting")
            self.running = False
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if not self.running:
            self.start()

    # ====================================================================
    # Audio Callback
    # ====================================================================

    def _audio_callback(self, out: np.ndarray, frames: int, time_info, status):
        try:
            with self.lock:
                output = np.zeros(frames, dtype=np.float32)

                # Song/pattern playback via POKEY
                if self.playing and self._vq_player:
                    output += self._render_pokey(frames)

                # Preview channel (pre-rendered POKEY PCM)
                pv = self._preview
                if pv.active and pv.sample_data is not None:
                    pv_out = self._render_preview(pv, frames)
                    output += pv_out

                mono_out = np.tanh(output * self.master_volume)
                out[:, 0] = mono_out
                out[:, 1] = mono_out

                # FFT ring buffer
                n = len(mono_out)
                pos = self._fft_write_pos
                buf = self._fft_buf
                size = len(buf)
                if n >= size:
                    # Input larger than buffer — just keep the tail
                    buf[:] = mono_out[n - size:]
                    self._fft_write_pos = 0
                else:
                    end = pos + n
                    if end <= size:
                        buf[pos:end] = mono_out
                    else:
                        first = size - pos
                        buf[pos:size] = mono_out[:first]
                        buf[0:n - first] = mono_out[first:]
                    self._fft_write_pos = end % size
        except Exception as e:
            out[:] = 0
            logger.error(f"Audio callback error (stream kept alive): {e}")

    # ====================================================================
    # POKEY Rendering (song/pattern playback)
    # ====================================================================

    def _render_pokey(self, frames: int) -> np.ndarray:
        """Render audio via POKEY emulation — song/pattern playback."""
        output = np.zeros(frames, dtype=np.float32)
        player = self._vq_player
        if not player:
            return output

        written = 0
        while written < frames:
            # Drain existing buffer
            if self._pokey_buf_avail > 0:
                take = min(frames - written, self._pokey_buf_avail)
                start = self._pokey_buf_pos
                output[written:written + take] = self._pokey_buf[start:start + take]
                self._pokey_buf_pos += take
                self._pokey_buf_avail -= take
                written += take

                # Row callback tracking
                self._pokey_row_cb_cycle += take
                spf = SAMPLE_RATE // self.hz
                while self._pokey_row_cb_cycle >= spf:
                    self._pokey_row_cb_cycle -= spf
                    if self.on_row and player.playing:
                        new_sl = player.seq_songline
                        new_row = player.seq_row
                        if new_sl != self.songline or new_row != self.row:
                            self.songline = new_sl
                            self.row = new_row
                            self._pending_callbacks.append(
                                (self.on_row, (self.songline, self.row)))
                continue

            # Buffer empty — render next POKEY frame
            if not player.playing and not any(
                    ch.active for ch in player.channels):
                self.playing = False
                if self.on_stop:
                    self._pending_callbacks.append((self.on_stop, ()))
                break

            # Sync channel mute state from AudioEngine → VQPlayer
            for i in range(min(MAX_CHANNELS, len(player.channel_muted))):
                player.channel_muted[i] = not self.channels[i].enabled

            pcm = player.render_frame()
            if len(pcm) == 0:
                break
            self._pokey_buf = pcm
            self._pokey_buf_pos = 0
            self._pokey_buf_avail = len(pcm)

        # VU levels from POKEY channel activity
        if player:
            for i in range(min(MAX_CHANNELS, len(player.channels))):
                pch = player.channels[i]
                if pch.active and self.channels[i].enabled:
                    # Scale by channel volume (vol_shift is 0xF0 at max)
                    vol_frac = ((pch.vol_shift >> 4) & 0xF) / 15.0
                    self.channels[i].vu_level = max(
                        self.channels[i].vu_level, vol_frac)

        return output

    def _render_preview(self, ch: Channel, frames: int) -> np.ndarray:
        """Render preview channel (pre-rendered PCM from POKEY)."""
        out = np.zeros(frames, dtype=np.float32)
        if ch.sample_data is None:
            return out
        length = len(ch.sample_data)
        for i in range(frames):
            pos = int(ch.position)
            if pos >= length - 1:
                ch.active = False
                break
            frac = ch.position - pos
            out[i] = (ch.sample_data[pos] * (1 - frac) +
                      ch.sample_data[min(pos + 1, length - 1)] * frac)
            ch.position += ch.pitch
        return out

    # ====================================================================
    # POKEY Player Setup
    # ====================================================================

    def set_vq_state(self, vq_state):
        """Store reference to VQState for conversion data + settings."""
        self._vq_state = vq_state

    def _get_target_rate(self) -> int:
        """Get the VQ target sample rate from settings."""
        if self._vq_state and hasattr(self._vq_state, 'settings'):
            return self._vq_state.settings.rate
        return _DEFAULT_RATE

    def _get_vector_size(self) -> int:
        if self._vq_state and hasattr(self._vq_state, 'settings'):
            return self._vq_state.settings.vector_size
        return _DEFAULT_VECTOR_SIZE

    def _has_vq_data(self) -> bool:
        """Check if VQ conversion data is available."""
        if not POKEY_EMU_OK or not self._vq_state:
            return False
        if not self._vq_state.converted or not self._vq_state.result:
            return False
        if not self._vq_state.result.success:
            return False
        if not self._vq_state.result.output_dir:
            return False
        return True

    def _build_player_obj(self, songline: int = 0,
                          row: int = 0) -> Optional['VQPlayer']:
        """Build VQPlayer for the current song (called outside lock).

        Uses VQ conversion data if available; otherwise builds RAW
        instruments on-the-fly from WAV samples at the target rate.

        Returns VQPlayer on success, None on failure.
        """
        if not POKEY_EMU_OK or not self.song:
            return None

        try:
            player = VQPlayer(sample_rate=SAMPLE_RATE)

            if self._has_vq_data():
                # Post-conversion: use actual VQ/RAW data
                player.load_from_tracker(
                    self.song,
                    self._vq_state.result,
                    self._vq_state.settings,
                )
                # Validate: instruments loaded and codebook non-empty
                n_loaded = len(player.song.instruments)
                n_needed = len(self.song.instruments)
                cb_size = len(player.song.codebook)
                if n_loaded == 0 or cb_size == 0:
                    logger.warning(
                        f"VQ data incomplete (inst={n_loaded}, "
                        f"codebook={cb_size}B) — falling back to "
                        f"live RAW")
                    player = VQPlayer(sample_rate=SAMPLE_RATE)
                    song_data = self._build_live_song_data()
                    player.load_song(song_data)
                elif n_loaded < n_needed:
                    logger.warning(
                        f"VQ has {n_loaded} instruments but song "
                        f"needs {n_needed} — falling back to live RAW")
                    player = VQPlayer(sample_rate=SAMPLE_RATE)
                    song_data = self._build_live_song_data()
                    player.load_song(song_data)
                else:
                    logger.info("POKEY player: using converted VQ data")
            else:
                # Pre-conversion: build RAW from WAV instruments
                song_data = self._build_live_song_data()
                player.load_song(song_data)
                logger.info("POKEY player: using live RAW from WAV")

            player.start_playback(songline=songline, row=row)
            return player
        except Exception as e:
            logger.error(f"POKEY player build failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _install_player(self, player: Optional['VQPlayer']):
        """Install a pre-built player (called with lock held)."""
        self._vq_player = player
        self._pokey_buf = np.zeros(0, dtype=np.float32)
        self._pokey_buf_pos = 0
        self._pokey_buf_avail = 0
        self._pokey_row_cb_cycle = 0

    def _build_player(self, songline: int = 0, row: int = 0) -> bool:
        """Build and install VQPlayer (convenience, for use inside lock).

        Used by render_offline which doesn't need the split.
        """
        player = self._build_player_obj(songline, row)
        self._install_player(player)
        return player is not None

    def _build_live_song_data(self) -> 'SongData':
        """Build SongData from current song with WAV→RAW conversion.

        Each instrument's WAV audio is resampled to the target rate and
        quantized to 4-bit POKEY levels. This gives an accurate preview
        of what the Atari will sound like at the configured sample rate.
        """
        song = self.song
        target_rate = self._get_target_rate()
        vector_size = self._get_vector_size()

        sd = SongData()
        sd.ntsc = (song.system == 60)
        sd.vector_size = vector_size
        sd.volume_control = getattr(song, 'volume_control', False)

        clock = NTSC_CLOCK if sd.ntsc else PAL_CLOCK
        sd.audf_val = max(0, min(255, round(clock / 28.0 / target_rate) - 1))
        sd.audctl_val = 0

        # Convert each instrument WAV → RAW POKEY bytes
        for i, inst in enumerate(song.instruments):
            if inst.is_loaded():
                # Get processed audio (with effects applied)
                from sample_editor.pipeline import get_playback_audio
                audio = get_playback_audio(inst)
                if audio is None:
                    audio = inst.sample_data

                raw_bytes = _wav_to_pokey_raw(audio, inst.sample_rate,
                                              target_rate)
                inst_data = InstrumentData(
                    index=i, is_vq=False,
                    stream_data=raw_bytes,
                    start_offset=0, end_offset=len(raw_bytes),
                )
            else:
                # Empty instrument
                inst_data = InstrumentData(
                    index=i, is_vq=False,
                    stream_data=b'\x10',
                    start_offset=0, end_offset=1,
                )
            sd.instruments.append(inst_data)

        # Empty codebook (no VQ data)
        sd.codebook = bytes(256 * vector_size)
        sd.build_codebook_offsets()

        # Pitch table
        player_tmp = VQPlayer(sample_rate=SAMPLE_RATE)
        sd.pitch_table = player_tmp._build_pitch_table()

        # Volume scale
        if sd.volume_control:
            sd.build_volume_scale()

        # Song structure
        sd.song_length = len(song.songlines)
        for sl in song.songlines:
            sd.songlines.append({
                'speed': max(1, sl.speed),
                'patterns': list(sl.patterns),
            })

        from constants import NOTE_OFF, VOL_CHANGE
        _VOL_CHANGE_ASM = 61  # VQPlayer's volume-change marker
        for ptn in song.patterns:
            events = []
            for row_idx in range(ptn.length):
                r = ptn.rows[row_idx]
                if r.note == 0:
                    continue  # Empty row
                # Translate tracker constants → VQPlayer constants
                if r.note == NOTE_OFF:  # 255 → note-off (0)
                    events.append((row_idx, 0, 0, 0))
                elif r.note == VOL_CHANGE:  # 254 → vol-change (61)
                    events.append((row_idx, _VOL_CHANGE_ASM,
                                   r.instrument, r.volume))
                else:
                    events.append((row_idx, r.note, r.instrument, r.volume))
            sd.patterns.append({
                'length': ptn.length,
                'events': events,
            })

        return sd

    # ====================================================================
    # Note Preview via POKEY
    # ====================================================================

    def _render_note_pokey(self, note: int, inst_idx: int,
                           volume: int, duration_s: float = 2.0
                           ) -> Optional[np.ndarray]:
        """Pre-render a single note through POKEY emulation.

        Returns float32 PCM array, or None on failure.
        """
        if not POKEY_EMU_OK or not self.song:
            return None

        try:
            player = VQPlayer(sample_rate=SAMPLE_RATE)

            if self._has_vq_data():
                player.load_from_tracker(
                    self.song,
                    self._vq_state.result,
                    self._vq_state.settings,
                )
                # Validate: fall back if VQ data is incomplete
                if (len(player.song.instruments) == 0 or
                        inst_idx >= len(player.song.instruments)):
                    player = VQPlayer(sample_rate=SAMPLE_RATE)
                    sd_data = self._build_live_song_data()
                    player.load_song(sd_data)
            else:
                sd_data = self._build_live_song_data()
                player.load_song(sd_data)

            # Don't start sequencer — manually trigger a note
            player.playing = False

            if inst_idx < len(player.song.instruments):
                inst = player.song.instruments[inst_idx]
                pitch_step = 0x0100  # default 1x
                note_idx = note - 1
                if 0 <= note_idx < len(player.song.pitch_table):
                    pitch_step = player.song.pitch_table[note_idx]

                ch = player.channels[0]
                ch.trigger(inst, pitch_step, player.song)
                ch.vol_shift = (volume << 4) & 0xF0

            # Render frames until note ends or duration exceeded
            max_frames = int(duration_s * self.hz)
            chunks = []
            for _ in range(max_frames):
                pcm = player.render_frame()
                if len(pcm) > 0:
                    chunks.append(pcm)
                if not any(c.active for c in player.channels):
                    break

            if chunks:
                return np.concatenate(chunks)
            return None
        except Exception as e:
            logger.error(f"Note preview render failed: {e}")
            return None

    # ====================================================================
    # Callbacks
    # ====================================================================

    def process_callbacks(self):
        with self.lock:
            callbacks = self._pending_callbacks.copy()
            self._pending_callbacks.clear()
        for fn, args in callbacks:
            try:
                fn(*args)
            except Exception as e:
                logger.warning(f"Callback error in {fn.__name__}: {e}")

    # ====================================================================
    # PUBLIC API
    # ====================================================================

    def set_song(self, song):
        with self.lock:
            self.song = song
            if song:
                if song.songlines:
                    self.speed = song.songlines[0].speed
                else:
                    self.speed = DEFAULT_SPEED
                self.hz = song.system
                self.samples_per_tick = SAMPLE_RATE // self.hz

    def play_from(self, songline: int, row: int):
        """Play from position (pattern mode)."""
        if not self.song:
            return
        # Build player outside lock (heavy: 60-70ms)
        player = self._build_player_obj(songline, row)
        with self.lock:
            self._stop_all()
            self.mode = 'pattern'
            self.songline = songline
            self.row = row
            self._install_player(player)
            self.playing = True
            if self.on_row:
                self._pending_callbacks.append(
                    (self.on_row, (self.songline, self.row)))

    def play_pattern(self, songline: int = 0):
        self.play_from(songline, 0)

    def play_song(self, from_start: bool = True, songline: int = 0,
                  row: int = 0):
        if not self.song:
            return
        start_sl = 0 if from_start else songline
        start_row = 0 if from_start else row
        # Build player outside lock
        player = self._build_player_obj(start_sl, start_row)
        with self.lock:
            self._stop_all()
            self.mode = 'song'
            self.songline = start_sl
            self.row = start_row
            self._install_player(player)
            self.playing = True
            if self.on_row:
                self._pending_callbacks.append(
                    (self.on_row, (self.songline, self.row)))

    def stop_playback(self):
        with self.lock:
            was_playing = self.playing
            self.playing = False
            self.mode = 'stop'
            self._vq_player = None
            self._stop_all()
            for ch in self.channels:
                ch.vu_level = 0.0
            if was_playing and self.on_stop:
                self._pending_callbacks.append((self.on_stop, ()))

    def _stop_all(self):
        for ch in self.channels:
            ch.active = False
            ch.reset()

    # === NOTE PREVIEW (through POKEY) ===

    def preview_note(self, ch_idx: int, note: int, inst,
                     volume: int = MAX_VOLUME):
        """Preview a single note through POKEY emulation.

        The note is pre-rendered through the POKEY emulator (RAW or VQ
        depending on conversion state) and played via the preview channel.

        Heavy POKEY rendering happens OUTSIDE the lock to avoid blocking
        the audio callback (which fires every ~11ms).
        """
        if not inst or not inst.is_loaded():
            return
        # Find instrument index (UI thread only, no lock needed)
        inst_idx = 0
        if self.song:
            for i, si in enumerate(self.song.instruments):
                if si is inst:
                    inst_idx = i
                    break

        # Render outside lock (60-100ms of POKEY emulation)
        pcm = self._render_note_pokey(note, inst_idx, volume)

        # Brief lock to swap in the result
        if pcm is not None and len(pcm) > 0:
            with self.lock:
                self.channels[ch_idx].vu_level = volume / MAX_VOLUME
                self.channels[ch_idx].active = True
                pv = self._preview
                pv.sample_data = pcm
                pv.sample_rate = SAMPLE_RATE
                pv.pitch = 1.0
                pv.position = 0.0
                pv.volume = MAX_VOLUME
                pv.active = True
                pv.vu_level = 1.0

    def preview_row(self, song, songline: int, row: int):
        """Preview all notes in a row through POKEY emulation."""
        if not song or songline >= len(song.songlines):
            return
        from constants import NOTE_OFF, VOL_CHANGE
        sl = song.songlines[songline]

        # Collect all active notes (UI thread, no lock needed)
        notes = []
        note_ch_info = []
        for ch_idx in range(MAX_CHANNELS):
            ptn = song.get_pattern(sl.patterns[ch_idx])
            r = ptn.get_row_wrapped(row)
            if r.note == NOTE_OFF:
                note_ch_info.append((ch_idx, 'off', 0))
            elif r.note == VOL_CHANGE:
                note_ch_info.append((ch_idx, 'vol', r.volume))
            elif r.note > 0:
                notes.append((ch_idx, r.note, r.instrument, r.volume))

        if not notes:
            # Still apply note-offs and vol changes under lock
            with self.lock:
                for ch_idx, kind, vol in note_ch_info:
                    if kind == 'off':
                        self.channels[ch_idx].active = False
                        self.channels[ch_idx].vu_level = 0.0
                    elif kind == 'vol':
                        self.channels[ch_idx].vu_level = vol / MAX_VOLUME
            return

        # Heavy render outside lock
        pcm = self._render_row_pokey(notes)

        # Brief lock to swap in result
        with self.lock:
            for ch_idx, kind, vol in note_ch_info:
                if kind == 'off':
                    self.channels[ch_idx].active = False
                    self.channels[ch_idx].vu_level = 0.0
                elif kind == 'vol':
                    self.channels[ch_idx].vu_level = vol / MAX_VOLUME

            if pcm is not None and len(pcm) > 0:
                for ch_idx, _, _, vol in notes:
                    self.channels[ch_idx].vu_level = vol / MAX_VOLUME
                    self.channels[ch_idx].active = True
                pv = self._preview
                pv.sample_data = pcm
                pv.sample_rate = SAMPLE_RATE
                pv.pitch = 1.0
                pv.position = 0.0
                pv.volume = MAX_VOLUME
                pv.active = True

    def _render_row_pokey(self, notes: list,
                          duration_s: float = 2.0) -> Optional[np.ndarray]:
        """Pre-render multiple notes through POKEY (for row preview)."""
        if not POKEY_EMU_OK or not self.song:
            return None
        try:
            player = VQPlayer(sample_rate=SAMPLE_RATE)
            if self._has_vq_data():
                player.load_from_tracker(
                    self.song, self._vq_state.result,
                    self._vq_state.settings)
                if len(player.song.instruments) == 0:
                    player = VQPlayer(sample_rate=SAMPLE_RATE)
                    player.load_song(self._build_live_song_data())
            else:
                player.load_song(self._build_live_song_data())

            player.playing = False

            for ch_idx, note, inst_idx, vol in notes:
                if inst_idx >= len(player.song.instruments):
                    continue
                if ch_idx >= 4:
                    continue
                inst = player.song.instruments[inst_idx]
                pitch_step = 0x0100
                nidx = note - 1
                if 0 <= nidx < len(player.song.pitch_table):
                    pitch_step = player.song.pitch_table[nidx]
                ch = player.channels[ch_idx]
                ch.trigger(inst, pitch_step, player.song)
                ch.vol_shift = (vol << 4) & 0xF0

            max_frames = int(duration_s * self.hz)
            chunks = []
            for _ in range(max_frames):
                pcm = player.render_frame()
                if len(pcm) > 0:
                    chunks.append(pcm)
                if not any(c.active for c in player.channels):
                    break
            return np.concatenate(chunks) if chunks else None
        except Exception as e:
            logger.error(f"Row preview render failed: {e}")
            return None

    # === SAMPLE EDITOR PREVIEW (through POKEY RAW) ===

    def play_preview(self, audio_data: np.ndarray, sample_rate: int):
        """Play audio through POKEY emulation in RAW mode at target rate.

        Used by sample editor and file browser. The audio is converted to
        POKEY RAW format at the configured target rate, rendered through the
        POKEY emulator, and played back — giving an accurate preview of
        what the sample will sound like on Atari hardware.
        """
        if sample_rate <= 0 or len(audio_data) == 0:
            return
        data = np.asarray(audio_data, dtype=np.float32)
        if data.ndim > 1:
            data = data.mean(axis=1)

        target_rate = self._get_target_rate()

        # Heavy POKEY render outside lock
        pcm = self._render_raw_preview(data, sample_rate, target_rate)

        if pcm is not None and len(pcm) > 0:
            with self.lock:
                pv = self._preview
                pv.sample_data = pcm
                pv.sample_rate = SAMPLE_RATE
                pv.pitch = 1.0
                pv.position = 0.0
                pv.volume = MAX_VOLUME
                pv.active = True
                pv.vu_level = 1.0

    def _render_raw_preview(self, audio: np.ndarray, src_rate: int,
                            target_rate: int) -> Optional[np.ndarray]:
        """Render audio through POKEY in RAW mode for sample preview."""
        if not POKEY_EMU_OK:
            return None
        try:
            raw_bytes = _wav_to_pokey_raw(audio, src_rate, target_rate)
            if len(raw_bytes) == 0:
                return None

            player = VQPlayer(sample_rate=SAMPLE_RATE)
            sd_data = SongData()
            sd_data.ntsc = (self.song.system == 60) if self.song else False

            clock = NTSC_CLOCK if sd_data.ntsc else PAL_CLOCK
            sd_data.audf_val = max(0, min(255,
                                          round(clock / 28.0 / target_rate) - 1))
            sd_data.audctl_val = 0
            sd_data.vector_size = _DEFAULT_VECTOR_SIZE
            sd_data.codebook = bytes(256 * sd_data.vector_size)
            sd_data.build_codebook_offsets()
            sd_data.pitch_table = player._build_pitch_table()

            inst = InstrumentData(
                index=0, is_vq=False,
                stream_data=raw_bytes,
                start_offset=0, end_offset=len(raw_bytes),
            )
            sd_data.instruments.append(inst)
            sd_data.song_length = 1
            sd_data.songlines.append({'speed': 6, 'patterns': [0, 0, 0, 0]})
            sd_data.patterns.append({
                'length': 64,
                'events': [(0, 1, 0, 15)],  # C-1, inst 0, vol 15
            })

            player.load_song(sd_data)
            player.playing = False

            # Trigger note directly on channel 0
            ch = player.channels[0]
            ch.trigger(inst, 0x0100, sd_data)  # 1:1 pitch
            ch.vol_shift = 0xF0  # Full volume

            # Render until done
            max_frames = int(len(raw_bytes) / target_rate * self.hz) + 20
            max_frames = min(max_frames, 30000)
            chunks = []
            for _ in range(max_frames):
                pcm = player.render_frame()
                if len(pcm) > 0:
                    chunks.append(pcm)
                if not ch.active:
                    break
            return np.concatenate(chunks) if chunks else None
        except Exception as e:
            logger.error(f"RAW preview render failed: {e}")
            return None

    def stop_preview(self):
        with self.lock:
            self._preview.active = False
            self._preview.vu_level = 0.0
            self._preview.sample_data = None

    def is_preview_playing(self) -> bool:
        return self._preview.active and self._preview.sample_data is not None

    def get_preview_position(self) -> float:
        """Return current preview playback position in seconds.

        The preview PCM is always rendered at SAMPLE_RATE regardless of the
        POKEY target rate, so we always divide by SAMPLE_RATE.
        """
        pv = self._preview
        if not pv.active or pv.sample_data is None:
            return -1.0
        return pv.position / SAMPLE_RATE

    # === CHANNEL CONTROLS ===

    def toggle_channel(self, ch: int) -> bool:
        if 0 <= ch < MAX_CHANNELS:
            self.channels[ch].enabled = not self.channels[ch].enabled
            return self.channels[ch].enabled
        return True

    def set_channel_enabled(self, ch: int, enabled: bool):
        if 0 <= ch < MAX_CHANNELS:
            self.channels[ch].enabled = enabled

    def is_channel_enabled(self, ch: int) -> bool:
        return self.channels[ch].enabled if 0 <= ch < MAX_CHANNELS else True

    def set_speed(self, speed: int):
        with self.lock:
            self.speed = max(1, min(255, speed))

    def set_system(self, hz: int):
        with self.lock:
            self.hz = hz
            self.samples_per_tick = SAMPLE_RATE // hz

    # === QUERY ===

    def get_vu_levels(self):
        """Read VU levels and reset to 0 (consume pattern).
        
        The audio callback sets vu_level to the peak volume each frame.
        The UI reads it and resets to 0 so the next audio frame can set
        a fresh value. The UI-side gravity handles the visual decay.
        """
        levels = []
        for ch in self.channels[:MAX_CHANNELS]:
            levels.append(ch.vu_level)
            ch.vu_level = 0.0
        return levels

    def get_fft_snapshot(self):
        pos = self._fft_write_pos
        buf = self._fft_buf
        return np.roll(buf, -pos).copy()

    def is_playing(self) -> bool:
        return self.playing

    def is_pokey_mode(self) -> bool:
        """Always True — all playback uses POKEY emulation."""
        return POKEY_EMU_OK

    def get_mode(self) -> str:
        return self.mode

    def get_position(self) -> Tuple[int, int]:
        return (self.songline, self.row)

    # === OFFLINE RENDERING (WAV export — always through POKEY) ===

    def render_offline(self, progress_cb=None) -> Optional[np.ndarray]:
        """Render entire song to numpy array via POKEY emulation."""
        if not self.song or not self.song.songlines:
            return None
        if not POKEY_EMU_OK:
            return None

        try:
            player = VQPlayer(sample_rate=SAMPLE_RATE)
            if self._has_vq_data():
                player.load_from_tracker(
                    self.song, self._vq_state.result,
                    self._vq_state.settings)
                if (len(player.song.instruments) == 0 or
                        len(player.song.instruments) <
                        len(self.song.instruments)):
                    player = VQPlayer(sample_rate=SAMPLE_RATE)
                    player.load_song(self._build_live_song_data())
            else:
                player.load_song(self._build_live_song_data())
            player.start_playback(songline=0, row=0)

            chunks = []
            frame_count = 0
            max_frames = 30000  # ~10 minutes at 50fps

            while frame_count < max_frames:
                pcm = player.render_frame()
                if len(pcm) > 0:
                    chunks.append(pcm)
                frame_count += 1

                if progress_cb and frame_count % 50 == 0:
                    try:
                        progress_cb(player.seq_songline, player.seq_row,
                                    len(self.song.songlines))
                    except Exception:
                        pass

                if not player.playing and not any(
                        ch.active for ch in player.channels):
                    for _ in range(10):
                        pcm = player.render_frame()
                        if len(pcm) > 0:
                            chunks.append(pcm)
                    break

            if not chunks:
                return None
            return np.tanh(np.concatenate(chunks) * self.master_volume)
        except Exception as e:
            logger.error(f"POKEY offline render failed: {e}")
            return None
