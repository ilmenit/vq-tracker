"""POKEY VQ Tracker - File Operations

New, open, save, export, and import operations.
"""
import os
import logging

import file_io
from constants import MAX_VOLUME
from state import state
from file_io import (
    save_project, load_project, export_asm, export_binary,
    import_pokeyvq, EditorState,
)
from ops.base import ui, save_undo, fmt

logger = logging.getLogger("tracker.ops.file")


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
    """Open project file."""
    ui.show_file_dialog("Open Project", [".pvq", ".json"], _load_file)


def _load_file(path: str):
    if not path:
        return
    if not file_io.work_dir:
        ui.show_error("Load Error", "Working directory not initialized")
        return

    song, editor_state, msg = load_project(path, file_io.work_dir)
    if song:
        state.audio.stop_playback()
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
    state.vq.settings.optimize_speed = editor_state.vq_optimize_speed
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

    Uses sample_path (extracted files in work_dir) rather than original_sample_path,
    since the original files may no longer exist on the user's disk.
    """
    input_files = []
    for inst in state.song.instruments:
        if inst.sample_path and os.path.exists(inst.sample_path):
            input_files.append(inst.sample_path)

    if not input_files:
        return

    from ui_callbacks import show_vq_conversion_window
    show_vq_conversion_window(input_files)


def save_song(*args):
    """Save project."""
    if state.song.file_path:
        _save_file(state.song.file_path)
    else:
        save_song_as()


def save_song_as(*args):
    """Save project as new file."""
    ui.show_file_dialog("Save Project", [".pvq"], _save_file, save_mode=True)


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
        vq_optimize_speed=state.vq.settings.optimize_speed,
    )


# =============================================================================
# EXPORT / IMPORT
# =============================================================================

def export_binary_file(*args):
    """Export to binary .pvg format."""
    ui.show_file_dialog("Export Binary", [".pvg"], _do_export_binary, save_mode=True)


def _do_export_binary(path: str):
    if not path:
        return
    ok, msg = export_binary(state.song, path)
    if ok:
        ui.show_status(msg)
    else:
        ui.show_error("Export Error", msg)


def export_asm_files(*args):
    """Export to ASM files."""
    ui.show_file_dialog("Export ASM", [], _do_export_asm, dir_mode=True)


def _do_export_asm(path: str):
    if not path:
        return
    ok, msg = export_asm(state.song, path)
    if ok:
        ui.show_status(msg)
    else:
        ui.show_error("Export Error", msg)


def import_vq_converter(*args):
    """Import vq_converter output (conversion_info.json)."""
    ui.show_file_dialog("Import vq_converter", [".json"], _do_import_vq_converter)


def _do_import_vq_converter(path: str):
    if not path:
        return

    results, config, msg = import_pokeyvq(path)

    if not results:
        ui.show_error("Import Error", msg)
        return

    loaded = 0
    save_undo("Import vq_converter")
    for inst, ok, inst_msg in results:
        if ok:
            idx = state.song.add_instrument()
            if idx >= 0:
                state.song.instruments[idx] = inst
                loaded += 1
            else:
                ui.show_error("Warning", "Maximum instruments reached")
                break

    if loaded > 0:
        state.song.modified = True
        state.vq.invalidate()
        ui.refresh_instruments()
        ui.refresh_all_instrument_combos()
        state.audio.set_song(state.song)

    ui.show_status(msg)
