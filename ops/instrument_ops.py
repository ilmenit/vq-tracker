"""POKEY VQ Tracker - Instrument Operations

Add, remove, rename, and select instruments.

DESIGN NOTE: All import paths (file selection, folder selection) converge
through _import_paths(), which is the single implementation of
"list of audio files → instruments added to song".  This eliminates the
class of bugs caused by two parallel code paths diverging.
"""
import os
import logging

from constants import NOTE_OFF
from state import state
from file_io import (import_samples_multi,
                     next_sample_start_index, get_supported_extensions)
from ops.base import ui, save_undo, fmt, get_samples_dir

logger = logging.getLogger("tracker.ops.instruments")


from typing import Optional


def _audio_filters() -> dict:
    """Build filter dict for native file dialog from supported extensions."""
    exts = get_supported_extensions()
    # "wav,mp3,ogg,flac,aiff,aif,m4a,wma" (without dots)
    spec = ",".join(e.lstrip(".") for e in sorted(exts))
    return {"Audio Files": spec}


# =========================================================================
# PUBLIC ENTRY POINTS (called from menus / keyboard shortcuts)
# =========================================================================

def add_sample(*args):
    """Load sample file(s) - native multi-select file dialog."""
    import native_dialog
    paths = native_dialog.open_files(
        title="Add Sample Files",
        start_dir=_last_browse_dir(),
        filters=_audio_filters(),
        allow_multi=True,
    )
    if paths:
        _remember_browse_dir(paths[0])
        _on_files_selected(paths)


def add_folder(*args):
    """Load all samples from selected folder."""
    import native_dialog
    folder = native_dialog.pick_folder(
        title="Add Samples from Folder",
        start_dir=_last_browse_dir(),
    )
    if folder:
        _remember_browse_dir(folder)
        _on_folders_selected([folder])


def replace_instrument(*args):
    """Replace selected instrument's sample with a new audio file."""
    if not state.song.instruments:
        return
    if state.instrument >= len(state.song.instruments):
        return

    inst = state.song.instruments[state.instrument]

    # Start from the directory of the instrument's original source file
    start_dir = _last_browse_dir()
    if inst.original_sample_path:
        parent = os.path.dirname(inst.original_sample_path)
        if os.path.isdir(parent):
            start_dir = parent

    import native_dialog
    paths = native_dialog.open_files(
        title=f"Replace Instrument: {inst.name}",
        start_dir=start_dir,
        filters=_audio_filters(),
        allow_multi=False,
    )
    if paths:
        _remember_browse_dir(paths[0])
        _on_replace_file_selected(paths)


# =========================================================================
# BROWSE DIRECTORY MEMORY (persists across dialogs within session)
# =========================================================================
_browse_dir = None


def _last_browse_dir() -> Optional[str]:
    """Return the last directory the user browsed to."""
    global _browse_dir
    if _browse_dir and os.path.isdir(_browse_dir):
        return _browse_dir
    return os.path.expanduser("~")


def _remember_browse_dir(path: str):
    """Remember the directory of a selected file/folder."""
    global _browse_dir
    if os.path.isdir(path):
        _browse_dir = path
    else:
        _browse_dir = os.path.dirname(path)


# =========================================================================
# BROWSER CALLBACKS  (thin adapters → _import_paths / direct replace)
# =========================================================================

def _on_files_selected(paths):
    """Browser callback for file-mode selection."""
    if not paths:
        return
    if isinstance(paths, str):
        paths = [paths]
    _import_paths(paths, "Add samples")


def _on_folders_selected(paths):
    """Browser callback for folder-mode selection.

    Expands folder paths into audio file paths, then delegates to
    the same import function used by file-mode.
    """
    if not paths:
        return
    if isinstance(paths, str):
        paths = [paths]

    # Expand folders → flat list of audio file paths
    audio_paths = []
    extensions = set(get_supported_extensions())
    for folder_path in paths:
        if not os.path.isdir(folder_path):
            continue
        for root, _dirs, files in os.walk(folder_path):
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                if ext in extensions:
                    audio_paths.append(os.path.join(root, f))

    if not audio_paths:
        ui.show_status("No audio files found in selected folder(s)")
        return

    _import_paths(audio_paths, "Add folder")


def _on_replace_file_selected(paths):
    """Browser callback for replace single-file selection.

    Imports the new file first (no state mutation), then swaps the
    audio fields on the current instrument.  Pattern data and instrument
    index are untouched.
    """
    if not paths:
        return
    path = paths[0] if isinstance(paths, list) else paths

    if state.instrument >= len(state.song.instruments):
        return

    dest_dir = get_samples_dir()
    start_index = next_sample_start_index(dest_dir)

    # Import the single file (creates new numbered WAV, no song mutation)
    results = import_samples_multi([path], dest_dir, start_index)
    new_inst, ok, msg = results[0]

    if not ok:
        ui.show_status(f"Replace failed: {msg}")
        return

    # Now mutate — save undo BEFORE changing state so it captures old audio
    save_undo("Replace instrument")

    inst = state.song.instruments[state.instrument]
    inst.name = new_inst.name
    inst.sample_path = new_inst.sample_path
    inst.original_sample_path = new_inst.original_sample_path
    inst.sample_data = new_inst.sample_data
    inst.sample_rate = new_inst.sample_rate
    inst.invalidate_cache()  # Clear processed audio cache (sample changed)
    # Preserve: base_note (user may have tuned it)
    # Preserve: effects (user-configured pipeline still applies)

    state.vq.invalidate()
    ui.refresh_instruments()
    # Refresh sample editor if open (sample data changed under it)
    try:
        from sample_editor.ui_editor import refresh_editor
        refresh_editor()
    except Exception:
        pass
    ui.show_status(f"Replaced with: {new_inst.name}")


# =========================================================================
# CORE IMPORT  (single implementation — both paths converge here)
# =========================================================================

def _import_paths(paths: list, undo_desc: str):
    """Import a list of audio file paths as instruments.

    This is the ONE place where "audio files → song instruments" happens.
    All field initialization (name, sample_path, original_sample_path,
    sample_data) is done by import_samples_multi in file_io.py.
    This function only handles: undo, adding to song, error reporting, UI.
    """
    dest_dir = get_samples_dir()
    start_index = next_sample_start_index(dest_dir)

    save_undo(undo_desc)

    results = import_samples_multi(paths, dest_dir, start_index)

    count = 0
    failed = 0
    for inst, ok, msg in results:
        if ok:
            idx = state.song.add_instrument()
            if idx < 0:
                ui.show_error("Error", "Maximum instruments reached")
                break
            # Replace the empty placeholder with the fully-initialized instrument
            state.song.instruments[idx] = inst
            count += 1
            state.instrument = idx
        else:
            failed += 1
            logger.warning(f"Import failed: {inst.original_sample_path or inst.name}: {msg}")

    if count > 0:
        state.vq.invalidate()
        ui.refresh_instruments()
        status = f"Loaded {count} sample(s)"
        if failed:
            status += f" ({failed} failed)"
        ui.show_status(status)
    else:
        # Nothing imported — discard the undo snapshot
        if state.undo.undo_stack:
            state.undo.undo_stack.pop()
        if failed:
            ui.show_status(f"Import failed for all {failed} file(s)")


# =========================================================================
# REMOVE / RESET
# =========================================================================

def remove_instrument(*args):
    """Remove current instrument."""
    if not state.song.instruments:
        return
    save_undo("Remove instrument")
    # Close sample editor — inst indices shift after removal
    try:
        from sample_editor.ui_editor import close_editor
        close_editor()
    except Exception:
        pass
    if state.song.remove_instrument(state.instrument):
        if state.instrument >= len(state.song.instruments):
            state.instrument = max(0, len(state.song.instruments) - 1)
        state.vq.invalidate()
        ui.refresh_instruments()


def reset_all_instruments(*args):
    """Remove all instruments after confirmation."""
    if not state.song.instruments:
        return

    count = len(state.song.instruments)
    msg = f"Remove all {count} instrument{'s' if count != 1 else ''}?"

    def do_reset():
        save_undo("Reset all instruments")
        try:
            from sample_editor.ui_editor import close_editor
            close_editor()
        except Exception:
            pass
        state.song.instruments.clear()
        state.instrument = 0
        for pattern in state.song.patterns:
            for row in pattern.rows:
                if row.note > 0 and row.note != NOTE_OFF:
                    row.instrument = 0
        state.vq.invalidate()
        ui.refresh_instruments()

    ui.show_confirm("Reset Instruments", msg, do_reset)


# =========================================================================
# RENAME / SELECT
# =========================================================================

def rename_instrument(*args):
    """Rename current instrument."""
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        ui.show_rename_dialog("Rename Instrument", inst.name, _do_rename)


def _do_rename(name: str):
    if name and state.instrument < len(state.song.instruments):
        save_undo("Rename")
        state.song.instruments[state.instrument].name = name
        ui.refresh_instruments()
        try:
            from sample_editor.ui_editor import refresh_editor
            refresh_editor()
        except Exception:
            pass


def select_instrument(idx: int):
    """Select instrument by index."""
    state.instrument = max(0, min(idx, len(state.song.instruments) - 1))
    ui.refresh_instruments()
    # Update sample editor if open
    try:
        from sample_editor.ui_editor import update_editor_instrument
        update_editor_instrument(state.instrument)
    except Exception:
        pass


def clone_instrument(*args):
    """Clone selected instrument (deep copy with processed audio) to end of list."""
    import copy
    
    if not state.song.instruments:
        return
    if state.instrument >= len(state.song.instruments):
        return
    
    src = state.song.instruments[state.instrument]
    if not src.is_loaded():
        ui.show_status("Cannot clone: instrument has no audio data")
        return
    
    save_undo("Clone instrument")
    
    # Check if we can add another instrument
    idx = state.song.add_instrument()
    if idx < 0:
        ui.show_status("Cannot clone: maximum instruments reached")
        return
    
    # Deep copy all fields
    clone = copy.copy(src)
    clone.name = src.name + " (clone)"
    # Deep copy numpy arrays so edits to clone don't affect original
    if src.sample_data is not None:
        clone.sample_data = src.sample_data.copy()
    if src.processed_data is not None:
        clone.processed_data = src.processed_data.copy()
    # Deep copy effects list
    clone.effects = copy.deepcopy(src.effects)
    
    state.song.instruments[idx] = clone
    state.instrument = idx
    state.vq.invalidate()
    ui.refresh_instruments()
    ui.show_status(f"Cloned instrument to slot {idx}: {clone.name}")
