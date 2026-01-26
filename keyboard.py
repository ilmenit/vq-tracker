"""
Atari Sample Tracker - Keyboard Handler
Process keyboard input for notes and commands.
"""

import dearpygui.dearpygui as dpg
from typing import Optional

from constants import NOTE_KEYS
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


def handle_key(sender, key):
    """Handle key press event."""
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
    
    # Ctrl shortcuts
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
            ops.copy_row()
        elif key == dpg.mvKey_X:
            ops.cut_row()
        elif key == dpg.mvKey_V:
            ops.paste_row()
        elif key == dpg.mvKey_Home:
            ops.jump_first_songline()
        elif key == dpg.mvKey_End:
            ops.jump_last_songline()
        return
    
    # Navigation
    if key == dpg.mvKey_Up:
        ops.move_cursor(-1, 0)
    elif key == dpg.mvKey_Down:
        ops.move_cursor(1, 0)
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
    
    # Playback
    elif key == dpg.mvKey_Spacebar:
        ops.play_stop()
    elif key == dpg.mvKey_F1:
        from ui_dialogs import show_shortcuts
        show_shortcuts()
    elif key == dpg.mvKey_F5:
        ops.play_pattern()
    elif key == dpg.mvKey_F6:
        ops.play_song_start()
    elif key == dpg.mvKey_F7:
        ops.play_song_here()
    elif key == dpg.mvKey_F8:
        ops.stop_playback()
    elif key == dpg.mvKey_Return or key == dpg.mvKey_NumPadEnter:
        ops.preview_row()
    
    # Octave
    elif key == dpg.mvKey_Multiply:
        ops.octave_up()
    elif key in (dpg.mvKey_Subtract, dpg.mvKey_Minus):
        ops.octave_down()
    
    # Instrument
    elif key == dpg.mvKey_Open_Brace:
        ops.prev_inst()
    elif key == dpg.mvKey_Close_Brace:
        ops.next_inst()
    
    # Character input
    else:
        char = KEY_MAP.get(key)
        if char:
            handle_char(char)


def handle_char(char: str):
    """Handle character input for notes and values."""
    char = char.lower()
    
    # Note keys
    if char in NOTE_KEYS:
        ops.enter_note(NOTE_KEYS[char])
        return
    
    # Hex digits for inst/vol columns
    if state.column > 0:
        if char in '0123456789':
            ops.enter_digit(int(char))
        elif char in 'abcdef':
            ops.enter_digit(10 + ord(char) - ord('a'))
