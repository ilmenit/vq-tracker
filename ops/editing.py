"""POKEY VQ Tracker - Editing Operations

Cell editing, note entry, copy/paste, undo/redo.
"""
import logging

from constants import (MAX_NOTES, MAX_VOLUME, MAX_INSTRUMENTS, MAX_CHANNELS,
                       NOTE_OFF, VOL_CHANGE, MAX_OCTAVES)
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


def enter_vol_change():
    """Enter volume-change marker at cursor position.

    Sets the note to VOL_CHANGE (V--) and stamps the current brush
    volume.  Requires volume_control to be enabled on the song.
    """
    if not state.song.volume_control:
        ui.show_status("Volume control is disabled - enable in Song Info")
        return

    save_undo("Enter volume change")
    state.clear_pending()
    state.selection.clear()

    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    row.note = VOL_CHANGE
    row.volume = state.volume

    from ops.navigation import move_cursor
    move_cursor(state.step, 0)


# =============================================================================
# CELL EDITING
# =============================================================================

def clear_cell(*args):
    """Clear current cell or selected block."""
    block = state.selection.get_block()
    if block:
        # Clear entire selected rectangle
        save_undo("Clear block")
        row_lo, row_hi, ch_lo, ch_hi = block
        target_chs = set(range(ch_lo, ch_hi + 1))
        _unshare_patterns(target_chs)
        ptns = state.song.songlines[state.songline].patterns
        for ch in range(ch_lo, ch_hi + 1):
            ptn = state.song.get_pattern(ptns[ch])
            for r in range(row_lo, row_hi + 1):
                if r < ptn.length:
                    ptn.get_row(r).clear()
        state.selection.clear()
        ui.refresh_editor()
        return

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
    """Delete row at cursor, or clear selected block."""
    block = state.selection.get_block()
    if block:
        # Delete with selection = clear the block
        clear_cell()
        return
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
        # Auto-insert VOL_CHANGE on empty rows
        if row.note == 0 and state.song.volume_control:
            row.note = VOL_CHANGE
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
            # Auto-insert VOL_CHANGE on empty rows
            if row.note == 0 and state.song.volume_control:
                row.note = VOL_CHANGE
            state.clear_pending()
            from ops.navigation import move_cursor
            move_cursor(state.step, 0)
            return
        else:
            save_undo("Enter volume")
            state.pending_digit = d
            state.pending_col = 2
            row.volume = min(d, MAX_VOLUME)
            # Auto-insert VOL_CHANGE on empty rows
            if row.note == 0 and state.song.volume_control:
                row.note = VOL_CHANGE

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

def _unshare_patterns(target_chs: set) -> bool:
    """Auto-clone patterns that are shared between target and non-target channels.

    When editing (paste/cut/clear) a multi-channel block, if a target channel's
    pattern index is also used by a channel outside the target set, cloning the
    pattern first prevents the edit from "leaking" to unrelated channels.

    Returns True if any pattern was cloned (caller should refresh combos).
    """
    songline = state.song.songlines[state.songline]
    ptns = songline.patterns
    cloned = False
    for ch in target_chs:
        ptn_idx = ptns[ch]
        shared = any(ptns[other] == ptn_idx
                     for other in range(MAX_CHANNELS)
                     if other not in target_chs)
        if shared:
            new_idx = state.song.clone_pattern(ptn_idx)
            if new_idx >= 0:
                ptns[ch] = new_idx
                cloned = True
    if cloned:
        try:
            ui.refresh_all_pattern_combos()
        except Exception:
            pass
    return cloned

def copy_cells(*args):
    """Copy selected block (or current row) to clipboard + OS clipboard."""
    import clipboard_text
    block = state.selection.get_block()

    if block:
        row_lo, row_hi, ch_lo, ch_hi = block
        ptns = state.get_patterns()
        data = []  # data[ch_offset][row_offset]
        for ch in range(ch_lo, ch_hi + 1):
            ptn = state.song.get_pattern(ptns[ch])
            ch_rows = []
            for r in range(row_lo, row_hi + 1):
                ch_rows.append(ptn.get_row(r % ptn.length).copy())
            data.append(ch_rows)
        state.clipboard.copy_block(data)
        num_ch = ch_hi - ch_lo + 1
        num_rows = row_hi - row_lo + 1
        # Also set OS clipboard
        try:
            text = clipboard_text.rows_to_text(data)
            clipboard_text.set_os_clipboard(text)
        except Exception:
            pass
        ui.show_status(f"Copied {num_rows} rows × {num_ch} ch")
    else:
        # No selection: copy current row, current channel only
        ptn = state.current_pattern()
        data = [[ptn.get_row(state.row).copy()]]
        state.clipboard.copy_block(data)
        try:
            text = clipboard_text.rows_to_text(data)
            clipboard_text.set_os_clipboard(text)
        except Exception:
            pass
        ui.show_status("Copied row")


def cut_cells(*args):
    """Cut selected block (or current row)."""
    copy_cells()

    block = state.selection.get_block()
    save_undo("Cut")

    if block:
        row_lo, row_hi, ch_lo, ch_hi = block
        target_chs = set(range(ch_lo, ch_hi + 1))
        _unshare_patterns(target_chs)
        ptns = state.song.songlines[state.songline].patterns
        for ch in range(ch_lo, ch_hi + 1):
            ptn = state.song.get_pattern(ptns[ch])
            for r in range(row_lo, row_hi + 1):
                if r < ptn.length:
                    ptn.get_row(r).clear()
    else:
        ptn = state.current_pattern()
        ptn.get_row(state.row).clear()

    state.selection.clear()
    ui.refresh_editor()
    ui.show_status("Cut")


def paste_cells(*args):
    """Paste block at cursor.

    Priority:
    1. OS clipboard (if it contains valid PVQT text — user may have edited
       the data in Notepad since the last internal copy).
    2. Internal clipboard (always available, set by Ctrl+C within tracker).

    Pastes multi-channel blocks starting at (state.row, state.channel).
    Auto-clones shared patterns so the paste doesn't leak to channels
    outside the target range.
    """
    import clipboard_text

    data = None
    # Try OS clipboard first (may contain user-edited PVQT text)
    try:
        text = clipboard_text.get_os_clipboard()
        if text:
            check = text.lstrip("\ufeff\xef\xbb\xbf")
            if check.startswith(clipboard_text.MAGIC):
                result = clipboard_text.text_to_rows(text)
                if result:
                    data, _, _ = result
    except Exception:
        pass
    # Fall back to internal clipboard
    if not data and state.clipboard.has_data():
        data = state.clipboard.paste_block()

    if not data:
        ui.show_status("Nothing to paste")
        return

    save_undo("Paste")
    num_ch = min(len(data), MAX_CHANNELS - state.channel)
    num_rows = len(data[0]) if data else 0
    target_chs = set(range(state.channel, state.channel + num_ch))

    _unshare_patterns(target_chs)

    ptns = state.song.songlines[state.songline].patterns
    for ch_offset in range(num_ch):
        target_ch = state.channel + ch_offset
        ptn = state.song.get_pattern(ptns[target_ch])
        for r_offset in range(num_rows):
            target_row = state.row + r_offset
            if target_row < ptn.length:
                ptn.rows[target_row] = data[ch_offset][r_offset]

    state.selection.clear()
    ui.refresh_editor()
    ui.show_status(f"Pasted {num_rows} rows × {num_ch} ch")


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
