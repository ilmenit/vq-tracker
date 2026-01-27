"""Atari Sample Tracker - Main UI (v3.1)"""
import dearpygui.dearpygui as dpg
import os
from constants import (APP_NAME, APP_VERSION, WIN_WIDTH, WIN_HEIGHT, ROW_HEIGHT,
                       MAX_CHANNELS, MAX_OCTAVES, MAX_VOLUME, MAX_ROWS, MAX_INSTRUMENTS,
                       MAX_NOTES, PAL_HZ, NTSC_HZ, note_to_str, FOCUS_SONG, FOCUS_PATTERN,
                       FOCUS_INSTRUMENTS, FOCUS_INFO, FOCUS_EDITOR, COL_CH,
                       COL_NOTE, COL_INST, COL_VOL, NOTE_NAMES, COL_INACTIVE)
from state import state
from ui_theme import create_themes, get_cell_theme
from ui_dialogs import (show_file_dialog, show_confirm, show_error,
                        show_rename_dialog, show_about, show_shortcuts)
import operations as ops
from keyboard import handle_key

# =============================================================================
# GLOBALS
# =============================================================================
_visible_rows = 16
_play_row = -1
_play_songline = -1
_last_refresh_hash = None  # For optimizing grid refresh

# =============================================================================
# UI HELPERS
# =============================================================================

def fmt(val: int, width: int = 2) -> str:
    """Format number in hex or decimal."""
    return f"{val:0{width}X}" if state.hex_mode else f"{val:0{width}d}"

def set_focus(area: int):
    """Set focus to area and update visual indicators."""
    state.set_focus(area)
    panels = [
        ("song_panel", FOCUS_SONG),
        ("pattern_panel", FOCUS_PATTERN),
        ("inst_panel", FOCUS_INSTRUMENTS),
        ("info_panel", FOCUS_INFO),
        ("editor_panel", FOCUS_EDITOR),
    ]
    for tag, focus_id in panels:
        if dpg.does_item_exist(tag):
            theme = "theme_panel_focused" if area == focus_id else "theme_panel_normal"
            dpg.bind_item_theme(tag, theme)

def on_input_focus(sender, data):
    """Called when text input gains focus."""
    state.set_input_active(True)

def on_input_blur(sender, data):
    """Called when text input loses focus."""
    state.set_input_active(False)

def get_grid_hash():
    """Get hash of current grid state for change detection."""
    return (state.songline, state.row, state.channel, state.column, 
            _play_row, _play_songline, state.hex_mode,
            tuple(state.get_patterns()),
            tuple(state.audio.is_channel_enabled(i) for i in range(MAX_CHANNELS)))

# =============================================================================
# REFRESH FUNCTIONS
# =============================================================================

def refresh_all():
    """Refresh entire UI."""
    refresh_songlist()
    refresh_pattern_info()
    refresh_instruments()
    refresh_editor()
    update_controls()

def refresh_songlist():
    """Refresh song list with clickable pattern combos."""
    if not dpg.does_item_exist("songlist"):
        return
    
    dpg.delete_item("songlist", children_only=True)
    
    # Header row
    with dpg.group(horizontal=True, parent="songlist"):
        dpg.add_text("   ", color=(100,100,100))  # Spacer for marker
        dpg.add_text("CH1", color=COL_CH[0])
        dpg.add_spacer(width=10)
        dpg.add_text("CH2", color=COL_CH[1])
        dpg.add_spacer(width=10)
        dpg.add_text("CH3", color=COL_CH[2])
    
    for i, sl in enumerate(state.song.songlines):
        is_current = (i == state.songline)
        marker = ">" if is_current else " "
        
        with dpg.group(horizontal=True, parent="songlist"):
            # Row number and marker
            btn = dpg.add_button(label=f"{marker}{fmt(i)}", width=40, height=22,
                                 callback=select_songline_click, user_data=i)
            if is_current:
                dpg.bind_item_theme(btn, "theme_cell_cursor")
            with dpg.tooltip(btn):
                dpg.add_text("Click to select this song row")
            
            # Pattern combos for each channel
            for ch in range(MAX_CHANNELS):
                ptn_items = [fmt(p) for p in range(len(state.song.patterns))] + ["ADD"]
                combo = dpg.add_combo(
                    items=ptn_items, default_value=fmt(sl.patterns[ch]),
                    width=50, callback=on_songline_pattern_change,
                    user_data=(i, ch)
                )
                with dpg.tooltip(combo):
                    dpg.add_text(f"Pattern for CH{ch+1}. Select ADD to create new pattern.")

def refresh_pattern_info():
    """Refresh pattern section - now shows selected pattern editor."""
    # Update pattern selector combo
    if dpg.does_item_exist("ptn_select_combo"):
        ptn_items = [f"{fmt(i)}" for i in range(len(state.song.patterns))] + ["ADD"]
        dpg.configure_item("ptn_select_combo", items=ptn_items)
        dpg.set_value("ptn_select_combo", fmt(state.selected_pattern))
    
    # Update length
    if dpg.does_item_exist("ptn_len_input"):
        ptn = state.song.get_pattern(state.selected_pattern)
        dpg.set_value("ptn_len_input", ptn.length)

def refresh_instruments():
    """Refresh instrument list."""
    if not dpg.does_item_exist("instlist"):
        return
    
    dpg.delete_item("instlist", children_only=True)
    
    for i, inst in enumerate(state.song.instruments):
        is_current = (i == state.instrument)
        marker = ">" if is_current else " "
        loaded = "*" if inst.is_loaded() else " "
        name = inst.name[:12]
        label = f"{marker}{fmt(i)}{loaded}{name}"
        
        btn = dpg.add_button(
            label=label, parent="instlist", width=-1, height=22,
            callback=select_inst_click, user_data=i
        )
        if is_current:
            dpg.bind_item_theme(btn, "theme_cell_cursor")

def refresh_editor():
    """Refresh pattern editor grid with optimized updates."""
    global _visible_rows, _last_refresh_hash
    
    if not dpg.does_item_exist("editor_grid"):
        return
    
    # Check if we actually need to refresh
    current_hash = get_grid_hash()
    
    # Delete and recreate table
    parent = dpg.get_item_parent("editor_grid")
    dpg.delete_item("editor_grid")
    
    ptns = state.get_patterns()
    patterns = [state.song.get_pattern(p) for p in ptns]
    max_len = state.song.max_pattern_length(state.songline)
    
    # Calculate visible range (center cursor)
    half = _visible_rows // 2
    start_row = max(0, state.row - half)
    if start_row + _visible_rows > max_len:
        start_row = max(0, max_len - _visible_rows)
    end_row = min(start_row + _visible_rows, max_len)
    
    # Create new table
    with dpg.table(tag="editor_grid", parent=parent, header_row=False,
                   borders_innerH=True, borders_innerV=True,
                   resizable=False, policy=dpg.mvTable_SizingStretchProp):
        # Add columns
        dpg.add_table_column(label="Row", width_fixed=True, init_width_or_weight=50)
        for ch in range(MAX_CHANNELS):
            dpg.add_table_column(label=f"CH{ch+1}")
        
        # Header row with pattern combos
        with dpg.table_row():
            dpg.add_text("Row")
            for ch in range(MAX_CHANNELS):
                enabled = state.audio.is_channel_enabled(ch)
                with dpg.group(horizontal=True):
                    # Channel checkbox
                    cb = dpg.add_checkbox(
                        label="", default_value=enabled,
                        callback=on_channel_toggle, user_data=ch
                    )
                    with dpg.tooltip(cb):
                        dpg.add_text(f"Enable/disable CH{ch+1}")
                    
                    # Pattern combo
                    ptn_items = [fmt(p) for p in range(len(state.song.patterns))] + ["ADD"]
                    combo = dpg.add_combo(
                        items=ptn_items, default_value=fmt(ptns[ch]),
                        width=60, callback=on_editor_pattern_change, user_data=ch
                    )
                    col = COL_CH[ch] if enabled else COL_INACTIVE
                    with dpg.tooltip(combo):
                        dpg.add_text(f"CH{ch+1} pattern. Select ADD to create new.")
        
        # Data rows
        for row_idx in range(start_row, end_row):
            is_cursor_row = (row_idx == state.row)
            is_playing = (row_idx == _play_row and state.songline == _play_songline)
            
            with dpg.table_row():
                # Row number
                row_label = fmt(row_idx)
                row_text = dpg.add_text(row_label)
                if is_playing:
                    dpg.bind_item_theme(row_text, "theme_text_green")
                elif is_cursor_row:
                    dpg.bind_item_theme(row_text, "theme_text_accent")
                
                # Channel cells
                for ch in range(MAX_CHANNELS):
                    ptn = patterns[ch]
                    ptn_len = ptn.length
                    ch_enabled = state.audio.is_channel_enabled(ch)
                    
                    # Check if we're in repeat zone
                    is_repeat = row_idx >= ptn_len
                    actual_row = row_idx % ptn_len if ptn_len > 0 else 0
                    r = ptn.get_row(actual_row)
                    
                    # Determine cell state
                    is_cursor = is_cursor_row and ch == state.channel
                    is_selected = state.selection.contains(row_idx, ch)
                    has_note = r.note > 0
                    
                    # Build cell with individual clickable parts
                    with dpg.group(horizontal=True):
                        # Note field
                        note_str = note_to_str(r.note)
                        is_note_cursor = is_cursor and state.column == COL_NOTE
                        note_theme = "theme_cell_cursor" if is_note_cursor else (
                            "theme_cell_inactive" if not ch_enabled else
                            get_cell_theme(False, is_playing, is_selected, is_repeat, has_note, not ch_enabled))
                        
                        if is_repeat and actual_row == 0:
                            note_label = f"~{note_str}"
                        else:
                            note_label = f" {note_str}"
                        
                        note_btn = dpg.add_button(
                            label=note_label, width=45, height=ROW_HEIGHT - 4,
                            callback=cell_click, user_data=(row_idx, ch, COL_NOTE)
                        )
                        dpg.bind_item_theme(note_btn, note_theme)
                        with dpg.tooltip(note_btn):
                            dpg.add_text("Note - Click to edit, use piano keys")
                        
                        # Instrument field  
                        inst_str = fmt(r.instrument) if r.note > 0 else "--"
                        is_inst_cursor = is_cursor and state.column == COL_INST
                        inst_theme = "theme_cell_cursor" if is_inst_cursor else (
                            "theme_cell_inactive" if not ch_enabled else
                            get_cell_theme(False, is_playing, is_selected, is_repeat, has_note, not ch_enabled))
                        
                        inst_btn = dpg.add_button(
                            label=inst_str, width=30, height=ROW_HEIGHT - 4,
                            callback=cell_click, user_data=(row_idx, ch, COL_INST)
                        )
                        dpg.bind_item_theme(inst_btn, inst_theme)
                        with dpg.tooltip(inst_btn):
                            dpg.add_text("Instrument - Click to select from list")
                        
                        # Volume field
                        vol_str = f"{r.volume:X}" if r.note > 0 else "-"
                        is_vol_cursor = is_cursor and state.column == COL_VOL
                        vol_theme = "theme_cell_cursor" if is_vol_cursor else (
                            "theme_cell_inactive" if not ch_enabled else
                            get_cell_theme(False, is_playing, is_selected, is_repeat, has_note, not ch_enabled))
                        
                        vol_btn = dpg.add_button(
                            label=vol_str, width=20, height=ROW_HEIGHT - 4,
                            callback=cell_click, user_data=(row_idx, ch, COL_VOL)
                        )
                        dpg.bind_item_theme(vol_btn, vol_theme)
                        with dpg.tooltip(vol_btn):
                            dpg.add_text("Volume (0-F) - Click to edit")
    
    _last_refresh_hash = current_hash

def update_controls():
    """Update control values."""
    if dpg.does_item_exist("oct_input"):
        dpg.set_value("oct_input", state.octave)
    if dpg.does_item_exist("step_input"):
        dpg.set_value("step_input", state.step)
    if dpg.does_item_exist("speed_input"):
        dpg.set_value("speed_input", state.song.speed)
    if dpg.does_item_exist("ptn_len_input"):
        ptn = state.song.get_pattern(state.selected_pattern)
        dpg.set_value("ptn_len_input", ptn.length)

def update_title():
    """Update window title."""
    mod = "*" if state.song.modified else ""
    name = state.song.title or "Untitled"
    dpg.set_viewport_title(f"{mod}{name} - {APP_NAME}")

def show_status(msg: str):
    """Show status message."""
    if dpg.does_item_exist("status_text"):
        dpg.set_value("status_text", msg)

# =============================================================================
# CLICK HANDLERS
# =============================================================================

def select_songline_click(sender, app_data, user_data):
    """Handle songline click."""
    set_focus(FOCUS_SONG)
    ops.select_songline(user_data)

def select_inst_click(sender, app_data, user_data):
    """Handle instrument click."""
    set_focus(FOCUS_INSTRUMENTS)
    ops.select_instrument(user_data)

def cell_click(sender, app_data, user_data):
    """Handle cell click - now includes column."""
    row, channel, column = user_data
    set_focus(FOCUS_EDITOR)
    state.row = row
    state.channel = channel
    state.column = column
    state.selection.clear()
    
    # Show popup for instrument/volume selection
    if column == COL_INST and state.song.instruments:
        show_instrument_popup(row, channel)
    elif column == COL_VOL:
        show_volume_popup(row, channel)
    elif column == COL_NOTE:
        show_note_popup(row, channel)
    
    refresh_editor()

def show_instrument_popup(row: int, channel: int):
    """Show instrument selection popup."""
    if dpg.does_item_exist("inst_popup"):
        dpg.delete_item("inst_popup")
    
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_inst = ptn.get_row(row).instrument
    
    items = [f"{fmt(i)} - {inst.name}" for i, inst in enumerate(state.song.instruments)]
    if not items:
        return
    
    def on_select(sender, value):
        try:
            idx = int(value.split(" - ")[0], 16 if state.hex_mode else 10)
            ops.set_cell_instrument(row, channel, idx)
        except:
            pass
        dpg.delete_item("inst_popup")
    
    with dpg.window(tag="inst_popup", popup=True, no_title_bar=True, 
                    min_size=(200, 100), max_size=(300, 300)):
        dpg.add_text("Select Instrument:")
        dpg.add_listbox(items=items, default_value=items[min(current_inst, len(items)-1)] if items else "",
                        num_items=min(8, len(items)), callback=on_select, width=-1)

def show_volume_popup(row: int, channel: int):
    """Show volume selection popup."""
    if dpg.does_item_exist("vol_popup"):
        dpg.delete_item("vol_popup")
    
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_vol = ptn.get_row(row).volume
    
    def on_change(sender, value):
        ops.set_cell_volume(row, channel, value)
        dpg.delete_item("vol_popup")
    
    with dpg.window(tag="vol_popup", popup=True, no_title_bar=True, min_size=(150, 60)):
        dpg.add_text("Volume (0-15):")
        dpg.add_slider_int(default_value=current_vol, min_value=0, max_value=MAX_VOLUME,
                           callback=on_change, width=-1)

def show_note_popup(row: int, channel: int):
    """Show note selection popup."""
    if dpg.does_item_exist("note_popup"):
        dpg.delete_item("note_popup")
    
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_note = ptn.get_row(row).note
    
    # Build note list
    notes = ["--- (empty)"] + [note_to_str(n) for n in range(1, MAX_OCTAVES * 12 + 1)]
    current_val = notes[current_note] if current_note < len(notes) else notes[0]
    
    def on_select(sender, value):
        if value == "--- (empty)":
            ops.set_cell_note(row, channel, 0)
        else:
            try:
                idx = notes.index(value)
                ops.set_cell_note(row, channel, idx)
            except:
                pass
        dpg.delete_item("note_popup")
    
    with dpg.window(tag="note_popup", popup=True, no_title_bar=True,
                    min_size=(120, 200), max_size=(150, 400)):
        dpg.add_text("Select Note:")
        dpg.add_listbox(items=notes, default_value=current_val,
                        num_items=12, callback=on_select, width=-1)

# =============================================================================
# CONTROL CALLBACKS
# =============================================================================

def on_octave_change(sender, value):
    ops.set_octave(value)

def on_step_change(sender, value):
    ops.set_step(value)

def on_speed_change(sender, value):
    ops.set_speed(value)

def on_ptn_len_change(sender, value):
    ops.set_pattern_length(value, state.selected_pattern)

def on_pattern_select(sender, value):
    """Handle pattern selection in PATTERN panel."""
    if value == "ADD":
        idx = state.song.add_pattern()
        if idx >= 0:
            state.selected_pattern = idx
            ops.save_undo("Add pattern")
            refresh_pattern_info()
            show_status(f"Added pattern {fmt(idx)}")
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            state.selected_pattern = idx
            refresh_pattern_info()
        except:
            pass

def on_songline_pattern_change(sender, value, user_data):
    """Handle pattern change in songline."""
    sl_idx, ch = user_data
    if value == "ADD":
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[sl_idx].patterns[ch] = idx
            ops.save_undo("Add pattern")
            refresh_all()
            show_status(f"Added pattern {fmt(idx)}")
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            state.song.songlines[sl_idx].patterns[ch] = idx
            state.song.modified = True
            refresh_editor()
        except:
            pass

def on_editor_pattern_change(sender, value, user_data):
    """Handle pattern change in editor header."""
    ch = user_data
    if value == "ADD":
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[state.songline].patterns[ch] = idx
            ops.save_undo("Add pattern")
            refresh_all()
            show_status(f"Added pattern {fmt(idx)}")
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            ops.set_songline_pattern(ch, idx)
        except:
            pass

def on_channel_toggle(sender, value, user_data):
    """Handle channel enable/disable toggle."""
    ch = user_data
    state.audio.set_channel_enabled(ch, value)
    refresh_editor()

def on_system_change(sender, value):
    state.song.system = PAL_HZ if value == "PAL" else NTSC_HZ
    state.audio.set_system(state.song.system)
    state.song.modified = True
    update_title()

def on_hex_toggle(sender, value):
    state.hex_mode = value
    refresh_all()

# =============================================================================
# PLAYBACK CALLBACKS
# =============================================================================

def on_playback_row(songline: int, row: int):
    global _play_row, _play_songline
    _play_row = row
    _play_songline = songline
    if state.follow and state.audio.is_playing():
        if state.songline != songline:
            state.songline = songline
            refresh_songlist()
        state.row = row
    refresh_editor()

def on_playback_stop():
    global _play_row, _play_songline
    _play_row = -1
    _play_songline = -1
    refresh_editor()

# =============================================================================
# WINDOW RESIZE HANDLER
# =============================================================================

def calculate_visible_rows():
    """Calculate visible rows based on editor panel height."""
    global _visible_rows
    if dpg.does_item_exist("editor_panel"):
        height = dpg.get_item_height("editor_panel")
        # Account for header row, padding, and controls
        available = height - 80  # Header + margins
        rows = max(4, available // ROW_HEIGHT)
        if rows != _visible_rows:
            _visible_rows = rows
            refresh_editor()

# =============================================================================
# BUILD UI
# =============================================================================

def build_menu():
    """Build menu bar."""
    with dpg.menu_bar():
        with dpg.menu(label="File"):
            dpg.add_menu_item(label="New", callback=ops.new_song, shortcut="Ctrl+N")
            dpg.add_menu_item(label="Open...", callback=ops.open_song, shortcut="Ctrl+O")
            dpg.add_separator()
            dpg.add_menu_item(label="Save", callback=ops.save_song, shortcut="Ctrl+S")
            dpg.add_menu_item(label="Save As...", callback=ops.save_song_as, shortcut="Ctrl+Shift+S")
            dpg.add_separator()
            with dpg.menu(label="Export"):
                dpg.add_menu_item(label="Binary (.pvg)...", callback=ops.export_binary_file)
                dpg.add_menu_item(label="ASM Files...", callback=ops.export_asm_files)
            dpg.add_separator()
            dpg.add_menu_item(label="Exit", callback=lambda: dpg.stop_dearpygui())
        
        with dpg.menu(label="Edit"):
            dpg.add_menu_item(label="Undo", callback=ops.undo, shortcut="Ctrl+Z")
            dpg.add_menu_item(label="Redo", callback=ops.redo, shortcut="Ctrl+Y")
            dpg.add_separator()
            dpg.add_menu_item(label="Copy Cells", callback=ops.copy_cells, shortcut="Ctrl+C")
            dpg.add_menu_item(label="Cut Cells", callback=ops.cut_cells, shortcut="Ctrl+X")
            dpg.add_menu_item(label="Paste Cells", callback=ops.paste_cells, shortcut="Ctrl+V")
            dpg.add_separator()
            dpg.add_menu_item(label="Clear Pattern", callback=ops.clear_pattern)
        
        with dpg.menu(label="Song"):
            dpg.add_menu_item(label="Add Row", callback=ops.add_songline)
            dpg.add_menu_item(label="Clone Row", callback=ops.clone_songline)
            dpg.add_menu_item(label="Delete Row", callback=on_delete_songline_confirm)
        
        with dpg.menu(label="Pattern"):
            dpg.add_menu_item(label="New Pattern", callback=ops.add_pattern)
            dpg.add_menu_item(label="Clone Pattern", callback=ops.clone_pattern)
            dpg.add_menu_item(label="Delete Pattern", callback=on_delete_pattern_confirm)
            dpg.add_separator()
            dpg.add_menu_item(label="Transpose +1", callback=lambda: ops.transpose(1))
            dpg.add_menu_item(label="Transpose -1", callback=lambda: ops.transpose(-1))
            dpg.add_menu_item(label="Transpose +12", callback=lambda: ops.transpose(12))
            dpg.add_menu_item(label="Transpose -12", callback=lambda: ops.transpose(-12))
        
        with dpg.menu(label="Help"):
            dpg.add_menu_item(label="Keyboard Shortcuts", callback=show_shortcuts, shortcut="F1")
            dpg.add_separator()
            dpg.add_menu_item(label="About", callback=show_about)

def on_delete_songline_confirm():
    """Confirm before deleting songline."""
    show_confirm_centered("Delete Row", "Delete this song row?", ops.delete_songline)

def on_delete_pattern_confirm():
    """Confirm before deleting pattern."""
    ptn_idx = state.selected_pattern
    if state.song.pattern_in_use(ptn_idx):
        show_error("Cannot Delete", "Pattern is in use by song rows")
        return
    show_confirm_centered("Delete Pattern", f"Delete pattern {fmt(ptn_idx)}?", ops.delete_pattern)

def show_confirm_centered(title: str, message: str, callback):
    """Show confirmation dialog centered on window."""
    if dpg.does_item_exist("confirm_dialog"):
        dpg.delete_item("confirm_dialog")
    
    # Calculate center position
    vp_width = dpg.get_viewport_width()
    vp_height = dpg.get_viewport_height()
    dialog_width, dialog_height = 320, 120
    pos_x = (vp_width - dialog_width) // 2
    pos_y = (vp_height - dialog_height) // 2
    
    def on_ok():
        dpg.delete_item("confirm_dialog")
        callback()
    
    def on_cancel():
        dpg.delete_item("confirm_dialog")
    
    with dpg.window(
        tag="confirm_dialog",
        label=title,
        modal=True,
        width=dialog_width,
        height=dialog_height,
        pos=[pos_x, pos_y],
        no_resize=True,
        no_collapse=True
    ):
        dpg.add_text(message)
        dpg.add_spacer(height=15)
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=80, callback=on_ok)
            dpg.add_spacer(width=10)
            dpg.add_button(label="Cancel", width=80, callback=on_cancel)

def build_top_row():
    """Build top row: SONG, PATTERN, INSTRUMENTS."""
    with dpg.group(horizontal=True):
        # === SONG PANEL ===
        with dpg.child_window(tag="song_panel", width=230, height=240, border=True):
            dpg.add_text("SONG")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Song arrangement - each row assigns patterns to channels.\nClick pattern numbers to change, ADD creates new pattern.")
            
            with dpg.child_window(tag="songlist", height=160, border=False):
                pass
            
            with dpg.group(horizontal=True):
                b = dpg.add_button(label="Add", width=55, callback=ops.add_songline)
                with dpg.tooltip(b):
                    dpg.add_text("Add new song row after current")
                
                b = dpg.add_button(label="Clone", width=55, callback=ops.clone_songline)
                with dpg.tooltip(b):
                    dpg.add_text("Duplicate current song row")
                
                b = dpg.add_button(label="Del", width=50, callback=on_delete_songline_confirm)
                with dpg.tooltip(b):
                    dpg.add_text("Delete current song row (with confirmation)")
        
        # === PATTERN PANEL (now pattern editor) ===
        with dpg.child_window(tag="pattern_panel", width=200, height=240, border=True):
            dpg.add_text("PATTERN")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Edit selected pattern properties")
            
            dpg.add_spacer(height=5)
            
            # Pattern selector
            with dpg.group(horizontal=True):
                dpg.add_text("Pattern:")
                ptn_items = [fmt(i) for i in range(len(state.song.patterns))] + ["ADD"]
                combo = dpg.add_combo(
                    tag="ptn_select_combo",
                    items=ptn_items, default_value=fmt(0),
                    width=70, callback=on_pattern_select
                )
                with dpg.tooltip(combo):
                    dpg.add_text("Select pattern to edit. ADD creates new pattern.")
            
            dpg.add_spacer(height=10)
            
            # Pattern length
            with dpg.group(horizontal=True):
                dpg.add_text("Length: ")
                inp = dpg.add_input_int(
                    tag="ptn_len_input", default_value=64,
                    min_value=1, max_value=MAX_ROWS, min_clamped=True, max_clamped=True,
                    width=80, callback=on_ptn_len_change, on_enter=True
                )
                with dpg.tooltip(inp):
                    dpg.add_text("Pattern length in rows (1-256)")
            
            dpg.add_spacer(height=10)
            
            with dpg.group(horizontal=True):
                b = dpg.add_button(label="Add", width=50, callback=ops.add_pattern)
                with dpg.tooltip(b):
                    dpg.add_text("Create new empty pattern")
                
                b = dpg.add_button(label="Clone", width=55, callback=ops.clone_pattern)
                with dpg.tooltip(b):
                    dpg.add_text("Duplicate selected pattern")
                
                b = dpg.add_button(label="Del", width=45, callback=on_delete_pattern_confirm)
                with dpg.tooltip(b):
                    dpg.add_text("Delete pattern (with confirmation, only if unused)")
        
        # === INSTRUMENTS PANEL ===
        with dpg.child_window(tag="inst_panel", width=200, height=240, border=True):
            dpg.add_text("INSTRUMENTS")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Sample instruments - * indicates loaded sample")
            
            with dpg.child_window(tag="instlist", height=140, border=False):
                pass
            
            with dpg.group(horizontal=True):
                b = dpg.add_button(label="+ Sample", width=80, callback=ops.add_sample)
                with dpg.tooltip(b):
                    dpg.add_text("Load WAV sample(s) - multi-select supported")
                
                b = dpg.add_button(label="+ Folder", width=80, callback=ops.add_folder)
                with dpg.tooltip(b):
                    dpg.add_text("Load all WAV files from folder AND subfolders")
            
            with dpg.group(horizontal=True):
                b = dpg.add_button(label="Rename", width=65, callback=ops.rename_instrument)
                with dpg.tooltip(b):
                    dpg.add_text("Rename current instrument")
                
                b = dpg.add_button(label="Del", width=50, callback=ops.remove_instrument)
                with dpg.tooltip(b):
                    dpg.add_text("Remove current instrument")
        
        # === SETTINGS PANEL ===
        with dpg.child_window(width=-1, height=240, border=True):
            dpg.add_text("SETTINGS")
            
            dpg.add_spacer(height=5)
            
            # System selector
            with dpg.group(horizontal=True):
                dpg.add_text("System:")
                combo = dpg.add_combo(
                    items=["PAL", "NTSC"], default_value="PAL",
                    width=80, callback=on_system_change
                )
                with dpg.tooltip(combo):
                    dpg.add_text("PAL=50Hz (Europe), NTSC=60Hz (USA) timing")
            
            dpg.add_spacer(height=5)
            cb = dpg.add_checkbox(label="Hex mode", default_value=True, callback=on_hex_toggle)
            with dpg.tooltip(cb):
                dpg.add_text("Display numbers in hexadecimal")
            
            dpg.add_spacer(height=10)
            dpg.add_separator()
            dpg.add_spacer(height=5)
            
            # Input settings
            dpg.add_text("INPUT", color=(150,150,160))
            dpg.add_spacer(height=3)
            
            with dpg.group(horizontal=True):
                dpg.add_text("Octave:")
                inp = dpg.add_input_int(
                    tag="oct_input", default_value=state.octave,
                    min_value=1, max_value=MAX_OCTAVES, min_clamped=True, max_clamped=True,
                    width=70, callback=on_octave_change, on_enter=True
                )
                with dpg.tooltip(inp):
                    dpg.add_text("Base octave for note entry (1-3)")
                with dpg.item_handler_registry() as handler:
                    dpg.add_item_activated_handler(callback=on_input_focus)
                    dpg.add_item_deactivated_handler(callback=on_input_blur)
                dpg.bind_item_handler_registry(inp, handler)
            
            with dpg.group(horizontal=True):
                dpg.add_text("Step:   ")
                inp = dpg.add_input_int(
                    tag="step_input", default_value=state.step,
                    min_value=0, max_value=16, min_clamped=True, max_clamped=True,
                    width=70, callback=on_step_change, on_enter=True
                )
                with dpg.tooltip(inp):
                    dpg.add_text("Cursor advance after note entry (0-16)")
                with dpg.item_handler_registry() as handler:
                    dpg.add_item_activated_handler(callback=on_input_focus)
                    dpg.add_item_deactivated_handler(callback=on_input_blur)
                dpg.bind_item_handler_registry(inp, handler)

def build_middle_row():
    """Build middle row: SONG INFO."""
    with dpg.child_window(tag="info_panel", height=80, border=True):
        dpg.add_text("SONG INFO")
        
        dpg.add_spacer(height=3)
        
        with dpg.group(horizontal=True):
            dpg.add_text("Title:")
            inp = dpg.add_input_text(
                tag="title_input", default_value=state.song.title,
                width=220, callback=lambda s, v: setattr(state.song, 'title', v)
            )
            with dpg.tooltip(inp):
                dpg.add_text("Song title")
            with dpg.item_handler_registry() as handler:
                dpg.add_item_activated_handler(callback=on_input_focus)
                dpg.add_item_deactivated_handler(callback=on_input_blur)
            dpg.bind_item_handler_registry(inp, handler)
            
            dpg.add_spacer(width=30)
            
            dpg.add_text("Author:")
            inp = dpg.add_input_text(
                tag="author_input", default_value=state.song.author,
                width=180, callback=lambda s, v: setattr(state.song, 'author', v)
            )
            with dpg.tooltip(inp):
                dpg.add_text("Composer name")
            with dpg.item_handler_registry() as handler:
                dpg.add_item_activated_handler(callback=on_input_focus)
                dpg.add_item_deactivated_handler(callback=on_input_blur)
            dpg.bind_item_handler_registry(inp, handler)
            
            dpg.add_spacer(width=30)
            
            dpg.add_text("Speed:")
            inp = dpg.add_input_int(
                tag="speed_input", default_value=state.song.speed,
                min_value=1, max_value=255, min_clamped=True, max_clamped=True,
                width=70, callback=on_speed_change, on_enter=True
            )
            with dpg.tooltip(inp):
                dpg.add_text("Ticks per row (lower = faster)")
            with dpg.item_handler_registry() as handler:
                dpg.add_item_activated_handler(callback=on_input_focus)
                dpg.add_item_deactivated_handler(callback=on_input_blur)
            dpg.bind_item_handler_registry(inp, handler)

def build_editor():
    """Build pattern editor."""
    with dpg.child_window(tag="editor_panel", border=True):
        dpg.add_text("PATTERN EDITOR")
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text("Click on Note/Inst/Vol to edit. ~ marks pattern repeat.\nUse checkbox to enable/disable channel, combo to change pattern.")
        
        # Create initial table (will be recreated on refresh)
        with dpg.table(tag="editor_grid", header_row=False,
                       borders_innerH=True, borders_innerV=True,
                       resizable=False, policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label="Row", width_fixed=True, init_width_or_weight=50)
            for ch in range(MAX_CHANNELS):
                dpg.add_table_column(label=f"CH{ch+1}")

def build_status_bar():
    """Build status bar."""
    with dpg.group(horizontal=True):
        dpg.add_text(tag="status_text", default_value="Ready")
        dpg.add_spacer(width=30)
        
        b = dpg.add_button(label="[>] Play", width=80, callback=ops.play_stop)
        with dpg.tooltip(b):
            dpg.add_text("Play/Stop (Space)")
        
        b = dpg.add_button(label="[>>] Song", width=80, callback=ops.play_song_start)
        with dpg.tooltip(b):
            dpg.add_text("Play song from start (F6)")
        
        b = dpg.add_button(label="[X] Stop", width=80, callback=ops.stop_playback)
        with dpg.tooltip(b):
            dpg.add_text("Stop playback (F8)")

def build_ui():
    """Build complete UI."""
    with dpg.window(tag="main_window"):
        build_menu()
        dpg.add_spacer(height=8)
        build_top_row()
        dpg.add_spacer(height=8)
        build_middle_row()
        dpg.add_spacer(height=8)
        build_editor()
        dpg.add_spacer(height=8)
        build_status_bar()

# =============================================================================
# MAIN
# =============================================================================

def setup_operations_callbacks():
    """Wire up operations module callbacks."""
    ops.refresh_all = refresh_all
    ops.refresh_editor = refresh_editor
    ops.refresh_songlist = refresh_songlist
    ops.refresh_instruments = refresh_instruments
    ops.refresh_pattern_combo = refresh_pattern_info
    ops.update_controls = update_controls
    ops.show_status = show_status
    ops.update_title = update_title
    ops.show_error = show_error
    ops.show_confirm = show_confirm
    ops.show_file_dialog = show_file_dialog
    ops.show_rename_dialog = show_rename_dialog

def main():
    """Main entry point."""
    dpg.create_context()
    dpg.create_viewport(title=APP_NAME, width=WIN_WIDTH, height=WIN_HEIGHT)
    
    # Setup larger font
    with dpg.font_registry():
        default_font = None
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
            "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
            "C:/Windows/Fonts/consola.ttf",
            "/System/Library/Fonts/Monaco.ttf",
        ]
        for font_path in font_paths:
            try:
                if os.path.exists(font_path):
                    default_font = dpg.add_font(font_path, 18)
                    break
            except:
                pass
        
        if default_font:
            dpg.bind_font(default_font)
    
    create_themes()
    build_ui()
    setup_operations_callbacks()
    
    state.audio.on_row = on_playback_row
    state.audio.on_stop = on_playback_stop
    
    with dpg.handler_registry():
        dpg.add_key_press_handler(callback=handle_key)
    
    state.audio.set_song(state.song)
    state.audio.start()
    refresh_all()
    update_title()
    set_focus(FOCUS_EDITOR)
    
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    
    while dpg.is_dearpygui_running():
        state.audio.process_callbacks()
        calculate_visible_rows()
        dpg.render_dearpygui_frame()
    
    state.audio.stop()
    dpg.destroy_context()

if __name__ == "__main__":
    main()
