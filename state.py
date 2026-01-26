"""
Atari Sample Tracker - Application State
Global state and undo/redo management.
"""

from typing import List, Tuple, Optional
from dataclasses import dataclass, field

from constants import DEFAULT_OCTAVE, DEFAULT_STEP, VISIBLE_ROWS, MAX_CHANNELS
from data_model import Song, Pattern, Row
from audio_engine import AudioEngine

# =============================================================================
# UNDO MANAGER
# =============================================================================

class UndoManager:
    """Manages undo/redo history."""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.undo_stack: List[Tuple[dict, str]] = []
        self.redo_stack: List[Tuple[dict, str]] = []
    
    def save(self, song: Song, desc: str = ""):
        """Save state before modification."""
        self.undo_stack.append((song.to_dict(), desc))
        self.redo_stack.clear()
        while len(self.undo_stack) > self.max_size:
            self.undo_stack.pop(0)
    
    def undo(self, song: Song) -> Optional[str]:
        """Undo last action."""
        if not self.undo_stack:
            return None
        self.redo_stack.append((song.to_dict(), "redo"))
        state, desc = self.undo_stack.pop()
        self._restore(song, state)
        return desc
    
    def redo(self, song: Song) -> Optional[str]:
        """Redo last undone action."""
        if not self.redo_stack:
            return None
        self.undo_stack.append((song.to_dict(), "undo"))
        state, desc = self.redo_stack.pop()
        self._restore(song, state)
        return desc
    
    def _restore(self, song: Song, state: dict):
        restored = Song.from_dict(state)
        song.title = restored.title
        song.author = restored.author
        song.speed = restored.speed
        song.system = restored.system
        song.songlines = restored.songlines
        song.patterns = restored.patterns
        song.instruments = restored.instruments
    
    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0
    
    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0
    
    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()

# =============================================================================
# CLIPBOARD
# =============================================================================

class Clipboard:
    """Copy/paste clipboard."""
    
    def __init__(self):
        self.rows: List[Row] = []
    
    def copy(self, rows: List[Row]):
        self.rows = [r.copy() for r in rows]
    
    def paste(self) -> List[Row]:
        return [r.copy() for r in self.rows]
    
    def has_data(self) -> bool:
        return len(self.rows) > 0
    
    def clear(self):
        self.rows.clear()

# =============================================================================
# APPLICATION STATE
# =============================================================================

class AppState:
    """Global application state."""
    
    def __init__(self):
        # Core
        self.song = Song()
        self.undo = UndoManager()
        self.clipboard = Clipboard()
        self.audio = AudioEngine()
        
        # Cursor
        self.songline = 0
        self.row = 0
        self.channel = 0
        self.column = 0  # 0=note, 1=inst, 2=vol
        
        # Input
        self.octave = DEFAULT_OCTAVE
        self.step = DEFAULT_STEP
        self.instrument = 0
        
        # Display
        self.hex_mode = True
        self.visible_rows = VISIBLE_ROWS
        self.follow = True
        
        # Pending hex digit
        self.pending_digit: Optional[int] = None
        self.pending_col: int = -1
    
    def patterns(self) -> List[int]:
        """Get pattern indices for current songline."""
        if self.songline < len(self.song.songlines):
            return self.song.songlines[self.songline].patterns
        return [0, 0, 0]
    
    def current_pattern(self) -> Pattern:
        """Get pattern for current channel."""
        ptns = self.patterns()
        if self.channel < len(ptns):
            return self.song.get_pattern(ptns[self.channel])
        return Pattern()
    
    def focused_pattern_idx(self) -> int:
        """Get pattern index for current channel."""
        ptns = self.patterns()
        return ptns[self.channel] if self.channel < len(ptns) else 0
    
    def clear_pending(self):
        """Clear pending digit entry."""
        self.pending_digit = None
        self.pending_col = -1

# =============================================================================
# GLOBAL STATE INSTANCE
# =============================================================================

state = AppState()
