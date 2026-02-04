"""POKEY VQ Tracker - Operations (Backward Compatibility Wrapper)

This module delegates all functionality to the ops/ package.
Existing code that does `import operations as ops` or
`from operations import ...` continues to work unchanged.

The actual implementation is split across:
    ops/base.py           - Shared state, callbacks, formatting, undo
    ops/file_ops.py       - File new/open/save/export/import
    ops/editing.py        - Cell editing, note entry, copy/paste, undo/redo
    ops/navigation.py     - Cursor movement, jumping
    ops/playback.py       - Play/stop/preview
    ops/instrument_ops.py - Instrument add/remove/rename
    ops/pattern_ops.py    - Pattern add/clone/delete/transpose
    ops/songline_ops.py   - Songline add/delete/clone
    ops/input_settings.py - Octave, step, speed changes
"""

# Re-export everything from the ops package
from ops import *  # noqa: F401, F403

# Re-export the UICallbacks instance and setter for backward compatibility
from ops.base import ui, set_ui_callbacks

# Legacy aliases used by some code paths
import file_io
from file_io import import_samples_multi, import_samples_folder
from ops.base import get_samples_dir as _get_samples_dir

load_samples_multi = lambda paths: import_samples_multi(paths, _get_samples_dir(), 0)
load_samples_folder = lambda folder, recursive=True: import_samples_folder(folder, _get_samples_dir(), recursive, 0)


# =============================================================================
# BACKWARD COMPATIBILITY - module-level callback attributes
# =============================================================================
# External modules (keyboard.py, ui_build.py, etc.) may access callback
# attributes on this module, e.g. ops.refresh_instruments().
# We delegate those reads to the UICallbacks instance in ops.base.

def __getattr__(name):
    """Support legacy attribute access for callback names."""
    _callback_names = {
        'refresh_all', 'refresh_editor', 'refresh_song_editor',
        'refresh_songlist', 'refresh_instruments', 'refresh_pattern_combo',
        'refresh_all_pattern_combos', 'refresh_all_instrument_combos',
        'update_controls', 'show_status', 'update_title', 'show_error',
        'rebuild_recent_menu', 'show_confirm', 'show_file_dialog',
        'show_rename_dialog',
    }
    if name in _callback_names:
        import ops.base
        return getattr(ops.base.ui, name)
    raise AttributeError(f"module 'operations' has no attribute {name!r}")
