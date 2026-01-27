"""Atari Sample Tracker - Keyboard Handler"""
import dearpygui.dearpygui as dpg
from constants import NOTE_KEYS, FOCUS_EDITOR, FOCUS_SONG, MAX_CHANNELS
from state import state
import operations as ops

# Key to character mapping
KEY_MAP = {
    dpg.mvKey_A: 'a', dpg.mvKey_B: 'b', dpg.mvKey_C: 'c', dpg.mvKey_D: 'd',
    dpg.mvKey_E: 'e', dpg.mvKey_F: 'f', dpg.mvKey_G: 'g', dpg.mvKey_H: 'h',
    dpg.mvKey_I: 'i', dpg.mvKey_J: 'j', dpg.mvKey_K: 'k', dpg.mvKey_L: 'l',
    dpg.mvKey_M: 'm', dpg.mvKey_N: 'n', dpg.mvKey_O: 'o', dpg.mvKey_P: 'p',
    dpg.mvKey_Q: 'q', dpg.mvKey_R: 'r', dpg.mvKey_S: 's', dpg.mvKey_T: 't',
    dpg.mvKey_U: 'u', dpg.mvKey_V: 'v', dpg.mvKey_W: 'w', dpg.mvKey_X: 'x',
    dpg.mvKey_Y: 'y', dpg.mvKey_Z: 'z',
    dpg.mvKey_0: '0', dpg.mvKey_1: '1', dpg.mvKey_2: '2', dpg.mvKey_3: '3',
    dpg.mvKey_4: '4', dpg.mvKey_5: '5', dpg.mvKey_6: '6', dpg.mvKey_7: '7',
    dpg.mvKey_8: '8', dpg.mvKey_9: '9',
    dpg.mvKey_NumPad0: '0', dpg.mvKey_NumPad1: '1', dpg.mvKey_NumPad2: '2',
    dpg.mvKey_NumPad3: '3', dpg.mvKey_NumPad4: '4', dpg.mvKey_NumPad5: '5',
    dpg.mvKey_NumPad6: '6', dpg.mvKey_NumPad7: '7', dpg.mvKey_NumPad8: '8',
    dpg.mvKey_NumPad9: '9',
}

# Pending hex digit for song editor
_song_pending_digit = None


def handle_key(sender, key):
    """Handle key press event."""
    # Skip if typing in a text field - check both our flag and DPG's active item detection
    if state.input_active:
        return
    
    # Additional check: see if any input-related item has keyboard focus
    # This catches cases where our callback didn't fire
    input_tags = ["title_input", "author_input", "speed_input", "step_input", "ptn_len_input"]
    try:
        for tag in input_tags:
            if dpg.does_item_exist(tag):
                if dpg.is_item_active(tag) or dpg.is_item_focused(tag):
                    return
    except:
        pass
    
    # Also check if a popup or modal is open (file dialogs, etc.)
    # This is harder to detect, but we can check for common popup tags
    popup_tags = ["popup_inst", "popup_vol", "popup_note", "popup_song_ptn", 
                  "confirm_dlg", "rename_dlg", "error_dlg", "confirm_dialog", 
                  "error_dialog", "rename_dialog", "about_dialog", "shortcuts_dialog"]
    try:
        for tag in popup_tags:
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                return
    except:
        pass
    
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
    
    # === GLOBAL SHORTCUTS (Ctrl+key) ===
    if ctrl:
        if key == dpg.mvKey_N:
            ops.new_song()
        elif key == dpg.mvKey_O:
            ops.open_song()
        elif key == dpg.mvKey_S:
            ops.save_song_as() if shift else ops.save_song()
        elif key == dpg.mvKey_Z:
            ops.undo()
        elif key == dpg.mvKey_Y:
            ops.redo()
        elif key == dpg.mvKey_C:
            ops.copy_cells()
        elif key == dpg.mvKey_X:
            ops.cut_cells()
        elif key == dpg.mvKey_V:
            ops.paste_cells()
        elif key == dpg.mvKey_Home:
            ops.jump_first_songline()
        elif key == dpg.mvKey_End:
            ops.jump_last_songline()
        return
    
    # === PLAYBACK (always active) ===
    if key == dpg.mvKey_Spacebar:
        ops.play_stop()
        return
    elif key == dpg.mvKey_F1:
        from ui_dialogs import show_shortcuts
        show_shortcuts()
        return
    elif key == dpg.mvKey_F5:
        ops.play_pattern()
        return
    elif key == dpg.mvKey_F6:
        ops.play_song_start()
        return
    elif key == dpg.mvKey_F7:
        ops.play_song_here()
        return
    elif key == dpg.mvKey_F8:
        ops.stop_playback()
        return
    elif key in (dpg.mvKey_Return, dpg.mvKey_NumPadEnter):
        ops.preview_row()
        return
    
    # === SONG EDITOR SHORTCUTS ===
    if state.focus == FOCUS_SONG:
        total_songlines = len(state.song.songlines)
        if key == dpg.mvKey_Up:
            if state.song_cursor_row > 0:
                state.song_cursor_row -= 1
                state.songline = state.song_cursor_row
                ops.refresh_song_editor()
                ops.refresh_editor()
        elif key == dpg.mvKey_Down:
            if state.song_cursor_row < total_songlines - 1:
                state.song_cursor_row += 1
                state.songline = state.song_cursor_row
                ops.refresh_song_editor()
                ops.refresh_editor()
        elif key == dpg.mvKey_Left:
            if state.song_cursor_col > 0:
                state.song_cursor_col -= 1
                ops.refresh_song_editor()
        elif key == dpg.mvKey_Right:
            if state.song_cursor_col < MAX_CHANNELS - 1:
                state.song_cursor_col += 1
                ops.refresh_song_editor()
        elif key == dpg.mvKey_Home:
            state.song_cursor_row = 0
            state.songline = 0
            ops.refresh_song_editor()
            ops.refresh_editor()
        elif key == dpg.mvKey_End:
            state.song_cursor_row = total_songlines - 1
            state.songline = state.song_cursor_row
            ops.refresh_song_editor()
            ops.refresh_editor()
        elif key == dpg.mvKey_Delete:
            # Delete current songline
            if total_songlines > 1:
                ops.delete_songline()
                if state.song_cursor_row >= len(state.song.songlines):
                    state.song_cursor_row = len(state.song.songlines) - 1
                state.songline = state.song_cursor_row
                ops.refresh_all()
        elif key == dpg.mvKey_Insert:
            # Insert new songline at current position
            ops.add_songline()
            ops.refresh_all()
        # Hex digit input to change pattern
        else:
            char = KEY_MAP.get(key)
            if char and char in '0123456789abcdef':
                handle_song_hex_input(char)
        return
    
    # === EDITOR-ONLY SHORTCUTS ===
    if state.focus != FOCUS_EDITOR:
        return
    
    # Navigation
    if key == dpg.mvKey_Up:
        ops.move_cursor(-1, 0, extend_selection=shift)
    elif key == dpg.mvKey_Down:
        ops.move_cursor(1, 0, extend_selection=shift)
    elif key == dpg.mvKey_Left:
        ops.move_cursor(0, -1)
    elif key == dpg.mvKey_Right:
        ops.move_cursor(0, 1)
    elif key == dpg.mvKey_Tab:
        ops.prev_channel() if shift else ops.next_channel()
    elif key == dpg.mvKey_Prior:  # Page Up
        ops.jump_rows(-16)
    elif key == dpg.mvKey_Next:  # Page Down
        ops.jump_rows(16)
    elif key == dpg.mvKey_Home:
        ops.jump_start()
    elif key == dpg.mvKey_End:
        ops.jump_end()
    
    # Editing
    elif key == dpg.mvKey_Delete:
        ops.clear_cell()
    elif key == dpg.mvKey_Back:  # Backspace
        ops.clear_and_up()
    elif key == dpg.mvKey_Insert:
        ops.insert_row()
    
    # Octave change
    elif key == dpg.mvKey_Multiply:  # Numpad *
        ops.octave_up()
    elif key in (dpg.mvKey_Subtract, dpg.mvKey_Minus):  # Numpad - or -
        ops.octave_down()
    
    # Instrument change
    elif key == dpg.mvKey_Open_Brace:  # [
        ops.prev_instrument()
    elif key == dpg.mvKey_Close_Brace:  # ]
        ops.next_instrument()
    
    # Character input (notes and hex digits)
    else:
        char = KEY_MAP.get(key)
        if char:
            handle_char(char)


def handle_char(char: str):
    """Handle character input for notes and values."""
    char = char.lower()
    
    # Note keys (only in note column)
    if char in NOTE_KEYS and state.column == 0:
        ops.enter_note(NOTE_KEYS[char])
        return
    
    # Digits for instrument/volume columns
    if state.column > 0:
        if state.hex_mode:
            # Hex mode: 0-9 and a-f
            if char in '0123456789':
                ops.enter_digit(int(char))
            elif char in 'abcdef':
                ops.enter_digit(10 + ord(char) - ord('a'))
        else:
            # Decimal mode: only 0-9
            if char in '0123456789':
                ops.enter_digit_decimal(int(char))


def handle_song_hex_input(char: str):
    """Handle hex digit input for song editor (pattern selection)."""
    global _song_pending_digit
    
    char = char.lower()
    if char in '0123456789':
        digit = int(char)
    elif char in 'abcdef':
        digit = 10 + ord(char) - ord('a')
    else:
        return
    
    if state.hex_mode:
        # Two-digit hex entry
        if _song_pending_digit is not None:
            # Second digit - complete the value
            value = _song_pending_digit * 16 + digit
            _song_pending_digit = None
        else:
            # First digit - store and wait
            _song_pending_digit = digit
            return
    else:
        # Single digit decimal for simplicity (could do multi-digit)
        value = digit
    
    # Apply value to current cell
    if value < len(state.song.patterns):
        sl_idx = state.song_cursor_row
        ch = state.song_cursor_col
        state.song.songlines[sl_idx].patterns[ch] = value
        state.selected_pattern = value
        state.song.modified = True
        ops.refresh_song_editor()
        ops.refresh_editor()
