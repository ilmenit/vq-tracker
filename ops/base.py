"""POKEY VQ Tracker - Operations Base

Shared utilities used by all operation modules:
- UICallbacks instance access
- State access
- Formatting helpers
- Undo helper
- file_io access helpers
"""
import os
import logging
from typing import Callable, Optional

import file_io
from state import state
from ui_callbacks_interface import UICallbacks

logger = logging.getLogger("tracker.ops")

# =============================================================================
# UI CALLBACKS INSTANCE
# =============================================================================
# Single typed instance replaces ~15 module-level mutable variables.
# Initialized with no-ops; wired up by main.py via set_ui_callbacks().
ui = UICallbacks()


def set_ui_callbacks(callbacks: UICallbacks):
    """Update the global UICallbacks instance in-place.
    
    Called once during startup after UI is built.
    
    IMPORTANT: We mutate the existing object rather than replacing it,
    because all ops modules import `ui` at module level via
    `from ops.base import ui`. If we replaced the object (global ui = callbacks),
    those imported references would still point to the old default no-op instance.
    By mutating in-place, all existing references see the updated callbacks.
    """
    from dataclasses import fields
    for f in fields(UICallbacks):
        setattr(ui, f.name, getattr(callbacks, f.name))


# =============================================================================
# PLAYBACK CALLBACKS
# =============================================================================

def set_playback_row_callback(callback: Callable):
    """Set callback for playback row updates."""
    state.audio.on_row = callback


def set_playback_stop_callback(callback: Callable):
    """Set callback for playback stop."""
    state.audio.on_stop = callback


# =============================================================================
# FORMATTING
# =============================================================================

def fmt(val: int, width: int = 2) -> str:
    """Format number in hex or decimal mode."""
    return f"{val:0{width}X}" if state.hex_mode else f"{val:0{width}d}"


# =============================================================================
# UNDO HELPER
# =============================================================================

def save_undo(desc: str = ""):
    """Save state for undo."""
    state.undo.save(state.song, desc)
    state.song.modified = True
    ui.update_title()


# =============================================================================
# FILE I/O HELPERS
# =============================================================================

def get_samples_dir() -> str:
    """Get samples directory, falling back to .tmp/samples if work_dir not initialized."""
    if file_io.work_dir:
        return file_io.work_dir.samples
    return ".tmp/samples"
