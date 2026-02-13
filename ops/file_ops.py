"""POKEY VQ Tracker - File Operations

New, open, save, export, and import operations.
"""
import os
import logging

import file_io
import native_dialog
from constants import MAX_VOLUME
from state import state
from file_io import (
    save_project, load_project, export_binary,
    EditorState,
)
from ops.base import ui, save_undo, fmt

logger = logging.getLogger("tracker.ops.file")


# =============================================================================
# HELPERS
# =============================================================================

def _project_start_dir() -> str:
    """Return a sensible starting directory for project file dialogs."""
    if state.song.file_path:
        d = os.path.dirname(state.song.file_path)
        if os.path.isdir(d):
            return d
    return os.path.expanduser("~")


# =============================================================================
# NEW / OPEN / SAVE
# =============================================================================

def new_song(*args):
    """Create new project."""
    if state.song.modified:
        ui.show_confirm("Unsaved Changes", "Create new project?", _do_new)
    else:
        _do_new()


def _do_new():
    state.audio.stop_playback()
    # Close sample editor before clearing instruments
    try:
        from sample_editor.ui_editor import close_editor
        close_editor()
    except Exception:
        pass
    state.song.reset()
    state.undo.clear()
    state.songline = state.row = state.channel = state.instrument = 0
    state.song_cursor_row = state.song_cursor_col = 0
    state.volume = MAX_VOLUME
    state.selection.clear()
    state.vq.invalidate()
    if file_io.work_dir:
        file_io.work_dir.clear_all()
    state.audio.set_song(state.song)
    ui.refresh_all()
    ui.update_title()
    ui.show_status("New project created")


def open_song(*args):
    """Open project file via native OS dialog."""
    paths = native_dialog.open_files(
        title="Open Project",
        start_dir=_project_start_dir(),
        filters={"Project Files": "pvq,json"},
        allow_multi=False,
    )
    if paths:
        _load_file(paths[0])


def _load_file(path: str):
    if not path:
        return
    if not file_io.work_dir:
        ui.show_error("Load Error", "Working directory not initialized")
        return

    # Stop audio BEFORE loading to release any file handles
    # On Windows, the audio engine may hold references to sample files
    state.audio.stop_playback()
    
    # Close sample editor before replacing song
    try:
        from sample_editor.ui_editor import close_editor
        close_editor()
    except Exception:
        pass
    
    logger.info(f"Loading project: {path}")
    song, editor_state, msg = load_project(path, file_io.work_dir)
    if song:
        state.song = song
        state.undo.clear()

        if editor_state:
            _restore_editor_state(editor_state)
        else:
            _reset_editor_state()

        state.selection.clear()
        state.audio.set_song(state.song)
        ui.refresh_all()
        ui.update_title()
        ui.show_status(msg)

        # Add to recent files
        import ui_globals as G
        G.add_recent_file(path)
        ui.rebuild_recent_menu()

        # Auto-convert if there are samples
        _trigger_auto_conversion()
    else:
        ui.show_error("Load Error", msg)


def _restore_editor_state(editor_state: EditorState):
    """Restore editor state from loaded project."""
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

    # Restore VQ settings
    state.vq.settings.rate = editor_state.vq_rate
    state.vq.settings.vector_size = editor_state.vq_vector_size
    state.vq.settings.smoothness = editor_state.vq_smoothness
    state.vq.settings.enhance = editor_state.vq_enhance
    # memory_limit removed — now auto-computed from start_address + memory_config
    state.vq.settings.used_only = editor_state.vq_used_only
    state.vq.invalidate()


def _reset_editor_state():
    """Reset editor state for legacy files without saved state."""
    state.songline = state.row = state.channel = 0
    state.instrument = 0
    state.song_cursor_row = state.song_cursor_col = 0
    state.volume = MAX_VOLUME
    state.vq.invalidate()


def _trigger_auto_conversion():
    """Auto-trigger VQ conversion after loading a project.

    Uses sample_path (extracted files in work_dir) for sample loading,
    since the original files may no longer exist on the user's disk.
    Writes processed WAVs for instruments with effects.
    """
    if not state.song.instruments:
        return

    from ui_callbacks import _prepare_conversion_files, show_vq_conversion_window
    import ui_callbacks

    used_indices = None
    if state.vq.settings.used_only:
        used_indices = state.song.get_used_instrument_indices()
    
    input_files, proc_files, error = _prepare_conversion_files(
        state.song.instruments, used_indices=used_indices)
    if not input_files:
        return

    ui_callbacks._vq_proc_files = proc_files
    ui_callbacks._vq_used_indices = used_indices
    show_vq_conversion_window(input_files)


def save_song(*args):
    """Save project."""
    if state.song.file_path:
        _save_file(state.song.file_path)
    else:
        save_song_as()


def save_song_as(*args):
    """Save project as new file via native OS dialog."""
    path = native_dialog.save_file(
        title="Save Project",
        start_dir=_project_start_dir(),
        filters={"Project Files": "pvq"},
        default_name=os.path.basename(state.song.file_path) if state.song.file_path else "untitled.pvq",
    )
    if path:
        _save_file(path)


def _save_file(path: str):
    if not path:
        return
    if not file_io.work_dir:
        ui.show_error("Save Error", "Working directory not initialized")
        return

    editor_state = _build_editor_state()
    ok, msg = save_project(state.song, editor_state, path, file_io.work_dir)
    if ok:
        ui.update_title()
        ui.show_status(msg)
        import ui_globals as G
        G.add_recent_file(path)
        ui.rebuild_recent_menu()
    else:
        ui.show_error("Save Error", msg)


def _build_editor_state() -> EditorState:
    """Build EditorState from current application state."""
    return EditorState(
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
        vq_used_only=state.vq.settings.used_only,
    )


# =============================================================================
# EXPORT / IMPORT
# =============================================================================

def export_binary_file(*args):
    """Export to binary .pvg format via native OS dialog."""
    path = native_dialog.save_file(
        title="Export Binary",
        start_dir=_project_start_dir(),
        filters={"Binary Files": "pvg"},
    )
    if path:
        _do_export_binary(path)


def _do_export_binary(path: str):
    if not path:
        return
    ok, msg = export_binary(state.song, path)
    if ok:
        ui.show_status(msg)
    else:
        ui.show_error("Export Error", msg)


def import_mod(*args):
    """Import Amiga MOD file via native OS dialog."""
    paths = native_dialog.open_files(
        title="Import MOD File",
        start_dir=_project_start_dir(),
        filters={"MOD Files": "mod"},
        allow_multi=False,
    )
    if paths:
        # Quick-scan for features, then show options dialog
        from mod_import import scan_mod_features
        features = scan_mod_features(paths[0])
        if features.get('error'):
            ui.show_error("Import Error", features['error'])
            return
        from ui_callbacks import show_mod_import_options
        show_mod_import_options(paths[0], features)


def _do_import_mod(path: str, options: dict = None):
    """Import a .MOD file, replacing the current song."""
    if not path:
        return
    if not file_io.work_dir:
        ui.show_error("Import Error", "Working directory not initialized")
        return

    from mod_import import import_mod_file

    # Stop audio and close editors
    state.audio.stop_playback()
    try:
        from sample_editor.ui_editor import close_editor
        close_editor()
    except Exception:
        pass

    # Import MOD — writes WAV samples to work_dir.samples
    # Do NOT clear_all first: if import fails, old song's files stay intact.
    # The new WAVs overwrite any same-numbered old files; leftovers are harmless.
    song, import_log = import_mod_file(path, file_io.work_dir, options)
    if song:
        # Success — clear VQ/build (now invalid), adopt new song
        file_io.work_dir.clear_vq_output()
        file_io.work_dir.clear_build()
        state.song = song
        state.undo.clear()
        _reset_editor_state()
        state.selection.clear()
        state.vq.invalidate()
        state.audio.set_song(state.song)
        ui.refresh_all()
        ui.update_title()
        ui.show_status(import_log.summary_line())
        logger.info(import_log.summary_line())
        
        # Auto-optimize RAW/VQ mode for imported instruments
        _auto_optimize()
    else:
        ui.show_status("MOD import failed")

    # Show result window (both success and failure)
    from ui_callbacks import show_mod_import_result
    show_mod_import_result(import_log, success=song is not None)


def _auto_optimize():
    """Run RAW/VQ optimizer silently after import."""
    from optimize import analyze_instruments
    
    if not state.song.instruments:
        return
    
    loaded = [inst for inst in state.song.instruments if inst.is_loaded()]
    if not loaded:
        return
    
    # Determine which instruments to consider
    used_indices = None
    if state.vq.settings.used_only:
        used_indices = state.song.get_used_instrument_indices()
    
    # Determine banking mode and memory budget
    from constants import compute_memory_budget
    use_banking = state.song.memory_config != "64 KB"
    budget = compute_memory_budget(
        start_address=state.song.start_address,
        memory_config=state.song.memory_config,
        n_songlines=len(state.song.songlines),
        n_patterns=len(state.song.patterns),
        pattern_lengths=[p.length for p in state.song.patterns],
        n_instruments=len(state.song.instruments),
        vector_size=state.vq.settings.vector_size,
    )
    banking_budget = budget if use_banking else 0
    
    result = analyze_instruments(
        instruments=state.song.instruments,
        target_rate=state.vq.settings.rate,
        vector_size=state.vq.settings.vector_size,
        memory_budget=budget,
        song=state.song,
        volume_control=state.song.volume_control,
        system_hz=state.song.system,
        used_indices=used_indices,
        use_banking=use_banking,
        banking_budget=banking_budget,
    )
    
    n_changed = 0
    for a in result.analyses:
        if a.skipped:
            continue
        if a.index < len(state.song.instruments):
            inst = state.song.instruments[a.index]
            new_use_vq = not a.suggest_raw
            if inst.use_vq != new_use_vq:
                inst.use_vq = new_use_vq
                n_changed += 1
    
    state._optimize_result = result
    
    if n_changed > 0:
        ui.refresh_instruments()
        logger.info(f"Auto-optimize: {n_changed} instrument(s) set to RAW. {result.summary}")
