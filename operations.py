"""POKEY VQ Tracker - Operations"""
import os
import file_io
from constants import (MAX_OCTAVES, MAX_NOTES, MAX_VOLUME, MAX_ROWS,
                       MAX_INSTRUMENTS, NOTE_KEYS, PAL_HZ, NTSC_HZ, FOCUS_EDITOR,
                       NOTE_OFF)
from state import state
from file_io import (save_project, load_project, load_sample, export_asm,
                     export_binary, import_samples_multi, import_samples_folder,
                     EditorState, import_audio_file, get_supported_extensions,
                     import_pokeyvq)

# Legacy compatibility aliases - access file_io.work_dir at runtime (not import time)
def _get_samples_dir():
    """Get samples directory, falling back to .tmp/samples if work_dir not initialized."""
    if file_io.work_dir:
        return file_io.work_dir.samples
    return ".tmp/samples"

load_samples_multi = lambda paths: import_samples_multi(paths, _get_samples_dir(), 0)
load_samples_folder = lambda folder, recursive=True: import_samples_folder(folder, _get_samples_dir(), recursive, 0)

# UI callbacks (set by main module)
refresh_all = None
refresh_editor = None
refresh_song_editor = None
refresh_songlist = None
refresh_instruments = None
refresh_pattern_combo = None
refresh_all_pattern_combos = None
refresh_all_instrument_combos = None
update_controls = None
show_status = None
update_title = None
show_error = None
rebuild_recent_menu = None  # Rebuild recent files menu
show_confirm = None
show_file_dialog = None
show_rename_dialog = None


def set_playback_row_callback(callback):
    """Set callback for playback row updates."""
    state.audio.on_row = callback


def set_playback_stop_callback(callback):
    """Set callback for playback stop."""
    state.audio.on_stop = callback


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
    state.song_cursor_row = state.song_cursor_col = 0  # Reset song grid cursor
    state.volume = MAX_VOLUME  # Reset brush volume
    state.selection.clear()
    state.vq.invalidate()  # Clear VQ conversion for new project
    # Clear working directory for new project
    if file_io.work_dir:
        file_io.work_dir.clear_all()
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
    if not file_io.work_dir:
        show_error("Load Error", "Working directory not initialized")
        return
    
    song, editor_state, msg = load_project(path, file_io.work_dir)
    if song:
        state.audio.stop_playback()
        state.song = song
        state.undo.clear()
        
        # Restore editor state if available
        if editor_state:
            state.songline = editor_state.songline
            state.row = editor_state.row
            state.channel = editor_state.channel
            state.column = editor_state.column
            state.song_cursor_row = editor_state.song_cursor_row
            state.song_cursor_col = editor_state.song_cursor_col
            state.octave = editor_state.octave
            state.step = editor_state.step
            state.instrument = editor_state.instrument
            state.volume = editor_state.volume
            state.selected_pattern = editor_state.selected_pattern
            state.hex_mode = editor_state.hex_mode
            state.follow = editor_state.follow
            
            # Restore VQ settings (conversion will happen automatically)
            state.vq.settings.rate = editor_state.vq_rate
            state.vq.settings.vector_size = editor_state.vq_vector_size
            state.vq.settings.smoothness = editor_state.vq_smoothness
            state.vq.settings.enhance = editor_state.vq_enhance
            state.vq.settings.optimize_speed = editor_state.vq_optimize_speed
            
            # VQ output not loaded from archive - will be regenerated
            state.vq.invalidate()
        else:
            # Default state for legacy files
            state.songline = state.row = state.channel = 0
            state.instrument = 0
            state.song_cursor_row = state.song_cursor_col = 0
            state.volume = MAX_VOLUME
            state.vq.invalidate()
        
        state.selection.clear()
        state.audio.set_song(state.song)
        refresh_all()
        update_title()
        show_status(msg)
        
        # Add to recent files
        import ui_globals as G
        G.add_recent_file(path)
        if rebuild_recent_menu:
            rebuild_recent_menu()
        
        # Auto-convert if there are samples (ensures latest VQ algorithm is used)
        _trigger_auto_conversion()
    else:
        show_error("Load Error", msg)


def _trigger_auto_conversion():
    """Auto-trigger VQ conversion after loading a project.
    
    Uses sample_path (extracted files in work_dir) rather than original_sample_path,
    since the original files may no longer exist on the user's disk.
    """
    # Collect input files from extracted samples
    input_files = []
    for inst in state.song.instruments:
        # Use sample_path (extracted file) - guaranteed to exist after load
        if inst.sample_path and os.path.exists(inst.sample_path):
            input_files.append(inst.sample_path)
    
    if not input_files:
        # No samples to convert
        return
    
    # Import here to avoid circular import at module load time
    from ui_callbacks import show_vq_conversion_window
    
    # Trigger conversion with extracted samples
    show_vq_conversion_window(input_files)

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
    if not file_io.work_dir:
        show_error("Save Error", "Working directory not initialized")
        return
    
    # Build editor state from current state
    editor_state = EditorState(
        songline=state.songline,
        row=state.row,
        channel=state.channel,
        column=state.column,
        song_cursor_row=state.song_cursor_row,
        song_cursor_col=state.song_cursor_col,
        octave=state.octave,
        step=state.step,
        instrument=state.instrument,
        volume=state.volume,
        selected_pattern=state.selected_pattern,
        hex_mode=state.hex_mode,
        follow=state.follow,
        focus=state.focus,
        vq_converted=state.vq.is_valid,
        vq_rate=state.vq.rate,
        vq_vector_size=state.vq.vector_size,
        vq_smoothness=state.vq.smoothness,
        vq_enhance=state.vq.settings.enhance,
        vq_optimize_speed=state.vq.settings.optimize_speed
    )
    
    ok, msg = save_project(state.song, editor_state, path, file_io.work_dir)
    if ok:
        update_title()
        show_status(msg)
        
        # Add to recent files
        import ui_globals as G
        G.add_recent_file(path)
        if rebuild_recent_menu:
            rebuild_recent_menu()
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

def import_vq_converter(*args):
    """Import vq_converter output (conversion_info.json)."""
    show_file_dialog("Import vq_converter", [".json"], _do_import_vq_converter)

def _do_import_vq_converter(path: str):
    if not path:
        return
    
    results, config, msg = import_pokeyvq(path)
    
    if not results:
        show_error("Import Error", msg)
        return
    
    # Add successfully loaded instruments to song
    loaded = 0
    for inst, ok, inst_msg in results:
        if ok:
            idx = state.song.add_instrument()
            if idx >= 0:
                state.song.instruments[idx] = inst
                loaded += 1
            else:
                show_error("Warning", "Maximum instruments reached")
                break
    
    if loaded > 0:
        save_undo("Import vq_converter")
        state.song.modified = True
        state.vq.invalidate()  # Invalidate VQ conversion
        refresh_instruments()
        refresh_all_instrument_combos()
        state.audio.set_song(state.song)
    
    show_status(msg)

# =============================================================================
# INSTRUMENT OPERATIONS
# =============================================================================

def add_sample(*args):
    """Load sample file(s) - multi-select with audio preview."""
    from ui_browser import show_sample_browser
    show_sample_browser('file', _load_samples)

def _load_samples(paths):
    if not paths:
        return
    if isinstance(paths, str):
        paths = [paths]
    
    # Get samples directory from working directory
    dest_dir = _get_samples_dir()
    start_index = len(state.song.instruments)
    
    count = 0
    for i, path in enumerate(paths):
        idx = state.song.add_instrument()
        if idx < 0:
            show_error("Error", "Maximum instruments reached")
            break
        inst = state.song.instruments[idx]
        
        # Import and convert to WAV if needed
        dest_path, import_msg = import_audio_file(path, dest_dir, start_index + i)
        
        if dest_path:
            ok, msg = load_sample(inst, dest_path)
            if ok:
                # Store original path for reference
                inst.original_sample_path = path
                count += 1
                state.instrument = idx
            else:
                state.song.remove_instrument(idx)
                show_status(f"Error: {msg}")
        else:
            state.song.remove_instrument(idx)
            show_status(f"Import error: {import_msg}")
    
    if count > 0:
        save_undo("Add samples")
        state.vq.invalidate()  # Invalidate VQ conversion
        refresh_instruments()
        show_status(f"Loaded {count} sample(s)")

def add_folder(*args):
    """Load all samples from selected folder(s).
    
    Uses custom browser where user can select one or more folders.
    All audio files in the selected folders will be imported.
    """
    from ui_browser import show_sample_browser
    show_sample_browser('folder', _load_folders)

def _load_folders(paths):
    """Load samples from multiple folders."""
    if not paths:
        return
    if isinstance(paths, str):
        paths = [paths]
    
    total_count = 0
    for folder_path in paths:
        if os.path.isdir(folder_path):
            count = _load_folder_internal(folder_path)
            total_count += count
    
    if total_count > 0:
        show_status(f"Loaded {total_count} sample(s) from {len(paths)} folder(s)")

def _load_folder_internal(path: str) -> int:
    """Load samples from a single folder. Returns count loaded."""
    if not path:
        return 0
    
    # Get samples directory from working directory
    dest_dir = _get_samples_dir()
    start_index = len(state.song.instruments)
    
    results = import_samples_folder(path, dest_dir, recursive=True, start_index=start_index)
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
        state.vq.invalidate()  # Invalidate VQ conversion
        refresh_instruments()
    
    return count

def remove_instrument(*args):
    """Remove current instrument."""
    if not state.song.instruments:
        return
    if state.song.remove_instrument(state.instrument):
        if state.instrument >= len(state.song.instruments):
            state.instrument = max(0, len(state.song.instruments) - 1)
        save_undo("Remove instrument")
        state.vq.invalidate()  # Invalidate VQ conversion
        refresh_instruments()

def reset_all_instruments(*args):
    """Remove all instruments after confirmation."""
    if not state.song.instruments:
        return
    
    count = len(state.song.instruments)
    msg = f"Remove all {count} instrument{'s' if count != 1 else ''}?\nThis cannot be undone."
    
    def do_reset():
        state.song.instruments.clear()
        state.instrument = 0
        # Clear all instrument references in patterns
        for pattern in state.song.patterns:
            for row in pattern.rows:
                if row.note > 0 and row.note != 255:
                    row.instrument = 0
        save_undo("Reset all instruments")
        state.vq.invalidate()
        refresh_instruments()
    
    show_confirm("Reset Instruments", msg, do_reset)

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
    from constants import MAX_PATTERNS
    if len(state.song.patterns) >= MAX_PATTERNS:
        if show_status:
            show_status(f"⚠ Maximum {MAX_PATTERNS} patterns reached!")
        return
    idx = state.song.add_pattern()
    if idx >= 0:
        state.selected_pattern = idx
        save_undo("Add pattern")
        refresh_all_pattern_combos()
        refresh_pattern_combo()
        show_status(f"Added pattern {fmt(idx)}")

def clone_pattern(*args):
    """Clone current pattern."""
    ptn_idx = state.current_pattern_idx()
    new_idx = state.song.clone_pattern(ptn_idx)
    if new_idx >= 0:
        state.selected_pattern = new_idx
        save_undo("Clone pattern")
        refresh_all_pattern_combos()
        refresh_pattern_combo()
        show_status(f"Cloned > {fmt(new_idx)}")

def delete_pattern(*args):
    """Delete selected pattern if unused."""
    ptn_idx = state.selected_pattern
    if state.song.pattern_in_use(ptn_idx):
        show_error("Cannot Delete", "Pattern is in use by a songline")
        return
    if len(state.song.patterns) <= 1:
        show_error("Cannot Delete", "Cannot delete last pattern")
        return
    if state.song.delete_pattern(ptn_idx):
        # Adjust selected_pattern if needed
        if state.selected_pattern >= len(state.song.patterns):
            state.selected_pattern = len(state.song.patterns) - 1
        save_undo("Delete pattern")
        refresh_all()
        show_status(f"Deleted pattern")

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
    from constants import MAX_SONGLINES
    if len(state.song.songlines) >= MAX_SONGLINES:
        if show_status:
            show_status(f"⚠ Maximum {MAX_SONGLINES} songlines reached!")
        return
    idx = state.song.add_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        state.song_cursor_row = idx  # Keep song grid cursor in sync
        save_undo("Add row")
        refresh_all()

def delete_songline(*args):
    """Delete current songline."""
    if len(state.song.songlines) <= 1:
        show_error("Cannot Delete", "Last row")
        return
    if state.song.delete_songline(state.songline):
        if state.songline >= len(state.song.songlines):
            state.songline = len(state.song.songlines) - 1
        state.song_cursor_row = state.songline  # Keep song grid cursor in sync
        save_undo("Delete row")
        refresh_all()

def clone_songline(*args):
    """Clone current songline."""
    idx = state.song.clone_songline(state.songline)
    if idx >= 0:
        state.songline = idx
        state.song_cursor_row = idx  # Keep song grid cursor in sync
        save_undo("Clone row")
        refresh_all()

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
    idx = max(0, min(idx, len(state.song.songlines) - 1))
    state.songline = idx
    state.song_cursor_row = idx  # Keep song grid cursor in sync
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
    """Play song from current position (songline and row)."""
    state.audio.play_song(from_start=False, songline=state.songline, row=state.row)
    show_status(f"Playing from line {fmt(state.songline)} row {fmt(state.row)}...")

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
    """Enter note at cursor. If cell was empty, stamp full brush (note+inst+vol).
    If cell had existing note, only change the note."""
    note = (state.octave - 1) * 12 + semitone + 1
    if not (1 <= note <= MAX_NOTES):
        return
    
    # Check if selected instrument exists
    if state.instrument >= len(state.song.instruments):
        if show_status:
            show_status(f"⚠ Instrument {state.instrument} doesn't exist - add samples first!")
        # Still allow entry (for flexibility) but warn
    
    save_undo("Enter note")
    state.clear_pending()
    state.selection.clear()
    
    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    
    was_empty = (row.note == 0)
    row.note = note
    
    # If cell was empty, stamp full brush (instrument + volume)
    if was_empty:
        row.instrument = state.instrument
        row.volume = state.volume
    # If cell had note, keep existing instrument and volume
    
    # Preview note (only if instrument exists and is loaded)
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        if inst.is_loaded():
            state.audio.preview_note(state.channel, note, inst, row.volume)
    
    # Advance cursor by step (move_cursor handles refresh and cross-songline navigation)
    move_cursor(state.step, 0)


def enter_note_off():
    """Enter note-off (silence) at cursor position.
    
    Note-off stops the currently playing sample on this channel.
    Displayed as 'OFF' in the pattern editor.
    Exported as note=0 in ASM format (interpreted as silence by player).
    """
    save_undo("Enter note-off")
    state.clear_pending()
    state.selection.clear()
    
    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    row.note = NOTE_OFF
    # Note-off doesn't need instrument/volume - player will silence channel
    
    # Advance cursor by step (move_cursor handles refresh and cross-songline navigation)
    move_cursor(state.step, 0)

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
    
    if state.column == 1:  # Instrument (2 hex digits)
        if state.pending_digit is not None and state.pending_col == 1:
            val = (state.pending_digit << 4) | (d & 0xF)
            save_undo("Enter instrument")
            row.instrument = min(val, MAX_INSTRUMENTS - 1)
            # Warn if instrument doesn't exist
            if row.instrument >= len(state.song.instruments):
                show_status(f"⚠ Instrument {row.instrument:02X} not defined")
            state.clear_pending()
            move_cursor(state.step, 0)  # Handles refresh and cross-songline
            return
        else:
            state.pending_digit = d & 0xF
            state.pending_col = 1
            row.instrument = d & 0xF
    else:  # Volume (1 hex digit)
        save_undo("Enter volume")
        row.volume = min(d & 0xF, MAX_VOLUME)
        state.clear_pending()
        move_cursor(state.step, 0)  # Handles refresh and cross-songline
        return
    
    refresh_editor()  # Only for partial input case

def enter_digit_decimal(d: int):
    """Enter decimal digit for instrument/volume in decimal mode."""
    if state.column == 0:
        return
    
    ptn = state.current_pattern()
    row = ptn.get_row(state.row)
    
    if state.column == 1:  # Instrument (3 decimal digits, 000-127)
        if state.pending_digit is not None and state.pending_col == 1:
            # Check if we have 2 pending digits
            if state.pending_digit >= 10:  # Already have 2 digits
                val = state.pending_digit * 10 + d
                save_undo("Enter instrument")
                row.instrument = min(val, MAX_INSTRUMENTS - 1)
                # Warn if instrument doesn't exist
                if row.instrument >= len(state.song.instruments):
                    show_status(f"⚠ Instrument {row.instrument} not defined")
                state.clear_pending()
                move_cursor(state.step, 0)  # Handles refresh and cross-songline
                return
            else:  # Have 1 digit, now 2
                state.pending_digit = state.pending_digit * 10 + d
                row.instrument = min(state.pending_digit, MAX_INSTRUMENTS - 1)
        else:
            state.pending_digit = d
            state.pending_col = 1
            row.instrument = d
    else:  # Volume (2 decimal digits, 00-15)
        if state.pending_digit is not None and state.pending_col == 2:
            val = state.pending_digit * 10 + d
            save_undo("Enter volume")
            row.volume = min(val, MAX_VOLUME)
            state.clear_pending()
            move_cursor(state.step, 0)  # Handles refresh and cross-songline
            return
        else:
            state.pending_digit = d
            state.pending_col = 2
            row.volume = min(d, MAX_VOLUME)
    
    refresh_editor()  # Only for partial input case

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
    """Move cursor with optional selection extension.
    
    Cross-songline navigation:
    - Moving past first row goes to previous songline's last row
    - Moving past last row goes to next songline's first row
    - At song boundaries (first songline row 0, last songline last row): stop
    """
    state.clear_pending()
    
    max_len = state.song.max_pattern_length(state.songline)
    
    # Max column depends on whether volume control is enabled
    max_col = 2 if state.song.volume_control else 1
    
    new_row = state.row + drow
    new_col = state.column + dcol
    new_songline = state.songline
    
    # Handle column wrap to next/prev channel
    if new_col < 0:
        if state.channel > 0:
            state.channel -= 1
            new_col = max_col
        else:
            new_col = 0
    elif new_col > max_col:
        if state.channel < 2:
            state.channel += 1
            new_col = 0
        else:
            new_col = max_col
    
    # Handle row navigation with cross-songline support
    if new_row < 0:
        # Moving up past first row
        if new_songline > 0:
            # Go to previous songline
            new_songline -= 1
            prev_max_len = state.song.max_pattern_length(new_songline)
            new_row = prev_max_len + new_row  # new_row is negative, so this gives last row + offset
            # Handle case where we jumped more than one songline's worth
            while new_row < 0 and new_songline > 0:
                new_songline -= 1
                prev_max_len = state.song.max_pattern_length(new_songline)
                new_row = prev_max_len + new_row
            if new_row < 0:
                new_row = 0  # At absolute beginning of song
        else:
            new_row = 0  # Stay at first row of first songline
    elif new_row >= max_len:
        # Moving down past last row
        total_songlines = len(state.song.songlines)
        if new_songline < total_songlines - 1:
            # Go to next songline
            overflow = new_row - max_len
            new_songline += 1
            new_row = overflow
            # Handle case where we jumped more than one songline's worth
            next_max_len = state.song.max_pattern_length(new_songline)
            while new_row >= next_max_len and new_songline < total_songlines - 1:
                overflow = new_row - next_max_len
                new_songline += 1
                new_row = overflow
                next_max_len = state.song.max_pattern_length(new_songline)
            if new_row >= next_max_len:
                new_row = next_max_len - 1  # At absolute end of song
        else:
            new_row = max_len - 1  # Stay at last row of last songline
    
    # Handle selection
    if extend_selection:
        if not state.selection.active:
            state.selection.begin(state.row, state.channel)
        state.selection.extend(new_row)
    else:
        state.selection.clear()
    
    # Check if songline changed
    songline_changed = (new_songline != state.songline)
    
    state.songline = new_songline
    state.row = new_row
    state.column = new_col
    
    # Keep song editor cursor in sync
    if songline_changed:
        state.song_cursor_row = new_songline
        refresh_all()
    else:
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
    """Jump multiple rows with cross-songline support.
    
    Used by:
    - PageUp/PageDown (±16 rows)
    - Ctrl+Up/Down (±step rows)  
    - Backspace (-step rows after clear)
    """
    state.clear_pending()
    state.selection.clear()
    
    max_len = state.song.max_pattern_length(state.songline)
    new_row = state.row + delta
    new_songline = state.songline
    total_songlines = len(state.song.songlines)
    
    # Handle cross-songline navigation
    if new_row < 0:
        # Moving up past first row
        while new_row < 0 and new_songline > 0:
            new_songline -= 1
            prev_max_len = state.song.max_pattern_length(new_songline)
            new_row = prev_max_len + new_row  # new_row is negative
        if new_row < 0:
            new_row = 0  # At absolute beginning of song
    elif new_row >= max_len:
        # Moving down past last row
        while new_row >= state.song.max_pattern_length(new_songline) and new_songline < total_songlines - 1:
            current_max = state.song.max_pattern_length(new_songline)
            new_row = new_row - current_max
            new_songline += 1
        # Clamp to last row of current songline
        final_max = state.song.max_pattern_length(new_songline)
        if new_row >= final_max:
            new_row = final_max - 1
    
    # Check if songline changed
    songline_changed = (new_songline != state.songline)
    
    state.songline = new_songline
    state.row = new_row
    
    # Keep song editor cursor in sync
    if songline_changed:
        state.song_cursor_row = new_songline
        refresh_all()
    else:
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
    """Set octave (1-4)."""
    state.octave = max(1, min(MAX_OCTAVES, val))
    if update_controls:
        update_controls()

def set_step(val: int):
    """Set step (0-16)."""
    state.step = max(0, min(16, val))
    if update_controls:
        update_controls()

def change_step(delta: int):
    """Change step by delta (+/- to increase/decrease)."""
    set_step(state.step + delta)
    if show_status:
        show_status(f"Step: {state.step}")

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
    else:
        show_status(f"Octave: {state.octave} (max)")

def octave_down(*args):
    """Decrease octave."""
    if state.octave > 1:
        state.octave -= 1
        if update_controls:
            update_controls()
        show_status(f"Octave: {state.octave}")
    else:
        show_status(f"Octave: {state.octave} (min)")

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
    """Set note at specific cell. Applies brush logic if cell was empty."""
    ptns = state.get_patterns()
    ptn = state.song.get_pattern(ptns[channel])
    if 0 <= row < ptn.length:
        save_undo("Set note")
        cell = ptn.get_row(row)
        was_empty = (cell.note == 0)
        cell.note = note
        # If cell was empty and setting a note, stamp full brush
        if was_empty and note > 0:
            cell.instrument = state.instrument
            cell.volume = state.volume
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
