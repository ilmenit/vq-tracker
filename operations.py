"""
Atari Sample Tracker - Operations
All editing, file, and playback operations.
"""

import os
from constants import (
    MAX_OCTAVES, MAX_NOTES, MAX_VOLUME, MAX_ROWS,
    NOTE_KEYS, PAL_HZ, NTSC_HZ, APP_NAME, APP_VERSION
)
from state import state
from file_io import save_project, load_project, load_sample, export_asm

# Forward declarations for UI refresh (set by ui module)
refresh_all = None
refresh_editor = None
refresh_songlist = None
refresh_instruments = None
refresh_pattern_combo = None
update_pattern_len = None
show_status = None
update_title = None
show_error = None
show_confirm = None
show_file_dialog = None
show_rename_dlg = None

def fmt(val: int, width: int = 2) -> str:
    """Format number in hex or decimal."""
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
    if state.song.modified:
        show_confirm("Unsaved Changes", "Create new project?", _do_new)
    else:
        _do_new()

def _do_new():
    state.audio.stop_playback()
    state.song.reset()
    state.undo.clear()
    state.songline = state.row = state.channel = state.instrument = 0
    state.audio.set_song(state.song)
    refresh_all()
    update_title()
    show_status("New project created")

def open_song(*args):
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
        state.instrument = 0 if song.instruments else 0
        state.audio.set_song(state.song)
        refresh_all()
        update_title()
        show_status(msg)
    else:
        show_error("Load Error", msg)

def save_song(*args):
    if state.song.file_path:
        _save_file(state.song.file_path)
    else:
        save_song_as()

def save_song_as(*args):
    show_file_dialog("Save Project As", [".pvq"], _save_file, save_mode=True)

def _save_file(path: str):
    if not path:
        return
    ok, msg = save_project(state.song, path)
    if ok:
        update_title()
        show_status(msg)
    else:
        show_error("Save Error", msg)

def export_asm_files(*args):
    show_file_dialog("Export Directory", [], _do_export, dir_mode=True)

def _do_export(path: str):
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

def add_instrument(*args):
    idx = state.song.add_instrument()
    if idx >= 0:
        state.instrument = idx
        save_undo("Add instrument")
        refresh_instruments()
        show_status(f"Added instrument {fmt(idx)}")

def load_sample_dlg(*args):
    show_file_dialog("Load Sample", [".wav", ".WAV"], _load_sample_file)

def _load_sample_file(path: str):
    if not path:
        return
    if state.instrument >= len(state.song.instruments):
        idx = state.song.add_instrument()
        if idx >= 0:
            state.instrument = idx
        else:
            show_error("Error", "Max instruments reached")
            return
    inst = state.song.instruments[state.instrument]
    ok, msg = load_sample(inst, path)
    if ok:
        save_undo("Load sample")
        refresh_instruments()
        show_status(msg)
    else:
        show_error("Load Error", msg)

def remove_instrument(*args):
    if not state.song.instruments:
        return
    if state.song.remove_instrument(state.instrument):
        if state.instrument >= len(state.song.instruments):
            state.instrument = max(0, len(state.song.instruments) - 1)
        save_undo("Remove instrument")
        refresh_instruments()

def rename_instrument(*args):
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        show_rename_dlg("Rename Instrument", inst.name, _do_rename)

def _do_rename(name: str):
    if name and state.instrument < len(state.song.instruments):
        state.song.instruments[state.instrument].name = name
        save_undo("Rename")
        refresh_instruments()

def select_instrument(idx: int):
    state.instrument = max(0, min(idx, len(state.song.instruments) - 1))
    refresh_instruments()

# =============================================================================
# PATTERN OPERATIONS
# =============================================================================

def add_pattern(*args):
    idx = state.song.add_pattern()
    if idx >= 0:
        save_undo("Add pattern")
        refresh_pattern_combo()
        show_status(f"Added pattern {fmt(idx)}")

def clone_pattern(*args):
    ptn_idx = state.focused_pattern_idx()
    new_idx = state.song.clone_pattern(ptn_idx)
    if new_idx >= 0:
        save_undo("Clone pattern")
        refresh_pattern_combo()
        show_status(f"Cloned → {fmt(new_idx)}")

def delete_pattern(*args):
    ptn_idx = state.focused_pattern_idx()
    if state.song.pattern_in_use(ptn_idx):
        show_error("Cannot Delete", "Pattern in use")
        return
    if len(state.song.patterns) <= 1:
        show_error("Cannot Delete", "Last pattern")
        return
    if state.song.delete_pattern(ptn_idx):
        save_undo("Delete pattern")
        refresh_all()

def clear_pattern(*args):
    ptn_idx = state.focused_pattern_idx()
    state.song.get_pattern(ptn_idx).clear()
    save_undo("Clear pattern")
    refresh_editor()

def set_pattern_length(length: int):
    length = max(1, min(MAX_ROWS, length))
    ptn_idx = state.focused_pattern_idx()
    ptn = state.song.get_pattern(ptn_idx)
    if ptn.length != length:
        ptn.set_length(length)
        save_undo("Set length")
        if state.row >= length:
            state.row = length - 1
        refresh_editor()
        update_pattern_len()

def transpose(semitones: int):
    ptn_idx = state.focused_pattern_idx()
    state.song.get_pattern(ptn_idx).transpose(semitones)
    save_undo(f"Transpose {semitones:+d}")
    refresh_editor()
    show_status(f"Transposed {semitones:+d}")

# =============================================================================
# SONGLINE OPERATIONS
# =============================================================================

def add_songline(*args):
    idx = state.song.add_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        save_undo("Add songline")
        refresh_songlist()

def delete_songline(*args):
    if len(state.song.songlines) <= 1:
        show_error("Cannot Delete", "Last songline")
        return
    if state.song.delete_songline(state.songline):
        if state.songline >= len(state.song.songlines):
            state.songline = len(state.song.songlines) - 1
        save_undo("Delete songline")
        refresh_all()

def clone_songline(*args):
    idx = state.song.clone_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        save_undo("Clone songline")
        refresh_songlist()

def set_songline_pattern(ch: int, ptn_idx: int):
    ptn_idx = max(0, min(ptn_idx, len(state.song.patterns) - 1))
    if state.songline < len(state.song.songlines):
        state.song.songlines[state.songline].patterns[ch] = ptn_idx
        save_undo("Set pattern")
        refresh_songlist()
        refresh_editor()

def select_songline(idx: int):
    state.songline = max(0, min(idx, len(state.song.songlines) - 1))
    state.row = 0
    refresh_all()

# =============================================================================
# PLAYBACK
# =============================================================================

def play_stop(*args):
    if state.audio.is_playing():
        state.audio.stop_playback()
        show_status("Stopped")
    else:
        state.audio.play_from(state.songline, state.row)
        show_status("Playing...")

def play_pattern(*args):
    state.audio.play_pattern(state.songline)
    show_status("Playing pattern...")

def play_song_start(*args):
    state.audio.play_song(from_start=True)
    show_status("Playing song...")

def play_song_here(*args):
    state.audio.play_song(from_start=False, songline=state.songline)
    show_status(f"Playing from {fmt(state.songline)}...")

def stop_playback(*args):
    state.audio.stop_playback()
    show_status("Stopped")

def preview_row(*args):
    state.audio.preview_row(state.song, state.songline, state.row)

# =============================================================================
# EDITING
# =============================================================================

def enter_note(semitone: int):
    note = (state.octave - 1) * 12 + semitone + 1
    if not (1 <= note <= MAX_NOTES):
        return
    
    save_undo("Enter note")
    state.clear_pending()
    
    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    row.note = note
    row.instrument = state.instrument
    
    # Preview
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        if inst.is_loaded():
            state.audio.preview_note(state.channel, note, inst, row.volume)
    
    move_cursor(state.step, 0)
    refresh_editor()

def clear_cell(*args):
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
    save_undo("Clear row")
    state.clear_pending()
    ptn = state.current_pattern()
    ptn.get_row(state.row).clear()
    refresh_editor()

def clear_and_up():
    clear_cell()
    move_cursor(-1, 0)

def insert_row(*args):
    save_undo("Insert")
    state.clear_pending()
    state.current_pattern().insert_row(state.row)
    refresh_editor()

def delete_row(*args):
    save_undo("Delete row")
    state.clear_pending()
    state.current_pattern().delete_row(state.row)
    refresh_editor()

def enter_digit(d: int):
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

def copy_row(*args):
    ptn = state.current_pattern()
    state.clipboard.copy([ptn.get_row(state.row)])
    show_status("Copied")

def cut_row(*args):
    copy_row()
    clear_row()
    show_status("Cut")

def paste_row(*args):
    rows = state.clipboard.paste()
    if rows:
        save_undo("Paste")
        ptn = state.current_pattern()
        for i, r in enumerate(rows):
            if state.row + i < ptn.length:
                ptn.rows[state.row + i] = r
        refresh_editor()
        show_status("Pasted")

def undo(*args):
    desc = state.undo.undo(state.song)
    if desc:
        state.audio.set_song(state.song)
        refresh_all()
        show_status(f"Undo: {desc}" if desc else "Undo")

def redo(*args):
    desc = state.undo.redo(state.song)
    if desc:
        state.audio.set_song(state.song)
        refresh_all()
        show_status(f"Redo: {desc}" if desc else "Redo")

# =============================================================================
# CURSOR MOVEMENT
# =============================================================================

def move_cursor(drow: int, dcol: int):
    state.clear_pending()
    ptn = state.current_pattern()
    
    new_row = state.row + drow
    new_col = state.column + dcol
    
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
    
    if new_row < 0:
        new_row = ptn.length - 1
    elif new_row >= ptn.length:
        new_row = 0
    
    state.row = new_row
    state.column = new_col
    refresh_editor()

def next_channel():
    state.clear_pending()
    if state.channel < 2:
        state.channel += 1
        state.column = 0
        refresh_editor()

def prev_channel():
    state.clear_pending()
    if state.channel > 0:
        state.channel -= 1
        state.column = 0
        refresh_editor()

def jump_rows(delta: int):
    state.clear_pending()
    ptn = state.current_pattern()
    state.row = max(0, min(state.row + delta, ptn.length - 1))
    refresh_editor()

def jump_start():
    state.clear_pending()
    state.row = 0
    refresh_editor()

def jump_end():
    state.clear_pending()
    state.row = state.current_pattern().length - 1
    refresh_editor()

def jump_first_songline():
    state.clear_pending()
    state.songline = 0
    state.row = 0
    refresh_all()

def jump_last_songline():
    state.clear_pending()
    state.songline = len(state.song.songlines) - 1
    state.row = 0
    refresh_all()

def octave_up(*args):
    if state.octave < MAX_OCTAVES:
        state.octave += 1
        show_status(f"Octave: {state.octave}")

def octave_down(*args):
    if state.octave > 1:
        state.octave -= 1
        show_status(f"Octave: {state.octave}")

def next_inst():
    if state.song.instruments:
        state.instrument = (state.instrument + 1) % len(state.song.instruments)
        refresh_instruments()
        show_status(f"Instrument: {fmt(state.instrument)}")

def prev_inst():
    if state.song.instruments:
        state.instrument = (state.instrument - 1) % len(state.song.instruments)
        refresh_instruments()
        show_status(f"Instrument: {fmt(state.instrument)}")
