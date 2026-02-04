"""POKEY VQ Tracker - Instrument Operations

Add, remove, rename, and select instruments.
"""
import os
import logging

from constants import NOTE_OFF
from state import state
from file_io import import_audio_file, load_sample, import_samples_folder
from ops.base import ui, save_undo, fmt, get_samples_dir

logger = logging.getLogger("tracker.ops.instruments")


def add_sample(*args):
    """Load sample file(s) - multi-select with audio preview."""
    from ui_browser import show_sample_browser
    show_sample_browser('file', _load_samples)


def _load_samples(paths):
    if not paths:
        return
    if isinstance(paths, str):
        paths = [paths]

    dest_dir = get_samples_dir()
    start_index = len(state.song.instruments)

    count = 0
    save_undo("Add samples")
    for i, path in enumerate(paths):
        idx = state.song.add_instrument()
        if idx < 0:
            ui.show_error("Error", "Maximum instruments reached")
            break
        inst = state.song.instruments[idx]

        dest_path, import_msg = import_audio_file(path, dest_dir, start_index + i)

        if dest_path:
            ok, msg = load_sample(inst, dest_path)
            if ok:
                inst.original_sample_path = path
                count += 1
                state.instrument = idx
            else:
                state.song.remove_instrument(idx)
                ui.show_status(f"Error: {msg}")
        else:
            state.song.remove_instrument(idx)
            ui.show_status(f"Import error: {import_msg}")

    if count > 0:
        state.vq.invalidate()
        ui.refresh_instruments()
        ui.show_status(f"Loaded {count} sample(s)")


def add_folder(*args):
    """Load all samples from selected folder(s)."""
    from ui_browser import show_sample_browser
    show_sample_browser('folder', _load_folders)


def _load_folders(paths):
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
        ui.show_status(f"Loaded {total_count} sample(s) from {len(paths)} folder(s)")


def _load_folder_internal(path: str) -> int:
    """Load samples from a single folder. Returns count loaded."""
    if not path:
        return 0

    dest_dir = get_samples_dir()
    start_index = len(state.song.instruments)

    results = import_samples_folder(path, dest_dir, recursive=True, start_index=start_index)
    count = 0
    failed = 0
    save_undo("Add folder")
    for inst, ok, msg in results:
        if ok:
            idx = state.song.add_instrument()
            if idx < 0:
                break
            state.song.instruments[idx] = inst
            count += 1
            state.instrument = idx
        else:
            failed += 1
            logger.warning(f"Failed to import: {inst.original_sample_path or inst.name}: {msg}")

    if failed > 0:
        logger.warning(f"Failed to import {failed} file(s) from {path}")

    if count > 0:
        state.vq.invalidate()
        ui.refresh_instruments()

    return count


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
    msg = f"Remove all {count} instrument{'s' if count != 1 else ''}?\nThis cannot be undone."

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
