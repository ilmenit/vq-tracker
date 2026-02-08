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


# =========================================================================
# PUBLIC ENTRY POINTS (called from menus / keyboard shortcuts)
# =========================================================================

def add_sample(*args):
    """Load sample file(s) - multi-select with audio preview."""
    from ui_browser import show_sample_browser
    show_sample_browser('file', _on_files_selected)


def add_folder(*args):
    """Load all samples from selected folder(s)."""
    from ui_browser import show_sample_browser
    show_sample_browser('folder', _on_folders_selected)


def replace_instrument(*args):
    """Replace selected instrument's sample with a new audio file."""
    if not state.song.instruments:
        return
    if state.instrument >= len(state.song.instruments):
        return

    inst = state.song.instruments[state.instrument]
    from ui_browser import show_sample_browser

    # Open browser in single-select file mode, starting from the
    # directory of the instrument's original source file (if known)
    start_dir = None
    if inst.original_sample_path:
        parent = os.path.dirname(inst.original_sample_path)
        if os.path.isdir(parent):
            start_dir = parent

    show_sample_browser(
        'file', _on_replace_file_selected,
        start_path=start_dir,
        ok_label="\u2713 Replace",
        allow_multi=False,
        title=f"Replace Instrument: {inst.name}")


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
    # Preserve: base_note (user may have tuned it)

    state.vq.invalidate()
    ui.refresh_instruments()
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


def select_instrument(idx: int):
    """Select instrument by index."""
    state.instrument = max(0, min(idx, len(state.song.instruments) - 1))
    ui.refresh_instruments()
