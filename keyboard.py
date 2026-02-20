"""POKEY VQ Tracker - Keyboard Handler

Action shortcuts (playback, file ops, octave) are loaded from keyboard.json
via key_config module.  Navigation and note-input keys stay hardcoded.
"""
import dearpygui.dearpygui as dpg
from constants import (NOTE_KEYS, FOCUS_EDITOR, FOCUS_SONG, FOCUS_INSTRUMENTS,
                       MAX_CHANNELS, MAX_VOLUME, MAX_NOTES, NOTE_OFF)
from state import state
import ops
import ui_refresh as R
import ui_globals as G
import key_config
import dpg_keys

# ── Key-to-character mapping — built at init from resolved constants ─────
# Populated by init_keys() after DPG context is created.
KEY_MAP = {}

# F-keys (F1–F12) — used to gate the global playback bypass.
# Only F-keys can bypass text input / modal / sample editor gates, because
# they are never valid text-entry characters.  If a user remaps play_song
# to a letter key, it must NOT fire during text input.
_F_KEYS = set()
for _i in range(1, 26):
    _k = getattr(dpg, f'mvKey_F{_i}', None)
    if _k is not None:
        _F_KEYS.add(_k)

# ── All known modal dialog tags ──────────────────────────────────────────
# Single source of truth: used by Space-key gate AND the general modal skip.
# When adding a new modal dialog anywhere in the codebase, add its tag here.
_MODAL_DIALOG_TAGS = (
    # Cell popups
    "popup_inst", "popup_vol", "popup_note", "popup_song_ptn", "popup_spd",
    # Confirmation / error / info / rename
    "confirm_dlg", "rename_dlg", "error_dlg",
    "confirm_dialog", "error_dialog", "info_dialog", "rename_dialog",
    # Help & about
    "about_dialog", "shortcuts_dialog",
    # Settings
    "settings_dialog",
    # Build & VQ conversion (may contain selectable output text)
    "build_progress_window", "build_validation_dlg",
    "vq_conv_window",
    # MOD import wizard
    "mod_import_result",
    # Autosave recovery
    "autosave_dialog",
)

# Shift-modified character overrides (same physical key, different char)
# Only includes mappings where we need the shifted character for tracker input.
# We intentionally do NOT map shift+numbers to symbols — digits must stay
# as digits for hex/decimal entry even when shift is held.
_SHIFT_MAP = {
    '`': '~',   # Grave → Tilde  (V-- entry)
}


def init_keys():
    """Build KEY_MAP from resolved DPG key constants.
    
    Must be called after dpg_keys.init() (i.e. after dpg.create_context).
    """
    global KEY_MAP
    KEY_MAP = dpg_keys.build_key_map()

# ── Song-editor pending hex state ────────────────────────────────────────────
_song_pending_digit = None
_song_digit_count = 0


def clear_song_pending():
    """Clear pending digit state for song editor."""
    global _song_pending_digit, _song_digit_count
    _song_pending_digit = None
    _song_digit_count = 0


# ═════════════════════════════════════════════════════════════════════════════
# ACTION DISPATCH TABLE  (action name → callable)
# ═════════════════════════════════════════════════════════════════════════════

def _mk_octave(n):
    def _set():
        ops.set_octave(n)
        G.show_status(f"Octave: {state.octave}")
    return _set

def _show_help():
    from ui_dialogs import show_shortcuts
    show_shortcuts()

ACTION_HANDLERS = {
    # File
    "new_project":          lambda: ops.new_song(),
    "open_project":         lambda: ops.open_song(),
    "save_project":         lambda: ops.save_song(),
    "save_project_as":      lambda: ops.save_song_as(),
    "undo":                 lambda: ops.undo(),
    "redo":                 lambda: ops.redo(),
    "copy":                 lambda: ops.copy_cells(),
    "cut":                  lambda: ops.cut_cells(),
    "paste":                lambda: ops.paste_cells(),
    "select_all":           lambda: ops.select_all(),
    "toggle_follow":        lambda: ops.toggle_follow(),
    "jump_first_songline":  lambda: ops.jump_first_songline(),
    "jump_last_songline":   lambda: ops.jump_last_songline(),
    "step_up":              lambda: ops.change_step(1),
    "step_down":            lambda: ops.change_step(-1),
    # Octave (3 octaves supported)
    "octave_1": _mk_octave(1),
    "octave_2": _mk_octave(2),
    "octave_3": _mk_octave(3),
    # Playback
    "play_song":            lambda: ops.play_song_start(),
    "play_pattern":         lambda: ops.play_pattern(),
    "play_from_cursor":     lambda: ops.play_song_here(),
    "stop":                 lambda: ops.stop_playback(),
    "play_stop_toggle":     lambda: ops.play_stop(),
    "preview_row":          lambda: ops.preview_row(),
    # Other
    "show_help":            _show_help,
}

# Actions that work regardless of focus, text input, modals, or sample editor.
# These bypass ALL input gates.  Only non-text keys (F-keys) belong here;
# Space/Enter are handled separately because they ARE valid text characters.
_GLOBAL_ACTIONS = frozenset({
    "play_song",          # F5
    "play_pattern",       # F6
    "play_from_cursor",   # F7
    "stop",               # F8
})


# ═════════════════════════════════════════════════════════════════════════════
# MAIN KEY HANDLER
# ═════════════════════════════════════════════════════════════════════════════

def handle_key(sender, key):
    """Handle key press event."""

    # ── Escape: stop playback / close popups / clear selection ────────────
    if key == dpg.mvKey_Escape:
        if state.audio.is_playing():
            ops.stop_playback()
            return
        for tag in ("popup_inst", "popup_vol", "popup_note",
                    "popup_song_ptn", "popup_spd"):
            if dpg.does_item_exist(tag):
                try:
                    dpg.delete_item(tag)
                    state.set_input_active(False)
                    return
                except:
                    pass
        # Close sample editor on Escape
        try:
            if (dpg.does_item_exist("sample_editor_win") and
                    dpg.is_item_shown("sample_editor_win")):
                from sample_editor.ui_editor import handle_editor_key
                handle_editor_key(key)
                return
        except Exception:
            pass
        if state.selection.active:
            state.selection.clear()
            R.refresh_editor()
            return

    # ── GLOBAL PLAYBACK ACTIONS ───────────────────────────────────────────
    # F5/F6/F7/F8 always work, regardless of focus, text input, modals,
    # or sample editor. Only F-keys bypass all gates — letter/number keys
    # must respect text input fields even if mapped to playback actions.
    ctrl  = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
    if not ctrl and not shift and key in _F_KEYS:
        action = key_config.get_action(key, False, False)
        if action in _GLOBAL_ACTIONS:
            handler = ACTION_HANDLERS.get(action)
            if handler:
                handler()
                return

    # ── Space as play/stop — global EXCEPT in text inputs, sample editor,
    #    instrument panel (when stopped), or modal dialogs (when stopped).
    #    When audio IS playing, Space ALWAYS stops regardless of context.
    if key == dpg.mvKey_Spacebar and not ctrl and not shift:
        in_text = state.input_active
        if not in_text:
            for tag in ("title_input", "author_input", "step_input",
                        "ptn_len_input", "start_address_input"):
                try:
                    if dpg.does_item_exist(tag) and (dpg.is_item_active(tag) or
                                                      dpg.is_item_focused(tag)):
                        in_text = True
                        break
                except:
                    pass
        in_sample_editor = False
        try:
            in_sample_editor = (dpg.does_item_exist("sample_editor_win") and
                                dpg.is_item_shown("sample_editor_win"))
        except Exception:
            pass
        # When playing, Space = stop (always, even from instrument panel/modals)
        # When stopped + instrument panel, let it fall through to preview
        in_inst_panel = (state.focus == FOCUS_INSTRUMENTS and
                         not state.audio.is_playing())
        # Block Space from starting playback during modal dialogs
        in_modal = False
        if not state.audio.is_playing():
            for tag in _MODAL_DIALOG_TAGS:
                try:
                    if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                        in_modal = True
                        break
                except:
                    pass
        if not in_text and not in_sample_editor and not in_inst_panel and not in_modal:
            action = key_config.get_action(key, False, False)
            if action and action in ACTION_HANDLERS:
                ACTION_HANDLERS[action]()
                return

    # ── Skip while typing in a text field ─────────────────────────────────
    if state.input_active:
        # Safety: verify a text field is actually focused.
        # DPG's deactivated_handler can miss events (window focus loss,
        # dialog open), leaving input_active stuck.  If no field is
        # active, clear the flag and continue processing the key.
        any_field_active = False
        for tag in ("title_input", "author_input", "step_input",
                    "ptn_len_input", "start_address_input"):
            try:
                if dpg.does_item_exist(tag) and (dpg.is_item_active(tag) or
                                                  dpg.is_item_focused(tag)):
                    any_field_active = True
                    break
            except:
                pass
        if any_field_active:
            return
        # Flag was stale — clear it and continue
        state.set_input_active(False)
    for tag in ("title_input", "author_input", "step_input", "ptn_len_input",
                "start_address_input"):
        try:
            if dpg.does_item_exist(tag) and (dpg.is_item_active(tag) or dpg.is_item_focused(tag)):
                return
        except:
            pass

    # ── Skip while a modal dialog is open ─────────────────────────────────
    for tag in _MODAL_DIALOG_TAGS:
        try:
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                return
        except:
            pass

    # ── Sample editor: forward remaining keys ─────────────────────────────
    try:
        if (dpg.does_item_exist("sample_editor_win") and
                dpg.is_item_shown("sample_editor_win")):
            from sample_editor.ui_editor import handle_editor_key
            handle_editor_key(key)
            return
    except Exception:
        pass

    # ── INSTRUMENT PANEL: intercept instrument-specific keys first ────────
    # Space/Enter play instrument preview, arrows navigate, piano keys play.
    # F-keys and Ctrl combos are NOT consumed → fall through to action lookup.
    if state.focus == FOCUS_INSTRUMENTS and not ctrl:
        if _handle_instruments_key(key, shift):
            return

    # ── Configurable action lookup (from keyboard.json) ───────────────────
    action = key_config.get_action(key, ctrl, shift)
    # NumpadEnter is a transparent alias for Enter in action lookup
    if action is None and key == dpg_keys.get('mvKey_NumPadEnter'):
        action = key_config.get_action(dpg.mvKey_Return, ctrl, shift)
    if action:
        handler = ACTION_HANDLERS.get(action)
        if handler:
            handler()
            return

    # ── Ctrl+Arrow: jump by step (hardcoded, context-dependent) ───────────
    if ctrl and not shift:
        if key == dpg.mvKey_Up and state.focus == FOCUS_EDITOR:
            ops.jump_rows(-state.step)
            return
        if key == dpg.mvKey_Down and state.focus == FOCUS_EDITOR:
            ops.jump_rows(state.step)
            return

    # Any remaining Ctrl combos that weren't matched — ignore to avoid
    # Ctrl+letter accidentally entering notes
    if ctrl:
        return

    # If instrument panel and we get here, the key wasn't consumed by
    # _handle_instruments_key and wasn't a configurable action — ignore
    if state.focus == FOCUS_INSTRUMENTS:
        return

    # ── SONG EDITOR (navigation + hex entry — not configurable) ───────────
    if state.focus == FOCUS_SONG:
        _handle_song_key(key)
        return

    # ── PATTERN EDITOR ────────────────────────────────────────────────────
    if state.focus != FOCUS_EDITOR:
        return

    # Navigation
    if   key == dpg.mvKey_Up:    ops.move_cursor(-1, 0, extend_selection=shift)
    elif key == dpg.mvKey_Down:  ops.move_cursor( 1, 0, extend_selection=shift)
    elif key == dpg.mvKey_Left:  ops.move_cursor(0, -1, extend_selection=shift)
    elif key == dpg.mvKey_Right: ops.move_cursor(0,  1, extend_selection=shift)
    elif key == dpg.mvKey_Tab:
        ops.prev_channel() if shift else ops.next_channel()
    elif key == dpg_keys.get('mvKey_Prior'): ops.jump_rows(-G.visible_rows)
    elif key == dpg_keys.get('mvKey_Next'):  ops.jump_rows( G.visible_rows)
    elif key == dpg.mvKey_Home:  ops.jump_start()
    elif key == dpg.mvKey_End:   ops.jump_end()

    # Editing
    elif key == dpg.mvKey_Delete:
        ops.delete_row()
    elif key == dpg_keys.get('mvKey_Back'):
        ops.clear_cell()
        ops.jump_rows(-state.step)
    elif key == dpg.mvKey_Insert:
        ops.insert_row()

    # Octave change (numpad special keys — not configurable editing keys)
    elif key == dpg.mvKey_Multiply: ops.octave_up()
    elif key == dpg.mvKey_Add:      ops.octave_up()
    elif key in (dpg.mvKey_Subtract, dpg_keys.get('mvKey_Minus', -1)): ops.octave_down()

    # Instrument change
    elif key == dpg_keys.get('mvKey_Open_Brace'):  ops.prev_instrument()
    elif key == dpg_keys.get('mvKey_Close_Brace'): ops.next_instrument()

    # Character input (notes, hex digits, octave change, note-off)
    else:
        char = KEY_MAP.get(key)
        if char:
            # Apply shift to get shifted character (e.g. ` → ~)
            if shift and char in _SHIFT_MAP:
                char = _SHIFT_MAP[char]
            handle_char(char)


# ═════════════════════════════════════════════════════════════════════════════
# INSTRUMENT PANEL KEYS
# ═════════════════════════════════════════════════════════════════════════════

def _handle_instruments_key(key, shift):
    """Handle instrument-panel-specific keys.
    
    Returns True if the key was consumed, False to let it fall through
    to the configurable action lookup (e.g. F-keys should still work).
    """
    total = len(state.song.instruments)
    if total == 0:
        # Even with no instruments, consume nav keys so they don't trigger actions
        if key in (dpg.mvKey_Spacebar, dpg.mvKey_Return, dpg_keys.get('mvKey_NumPadEnter'),
                   dpg.mvKey_Up, dpg.mvKey_Down, dpg_keys.get('mvKey_Prior'),
                   dpg_keys.get('mvKey_Next'),
                   dpg.mvKey_Home, dpg.mvKey_End):
            return True
        return False

    if key == dpg.mvKey_Spacebar or key in (dpg.mvKey_Return, dpg_keys.get('mvKey_NumPadEnter')):
        _play_instrument_preview(1)
        return True
    elif key == dpg.mvKey_Up:
        if state.instrument > 0:
            state.instrument -= 1; ops.refresh_instruments()
        return True
    elif key == dpg.mvKey_Down:
        if state.instrument < total - 1:
            state.instrument += 1; ops.refresh_instruments()
        return True
    elif key == dpg_keys.get('mvKey_Prior'):
        state.instrument = max(0, state.instrument - 8); ops.refresh_instruments()
        return True
    elif key == dpg_keys.get('mvKey_Next'):
        state.instrument = min(total - 1, state.instrument + 8); ops.refresh_instruments()
        return True
    elif key == dpg.mvKey_Home:
        state.instrument = 0; ops.refresh_instruments()
        return True
    elif key == dpg.mvKey_End:
        state.instrument = total - 1; ops.refresh_instruments()
        return True
    else:
        char = KEY_MAP.get(key)
        if char:
            semitone = NOTE_KEYS.get(char)
            if semitone is not None:
                actual_note = (state.octave - 1) * 12 + semitone + 1
                if 1 <= actual_note <= MAX_NOTES:
                    _play_instrument_preview(actual_note)
                return True
        return False  # Let F-keys, etc. fall through to action lookup


def _play_instrument_preview(note: int):
    if state.instrument < len(state.song.instruments):
        inst = state.song.instruments[state.instrument]
        if inst.is_loaded():
            state.audio.preview_note(0, note, inst, MAX_VOLUME)


# ═════════════════════════════════════════════════════════════════════════════
# SONG EDITOR KEYS
# ═════════════════════════════════════════════════════════════════════════════

def _handle_song_key(key):
    total_songlines = len(state.song.songlines)
    max_col = MAX_CHANNELS  # Columns: 0=C1 .. 3=C4, 4=SPD

    if key == dpg.mvKey_Up:
        clear_song_pending()
        if state.song_cursor_row > 0:
            state.song_cursor_row -= 1
            state.songline = state.song_cursor_row
            ops.refresh_song_editor(); ops.refresh_editor()
    elif key == dpg.mvKey_Down:
        clear_song_pending()
        if state.song_cursor_row < total_songlines - 1:
            state.song_cursor_row += 1
            state.songline = state.song_cursor_row
            ops.refresh_song_editor(); ops.refresh_editor()
    elif key == dpg.mvKey_Left:
        clear_song_pending()
        if state.song_cursor_col > 0:
            state.song_cursor_col -= 1; ops.refresh_song_editor()
    elif key == dpg.mvKey_Right:
        clear_song_pending()
        if state.song_cursor_col < max_col:
            state.song_cursor_col += 1; ops.refresh_song_editor()
    elif key == dpg.mvKey_Home:
        clear_song_pending()
        state.song_cursor_row = 0; state.songline = 0
        ops.refresh_song_editor(); ops.refresh_editor()
    elif key == dpg.mvKey_End:
        clear_song_pending()
        state.song_cursor_row = total_songlines - 1
        state.songline = state.song_cursor_row
        ops.refresh_song_editor(); ops.refresh_editor()
    elif key == dpg_keys.get('mvKey_Prior'):
        clear_song_pending()
        state.song_cursor_row = max(0, state.song_cursor_row - G.SONG_VISIBLE_ROWS)
        state.songline = state.song_cursor_row
        ops.refresh_song_editor(); ops.refresh_editor()
    elif key == dpg_keys.get('mvKey_Next'):
        clear_song_pending()
        state.song_cursor_row = min(total_songlines - 1, state.song_cursor_row + G.SONG_VISIBLE_ROWS)
        state.songline = state.song_cursor_row
        ops.refresh_song_editor(); ops.refresh_editor()
    elif key == dpg.mvKey_Delete:
        clear_song_pending()
        if total_songlines > 1:
            ops.delete_songline()
            if state.song_cursor_row >= len(state.song.songlines):
                state.song_cursor_row = len(state.song.songlines) - 1
            state.songline = state.song_cursor_row
            ops.refresh_all()
    elif key == dpg.mvKey_Insert:
        clear_song_pending()
        ops.add_songline(); ops.refresh_all()
    else:
        char = KEY_MAP.get(key)
        if char and char in '0123456789abcdef':
            handle_song_hex_input(char)


# ═════════════════════════════════════════════════════════════════════════════
# NOTE / HEX CHARACTER INPUT
# ═════════════════════════════════════════════════════════════════════════════

def handle_char(char: str):
    """Handle character input for notes and values.

    Special keys (work in any column):
      ` (backtick) enters note-off (only in note column)
      = or + raises octave,  - lowers octave
    """
    char_lower = char.lower()

    # Octave change
    if char in '=+*':
        ops.octave_up(); return
    if char == '-':
        ops.octave_down(); return

    # Note-off via backtick
    if char == '`' and state.column == 0:
        ops.enter_note_off(); return

    # Volume-change via tilde (Shift+backtick)
    if char == '~' and state.column == 0:
        ops.enter_vol_change(); return

    # Note column
    if state.column == 0:
        if not G.piano_keys_mode and char_lower == '1':
            ops.enter_note_off(); return
        if not G.piano_keys_mode and char_lower in '23':
            ops.set_octave(int(char_lower))
            G.show_status(f"Octave: {state.octave}"); return
        if char_lower in NOTE_KEYS:
            if not G.piano_keys_mode and char_lower in '2356790':
                return
            ops.enter_note(NOTE_KEYS[char_lower]); return

    # Instrument / volume columns
    if state.column > 0:
        if state.hex_mode:
            if char_lower in '0123456789':
                ops.enter_digit(int(char_lower))
            elif char_lower in 'abcdef':
                ops.enter_digit(10 + ord(char_lower) - ord('a'))
        else:
            if char_lower in '0123456789':
                ops.enter_digit_decimal(int(char_lower))


# ═════════════════════════════════════════════════════════════════════════════
# SONG EDITOR HEX INPUT
# ═════════════════════════════════════════════════════════════════════════════

def handle_song_hex_input(char: str):
    """Handle digit input for song editor (pattern selection)."""
    global _song_pending_digit, _song_digit_count
    char = char.lower()

    if state.hex_mode:
        if char in '0123456789':
            digit = int(char)
        elif char in 'abcdef':
            digit = 10 + ord(char) - ord('a')
        else:
            return

        if _song_pending_digit is not None:
            value = _song_pending_digit * 16 + digit
            _apply_song_pattern_value(value)
            _song_pending_digit = None
        else:
            ops.save_undo("Edit song")
            _song_pending_digit = digit
            _show_song_partial_value(digit)
    else:
        if char in '0123456789':
            digit = int(char)
        else:
            return

        if _song_pending_digit is not None:
            if _song_digit_count >= 2:
                value = _song_pending_digit * 10 + digit
                _apply_song_pattern_value(value)
                _song_pending_digit = None
                _song_digit_count = 0
            else:
                _song_pending_digit = _song_pending_digit * 10 + digit
                _song_digit_count += 1
                _show_song_partial_value(_song_pending_digit)
        else:
            ops.save_undo("Edit song")
            _song_pending_digit = digit
            _song_digit_count = 1
            _show_song_partial_value(digit)


def _show_song_partial_value(value: int):
    sl_idx = state.song_cursor_row
    col = state.song_cursor_col
    if col == MAX_CHANNELS:
        if value >= 1:
            state.song.songlines[sl_idx].speed = value
            state.song.modified = True
    elif col < MAX_CHANNELS:
        if value < len(state.song.patterns):
            state.song.songlines[sl_idx].patterns[col] = value
            state.song.modified = True
    ops.refresh_song_editor()


def _apply_song_pattern_value(value: int):
    sl_idx = state.song_cursor_row
    col = state.song_cursor_col
    if col == MAX_CHANNELS:
        value = max(1, min(255, value))
        state.song.songlines[sl_idx].speed = value
        state.song.modified = True
    elif col < MAX_CHANNELS:
        if value < len(state.song.patterns):
            state.song.songlines[sl_idx].patterns[col] = value
            state.selected_pattern = value
            state.song.modified = True
    ops.refresh_song_editor()
