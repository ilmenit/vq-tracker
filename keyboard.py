"""POKEY VQ Tracker - Keyboard Handler"""
import dearpygui.dearpygui as dpg
from constants import NOTE_KEYS, FOCUS_EDITOR, FOCUS_SONG, FOCUS_INSTRUMENTS, MAX_CHANNELS, MAX_VOLUME, MAX_NOTES, NOTE_OFF
from state import state
import operations as ops
import ui_refresh as R
import ui_globals as G

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
    # Special keys for octave/note-off
    # DearPyGUI key constants
    dpg.mvKey_Minus: '-',
    dpg.mvKey_Subtract: '-',
    dpg.mvKey_Add: '+',
    dpg.mvKey_Multiply: '*',
    # Actual key codes discovered on user's system (DearPyGUI internal codes)
    606: '`',   # Backtick/grave accent key
    602: '=',   # Equal/plus key (=/+ on same physical key)
    # GLFW codes (may vary by platform)
    96: '`',    # GLFW_KEY_GRAVE_ACCENT
    45: '-',    # GLFW_KEY_MINUS
    61: '=',    # GLFW_KEY_EQUAL
}

# Keys that need special handling (checked by keycode directly)
# Backtick/grave accent key for note-off
# DearPyGUI uses GLFW key codes internally: GLFW_KEY_GRAVE_ACCENT = 96
KEY_GRAVE = 96

# Pending hex digit for song editor
_song_pending_digit = None
_song_digit_count = 0  # Track number of digits entered in decimal mode


def clear_song_pending():
    """Clear pending digit state for song editor."""
    global _song_pending_digit, _song_digit_count
    _song_pending_digit = None
    _song_digit_count = 0


def handle_key(sender, key):
    """Handle key press event."""
    
    # === ESCAPE KEY - Stop playback or close popups ===
    if key == dpg.mvKey_Escape:
        # First priority: stop playback if playing
        if state.audio.is_playing():
            ops.stop_playback()
            return
        
        # Check for and close any open popups
        popup_tags = ["popup_inst", "popup_vol", "popup_note", "popup_song_ptn", "popup_spd"]
        for tag in popup_tags:
            if dpg.does_item_exist(tag):
                try:
                    dpg.delete_item(tag)
                    state.set_input_active(False)
                    return
                except:
                    pass
        # If no popup, Escape can be used for other things (like clearing selection)
        if state.selection.active:
            state.selection.clear()
            R.refresh_editor()
            return
    
    # Skip if typing in a text field - check both our flag and DPG's active item detection
    if state.input_active:
        return
    
    # Additional check: see if any input-related item has keyboard focus
    # This catches cases where our callback didn't fire
    input_tags = ["title_input", "author_input", "step_input", "ptn_len_input"]
    try:
        for tag in input_tags:
            if dpg.does_item_exist(tag):
                if dpg.is_item_active(tag) or dpg.is_item_focused(tag):
                    return
    except:
        pass
    
    # Also check if a popup or modal is open (file dialogs, etc.)
    # This is harder to detect, but we can check for common popup tags
    popup_tags = ["popup_inst", "popup_vol", "popup_note", "popup_song_ptn", "popup_spd",
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
        # Ctrl+Shift+Arrow: Change Step (works anywhere)
        elif key == dpg.mvKey_Up and shift:
            ops.change_step(1)
        elif key == dpg.mvKey_Down and shift:
            ops.change_step(-1)
        # Ctrl+Arrow: Jump by Step rows (pattern editor only)
        elif key == dpg.mvKey_Up and state.focus == FOCUS_EDITOR:
            ops.jump_rows(-state.step)
        elif key == dpg.mvKey_Down and state.focus == FOCUS_EDITOR:
            ops.jump_rows(state.step)
        return
    
    # === OCTAVE SELECTION (F1-F4) - Always available ===
    # F1=Octave 1, F2=Octave 2, F3=Octave 3, F4=Octave 4
    if key == dpg.mvKey_F1:
        ops.set_octave(1)
        G.show_status("Octave: 1")
        return
    elif key == dpg.mvKey_F2:
        ops.set_octave(2)
        G.show_status("Octave: 2")
        return
    elif key == dpg.mvKey_F3:
        ops.set_octave(3)
        G.show_status("Octave: 3")
        return
    elif key == dpg.mvKey_F4:
        ops.set_octave(4)
        G.show_status("Octave: 4")
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
    elif key == dpg.mvKey_F12:
        # F12 shows help/keyboard shortcuts
        from ui_dialogs import show_shortcuts
        show_shortcuts()
        return
    
    # === INSTRUMENTS SHORTCUTS ===
    if state.focus == FOCUS_INSTRUMENTS:
        total_instruments = len(state.song.instruments)
        if total_instruments > 0:
            if key == dpg.mvKey_Spacebar or key in (dpg.mvKey_Return, dpg.mvKey_NumPadEnter):
                # Play at C-1 (note 1)
                _play_instrument_preview(1)
            elif key == dpg.mvKey_Up:
                if state.instrument > 0:
                    state.instrument -= 1
                    ops.refresh_instruments()
            elif key == dpg.mvKey_Down:
                if state.instrument < total_instruments - 1:
                    state.instrument += 1
                    ops.refresh_instruments()
            elif key == dpg.mvKey_Prior:  # Page Up
                state.instrument = max(0, state.instrument - 8)
                ops.refresh_instruments()
            elif key == dpg.mvKey_Next:  # Page Down
                state.instrument = min(total_instruments - 1, state.instrument + 8)
                ops.refresh_instruments()
            elif key == dpg.mvKey_Home:
                state.instrument = 0
                ops.refresh_instruments()
            elif key == dpg.mvKey_End:
                state.instrument = total_instruments - 1
                ops.refresh_instruments()
            else:
                # Piano keys - play notes like in pattern editor
                char = KEY_MAP.get(key)
                if char:
                    semitone = NOTE_KEYS.get(char)
                    if semitone is not None:
                        # Calculate actual note based on octave (same formula as enter_note)
                        actual_note = (state.octave - 1) * 12 + semitone + 1
                        if 1 <= actual_note <= MAX_NOTES:
                            _play_instrument_preview(actual_note)
        # Always return when in FOCUS_INSTRUMENTS
        return
    
    # === PLAYBACK (SONG/EDITOR focus) ===
    if key == dpg.mvKey_Spacebar:
        ops.play_stop()
        return
    elif key in (dpg.mvKey_Return, dpg.mvKey_NumPadEnter):
        ops.preview_row()
        return
    
    # === SONG EDITOR SHORTCUTS ===
    if state.focus == FOCUS_SONG:
        total_songlines = len(state.song.songlines)
        # Columns: 0=C1, 1=C2, 2=C3, 3=SPD
        max_col = 3  # SPD column
        if key == dpg.mvKey_Up:
            clear_song_pending()
            if state.song_cursor_row > 0:
                state.song_cursor_row -= 1
                state.songline = state.song_cursor_row
                ops.refresh_song_editor()
                ops.refresh_editor()
        elif key == dpg.mvKey_Down:
            clear_song_pending()
            if state.song_cursor_row < total_songlines - 1:
                state.song_cursor_row += 1
                state.songline = state.song_cursor_row
                ops.refresh_song_editor()
                ops.refresh_editor()
        elif key == dpg.mvKey_Left:
            clear_song_pending()
            if state.song_cursor_col > 0:
                state.song_cursor_col -= 1
                ops.refresh_song_editor()
        elif key == dpg.mvKey_Right:
            clear_song_pending()
            if state.song_cursor_col < max_col:
                state.song_cursor_col += 1
                ops.refresh_song_editor()
        elif key == dpg.mvKey_Home:
            clear_song_pending()
            state.song_cursor_row = 0
            state.songline = 0
            ops.refresh_song_editor()
            ops.refresh_editor()
        elif key == dpg.mvKey_End:
            clear_song_pending()
            state.song_cursor_row = total_songlines - 1
            state.songline = state.song_cursor_row
            ops.refresh_song_editor()
            ops.refresh_editor()
        elif key == dpg.mvKey_Delete:
            clear_song_pending()
            # Delete current songline
            if total_songlines > 1:
                ops.delete_songline()
                if state.song_cursor_row >= len(state.song.songlines):
                    state.song_cursor_row = len(state.song.songlines) - 1
                state.songline = state.song_cursor_row
                ops.refresh_all()
        elif key == dpg.mvKey_Insert:
            clear_song_pending()
            # Insert new songline at current position
            ops.add_songline()
            ops.refresh_all()
        # Hex digit input to change pattern or speed
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
        # Delete: Remove cell and shift others up (new empty row at end)
        ops.delete_row()
    elif key == dpg.mvKey_Back:  # Backspace
        # Backspace: Clear cell and jump up by Step rows
        ops.clear_cell()
        ops.jump_rows(-state.step)
    elif key == dpg.mvKey_Insert:
        # Insert: Add empty cell and shift others down
        ops.insert_row()
    
    # Octave change
    # Support both numpad and regular keyboard keys
    # Regular keyboard: - (minus) for down, = or + (with shift) for up
    # Numpad: - (subtract) for down, + (add) for up
    # Note: Also handled in handle_char() as fallback
    elif key == dpg.mvKey_Multiply:  # Numpad *
        ops.octave_up()
    elif key == dpg.mvKey_Add:  # Numpad +
        ops.octave_up()
    elif key in (dpg.mvKey_Subtract, dpg.mvKey_Minus):  # Numpad -, regular -
        ops.octave_down()
    
    # Instrument change
    elif key == dpg.mvKey_Open_Brace:  # [
        ops.prev_instrument()
    elif key == dpg.mvKey_Close_Brace:  # ]
        ops.next_instrument()
    
    # Note-off key: handled in handle_char() now
    
    # Character input (notes, hex digits, octave change, note-off)
    else:
        char = KEY_MAP.get(key)
        if char:
            handle_char(char)
        # Uncomment for debugging unknown keys:
        # else:
        #     print(f"DEBUG: Unhandled key code: {key}")


def _play_instrument_preview(note: int):
    """Play the currently selected instrument at the given note."""
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        if inst.is_loaded():
            state.audio.preview_note(0, note, inst, MAX_VOLUME)


def handle_char(char: str):
    """Handle character input for notes and values.
    
    Key behavior depends on G.piano_keys_mode:
    - Piano mode (True): Number keys 2,3,5,6,7,9,0 play sharp notes
    - Tracker mode (False): Number keys 1,2,3 select octave, '1' enters note-off in note column
    
    Special keys (work in any column):
    - Backtick (`) enters note-off (only in note column)
    - = or + raises octave
    - - lowers octave
    """
    # Don't lowercase special characters
    char_lower = char.lower()
    
    # === SPECIAL KEYS (work in any column) ===
    
    # Octave change: = or + (up), - (down)
    if char in '=+*':
        ops.octave_up()
        return
    if char == '-':
        ops.octave_down()
        return
    
    # Note-off: backtick (only in note column)
    if char == '`' and state.column == 0:
        ops.enter_note_off()
        return
    
    # === NOTE COLUMN ===
    if state.column == 0:
        # Tracker mode special handling for '1' key = note-off
        if not G.piano_keys_mode and char_lower == '1':
            ops.enter_note_off()
            return
        
        # Tracker mode: '2', '3', '4' select octave (but only if not in NOTE_KEYS)
        if not G.piano_keys_mode and char_lower in '234':
            octave = int(char_lower)
            ops.set_octave(octave)
            G.show_status(f"Octave: {octave}")
            return
        
        # Piano mode: all NOTE_KEYS work normally
        # Tracker mode: NOTE_KEYS without number sharps work
        if char_lower in NOTE_KEYS:
            # In tracker mode, skip number keys (they're used for octave selection)
            if not G.piano_keys_mode and char_lower in '2356790':
                return  # Ignore - these don't play notes in tracker mode
            ops.enter_note(NOTE_KEYS[char_lower])
            return
    
    # === INSTRUMENT/VOLUME COLUMNS ===
    if state.column > 0:
        if state.hex_mode:
            # Hex mode: 0-9 and a-f
            if char_lower in '0123456789':
                ops.enter_digit(int(char_lower))
            elif char_lower in 'abcdef':
                ops.enter_digit(10 + ord(char_lower) - ord('a'))
        else:
            # Decimal mode: only 0-9
            if char_lower in '0123456789':
                ops.enter_digit_decimal(int(char_lower))


def handle_song_hex_input(char: str):
    """Handle digit input for song editor (pattern selection).
    
    Uses same logic as PATTERN EDITOR digit entry:
    - Hex mode: 2 digits (00-FF)
    - Decimal mode: 3 digits (000-255)
    """
    global _song_pending_digit, _song_digit_count
    
    char = char.lower()
    
    if state.hex_mode:
        # Hex mode: accept 0-9 and a-f
        if char in '0123456789':
            digit = int(char)
        elif char in 'abcdef':
            digit = 10 + ord(char) - ord('a')
        else:
            return
        
        # Two-digit hex entry (like instrument in PATTERN EDITOR)
        if _song_pending_digit is not None:
            # Second digit - complete the value
            value = _song_pending_digit * 16 + digit
            _apply_song_pattern_value(value)
            _song_pending_digit = None
        else:
            # First digit - store and show partial
            _song_pending_digit = digit
            _show_song_partial_value(digit)
    else:
        # Decimal mode: accept 0-9 only
        if char in '0123456789':
            digit = int(char)
        else:
            return
        
        # Three-digit decimal entry (000-255, like instrument in PATTERN EDITOR)
        if _song_pending_digit is not None:
            if _song_digit_count >= 2:
                # Third digit - complete the value
                value = _song_pending_digit * 10 + digit
                _apply_song_pattern_value(value)
                _song_pending_digit = None
                _song_digit_count = 0
            else:
                # Second digit - store and show partial
                _song_pending_digit = _song_pending_digit * 10 + digit
                _song_digit_count += 1
                _show_song_partial_value(_song_pending_digit)
        else:
            # First digit - store and show partial
            _song_pending_digit = digit
            _song_digit_count = 1
            _show_song_partial_value(digit)


def _show_song_partial_value(value: int):
    """Show partial value in song cell during digit entry."""
    sl_idx = state.song_cursor_row
    col = state.song_cursor_col
    
    if col == 3:
        # SPD column: speed value (1-255)
        if value >= 1:
            state.song.songlines[sl_idx].speed = value
            state.song.modified = True
    elif col < MAX_CHANNELS:
        # Pattern columns
        if value < len(state.song.patterns):
            state.song.songlines[sl_idx].patterns[col] = value
            state.song.modified = True
    ops.refresh_song_editor()


def _apply_song_pattern_value(value: int):
    """Apply completed pattern/speed value to song cell."""
    sl_idx = state.song_cursor_row
    col = state.song_cursor_col
    
    ops.save_undo("Edit song")
    if col == 3:
        # SPD column: speed value (1-255, minimum 1)
        value = max(1, min(255, value))
        state.song.songlines[sl_idx].speed = value
        state.song.modified = True
    elif col < MAX_CHANNELS:
        # Pattern columns
        if value < len(state.song.patterns):
            state.song.songlines[sl_idx].patterns[col] = value
            state.selected_pattern = value
            state.song.modified = True
    ops.refresh_song_editor()
