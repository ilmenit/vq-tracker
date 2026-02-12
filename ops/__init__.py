"""POKEY VQ Tracker - Operations Package

Focused modules for all tracker operations:
- ops.base       : Shared state, callback access, formatting, undo helper
- ops.file_ops   : File operations (new, open, save, export, import)
- ops.editing    : Cell editing, note entry, copy/paste
- ops.navigation : Cursor movement, jumping, channel switching
- ops.playback   : Play/stop/preview controls
- ops.instrument_ops : Instrument add/remove/rename/select
- ops.pattern_ops    : Pattern add/clone/delete/clear/transpose
- ops.songline_ops   : Songline add/delete/clone/select

All public functions are re-exported here so callers can do:
    import ops
    ops.enter_note(5)
"""

from ops.base import (
    ui, set_ui_callbacks, fmt, save_undo,
    set_playback_row_callback, set_playback_stop_callback,
)

from ops.file_ops import (
    new_song, open_song, save_song, save_song_as,
    export_binary_file,
    import_mod,
)

from ops.editing import (
    enter_note, enter_note_off, clear_cell, clear_row, clear_and_up,
    insert_row, delete_row, enter_digit, enter_digit_decimal,
    copy_cells, cut_cells, paste_cells,
    undo, redo,
    set_cell_note, set_cell_instrument, set_cell_volume,
    set_pattern_length,
)

from ops.navigation import (
    move_cursor, next_channel, prev_channel,
    jump_rows, jump_start, jump_end,
    jump_first_songline, jump_last_songline,
)

from ops.playback import (
    play_stop, play_pattern, play_song_start, play_song_here,
    stop_playback, preview_row,
)

from ops.instrument_ops import (
    add_sample, add_folder, replace_instrument, remove_instrument,
    reset_all_instruments, rename_instrument, select_instrument,
    clone_instrument,
)

from ops.pattern_ops import (
    add_pattern, clone_pattern, delete_pattern,
    clear_pattern, transpose,
)

from ops.songline_ops import (
    add_songline, delete_songline, clone_songline,
    set_songline_pattern, select_songline,
)

from ops.input_settings import (
    set_octave, set_step, change_step, set_speed,
    octave_up, octave_down, next_instrument, prev_instrument,
)


# =============================================================================
# BACKWARD COMPATIBILITY - module-level callback attributes
# =============================================================================
# Legacy code (main.py) may read these attributes via ops.show_status etc.
# We delegate reads to the UICallbacks instance via __getattr__.
# For SETTING callbacks, use set_ui_callbacks() from ops.base (preferred)
# or set attributes directly on ops.base.ui.
#
# NOTE: Module-level __setattr__ is NOT supported by Python (PEP 562 only
# supports __getattr__). Legacy code that does ops.show_status = fn will
# set a module dict entry, not the UICallbacks field. The proper way to
# wire callbacks is via set_ui_callbacks() or direct attribute setting
# on ops.base.ui.

def __getattr__(name):
    """Support legacy attribute access for callback reading."""
    _callback_names = {
        'refresh_all', 'refresh_editor', 'refresh_song_editor',
        'refresh_songlist', 'refresh_instruments', 'refresh_pattern_combo',
        'refresh_all_pattern_combos', 'refresh_all_instrument_combos',
        'update_controls', 'show_status', 'update_title', 'show_error',
        'rebuild_recent_menu', 'show_confirm',
        'show_rename_dialog',
    }
    if name in _callback_names:
        import ops.base
        return getattr(ops.base.ui, name)
    raise AttributeError(f"module 'ops' has no attribute {name!r}")
