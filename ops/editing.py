"""POKEY VQ Tracker - Editing Operations

Cell editing, note entry, copy/paste, undo/redo.
"""
import logging

from constants import (MAX_NOTES, MAX_VOLUME, MAX_INSTRUMENTS, NOTE_OFF,
                       MAX_OCTAVES)
from state import state
from ops.base import ui, save_undo, fmt

logger = logging.getLogger("tracker.ops.editing")


# =============================================================================
# NOTE ENTRY
# =============================================================================

def enter_note(semitone: int):
    """Enter note at cursor.
    
    Coupled mode (default): always stamp note + instrument + volume.
    Uncoupled mode: if cell had existing note, only change the note.
    Empty cells always get the full stamp regardless of mode.
    """
    import ui_globals as G
    
    note = (state.octave - 1) * 12 + semitone + 1
    if not (1 <= note <= MAX_NOTES):
        return

    # Warn if instrument doesn't exist (but still allow entry)
    if state.instrument >= len(state.song.instruments):
        ui.show_status(f"\u26a0 Instrument {state.instrument} doesn't exist - add samples first!")

    save_undo("Enter note")
    state.clear_pending()
    state.selection.clear()

    ptn = state.current_pattern()
    row = ptn.get_row(state.row)

    was_empty = (row.note == 0)
    row.note = note

    # Stamp instrument + volume when:
    # - Cell was empty (always), OR
    # - Coupled mode is ON (classic tracker behavior)
    if was_empty or G.coupled_entry:
        row.instrument = state.instrument
        row.volume = state.volume

    # Preview note using the instrument that's actually on the row
    preview_inst_idx = row.instrument
    if preview_inst_idx < len(state.song.instruments):
        inst = state.song.instruments[preview_inst_idx]
        if inst.is_loaded():
            state.audio.preview_note(state.channel, note, inst, row.volume)

    # Advance cursor by step
    from ops.navigation import move_cursor
    move_cursor(state.step, 0)


def enter_note_off():
    """Enter note-off (silence) at cursor position."""
    save_undo("Enter note-off")
    state.clear_pending()
    state.selection.clear()

    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    row.note = NOTE_OFF

    from ops.navigation import move_cursor
    move_cursor(state.step, 0)


# =============================================================================
# CELL EDITING
# =============================================================================

def clear_cell(*args):
    """Clear current cell."""
    save_undo("Clear")
    state.clear_pending()
    ptn = state.current_pattern()
    row = ptn.get_row(state.row)

    if state.column == 0:
        row.note = 0
    elif state.column == 1:
        row.instrument = 0
    else:
        row.volume = MAX_VOLUME
    ui.refresh_editor()


def clear_row():
    """Clear entire row."""
    save_undo("Clear row")
    state.clear_pending()
    state.current_pattern().get_row(state.row).clear()
    ui.refresh_editor()


def clear_and_up():
    """Clear cell and move up."""
    clear_cell()
    from ops.navigation import move_cursor
    move_cursor(-1, 0)


def insert_row(*args):
    """Insert row at cursor."""
    save_undo("Insert")
    state.clear_pending()
    state.current_pattern().insert_row(state.row)
    ui.refresh_editor()


def delete_row(*args):
    """Delete row at cursor."""
    save_undo("Delete row")
    state.clear_pending()
    state.current_pattern().delete_row(state.row)
    ui.refresh_editor()


def enter_digit(d: int):
    """Enter hex digit for instrument/volume."""
    if state.column == 0:
        return

    ptn = state.current_pattern()
    row = ptn.get_row(state.row)

    if state.column == 1:  # Instrument (2 hex digits)
        if state.pending_digit is not None and state.pending_col == 1:
            val = (state.pending_digit << 4) | (d & 0xF)
            row.instrument = min(val, MAX_INSTRUMENTS - 1)
            if row.instrument >= len(state.song.instruments):
                ui.show_status(f"\u26a0 Instrument {row.instrument:02X} not defined")
            state.clear_pending()
            from ops.navigation import move_cursor
            move_cursor(state.step, 0)
            return
        else:
            save_undo("Enter instrument")
            state.pending_digit = d & 0xF
            state.pending_col = 1
            row.instrument = d & 0xF
    else:  # Volume (1 hex digit)
        save_undo("Enter volume")
        row.volume = min(d & 0xF, MAX_VOLUME)
        state.clear_pending()
        from ops.navigation import move_cursor
        move_cursor(state.step, 0)
        return

    ui.refresh_editor()


def enter_digit_decimal(d: int):
    """Enter decimal digit for instrument/volume in decimal mode."""
    if state.column == 0:
        return

    ptn = state.current_pattern()
    row = ptn.get_row(state.row)

    if state.column == 1:  # Instrument (3 decimal digits, 000-127)
        if state.pending_digit is not None and state.pending_col == 1:
            if state.pending_digit >= 10:  # Already have 2 digits
                val = state.pending_digit * 10 + d
                row.instrument = min(val, MAX_INSTRUMENTS - 1)
                if row.instrument >= len(state.song.instruments):
                    ui.show_status(f"\u26a0 Instrument {row.instrument} not defined")
                state.clear_pending()
                from ops.navigation import move_cursor
                move_cursor(state.step, 0)
                return
            else:
                state.pending_digit = state.pending_digit * 10 + d
                row.instrument = min(state.pending_digit, MAX_INSTRUMENTS - 1)
        else:
            save_undo("Enter instrument")
            state.pending_digit = d
            state.pending_col = 1
            row.instrument = d
    else:  # Volume (2 decimal digits, 00-15)
        if state.pending_digit is not None and state.pending_col == 2:
            val = state.pending_digit * 10 + d
            row.volume = min(val, MAX_VOLUME)
            state.clear_pending()
            from ops.navigation import move_cursor
            move_cursor(state.step, 0)
            return
        else:
            save_undo("Enter volume")
            state.pending_digit = d
            state.pending_col = 2
            row.volume = min(d, MAX_VOLUME)

    ui.refresh_editor()


# =============================================================================
# CELL EDITING (for popup selection)
# =============================================================================

def set_cell_note(row: int, channel: int, note: int):
    """Set note at specific cell."""
    import ui_globals as G
    
    ptns = state.get_patterns()
    ptn = state.song.get_pattern(ptns[channel])
    if 0 <= row < ptn.length:
        save_undo("Set note")
        cell = ptn.get_row(row)
        was_empty = (cell.note == 0)
        cell.note = note
        if note > 0 and (was_empty or G.coupled_entry):
            cell.instrument = state.instrument
            cell.volume = state.volume
        state.song.modified = True
        ui.refresh_editor()


def set_cell_instrument(row: int, channel: int, inst: int):
    """Set instrument at specific cell."""
    ptns = state.get_patterns()
    ptn = state.song.get_pattern(ptns[channel])
    if 0 <= row < ptn.length:
        save_undo("Set instrument")
        ptn.get_row(row).instrument = inst
        state.song.modified = True
        ui.refresh_editor()


def set_cell_volume(row: int, channel: int, vol: int):
    """Set volume at specific cell."""
    ptns = state.get_patterns()
    ptn = state.song.get_pattern(ptns[channel])
    if 0 <= row < ptn.length:
        save_undo("Set volume")
        ptn.get_row(row).volume = min(vol, MAX_VOLUME)
        state.song.modified = True
        ui.refresh_editor()


def set_pattern_length(length: int, ptn_idx: int = None):
    """Set pattern length."""
    if ptn_idx is None:
        ptn_idx = state.selected_pattern
    if not (0 <= ptn_idx < len(state.song.patterns)):
        return
    ptn = state.song.patterns[ptn_idx]
    save_undo("Set length")
    ptn.set_length(length)
    state.song.modified = True
    if state.row >= ptn.length:
        state.row = ptn.length - 1
    ui.refresh_editor()
    ui.update_controls()


# =============================================================================
# COPY / PASTE
# =============================================================================

def copy_cells(*args):
    """Copy selected cells or current row."""
    ptn = state.current_pattern()
    sel_range = state.selection.get_range()

    if sel_range:
        start, end = sel_range
        rows = [ptn.get_row(i) for i in range(start, end + 1)]
        state.clipboard.copy(rows, state.channel)
        ui.show_status(f"Copied {len(rows)} rows")
    else:
        state.clipboard.copy([ptn.get_row(state.row)], state.channel)
        ui.show_status("Copied row")


def cut_cells(*args):
    """Cut selected cells or current row."""
    copy_cells()

    ptn = state.current_pattern()
    sel_range = state.selection.get_range()

    save_undo("Cut")
    if sel_range:
        start, end = sel_range
        for i in range(start, end + 1):
            ptn.get_row(i).clear()
    else:
        ptn.get_row(state.row).clear()

    state.selection.clear()
    ui.refresh_editor()
    ui.show_status("Cut")


def paste_cells(*args):
    """Paste cells at cursor."""
    rows = state.clipboard.paste()
    if not rows:
        return

    save_undo("Paste")
    ptn = state.current_pattern()
    for i, row in enumerate(rows):
        target_row = state.row + i
        if target_row < ptn.length:
            ptn.rows[target_row] = row

    state.selection.clear()
    ui.refresh_editor()
    ui.show_status(f"Pasted {len(rows)} rows")


# =============================================================================
# UNDO / REDO
# =============================================================================

def undo(*args):
    """Undo last action."""
    desc = state.undo.undo(state.song)
    if desc:
        state.audio.set_song(state.song)
        state.selection.clear()
        ui.refresh_all()
        # Refresh sample editor (instruments were replaced by undo)
        try:
            from sample_editor.ui_editor import refresh_editor
            refresh_editor()
        except Exception:
            pass
        ui.show_status(f"Undo: {desc}" if desc else "Undo")


def redo(*args):
    """Redo last undone action."""
    desc = state.undo.redo(state.song)
    if desc:
        state.audio.set_song(state.song)
        state.selection.clear()
        ui.refresh_all()
        try:
            from sample_editor.ui_editor import refresh_editor
            refresh_editor()
        except Exception:
            pass
        ui.show_status(f"Redo: {desc}" if desc else "Redo")
