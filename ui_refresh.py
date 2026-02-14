"""POKEY VQ Tracker - UI Refresh Functions"""
import dearpygui.dearpygui as dpg
from constants import (MAX_CHANNELS, MAX_VOLUME, note_to_str, FOCUS_SONG,
                       COL_NOTE, COL_INST, COL_VOL)
from state import state
from ui_theme import get_cell_theme
from cell_colors import (get_note_color_theme as _get_note_color,
                         get_inst_color_theme as _get_inst_color,
                         get_vol_color_theme as _get_vol_color,
                         get_ptn_color_theme as _get_ptn_color,
                         get_combo_color_theme as _get_combo_color)
import ui_globals as G

# Callbacks set by main module to avoid circular imports
_preview_callback = None
_select_callback = None
_effects_callback = None


def set_instrument_callbacks(preview_cb, select_cb, effects_cb=None):
    """Set callbacks for instrument list buttons."""
    global _preview_callback, _select_callback, _effects_callback
    _preview_callback = preview_cb
    _select_callback = select_cb
    _effects_callback = effects_cb


def refresh_all():
    """Refresh all UI components."""
    refresh_all_pattern_combos()
    refresh_all_instrument_combos()
    refresh_song_editor()
    refresh_pattern_info()
    refresh_instruments()
    refresh_editor()
    update_controls()
    update_validation_indicator()
    
    # Update BUILD button state (depends on VQ conversion and instruments)
    # Import here to avoid circular import
    try:
        from ui_callbacks import update_build_button_state
        update_build_button_state()
    except ImportError:
        pass


def _color_combo(tag: str, value: int, palette: str):
    """Apply palette text color to a combo widget, or unbind if palette is None."""
    if not dpg.does_item_exist(tag):
        return
    ct = _get_combo_color(value, palette)
    if ct and dpg.does_item_exist(ct):
        dpg.bind_item_theme(tag, ct)
    else:
        dpg.bind_item_theme(tag, 0)  # unbind


def refresh_all_pattern_combos():
    """Update ALL pattern combo lists throughout the UI."""
    ptn_items = [G.fmt(i) for i in range(len(state.song.patterns))] + ["+"]
    
    if dpg.does_item_exist("ptn_select_combo"):
        dpg.configure_item("ptn_select_combo", items=ptn_items)
        if state.selected_pattern < len(state.song.patterns):
            dpg.set_value("ptn_select_combo", G.fmt(state.selected_pattern))
        _color_combo("ptn_select_combo", state.selected_pattern, G.ptn_palette)
    
    for ch in range(MAX_CHANNELS):
        combo_tag = f"ch_ptn_combo_{ch}"
        if dpg.does_item_exist(combo_tag):
            dpg.configure_item(combo_tag, items=ptn_items)
            ptns = state.get_patterns()
            if ch < len(ptns):
                dpg.set_value(combo_tag, G.fmt(ptns[ch]))
                _color_combo(combo_tag, ptns[ch], G.ptn_palette)


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
        _color_combo("input_inst_combo", state.instrument, G.inst_palette)
    
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
                        # Apply pattern palette color
                        cc = _get_ptn_color(ptn_val, G.ptn_palette, "n")
                        theme = cc or "theme_cell_empty"
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
                
                # SPD column is after all channel columns
                is_cursor = is_cursor_row and state.song_cursor_col == MAX_CHANNELS and state.focus == FOCUS_SONG
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
    from vq_convert import format_size
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
        # Get per-instrument sizes from VQ result (if available)
        vq_result = state.vq.result if state.vq.converted else None
        # Get optimize suggestions (if available)
        opt_result = getattr(state, '_optimize_result', None)
        
        for i, inst in enumerate(state.song.instruments):
            is_current = (i == state.instrument)
            theme = get_inst_theme(is_current, is_converted)
            
            with dpg.group(horizontal=True, parent="instlist"):
                # Instrument number
                dpg.add_text(f"{G.fmt(i)}", color=(100,100,110))
                dpg.add_spacer(width=2)
                
                # Preview button
                if _preview_callback:
                    play_btn = dpg.add_button(label=">", width=22, height=20,
                                              callback=_preview_callback, user_data=i)
                    with dpg.tooltip(play_btn):
                        dpg.add_text("Preview sample")
                
                dpg.add_spacer(width=2)
                
                # VQ checkbox
                cb_tag = f"inst_vq_cb_{i}"
                dpg.add_checkbox(tag=cb_tag, label="", default_value=inst.use_vq,
                                 callback=_on_vq_checkbox_change, user_data=i)
                with dpg.tooltip(cb_tag):
                    if inst.use_vq:
                        dpg.add_text("VQ compressed", color=(200, 200, 100))
                        dpg.add_text("Uncheck for RAW (better quality, more memory)")
                    else:
                        dpg.add_text("RAW (uncompressed)", color=(100, 200, 100))
                        dpg.add_text("Check for VQ (smaller, lower quality)")
                
                # Optimize suggestion indicator (next to checkbox)
                if opt_result and i < len(opt_result.analyses):
                    a = opt_result.analyses[i]
                    if a.skipped:
                        # Unused instrument in "Used Samples" mode
                        ind = dpg.add_text("-", color=(100, 100, 110))
                        with dpg.tooltip(ind):
                            dpg.add_text("Unused in song", color=(150, 150, 150))
                            dpg.add_text("Not included in CONVERT/OPTIMIZE.")
                            dpg.add_text("Add notes using this instrument")
                            dpg.add_text("or uncheck 'Used Samples'.")
                    elif a.suggest_raw:
                        matches = not inst.use_vq  # RAW suggested, checkbox unchecked = match
                        if matches:
                            ind = dpg.add_text("R", color=(100, 255, 100))
                        else:
                            ind = dpg.add_text("R", color=(255, 100, 100))
                        with dpg.tooltip(ind):
                            dpg.add_text("Optimizer: RAW", color=(100, 255, 100))
                            if not matches:
                                dpg.add_text("(you overrode this)", color=(255, 200, 100))
                            dpg.add_text(f"Reason: {a.reason}")
                            dpg.add_text(f"RAW: {format_size(a.raw_size_aligned)}, VQ: {format_size(a.vq_size)}")
                            if a.cpu_saving > 0.5:
                                dpg.add_text(f"CPU saving: {a.cpu_saving:.1f} cyc/IRQ")
                    else:
                        matches = inst.use_vq  # VQ suggested, checkbox checked = match
                        if matches:
                            ind = dpg.add_text("V", color=(200, 200, 100))
                        else:
                            ind = dpg.add_text("V", color=(255, 100, 100))
                        with dpg.tooltip(ind):
                            dpg.add_text("Optimizer: VQ", color=(200, 200, 100))
                            if not matches:
                                dpg.add_text("(you overrode this)", color=(255, 200, 100))
                            dpg.add_text(f"Reason: {a.reason}")
                            dpg.add_text(f"RAW: {format_size(a.raw_size_aligned)}, VQ: {format_size(a.vq_size)}")
                
                # Effects indicator button (opens sample editor)
                has_fx = bool(inst.effects)
                fx_label = "E" if has_fx else " "
                fx_btn = dpg.add_button(label=fx_label, width=20, height=20,
                                        callback=_effects_callback or _select_callback,
                                        user_data=i)
                if has_fx:
                    dpg.bind_item_theme(fx_btn, "theme_fx_active")
                with dpg.tooltip(fx_btn):
                    if has_fx:
                        n = len(inst.effects)
                        dpg.add_text(f"{n} effect(s) applied", color=(180, 220, 255))
                        for fx in inst.effects[:5]:
                            dpg.add_text(f"  {fx.type}", color=(140, 160, 180))
                        dpg.add_text("Click to open Sample Editor")
                    else:
                        dpg.add_text("No effects", color=(120, 120, 120))
                        dpg.add_text("Click to open Sample Editor")
                
                # Instrument name button (clickable to select)
                name = inst.name[:20] if inst.name else "(unnamed)"
                
                # Build label with size info
                size_str = ""
                if vq_result and i < len(vq_result.inst_vq_sizes):
                    if inst.use_vq:
                        sz = vq_result.inst_vq_sizes[i]
                        size_str = f" ({format_size(sz)})" if sz > 0 else ""
                    else:
                        # Show RAW size estimate (page-aligned)
                        if inst.is_loaded():
                            from optimize import compute_raw_size, compute_raw_size_aligned
                            raw_sz = compute_raw_size(
                                inst.processed_data if inst.processed_data is not None else inst.sample_data,
                                inst.sample_rate, state.vq.settings.rate)
                            raw_aligned = compute_raw_size_aligned(raw_sz)
                            size_str = f" ({format_size(raw_aligned)})"
                elif inst.is_loaded():
                    # Before conversion: show estimated size
                    from optimize import compute_raw_size, compute_raw_size_aligned, estimate_vq_size
                    data = inst.processed_data if inst.processed_data is not None else inst.sample_data
                    sr = inst.sample_rate
                    rate = state.vq.settings.rate
                    if inst.use_vq:
                        est = estimate_vq_size(data, sr, rate, state.vq.settings.vector_size)
                        size_str = f" (~{format_size(est)})"
                    else:
                        est = compute_raw_size_aligned(compute_raw_size(data, sr, rate))
                        size_str = f" (~{format_size(est)})"
                
                label = f"{name}{size_str}"
                
                if _select_callback:
                    btn = dpg.add_button(label=label, width=-1, height=20,
                                         callback=_select_callback, user_data=i)
                    with dpg.tooltip(btn):
                        lines = [f"Click to select as current instrument"]
                        if inst.is_loaded():
                            dur = inst.duration()
                            lines.append(f"Duration: {dur:.2f}s")
                            lines.append(f"Mode: {'VQ' if inst.use_vq else 'RAW'}")
                        for line in lines:
                            dpg.add_text(line)
                    dpg.bind_item_theme(btn, theme)
    
    # Update VQ UI elements
    _update_vq_ui()
    
    refresh_all_instrument_combos()


def _on_vq_checkbox_change(sender, app_data, user_data):
    """Handle VQ checkbox toggle for an instrument."""
    from ui_callbacks import invalidate_vq_conversion
    inst_idx = user_data
    if 0 <= inst_idx < len(state.song.instruments):
        state.song.instruments[inst_idx].use_vq = app_data
        # Changing VQ/RAW mode requires re-conversion because:
        # - SAMPLE_DIR.asm pointers change (VQ_INDICES vs RAW_INST_XX labels)
        # - SAMPLE_MODE flags change ($00 vs $FF)
        # - RAW_SAMPLES.asm needs regeneration
        # - VQ_BLOB format may change (size→speed forced by RAW instruments)
        # Preserve optimize suggestions — they're still valid as reference
        saved = getattr(state, '_optimize_result', None)
        invalidate_vq_conversion()
        state._optimize_result = saved
        # Re-refresh with restored optimize result (invalidate already refreshed
        # once but _optimize_result was None at that point)
        refresh_instruments()


def _update_vq_ui():
    """Update VQ-related UI elements based on state."""
    from vq_convert import format_size
    
    # Update size label
    if dpg.does_item_exist("vq_size_label"):
        if state.vq.converted and state.vq.result and state.vq.result.vq_data_size > 0:
            dpg.set_value("vq_size_label", f"Atari data: {format_size(state.vq.result.vq_data_size)}")
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
            _color_combo(combo_tag, ptns[ch], G.ptn_palette)
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
                    base_theme = cell_theme(is_cursor and state.column == COL_NOTE)
                    # Apply palette color for data cells (not cursor/playing/selected/inactive/repeat)
                    cc_theme = None
                    if (r.note > 0 and not is_cursor and not is_playing
                            and not is_repeat and ch_enabled
                            and not is_selected and G.note_palette != "None"):
                        variant = "c" if is_cursor_row else ("h" if is_highlight else "n")
                        cc_theme = _get_note_color(r.note, G.note_palette, variant)
                    dpg.bind_item_theme(note_tag, cc_theme or base_theme)
                else:
                    dpg.configure_item(note_tag, label="")
            
            inst_tag = f"cell_inst_{vis_row}_{ch}"
            if dpg.does_item_exist(inst_tag):
                if r and row_idx < max_len:
                    inst_str = G.fmt_inst(r.instrument) if r.note > 0 else ("--" if state.hex_mode else "---")
                    dpg.configure_item(inst_tag, label=inst_str)
                    
                    # Check for invalid instrument reference (has note but inst doesn't exist)
                    has_invalid_inst = (r.note > 0 and r.note not in (255, 254) and 
                                       r.instrument >= len(state.song.instruments))
                    
                    if has_invalid_inst and not is_cursor:
                        dpg.bind_item_theme(inst_tag, "theme_cell_warning")
                    else:
                        base_theme = cell_theme(is_cursor and state.column == COL_INST)
                        cc_theme = None
                        if (r.note > 0 and not has_invalid_inst
                                and not is_cursor and not is_playing
                                and not is_repeat and ch_enabled
                                and not is_selected and G.inst_palette != "None"):
                            variant = "c" if is_cursor_row else ("h" if is_highlight else "n")
                            cc_theme = _get_inst_color(r.instrument, True, G.inst_palette, variant)
                        dpg.bind_item_theme(inst_tag, cc_theme or base_theme)
                else:
                    dpg.configure_item(inst_tag, label="")
            
            vol_tag = f"cell_vol_{vis_row}_{ch}"
            if dpg.does_item_exist(vol_tag):
                if r and row_idx < max_len:
                    vol_str = G.fmt_vol(r.volume) if r.note > 0 else ("-" if state.hex_mode else "--")
                    dpg.configure_item(vol_tag, label=vol_str)
                    base_theme = cell_theme(is_cursor and state.column == COL_VOL)
                    cc_theme = None
                    if (r.note > 0 and not is_cursor and not is_playing
                            and not is_repeat and ch_enabled
                            and not is_selected and G.vol_palette != "None"):
                        variant = "c" if is_cursor_row else ("h" if is_highlight else "n")
                        cc_theme = _get_vol_color(r.volume, True, G.vol_palette, variant)
                    dpg.bind_item_theme(vol_tag, cc_theme or base_theme)
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
    if dpg.does_item_exist("screen_control_cb"):
        dpg.set_value("screen_control_cb", state.song.screen_control)
    if dpg.does_item_exist("keyboard_control_cb"):
        dpg.set_value("keyboard_control_cb", state.song.keyboard_control)
    if dpg.does_item_exist("start_address_input"):
        dpg.set_value("start_address_input", f"{state.song.start_address:04X}")
    if dpg.does_item_exist("memory_config_combo"):
        dpg.set_value("memory_config_combo", state.song.memory_config)
    # Show/hide volume in CURRENT section based on volume_control setting
    if dpg.does_item_exist("current_vol_group"):
        dpg.configure_item("current_vol_group", show=state.song.volume_control)
    if dpg.does_item_exist("title_input"):
        dpg.set_value("title_input", state.song.title)
    if dpg.does_item_exist("author_input"):
        dpg.set_value("author_input", state.song.author)
    if dpg.does_item_exist("input_vol_combo"):
        dpg.set_value("input_vol_combo", G.fmt_vol(state.volume))
    
    # Update VQ settings combos
    if dpg.does_item_exist("vq_rate_combo"):
        dpg.set_value("vq_rate_combo", f"{state.vq.settings.rate} Hz")
    if dpg.does_item_exist("vq_vector_combo"):
        dpg.set_value("vq_vector_combo", str(state.vq.settings.vector_size))
    if dpg.does_item_exist("vq_smooth_combo"):
        dpg.set_value("vq_smooth_combo", str(state.vq.settings.smoothness))
    if dpg.does_item_exist("vq_enhance_cb"):
        dpg.set_value("vq_enhance_cb", state.vq.settings.enhance)
    if dpg.does_item_exist("vq_used_only_cb"):
        dpg.set_value("vq_used_only_cb", state.vq.settings.used_only)
    
    G.update_title()


def quick_validate_song():
    """Run quick validation and update the validation indicator.
    
    Returns (error_count, warning_count, first_issue_msg)
    """
    from constants import MAX_ROWS, MAX_NOTES, MAX_VOLUME, NOTE_OFF, VOL_CHANGE
    
    errors = 0
    warnings = 0
    first_issue = None
    
    song = state.song
    
    # Check if song has content
    if not song.songlines or not song.patterns:
        return (1, 0, "Empty song")
    
    # Check pattern lengths and note values
    for ptn_idx, pattern in enumerate(song.patterns):
        # Check length (max 254 for export)
        if pattern.length > MAX_ROWS:
            errors += 1
            if not first_issue:
                first_issue = f"Pattern {ptn_idx}: length {pattern.length} > {MAX_ROWS}"
        
        # Check rows
        for row_idx, row in enumerate(pattern.rows):
            if row_idx >= pattern.length:
                break
            
            # Check note
            if row.note != 0 and row.note != NOTE_OFF:
                if row.note != VOL_CHANGE and (row.note < 1 or row.note > MAX_NOTES):
                    errors += 1
                    if not first_issue:
                        first_issue = f"Ptn {ptn_idx} Row {row_idx}: invalid note {row.note}"
                        
            # Check volume
            if row.volume < 0 or row.volume > MAX_VOLUME:
                errors += 1
                if not first_issue:
                    first_issue = f"Ptn {ptn_idx} Row {row_idx}: invalid volume"
    
    # Track used instruments
    used_instruments = set()
    for pattern in song.patterns:
        for row in pattern.rows[:pattern.length]:
            if row.note > 0 and row.note not in (NOTE_OFF, VOL_CHANGE):
                used_instruments.add(row.instrument)
    
    # Check instrument references
    num_instruments = len(song.instruments)
    for inst_idx in used_instruments:
        if inst_idx >= num_instruments:
            errors += 1
            if not first_issue:
                first_issue = f"Instrument {inst_idx} referenced but not defined"
        elif inst_idx < num_instruments and not song.instruments[inst_idx].is_loaded():
            warnings += 1
            if not first_issue:
                first_issue = f"Instrument {inst_idx} has no sample"
    
    # Check songline pattern references
    num_patterns = len(song.patterns)
    for sl_idx, sl in enumerate(song.songlines):
        for ch, ptn_idx in enumerate(sl.patterns):
            if ptn_idx >= num_patterns:
                errors += 1
                if not first_issue:
                    first_issue = f"Songline {sl_idx}: invalid pattern {ptn_idx}"
    
    return (errors, warnings, first_issue)


def update_validation_indicator():
    """Update the validation indicator in status bar."""
    if not dpg.does_item_exist("validation_indicator"):
        return
    
    errors, warnings, first_issue = quick_validate_song()
    
    if errors > 0:
        # Red - errors found
        dpg.configure_item("validation_indicator", color=(255, 100, 100))
        dpg.set_value("validation_indicator", f"[X] {errors} error(s)")
        if dpg.does_item_exist("validation_tooltip_text"):
            dpg.set_value("validation_tooltip_text", first_issue or "Click VALIDATE for details")
    elif warnings > 0:
        # Yellow - warnings only
        dpg.configure_item("validation_indicator", color=(255, 200, 100))
        dpg.set_value("validation_indicator", f"[!] {warnings} warning(s)")
        if dpg.does_item_exist("validation_tooltip_text"):
            dpg.set_value("validation_tooltip_text", first_issue or "Click VALIDATE for details")
    else:
        # Green - all good
        dpg.configure_item("validation_indicator", color=(100, 200, 100))
        dpg.set_value("validation_indicator", "[OK] Valid")
        if dpg.does_item_exist("validation_tooltip_text"):
            dpg.set_value("validation_tooltip_text", "Song is ready for export")


# =============================================================================
# VU METERS — vertical bars per channel
# =============================================================================

_vu_display = [0.0] * MAX_CHANNELS  # Smoothed display levels (0.0–1.0)
_vu_was_silent = True  # Track if we already cleared

_VU_DECAY = 0.92   # Per-frame decay (~60fps: full→10% in ~0.6s)
_VU_TAG = "vu_drawlist"

# Bar colors (RGBA) — match channel header colors
_VU_BAR = [
    (200, 60, 60, 180),    # Ch1 red
    (60, 180, 80, 180),    # Ch2 green
    (60, 120, 220, 180),   # Ch3 blue
    (200, 165, 50, 180),   # Ch4 amber
]
_VU_PEAK = [
    (255, 140, 140, 255),  # Ch1 bright red
    (140, 255, 160, 255),  # Ch2 bright green
    (140, 190, 255, 255),  # Ch3 bright blue
    (255, 220, 120, 255),  # Ch4 bright amber
]
_VU_GLOW = [
    (255, 80, 80, 60),     # Ch1 glow
    (80, 255, 100, 60),    # Ch2 glow
    (80, 150, 255, 60),    # Ch3 glow
    (255, 200, 60, 60),    # Ch4 glow
]


def update_vu_meters():
    """Update VU meter drawlist — vertical bars per channel.
    
    Called every frame from main loop.  Each bar spikes up on note
    trigger and decays smoothly downward.
    """
    global _vu_display, _vu_was_silent
    if not dpg.does_item_exist(_VU_TAG):
        return

    # Read engine levels and apply peak-hold + decay
    engine_levels = state.audio.get_vu_levels()
    for i in range(MAX_CHANNELS):
        fresh = engine_levels[i] if i < len(engine_levels) else 0.0
        _vu_display[i] = max(fresh, _vu_display[i] * _VU_DECAY)
        # Let engine level decay too so next frame sees lower value
        if i < len(state.audio.channels):
            state.audio.channels[i].vu_level *= _VU_DECAY

    # Skip drawing when all silent
    if all(v < 0.005 for v in _vu_display):
        if not _vu_was_silent:
            children = dpg.get_item_children(_VU_TAG, slot=2)
            if children:
                dpg.delete_item(_VU_TAG, children_only=True)
            _vu_was_silent = True
        return
    _vu_was_silent = False

    # Get dimensions
    w = dpg.get_item_width(_VU_TAG)
    h = dpg.get_item_height(_VU_TAG)
    if w < 20 or h < 10:
        return

    dpg.delete_item(_VU_TAG, children_only=True)

    pad = 4
    gap = 5
    bar_w = max(6, (w - 2 * pad - (MAX_CHANNELS - 1) * gap) // MAX_CHANNELS)
    max_h = h - pad * 2   # usable vertical pixels
    peak_h = 3            # bright cap at top of bar

    for i in range(MAX_CHANNELS):
        level = min(1.0, _vu_display[i])
        x = pad + i * (bar_w + gap)
        bar_h = int(max_h * level)

        if bar_h < 1:
            continue

        y_top = pad + (max_h - bar_h)
        y_bot = pad + max_h

        # Glow behind bar (wider, translucent)
        if bar_h > 4:
            dpg.draw_rectangle(
                (x - 1, y_top + 1), (x + bar_w + 1, y_bot),
                fill=_VU_GLOW[i], color=(0, 0, 0, 0), parent=_VU_TAG)

        # Main bar body
        dpg.draw_rectangle(
            (x, y_top), (x + bar_w, y_bot),
            fill=_VU_BAR[i], color=(0, 0, 0, 0), parent=_VU_TAG)

        # Peak cap (bright line at top)
        cap_bot = min(y_top + peak_h, y_bot)
        dpg.draw_rectangle(
            (x, y_top), (x + bar_w, cap_bot),
            fill=_VU_PEAK[i], color=(0, 0, 0, 0), parent=_VU_TAG)
