"""POKEY VQ Tracker - Songline Operations

Add, delete, clone, and select songlines.
"""
from constants import MAX_SONGLINES
from state import state
from ops.base import ui, save_undo


def add_songline(*args):
    """Add new songline."""
    if len(state.song.songlines) >= MAX_SONGLINES:
        ui.show_status(f"\u26a0 Maximum {MAX_SONGLINES} songlines reached!")
        return
    save_undo("Add row")
    idx = state.song.add_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        state.song_cursor_row = idx
        ui.refresh_all()


def delete_songline(*args):
    """Delete current songline."""
    if len(state.song.songlines) <= 1:
        ui.show_error("Cannot Delete", "Last row")
        return
    save_undo("Delete row")
    if state.song.delete_songline(state.songline):
        if state.songline >= len(state.song.songlines):
            state.songline = len(state.song.songlines) - 1
        state.song_cursor_row = state.songline
        ui.refresh_all()


def clone_songline(*args):
    """Clone current songline."""
    save_undo("Clone row")
    idx = state.song.clone_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        state.song_cursor_row = idx
        ui.refresh_all()


def set_songline_pattern(ch: int, ptn_idx: int):
    """Set pattern for channel in current songline."""
    ptn_idx = max(0, min(ptn_idx, len(state.song.patterns) - 1))
    if state.songline < len(state.song.songlines):
        save_undo("Set pattern")
        state.song.songlines[state.songline].patterns[ch] = ptn_idx
        ui.refresh_songlist()
        ui.refresh_editor()


def select_songline(idx: int):
    """Select songline by index."""
    idx = max(0, min(idx, len(state.song.songlines) - 1))
    state.songline = idx
    state.song_cursor_row = idx
    state.row = 0
    state.selection.clear()
    ui.refresh_all()
