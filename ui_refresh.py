"""Atari Sample Tracker - UI Refresh Functions"""
import dearpygui.dearpygui as dpg
from constants import (MAX_CHANNELS, MAX_VOLUME, note_to_str, FOCUS_SONG,
                       COL_NOTE, COL_INST, COL_VOL)
from state import state
from ui_theme import get_cell_theme
import ui_globals as G

# Callbacks set by main module to avoid circular imports
_preview_callback = None
_select_callback = None


def set_instrument_callbacks(preview_cb, select_cb):
    """Set callbacks for instrument list buttons."""
    global _preview_callback, _select_callback
    _preview_callback = preview_cb
    _select_callback = select_cb


def refresh_all():
    """Refresh all UI components."""
    refresh_all_pattern_combos()
    refresh_all_instrument_combos()
    refresh_song_editor()
    refresh_pattern_info()
    refresh_instruments()
    refresh_editor()
    update_controls()
    
    # Update BUILD button state (depends on VQ conversion and instruments)
    # Import here to avoid circular import
    try:
        from ui_callbacks import update_build_button_state
        update_build_button_state()
    except ImportError:
        pass


def refresh_all_pattern_combos():
    """Update ALL pattern combo lists throughout the UI."""
    ptn_items = [G.fmt(i) for i in range(len(state.song.patterns))] + ["+"]
    
    if dpg.does_item_exist("ptn_select_combo"):
        dpg.configure_item("ptn_select_combo", items=ptn_items)
        if state.selected_pattern < len(state.song.patterns):
            dpg.set_value("ptn_select_combo", G.fmt(state.selected_pattern))
    
    for ch in range(MAX_CHANNELS):
        combo_tag = f"ch_ptn_combo_{ch}"
        if dpg.does_item_exist(combo_tag):
            dpg.configure_item(combo_tag, items=ptn_items)
            ptns = state.get_patterns()
            if ch < len(ptns):
                dpg.set_value(combo_tag, G.fmt(ptns[ch]))


def refresh_all_instrument_combos():
    """Update ALL instrument combo/lists throughout the UI."""
    items = [f"{G.fmt(i)} - {inst.name[:12]}" for i, inst in enumerate(state.song.instruments)]
    if not items:
        items = ["(none)"]
    
    if dpg.does_item_exist("input_inst_combo"):
        dpg.configure_item("input_inst_combo", items=items)
        if state.song.instruments and state.instrument < len(state.song.instruments):
            dpg.set_value("input_inst_combo", items[state.instrument])
        elif items:
            dpg.set_value("input_inst_combo", items[0])
    
    if dpg.does_item_exist("input_vol_combo"):
        vol_items = [G.fmt_vol(v) for v in range(MAX_VOLUME + 1)]
        dpg.configure_item("input_vol_combo", items=vol_items)
        dpg.set_value("input_vol_combo", G.fmt_vol(state.volume))


def refresh_song_editor():
    """Refresh the song editor grid (5-row scrolling view)."""
    total_songlines = len(state.song.songlines)
    
    half = G.SONG_VISIBLE_ROWS // 2
    start_row = max(0, state.song_cursor_row - half)
    if start_row + G.SONG_VISIBLE_ROWS > total_songlines:
        start_row = max(0, total_songlines - G.SONG_VISIBLE_ROWS)
    
    for vis_row in range(G.SONG_VISIBLE_ROWS):
        sl_idx = start_row + vis_row
        is_cursor_row = (sl_idx == state.song_cursor_row)
        is_playing = (sl_idx == G.play_songline and state.audio.is_playing())
        has_data = sl_idx < total_songlines
        
        row_tag = f"song_row_num_{vis_row}"
        if dpg.does_item_exist(row_tag):
            if has_data:
                dpg.configure_item(row_tag, label=G.fmt(sl_idx))
                if is_playing:
                    theme = "theme_song_row_playing"
                elif is_cursor_row:
                    theme = "theme_song_row_cursor"
                else:
                    theme = "theme_song_row_normal"
            else:
                dpg.configure_item(row_tag, label="--")
                theme = "theme_song_row_empty"
            dpg.bind_item_theme(row_tag, theme)
        
        for ch in range(MAX_CHANNELS):
            cell_tag = f"song_cell_{vis_row}_{ch}"
            if dpg.does_item_exist(cell_tag):
                if has_data:
                    sl = state.song.songlines[sl_idx]
                    ptn_val = sl.patterns[ch]
                    dpg.configure_item(cell_tag, label=G.fmt(ptn_val))
                    
                    is_cursor = is_cursor_row and ch == state.song_cursor_col and state.focus == FOCUS_SONG
                    if is_cursor:
                        theme = "theme_cell_cursor"
                    elif is_playing:
                        theme = "theme_cell_playing"
                    elif is_cursor_row:
                        theme = "theme_cell_current_row"
                    else:
                        theme = "theme_cell_empty"
                    dpg.bind_item_theme(cell_tag, theme)
                else:
                    dpg.configure_item(cell_tag, label="--")
                    dpg.bind_item_theme(cell_tag, "theme_cell_inactive")
        
        # SPD column
        spd_tag = f"song_spd_{vis_row}"
        if dpg.does_item_exist(spd_tag):
            if has_data:
                sl = state.song.songlines[sl_idx]
                dpg.configure_item(spd_tag, label=G.fmt(sl.speed))
                
                # SPD column is index 3 (after C1=0, C2=1, C3=2)
                is_cursor = is_cursor_row and state.song_cursor_col == 3 and state.focus == FOCUS_SONG
                if is_cursor:
                    theme = "theme_cell_cursor"
                elif is_playing:
                    theme = "theme_cell_playing"
                elif is_cursor_row:
                    theme = "theme_cell_current_row"
                else:
                    theme = "theme_cell_empty"
                dpg.bind_item_theme(spd_tag, theme)
            else:
                dpg.configure_item(spd_tag, label="--")
                dpg.bind_item_theme(spd_tag, "theme_cell_inactive")


def refresh_pattern_info():
    """Update pattern length display - respects hex/decimal mode."""
    if dpg.does_item_exist("ptn_len_input"):
        ptn = state.song.get_pattern(state.selected_pattern)
        # Format as hex or decimal based on mode
        if state.hex_mode:
            dpg.set_value("ptn_len_input", f"{ptn.length:02X}")
        else:
            dpg.set_value("ptn_len_input", str(ptn.length))


def refresh_instruments():
    """Refresh instruments list and all instrument combos."""
    if not dpg.does_item_exist("instlist"):
        return
    dpg.delete_item("instlist", children_only=True)
    
    from ui_theme import get_inst_theme
    # Green background when user is USING converted samples, not just when converted
    is_converted = state.vq.use_converted
    
    if not state.song.instruments:
        # Show help message when no instruments loaded
        with dpg.group(parent="instlist"):
            dpg.add_spacer(height=10)
            dpg.add_text("No instruments loaded.", color=(180, 180, 100))
            dpg.add_spacer(height=5)
            dpg.add_text("Load samples using buttons below:", color=(140, 140, 140))
            dpg.add_text("  [Add] - Load individual WAV files", color=(120, 120, 120))
            dpg.add_text("  [Folder] - Load all WAVs from folder", color=(120, 120, 120))
            dpg.add_spacer(height=10)
    else:
        for i, inst in enumerate(state.song.instruments):
            is_current = (i == state.instrument)
            theme = get_inst_theme(is_current, is_converted)
            
            with dpg.group(horizontal=True, parent="instlist"):
                dpg.add_text(f"{G.fmt(i)}", color=(100,100,110))
                dpg.add_spacer(width=3)
                if _preview_callback:
                    play_btn = dpg.add_button(label=">", width=22, height=20,
                                              callback=_preview_callback, user_data=i)
                    with dpg.tooltip(play_btn):
                        dpg.add_text("Preview sample")
                dpg.add_spacer(width=3)
                name = inst.name[:24] if inst.name else "(unnamed)"
                if _select_callback:
                    btn = dpg.add_button(label=name, width=-1, height=20,
                                         callback=_select_callback, user_data=i)
                    with dpg.tooltip(btn):
                        dpg.add_text("Click to select as current instrument")
                    dpg.bind_item_theme(btn, theme)
    
    # Update VQ UI elements
    _update_vq_ui()
    
    refresh_all_instrument_combos()


def _update_vq_ui():
    """Update VQ-related UI elements based on state."""
    from vq_convert import format_size
    
    # Update size label
    if dpg.does_item_exist("vq_size_label"):
        if state.vq.converted and state.vq.result:
            dpg.set_value("vq_size_label", f"Size: {format_size(state.vq.result.total_size)}")
        else:
            dpg.set_value("vq_size_label", "")
    
    # Update use converted checkbox
    if dpg.does_item_exist("vq_use_converted_cb"):
        dpg.configure_item("vq_use_converted_cb", enabled=state.vq.converted)
        if not state.vq.converted:
            dpg.set_value("vq_use_converted_cb", False)
    
    # Update convert button theme
    if dpg.does_item_exist("vq_convert_btn"):
        if dpg.does_item_exist("theme_btn_convert"):
            dpg.bind_item_theme("vq_convert_btn", "theme_btn_convert")


def refresh_editor():
    """Refresh pattern editor grid."""
    ptns = state.get_patterns()
    patterns = [state.song.get_pattern(p) for p in ptns]
    max_len = state.song.max_pattern_length(state.songline)
    
    half = G.visible_rows // 2
    start_row = max(0, state.row - half)
    if start_row + G.visible_rows > max_len:
        start_row = max(0, max_len - G.visible_rows)
    
    for ch in range(MAX_CHANNELS):
        combo_tag = f"ch_ptn_combo_{ch}"
        if dpg.does_item_exist(combo_tag):
            dpg.set_value(combo_tag, G.fmt(ptns[ch]))
        cb_tag = f"ch_enabled_{ch}"
        if dpg.does_item_exist(cb_tag):
            dpg.set_value(cb_tag, state.audio.is_channel_enabled(ch))
    
    for vis_row in range(G.visible_rows):
        row_idx = start_row + vis_row
        is_cursor_row = (row_idx == state.row)
        is_playing = (row_idx == G.play_row and state.songline == G.play_songline)
        # Check if this row is a highlight row (beat marker)
        is_highlight = (row_idx % G.highlight_interval == 0) if G.highlight_interval > 0 else False
        
        row_tag = f"row_num_{vis_row}"
        if dpg.does_item_exist(row_tag):
            if row_idx < max_len:
                dpg.configure_item(row_tag, label=G.fmt(row_idx))
                if is_playing:
                    theme = "theme_song_row_playing"
                elif is_cursor_row:
                    theme = "theme_song_row_cursor"
                elif is_highlight:
                    theme = "theme_song_row_highlight"
                else:
                    theme = "theme_song_row_normal"
                dpg.bind_item_theme(row_tag, theme)
            else:
                dpg.configure_item(row_tag, label="--")
                dpg.bind_item_theme(row_tag, "theme_song_row_empty")
        
        for ch in range(MAX_CHANNELS):
            ptn = patterns[ch]
            ptn_len = ptn.length
            ch_enabled = state.audio.is_channel_enabled(ch)
            is_repeat = row_idx >= ptn_len
            actual_row = row_idx % ptn_len if ptn_len > 0 else 0
            r = ptn.get_row(actual_row) if row_idx < max_len else None
            is_cursor = is_cursor_row and ch == state.channel
            is_selected = state.selection.contains(row_idx, ch)
            has_note = r.note > 0 if r else False
            
            # Helper to get cell theme with all conditions
            def cell_theme(is_col_cursor: bool) -> str:
                if is_col_cursor:
                    return "theme_cell_cursor"
                elif is_playing:
                    return "theme_cell_playing"
                elif is_cursor_row:
                    return "theme_cell_current_row"
                elif not ch_enabled:
                    return "theme_cell_inactive"
                elif is_highlight and not is_repeat:
                    return "theme_cell_highlight"
                else:
                    return get_cell_theme(False, False, is_selected, is_repeat, has_note, not ch_enabled)
            
            note_tag = f"cell_note_{vis_row}_{ch}"
            if dpg.does_item_exist(note_tag):
                if r and row_idx < max_len:
                    note_str = note_to_str(r.note)
                    prefix = "~" if is_repeat and actual_row == 0 else " "
                    dpg.configure_item(note_tag, label=f"{prefix}{note_str}")
                    dpg.bind_item_theme(note_tag, cell_theme(is_cursor and state.column == COL_NOTE))
                else:
                    dpg.configure_item(note_tag, label="")
            
            inst_tag = f"cell_inst_{vis_row}_{ch}"
            if dpg.does_item_exist(inst_tag):
                if r and row_idx < max_len:
                    inst_str = G.fmt_inst(r.instrument) if r.note > 0 else ("--" if state.hex_mode else "---")
                    dpg.configure_item(inst_tag, label=inst_str)
                    dpg.bind_item_theme(inst_tag, cell_theme(is_cursor and state.column == COL_INST))
                else:
                    dpg.configure_item(inst_tag, label="")
            
            vol_tag = f"cell_vol_{vis_row}_{ch}"
            if dpg.does_item_exist(vol_tag):
                if r and row_idx < max_len:
                    vol_str = G.fmt_vol(r.volume) if r.note > 0 else ("-" if state.hex_mode else "--")
                    dpg.configure_item(vol_tag, label=vol_str)
                    dpg.bind_item_theme(vol_tag, cell_theme(is_cursor and state.column == COL_VOL))
                else:
                    dpg.configure_item(vol_tag, label="")


def update_controls():
    """Update control widgets with current state."""
    if dpg.does_item_exist("oct_combo"):
        dpg.set_value("oct_combo", str(state.octave))
    if dpg.does_item_exist("step_input"):
        dpg.set_value("step_input", state.step)
    if dpg.does_item_exist("ptn_len_input"):
        ptn = state.song.get_pattern(state.selected_pattern)
        # Format as hex or decimal based on mode
        if state.hex_mode:
            dpg.set_value("ptn_len_input", f"{ptn.length:02X}")
        else:
            dpg.set_value("ptn_len_input", str(ptn.length))
    if dpg.does_item_exist("hex_mode_cb"):
        dpg.set_value("hex_mode_cb", state.hex_mode)
    if dpg.does_item_exist("volume_control_cb"):
        dpg.set_value("volume_control_cb", state.song.volume_control)
    # Show/hide volume in CURRENT section based on volume_control setting
    if dpg.does_item_exist("current_vol_group"):
        dpg.configure_item("current_vol_group", show=state.song.volume_control)
    if dpg.does_item_exist("title_input"):
        dpg.set_value("title_input", state.song.title)
    if dpg.does_item_exist("author_input"):
        dpg.set_value("author_input", state.song.author)
    if dpg.does_item_exist("input_vol_combo"):
        dpg.set_value("input_vol_combo", G.fmt_vol(state.volume))
    G.update_title()
