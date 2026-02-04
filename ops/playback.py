"""POKEY VQ Tracker - Playback Operations

Play/stop/preview controls.
"""
from state import state
from ops.base import ui, fmt


def play_stop(*args):
    """Toggle play/stop."""
    if state.audio.is_playing():
        state.audio.stop_playback()
        ui.show_status("Stopped")
    else:
        state.audio.play_from(state.songline, state.row)
        ui.show_status("Playing...")


def play_pattern(*args):
    """Play current pattern."""
    state.audio.play_pattern(state.songline)
    ui.show_status("Playing pattern...")


def play_song_start(*args):
    """Play song from start."""
    state.audio.play_song(from_start=True)
    ui.show_status("Playing song...")


def play_song_here(*args):
    """Play song from current position."""
    state.audio.play_song(from_start=False, songline=state.songline, row=state.row)
    ui.show_status(f"Playing from line {fmt(state.songline)} row {fmt(state.row)}...")


def stop_playback(*args):
    """Stop playback."""
    state.audio.stop_playback()
    ui.show_status("Stopped")


def preview_row(*args):
    """Preview current row."""
    state.audio.preview_row(state.song, state.songline, state.row)
