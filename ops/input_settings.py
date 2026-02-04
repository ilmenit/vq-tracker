"""POKEY VQ Tracker - Input Settings Operations

Octave, step, speed changes and instrument selection.
"""
from constants import MAX_OCTAVES, MAX_VOLUME
from state import state
from ops.base import ui, fmt


def set_octave(val: int):
    """Set octave (1-4)."""
    state.octave = max(1, min(MAX_OCTAVES, val))
    ui.update_controls()


def set_step(val: int):
    """Set step (0-16)."""
    state.step = max(0, min(16, val))
    ui.update_controls()


def change_step(delta: int):
    """Change step by delta."""
    set_step(state.step + delta)
    ui.show_status(f"Step: {state.step}")


def set_speed(val: int):
    """Set song speed."""
    val = max(1, min(255, val))
    state.song.speed = val
    state.song.modified = True
    state.audio.set_speed(val)
    ui.update_controls()
    ui.update_title()


def octave_up(*args):
    """Increase octave."""
    if state.octave < MAX_OCTAVES:
        state.octave += 1
        ui.update_controls()
        ui.show_status(f"Octave: {state.octave}")
    else:
        ui.show_status(f"Octave: {state.octave} (max)")


def octave_down(*args):
    """Decrease octave."""
    if state.octave > 1:
        state.octave -= 1
        ui.update_controls()
        ui.show_status(f"Octave: {state.octave}")
    else:
        ui.show_status(f"Octave: {state.octave} (min)")


def next_instrument():
    """Select next instrument."""
    if state.song.instruments:
        state.instrument = (state.instrument + 1) % len(state.song.instruments)
        ui.refresh_instruments()
        ui.show_status(f"Instrument: {fmt(state.instrument)}")


def prev_instrument():
    """Select previous instrument."""
    if state.song.instruments:
        state.instrument = (state.instrument - 1) % len(state.song.instruments)
        ui.refresh_instruments()
        ui.show_status(f"Instrument: {fmt(state.instrument)}")
