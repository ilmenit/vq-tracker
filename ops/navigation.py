"""POKEY VQ Tracker - Navigation Operations

Cursor movement, jumping, channel switching.
"""
from state import state
from constants import MAX_CHANNELS
from ops.base import ui


# =============================================================================
# CURSOR MOVEMENT
# =============================================================================

def move_cursor(drow: int, dcol: int, extend_selection: bool = False):
    """Move cursor with optional 2D selection extension.

    When extend_selection=True:
      - drow extends the row range (Shift+Up/Down)
      - dcol extends the channel range (Shift+Left/Right wraps at column boundaries)
    
    Cross-songline navigation:
    - Moving past first row goes to previous songline's last row
    - Moving past last row goes to next songline's first row
    - At song boundaries: stop
    """
    state.clear_pending()

    max_len = state.song.max_pattern_length(state.songline)
    max_col = 2 if state.song.volume_control else 1

    new_row = state.row + drow
    new_col = state.column + dcol
    new_channel = state.channel
    new_songline = state.songline

    # Handle column wrap to next/prev channel
    if new_col < 0:
        if new_channel > 0:
            new_channel -= 1
            new_col = max_col
        else:
            new_col = 0
    elif new_col > max_col:
        if new_channel < MAX_CHANNELS - 1:
            new_channel += 1
            new_col = 0
        else:
            new_col = max_col

    # Handle row navigation with cross-songline support
    if new_row < 0:
        if new_songline > 0:
            new_songline -= 1
            prev_max_len = state.song.max_pattern_length(new_songline)
            new_row = prev_max_len + new_row
            while new_row < 0 and new_songline > 0:
                new_songline -= 1
                prev_max_len = state.song.max_pattern_length(new_songline)
                new_row = prev_max_len + new_row
            if new_row < 0:
                new_row = 0
        else:
            new_row = 0
    elif new_row >= max_len:
        total_songlines = len(state.song.songlines)
        if new_songline < total_songlines - 1:
            overflow = new_row - max_len
            new_songline += 1
            new_row = overflow
            next_max_len = state.song.max_pattern_length(new_songline)
            while new_row >= next_max_len and new_songline < total_songlines - 1:
                overflow = new_row - next_max_len
                new_songline += 1
                new_row = overflow
                next_max_len = state.song.max_pattern_length(new_songline)
            if new_row >= state.song.max_pattern_length(new_songline):
                next_max_len = state.song.max_pattern_length(new_songline)
                new_row = next_max_len - 1
        else:
            new_row = max_len - 1

    # Handle selection
    if extend_selection:
        if not state.selection.active:
            state.selection.begin(state.row, state.channel)
        # Extend to new position (both row and channel)
        state.selection.extend(new_row, new_channel)
    else:
        state.selection.clear()

    songline_changed = (new_songline != state.songline)
    state.songline = new_songline
    state.row = new_row
    state.column = new_col
    state.channel = new_channel

    if songline_changed:
        state.song_cursor_row = new_songline
        ui.refresh_all()
    else:
        ui.refresh_editor()


# =============================================================================
# CHANNEL SWITCHING
# =============================================================================

def next_channel():
    """Move to next channel."""
    state.clear_pending()
    state.selection.clear()
    if state.channel < MAX_CHANNELS - 1:
        state.channel += 1
        state.column = 0
        ui.refresh_editor()


def prev_channel():
    """Move to previous channel."""
    state.clear_pending()
    state.selection.clear()
    if state.channel > 0:
        state.channel -= 1
        state.column = 0
        ui.refresh_editor()


# =============================================================================
# JUMPING
# =============================================================================

def jump_rows(delta: int):
    """Jump multiple rows with cross-songline support.

    Used by PageUp/PageDown (±16 rows), Ctrl+Up/Down (±step rows).
    """
    state.clear_pending()
    state.selection.clear()

    max_len = state.song.max_pattern_length(state.songline)
    new_row = state.row + delta
    new_songline = state.songline
    total_songlines = len(state.song.songlines)

    if new_row < 0:
        while new_row < 0 and new_songline > 0:
            new_songline -= 1
            prev_max_len = state.song.max_pattern_length(new_songline)
            new_row = prev_max_len + new_row
        if new_row < 0:
            new_row = 0
    elif new_row >= max_len:
        while new_row >= state.song.max_pattern_length(new_songline) and new_songline < total_songlines - 1:
            current_max = state.song.max_pattern_length(new_songline)
            new_row = new_row - current_max
            new_songline += 1
        final_max = state.song.max_pattern_length(new_songline)
        if new_row >= final_max:
            new_row = final_max - 1

    songline_changed = (new_songline != state.songline)
    state.songline = new_songline
    state.row = new_row

    if songline_changed:
        state.song_cursor_row = new_songline
        ui.refresh_all()
    else:
        ui.refresh_editor()


def jump_start():
    """Jump to first row."""
    state.clear_pending()
    state.selection.clear()
    state.row = 0
    ui.refresh_editor()


def jump_end():
    """Jump to last row."""
    state.clear_pending()
    state.selection.clear()
    state.row = state.song.max_pattern_length(state.songline) - 1
    ui.refresh_editor()


def jump_first_songline():
    """Jump to first songline."""
    state.clear_pending()
    state.selection.clear()
    state.songline = 0
    state.song_cursor_row = 0
    state.row = 0
    ui.refresh_all()


def jump_last_songline():
    """Jump to last songline."""
    state.clear_pending()
    state.selection.clear()
    last = len(state.song.songlines) - 1
    state.songline = last
    state.song_cursor_row = last
    state.row = 0
    ui.refresh_all()


def select_all():
    """Select all rows across all channels in current songline."""
    max_len = state.song.max_pattern_length(state.songline)
    state.selection.begin(0, 0)
    state.selection.extend(max_len - 1, MAX_CHANNELS - 1)
    ui.refresh_editor()


def toggle_follow():
    """Toggle follow mode (cursor follows playback position)."""
    state.follow = not state.follow
    ui.update_controls()
    ui.show_status(f"Follow {'ON' if state.follow else 'OFF'}")


def solo_channel(ch: int):
    """Solo a channel: enable only this channel, mute all others.

    If this channel is already the only one enabled, un-solo (enable all).
    """
    if not (0 <= ch < MAX_CHANNELS):
        return

    # Check if already solo'd on this channel
    enabled = [state.audio.is_channel_enabled(c) for c in range(MAX_CHANNELS)]
    already_solo = (enabled[ch] and enabled.count(True) == 1)

    if already_solo:
        # Un-solo: enable all channels
        for c in range(MAX_CHANNELS):
            state.audio.set_channel_enabled(c, True)
        ui.show_status("All channels enabled")
    else:
        # Solo: enable only this channel
        for c in range(MAX_CHANNELS):
            state.audio.set_channel_enabled(c, c == ch)
        ui.show_status(f"Solo channel {ch + 1}")
    ui.update_controls()
    ui.refresh_editor()
