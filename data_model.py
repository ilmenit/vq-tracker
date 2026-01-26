"""
Atari Sample Tracker - Data Model
Core data structures: Song, Pattern, Row, Instrument
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import numpy as np

from constants import (
    MAX_CHANNELS, MAX_PATTERNS, MAX_ROWS, MAX_INSTRUMENTS,
    MAX_SONGLINES, MAX_VOLUME, DEFAULT_SPEED, DEFAULT_LENGTH,
    PAL_HZ, MAX_NOTES
)

# =============================================================================
# PATTERN ROW
# =============================================================================

@dataclass
class Row:
    """Single row in a pattern."""
    note: int = 0           # 0=empty, 1-48=note
    instrument: int = 0     # 0-127
    volume: int = MAX_VOLUME  # 0-15
    
    def clear(self):
        self.note = 0
        self.instrument = 0
        self.volume = MAX_VOLUME
    
    def copy(self) -> 'Row':
        return Row(self.note, self.instrument, self.volume)
    
    def to_dict(self) -> dict:
        return {'note': self.note, 'instrument': self.instrument, 'volume': self.volume}
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Row':
        return cls(d.get('note', 0), d.get('instrument', 0), d.get('volume', MAX_VOLUME))

# =============================================================================
# PATTERN
# =============================================================================

@dataclass
class Pattern:
    """Sequence of rows for one channel."""
    length: int = DEFAULT_LENGTH
    rows: List[Row] = field(default_factory=list)
    
    def __post_init__(self):
        while len(self.rows) < self.length:
            self.rows.append(Row())
        if len(self.rows) > self.length:
            self.rows = self.rows[:self.length]
    
    def get_row(self, idx: int) -> Row:
        if 0 <= idx < len(self.rows):
            return self.rows[idx]
        return Row()
    
    def set_length(self, length: int):
        length = max(1, min(MAX_ROWS, length))
        while len(self.rows) < length:
            self.rows.append(Row())
        if len(self.rows) > length:
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
                new = row.note + semitones
                if 1 <= new <= MAX_NOTES:
                    row.note = new
    
    def clear(self):
        for row in self.rows:
            row.clear()
    
    def copy(self) -> 'Pattern':
        p = Pattern(length=self.length)
        p.rows = [r.copy() for r in self.rows]
        return p
    
    def to_dict(self) -> dict:
        return {'length': self.length, 'rows': [r.to_dict() for r in self.rows]}
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Pattern':
        p = cls(length=d.get('length', DEFAULT_LENGTH))
        p.rows = [Row.from_dict(r) for r in d.get('rows', [])]
        while len(p.rows) < p.length:
            p.rows.append(Row())
        return p

# =============================================================================
# INSTRUMENT
# =============================================================================

@dataclass
class Instrument:
    """Sample-based instrument."""
    name: str = "New Instrument"
    sample_path: str = ""
    sample_data: Optional[np.ndarray] = None
    sample_rate: int = 44100
    base_note: int = 25  # C2
    
    def is_loaded(self) -> bool:
        return self.sample_data is not None and len(self.sample_data) > 0
    
    def duration(self) -> float:
        return len(self.sample_data) / self.sample_rate if self.is_loaded() else 0.0
    
    def to_dict(self) -> dict:
        return {'name': self.name, 'sample': self.sample_path, 'base_note': self.base_note}
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Instrument':
        return cls(name=d.get('name', 'New'), sample_path=d.get('sample', ''),
                   base_note=d.get('base_note', 25))

# =============================================================================
# SONGLINE
# =============================================================================

@dataclass
class Songline:
    """One row in song arrangement."""
    patterns: List[int] = field(default_factory=lambda: [0, 0, 0])
    
    def __post_init__(self):
        while len(self.patterns) < MAX_CHANNELS:
            self.patterns.append(0)
        self.patterns = self.patterns[:MAX_CHANNELS]
    
    def copy(self) -> 'Songline':
        return Songline(patterns=self.patterns.copy())

# =============================================================================
# SONG
# =============================================================================

@dataclass
class Song:
    """Complete song container."""
    title: str = "Untitled"
    author: str = ""
    speed: int = DEFAULT_SPEED
    system: int = PAL_HZ
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
        """Reset to empty state."""
        self.title = "Untitled"
        self.author = ""
        self.speed = DEFAULT_SPEED
        self.system = PAL_HZ
        self.songlines = [Songline(patterns=[0, 1, 2])]
        self.patterns = [Pattern() for _ in range(3)]
        self.instruments = []
        self.modified = False
        self.file_path = ""
    
    def get_pattern(self, idx: int) -> Pattern:
        return self.patterns[idx] if 0 <= idx < len(self.patterns) else Pattern()
    
    def get_instrument(self, idx: int) -> Optional[Instrument]:
        return self.instruments[idx] if 0 <= idx < len(self.instruments) else None
    
    # Songline operations
    def add_songline(self, after: int = -1) -> int:
        if len(self.songlines) >= MAX_SONGLINES:
            return -1
        after = after if after >= 0 else len(self.songlines) - 1
        new = self.songlines[after].copy() if 0 <= after < len(self.songlines) else Songline()
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
    
    # Pattern operations
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
        for sl in self.songlines:
            if idx in sl.patterns:
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
    
    # Instrument operations
    def add_instrument(self, name: str = "New Instrument") -> int:
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
    
    # Serialization
    def to_dict(self) -> dict:
        return {
            'version': 2,
            'metadata': {'title': self.title, 'author': self.author,
                         'speed': self.speed, 'system': self.system},
            'songlines': [sl.patterns for sl in self.songlines],
            'patterns': [p.to_dict() for p in self.patterns],
            'instruments': [i.to_dict() for i in self.instruments]
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'Song':
        meta = d.get('metadata', {})
        song = cls(
            title=meta.get('title', 'Untitled'),
            author=meta.get('author', ''),
            speed=meta.get('speed', DEFAULT_SPEED),
            system=meta.get('system', PAL_HZ)
        )
        song.songlines = [Songline(patterns=list(sl)) for sl in d.get('songlines', [[0, 1, 2]])]
        song.patterns = [Pattern.from_dict(p) for p in d.get('patterns', [])]
        song.instruments = [Instrument.from_dict(i) for i in d.get('instruments', [])]
        while len(song.patterns) < 3:
            song.patterns.append(Pattern())
        return song
