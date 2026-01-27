"""Atari Sample Tracker - Operations"""
import os
from constants import (MAX_OCTAVES, MAX_NOTES, MAX_VOLUME, MAX_ROWS,
                       NOTE_KEYS, PAL_HZ, NTSC_HZ, FOCUS_EDITOR)
from state import state
from file_io import (save_project, load_project, load_sample, export_asm,
                     export_binary, load_samples_multi, load_samples_folder)

# UI callbacks (set by main module)
refresh_all = None
refresh_editor = None
refresh_songlist = None
refresh_instruments = None
refresh_pattern_combo = None
update_controls = None
show_status = None
update_title = None
show_error = None
show_confirm = None
show_file_dialog = None
show_rename_dialog = None

def fmt(val: int, width: int = 2) -> str:
    """Format number in hex or decimal mode."""
    return f"{val:0{width}X}" if state.hex_mode else f"{val:0{width}d}"

def save_undo(desc: str = ""):
    """Save state for undo."""
    state.undo.save(state.song, desc)
    state.song.modified = True
    if update_title:
        update_title()

# =============================================================================
# FILE OPERATIONS
# =============================================================================

def new_song(*args):
    """Create new project."""
    if state.song.modified:
        show_confirm("Unsaved Changes", "Create new project?", _do_new)
    else:
        _do_new()

def _do_new():
    state.audio.stop_playback()
    state.song.reset()
    state.undo.clear()
    state.songline = state.row = state.channel = state.instrument = 0
    state.selection.clear()
    state.audio.set_song(state.song)
    refresh_all()
    update_title()
    show_status("New project created")

def open_song(*args):
    """Open project file."""
    show_file_dialog("Open Project", [".pvq", ".json"], _load_file)

def _load_file(path: str):
    if not path:
        return
    song, msg = load_project(path)
    if song:
        state.audio.stop_playback()
        state.song = song
        state.undo.clear()
        state.songline = state.row = state.channel = 0
        state.instrument = 0
        state.selection.clear()
        state.audio.set_song(state.song)
        refresh_all()
        update_title()
        show_status(msg)
    else:
        show_error("Load Error", msg)

def save_song(*args):
    """Save project (JSON format)."""
    if state.song.file_path:
        _save_file(state.song.file_path)
    else:
        save_song_as()

def save_song_as(*args):
    """Save project as new file."""
    show_file_dialog("Save Project", [".pvq"], _save_file, save_mode=True)

def _save_file(path: str):
    if not path:
        return
    ok, msg = save_project(state.song, path)
    if ok:
        update_title()
        show_status(msg)
    else:
        show_error("Save Error", msg)

def export_binary_file(*args):
    """Export to binary .pvg format."""
    show_file_dialog("Export Binary", [".pvg"], _do_export_binary, save_mode=True)

def _do_export_binary(path: str):
    if not path:
        return
    ok, msg = export_binary(state.song, path)
    if ok:
        show_status(msg)
    else:
        show_error("Export Error", msg)

def export_asm_files(*args):
    """Export to ASM files."""
    show_file_dialog("Export ASM", [], _do_export_asm, dir_mode=True)

def _do_export_asm(path: str):
    if not path:
        return
    ok, msg = export_asm(state.song, path)
    if ok:
        show_status(msg)
    else:
        show_error("Export Error", msg)

# =============================================================================
# INSTRUMENT OPERATIONS
# =============================================================================

def add_sample(*args):
    """Load sample file(s) - multi-select."""
    show_file_dialog("Load Samples", [".wav", ".WAV"], _load_samples, multi=True)

def _load_samples(paths):
    if not paths:
        return
    if isinstance(paths, str):
        paths = [paths]
    
    count = 0
    for path in paths:
        idx = state.song.add_instrument()
        if idx < 0:
            show_error("Error", "Maximum instruments reached")
            break
        inst = state.song.instruments[idx]
        ok, msg = load_sample(inst, path)
        if ok:
            count += 1
            state.instrument = idx
        else:
            state.song.remove_instrument(idx)
    
    if count > 0:
        save_undo("Add samples")
        refresh_instruments()
        show_status(f"Loaded {count} sample(s)")

def add_folder(*args):
    """Load all samples from folder."""
    show_file_dialog("Select Folder", [], _load_folder, dir_mode=True)

def _load_folder(path: str):
    if not path:
        return
    
    results = load_samples_folder(path)
    count = 0
    for inst, ok, msg in results:
        if ok:
            idx = state.song.add_instrument()
            if idx < 0:
                break
            state.song.instruments[idx] = inst
            count += 1
            state.instrument = idx
    
    if count > 0:
        save_undo("Add folder")
        refresh_instruments()
        show_status(f"Loaded {count} sample(s) from folder")

def remove_instrument(*args):
    """Remove current instrument."""
    if not state.song.instruments:
        return
    if state.song.remove_instrument(state.instrument):
        if state.instrument >= len(state.song.instruments):
            state.instrument = max(0, len(state.song.instruments) - 1)
        save_undo("Remove instrument")
        refresh_instruments()

def rename_instrument(*args):
    """Rename current instrument."""
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        show_rename_dialog("Rename Instrument", inst.name, _do_rename)

def _do_rename(name: str):
    if name and state.instrument < len(state.song.instruments):
        state.song.instruments[state.instrument].name = name
        save_undo("Rename")
        refresh_instruments()

def select_instrument(idx: int):
    """Select instrument by index."""
    state.instrument = max(0, min(idx, len(state.song.instruments) - 1))
    refresh_instruments()

# =============================================================================
# PATTERN OPERATIONS
# =============================================================================

def add_pattern(*args):
    """Add new pattern."""
    idx = state.song.add_pattern()
    if idx >= 0:
        save_undo("Add pattern")
        refresh_pattern_combo()
        show_status(f"Added pattern {fmt(idx)}")

def clone_pattern(*args):
    """Clone current pattern."""
    ptn_idx = state.current_pattern_idx()
    new_idx = state.song.clone_pattern(ptn_idx)
    if new_idx >= 0:
        save_undo("Clone pattern")
        refresh_pattern_combo()
        show_status(f"Cloned > {fmt(new_idx)}")

def delete_pattern(*args):
    """Delete current pattern if unused."""
    ptn_idx = state.current_pattern_idx()
    if state.song.pattern_in_use(ptn_idx):
        show_error("Cannot Delete", "Pattern is in use")
        return
    if len(state.song.patterns) <= 1:
        show_error("Cannot Delete", "Last pattern")
        return
    if state.song.delete_pattern(ptn_idx):
        save_undo("Delete pattern")
        refresh_all()

def clear_pattern(*args):
    """Clear all rows in current pattern."""
    ptn_idx = state.current_pattern_idx()
    state.song.get_pattern(ptn_idx).clear()
    save_undo("Clear pattern")
    refresh_editor()

def transpose(semitones: int):
    """Transpose current pattern."""
    ptn_idx = state.current_pattern_idx()
    state.song.get_pattern(ptn_idx).transpose(semitones)
    save_undo(f"Transpose {semitones:+d}")
    refresh_editor()
    show_status(f"Transposed {semitones:+d}")

# =============================================================================
# SONGLINE OPERATIONS
# =============================================================================

def add_songline(*args):
    """Add new songline."""
    idx = state.song.add_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        save_undo("Add row")
        refresh_songlist()

def delete_songline(*args):
    """Delete current songline."""
    if len(state.song.songlines) <= 1:
        show_error("Cannot Delete", "Last row")
        return
    if state.song.delete_songline(state.songline):
        if state.songline >= len(state.song.songlines):
            state.songline = len(state.song.songlines) - 1
        save_undo("Delete row")
        refresh_all()

def clone_songline(*args):
    """Clone current songline."""
    idx = state.song.clone_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        save_undo("Clone row")
        refresh_songlist()

def set_songline_pattern(ch: int, ptn_idx: int):
    """Set pattern for channel in current songline."""
    ptn_idx = max(0, min(ptn_idx, len(state.song.patterns) - 1))
    if state.songline < len(state.song.songlines):
        state.song.songlines[state.songline].patterns[ch] = ptn_idx
        save_undo("Set pattern")
        refresh_songlist()
        refresh_editor()

def select_songline(idx: int):
    """Select songline by index."""
    state.songline = max(0, min(idx, len(state.song.songlines) - 1))
    state.row = 0
    state.selection.clear()
    refresh_all()

# =============================================================================
# PLAYBACK
# =============================================================================

def play_stop(*args):
    """Toggle play/stop."""
    if state.audio.is_playing():
        state.audio.stop_playback()
        show_status("Stopped")
    else:
        state.audio.play_from(state.songline, state.row)
        show_status("Playing...")

def play_pattern(*args):
    """Play current pattern."""
    state.audio.play_pattern(state.songline)
    show_status("Playing pattern...")

def play_song_start(*args):
    """Play song from start."""
    state.audio.play_song(from_start=True)
    show_status("Playing song...")

def play_song_here(*args):
    """Play song from current position."""
    state.audio.play_song(from_start=False, songline=state.songline)
    show_status(f"Playing from {fmt(state.songline)}...")

def stop_playback(*args):
    """Stop playback."""
    state.audio.stop_playback()
    show_status("Stopped")

def preview_row(*args):
    """Preview current row."""
    state.audio.preview_row(state.song, state.songline, state.row)

# =============================================================================
# EDITING
# =============================================================================

def enter_note(semitone: int):
    """Enter note at cursor."""
    note = (state.octave - 1) * 12 + semitone + 1
    if not (1 <= note <= MAX_NOTES):
        return
    
    save_undo("Enter note")
    state.clear_pending()
    state.selection.clear()
    
    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    row.note = note
    row.instrument = state.instrument
    
    # Preview note
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        if inst.is_loaded():
            state.audio.preview_note(state.channel, note, inst, row.volume)
    
    move_cursor(state.step, 0)
    refresh_editor()

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
    refresh_editor()

def clear_row():
    """Clear entire row."""
    save_undo("Clear row")
    state.clear_pending()
    state.current_pattern().get_row(state.row).clear()
    refresh_editor()

def clear_and_up():
    """Clear cell and move up."""
    clear_cell()
    move_cursor(-1, 0)

def insert_row(*args):
    """Insert row at cursor."""
    save_undo("Insert")
    state.clear_pending()
    state.current_pattern().insert_row(state.row)
    refresh_editor()

def delete_row(*args):
    """Delete row at cursor."""
    save_undo("Delete row")
    state.clear_pending()
    state.current_pattern().delete_row(state.row)
    refresh_editor()

def enter_digit(d: int):
    """Enter hex digit for instrument/volume."""
    if state.column == 0:
        return
    
    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    
    if state.column == 1:  # Instrument (2 digits)
        if state.pending_digit is not None and state.pending_col == 1:
            val = (state.pending_digit << 4) | (d & 0xF)
            save_undo("Enter instrument")
            row.instrument = min(val, 127)
            state.clear_pending()
            move_cursor(state.step, 0)
        else:
            state.pending_digit = d & 0xF
            state.pending_col = 1
            row.instrument = d & 0xF
    else:  # Volume (1 digit)
        save_undo("Enter volume")
        row.volume = min(d & 0xF, MAX_VOLUME)
        state.clear_pending()
        move_cursor(state.step, 0)
    
    refresh_editor()

# =============================================================================
# COPY/PASTE (Multi-cell)
# =============================================================================

def copy_cells(*args):
    """Copy selected cells or current row."""
    ptn = state.current_pattern()
    sel_range = state.selection.get_range()
    
    if sel_range:
        start, end = sel_range
        rows = [ptn.get_row(i) for i in range(start, end + 1)]
        state.clipboard.copy(rows, state.channel)
        show_status(f"Copied {len(rows)} rows")
    else:
        state.clipboard.copy([ptn.get_row(state.row)], state.channel)
        show_status("Copied row")

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
    refresh_editor()
    show_status("Cut")

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
    refresh_editor()
    show_status(f"Pasted {len(rows)} rows")

def undo(*args):
    """Undo last action."""
    desc = state.undo.undo(state.song)
    if desc:
        state.audio.set_song(state.song)
        state.selection.clear()
        refresh_all()
        show_status(f"Undo: {desc}" if desc else "Undo")

def redo(*args):
    """Redo last undone action."""
    desc = state.undo.redo(state.song)
    if desc:
        state.audio.set_song(state.song)
        state.selection.clear()
        refresh_all()
        show_status(f"Redo: {desc}" if desc else "Redo")

# =============================================================================
# CURSOR MOVEMENT
# =============================================================================

def move_cursor(drow: int, dcol: int, extend_selection: bool = False):
    """Move cursor with optional selection extension."""
    state.clear_pending()
    
    max_len = state.song.max_pattern_length(state.songline)
    
    new_row = state.row + drow
    new_col = state.column + dcol
    
    # Handle column wrap to next/prev channel
    if new_col < 0:
        if state.channel > 0:
            state.channel -= 1
            new_col = 2
        else:
            new_col = 0
    elif new_col > 2:
        if state.channel < 2:
            state.channel += 1
            new_col = 0
        else:
            new_col = 2
    
    # Handle row wrap
    if new_row < 0:
        new_row = max_len - 1
    elif new_row >= max_len:
        new_row = 0
    
    # Handle selection
    if extend_selection:
        if not state.selection.active:
            state.selection.begin(state.row, state.channel)
        state.selection.extend(new_row)
    else:
        state.selection.clear()
    
    state.row = new_row
    state.column = new_col
    refresh_editor()

def next_channel():
    """Move to next channel."""
    state.clear_pending()
    state.selection.clear()
    if state.channel < 2:
        state.channel += 1
        state.column = 0
        refresh_editor()

def prev_channel():
    """Move to previous channel."""
    state.clear_pending()
    state.selection.clear()
    if state.channel > 0:
        state.channel -= 1
        state.column = 0
        refresh_editor()

def jump_rows(delta: int):
    """Jump multiple rows."""
    state.clear_pending()
    state.selection.clear()
    max_len = state.song.max_pattern_length(state.songline)
    state.row = max(0, min(state.row + delta, max_len - 1))
    refresh_editor()

def jump_start():
    """Jump to first row."""
    state.clear_pending()
    state.selection.clear()
    state.row = 0
    refresh_editor()

def jump_end():
    """Jump to last row."""
    state.clear_pending()
    state.selection.clear()
    state.row = state.song.max_pattern_length(state.songline) - 1
    refresh_editor()

def jump_first_songline():
    """Jump to first songline."""
    state.clear_pending()
    state.selection.clear()
    state.songline = 0
    state.row = 0
    refresh_all()

def jump_last_songline():
    """Jump to last songline."""
    state.clear_pending()
    state.selection.clear()
    state.songline = len(state.song.songlines) - 1
    state.row = 0
    refresh_all()

# =============================================================================
# INPUT SETTINGS
# =============================================================================

def set_octave(val: int):
    """Set octave (1-3)."""
    state.octave = max(1, min(MAX_OCTAVES, val))
    if update_controls:
        update_controls()

def set_step(val: int):
    """Set step (0-16)."""
    state.step = max(0, min(16, val))
    if update_controls:
        update_controls()

def set_speed(val: int):
    """Set song speed."""
    val = max(1, min(255, val))
    state.song.speed = val
    state.song.modified = True
    state.audio.set_speed(val)
    if update_controls:
        update_controls()
    if update_title:
        update_title()

def octave_up(*args):
    """Increase octave."""
    if state.octave < MAX_OCTAVES:
        state.octave += 1
        if update_controls:
            update_controls()
        show_status(f"Octave: {state.octave}")

def octave_down(*args):
    """Decrease octave."""
    if state.octave > 1:
        state.octave -= 1
        if update_controls:
            update_controls()
        show_status(f"Octave: {state.octave}")

def next_instrument():
    """Select next instrument."""
    if state.song.instruments:
        state.instrument = (state.instrument + 1) % len(state.song.instruments)
        refresh_instruments()
        show_status(f"Instrument: {fmt(state.instrument)}")

def prev_instrument():
    """Select previous instrument."""
    if state.song.instruments:
        state.instrument = (state.instrument - 1) % len(state.song.instruments)
        refresh_instruments()
        show_status(f"Instrument: {fmt(state.instrument)}")

# =============================================================================
# CELL EDITING (for popup selection)
# =============================================================================

def set_cell_note(row: int, channel: int, note: int):
    """Set note at specific cell."""
    ptns = state.get_patterns()
    ptn = state.song.get_pattern(ptns[channel])
    if 0 <= row < ptn.length:
        save_undo("Set note")
        ptn.get_row(row).note = note
        state.song.modified = True
        refresh_editor()

def set_cell_instrument(row: int, channel: int, inst: int):
    """Set instrument at specific cell."""
    ptns = state.get_patterns()
    ptn = state.song.get_pattern(ptns[channel])
    if 0 <= row < ptn.length:
        save_undo("Set instrument")
        ptn.get_row(row).instrument = inst
        state.song.modified = True
        refresh_editor()

def set_cell_volume(row: int, channel: int, vol: int):
    """Set volume at specific cell."""
    ptns = state.get_patterns()
    ptn = state.song.get_pattern(ptns[channel])
    if 0 <= row < ptn.length:
        save_undo("Set volume")
        ptn.get_row(row).volume = min(vol, MAX_VOLUME)
        state.song.modified = True
        refresh_editor()

def set_pattern_length(length: int, ptn_idx: int = None):
    """Set pattern length."""
    if ptn_idx is None:
        ptn_idx = state.selected_pattern
    ptn = state.song.get_pattern(ptn_idx)
    if ptn:
        save_undo("Set length")
        ptn.set_length(length)
        state.song.modified = True
        # Clamp cursor if needed
        if state.row >= ptn.length:
            state.row = ptn.length - 1
        refresh_editor()
        if update_controls:
            update_controls()
