"""POKEY VQ Tracker - Audio Engine"""
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

SAMPLE_RATE = 44100
BUFFER_SIZE = 512

@dataclass
class Channel:
    """Audio channel state."""
    active: bool = False
    note: int = 0
    volume: int = MAX_VOLUME
    sample_data: Optional[np.ndarray] = None
    sample_rate: int = SAMPLE_RATE
    position: float = 0.0
    pitch: float = 1.0
    enabled: bool = True  # Simplified: just enabled/disabled
    vu_level: float = 0.0  # VU meter level (0.0–1.0), set on trigger
    
    def reset(self):
        self.active = False
        self.sample_data = None
        self.position = 0.0


class AudioEngine:
    """Real-time audio playback engine.
    
    Uses a SINGLE OutputStream for all audio.  Never use sd.play() anywhere
    in the application — it creates a second OutputStream that kills this one
    on many audio backends (WASAPI exclusive, ALSA without PulseAudio, etc.).
    
    Audio paths:
      - Tracker channels 0-3: song playback + note preview
      - Preview channel: sample editor waveform, browser file preview
    """
    
    def __init__(self):
        self.running = False
        self.stream = None
        self.channels = [Channel() for _ in range(MAX_CHANNELS)]
        self.lock = threading.RLock()
        
        # Dedicated preview channel (sample editor waveform, browser preview)
        # Separate from tracker channels so preview doesn't clobber playback.
        self._preview = Channel()
        self._preview_src_rate = SAMPLE_RATE  # source sample rate for position tracking
        
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
        
        # Callbacks (called from main thread via process_callbacks)
        self.on_row: Optional[Callable[[int, int], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self._pending_callbacks: List[Tuple] = []
        
        self.master_volume = 0.8
    
    def start(self) -> bool:
        """Start audio stream."""
        logger.info(f"Starting audio engine, AUDIO_OK={AUDIO_OK}, running={self.running}")
        if not AUDIO_OK:
            logger.warning(f"Cannot start: AUDIO_OK={AUDIO_OK}")
            return False
        if self.running and self.stream and self.stream.active:
            return True  # Already running and healthy
        # Close any dead stream before creating a new one
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            self.running = False
        try:
            # Use stereo output for compatibility with most audio systems
            self.stream = sd.OutputStream(
                samplerate=SAMPLE_RATE, channels=2, dtype='float32',
                blocksize=BUFFER_SIZE, callback=self._audio_callback, latency='low'
            )
            self.stream.start()
            self.running = True
            logger.info("Audio stream started successfully (stereo)")
            return True
        except Exception as e:
            logger.error(f"Audio start error: {e}")
            return False
    
    def stop(self):
        """Stop audio stream."""
        logger.info("Stopping audio engine")
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
        logger.info("Audio engine stopped")
    
    def ensure_stream(self):
        """Check stream health and restart if dead.
        
        Call from main loop to recover from silent stream death
        (e.g. PortAudio device errors, OS audio reconfiguration,
        audio device disconnected/reconnected).
        """
        if not AUDIO_OK:
            return
        if self.running and self.stream:
            try:
                if self.stream.active:
                    return  # Healthy
            except Exception:
                pass
            # Stream died — restart
            logger.warning("Audio stream died — restarting")
            self.running = False
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        # (Re)start
        if not self.running:
            self.start()
    
    def _audio_callback(self, out: np.ndarray, frames: int, time_info, status):
        """Audio thread callback.
        
        Wrapped in try/except to prevent PortAudio from killing the
        stream on transient errors.  An unhandled exception here causes
        PortAudio to permanently stop invoking the callback.
        """
        try:
            with self.lock:
                output = np.zeros(frames, dtype=np.float32)
                
                if self.playing:
                    self._process_timing(frames)
                
                # Mix tracker channels (0-3)
                for ch in self.channels:
                    if not ch.active or ch.sample_data is None or not ch.enabled:
                        continue
                    ch_out = self._render_channel(ch, frames)
                    output += ch_out * (ch.volume / MAX_VOLUME)
                
                # Mix preview channel (sample editor / browser)
                pv = self._preview
                if pv.active and pv.sample_data is not None:
                    pv_out = self._render_channel(pv, frames)
                    output += pv_out * (pv.volume / MAX_VOLUME)
                
                # Output to both stereo channels
                mono_out = np.tanh(output * self.master_volume)
                out[:, 0] = mono_out  # Left
                out[:, 1] = mono_out  # Right
        except Exception as e:
            # Output silence on error — keeps the stream alive
            out[:] = 0
            logger.error(f"Audio callback error (stream kept alive): {e}")
    
    def _render_channel(self, ch: Channel, frames: int) -> np.ndarray:
        """Render channel with linear interpolation."""
        out = np.zeros(frames, dtype=np.float32)
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
    
    def _process_timing(self, frames: int):
        """Process playback timing."""
        self.sample_count += frames
        while self.sample_count >= self.samples_per_tick:
            self.sample_count -= self.samples_per_tick
            self.tick += 1
            if self.tick >= self.speed:
                self.tick = 0
                self._advance_row()
    
    def _advance_row(self):
        """Advance to next row."""
        # First increment the row
        self.row += 1
        
        max_len = max(self.lengths) if self.lengths else DEFAULT_LENGTH
        if self.row >= max_len:
            self.row = 0
            if self.mode == 'song':
                self.songline += 1
                if self.song and self.songline >= len(self.song.songlines):
                    self.songline = 0
                self._update_patterns()
        
        # Then play the new row
        self._play_current_row()
        
        if self.on_row:
            self._pending_callbacks.append((self.on_row, (self.songline, self.row)))
    
    def _play_current_row(self):
        """Trigger notes for current row."""
        if not self.song:
            return
        from constants import NOTE_OFF, VOL_CHANGE
        for ch_idx in range(MAX_CHANNELS):
            if ch_idx >= len(self.patterns):
                continue
            ptn = self.song.get_pattern(self.patterns[ch_idx])
            row = ptn.get_row_wrapped(self.row)
            if row.note == NOTE_OFF:
                # Note-off: silence the channel
                self.channels[ch_idx].active = False
                self.channels[ch_idx].vu_level = 0.0
            elif row.note == VOL_CHANGE:
                # Volume change only — no retrigger
                self.channels[ch_idx].volume = row.volume
                self.channels[ch_idx].vu_level = row.volume / MAX_VOLUME
            elif row.note > 0:
                inst = self.song.get_instrument(row.instrument)
                if inst and inst.is_loaded():
                    self._trigger_note(ch_idx, row.note, inst, row.volume)
    
    def _update_patterns(self):
        """Update pattern info and speed from current songline."""
        if not self.song or self.songline >= len(self.song.songlines):
            return
        sl = self.song.songlines[self.songline]
        self.patterns = sl.patterns.copy()
        self.lengths = [self.song.get_pattern(p).length for p in self.patterns]
        # Update speed from songline (clamp: corrupt files may have speed=0)
        self.speed = max(1, sl.speed)
    
    def _trigger_note(self, ch_idx: int, note: int, inst, volume: int):
        """Trigger a note on a channel."""
        logger.debug(f"_trigger_note: ch={ch_idx}, note={note}, vol={volume}, inst_loaded={inst.is_loaded() if inst else False}")
        if not (0 <= ch_idx < MAX_CHANNELS):
            logger.warning(f"Invalid channel index: {ch_idx}")
            return
        if not inst or not inst.is_loaded():
            logger.warning(f"Instrument not loaded")
            return
        ch = self.channels[ch_idx]
        ch.pitch = 2 ** ((note - inst.base_note) / 12.0) * inst.sample_rate / SAMPLE_RATE
        ch.active = True
        ch.note = note
        ch.volume = volume
        ch.vu_level = volume / MAX_VOLUME  # VU meter spike on trigger
        # Use processed audio if effects are applied
        from sample_editor.pipeline import get_playback_audio
        audio = get_playback_audio(inst)
        ch.sample_data = audio if audio is not None else inst.sample_data
        ch.sample_rate = inst.sample_rate
        ch.position = 0.0
        logger.debug(f"Note triggered: ch={ch_idx}, pitch={ch.pitch:.3f}, sample_len={len(ch.sample_data)}")
    
    def _stop_all_channels(self):
        """Stop all channels."""
        for ch in self.channels:
            ch.reset()
    
    def process_callbacks(self):
        """Process pending callbacks (call from main thread)."""
        with self.lock:
            callbacks = self._pending_callbacks.copy()
            self._pending_callbacks.clear()
        for fn, args in callbacks:
            try:
                fn(*args)
            except Exception as e:
                logger.warning(f"Callback error in {fn.__name__}: {e}")
    
    # === PUBLIC API ===
    
    def set_song(self, song):
        """Set current song."""
        with self.lock:
            self.song = song
            if song:
                # Use speed from first songline (if available)
                if song.songlines:
                    self.speed = song.songlines[0].speed
                else:
                    self.speed = DEFAULT_SPEED
                self.hz = song.system
                self.samples_per_tick = SAMPLE_RATE // self.hz
    
    def play_from(self, songline: int, row: int):
        """Play from position."""
        with self.lock:
            if not self.song:
                return
            self._stop_all_channels()
            self.mode = 'pattern'
            self.songline = songline
            self.row = row
            self.tick = 0
            self.sample_count = 0
            self._update_patterns()
            self._play_current_row()  # Play first row immediately
            self.playing = True
            # Fire callback for initial position
            if self.on_row:
                self._pending_callbacks.append((self.on_row, (self.songline, self.row)))
    
    def play_pattern(self, songline: int = 0):
        """Play current pattern."""
        self.play_from(songline, 0)
    
    def play_song(self, from_start: bool = True, songline: int = 0, row: int = 0):
        """Play song.
        
        Args:
            from_start: If True, start from beginning (songline 0, row 0)
            songline: Starting songline (ignored if from_start=True)
            row: Starting row within songline (ignored if from_start=True)
        """
        with self.lock:
            if not self.song:
                return
            self._stop_all_channels()
            self.mode = 'song'
            self.songline = 0 if from_start else songline
            self.tick = 0
            self.sample_count = 0
            self._update_patterns()
            
            # Set starting row (with bounds check)
            if from_start:
                self.row = 0
            else:
                # Clamp row to valid range for current songline patterns
                max_len = max(self.lengths) if self.lengths else DEFAULT_LENGTH
                self.row = min(row, max_len - 1) if max_len > 0 else 0
            
            self._play_current_row()  # Play first row immediately
            self.playing = True
            # Fire callback for initial position
            if self.on_row:
                self._pending_callbacks.append((self.on_row, (self.songline, self.row)))
    
    def stop_playback(self):
        """Stop playback."""
        with self.lock:
            was_playing = self.playing
            self.playing = False
            self.mode = 'stop'
            self._stop_all_channels()
            for ch in self.channels:
                ch.vu_level = 0.0
            if was_playing and self.on_stop:
                self._pending_callbacks.append((self.on_stop, ()))
    
    # === PREVIEW (sample editor / browser — routed through main stream) ===
    
    def play_preview(self, audio_data: np.ndarray, sample_rate: int):
        """Play raw audio through the preview channel.
        
        Used by sample editor (waveform playback) and file browser
        (audio file preview).  Routed through the single OutputStream
        so it cannot kill the main audio stream.
        
        NEVER use sd.play() anywhere in this application.
        
        Args:
            audio_data: float32 mono array, values in [-1, 1]
            sample_rate: source sample rate (e.g. 44100, 15720)
        """
        if sample_rate <= 0:
            logger.warning(f"play_preview: invalid sample_rate={sample_rate}")
            return
        with self.lock:
            pv = self._preview
            # Ensure float32 mono
            data = np.asarray(audio_data, dtype=np.float32)
            if data.ndim > 1:
                data = data.mean(axis=1)
            if len(data) == 0:
                return
            pv.sample_data = data
            pv.sample_rate = sample_rate
            pv.pitch = sample_rate / SAMPLE_RATE
            pv.position = 0.0
            pv.volume = MAX_VOLUME
            pv.active = True
            pv.vu_level = 0.8
            self._preview_src_rate = sample_rate
    
    def stop_preview(self):
        """Stop preview channel playback."""
        with self.lock:
            self._preview.active = False
            self._preview.vu_level = 0.0
            self._preview.sample_data = None
    
    def is_preview_playing(self) -> bool:
        """Check if preview channel is actively playing."""
        return self._preview.active and self._preview.sample_data is not None
    
    def get_preview_position(self) -> float:
        """Get current preview playback position in seconds.
        
        Returns elapsed time relative to start of the audio data.
        """
        pv = self._preview
        if not pv.active or pv.sample_data is None:
            return -1.0
        return pv.position / self._preview_src_rate
    
    def get_vu_levels(self):
        """Get current VU levels for all channels. Thread-safe."""
        return [ch.vu_level for ch in self.channels[:MAX_CHANNELS]]
    
    def is_playing(self) -> bool:
        return self.playing
    
    def get_mode(self) -> str:
        return self.mode
    
    def get_position(self) -> Tuple[int, int]:
        return (self.songline, self.row)
    
    def preview_note(self, ch_idx: int, note: int, inst, volume: int = MAX_VOLUME):
        """Preview a single note."""
        logger.debug(f"preview_note called: ch={ch_idx}, note={note}, vol={volume}, running={self.running}")
        with self.lock:
            if inst and inst.is_loaded():
                logger.debug(f"Calling _trigger_note")
                self._trigger_note(ch_idx, note, inst, volume)
            else:
                logger.warning(f"preview_note: instrument not loaded or None")
    
    def preview_row(self, song, songline: int, row: int):
        """Preview all notes in a row."""
        with self.lock:
            if not song or songline >= len(song.songlines):
                return
            from constants import NOTE_OFF, VOL_CHANGE
            sl = song.songlines[songline]
            for ch_idx in range(MAX_CHANNELS):
                ptn = song.get_pattern(sl.patterns[ch_idx])
                r = ptn.get_row_wrapped(row)
                if r.note == NOTE_OFF:
                    self.channels[ch_idx].active = False
                    self.channels[ch_idx].vu_level = 0.0
                elif r.note == VOL_CHANGE:
                    self.channels[ch_idx].volume = r.volume
                    self.channels[ch_idx].vu_level = r.volume / MAX_VOLUME
                elif r.note > 0:
                    inst = song.get_instrument(r.instrument)
                    if inst and inst.is_loaded():
                        self._trigger_note(ch_idx, r.note, inst, r.volume)
    
    def toggle_channel(self, ch: int) -> bool:
        """Toggle channel enabled state."""
        if 0 <= ch < MAX_CHANNELS:
            self.channels[ch].enabled = not self.channels[ch].enabled
            return self.channels[ch].enabled
        return True
    
    def set_channel_enabled(self, ch: int, enabled: bool):
        """Set channel enabled state."""
        if 0 <= ch < MAX_CHANNELS:
            self.channels[ch].enabled = enabled
    
    def is_channel_enabled(self, ch: int) -> bool:
        """Check if channel is enabled."""
        return self.channels[ch].enabled if 0 <= ch < MAX_CHANNELS else True
    
    def set_speed(self, speed: int):
        with self.lock:
            self.speed = max(1, min(255, speed))
    
    def set_system(self, hz: int):
        with self.lock:
            self.hz = hz
            self.samples_per_tick = SAMPLE_RATE // hz

    # === OFFLINE RENDERING (WAV export) ===

    def _save_channel_state(self):
        """Snapshot all per-channel fields for later restore."""
        return [{
            'active': ch.active, 'note': ch.note, 'volume': ch.volume,
            'sample_data': ch.sample_data, 'sample_rate': ch.sample_rate,
            'position': ch.position, 'pitch': ch.pitch,
            'enabled': ch.enabled, 'vu_level': ch.vu_level,
        } for ch in self.channels]

    def _restore_channel_state(self, saved):
        """Restore per-channel fields from a snapshot."""
        for i, s in enumerate(saved):
            if i < len(self.channels):
                ch = self.channels[i]
                for k, v in s.items():
                    setattr(ch, k, v)

    def render_offline(self, progress_cb=None) -> Optional[np.ndarray]:
        """Render the entire song to a numpy array (mono float32, 44100 Hz).

        Plays through all songlines once (stops when songline wraps to 0).
        Returns mono float32 array at SAMPLE_RATE, or None on error.

        The audio stream is stopped during rendering so the PortAudio
        callback thread is not blocked.  The stream is restarted afterwards.

        Args:
            progress_cb: Optional callback(songline, row, total_songlines)
                         called after each row for progress display.
        """
        if not self.song or not self.song.songlines:
            return None

        total_songlines = len(self.song.songlines)

        # --- Quiesce the real-time audio path ---
        was_running = self.running
        self.stop_playback()          # playing=False, channels silent
        if was_running:
            self.stop()               # close stream — no callback runs

        # Save full state (safe: no concurrent access)
        saved_ch = self._save_channel_state()
        saved_engine = (self.mode, self.songline, self.row,
                        self.tick, self.sample_count, self.speed,
                        self.patterns[:] if self.patterns else [],
                        self.lengths[:] if self.lengths else [])

        try:
            # Initialise for offline rendering
            self._stop_all_channels()
            self.mode = 'song'
            self.songline = 0
            self.row = 0
            self.tick = 0
            self.sample_count = 0
            self.playing = True
            self._update_patterns()
            self._play_current_row()

            for ch in self.channels:
                ch.enabled = True

            chunks = []
            max_samples = SAMPLE_RATE * 600   # 10-minute hard cap
            total_samples = 0

            while total_samples < max_samples:
                buf_size = min(1024, self.samples_per_tick)
                output = np.zeros(buf_size, dtype=np.float32)

                # --- Timing: advance rows exactly as the real-time path ---
                remaining = buf_size
                while remaining > 0:
                    tick_remaining = self.samples_per_tick - self.sample_count
                    process = min(remaining, tick_remaining)
                    self.sample_count += process
                    remaining -= process

                    if self.sample_count >= self.samples_per_tick:
                        self.sample_count = 0
                        self.tick += 1
                        if self.tick >= self.speed:
                            self.tick = 0
                            self.row += 1
                            max_len = (max(self.lengths)
                                       if self.lengths else DEFAULT_LENGTH)
                            if self.row >= max_len:
                                self.row = 0
                                self.songline += 1
                                if self.songline >= total_songlines:
                                    self.playing = False
                                    break
                                self._update_patterns()
                            self._play_current_row()

                            if progress_cb:
                                try:
                                    progress_cb(self.songline, self.row,
                                                total_songlines)
                                except Exception:
                                    pass

                # --- Render this buffer (including the final one after
                #     the song ends — channels still ring out) ---
                for ch in self.channels:
                    if not ch.active or ch.sample_data is None:
                        continue
                    ch_out = self._render_channel(ch, buf_size)
                    output += ch_out * (ch.volume / MAX_VOLUME)

                chunks.append(np.tanh(output * self.master_volume))
                total_samples += buf_size

                if not self.playing:
                    break                 # exit AFTER rendering final buffer

            if not chunks:
                return None
            return np.concatenate(chunks)

        finally:
            # --- Restore engine + channel state ---
            (self.mode, self.songline, self.row,
             self.tick, self.sample_count, self.speed,
             self.patterns, self.lengths) = saved_engine
            self.playing = False          # always leave stopped
            self._restore_channel_state(saved_ch)

            # Restart audio stream if it was running
            if was_running:
                self.start()
