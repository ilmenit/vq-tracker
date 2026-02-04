"""POKEY VQ Tracker - Pattern Operations

Add, clone, delete, clear, and transpose patterns.
"""
from constants import MAX_PATTERNS
from state import state
from ops.base import ui, save_undo, fmt


def add_pattern(*args):
    """Add new pattern."""
    if len(state.song.patterns) >= MAX_PATTERNS:
        ui.show_status(f"\u26a0 Maximum {MAX_PATTERNS} patterns reached!")
        return
    save_undo("Add pattern")
    idx = state.song.add_pattern()
    if idx >= 0:
        state.selected_pattern = idx
        ui.refresh_all_pattern_combos()
        ui.refresh_pattern_combo()
        ui.show_status(f"Added pattern {fmt(idx)}")


def clone_pattern(*args):
    """Clone current pattern."""
    ptn_idx = state.current_pattern_idx()
    save_undo("Clone pattern")
    new_idx = state.song.clone_pattern(ptn_idx)
    if new_idx >= 0:
        state.selected_pattern = new_idx
        ui.refresh_all_pattern_combos()
        ui.refresh_pattern_combo()
        ui.show_status(f"Cloned > {fmt(new_idx)}")


def delete_pattern(*args):
    """Delete selected pattern if unused."""
    ptn_idx = state.selected_pattern
    if state.song.pattern_in_use(ptn_idx):
        ui.show_error("Cannot Delete", "Pattern is in use by a songline")
        return
    if len(state.song.patterns) <= 1:
        ui.show_error("Cannot Delete", "Cannot delete last pattern")
        return
    save_undo("Delete pattern")
    if state.song.delete_pattern(ptn_idx):
        if state.selected_pattern >= len(state.song.patterns):
            state.selected_pattern = len(state.song.patterns) - 1
        ui.refresh_all()
        ui.show_status("Deleted pattern")


def clear_pattern(*args):
    """Clear all rows in current pattern."""
    ptn_idx = state.current_pattern_idx()
    save_undo("Clear pattern")
    state.song.get_pattern(ptn_idx).clear()
    ui.refresh_editor()


def transpose(semitones: int):
    """Transpose current pattern."""
    ptn_idx = state.current_pattern_idx()
    save_undo(f"Transpose {semitones:+d}")
    state.song.get_pattern(ptn_idx).transpose(semitones)
    ui.refresh_editor()
    ui.show_status(f"Transposed {semitones:+d}")
