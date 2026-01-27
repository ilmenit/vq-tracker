"""Atari Sample Tracker - Application State"""
from typing import List, Tuple, Optional
from constants import (DEFAULT_OCTAVE, DEFAULT_STEP, VISIBLE_ROWS, MAX_CHANNELS,
                       FOCUS_EDITOR)
from data_model import Song, Pattern, Row
from audio_engine import AudioEngine

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


class Selection:
    """Multi-cell selection for copy/paste."""
    
    def __init__(self):
        self.active = False
        self.start_row = 0
        self.end_row = 0
        self.channel = 0
    
    def begin(self, row: int, channel: int):
        """Start selection."""
        self.active = True
        self.start_row = row
        self.end_row = row
        self.channel = channel
    
    def extend(self, row: int):
        """Extend selection to row."""
        if self.active:
            self.end_row = row
    
    def clear(self):
        """Clear selection."""
        self.active = False
        self.start_row = 0
        self.end_row = 0
    
    def get_range(self) -> Optional[Tuple[int, int]]:
        """Get (start, end) row range, or None if no selection."""
        if not self.active:
            return None
        lo = min(self.start_row, self.end_row)
        hi = max(self.start_row, self.end_row)
        return (lo, hi)
    
    def contains(self, row: int, channel: int) -> bool:
        """Check if row/channel is in selection."""
        if not self.active or channel != self.channel:
            return False
        lo, hi = min(self.start_row, self.end_row), max(self.start_row, self.end_row)
        return lo <= row <= hi


class Clipboard:
    """Copy/paste clipboard for pattern rows."""
    
    def __init__(self):
        self.rows: List[Row] = []
        self.channel: int = 0
    
    def copy(self, rows: List[Row], channel: int = 0):
        """Copy rows to clipboard."""
        self.rows = [r.copy() for r in rows]
        self.channel = channel
    
    def paste(self) -> List[Row]:
        """Get copied rows."""
        return [r.copy() for r in self.rows]
    
    def has_data(self) -> bool:
        return len(self.rows) > 0
    
    def clear(self):
        self.rows.clear()


class AppState:
    """Global application state."""
    
    def __init__(self):
        # Core data
        self.song = Song()
        self.undo = UndoManager()
        self.clipboard = Clipboard()
        self.selection = Selection()
        self.audio = AudioEngine()
        
        # Cursor position
        self.songline = 0
        self.row = 0
        self.channel = 0
        self.column = 0  # 0=note, 1=inst, 2=vol
        
        # Input settings
        self.octave = DEFAULT_OCTAVE
        self.step = DEFAULT_STEP
        self.instrument = 0
        self.selected_pattern = 0  # Currently selected pattern in PATTERN panel
        
        # Display settings
        self.hex_mode = True
        self.visible_rows = VISIBLE_ROWS
        self.follow = True
        
        # Focus system
        self.focus = FOCUS_EDITOR
        self.input_active = False  # True when typing in text field
        
        # Pending hex digit for two-digit entry
        self.pending_digit: Optional[int] = None
        self.pending_col: int = -1
    
    def get_patterns(self) -> List[int]:
        """Get pattern indices for current songline."""
        if self.songline < len(self.song.songlines):
            return self.song.songlines[self.songline].patterns
        return [0, 0, 0]
    
    def current_pattern(self) -> Pattern:
        """Get pattern for current channel."""
        ptns = self.get_patterns()
        if self.channel < len(ptns):
            return self.song.get_pattern(ptns[self.channel])
        return Pattern()
    
    def current_pattern_idx(self) -> int:
        """Get pattern index for current channel."""
        ptns = self.get_patterns()
        return ptns[self.channel] if self.channel < len(ptns) else 0
    
    def clear_pending(self):
        """Clear pending digit entry."""
        self.pending_digit = None
        self.pending_col = -1
    
    def set_focus(self, focus: int):
        """Set focus area."""
        self.focus = focus
    
    def set_input_active(self, active: bool):
        """Set whether a text input is active (blocks keyboard shortcuts)."""
        self.input_active = active


# Global state instance
state = AppState()
