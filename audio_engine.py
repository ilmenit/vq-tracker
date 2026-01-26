"""
Atari Sample Tracker - Audio Engine
Real-time playback with pitch control and mixing.
"""

import threading
import numpy as np
from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass

try:
    import sounddevice as sd
    AUDIO_OK = True
except ImportError:
    AUDIO_OK = False
    print("Note: sounddevice not installed. Audio disabled.")

from constants import MAX_CHANNELS, MAX_VOLUME, PAL_HZ

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
    muted: bool = False
    solo: bool = False
    
    def reset(self):
        self.active = False
        self.sample_data = None
        self.position = 0.0


class AudioEngine:
    """Audio playback engine."""
    
    def __init__(self):
        self.running = False
        self.stream = None
        self.channels = [Channel() for _ in range(MAX_CHANNELS)]
        
        # Playback state
        self.playing = False
        self.mode = 'stop'  # 'stop', 'pattern', 'song'
        self.song = None
        
        # Position
        self.songline = 0
        self.row = 0
        self.tick = 0
        self.speed = 6
        self.hz = PAL_HZ
        
        self.samples_per_tick = SAMPLE_RATE // PAL_HZ
        self.sample_count = 0
        
        # Pattern info
        self.patterns = [0, 1, 2]
        self.lengths = [64, 64, 64]
        
        # Callbacks
        self.on_row: Optional[Callable[[int, int], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        
        self.lock = threading.RLock()
        self.master_vol = 0.8
        self._callbacks: List[Tuple] = []
    
    def start(self) -> bool:
        if not AUDIO_OK or self.running:
            return self.running
        try:
            self.stream = sd.OutputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype='float32',
                blocksize=BUFFER_SIZE, callback=self._callback, latency='low'
            )
            self.stream.start()
            self.running = True
            return True
        except Exception as e:
            print(f"Audio error: {e}")
            return False
    
    def stop(self):
        self.stop_playback()
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
        self.running = False
    
    def _callback(self, out: np.ndarray, frames: int, time_info, status):
        with self.lock:
            output = np.zeros(frames, dtype=np.float32)
            
            if self.playing:
                self._process_timing(frames)
            
            any_solo = any(c.solo for c in self.channels)
            
            for ch in self.channels:
                if not ch.active or ch.sample_data is None or ch.muted:
                    continue
                if any_solo and not ch.solo:
                    continue
                
                ch_out = self._render_channel(ch, frames)
                output += ch_out * (ch.volume / MAX_VOLUME)
            
            output = np.tanh(output * self.master_vol)
            out[:, 0] = output
    
    def _render_channel(self, ch: Channel, frames: int) -> np.ndarray:
        out = np.zeros(frames, dtype=np.float32)
        length = len(ch.sample_data)
        
        for i in range(frames):
            pos = int(ch.position)
            if pos >= length - 1:
                ch.active = False
                break
            frac = ch.position - pos
            out[i] = ch.sample_data[pos] * (1 - frac) + ch.sample_data[min(pos + 1, length - 1)] * frac
            ch.position += ch.pitch
        
        return out
    
    def _process_timing(self, frames: int):
        self.sample_count += frames
        while self.sample_count >= self.samples_per_tick:
            self.sample_count -= self.samples_per_tick
            self.tick += 1
            if self.tick >= self.speed:
                self.tick = 0
                self._advance_row()
    
    def _advance_row(self):
        self._play_row()
        self.row += 1
        
        max_len = max(self.lengths) if self.lengths else 64
        if self.row >= max_len:
            self.row = 0
            if self.mode == 'song':
                self.songline += 1
                if self.song and self.songline >= len(self.song.songlines):
                    self.songline = 0
                self._update_patterns()
        
        if self.on_row:
            self._callbacks.append((self.on_row, (self.songline, self.row)))
    
    def _play_row(self):
        if not self.song:
            return
        for ch_idx in range(MAX_CHANNELS):
            if ch_idx >= len(self.patterns):
                continue
            ptn = self.song.get_pattern(self.patterns[ch_idx])
            row = ptn.get_row(self.row % ptn.length)
            if row.note > 0:
                inst = self.song.get_instrument(row.instrument)
                if inst and inst.is_loaded():
                    self._trigger(ch_idx, row.note, inst, row.volume)
    
    def _update_patterns(self):
        if not self.song or self.songline >= len(self.song.songlines):
            return
        sl = self.song.songlines[self.songline]
        self.patterns = sl.patterns.copy()
        self.lengths = [self.song.get_pattern(p).length for p in self.patterns]
    
    def _trigger(self, ch_idx: int, note: int, inst, volume: int):
        if not (0 <= ch_idx < MAX_CHANNELS) or not inst.is_loaded():
            return
        ch = self.channels[ch_idx]
        pitch = 2 ** ((note - inst.base_note) / 12.0) * inst.sample_rate / SAMPLE_RATE
        ch.active = True
        ch.note = note
        ch.volume = volume
        ch.sample_data = inst.sample_data
        ch.position = 0.0
        ch.pitch = pitch
    
    def process_callbacks(self):
        """Call from main thread."""
        with self.lock:
            cbs = self._callbacks.copy()
            self._callbacks.clear()
        for fn, args in cbs:
            try:
                fn(*args)
            except:
                pass
    
    # Public API
    def set_song(self, song):
        with self.lock:
            self.song = song
            if song:
                self.speed = song.speed
                self.hz = song.system
                self.samples_per_tick = SAMPLE_RATE // self.hz
    
    def play_from(self, songline: int, row: int):
        with self.lock:
            if not self.song:
                return
            self._stop_channels()
            self.mode = 'pattern'
            self.songline = songline
            self.row = row
            self.tick = 0
            self.sample_count = 0
            self._update_patterns()
            self.playing = True
    
    def play_pattern(self, songline: int = 0):
        self.play_from(songline, 0)
    
    def play_song(self, from_start: bool = True, songline: int = 0):
        with self.lock:
            if not self.song:
                return
            self._stop_channels()
            self.mode = 'song'
            self.songline = 0 if from_start else songline
            self.row = 0
            self.tick = 0
            self.sample_count = 0
            self._update_patterns()
            self.playing = True
    
    def stop_playback(self):
        with self.lock:
            was = self.playing
            self.playing = False
            self.mode = 'stop'
            self._stop_channels()
            if was and self.on_stop:
                self._callbacks.append((self.on_stop, ()))
    
    def _stop_channels(self):
        for ch in self.channels:
            ch.reset()
    
    def is_playing(self) -> bool:
        return self.playing
    
    def get_mode(self) -> str:
        return self.mode
    
    def get_position(self) -> Tuple[int, int]:
        return (self.songline, self.row)
    
    def preview_note(self, ch_idx: int, note: int, inst, vol: int = MAX_VOLUME):
        with self.lock:
            if inst and inst.is_loaded():
                self._trigger(ch_idx, note, inst, vol)
    
    def preview_row(self, song, songline: int, row: int):
        with self.lock:
            if not song or songline >= len(song.songlines):
                return
            sl = song.songlines[songline]
            for ch_idx in range(MAX_CHANNELS):
                ptn = song.get_pattern(sl.patterns[ch_idx])
                if row < ptn.length:
                    r = ptn.get_row(row)
                    if r.note > 0:
                        inst = song.get_instrument(r.instrument)
                        if inst and inst.is_loaded():
                            self._trigger(ch_idx, r.note, inst, r.volume)
    
    def toggle_mute(self, ch: int) -> bool:
        if 0 <= ch < MAX_CHANNELS:
            self.channels[ch].muted = not self.channels[ch].muted
            return self.channels[ch].muted
        return False
    
    def toggle_solo(self, ch: int) -> bool:
        if 0 <= ch < MAX_CHANNELS:
            self.channels[ch].solo = not self.channels[ch].solo
            return self.channels[ch].solo
        return False
    
    def is_muted(self, ch: int) -> bool:
        return self.channels[ch].muted if 0 <= ch < MAX_CHANNELS else False
    
    def is_solo(self, ch: int) -> bool:
        return self.channels[ch].solo if 0 <= ch < MAX_CHANNELS else False
    
    def set_speed(self, speed: int):
        with self.lock:
            self.speed = max(1, min(255, speed))
    
    def set_system(self, hz: int):
        with self.lock:
            self.hz = hz
            self.samples_per_tick = SAMPLE_RATE // hz
