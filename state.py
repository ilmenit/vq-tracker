"""POKEY VQ Tracker - Application State"""
from typing import List, Tuple, Optional
from constants import (DEFAULT_OCTAVE, DEFAULT_STEP, VISIBLE_ROWS, MAX_CHANNELS,
                       MAX_VOLUME, FOCUS_EDITOR)
from data_model import Song, Pattern, Row
from audio_engine import AudioEngine
from vq_convert import VQState

class UndoManager:
    """Manages undo/redo history."""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.undo_stack: List[Tuple[dict, str, dict]] = []  # (state, desc, audio_refs)
        self.redo_stack: List[Tuple[dict, str, dict]] = []
    
    def _capture_audio(self, song) -> dict:
        """Capture sample_data references from current instruments."""
        refs = {}
        for inst in song.instruments:
            if inst.sample_path and inst.sample_data is not None:
                refs[inst.sample_path] = (inst.sample_data, inst.sample_rate)
        return refs
    
    def save(self, song, desc: str = ""):
        """Save state before modification."""
        audio_refs = self._capture_audio(song)
        self.undo_stack.append((song.to_dict(), desc, audio_refs))
        self.redo_stack.clear()
        while len(self.undo_stack) > self.max_size:
            self.undo_stack.pop(0)
    
    def undo(self, song) -> Optional[str]:
        """Undo last action."""
        if not self.undo_stack:
            return None
        audio_refs = self._capture_audio(song)
        self.redo_stack.append((song.to_dict(), "redo", audio_refs))
        state, desc, saved_audio = self.undo_stack.pop()
        self._restore(song, state, saved_audio)
        return desc
    
    def redo(self, song) -> Optional[str]:
        """Redo last undone action."""
        if not self.redo_stack:
            return None
        audio_refs = self._capture_audio(song)
        self.undo_stack.append((song.to_dict(), "undo", audio_refs))
        state, desc, saved_audio = self.redo_stack.pop()
        self._restore(song, state, saved_audio)
        return desc
    
    def _restore(self, song, state: dict, audio_refs: dict = None):
        """Restore song from snapshot, re-attaching sample_data.
        
        Uses both the saved audio_refs from the snapshot AND any current
        instruments as sources for sample_data recovery. This ensures
        audio survives rename, remove+undo, and reorder operations.
        """
        # Build combined audio lookup from BOTH saved snapshot and current state
        combined_audio = {}
        if audio_refs:
            combined_audio.update(audio_refs)
        # Current instruments as fallback (for cases where audio_refs is incomplete)
        for inst in song.instruments:
            if inst.sample_path and inst.sample_data is not None:
                if inst.sample_path not in combined_audio:
                    combined_audio[inst.sample_path] = (inst.sample_data, inst.sample_rate)
        
        restored = Song.from_dict(state)
        song.title = restored.title
        song.author = restored.author
        song.speed = restored.speed
        song.system = restored.system
        song.volume_control = restored.volume_control
        song.screen_control = restored.screen_control
        song.keyboard_control = restored.keyboard_control
        song.songlines = restored.songlines
        song.patterns = restored.patterns
        song.instruments = restored.instruments
        
        # Re-attach sample_data by sample_path (unique within project)
        for inst in song.instruments:
            if inst.sample_path and inst.sample_path in combined_audio:
                data, rate = combined_audio[inst.sample_path]
                if inst.sample_data is None:
                    inst.sample_data = data
                    inst.sample_rate = rate
    
    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0
    
    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0
    
    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()


class Selection:
    """2D block selection for multi-channel copy/paste.
    
    Tracks a rectangular region: (start_row..end_row) × (start_ch..end_ch).
    Both dimensions can extend in either direction (start can be > end).
    """
    
    def __init__(self):
        self.active = False
        self.start_row = 0
        self.end_row = 0
        self.start_ch = 0
        self.end_ch = 0
    
    # Legacy alias for keyboard.py compatibility
    @property
    def channel(self):
        return self.start_ch
    
    def begin(self, row: int, channel: int):
        """Start selection at (row, channel)."""
        self.active = True
        self.start_row = row
        self.end_row = row
        self.start_ch = channel
        self.end_ch = channel
    
    def extend(self, row: int, channel: int = None):
        """Extend selection to (row, channel).
        
        If channel is None, extends rows only (preserves current channel range).
        """
        if self.active:
            self.end_row = row
            if channel is not None:
                self.end_ch = channel
    
    def clear(self):
        """Clear selection."""
        self.active = False
        self.start_row = 0
        self.end_row = 0
        self.start_ch = 0
        self.end_ch = 0
    
    def get_range(self) -> Optional[Tuple[int, int]]:
        """Get (start_row, end_row) range, or None.  Backward-compatible."""
        if not self.active:
            return None
        return (min(self.start_row, self.end_row),
                max(self.start_row, self.end_row))
    
    def get_block(self) -> Optional[Tuple[int, int, int, int]]:
        """Get (row_lo, row_hi, ch_lo, ch_hi) inclusive ranges, or None."""
        if not self.active:
            return None
        row_lo = min(self.start_row, self.end_row)
        row_hi = max(self.start_row, self.end_row)
        ch_lo = min(self.start_ch, self.end_ch)
        ch_hi = max(self.start_ch, self.end_ch)
        return (row_lo, row_hi, ch_lo, ch_hi)
    
    def contains(self, row: int, channel: int) -> bool:
        """Check if (row, channel) is inside the selection rectangle."""
        if not self.active:
            return False
        row_lo = min(self.start_row, self.end_row)
        row_hi = max(self.start_row, self.end_row)
        ch_lo = min(self.start_ch, self.end_ch)
        ch_hi = max(self.start_ch, self.end_ch)
        return row_lo <= row <= row_hi and ch_lo <= channel <= ch_hi
    
    @property
    def num_channels(self) -> int:
        """Number of channels in selection."""
        if not self.active:
            return 0
        return abs(self.end_ch - self.start_ch) + 1
    
    @property
    def num_rows(self) -> int:
        """Number of rows in selection."""
        if not self.active:
            return 0
        return abs(self.end_row - self.start_row) + 1


class Clipboard:
    """Copy/paste clipboard for pattern blocks.
    
    Stores a 2D block: block[ch_offset][row_offset] = Row.
    ch_offset 0 = first channel in the copied selection.
    """
    
    def __init__(self):
        self.block: List[List[Row]] = []  # block[ch][row]
        self.num_channels: int = 0
        self.num_rows: int = 0
    
    def copy_block(self, block: List[List[Row]]):
        """Copy a 2D block.  block[ch_idx][row_idx]."""
        self.block = [[r.copy() for r in ch_rows] for ch_rows in block]
        self.num_channels = len(block)
        self.num_rows = len(block[0]) if block else 0
    
    def copy(self, rows: List[Row], channel: int = 0):
        """Legacy: copy single-channel rows."""
        self.block = [[r.copy() for r in rows]]
        self.num_channels = 1
        self.num_rows = len(rows)
    
    def paste_block(self) -> List[List[Row]]:
        """Get copied block (deep copy).  Returns block[ch][row]."""
        return [[r.copy() for r in ch_rows] for ch_rows in self.block]
    
    def paste(self) -> List[Row]:
        """Legacy: get first channel's rows."""
        if not self.block:
            return []
        return [r.copy() for r in self.block[0]]
    
    def has_data(self) -> bool:
        return self.num_rows > 0 and self.num_channels > 0
    
    def clear(self):
        self.block.clear()
        self.num_channels = 0
        self.num_rows = 0


class AppState:
    """Global application state."""
    
    def __init__(self):
        # Core data
        self.song = Song()
        self.undo = UndoManager()
        self.clipboard = Clipboard()
        self.selection = Selection()
        self.audio = AudioEngine()
        
        # VQ Conversion state
        self.vq = VQState()
        
        # Pattern Editor cursor position
        self.songline = 0      # Current songline being edited
        self.row = 0           # Row in pattern
        self.channel = 0       # Channel 0-(MAX_CHANNELS-1)
        self.column = 0        # 0=note, 1=inst, 2=vol
        
        # Song Editor cursor position
        self.song_cursor_row = 0     # Row in song editor (which songline)
        self.song_cursor_col = 0     # Column: 0=C1, 1=C2, 2=C3, 3=C4
        
        # Input settings (brush)
        self.octave = DEFAULT_OCTAVE
        self.step = DEFAULT_STEP
        self.instrument = 0
        self.volume = MAX_VOLUME  # Brush volume for stamping new notes
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
        return [0] * MAX_CHANNELS
    
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
