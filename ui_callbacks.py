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
import operations as ops
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
            idx = state.song.add_pattern()
            if idx >= 0:
                state.song.songlines[sl_idx].patterns[ch] = idx
                state.selected_pattern = idx
                ops.save_undo("Add pattern")
        else:
            try:
                idx = int(value, 16) if state.hex_mode else int(value)
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
            state.song.songlines[sl_idx].speed = spd
            state.song.modified = True
            ops.save_undo("Change speed")
        except: pass
        
        # Update cursor position
        state.song_cursor_row = sl_idx
        state.song_cursor_col = 3  # SPD column
        state.songline = sl_idx
        
        dpg.delete_item("popup_spd")
        R.refresh_song_editor()
        R.refresh_editor()
    
    def on_cancel():
        """Called when popup closes without selection."""
        state.set_input_active(False)
        # Still move cursor to clicked cell
        state.song_cursor_row = sl_idx
        state.song_cursor_col = 3  # SPD column
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


def on_speed_change(sender, value):
    state.song.speed = max(1, min(255, value))
    state.song.modified = True


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
            G.show_status(f"⚠ Max pattern length is {MAX_ROWS} (row 255 reserved for export)")
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
        idx = state.song.add_pattern()
        if idx >= 0:
            state.selected_pattern = idx
            ops.save_undo("Add pattern")
            R.refresh_all_pattern_combos()
            R.refresh_pattern_info()
            G.show_status(f"Added pattern {G.fmt(idx)}")
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            state.selected_pattern = idx
            R.refresh_pattern_info()
        except: pass


def on_songline_pattern_change(sender, value, user_data):
    sl_idx, ch = user_data
    if value == "+":
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[sl_idx].patterns[ch] = idx
            state.selected_pattern = idx
            ops.save_undo("Add pattern")
            R.refresh_all()
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            state.song.songlines[sl_idx].patterns[ch] = idx
            state.selected_pattern = idx
            state.song.modified = True
            R.refresh_pattern_info()
            R.refresh_editor()
        except: pass


def on_editor_pattern_change(sender, value, user_data):
    ch = user_data
    if value == "+":
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[state.songline].patterns[ch] = idx
            state.selected_pattern = idx
            ops.save_undo("Add pattern")
            R.refresh_all()
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
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
        G.show_status("Warning: Volume requires sample rate ≤5757 Hz")
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


def on_analyze_click():
    """Show timing analysis dialog."""
    show_analyze_dialog()


def show_analyze_dialog():
    """Display the timing analysis window."""
    try:
        from analyze import analyze_song, format_analysis_report
        
        # Check if we have VQ settings
        if not state.vq.converted:
            # Show a popup instead of just status bar message
            if dpg.does_item_exist("analyze_error_popup"):
                dpg.delete_item("analyze_error_popup")
            
            vp_w = dpg.get_viewport_width()
            vp_h = dpg.get_viewport_height()
            w, h = 350, 120
            
            with dpg.window(
                tag="analyze_error_popup",
                label="Cannot Analyze",
                modal=True,
                width=w, height=h,
                pos=[(vp_w - w) // 2, (vp_h - h) // 2],
                no_resize=True, no_collapse=True,
                on_close=lambda: dpg.delete_item("analyze_error_popup")
            ):
                dpg.add_text("Run CONVERT first!", color=(255, 200, 100))
                dpg.add_spacer(height=5)
                dpg.add_text("ANALYZE requires VQ settings from conversion.")
                dpg.add_text("Click CONVERT to generate VQ data.")
                dpg.add_spacer(height=10)
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=(w - 80) // 2)
                    dpg.add_button(label="OK", width=80,
                                  callback=lambda: dpg.delete_item("analyze_error_popup"))
            return
        
        # Get VQ settings
        rate = state.vq.settings.rate
        vector_size = state.vq.settings.vector_size
        optimize_speed = state.vq.settings.optimize_speed
        
        # Run analysis
        result = analyze_song(state.song, rate, vector_size, optimize_speed)
        report = format_analysis_report(result)
        
        # Close existing dialog if any
        if dpg.does_item_exist("analyze_dialog"):
            dpg.delete_item("analyze_dialog")
        
        # Create dialog window
        vp_w = dpg.get_viewport_width()
        vp_h = dpg.get_viewport_height()
        w, h = 600, 500
        
        with dpg.window(
            tag="analyze_dialog",
            label="Timing Analysis",
            modal=True,
            width=w,
            height=h,
            pos=[(vp_w - w) // 2, (vp_h - h) // 2],
            no_resize=False,
            no_collapse=True,
            on_close=lambda: dpg.delete_item("analyze_dialog")
        ):
            # Status header
            if result.is_safe:
                dpg.add_text("✓ PASS - No timing issues detected", color=(100, 255, 100))
            else:
                pct = (result.over_budget_count / result.total_rows * 100) if result.total_rows > 0 else 0
                dpg.add_text(f"✗ FAIL - {result.over_budget_count} rows overflow ({pct:.1f}%)", 
                            color=(255, 100, 100))
            
            # Volume control warning
            if state.song.volume_control and not result.volume_safe:
                dpg.add_text(f"⚠ Volume control requires rate ≤5757 Hz (current: {rate})", 
                            color=(255, 200, 100))
            
            dpg.add_separator()
            
            # Summary info
            with dpg.group(horizontal=True):
                dpg.add_text(f"Rate: {rate} Hz")
                dpg.add_spacer(width=20)
                dpg.add_text(f"Vector: {vector_size}")
                dpg.add_spacer(width=20)
                dpg.add_text(f"Budget: {result.available_cycles} cycles")
            
            dpg.add_spacer(height=5)
            
            # Log area with scrolling
            with dpg.child_window(tag="analyze_log_scroll", height=-40, border=True):
                dpg.add_input_text(
                    tag="analyze_log",
                    default_value=report,
                    multiline=True,
                    readonly=True,
                    width=-1,
                    height=-1,
                    tab_input=False
                )
            
            # Close button
            dpg.add_spacer(height=5)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=(w - 100) // 2)
                dpg.add_button(label="Close", width=100, 
                              callback=lambda: dpg.delete_item("analyze_dialog"))
        
        # Auto-scroll to bottom after dialog is created
        # Use split_frame to ensure layout is computed before scrolling
        dpg.split_frame()
        if dpg.does_item_exist("analyze_log_scroll"):
            dpg.set_y_scroll("analyze_log_scroll", dpg.get_y_scroll_max("analyze_log_scroll"))
    
    except Exception as e:
        import traceback
        error_msg = f"ANALYZE error: {e}\n{traceback.format_exc()}"
        print(error_msg)
        G.show_status(f"ANALYZE error: {e}")


def on_input_inst_change(sender, value):
    try:
        idx = int(value.split(" - ")[0], 16 if state.hex_mode else 10)
        state.instrument = idx
        R.refresh_instruments()
    except: pass


def on_input_vol_change(sender, value):
    try:
        vol = int(value, 16) if state.hex_mode else int(value)
        state.volume = max(0, min(MAX_VOLUME, vol))
    except: pass


def on_reset_song():
    def do_reset():
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


def on_play_pattern_click(sender, app_data):
    ops.play_stop()


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

def on_move_inst_up(sender, app_data):
    if state.instrument > 0 and state.instrument < len(state.song.instruments):
        idx = state.instrument
        state.song.instruments[idx], state.song.instruments[idx-1] = \
            state.song.instruments[idx-1], state.song.instruments[idx]
        state.instrument -= 1
        state.song.modified = True
        state.vq.invalidate()  # Invalidate VQ conversion
        R.refresh_instruments()
        G.show_status("Moved instrument up")


def on_move_inst_down(sender, app_data):
    if state.instrument < len(state.song.instruments) - 1:
        idx = state.instrument
        state.song.instruments[idx], state.song.instruments[idx+1] = \
            state.song.instruments[idx+1], state.song.instruments[idx]
        state.instrument += 1
        state.song.modified = True
        state.vq.invalidate()  # Invalidate VQ conversion
        R.refresh_instruments()
        G.show_status("Moved instrument down")


# =============================================================================
# SONGLINE MANAGEMENT
# =============================================================================

def on_move_songline_up(sender, app_data):
    if state.song_cursor_row > 0:
        idx = state.song_cursor_row
        state.song.songlines[idx], state.song.songlines[idx-1] = \
            state.song.songlines[idx-1], state.song.songlines[idx]
        state.song_cursor_row -= 1
        state.songline = state.song_cursor_row
        state.song.modified = True
        ops.save_undo("Move songline up")
        R.refresh_song_editor()
        R.refresh_editor()
        G.show_status("Moved songline up")


def on_move_songline_down(sender, app_data):
    if state.song_cursor_row < len(state.song.songlines) - 1:
        idx = state.song_cursor_row
        state.song.songlines[idx], state.song.songlines[idx+1] = \
            state.song.songlines[idx+1], state.song.songlines[idx]
        state.song_cursor_row += 1
        state.songline = state.song_cursor_row
        state.song.modified = True
        ops.save_undo("Move songline down")
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
    """
    if app_data != 0:  # 0 = left click
        return
    
    # Don't process if a popup/modal is active
    if state.input_active:
        return
    
    mouse_pos = dpg.get_mouse_pos(local=False)
    
    # Check song panel - just set focus, don't change row (buttons handle that)
    if dpg.does_item_exist("song_panel"):
        try:
            pos = dpg.get_item_pos("song_panel")
            rect = dpg.get_item_rect_size("song_panel")
            if pos and rect:
                if (pos[0] <= mouse_pos[0] <= pos[0] + rect[0] and
                    pos[1] <= mouse_pos[1] <= pos[1] + rect[1]):
                    G.set_focus(FOCUS_SONG)
                    # Don't update row here - button callbacks handle cell selection
                    # This prevents race condition with popup dialogs
                    return
        except:
            pass
    
    # Check editor panel - just set focus, don't change row (buttons handle that)
    if dpg.does_item_exist("editor_panel"):
        try:
            pos = dpg.get_item_pos("editor_panel")
            rect = dpg.get_item_rect_size("editor_panel")
            if pos and rect:
                if (pos[0] <= mouse_pos[0] <= pos[0] + rect[0] and
                    pos[1] <= mouse_pos[1] <= pos[1] + rect[1]):
                    G.set_focus(FOCUS_EDITOR)
                    # Don't update row here - button callbacks handle cell selection
                    # This prevents race condition with popup dialogs
                    return
        except:
            pass
    
    # Check instruments panel
    if dpg.does_item_exist("inst_panel"):
        try:
            pos = dpg.get_item_pos("inst_panel")
            rect = dpg.get_item_rect_size("inst_panel")
            if pos and rect:
                if (pos[0] <= mouse_pos[0] <= pos[0] + rect[0] and
                    pos[1] <= mouse_pos[1] <= pos[1] + rect[1]):
                    G.set_focus(FOCUS_INSTRUMENTS)
                    return
        except:
            pass


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
    from file_io import load_project, load_instrument_samples
    
    # Close the recovery dialog
    if dpg.does_item_exist("autosave_dialog"):
        dpg.delete_item("autosave_dialog")
    
    if not os.path.exists(path):
        show_error("File Not Found", f"Autosave no longer exists:\n{path}")
        return
    
    # Autosave current work first
    if state.song.modified and G.autosave_enabled:
        G.do_autosave()
    
    # Load the autosave
    song, err = load_project(path)
    if err:
        show_error("Load Error", err)
        return
    
    state.song = song
    load_instrument_samples(state.song)
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
    path = user_data
    if not os.path.exists(path):
        show_error("File Not Found", f"File no longer exists:\n{path}")
        return
    if state.song.modified and G.autosave_enabled:
        G.do_autosave()
    from file_io import load_project, load_instrument_samples
    song, err = load_project(path)
    if err:
        show_error("Load Error", err)
        return
    state.song = song
    load_instrument_samples(state.song)
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
        fixed_height = G.TOP_PANEL_HEIGHT + G.INPUT_ROW_HEIGHT + G.EDITOR_HEADER_HEIGHT + 60
        available = vp_height - fixed_height
        rows = available // ROW_HEIGHT - 2
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
    
    # Optimize mode: "Speed" -> True, "Size" -> False
    try:
        opt_value = dpg.get_value("vq_optimize_combo")
        state.vq.settings.optimize_speed = (opt_value == "Speed")
    except:
        pass
    
    # Invalidate conversion
    invalidate_vq_conversion()


def on_vq_use_converted_change(sender, app_data):
    """Toggle between original and converted sample playback."""
    state.vq.use_converted = app_data
    
    # Reload samples based on new setting
    if state.vq.converted and state.vq.result and state.vq.use_converted:
        # Load converted WAVs
        _load_converted_samples()
    else:
        # Reload original samples from their source paths
        _reload_original_samples()
    
    state.audio.set_song(state.song)
    
    # Refresh instruments to update colors (green when using converted, gray otherwise)
    R.refresh_instruments()
    
    G.show_status("Using converted samples" if state.vq.use_converted else "Using original samples")


def _reload_original_samples():
    """Reload original samples from their working copy paths.
    
    Uses sample_path (the working copy in .tmp/samples/) rather than
    original_sample_path (the external file which might not exist).
    """
    import logging
    logger = logging.getLogger(__name__)
    from file_io import load_sample
    
    logger.debug(f"Reloading {len(state.song.instruments)} original samples")
    for inst in state.song.instruments:
        # Use sample_path (working copy) - this should always exist
        # sample_path points to .tmp/samples/ where the original was extracted/imported
        working_path = inst.sample_path
        if working_path and os.path.exists(working_path):
            logger.debug(f"  Inst {inst.name}: {working_path}")
            # Load without updating paths (they're already correct)
            ok, msg = load_sample(inst, working_path, is_converted=False, update_path=False)
            if not ok:
                G.show_status(f"Error reloading {inst.name}: {msg}")
            else:
                logger.debug(f"    Loaded OK, {len(inst.sample_data) if inst.sample_data is not None else 0} samples")
        else:
            # Fallback to original_sample_path if working copy not available
            original_path = inst.original_sample_path
            if original_path and os.path.exists(original_path):
                logger.debug(f"  Inst {inst.name}: fallback to {original_path}")
                # Don't update paths - just load the sample data
                ok, msg = load_sample(inst, original_path, is_converted=True, update_path=False)
                if not ok:
                    G.show_status(f"Error reloading {inst.name}: {msg}")
            else:
                logger.warning(f"  Inst {inst.name}: No valid sample path (working={working_path}, original={original_path})")


def _load_converted_samples():
    """Load converted WAV files into instruments.
    
    Note: Uses update_path=False to preserve sample_path pointing to original.
    This allows toggling back to original samples later.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not state.vq.result or not state.vq.result.converted_wavs:
        logger.warning("_load_converted_samples: No result or no converted_wavs")
        return
    
    from file_io import load_sample
    
    logger.debug(f"Loading {len(state.vq.result.converted_wavs)} converted WAVs")
    for i, inst in enumerate(state.song.instruments):
        if i < len(state.vq.result.converted_wavs):
            wav_path = state.vq.result.converted_wavs[i]
            logger.debug(f"  Inst {i} ({inst.name}): {wav_path}")
            if os.path.exists(wav_path):
                # Load converted sample data WITHOUT updating sample_path
                # This preserves sample_path pointing to the original working sample
                ok, msg = load_sample(inst, wav_path, is_converted=True, update_path=False)
                if not ok:
                    G.show_status(f"Error loading {os.path.basename(wav_path)}: {msg}")
                else:
                    logger.debug(f"    Loaded OK, {len(inst.sample_data) if inst.sample_data is not None else 0} samples")
            else:
                logger.warning(f"    File not found: {wav_path}")


def invalidate_vq_conversion():
    """Mark VQ conversion as invalid.
    
    SYNCHRONIZATION: When VQ conversion is invalidated, BUILD must also be disabled.
    This happens when:
    - Instruments are added, removed, or replaced
    - User explicitly runs CONVERT again
    - New project is loaded
    
    BUILD button is only enabled (green) when:
    - state.vq.converted == True (CONVERT was successful)
    - state.song.instruments is not empty
    """
    state.vq.invalidate()
    
    # Update CONVERT UI
    if dpg.does_item_exist("vq_size_label"):
        dpg.set_value("vq_size_label", "")
    
    if dpg.does_item_exist("vq_use_converted_cb"):
        dpg.set_value("vq_use_converted_cb", False)
        dpg.configure_item("vq_use_converted_cb", enabled=False)
    
    state.vq.use_converted = False
    
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
    
    # Also update ANALYZE button state
    update_analyze_button_state()


def update_analyze_button_state():
    """Update ANALYZE button to green when CONVERT is done."""
    if not dpg.does_item_exist("analyze_btn"):
        return
    
    if state.vq.converted:
        # Converted - green button (ready to analyze)
        dpg.bind_item_theme("analyze_btn", "theme_btn_green")
    else:
        # Not converted - normal/disabled
        dpg.bind_item_theme("analyze_btn", "theme_btn_disabled")


def on_vq_convert_click(sender, app_data):
    """Start VQ conversion."""
    from vq_convert import VQConverter
    from ui_dialogs import show_error
    import logging
    logger = logging.getLogger(__name__)
    
    logger.debug(f"on_vq_convert_click: {len(state.song.instruments)} instruments")
    
    # Check if there are instruments
    if not state.song.instruments:
        show_error("No Instruments", "Add instruments before converting.")
        return
    
    # Check all instruments have files - use sample_path (working copy in .tmp)
    # NOT original_sample_path which may point to external files that no longer exist
    input_files = []
    for i, inst in enumerate(state.song.instruments):
        # Use sample_path - the working copy extracted from project archive
        working_path = inst.sample_path
        logger.debug(f"  Inst {i}: name='{inst.name}', sample_path='{working_path}'")
        if working_path and os.path.exists(working_path):
            input_files.append(working_path)
        else:
            show_error("Missing File", 
                       f"Instrument '{inst.name}' has no valid sample file.\n\n"
                       f"Path: {working_path or '(empty)'}\n\n"
                       f"Please reload the instrument.")
            return
    
    logger.debug(f"Starting conversion with {len(input_files)} files")
    
    # Show conversion window
    show_vq_conversion_window(input_files)


# Global reference to converter for polling
_vq_converter = None


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
    
    # Start conversion
    _vq_converter = VQConverter(state.vq)
    _vq_converter.convert(input_files)


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
                dpg.set_value("vq_size_label", f"Size: {format_size(result.total_size)}")
            
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
            G.show_status(f"Conversion complete: {format_size(result.total_size)} - Using converted samples")
        else:
            G.show_status(f"Conversion failed: {result.error_message}")


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
                warning_lines.append(f"• {issue.location}: {issue.message}")
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
        dpg.add_text(f"✗ Cannot build: {validation.error_count} error(s) found", color=(255, 100, 100))
        
        if validation.warning_count > 0:
            dpg.add_text(f"⚠ {validation.warning_count} warning(s)", color=(255, 200, 100))
        
        dpg.add_separator()
        dpg.add_spacer(height=5)
        
        dpg.add_text("Please fix the following issues:", color=(200, 200, 200))
        dpg.add_spacer(height=5)
        
        # Issues list
        with dpg.child_window(height=-50, border=True):
            for issue in validation.issues:
                if issue.severity == "error":
                    color = (255, 100, 100)
                    icon = "❌"
                else:
                    color = (255, 200, 100)
                    icon = "⚠️"
                
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
