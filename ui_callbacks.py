"""POKEY VQ Tracker - UI Callbacks"""
import dearpygui.dearpygui as dpg
import os
import subprocess
import logging
import time
from constants import (MAX_CHANNELS, MAX_VOLUME, MAX_ROWS, PAL_HZ, NTSC_HZ,
                       FOCUS_SONG, FOCUS_EDITOR, FOCUS_INSTRUMENTS,
                       COL_NOTE, COL_INST, COL_VOL, ROW_HEIGHT)
from state import state
import ops
import ui_globals as G
import ui_refresh as R

logger = logging.getLogger("tracker.callbacks")

# Reference to rebuild_editor_grid set by main
_rebuild_editor_grid = None
_show_confirm = None

# Last built XEX path (for RUN button)
_last_built_xex = None

# Blink state for attention buttons
_blink_state = False
_last_blink_time = 0
BLINK_INTERVAL = 0.5  # seconds


def init_callbacks(rebuild_fn, confirm_fn):
    """Initialize callback module with references."""
    global _rebuild_editor_grid, _show_confirm
    _rebuild_editor_grid = rebuild_fn
    _show_confirm = confirm_fn


# =============================================================================
# SONG EDITOR CLICK HANDLERS
# =============================================================================

def select_songline_click(sender, app_data, user_data):
    """Click on row number in song editor."""
    vis_row = user_data
    G.set_focus(FOCUS_SONG)
    
    total_songlines = len(state.song.songlines)
    half = G.SONG_VISIBLE_ROWS // 2
    start_row = max(0, state.song_cursor_row - half)
    if start_row + G.SONG_VISIBLE_ROWS > total_songlines:
        start_row = max(0, total_songlines - G.SONG_VISIBLE_ROWS)
    
    sl_idx = start_row + vis_row
    if sl_idx < total_songlines:
        state.song_cursor_row = sl_idx
        state.songline = sl_idx
        R.refresh_song_editor()
        R.refresh_editor()


def song_header_click(sender, app_data, user_data):
    """Click on column header (C1-C4, SPD) in song editor → move cursor to that column."""
    col = user_data  # 0-3 for channels, MAX_CHANNELS for SPD
    G.set_focus(FOCUS_SONG)
    state.song_cursor_col = col
    R.refresh_song_editor()


def editor_header_click(sender, app_data, user_data):
    """Click on column header (Note/Ins/Vol) in pattern editor → move cursor to that channel+column."""
    channel, column = user_data
    G.set_focus(FOCUS_EDITOR)
    state.channel = channel
    state.column = column
    state.selection.clear()
    R.refresh_editor()


def song_cell_click(sender, app_data, user_data):
    """Click on pattern cell in song editor."""
    vis_row, ch = user_data
    
    # Calculate which songline was clicked BEFORE any state changes
    total_songlines = len(state.song.songlines)
    half = G.SONG_VISIBLE_ROWS // 2
    start_row = max(0, state.song_cursor_row - half)
    if start_row + G.SONG_VISIBLE_ROWS > total_songlines:
        start_row = max(0, total_songlines - G.SONG_VISIBLE_ROWS)
    
    sl_idx = start_row + vis_row
    if sl_idx < total_songlines:
        # Set input_active BEFORE showing popup to prevent concurrent handlers
        state.set_input_active(True)
        G.set_focus(FOCUS_SONG)
        mouse_pos = dpg.get_mouse_pos(local=False)
        show_song_pattern_popup(sl_idx, ch, mouse_pos)


def show_song_pattern_popup(sl_idx: int, ch: int, pos: tuple):
    """Show pattern selection popup for song editor cell."""
    if dpg.does_item_exist("popup_song_ptn"):
        dpg.delete_item("popup_song_ptn")
    
    current_ptn = state.song.songlines[sl_idx].patterns[ch]
    items = [G.fmt(i) for i in range(len(state.song.patterns))] + ["+"]
    
    def on_select(sender, value):
        state.set_input_active(False)
        G.set_focus(FOCUS_SONG)
        
        # Update the clicked cell
        if value == "+":
            ops.save_undo("Add pattern")
            idx = state.song.add_pattern()
            if idx >= 0:
                state.song.songlines[sl_idx].patterns[ch] = idx
                state.selected_pattern = idx
        else:
            try:
                idx = int(value, 16) if state.hex_mode else int(value)
                ops.save_undo("Change pattern")
                state.song.songlines[sl_idx].patterns[ch] = idx
                state.selected_pattern = idx
                state.song.modified = True
            except: pass
        
        # NOW update cursor position and scroll
        state.song_cursor_row = sl_idx
        state.song_cursor_col = ch
        state.songline = sl_idx
        
        dpg.delete_item("popup_song_ptn")
        R.refresh_all()
    
    def on_cancel():
        """Called when popup closes without selection (click outside or Escape)."""
        state.set_input_active(False)
        # Still move cursor to clicked cell
        state.song_cursor_row = sl_idx
        state.song_cursor_col = ch
        state.songline = sl_idx
        R.refresh_song_editor()
        R.refresh_editor()
    
    # input_active already set by song_cell_click
    with dpg.window(tag="popup_song_ptn", popup=True, no_title_bar=True, modal=True,
                    pos=[int(pos[0]), int(pos[1])], min_size=(80, 150), max_size=(100, 300),
                    on_close=on_cancel):
        dpg.add_text("Pattern:")
        dpg.add_listbox(items=items, default_value=G.fmt(current_ptn),
                        num_items=min(10, len(items)), callback=on_select, width=-1)


def song_spd_click(sender, app_data, user_data):
    """Click on SPD cell in song editor - shows speed selection popup."""
    vis_row = user_data
    
    # Calculate which songline was clicked BEFORE any state changes
    total_songlines = len(state.song.songlines)
    half = G.SONG_VISIBLE_ROWS // 2
    start_row = max(0, state.song_cursor_row - half)
    if start_row + G.SONG_VISIBLE_ROWS > total_songlines:
        start_row = max(0, total_songlines - G.SONG_VISIBLE_ROWS)
    
    sl_idx = start_row + vis_row
    if sl_idx < total_songlines:
        # Set input_active BEFORE showing popup to prevent concurrent handlers
        state.set_input_active(True)
        G.set_focus(FOCUS_SONG)
        mouse_pos = dpg.get_mouse_pos(local=False)
        show_speed_popup(sl_idx, mouse_pos)


def show_speed_popup(sl_idx: int, pos: tuple):
    """Show speed selection popup for song editor SPD cell."""
    if dpg.does_item_exist("popup_spd"):
        dpg.delete_item("popup_spd")
    
    current_spd = state.song.songlines[sl_idx].speed
    # Show common values 1-10 in list (keyboard can enter any value 1-255)
    items = [G.fmt(i) for i in range(1, 11)]
    
    def on_select(sender, value):
        state.set_input_active(False)
        G.set_focus(FOCUS_SONG)
        try:
            spd = int(value, 16) if state.hex_mode else int(value)
            spd = max(1, min(255, spd))
            ops.save_undo("Change speed")
            state.song.songlines[sl_idx].speed = spd
            state.song.modified = True
        except: pass
        
        # Update cursor position
        state.song_cursor_row = sl_idx
        state.song_cursor_col = MAX_CHANNELS  # SPD column
        state.songline = sl_idx
        
        dpg.delete_item("popup_spd")
        R.refresh_song_editor()
        R.refresh_editor()
    
    def on_cancel():
        """Called when popup closes without selection."""
        state.set_input_active(False)
        # Still move cursor to clicked cell
        state.song_cursor_row = sl_idx
        state.song_cursor_col = MAX_CHANNELS  # SPD column
        state.songline = sl_idx
        R.refresh_song_editor()
        R.refresh_editor()
    
    # input_active already set by song_spd_click
    with dpg.window(tag="popup_spd", popup=True, no_title_bar=True, modal=True,
                    pos=[int(pos[0]), int(pos[1])], min_size=(60, 180),
                    on_close=on_cancel):
        dpg.add_text("Speed:")
        # Find default value in list, or use first item
        default_val = G.fmt(current_spd) if 1 <= current_spd <= 10 else items[5]  # Default to 6
        dpg.add_listbox(items=items, default_value=default_val,
                        num_items=10, callback=on_select, width=-1)


# =============================================================================
# INSTRUMENT HANDLERS
# =============================================================================

def select_inst_click(sender, app_data, user_data):
    """Click on instrument name to select it."""
    G.set_focus(FOCUS_INSTRUMENTS)
    state.instrument = user_data
    R.refresh_instruments()
    G.show_status(f"Instrument: {G.fmt(user_data)}")


def preview_instrument(sender, app_data, user_data):
    """Preview instrument sound at C-1."""
    idx = user_data
    if idx < len(state.song.instruments):
        inst = state.song.instruments[idx]
        if inst.is_loaded():
            # Always play at C-1 (note 1)
            state.audio.preview_note(0, 1, inst, MAX_VOLUME)
            G.show_status(f"Playing: {inst.name}")
        else:
            G.show_status(f"Instrument not loaded")


def effects_inst_click(sender, app_data, user_data):
    """Click on effects [E] button — select instrument and open sample editor."""
    idx = user_data
    state.instrument = idx
    R.refresh_instruments()
    on_edit_instrument()


# =============================================================================
# EDITOR CLICK HANDLERS
# =============================================================================

def editor_row_click(sender, app_data, user_data):
    """Click on row number - select row."""
    vis_row = user_data
    G.set_focus(FOCUS_EDITOR)
    
    max_len = state.song.max_pattern_length(state.songline)
    half = G.visible_rows // 2
    start_row = max(0, state.row - half)
    if start_row + G.visible_rows > max_len:
        start_row = max(0, max_len - G.visible_rows)
    row = start_row + vis_row
    if row >= max_len:
        return
    
    state.row = row
    state.selection.clear()
    R.refresh_editor()


def cell_click(sender, app_data, user_data):
    """Click on cell to select and optionally show popup."""
    vis_row, channel, column = user_data
    
    # Calculate which row was clicked BEFORE any state changes
    # This must happen first, before any refresh/scroll could invalidate the position
    max_len = state.song.max_pattern_length(state.songline)
    half = G.visible_rows // 2
    start_row = max(0, state.row - half)
    if start_row + G.visible_rows > max_len:
        start_row = max(0, max_len - G.visible_rows)
    row = start_row + vis_row
    if row >= max_len:
        return
    
    mouse_pos = dpg.get_mouse_pos(local=False)
    
    # For Instrument and Volume columns, show popup
    # Set input_active BEFORE showing popup to prevent any concurrent handlers
    if column == COL_INST and state.song.instruments:
        state.set_input_active(True)  # Block other handlers immediately
        G.set_focus(FOCUS_EDITOR)
        show_instrument_popup(row, channel, mouse_pos)
    elif column == COL_VOL:
        state.set_input_active(True)  # Block other handlers immediately
        G.set_focus(FOCUS_EDITOR)
        show_volume_popup(row, channel, mouse_pos)
    else:
        # For Note column (or if no instruments), just move cursor
        G.set_focus(FOCUS_EDITOR)
        state.row = row
        state.channel = channel
        state.column = column
        state.selection.clear()
        R.refresh_editor()


def show_instrument_popup(row: int, channel: int, pos: tuple):
    """Show instrument selection popup."""
    if dpg.does_item_exist("popup_inst"):
        dpg.delete_item("popup_inst")
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_inst = ptn.get_row(row % ptn.length).instrument
    items = [f"{G.fmt_inst(i)} - {inst.name}" for i, inst in enumerate(state.song.instruments)]
    if not items:
        # No instruments - just move cursor, reset input_active
        state.set_input_active(False)
        state.row = row
        state.channel = channel
        state.column = COL_INST
        state.selection.clear()
        R.refresh_editor()
        return
    
    def on_select(sender, value):
        state.set_input_active(False)
        G.set_focus(FOCUS_EDITOR)
        try:
            idx = int(value.split(" - ")[0], 16 if state.hex_mode else 10)
            ops.set_cell_instrument(row, channel, idx)
        except: pass
        
        # NOW update cursor position and scroll
        state.row = row
        state.channel = channel
        state.column = COL_INST
        state.selection.clear()
        
        dpg.delete_item("popup_inst")
        R.refresh_editor()
    
    def on_cancel():
        """Called when popup closes without selection."""
        state.set_input_active(False)
        # Still move cursor to clicked cell
        state.row = row
        state.channel = channel
        state.column = COL_INST
        state.selection.clear()
        R.refresh_editor()
    
    with dpg.window(tag="popup_inst", popup=True, no_title_bar=True, modal=True,
                    pos=[int(pos[0]), int(pos[1])], min_size=(200, 100), max_size=(300, 300),
                    on_close=on_cancel):
        dpg.add_text("Select Instrument:")
        idx = min(current_inst, len(items)-1) if items else 0
        dpg.add_listbox(items=items, default_value=items[idx] if items else "",
                        num_items=min(8, len(items)), callback=on_select, width=-1)


def show_volume_popup(row: int, channel: int, pos: tuple):
    """Show volume selection popup."""
    if dpg.does_item_exist("popup_vol"):
        dpg.delete_item("popup_vol")
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_vol = ptn.get_row(row % ptn.length).volume
    items = [G.fmt_vol(v) for v in range(MAX_VOLUME + 1)]
    
    def on_select(sender, value):
        state.set_input_active(False)
        G.set_focus(FOCUS_EDITOR)
        try:
            vol = int(value, 16) if state.hex_mode else int(value)
            ops.set_cell_volume(row, channel, vol)
        except: pass
        
        # NOW update cursor position and scroll
        state.row = row
        state.channel = channel
        state.column = COL_VOL
        state.selection.clear()
        
        dpg.delete_item("popup_vol")
        R.refresh_editor()
    
    def on_cancel():
        """Called when popup closes without selection."""
        state.set_input_active(False)
        # Still move cursor to clicked cell
        state.row = row
        state.channel = channel
        state.column = COL_VOL
        state.selection.clear()
        R.refresh_editor()
    
    # input_active already set by cell_click
    with dpg.window(tag="popup_vol", popup=True, no_title_bar=True, modal=True,
                    pos=[int(pos[0]), int(pos[1])], min_size=(60, 180),
                    on_close=on_cancel):
        dpg.add_text("Volume:")
        dpg.add_listbox(items=items, default_value=G.fmt_vol(current_vol),
                        num_items=10, callback=on_select, width=-1)


# Note: show_note_popup removed - clicking on Note column just positions cursor


# =============================================================================
# WIDGET CALLBACKS
# =============================================================================

def on_octave_change(sender, value):
    try:
        state.octave = int(value)
        G.save_config()
    except: pass


def on_step_change(sender, value):
    state.step = max(0, min(16, value))
    G.save_config()


def on_ptn_len_change(sender, value):
    """Handle pattern length change - supports hex and decimal input."""
    try:
        # Parse as hex or decimal based on mode
        if isinstance(value, str):
            value = value.strip()
            if state.hex_mode:
                parsed = int(value, 16)
            else:
                parsed = int(value)
        else:
            parsed = int(value)
        
        # Warn if exceeding max (254 for export compatibility)
        if parsed > MAX_ROWS:
            G.show_status(f"[!] Max pattern length is {MAX_ROWS} (row 255 reserved for export)")
            parsed = MAX_ROWS
        
        parsed = max(1, min(MAX_ROWS, parsed))
        ops.set_pattern_length(parsed, state.selected_pattern)
        
        # Update validation indicator
        R.update_validation_indicator()
    except (ValueError, TypeError):
        # Invalid input - restore original value
        R.refresh_pattern_info()


def on_pattern_select(sender, value):
    if value == "+":
        ops.save_undo("Add pattern")
        idx = state.song.add_pattern()
        if idx >= 0:
            state.selected_pattern = idx
            R.refresh_all_pattern_combos()
            R.refresh_pattern_info()
            G.show_status(f"Added pattern {G.fmt(idx)}")
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            state.selected_pattern = idx
            R.refresh_pattern_info()
            R._color_combo("ptn_select_combo", idx, G.ptn_palette)
        except: pass


def on_songline_pattern_change(sender, value, user_data):
    sl_idx, ch = user_data
    if value == "+":
        ops.save_undo("Add pattern")
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[sl_idx].patterns[ch] = idx
            state.selected_pattern = idx
            R.refresh_all()
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            ops.save_undo("Change pattern")
            state.song.songlines[sl_idx].patterns[ch] = idx
            state.selected_pattern = idx
            state.song.modified = True
            R.refresh_pattern_info()
            R.refresh_editor()
        except: pass


def on_editor_pattern_change(sender, value, user_data):
    ch = user_data
    if value == "+":
        ops.save_undo("Add pattern")
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[state.songline].patterns[ch] = idx
            state.selected_pattern = idx
            R.refresh_all()
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            ops.save_undo("Change pattern")
            state.song.songlines[state.songline].patterns[ch] = idx
            state.selected_pattern = idx
            state.song.modified = True
            R.refresh_pattern_info()
            R.refresh_editor()
        except: pass


def on_channel_toggle(sender, value, user_data):
    ch = user_data
    state.audio.set_channel_enabled(ch, value)
    R.refresh_editor()


def on_system_change(sender, value):
    state.song.system = PAL_HZ if value == "PAL" else NTSC_HZ
    state.audio.set_system(state.song.system)
    state.song.modified = True
    G.update_title()


def on_hex_toggle(sender, value):
    state.hex_mode = value
    G.save_config()
    if _rebuild_editor_grid:
        _rebuild_editor_grid()
    R.refresh_all()


def on_autosave_toggle(sender, value):
    G.autosave_enabled = value
    G.save_config()


def on_piano_keys_toggle(sender, value):
    """Toggle between piano-style and tracker-style keyboard layout."""
    G.piano_keys_mode = value
    G.save_config()
    mode_name = "Piano" if value else "Tracker"
    G.show_status(f"Keyboard mode: {mode_name}")


def on_coupled_toggle(sender, value):
    """Toggle coupled note+instrument+volume entry."""
    G.coupled_entry = value
    G.save_config()
    mode_name = "Coupled" if value else "Note only"
    G.show_status(f"Entry mode: {mode_name}")


def on_highlight_change(sender, value):
    """Change row highlight interval."""
    try:
        interval = int(value)
        if interval in [2, 4, 8, 16]:
            G.highlight_interval = interval
            G.save_config()
            R.refresh_editor()
    except:
        pass


def on_volume_control_toggle(sender, value):
    """Toggle volume control in export."""
    state.song.volume_control = value
    state.song.modified = True
    G.update_title()
    
    # If disabling volume and cursor is in volume column, move to instrument column
    if not value and state.column == COL_VOL:
        state.column = COL_INST
    
    # Show/hide volume in CURRENT section
    if dpg.does_item_exist("current_vol_group"):
        dpg.configure_item("current_vol_group", show=value)
    
    # Trigger editor rebuild to show/hide volume column
    if _rebuild_editor_grid:
        _rebuild_editor_grid()
    R.refresh_editor()
    
    # Show warning if rate is too high
    if value and state.vq.settings.rate > 5757:
        G.show_status("Warning: Volume requires sample rate <=5757 Hz")
    else:
        mode = "enabled" if value else "disabled"
        G.show_status(f"Volume control {mode}")


def on_screen_control_toggle(sender, value):
    """Toggle screen display during playback."""
    state.song.screen_control = value
    state.song.modified = True
    G.update_title()
    
    if value:
        G.show_status("Screen enabled during playback (shows SONG/ROW/SPD)")
    else:
        G.show_status("Screen disabled during playback (~15% more CPU)")


def on_keyboard_control_toggle(sender, value):
    """Toggle keyboard control during playback."""
    state.song.keyboard_control = value
    state.song.modified = True
    G.update_title()
    
    if value:
        G.show_status("Keyboard control enabled (SPACE=play/stop, R=restart)")
    else:
        G.show_status("Keyboard control disabled (saves cycles, play-once mode)")


def on_start_address_change(sender, value):
    """Called when start address hex input changes."""
    from constants import MIN_START_ADDRESS, MAX_START_ADDRESS
    try:
        addr = int(value, 16)
        addr = max(MIN_START_ADDRESS, min(MAX_START_ADDRESS, addr))
        # Align to page boundary
        addr = addr & 0xFF00
        state.song.start_address = addr
        state.song.modified = True
        # Update display to show clamped/aligned value
        if dpg.does_item_exist("start_address_input"):
            dpg.set_value("start_address_input", f"{addr:04X}")
        # Budget changed — clear stale optimize suggestions
        if hasattr(state, '_optimize_result'):
            state._optimize_result = None
        R.refresh_instruments()
        G.update_title()
    except ValueError:
        pass


def on_memory_config_change(sender, value):
    """Called when memory config combo changes."""
    from constants import MEMORY_CONFIG_NAMES
    if value in MEMORY_CONFIG_NAMES:
        state.song.memory_config = value
        state.song.modified = True
        # Budget changed — clear stale optimize suggestions
        if hasattr(state, '_optimize_result'):
            state._optimize_result = None
        R.refresh_instruments()
        G.update_title()
        if value == "64 KB":
            G.show_status("64 KB mode: all data in main memory")
        else:
            G.show_status(f"{value} mode: samples in extended RAM banks")


def on_edit_instrument(*args):
    """Open the sample editor for the currently selected instrument."""
    from sample_editor.ui_editor import open_editor
    inst = state.song.get_instrument(state.instrument)
    if inst:
        invalidate_vq_conversion()
        open_editor(state.instrument)
    else:
        G.show_status("No instrument selected")


def on_input_inst_change(sender, value):
    try:
        idx = int(value.split(" - ")[0], 16 if state.hex_mode else 10)
        state.instrument = idx
        R._color_combo("input_inst_combo", idx, G.inst_palette)
        R.refresh_instruments()
        # Update sample editor if open
        from sample_editor.ui_editor import update_editor_instrument
        update_editor_instrument(idx)
    except: pass


def on_input_vol_change(sender, value):
    try:
        vol = int(value, 16) if state.hex_mode else int(value)
        state.volume = max(0, min(MAX_VOLUME, vol))
    except: pass


def on_reset_song():
    def do_reset():
        try:
            from sample_editor.ui_editor import close_editor
            close_editor()
        except Exception:
            pass
        state.song.reset()
        state.songline = state.row = state.channel = state.column = 0
        state.song_cursor_row = state.song_cursor_col = 0
        state.selected_pattern = 0
        state.volume = MAX_VOLUME
        R.refresh_all()
        G.update_title()
        G.show_status("Song reset")
    if _show_confirm:
        _show_confirm("Reset Song", "Clear all song data?", do_reset)


# =============================================================================
# PLAYBACK CALLBACKS
# =============================================================================

def on_playback_row(songline: int, row: int):
    """Called during playback to update position."""
    G.play_row = row
    G.play_songline = songline
    if state.follow and state.audio.is_playing():
        if state.songline != songline:
            state.songline = songline
            state.song_cursor_row = songline
            R.refresh_song_editor()
        state.row = row
    R.refresh_song_editor()
    R.refresh_editor()


def on_playback_stop():
    """Called when playback stops."""
    G.play_row = -1
    G.play_songline = -1
    R.refresh_song_editor()
    R.refresh_editor()


# =============================================================================
# REPLACE INSTRUMENT
# =============================================================================

_REPLACE_DLG = "replace_inst_dlg"


def on_replace_instrument(*args):
    """Show the Replace Instrument dialog."""
    if dpg.does_item_exist(_REPLACE_DLG):
        dpg.delete_item(_REPLACE_DLG)

    instruments = state.song.instruments
    if not instruments:
        G.show_status("No instruments loaded")
        return

    # Build instrument items: "00 - Kick", "01 - Snare", ...
    inst_items = [f"{G.fmt_inst(i)} - {inst.name}"
                  for i, inst in enumerate(instruments)]

    # Build pattern items: "00", "01", ...
    num_patterns = len(state.song.patterns)
    ptn_items = [G.fmt(i) for i in range(num_patterns)]

    # Default pattern: the one currently under the cursor
    current_ptn = state.get_patterns()[state.channel]

    # Default instrument indices (clamped to valid range)
    from_default = max(0, min(state.instrument, len(inst_items) - 1))
    # Default "To" to next instrument if possible, so From != To
    to_default = (from_default + 1) % len(inst_items)

    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    dlg_w, dlg_h = 380, 260

    with dpg.window(tag=_REPLACE_DLG, label="Replace Instrument",
                    modal=True, no_resize=True, no_collapse=True,
                    width=dlg_w, height=dlg_h,
                    pos=[(vp_w - dlg_w) // 2, (vp_h - dlg_h) // 2]):

        dpg.add_spacer(height=6)

        # -- Scope row --
        with dpg.group(horizontal=True):
            dpg.add_checkbox(tag=f"{_REPLACE_DLG}_all",
                             label="In all patterns",
                             default_value=False,
                             callback=_on_replace_scope_toggle)
            dpg.add_spacer(width=20)
            dpg.add_text("Pattern:", color=(180, 180, 180))
            dpg.add_combo(tag=f"{_REPLACE_DLG}_ptn",
                          items=ptn_items,
                          default_value=G.fmt(current_ptn),
                          width=60)

        dpg.add_spacer(height=12)

        # -- From instrument --
        with dpg.group(horizontal=True):
            dpg.add_text("From:", color=(180, 180, 180))
            dpg.add_spacer(width=10)
            dpg.add_combo(tag=f"{_REPLACE_DLG}_from",
                          items=inst_items,
                          default_value=inst_items[from_default],
                          width=260)

        dpg.add_spacer(height=8)

        # -- To instrument --
        with dpg.group(horizontal=True):
            dpg.add_text("To:    ", color=(180, 180, 180))
            dpg.add_spacer(width=10)
            dpg.add_combo(tag=f"{_REPLACE_DLG}_to",
                          items=inst_items,
                          default_value=inst_items[to_default],
                          width=260)

        dpg.add_spacer(height=16)

        # -- Result label (hidden until replace runs) --
        dpg.add_text("", tag=f"{_REPLACE_DLG}_result", color=(120, 200, 120))

        dpg.add_spacer(height=4)

        # -- Buttons --
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=115)
            dpg.add_button(label="Replace", width=100,
                           callback=_do_replace_instrument)
            dpg.add_spacer(width=10)
            dpg.add_button(label="Close", width=100,
                           callback=lambda: dpg.delete_item(_REPLACE_DLG))


def _on_replace_scope_toggle(sender, value, *args):
    """Enable/disable pattern combo based on 'all patterns' checkbox."""
    ptn_tag = f"{_REPLACE_DLG}_ptn"
    if dpg.does_item_exist(ptn_tag):
        dpg.configure_item(ptn_tag, enabled=not value)


def _do_replace_instrument(*args):
    """Execute the instrument replacement."""
    from ops.base import save_undo

    all_patterns = dpg.get_value(f"{_REPLACE_DLG}_all")
    from_str = dpg.get_value(f"{_REPLACE_DLG}_from")
    to_str = dpg.get_value(f"{_REPLACE_DLG}_to")

    # Parse instrument indices from "XX - Name" strings
    try:
        from_idx = int(from_str.split(" - ")[0], 16 if state.hex_mode else 10)
        to_idx = int(to_str.split(" - ")[0], 16 if state.hex_mode else 10)
    except (ValueError, IndexError):
        G.show_status("Error: could not parse instrument selection")
        return

    if from_idx == to_idx:
        if dpg.does_item_exist(f"{_REPLACE_DLG}_result"):
            dpg.set_value(f"{_REPLACE_DLG}_result",
                          "From and To are the same instrument.")
            dpg.configure_item(f"{_REPLACE_DLG}_result",
                               color=(240, 180, 80))
        return

    # Determine which patterns to scan
    if all_patterns:
        patterns = list(range(len(state.song.patterns)))
    else:
        ptn_str = dpg.get_value(f"{_REPLACE_DLG}_ptn")
        try:
            ptn_idx = int(ptn_str, 16 if state.hex_mode else 10)
        except ValueError:
            G.show_status("Error: invalid pattern number")
            return
        if ptn_idx >= len(state.song.patterns):
            G.show_status(f"Pattern {ptn_str} does not exist")
            return
        patterns = [ptn_idx]

    from constants import NOTE_OFF, VOL_CHANGE

    # Scan first to count matches before committing undo
    matches = []
    for pi in patterns:
        ptn = state.song.patterns[pi]
        for row in ptn.rows:
            if (row.instrument == from_idx
                    and row.note > 0
                    and row.note not in (NOTE_OFF, VOL_CHANGE)):
                matches.append(row)

    if not matches:
        scope = "all patterns" if all_patterns else f"pattern {G.fmt(patterns[0])}"
        msg = f"No matches found in {scope}"
        if dpg.does_item_exist(f"{_REPLACE_DLG}_result"):
            dpg.set_value(f"{_REPLACE_DLG}_result", msg)
            dpg.configure_item(f"{_REPLACE_DLG}_result", color=(180, 180, 100))
        return

    save_undo("Replace Instrument")

    for row in matches:
        row.instrument = to_idx
    count = len(matches)

    state.song.modified = True
    R.refresh_editor()

    from_name = state.song.instruments[from_idx].name if from_idx < len(state.song.instruments) else "?"
    to_name = state.song.instruments[to_idx].name if to_idx < len(state.song.instruments) else "?"
    scope = "all patterns" if all_patterns else f"pattern {G.fmt(patterns[0])}"

    msg = f"Replaced {count} note(s) in {scope}"
    if dpg.does_item_exist(f"{_REPLACE_DLG}_result"):
        dpg.set_value(f"{_REPLACE_DLG}_result", msg)
        col = (120, 200, 120) if count > 0 else (180, 180, 100)
        dpg.configure_item(f"{_REPLACE_DLG}_result", color=col)
    G.show_status(f"Replaced {count} note(s): {from_name} -> {to_name} ({scope})")


def on_play_pattern_click(sender, app_data):
    ops.play_pattern()


def on_play_pattern_here(sender, app_data):
    """Play current pattern from cursor position."""
    state.audio.play_from(state.songline, state.row)
    from ops.base import ui, fmt
    ui.show_status(f"Playing pattern from row {fmt(state.row)}...")


def on_play_song_click(sender, app_data):
    ops.play_song_start()


def on_play_song_start(sender, app_data):
    ops.play_song_start()


def on_play_song_here(sender, app_data):
    ops.play_song_here()


def on_stop_click(sender, app_data):
    ops.stop_playback()


# =============================================================================
# INSTRUMENT MANAGEMENT
# =============================================================================

def _remap_instrument_indices(idx_a: int, idx_b: int):
    """Swap all pattern row instrument references between idx_a and idx_b."""
    for pattern in state.song.patterns:
        for row in pattern.rows:
            if row.instrument == idx_a:
                row.instrument = idx_b
            elif row.instrument == idx_b:
                row.instrument = idx_a


def on_move_inst_up(sender, app_data):
    if state.instrument > 0 and state.instrument < len(state.song.instruments):
        ops.save_undo("Move instrument up")
        idx = state.instrument
        state.song.instruments[idx], state.song.instruments[idx-1] = \
            state.song.instruments[idx-1], state.song.instruments[idx]
        _remap_instrument_indices(idx, idx - 1)
        state.instrument -= 1
        state.song.modified = True
        invalidate_vq_conversion()  # Invalidate VQ + restore originals if needed
        R.refresh_instruments()
        R.refresh_editor()
        try:
            from sample_editor.ui_editor import update_editor_instrument
            update_editor_instrument(state.instrument)
        except Exception:
            pass
        G.show_status("Moved instrument up")


def on_move_inst_down(sender, app_data):
    if state.instrument < len(state.song.instruments) - 1:
        ops.save_undo("Move instrument down")
        idx = state.instrument
        state.song.instruments[idx], state.song.instruments[idx+1] = \
            state.song.instruments[idx+1], state.song.instruments[idx]
        _remap_instrument_indices(idx, idx + 1)
        state.instrument += 1
        state.song.modified = True
        invalidate_vq_conversion()  # Invalidate VQ + restore originals if needed
        R.refresh_instruments()
        R.refresh_editor()
        try:
            from sample_editor.ui_editor import update_editor_instrument
            update_editor_instrument(state.instrument)
        except Exception:
            pass
        G.show_status("Moved instrument down")


# =============================================================================
# SONGLINE MANAGEMENT
# =============================================================================

def on_move_songline_up(sender, app_data):
    if state.song_cursor_row > 0:
        ops.save_undo("Move songline up")
        idx = state.song_cursor_row
        state.song.songlines[idx], state.song.songlines[idx-1] = \
            state.song.songlines[idx-1], state.song.songlines[idx]
        state.song_cursor_row -= 1
        state.songline = state.song_cursor_row
        state.song.modified = True
        R.refresh_song_editor()
        R.refresh_editor()
        G.show_status("Moved songline up")


def on_move_songline_down(sender, app_data):
    if state.song_cursor_row < len(state.song.songlines) - 1:
        ops.save_undo("Move songline down")
        idx = state.song_cursor_row
        state.song.songlines[idx], state.song.songlines[idx+1] = \
            state.song.songlines[idx+1], state.song.songlines[idx]
        state.song_cursor_row += 1
        state.songline = state.song_cursor_row
        state.song.modified = True
        R.refresh_song_editor()
        R.refresh_editor()
        G.show_status("Moved songline down")


def on_add_songline_btn(sender, app_data):
    ops.add_songline()


def on_clone_songline_btn(sender, app_data):
    ops.clone_songline()


# =============================================================================
# MOUSE HANDLERS
# =============================================================================

def on_global_mouse_click(sender, app_data):
    """Handle global mouse clicks to set focus based on click position.
    
    Note: Row/cell selection is handled by individual button callbacks,
    NOT here. This only handles focus switching and clicking on empty areas.
    Uses dpg.is_item_hovered() for reliable hit-testing even with nested panels.
    """
    if app_data != 0:  # 0 = left click
        return
    
    # Don't process if a popup/modal is active
    if state.input_active:
        return
    
    # Check panels using DearPyGUI's native hover detection
    # (works correctly with nested child_windows unlike manual rect math)
    # Check most specific panels first, then broader containers
    
    for tag, focus in [("song_panel", FOCUS_SONG),
                       ("editor_panel", FOCUS_EDITOR),
                       ("inst_panel", FOCUS_INSTRUMENTS),
                       ("pattern_panel", FOCUS_EDITOR)]:
        if dpg.does_item_exist(tag):
            try:
                if dpg.is_item_hovered(tag):
                    G.set_focus(focus)
                    return
            except:
                pass


def _is_mouse_over(panel_tag):
    """Check if mouse cursor is over a given panel (for scroll routing).
    
    Uses rect-based checking so it works even when hovering over child
    widgets inside the panel (is_item_hovered only works for empty space).
    """
    if not dpg.does_item_exist(panel_tag):
        return False
    try:
        # Try native hover first (fast, works for direct hover)
        if dpg.is_item_hovered(panel_tag):
            return True
        # Fallback: rect-based check for when hovering over child widgets
        pos = dpg.get_item_rect_min(panel_tag)
        sz = dpg.get_item_rect_size(panel_tag)
        if not pos or not sz:
            return False
        mx, my = dpg.get_mouse_pos(local=False)
        return (pos[0] <= mx <= pos[0] + sz[0] and
                pos[1] <= my <= pos[1] + sz[1])
    except Exception:
        return False


def on_mouse_wheel(sender, app_data):
    """Handle mouse wheel for pattern editor and song scrolling.
    
    app_data is the wheel delta: positive = scroll up, negative = scroll down.
    """
    if state.input_active:
        return

    # Don't scroll while sample editor modal is open
    try:
        from sample_editor.ui_editor import is_editor_open
        if is_editor_open():
            return
    except Exception:
        pass

    delta = app_data  # +1 = wheel up, -1 = wheel down
    rows = -1 if delta > 0 else 1  # scroll 1 row per notch

    if _is_mouse_over("editor_panel"):
        ops.move_cursor(rows, 0)
    elif _is_mouse_over("song_panel"):
        total = len(state.song.songlines)
        if delta > 0 and state.song_cursor_row > 0:
            state.song_cursor_row = max(0, state.song_cursor_row - 1)
            state.songline = state.song_cursor_row
            R.refresh_song_editor()
            R.refresh_editor()
        elif delta < 0 and state.song_cursor_row < total - 1:
            state.song_cursor_row = min(total - 1,
                                        state.song_cursor_row + 1)
            state.songline = state.song_cursor_row
            R.refresh_song_editor()
            R.refresh_editor()


# =============================================================================
# AUTOSAVE RECOVERY
# =============================================================================

def show_autosave_recovery():
    """Show dialog to recover from autosaved files."""
    from ui_dialogs import show_error
    
    # Get autosave files
    autosaves = G.get_autosave_files()
    
    if not autosaves:
        if dpg.does_item_exist("autosave_empty_popup"):
            dpg.delete_item("autosave_empty_popup")
        
        vp_w = dpg.get_viewport_width()
        vp_h = dpg.get_viewport_height()
        w, h = 300, 100
        
        with dpg.window(
            tag="autosave_empty_popup",
            label="No Autosaves",
            modal=True,
            width=w, height=h,
            pos=[(vp_w - w) // 2, (vp_h - h) // 2],
            no_resize=True, no_collapse=True,
            on_close=lambda: dpg.delete_item("autosave_empty_popup")
        ):
            dpg.add_text("No autosave files found.")
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=(w - 80) // 2)
                dpg.add_button(label="OK", width=80,
                              callback=lambda: dpg.delete_item("autosave_empty_popup"))
        return
    
    # Close existing dialog
    if dpg.does_item_exist("autosave_dialog"):
        dpg.delete_item("autosave_dialog")
    
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 500, 350
    
    with dpg.window(
        tag="autosave_dialog",
        label="Recover Autosave",
        modal=True,
        width=w, height=h,
        pos=[(vp_w - w) // 2, (vp_h - h) // 2],
        no_resize=False, no_collapse=True,
        on_close=lambda: dpg.delete_item("autosave_dialog")
    ):
        dpg.add_text("Select an autosave to recover:", color=(255, 255, 150))
        dpg.add_text(f"Location: {G.AUTOSAVE_DIR}", color=(150, 150, 150))
        dpg.add_spacer(height=5)
        
        # List autosaves in scrollable area
        with dpg.child_window(height=-50, border=True):
            import datetime
            for i, path in enumerate(autosaves[:20]):  # Show up to 20
                mtime = os.path.getmtime(path)
                dt = datetime.datetime.fromtimestamp(mtime)
                size_kb = os.path.getsize(path) / 1024
                label = f"{path.name}  ({dt:%Y-%m-%d %H:%M}, {size_kb:.1f} KB)"
                
                dpg.add_button(
                    label=label, 
                    width=-1,
                    callback=lambda s, a, u: _load_autosave(u),
                    user_data=str(path)
                )
        
        # Close button
        dpg.add_spacer(height=5)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=(w - 100) // 2)
            dpg.add_button(label="Cancel", width=100,
                          callback=lambda: dpg.delete_item("autosave_dialog"))


def _load_autosave(path: str):
    """Load an autosave file."""
    from ui_dialogs import show_error
    import file_io
    from file_io import load_project
    
    # Close the recovery dialog
    if dpg.does_item_exist("autosave_dialog"):
        dpg.delete_item("autosave_dialog")
    
    if not os.path.exists(path):
        show_error("File Not Found", f"Autosave no longer exists:\n{path}")
        return
    
    if not file_io.work_dir:
        show_error("Load Error", "Working directory not initialized")
        return
    
    # Stop audio BEFORE loading to release any file handles
    state.audio.stop_playback()
    
    # Close sample editor before replacing song
    try:
        from sample_editor.ui_editor import close_editor
        close_editor()
    except Exception:
        pass
    
    # Autosave current work first
    if state.song.modified and G.autosave_enabled:
        G.do_autosave()
    
    # Load the autosave
    song, editor_state, msg = load_project(path, file_io.work_dir)
    if not song:
        show_error("Load Error", msg)
        return
    
    state.song = song
    state.audio.set_song(state.song)
    
    # Reset state
    state.songline = state.row = state.channel = state.selected_pattern = 0
    state.song_cursor_row = state.song_cursor_col = 0
    state.vq.invalidate()
    
    # Mark as modified since it's recovered (needs saving to a real location)
    state.song.modified = True
    state.song.file_path = None  # Clear path so Save As is required
    
    R.refresh_all()
    G.update_title()
    G.show_status(f"Recovered: {os.path.basename(path)} - Save to keep changes!")


# =============================================================================
# RECENT FILES
# =============================================================================

def load_recent_file(sender, app_data, user_data):
    from ui_dialogs import show_error
    import file_io
    from file_io import load_project
    path = user_data
    if not os.path.exists(path):
        show_error("File Not Found", f"File no longer exists:\n{path}")
        return
    if not file_io.work_dir:
        show_error("Load Error", "Working directory not initialized")
        return
    
    # Stop audio BEFORE loading to release any file handles
    state.audio.stop_playback()
    
    # Close sample editor before replacing song
    try:
        from sample_editor.ui_editor import close_editor
        close_editor()
    except Exception:
        pass
    
    if state.song.modified and G.autosave_enabled:
        G.do_autosave()
    song, editor_state, msg = load_project(path, file_io.work_dir)
    if not song:
        show_error("Load Error", msg)
        return
    state.song = song
    state.audio.set_song(state.song)
    G.add_recent_file(path)
    state.songline = state.row = state.channel = state.selected_pattern = 0
    state.song_cursor_row = state.song_cursor_col = 0
    state.vq.invalidate()  # Clear VQ conversion for loaded project
    R.refresh_all()
    G.update_title()
    G.show_status(f"Loaded: {os.path.basename(path)}")


# =============================================================================
# DYNAMIC LAYOUT
# =============================================================================

def calculate_visible_rows() -> int:
    """Calculate how many rows fit in the editor based on window height."""
    try:
        vp_height = dpg.get_viewport_height()
        # New layout: menu + CURRENT row + editor (full height) + status bar
        # No TOP_PANEL_HEIGHT above the editor anymore
        fixed_height = G.INPUT_ROW_HEIGHT + G.EDITOR_HEADER_HEIGHT + 60
        available = vp_height - fixed_height
        rows = available // ROW_HEIGHT - 4
        rows = max(1, min(G.MAX_VISIBLE_ROWS, rows))
        return rows
    except:
        return 10


def on_viewport_resize(sender=None, app_data=None):
    """Handle viewport resize - recalculate visible rows."""
    new_rows = calculate_visible_rows()
    if new_rows != G.visible_rows:
        G.visible_rows = new_rows
        if _rebuild_editor_grid:
            _rebuild_editor_grid()
        R.refresh_editor()


# =============================================================================
# VQ CONVERSION
# =============================================================================

def on_vq_setting_change(sender, app_data):
    """Called when any VQ setting changes - invalidates conversion."""
    # Update settings from UI
    try:
        rate_str = dpg.get_value("vq_rate_combo")
        state.vq.settings.rate = int(rate_str.replace(" Hz", ""))
    except:
        pass
    
    try:
        state.vq.settings.vector_size = int(dpg.get_value("vq_vector_combo"))
    except:
        pass
    
    try:
        state.vq.settings.smoothness = int(dpg.get_value("vq_smooth_combo"))
    except:
        pass
    
    state.vq.settings.enhance = dpg.get_value("vq_enhance_cb") if dpg.does_item_exist("vq_enhance_cb") else True
    
    # Invalidate conversion
    invalidate_vq_conversion()



def on_used_only_change(sender, app_data):
    """Called when 'Used Samples' checkbox changes."""
    state.vq.settings.used_only = app_data
    
    # Clear optimize suggestions (scope changed)
    if hasattr(state, '_optimize_result'):
        state._optimize_result = None
    
    # Invalidate conversion (different set of instruments)
    invalidate_vq_conversion()


def on_vq_use_converted_change(sender, app_data):
    """Toggle between original and converted sample playback."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"on_vq_use_converted_change: app_data={app_data}")
    logger.info(f"  state.vq.converted={state.vq.converted}")
    logger.info(f"  state.vq.result={state.vq.result}")
    if state.vq.result:
        logger.info(f"  result.converted_wavs count={len(state.vq.result.converted_wavs)}")
    
    state.vq.use_converted = app_data
    
    # Reload samples based on new setting
    if state.vq.converted and state.vq.result and state.vq.use_converted:
        # Load converted WAVs
        logger.info("  -> Loading converted samples")
        _load_converted_samples()
    else:
        # Reload original samples from their source paths
        logger.info("  -> Reloading original samples")
        _reload_original_samples()
    
    state.audio.set_song(state.song)
    
    # Refresh instruments to update colors (green when using converted, gray otherwise)
    R.refresh_instruments()
    
    G.show_status("Using converted samples" if state.vq.use_converted else "Using original samples")


def _reload_original_samples():
    """Reload original samples from their working copy paths.
    
    Uses sample_path which points to .tmp/samples/ where samples are stored.
    """
    import logging
    logger = logging.getLogger(__name__)
    from file_io import load_sample
    
    logger.debug(f"Reloading {len(state.song.instruments)} original samples")
    for inst in state.song.instruments:
        working_path = inst.sample_path
        if working_path and os.path.exists(working_path):
            logger.debug(f"  Inst {inst.name}: {working_path}")
            ok, msg = load_sample(inst, working_path, update_path=False)
            if not ok:
                G.show_status(f"Error reloading {inst.name}: {msg}")
        elif working_path:
            logger.warning(f"  Inst {inst.name}: sample not found: {working_path}")


def _load_converted_samples():
    """Load converted WAV files into instruments.
    
    Note: Uses update_path=False to preserve sample_path pointing to original.
    This allows toggling back to original samples later.
    
    Skips instruments that were not converted (used_only mode) so their
    original sample_data is preserved.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Debug: Show what we have
    logger.info(f"_load_converted_samples called")
    logger.info(f"  state.vq.result: {state.vq.result}")
    
    if not state.vq.result:
        G.show_status("Error: No conversion result available")
        logger.warning("_load_converted_samples: No result")
        return
    
    if not state.vq.result.converted_wavs:
        G.show_status("Error: No converted WAV files found")
        logger.warning(f"_load_converted_samples: No converted_wavs (result.output_dir={state.vq.result.output_dir})")
        return
    
    from file_io import load_sample
    
    num_wavs = len(state.vq.result.converted_wavs)
    num_instruments = len(state.song.instruments)
    logger.info(f"Loading {num_wavs} converted WAVs for {num_instruments} instruments")
    
    loaded_count = 0
    error_count = 0
    skipped_count = 0
    
    for i, inst in enumerate(state.song.instruments):
        # Skip instruments that weren't actually converted (dummy WAVs)
        if _vq_used_indices is not None and i not in _vq_used_indices:
            skipped_count += 1
            logger.debug(f"  Inst {i} ({inst.name}): skipped (unused)")
            continue
        
        if i < num_wavs:
            wav_path = state.vq.result.converted_wavs[i]
            logger.info(f"  Inst {i} ({inst.name}): {wav_path}")
            
            if os.path.exists(wav_path):
                # Load converted sample data WITHOUT updating sample_path
                # This preserves sample_path pointing to the original working sample
                ok, msg = load_sample(inst, wav_path, update_path=False)
                if ok:
                    loaded_count += 1
                    logger.info(f"    Loaded OK: {len(inst.sample_data) if inst.sample_data is not None else 0} samples")
                else:
                    error_count += 1
                    logger.error(f"    Load failed: {msg}")
                    G.show_status(f"Error loading {os.path.basename(wav_path)}: {msg}")
            else:
                error_count += 1
                logger.warning(f"    File not found: {wav_path}")
        else:
            logger.warning(f"  Inst {i} ({inst.name}): No converted WAV (only {num_wavs} WAVs)")
    
    status = f"Loaded {loaded_count} converted samples"
    if skipped_count:
        status += f" ({skipped_count} unused skipped)"
    if error_count:
        status += f" ({error_count} errors)"
    if loaded_count > 0:
        G.show_status(status)


def invalidate_vq_conversion():
    """Mark VQ conversion as invalid.
    
    SYNCHRONIZATION: When VQ conversion is invalidated, BUILD must also be disabled.
    This happens when:
    - Instruments are added, removed, or replaced
    - Sample editor is opened (effects may change)
    - User explicitly runs CONVERT again
    - New project is loaded
    
    BUILD button is only enabled (green) when:
    - state.vq.converted == True (CONVERT was successful)
    - state.song.instruments is not empty
    
    IMPORTANT: If use_converted was True, inst.sample_data contains VQ audio.
    We must reload original samples before clearing the flag, otherwise all
    playback/preview will use stale VQ data.
    """
    # If samples were swapped to VQ audio, restore originals FIRST
    was_using_converted = state.vq.use_converted
    
    state.vq.invalidate()
    
    # Clear optimize suggestions (they're based on old settings)
    if hasattr(state, '_optimize_result'):
        state._optimize_result = None
    
    # Clear used-indices tracking from previous conversion
    global _vq_used_indices
    _vq_used_indices = None
    
    # Update CONVERT UI
    if dpg.does_item_exist("vq_size_label"):
        dpg.set_value("vq_size_label", "")
    
    if dpg.does_item_exist("vq_use_converted_cb"):
        dpg.set_value("vq_use_converted_cb", False)
        dpg.configure_item("vq_use_converted_cb", enabled=False)
    
    state.vq.use_converted = False
    
    # Restore original sample data if it was swapped
    if was_using_converted:
        _reload_original_samples()
    
    # Update BUILD button state (must be disabled when VQ is invalid)
    update_build_button_state()
    
    # Refresh instruments to show gray backgrounds
    R.refresh_instruments()


def update_build_button_state():
    """Update BUILD button appearance based on VQ conversion state.
    
    SYNCHRONIZATION: BUILD button state depends on:
    1. VQ conversion being valid (state.vq.converted == True)
    2. Instruments existing (len(state.song.instruments) > 0)
    
    When both conditions are met: Green button with "Ready" status
    Otherwise: Disabled/gray button with appropriate status message
    """
    if not dpg.does_item_exist("build_btn"):
        return
    
    has_instruments = len(state.song.instruments) > 0
    vq_converted = state.vq.converted
    
    if vq_converted and has_instruments:
        # Ready to build - green button
        dpg.bind_item_theme("build_btn", "theme_btn_green")
        if dpg.does_item_exist("build_status_label"):
            dpg.set_value("build_status_label", "Ready")
            dpg.configure_item("build_status_label", color=(100, 200, 100))
    elif not has_instruments:
        # No instruments - disabled
        dpg.bind_item_theme("build_btn", "theme_btn_disabled")
        if dpg.does_item_exist("build_status_label"):
            dpg.set_value("build_status_label", "Add instruments first")
            dpg.configure_item("build_status_label", color=(150, 150, 150))
    else:
        # Not converted - disabled
        dpg.bind_item_theme("build_btn", "theme_btn_disabled")
        if dpg.does_item_exist("build_status_label"):
            dpg.set_value("build_status_label", "Run CONVERT first")
            dpg.configure_item("build_status_label", color=(150, 150, 150))
    



def _prepare_conversion_files(instruments, used_indices=None) -> tuple:
    """Prepare input files for VQ conversion, writing processed WAVs where needed.
    
    Always reads original audio from disk (sample_path), never from sample_data
    which may contain VQ-converted audio when use_converted is active.
    
    Args:
        instruments: List of Instrument objects
        used_indices: If not None, set of instrument indices that are used in
                      the song. Unused instruments get a tiny dummy WAV so
                      indices stay aligned but conversion is effectively free.
    
    Returns (input_files, proc_files, error_msg).
    error_msg is non-empty if a file is missing.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    input_files = []
    proc_files = []
    dummy_path = None
    
    for i, inst in enumerate(instruments):
        # If used_only filtering is active and this instrument is unused,
        # provide a tiny dummy WAV so the index stays aligned
        if used_indices is not None and i not in used_indices:
            if dummy_path is None:
                dummy_path = _get_dummy_wav_path()
            input_files.append(dummy_path)
            continue
        
        working_path = inst.sample_path
        if not working_path or not os.path.exists(working_path):
            return None, [], (
                f"Instrument '{inst.name}' has no valid sample file.\n\n"
                f"Path: {working_path or '(empty)'}\n\n"
                f"Please reload the instrument.")
        
        if inst.effects:
            # Read original audio from disk (not sample_data which may be VQ)
            import soundfile as sf
            from sample_editor.pipeline import run_pipeline
            try:
                original_audio, sr = sf.read(working_path, dtype='float32')
                if len(original_audio.shape) > 1:
                    original_audio = original_audio.mean(axis=1)
                processed = run_pipeline(original_audio, sr, inst.effects)
                proc_path = working_path.replace('.wav', '_proc.wav')
                sf.write(proc_path, processed, sr)
                input_files.append(proc_path)
                proc_files.append(proc_path)
                logger.debug(f"  Inst {i}: wrote processed audio to {proc_path}")
            except Exception as e:
                logger.warning(f"  Inst {i}: failed to process effects: {e}, using raw")
                input_files.append(working_path)
        else:
            input_files.append(working_path)
    
    return input_files, proc_files, ""


def _get_dummy_wav_path() -> str:
    """Create (once) a tiny 4-sample silent WAV for unused instrument slots."""
    import wave
    import runtime as rt
    dummy_dir = os.path.join(rt.get_app_dir(), ".tmp")
    os.makedirs(dummy_dir, exist_ok=True)
    dummy_path = os.path.join(dummy_dir, "_dummy_silent.wav")
    if not os.path.exists(dummy_path):
        with wave.open(dummy_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b'\x00\x00' * 4)
    return dummy_path


def on_optimize_click(sender, app_data):
    """Analyze instruments and apply optimal RAW/VQ per instrument."""
    import ui_refresh as R
    from ui_dialogs import show_error
    from optimize import analyze_instruments
    
    if not state.song.instruments:
        show_error("No Instruments", "Add instruments before optimizing.")
        return
    
    loaded = [inst for inst in state.song.instruments if inst.is_loaded()]
    if not loaded:
        show_error("No Audio", "Instruments have no audio data loaded.")
        return
    
    # Determine which instruments to consider
    used_indices = None
    if state.vq.settings.used_only:
        used_indices = state.song.get_used_instrument_indices()
    
    # Determine banking mode and memory budget
    from constants import MEMORY_CONFIGS, compute_memory_budget
    use_banking = state.song.memory_config != "64 KB"
    budget = compute_memory_budget(
        start_address=state.song.start_address,
        memory_config=state.song.memory_config,
        n_songlines=len(state.song.songlines),
        n_patterns=len(state.song.patterns),
        pattern_lengths=[p.length for p in state.song.patterns],
        n_instruments=len(state.song.instruments),
        vector_size=state.vq.settings.vector_size,
    )
    banking_budget = budget if use_banking else 0
    
    # Run the optimizer
    result = analyze_instruments(
        instruments=state.song.instruments,
        target_rate=state.vq.settings.rate,
        vector_size=state.vq.settings.vector_size,
        memory_budget=budget,
        vq_result=state.vq.result if state.vq.converted else None,
        song=state.song,
        volume_control=state.song.volume_control,
        system_hz=state.song.system,
        used_indices=used_indices,
        use_banking=use_banking,
        banking_budget=banking_budget,
    )
    
    # Apply suggestions directly to instrument checkboxes
    n_changed = 0
    for a in result.analyses:
        if a.skipped:
            continue  # Don't change unused instruments
        if a.index < len(state.song.instruments):
            inst = state.song.instruments[a.index]
            new_use_vq = not a.suggest_raw
            if inst.use_vq != new_use_vq:
                inst.use_vq = new_use_vq
                n_changed += 1
    
    # If any modes changed, re-conversion is required (data format changes)
    if n_changed > 0:
        invalidate_vq_conversion()
    
    # Store result for indicator display in refresh_instruments
    state._optimize_result = result
    
    # Refresh instrument list (checkboxes will reflect the new settings)
    R.refresh_instruments()
    
    # Show summary
    if n_changed > 0:
        G.show_status(f"Optimized: {n_changed} instrument(s) changed. {result.summary}")
    else:
        G.show_status(f"Already optimal. {result.summary}")


def on_vq_convert_click(sender, app_data):
    """Start VQ conversion."""
    from ui_dialogs import show_error
    import logging
    logger = logging.getLogger(__name__)
    
    logger.debug(f"on_vq_convert_click: {len(state.song.instruments)} instruments")
    
    if not state.song.instruments:
        show_error("No Instruments", "Add instruments before converting.")
        return
    
    # Determine which instruments to process
    used_indices = None
    if state.vq.settings.used_only:
        used_indices = state.song.get_used_instrument_indices()
        if not used_indices:
            show_error("No Used Instruments",
                       "No instruments are referenced in the song.\n"
                       "Add notes to patterns first, or uncheck 'Used Samples'.")
            return
        logger.debug(f"Used Samples mode: {len(used_indices)} of "
                     f"{len(state.song.instruments)} instruments used")
    
    input_files, proc_files, error = _prepare_conversion_files(
        state.song.instruments, used_indices=used_indices)
    if input_files is None:
        show_error("Missing File", error)
        return
    
    logger.debug(f"Starting conversion with {len(input_files)} files")
    
    # Track proc files for cleanup after conversion
    global _vq_proc_files, _vq_used_indices
    _vq_proc_files = proc_files
    _vq_used_indices = used_indices
    
    show_vq_conversion_window(input_files)


# =============================================================================
# MOD IMPORT RESULT WINDOW
# =============================================================================

_MOD_OPTIONS_DLG = "mod_import_options"
_MOD_IMPORT_DLG = "mod_import_result"


def show_mod_import_options(path: str, features: dict):
    """Show MOD import wizard dialog with machine selection and live budget."""
    import dearpygui.dearpygui as dpg
    from constants import MEMORY_CONFIGS, MEMORY_CONFIG_NAMES

    if dpg.does_item_exist(_MOD_OPTIONS_DLG):
        dpg.delete_item(_MOD_OPTIONS_DLG)

    state.set_input_active(True)

    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 600, 580

    title = features.get('title', os.path.basename(path))
    vol_count = features.get('vol_slide_count', 0) + features.get('vol_set_count', 0)
    loop_count = features.get('loop_count', 0)
    loop_details = features.get('loop_details', [])
    estimates = features.get('estimated_song_kb', {})
    n_unique = features.get('n_unique_patterns', 0)
    n_pos = features.get('n_positions', 0)
    n_inst = features.get('n_instruments', 0)
    fmt = features.get('format', 'MOD')

    TAG = _MOD_OPTIONS_DLG

    def on_close():
        state.set_input_active(False)
        if dpg.does_item_exist(TAG):
            dpg.delete_item(TAG)

    def _get_data_budget(mem_cfg):
        """Get available bytes for song data in the data region."""
        if mem_cfg == "64 KB":
            # No banking: data region from ~$2000 to $BFFF, minus code+player
            return 42000  # ~42KB after code
        else:
            # Banking: $8000-$BFFF = 16KB, minus fixed overhead
            return 16384 - 5800  # ~10.5KB for song data

    def _get_sample_budget(mem_cfg):
        """Get available bytes for sample audio."""
        for name, n_banks, _ in MEMORY_CONFIGS:
            if name == mem_cfg:
                if n_banks == 0:
                    return 42000  # shares with data in 64KB mode
                return n_banks * 16384  # bank count × 16KB
        return 42000

    def _update_budget(*args):
        """Recalculate and display memory budget when options change."""
        if not dpg.does_item_exist(TAG):
            return

        # Detect if the callback was triggered by the truncation checkbox itself
        # If so, don't auto-toggle it (respect user's manual override)
        sender = args[0] if args else None
        trunc_cb_tag = f"{TAG}_trunc_cb"
        from_trunc_cb = (sender == trunc_cb_tag) if sender else False
        from_trunc_val = (sender == f"{TAG}_trunc_val") if sender else False

        # Read current settings
        mem_cfg = dpg.get_value(f"{TAG}_machine")
        if mem_cfg not in MEMORY_CONFIG_NAMES:
            mem_cfg = "1088 KB"
        vol_on = dpg.get_value(f"{TAG}_vol")
        loops_on = dpg.get_value(f"{TAG}_loop")

        # Song data estimate (pre-truncation)
        if vol_on:
            est_kb = estimates.get('with_volume_dedup', estimates.get('with_volume', 20))
            raw_pats = estimates.get('with_volume_patterns', n_pos * 4)
            mode_str = f"{raw_pats} patterns, ~{int(raw_pats*0.55)} after dedup"
        else:
            est_kb = estimates.get('without_volume', 10)
            raw_pats = estimates.get('without_volume_patterns', n_unique * 4)
            mode_str = f"{raw_pats} patterns (shared across positions)"

        budget = _get_data_budget(mem_cfg)
        raw_est_bytes = int(est_kb * 1024)
        raw_fits = raw_est_bytes <= budget

        # Auto-toggle truncation checkbox when machine/volume changes
        # (NOT when user manually toggles the checkbox or edits trunc value)
        if not from_trunc_cb and not from_trunc_val:
            if dpg.does_item_exist(trunc_cb_tag):
                dpg.set_value(trunc_cb_tag, not raw_fits)
                # Auto-set truncation value when overflow detected
                if not raw_fits and n_pos > 0:
                    per_sl = raw_est_bytes / n_pos
                    fit_sl = max(1, int(budget / per_sl))
                    if dpg.does_item_exist(f"{TAG}_trunc_val"):
                        dpg.set_value(f"{TAG}_trunc_val", fit_sl)

        # Adjust for truncation if enabled
        if (dpg.does_item_exist(f"{TAG}_trunc_cb")
                and dpg.get_value(f"{TAG}_trunc_cb")
                and n_pos > 0):
            try:
                trunc_val = int(dpg.get_value(f"{TAG}_trunc_val"))
                trunc_val = max(1, min(trunc_val, n_pos))
                ratio = trunc_val / n_pos
                est_kb = est_kb * ratio
                mode_str += f" (keeping {trunc_val}/{n_pos} positions)"
            except (ValueError, TypeError):
                pass

        est_bytes = int(est_kb * 1024)
        sample_budget = _get_sample_budget(mem_cfg)
        fits = est_bytes <= budget
        pct = min(100, int(est_bytes * 100 / max(budget, 1)))

        # Update data budget display
        if dpg.does_item_exist(f"{TAG}_budget_data"):
            color = (120, 200, 120) if fits else (240, 100, 100)
            icon = "OK" if fits else "OVERFLOW"
            dpg.set_value(f"{TAG}_budget_data",
                f"  Song data: ~{est_kb:.1f} KB / {budget/1024:.1f} KB "
                f"({pct}%) [{icon}]")
            dpg.configure_item(f"{TAG}_budget_data", color=color)

        if dpg.does_item_exist(f"{TAG}_budget_pats"):
            dpg.set_value(f"{TAG}_budget_pats", f"  {mode_str}")

        if dpg.does_item_exist(f"{TAG}_budget_samples"):
            dpg.set_value(f"{TAG}_budget_samples",
                f"  Sample space: {sample_budget//1024} KB "
                f"({'banked' if mem_cfg != '64 KB' else 'shared with data'})")

        # Volume impact line
        if dpg.does_item_exist(f"{TAG}_vol_impact"):
            if vol_on:
                vol_kb = estimates.get('with_volume_dedup', 20)
                dpg.set_value(f"{TAG}_vol_impact",
                    f"    ~{vol_kb:.1f} KB song data (with dedup)")
            else:
                no_vol_kb = estimates.get('without_volume', 10)
                dpg.set_value(f"{TAG}_vol_impact",
                    f"    ~{no_vol_kb:.1f} KB song data")

        # Truncation info
        if dpg.does_item_exist(f"{TAG}_trunc_info"):
            trunc_on = (dpg.does_item_exist(f"{TAG}_trunc_cb")
                        and dpg.get_value(f"{TAG}_trunc_cb"))
            if not raw_fits and n_pos > 0:
                per_sl = raw_est_bytes / max(n_pos, 1)
                fit_sl = max(1, int(budget / per_sl))
                if trunc_on:
                    dpg.set_value(f"{TAG}_trunc_info",
                        f"    Keeping ~{fit_sl} of {n_pos} positions "
                        f"to fit in {budget/1024:.1f} KB.")
                else:
                    overflow_kb = est_kb - budget / 1024
                    dpg.set_value(f"{TAG}_trunc_info",
                        f"    Warning: data overflows by "
                        f"~{overflow_kb:.1f} KB.")
            else:
                if trunc_on:
                    try:
                        tv = int(dpg.get_value(f"{TAG}_trunc_val"))
                        if tv < n_pos:
                            dpg.set_value(f"{TAG}_trunc_info",
                                f"    Keeping {tv} of {n_pos} positions.")
                        else:
                            dpg.set_value(f"{TAG}_trunc_info", "")
                    except (ValueError, TypeError):
                        dpg.set_value(f"{TAG}_trunc_info", "")
                else:
                    dpg.set_value(f"{TAG}_trunc_info", "")

        # Loop size summary
        if dpg.does_item_exist(f"{TAG}_loop_size"):
            if loops_on and loop_details:
                try:
                    max_rep = int(dpg.get_value(f"{TAG}_max_repeats"))
                except (ValueError, TypeError):
                    max_rep = 8
                total_ext = 0
                for ld in loop_details:
                    reps = min(ld['calculated_repeats'], max_rep)
                    ext = ld['sample_bytes'] + max(0, reps - 1) * ld['loop_length'] * 2
                    total_ext += ext
                dpg.set_value(f"{TAG}_loop_size",
                    f"    Total extended sample data: ~{total_ext//1024} KB")
            else:
                dpg.set_value(f"{TAG}_loop_size", "")

    def on_import():
        mem_cfg = dpg.get_value(f"{TAG}_machine")
        if mem_cfg not in MEMORY_CONFIG_NAMES:
            mem_cfg = "1088 KB"
        max_rep = 8
        if dpg.does_item_exist(f"{TAG}_max_repeats"):
            try:
                max_rep = int(dpg.get_value(f"{TAG}_max_repeats"))
                max_rep = max(1, min(8, max_rep))
            except (ValueError, TypeError):
                max_rep = 8
        trunc = 0
        if dpg.does_item_exist(f"{TAG}_trunc_cb") and dpg.get_value(f"{TAG}_trunc_cb"):
            try:
                trunc = int(dpg.get_value(f"{TAG}_trunc_val"))
                trunc = max(1, trunc)
            except (ValueError, TypeError):
                trunc = 0

        options = {
            'volume_control': dpg.get_value(f"{TAG}_vol"),
            'extend_loops': dpg.get_value(f"{TAG}_loop"),
            'max_loop_repeats': max_rep,
            'memory_config': mem_cfg,
            'truncate_songlines': trunc,
            'dedup_patterns': True,
        }
        on_close()
        from ops.file_ops import _do_import_mod
        _do_import_mod(path, options)

    with dpg.window(tag=TAG, label=f"Import: {title}",
                    modal=True, width=w, height=h,
                    pos=[(vp_w - w) // 2, (vp_h - h) // 2],
                    no_resize=False, no_collapse=True, on_close=on_close):

        # Scrollable content area (keeps Import button visible)
        with dpg.child_window(height=-40, border=False):

            # === Header ===
            dpg.add_text(f"Importing: {os.path.basename(path)}")
            dpg.add_text(f"{fmt}, {n_unique} patterns, {n_pos} positions, "
                         f"{n_inst} instruments",
                         color=(160, 160, 160))
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # === Section 1: Target Machine ===
            dpg.add_text("TARGET MACHINE", color=(200, 200, 100))
            dpg.add_spacer(height=2)

            # Machine dropdown
            with dpg.group(horizontal=True):
                dpg.add_text("  Machine:")
                dpg.add_spacer(width=5)
                # Default to largest memory config (most capable)
                default_idx = len(MEMORY_CONFIG_NAMES) - 1
                dpg.add_combo(tag=f"{TAG}_machine",
                              items=MEMORY_CONFIG_NAMES,
                              default_value=MEMORY_CONFIG_NAMES[default_idx],
                              width=250, callback=_update_budget)

            dpg.add_spacer(height=2)
            dpg.add_text("", tag=f"{TAG}_budget_data", color=(120, 200, 120))
            dpg.add_text("", tag=f"{TAG}_budget_pats", color=(140, 140, 140))
            dpg.add_text("", tag=f"{TAG}_budget_samples", color=(140, 140, 140))

            dpg.add_spacer(height=6)
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # === Section 2: Volume Control ===
            dpg.add_text("VOLUME CONTROL", color=(200, 200, 100))
            dpg.add_spacer(height=2)

            vol_default = vol_count > 0
            dpg.add_checkbox(tag=f"{TAG}_vol",
                             label="Enable per-row volume control",
                             default_value=vol_default,
                             callback=_update_budget)
            if vol_count > 0:
                dpg.add_text(f"    {vol_count} volume effect(s) detected.",
                             color=(180, 180, 180))
            else:
                dpg.add_text("    No volume effects detected.",
                             color=(140, 140, 140))
            dpg.add_text("", tag=f"{TAG}_vol_impact", color=(160, 160, 160))

            dpg.add_spacer(height=6)
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # === Section 3: Loop Extension ===
            dpg.add_text("LOOP EXTENSION", color=(200, 200, 100))
            dpg.add_spacer(height=2)

            loop_default = loop_count > 0
            dpg.add_checkbox(tag=f"{TAG}_loop",
                             label="Extend looped instruments",
                             default_value=loop_default,
                             callback=_update_budget)
            if loop_count > 0:
                dpg.add_text(f"    {loop_count} looped sample(s) detected.",
                             color=(180, 180, 180))
                with dpg.group(horizontal=True):
                    dpg.add_text("    Max repeats:")
                    dpg.add_spacer(width=5)
                    dpg.add_input_int(tag=f"{TAG}_max_repeats",
                                      default_value=8, min_value=1,
                                      max_value=8, width=80, step=0,
                                      callback=_update_budget)
                # Loop details table
                if loop_details:
                    with dpg.child_window(height=min(100, 20 * len(loop_details) + 25),
                                          border=True):
                        dpg.add_text("  Inst  Name                  Repeats   Size",
                                     color=(120, 120, 140))
                        for ld in sorted(loop_details,
                                         key=lambda x: -x['extended_bytes'])[:8]:
                            reps = ld['calculated_repeats']
                            sz_kb = ld['extended_bytes'] / 1024
                            warn = " (!)" if sz_kb > 100 else ""
                            name = ld['name'][:22].ljust(22)
                            dpg.add_text(
                                f"  {ld['mod_num']:3d}   {name} {reps:3d}x   "
                                f"{sz_kb:6.0f} KB{warn}",
                                color=(200, 180, 100) if sz_kb > 100
                                      else (160, 160, 160))
                    if len(loop_details) > 8:
                        dpg.add_text(f"    ... and {len(loop_details) - 8} more",
                                     color=(120, 120, 120))
                dpg.add_text("", tag=f"{TAG}_loop_size", color=(160, 160, 160))
            else:
                dpg.add_text("    No looped samples detected.",
                             color=(140, 140, 140))

            dpg.add_spacer(height=6)
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # === Section 4: Truncation (always visible) ===
            dpg.add_text("TRUNCATION", color=(200, 200, 100))
            dpg.add_spacer(height=2)

            # Compute initial fit so we know whether truncation is needed
            _init_est_kb = estimates.get(
                'with_volume_dedup' if vol_count > 0 else 'without_volume', 10)
            _init_budget = _get_data_budget("1088 KB")  # default machine
            _init_est_bytes = int(_init_est_kb * 1024)
            _init_overflow = _init_est_bytes > _init_budget and n_pos > 0
            if _init_overflow:
                _per_sl = _init_est_bytes / n_pos
                _init_trunc = max(1, int(_init_budget / _per_sl))
            else:
                _init_trunc = n_pos

            with dpg.group(horizontal=True):
                dpg.add_checkbox(tag=f"{TAG}_trunc_cb",
                                 label="Truncate song to fit",
                                 default_value=_init_overflow,
                                 callback=_update_budget)
                dpg.add_spacer(width=10)
                dpg.add_text("Keep first")
                dpg.add_input_int(tag=f"{TAG}_trunc_val",
                                  default_value=_init_trunc,
                                  min_value=1, max_value=max(n_pos, 1),
                                  width=70, step=0,
                                  callback=_update_budget)
                dpg.add_text(f"of {n_pos} positions")
            dpg.add_text("", tag=f"{TAG}_trunc_info", color=(180, 150, 100))
            dpg.add_text("    Pattern dedup is automatic (identical patterns merged).",
                         color=(140, 140, 140))

            dpg.add_spacer(height=4)
            dpg.add_separator()

        # === Import / Cancel (outside scroll area, always visible) ===
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=350)
            dpg.add_button(label="Import", width=100, callback=on_import)
            dpg.add_spacer(width=10)
            dpg.add_button(label="Cancel", width=100, callback=on_close)

    # Initial budget calculation
    _update_budget()

    # Fix combo default (combo uses string value, not index)
    dpg.set_value(f"{TAG}_machine", MEMORY_CONFIG_NAMES[default_idx])


def show_mod_import_result(import_log, success: bool):
    """Show MOD import result window with log output."""
    if dpg.does_item_exist(_MOD_IMPORT_DLG):
        dpg.delete_item(_MOD_IMPORT_DLG)

    state.set_input_active(True)

    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 700, 450

    title = "MOD Import - Complete" if success else "MOD Import - Failed"

    def on_close():
        state.set_input_active(False)
        if dpg.does_item_exist(_MOD_IMPORT_DLG):
            dpg.delete_item(_MOD_IMPORT_DLG)

    with dpg.window(tag=_MOD_IMPORT_DLG, label=title, modal=True,
                    width=w, height=h,
                    pos=[(vp_w - w) // 2, (vp_h - h) // 2],
                    no_resize=False, no_collapse=True, on_close=on_close):

        # Status line
        if success:
            dpg.add_text(import_log.summary_line(), color=(120, 200, 120))
        else:
            dpg.add_text(import_log.summary_line(), color=(240, 80, 80))
        dpg.add_separator()
        dpg.add_spacer(height=5)

        # Log text area
        with dpg.child_window(tag=f"{_MOD_IMPORT_DLG}_scroll",
                               height=-50, border=True):
            dpg.add_input_text(tag=f"{_MOD_IMPORT_DLG}_text",
                               multiline=True, readonly=True,
                               width=-1, height=-1,
                               default_value=import_log.get_text())

        dpg.add_spacer(height=5)

        # Close button
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=550)
            dpg.add_button(label="Close", width=100, callback=on_close)

    # Scroll to bottom
    if dpg.does_item_exist(f"{_MOD_IMPORT_DLG}_scroll"):
        dpg.set_y_scroll(f"{_MOD_IMPORT_DLG}_scroll",
                         dpg.get_y_scroll_max(f"{_MOD_IMPORT_DLG}_scroll"))


# =============================================================================
# VQ CONVERSION
# =============================================================================

# Global reference to converter for polling
_vq_converter = None
_vq_proc_files = []
_vq_used_indices = None  # Set of instrument indices that were converted (None = all)


def show_vq_conversion_window(input_files: list):
    """Show VQ conversion progress window."""
    global _vq_converter
    from vq_convert import VQConverter, format_size
    
    if dpg.does_item_exist("vq_conv_window"):
        dpg.delete_item("vq_conv_window")
    
    state.set_input_active(True)
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 700, 450
    
    def on_close():
        global _vq_converter
        if state.vq.is_converting():
            state.vq.cancel_conversion()
        state.set_input_active(False)
        _vq_converter = None
        if dpg.does_item_exist("vq_conv_window"):
            dpg.delete_item("vq_conv_window")
    
    with dpg.window(tag="vq_conv_window", label="VQ Conversion", modal=True,
                    width=w, height=h, pos=[(vp_w - w) // 2, (vp_h - h) // 2],
                    no_resize=False, no_collapse=True, on_close=on_close):
        
        if _vq_used_indices is not None:
            n_used = len(_vq_used_indices)
            n_total = len(input_files)
            dpg.add_text(f"Converting {n_used} of {n_total} instrument(s) (Used Samples mode)...")
        else:
            dpg.add_text(f"Converting {len(input_files)} instrument(s)...")
        dpg.add_separator()
        dpg.add_spacer(height=5)
        
        # Output text area
        with dpg.child_window(tag="vq_output_scroll", height=-50, border=True):
            dpg.add_input_text(tag="vq_output_text", multiline=True, readonly=True,
                               width=-1, height=-1, default_value="")
        
        dpg.add_spacer(height=5)
        
        # Buttons
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=250)
            dpg.add_button(tag="vq_cancel_btn", label="Cancel", width=90, 
                           callback=lambda: state.vq.cancel_conversion())
            dpg.add_spacer(width=20)
            dpg.add_button(tag="vq_close_btn", label="Processing...", width=90, 
                           enabled=False, callback=on_close)
    
    # Start conversion — pass per-instrument RAW/VQ modes
    # Must match input_files ordering (all instruments, same as _prepare_conversion_files)
    sample_modes = [0 if inst.use_vq else 1 for inst in state.song.instruments]
    _vq_converter = VQConverter(state.vq)
    _vq_converter.convert(input_files, sample_modes=sample_modes)


def poll_vq_conversion():
    """Poll VQ conversion status - call from main loop."""
    global _vq_converter
    from vq_convert import format_size
    
    if _vq_converter is None:
        return
    
    # Process pending output lines (thread-safe)
    lines = state.vq.get_pending_output()
    if lines and dpg.does_item_exist("vq_output_text"):
        current = dpg.get_value("vq_output_text")
        new_text = current + "".join(lines)
        dpg.set_value("vq_output_text", new_text)
        # Auto-scroll to bottom
        if dpg.does_item_exist("vq_output_scroll"):
            dpg.set_y_scroll("vq_output_scroll", dpg.get_y_scroll_max("vq_output_scroll"))
    
    # Check for completion
    result = state.vq.check_completion()
    if result is not None:
        # Update UI on completion
        if dpg.does_item_exist("vq_close_btn"):
            dpg.configure_item("vq_close_btn", label="Close", enabled=True)
        
        if dpg.does_item_exist("vq_cancel_btn"):
            dpg.configure_item("vq_cancel_btn", show=False)
        
        if result.success:
            if dpg.does_item_exist("vq_size_label"):
                if result.vq_data_size > 0:
                    label = f"Atari: {format_size(result.vq_data_size)}"
                    if result.vq_only_size > 0 and result.raw_only_size > 0:
                        label = (f"VQ: {format_size(result.vq_only_size)}"
                                 f"  RAW: {format_size(result.raw_only_size)}"
                                 f"  Total: {format_size(result.vq_data_size)}")
                    elif result.raw_only_size > 0:
                        label = f"RAW: {format_size(result.raw_only_size)}"
                    elif result.vq_only_size > 0:
                        label = f"VQ: {format_size(result.vq_only_size)}"
                    dpg.set_value("vq_size_label", label)
                else:
                    dpg.set_value("vq_size_label", "")
            
            # Compute per-instrument RAW sizes for display
            if not result.inst_raw_sizes:
                from optimize import compute_raw_size
                for inst in state.song.instruments:
                    if inst.is_loaded():
                        if inst.effects and inst.processed_data is None:
                            try:
                                from sample_editor.pipeline import run_pipeline
                                inst.processed_data = run_pipeline(
                                    inst.sample_data, inst.sample_rate, inst.effects)
                            except Exception:
                                pass
                        data = inst.processed_data if inst.processed_data is not None else inst.sample_data
                        raw_sz = compute_raw_size(data, inst.sample_rate,
                                                  state.vq.settings.rate)
                        result.inst_raw_sizes.append(raw_sz)
                    else:
                        result.inst_raw_sizes.append(0)
            
            # Auto-enable and check "Use converted" checkbox
            if dpg.does_item_exist("vq_use_converted_cb"):
                dpg.configure_item("vq_use_converted_cb", enabled=True)
                dpg.set_value("vq_use_converted_cb", True)
            
            # Auto-load converted samples
            state.vq.use_converted = True
            _load_converted_samples()
            state.audio.set_song(state.song)
            
            # SYNCHRONIZATION: Update BUILD button to green now that VQ is valid
            update_build_button_state()
            
            # Refresh instruments (will show green because use_converted=True)
            R.refresh_instruments()
            if result.vq_data_size > 0:
                if result.vq_only_size > 0 and result.raw_only_size > 0:
                    G.show_status(
                        f"Converted: VQ {format_size(result.vq_only_size)}"
                        f" + RAW {format_size(result.raw_only_size)}"
                        f" = {format_size(result.vq_data_size)}")
                else:
                    G.show_status(f"Conversion complete: {format_size(result.vq_data_size)}")
            else:
                G.show_status("Conversion complete")
        else:
            G.show_status(f"Conversion failed: {result.error_message}")
        
        # Clean up processed temp files
        global _vq_proc_files
        for proc_path in _vq_proc_files:
            try:
                if os.path.exists(proc_path):
                    os.remove(proc_path)
            except OSError:
                pass
        _vq_proc_files = []


def update_vq_convert_button():
    """Update convert button appearance based on state."""
    if not dpg.does_item_exist("vq_convert_btn"):
        return
    
    if state.vq.converted:
        # Green for converted
        # Note: would need theme to change button color
        pass
    else:
        # Normal state
        pass


# =============================================================================
# BUILD
# =============================================================================

def on_build_click(sender, app_data):
    """Build Atari executable (.xex) - validates first."""
    from ui_dialogs import show_error, show_info
    import build
    
    # Run comprehensive validation as first step
    validation = build.validate_for_build(state.song)
    
    if not validation.valid:
        # Show detailed validation dialog with all issues
        show_build_validation_dialog(validation)
        return
    
    # Show warnings but continue
    if validation.warning_count > 0:
        warning_lines = []
        for issue in validation.issues:
            if issue.severity == "warning":
                warning_lines.append(f"- {issue.location}: {issue.message}")
        # Log warnings but don't block
        logger.warning(f"Build warnings: {warning_lines}")
    
    # Legacy checks (now handled by validation, but keep as backup)
    if not state.song.instruments:
        show_error("Cannot Build", "No instruments loaded.\n\nLoad samples first using [Add] or [Folder].")
        return
    
    if not state.vq.converted:
        show_error("Cannot Build", "Instruments not converted.\n\nClick [CONVERT] first to prepare samples for Atari.")
        return
    
    if not state.vq.result or not state.vq.result.output_dir:
        show_error("Cannot Build", "Conversion data not found.\n\nPlease run [CONVERT] again.")
        return
    
    # Build directly to app directory with sanitized song name
    # Sanitize title for filename (cross-platform safe)
    title = state.song.title or "untitled"
    # Keep only alphanumeric, spaces, hyphens, underscores
    safe_title = "".join(c if c.isalnum() or c in "_ -" else "_" for c in title)
    safe_title = safe_title.strip()[:50] or "song"
    
    # Build path: app_dir/songname.xex
    xex_path = os.path.join(str(G.APP_DIR), f"{safe_title}.xex")
    
    # Show build progress window directly
    show_build_progress_window(xex_path)


def show_build_validation_dialog(validation):
    """Show validation results dialog when BUILD fails validation."""
    if dpg.does_item_exist("build_validation_dlg"):
        dpg.delete_item("build_validation_dlg")
    
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    dlg_w, dlg_h = 500, 400
    
    with dpg.window(tag="build_validation_dlg", label="Build Failed - Validation Errors", modal=True, 
                    no_resize=False, no_collapse=True, width=dlg_w, height=dlg_h,
                    pos=[(vp_w - dlg_w) // 2, (vp_h - dlg_h) // 2]):
        
        # Summary line
        dpg.add_text(f"[X] Cannot build: {validation.error_count} error(s) found", color=(255, 100, 100))
        
        if validation.warning_count > 0:
            dpg.add_text(f"[!] {validation.warning_count} warning(s)", color=(255, 200, 100))
        
        dpg.add_separator()
        dpg.add_spacer(height=5)
        
        dpg.add_text("Please fix the following issues:", color=(200, 200, 200))
        dpg.add_spacer(height=5)
        
        # Issues list
        with dpg.child_window(height=-50, border=True):
            for issue in validation.issues:
                if issue.severity == "error":
                    color = (255, 100, 100)
                    icon = "[X]"
                else:
                    color = (255, 200, 100)
                    icon = "[!]"
                
                with dpg.group(horizontal=True):
                    dpg.add_text(icon, color=color)
                    dpg.add_text(f"{issue.location}:", color=(200, 200, 255))
                    dpg.add_text(issue.message)
        
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=(dlg_w - 100) // 2)
            dpg.add_button(label="Close", width=80, 
                          callback=lambda: dpg.delete_item("build_validation_dlg"))


def show_build_progress_window(xex_path: str):
    """Show build progress window with real-time output."""
    import build
    
    if dpg.does_item_exist("build_progress_window"):
        dpg.delete_item("build_progress_window")
    
    state.set_input_active(True)
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 700, 450
    
    def on_close():
        state.set_input_active(False)
        if dpg.does_item_exist("build_progress_window"):
            dpg.delete_item("build_progress_window")
    
    with dpg.window(tag="build_progress_window", label="Building XEX", modal=True,
                    width=w, height=h, pos=[(vp_w - w) // 2, (vp_h - h) // 2],
                    no_resize=False, no_collapse=True, on_close=on_close):
        
        dpg.add_text(f"Building: {os.path.basename(xex_path)}")
        dpg.add_separator()
        dpg.add_spacer(height=5)
        
        # Output text area
        with dpg.child_window(tag="build_output_scroll", height=-50, border=True):
            dpg.add_input_text(tag="build_output_text", multiline=True, readonly=True,
                               width=-1, height=-1, default_value="")
        
        dpg.add_spacer(height=5)
        
        # Buttons
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=550)
            dpg.add_button(tag="build_close_btn", label="Close", width=100, 
                           callback=on_close, enabled=False)
    
    # Start async build
    build.start_build_async(state.song, xex_path)
    G.show_status("Building XEX...")


def poll_build_progress():
    """Poll build progress (called from main loop)."""
    global _last_built_xex
    import build
    
    if not dpg.does_item_exist("build_progress_window"):
        return
    
    if not build.build_state.is_building and not build.build_state.build_complete:
        return
    
    # Get pending output
    while True:
        text = build.build_state.get_pending_output()
        if text is None:
            break
        # Append to text area
        if dpg.does_item_exist("build_output_text"):
            current = dpg.get_value("build_output_text")
            dpg.set_value("build_output_text", current + text)
            # Auto-scroll to bottom
            if dpg.does_item_exist("build_output_scroll"):
                dpg.set_y_scroll("build_output_scroll", dpg.get_y_scroll_max("build_output_scroll"))
    
    # Check completion
    if build.build_state.build_complete:
        result = build.build_state.completion_result
        
        # Enable close button
        if dpg.does_item_exist("build_close_btn"):
            dpg.configure_item("build_close_btn", enabled=True)
        
        # Update status
        if result and result.success:
            G.show_status(f"Build complete: {os.path.basename(result.xex_path)}")
            # Store XEX path for run
            _last_built_xex = result.xex_path
            
            # Auto-run the XEX after successful build
            # Close the progress window first
            if dpg.does_item_exist("build_progress_window"):
                state.set_input_active(False)
                dpg.delete_item("build_progress_window")
            # Run the built XEX
            on_run_click(None, None)
        else:
            error_msg = result.error_message if result else "Unknown error"
            G.show_status(f"Build failed: {error_msg[:50]}...")
        
        # Reset completion flag so we don't keep triggering
        build.build_state.build_complete = False


def on_run_click(sender, app_data):
    """Run the last built XEX in emulator."""
    from ui_dialogs import show_error
    import sys
    import platform
    
    if not _last_built_xex or not os.path.exists(_last_built_xex):
        show_error("Cannot Run", "No XEX file found.\n\nBuild the project first.")
        return
    
    G.show_status(f"Running: {os.path.basename(_last_built_xex)}")
    
    try:
        # Try to open with default application (works on most systems)
        if platform.system() == 'Windows':
            os.startfile(_last_built_xex)
        elif platform.system() == 'Darwin':  # macOS
            subprocess.Popen(['open', _last_built_xex])
        else:  # Linux
            subprocess.Popen(['xdg-open', _last_built_xex])
    except Exception as e:
        show_error("Run Failed", f"Could not launch XEX:\n{e}\n\n"
                   f"File: {_last_built_xex}\n\n"
                   "You may need to configure your system to open .xex files with an Atari emulator.")


# =============================================================================
# BUTTON BLINK (Attention indicators)
# =============================================================================

def poll_button_blink():
    """Update blinking buttons for attention indicators.
    
    - ADD/FOLDER buttons blink when no instruments loaded
    - CONVERT button blinks when instruments loaded but not converted
    """
    global _blink_state, _last_blink_time
    
    current_time = time.time()
    if current_time - _last_blink_time < BLINK_INTERVAL:
        return
    
    _last_blink_time = current_time
    _blink_state = not _blink_state
    
    has_instruments = len(state.song.instruments) > 0
    vq_converted = state.vq.converted
    
    # Choose blink theme based on current phase
    blink_theme = "theme_btn_blink_bright" if _blink_state else "theme_btn_blink_dim"
    
    # ADD and FOLDER buttons - blink when no instruments
    if dpg.does_item_exist("inst_add_btn") and dpg.does_item_exist("inst_folder_btn"):
        if not has_instruments:
            # No instruments - blink to draw attention
            dpg.bind_item_theme("inst_add_btn", blink_theme)
            dpg.bind_item_theme("inst_folder_btn", blink_theme)
        else:
            # Has instruments - use disabled theme (normal button look)
            dpg.bind_item_theme("inst_add_btn", "theme_btn_disabled")
            dpg.bind_item_theme("inst_folder_btn", "theme_btn_disabled")
    
    # CONVERT button - blink when instruments exist but not converted
    if dpg.does_item_exist("vq_convert_btn"):
        if has_instruments and not vq_converted:
            # Need conversion - blink
            dpg.bind_item_theme("vq_convert_btn", blink_theme)
        elif has_instruments and vq_converted:
            # Converted - green (solid)
            dpg.bind_item_theme("vq_convert_btn", "theme_btn_green")
        else:
            # No instruments - disabled/gray
            dpg.bind_item_theme("vq_convert_btn", "theme_btn_disabled")
