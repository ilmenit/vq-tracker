"""POKEY VQ Tracker - Data Model"""
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np
from constants import (MAX_CHANNELS, MAX_PATTERNS, MAX_ROWS, MAX_INSTRUMENTS,
                       MAX_SONGLINES, MAX_VOLUME, DEFAULT_SPEED, DEFAULT_LENGTH,
                       PAL_HZ, MAX_NOTES)

@dataclass
class Row:
    """Single row in a pattern."""
    note: int = 0
    instrument: int = 0
    volume: int = MAX_VOLUME
    
    def clear(self):
        self.note = self.instrument = 0
        self.volume = MAX_VOLUME
    
    def copy(self) -> 'Row':
        return Row(self.note, self.instrument, self.volume)
    
    def to_dict(self) -> dict:
        return {'n': self.note, 'i': self.instrument, 'v': self.volume}
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Row':
        note = d.get('n', d.get('note', 0))
        inst = d.get('i', d.get('instrument', 0))
        vol = d.get('v', d.get('volume', MAX_VOLUME))
        # Clamp to valid ranges
        note = max(0, min(MAX_NOTES, note))
        inst = max(0, min(MAX_INSTRUMENTS - 1, inst))  # 0-127
        vol = max(0, min(MAX_VOLUME, vol))
        return cls(note, inst, vol)

@dataclass
class Pattern:
    """Sequence of rows for one channel."""
    length: int = DEFAULT_LENGTH
    rows: List[Row] = field(default_factory=list)
    
    def __post_init__(self):
        while len(self.rows) < self.length:
            self.rows.append(Row())
        self.rows = self.rows[:self.length]
    
    def get_row(self, idx: int) -> Row:
        return self.rows[idx] if 0 <= idx < len(self.rows) else Row()
    
    def get_row_wrapped(self, idx: int) -> Row:
        """Get row with wrap-around for pattern repetition."""
        return self.rows[idx % self.length] if self.length > 0 else Row()
    
    def set_length(self, length: int):
        length = max(1, min(MAX_ROWS, length))
        while len(self.rows) < length:
            self.rows.append(Row())
        self.rows = self.rows[:length]
        self.length = length
    
    def insert_row(self, idx: int):
        if 0 <= idx <= self.length:
            self.rows.insert(idx, Row())
            self.rows.pop()
    
    def delete_row(self, idx: int):
        if 0 <= idx < self.length:
            self.rows.pop(idx)
            self.rows.append(Row())
    
    def transpose(self, semitones: int):
        for row in self.rows:
            if row.note > 0:
                new_note = row.note + semitones
                if 1 <= new_note <= MAX_NOTES:
                    row.note = new_note
    
    def clear(self):
        for row in self.rows:
            row.clear()
    
    def copy(self) -> 'Pattern':
        p = Pattern(length=self.length)
        p.rows = [r.copy() for r in self.rows]
        return p
    
    def to_dict(self) -> dict:
        return {'len': self.length, 'rows': [r.to_dict() for r in self.rows]}
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Pattern':
        p = cls(length=d.get('len', d.get('length', DEFAULT_LENGTH)))
        p.rows = [Row.from_dict(r) for r in d.get('rows', [])]
        while len(p.rows) < p.length:
            p.rows.append(Row())
        return p

@dataclass
class Instrument:
    """Sample-based instrument.
    
    Attributes:
        name: Display name for the instrument
        sample_path: Path to loaded sample file
        original_sample_path: Original WAV path before VQ conversion
        sample_data: Audio samples as numpy array (float32, normalized)
        sample_rate: Sample rate of loaded audio (Hz)
        base_note: Note number where sample plays at original pitch
                   Default is 1 (C-1) to match Atari pitch table where:
                   - Index 0 (C-1) = 1.0x playback speed
                   - Index 12 (C-2) = 2.0x playback speed
                   - Index 24 (C-3) = 4.0x playback speed
    """
    name: str = "New"
    sample_path: str = ""
    original_sample_path: str = ""
    sample_data: Optional[np.ndarray] = None
    sample_rate: int = 44100
    base_note: int = 1  # C-1 = 1.0x pitch (matches Atari pitch table index 0)
    
    def is_loaded(self) -> bool:
        return self.sample_data is not None and len(self.sample_data) > 0
    
    def duration(self) -> float:
        return len(self.sample_data) / self.sample_rate if self.is_loaded() else 0.0
    
    def get_original_path(self) -> str:
        """Get original external sample path (for reference/info only).
        
        WARNING: Do NOT use this for conversion - use sample_path instead.
        original_sample_path points to the user's original file which may not exist.
        sample_path points to the working copy in .tmp/samples/ which always exists.
        """
        return self.original_sample_path or self.sample_path
    
    def to_dict(self) -> dict:
        return {
            'name': self.name, 
            'path': self.sample_path, 
            # Don't fall back to sample_path - keep original_path separate
            'original_path': self.original_sample_path,
            'base': self.base_note
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Instrument':
        inst = cls(name=d.get('name', 'New'),
                   sample_path=d.get('path', d.get('sample', '')),
                   base_note=d.get('base', d.get('base_note', 1)))
        # Don't fall back to sample_path - original_path may legitimately be empty
        inst.original_sample_path = d.get('original_path', '')
        return inst

@dataclass
class Songline:
    """One row in song arrangement."""
    patterns: List[int] = field(default_factory=lambda: [0, 0, 0])
    speed: int = DEFAULT_SPEED  # Speed for this songline (VBLANKs per row)
    
    def __post_init__(self):
        while len(self.patterns) < MAX_CHANNELS:
            self.patterns.append(0)
        self.patterns = self.patterns[:MAX_CHANNELS]
    
    def copy(self) -> 'Songline':
        return Songline(patterns=self.patterns.copy(), speed=self.speed)

@dataclass
class Song:
    """Complete song container."""
    title: str = "Untitled"
    author: str = ""
    speed: int = DEFAULT_SPEED
    system: int = PAL_HZ
    volume_control: bool = False  # Enable volume control in export (requires lower sample rate)
    screen_control: bool = False  # Enable display during playback (costs ~15% CPU cycles)
    keyboard_control: bool = False  # Enable keyboard stop/restart during playback
    songlines: List[Songline] = field(default_factory=list)
    patterns: List[Pattern] = field(default_factory=list)
    instruments: List[Instrument] = field(default_factory=list)
    modified: bool = False
    file_path: str = ""
    
    def __post_init__(self):
        if not self.songlines:
            self.songlines = [Songline(patterns=[0, 1, 2])]
        if not self.patterns:
            self.patterns = [Pattern() for _ in range(3)]
    
    def reset(self):
        self.title = "Untitled"
        self.author = ""
        self.speed = DEFAULT_SPEED
        self.system = PAL_HZ
        self.volume_control = False
        self.screen_control = False
        self.keyboard_control = False
        self.songlines = [Songline(patterns=[0, 1, 2])]
        self.patterns = [Pattern() for _ in range(3)]
        self.instruments = []
        self.modified = False
        self.file_path = ""
    
    def get_pattern(self, idx: int) -> Pattern:
        return self.patterns[idx] if 0 <= idx < len(self.patterns) else Pattern()
    
    def get_instrument(self, idx: int) -> Optional[Instrument]:
        return self.instruments[idx] if 0 <= idx < len(self.instruments) else None
    
    def max_pattern_length(self, songline_idx: int) -> int:
        """Get max pattern length for a songline (for repetition display)."""
        if 0 <= songline_idx < len(self.songlines):
            sl = self.songlines[songline_idx]
            return max(self.get_pattern(p).length for p in sl.patterns)
        return DEFAULT_LENGTH
    
    # === SONGLINE OPERATIONS ===
    def add_songline(self, after: int = -1) -> int:
        """Add new songline with default patterns (all pattern 0)."""
        if len(self.songlines) >= MAX_SONGLINES:
            return -1
        after = after if after >= 0 else len(self.songlines) - 1
        # Create new songline with default patterns (pattern 0 for all channels)
        new = Songline()
        self.songlines.insert(after + 1, new)
        self.modified = True
        return after + 1
    
    def delete_songline(self, idx: int) -> bool:
        if len(self.songlines) <= 1 or not (0 <= idx < len(self.songlines)):
            return False
        self.songlines.pop(idx)
        self.modified = True
        return True
    
    def clone_songline(self, idx: int) -> int:
        if len(self.songlines) >= MAX_SONGLINES or not (0 <= idx < len(self.songlines)):
            return -1
        self.songlines.insert(idx + 1, self.songlines[idx].copy())
        self.modified = True
        return idx + 1
    
    # === PATTERN OPERATIONS ===
    def add_pattern(self) -> int:
        if len(self.patterns) >= MAX_PATTERNS:
            return -1
        self.patterns.append(Pattern())
        self.modified = True
        return len(self.patterns) - 1
    
    def clone_pattern(self, idx: int) -> int:
        if len(self.patterns) >= MAX_PATTERNS or not (0 <= idx < len(self.patterns)):
            return -1
        self.patterns.append(self.patterns[idx].copy())
        self.modified = True
        return len(self.patterns) - 1
    
    def delete_pattern(self, idx: int) -> bool:
        if len(self.patterns) <= 1:
            return False
        if any(idx in sl.patterns for sl in self.songlines):
            return False
        if 0 <= idx < len(self.patterns):
            self.patterns.pop(idx)
            for sl in self.songlines:
                for i, p in enumerate(sl.patterns):
                    if p > idx:
                        sl.patterns[i] = p - 1
            self.modified = True
            return True
        return False
    
    def pattern_in_use(self, idx: int) -> bool:
        return any(idx in sl.patterns for sl in self.songlines)
    
    # === INSTRUMENT OPERATIONS ===
    def add_instrument(self, name: str = "New") -> int:
        if len(self.instruments) >= MAX_INSTRUMENTS:
            return -1
        self.instruments.append(Instrument(name=name))
        self.modified = True
        return len(self.instruments) - 1
    
    def remove_instrument(self, idx: int) -> bool:
        if 0 <= idx < len(self.instruments):
            self.instruments.pop(idx)
            self.modified = True
            return True
        return False
    
    # === SERIALIZATION ===
    def to_dict(self) -> dict:
        return {
            'version': 4,
            'meta': {
                'title': self.title, 'author': self.author,
                'system': self.system,
                'volume_control': self.volume_control,
                'screen_control': self.screen_control,
                'keyboard_control': self.keyboard_control
            },
            'songlines': [{'patterns': sl.patterns, 'speed': sl.speed} for sl in self.songlines],
            'patterns': [p.to_dict() for p in self.patterns],
            'instruments': [i.to_dict() for i in self.instruments]
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Song':
        meta = d.get('meta', d.get('metadata', {}))
        
        # Handle screen_control with backward compatibility for old 'blank_screen'
        # Old: blank_screen=True meant blank the screen
        # New: screen_control=True means show the screen
        # So: screen_control = not blank_screen (inverted)
        if 'screen_control' in meta:
            screen_ctrl = meta.get('screen_control', False)
        elif 'blank_screen' in meta:
            # Old format: invert the value
            screen_ctrl = not meta.get('blank_screen', False)
        else:
            screen_ctrl = False
        
        song = cls(
            title=meta.get('title', 'Untitled'),
            author=meta.get('author', ''),
            speed=meta.get('speed', DEFAULT_SPEED),  # Legacy global speed
            system=meta.get('system', PAL_HZ),
            volume_control=meta.get('volume_control', False),
            screen_control=screen_ctrl,
            keyboard_control=meta.get('keyboard_control', False)
        )
        
        # Handle songlines - both old format (list of pattern arrays) and new format (list of dicts with speed)
        raw_songlines = d.get('songlines', [[0, 1, 2]])
        song.songlines = []
        for sl in raw_songlines:
            if isinstance(sl, dict):
                # New format with speed
                song.songlines.append(Songline(
                    patterns=list(sl.get('patterns', [0, 0, 0])),
                    speed=sl.get('speed', DEFAULT_SPEED)
                ))
            else:
                # Old format - just pattern array, use default or legacy global speed
                song.songlines.append(Songline(
                    patterns=list(sl),
                    speed=meta.get('speed', DEFAULT_SPEED)
                ))
        
        song.patterns = [Pattern.from_dict(p) 
                         for p in d.get('patterns', d.get('ptn', []))]
        song.instruments = [Instrument.from_dict(i) 
                            for i in d.get('instruments', d.get('inst', []))]
        while len(song.patterns) < 3:
            song.patterns.append(Pattern())
        return song
