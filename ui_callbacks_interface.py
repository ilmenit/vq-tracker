"""POKEY VQ Tracker - UI Callbacks Interface

Provides a typed dataclass for all UI callback functions needed by the
operations layer. Replaces the previous pattern of ~15 module-level mutable
callback variables in operations.py with a single, typed, injectable object.

This eliminates implicit coupling between operations.py and the UI layer,
makes dependencies explicit, and improves testability.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional, List


# Type aliases for clarity
RefreshFn = Callable[[], None]
StatusFn = Callable[[str], None]
ErrorFn = Callable[[str, str], None]
ConfirmFn = Callable[[str, str, Callable], None]
FileDialogFn = Callable  # Variable signatures
RenameFn = Callable[[str, str, Callable], None]


def _noop(*args, **kwargs):
    """Default no-op callback for unset functions."""
    pass


@dataclass
class UICallbacks:
    """Typed container for all UI callback functions.
    
    Groups all callback functions that the operations layer needs
    to communicate with the UI layer. Each callback has a sensible
    default (no-op) so the operations layer works even before
    the UI is fully wired up, and during testing.
    
    Usage:
        callbacks = UICallbacks()
        callbacks.refresh_all = my_refresh_function
        ops.init(callbacks)
    """
    
    # --- Refresh callbacks ---
    refresh_all: Callable = field(default=_noop)
    refresh_editor: Callable = field(default=_noop)
    refresh_song_editor: Callable = field(default=_noop)
    refresh_songlist: Callable = field(default=_noop)
    refresh_instruments: Callable = field(default=_noop)
    refresh_pattern_combo: Callable = field(default=_noop)
    refresh_all_pattern_combos: Callable = field(default=_noop)
    refresh_all_instrument_combos: Callable = field(default=_noop)
    update_controls: Callable = field(default=_noop)
    
    # --- Status / feedback callbacks ---
    show_status: Callable = field(default=_noop)
    update_title: Callable = field(default=_noop)
    show_error: Callable = field(default=_noop)
    
    # --- Dialog callbacks ---
    show_confirm: Callable = field(default=_noop)
    show_file_dialog: Callable = field(default=_noop)
    show_rename_dialog: Callable = field(default=_noop)
    
    # --- Menu callbacks ---
    rebuild_recent_menu: Callable = field(default=_noop)
