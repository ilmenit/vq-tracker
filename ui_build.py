"""POKEY VQ Tracker - UI Building Functions"""
import os
import dearpygui.dearpygui as dpg
from constants import (MAX_CHANNELS, MAX_VOLUME, MAX_ROWS, ROW_HEIGHT, COL_CH,
                       COL_NOTE, COL_INST, COL_VOL, COL_DIM,
                       VQ_RATES, VQ_RATE_DEFAULT, VQ_VECTOR_SIZES, VQ_VECTOR_DEFAULT,
                       VQ_SMOOTHNESS_VALUES, VQ_SMOOTHNESS_DEFAULT,
                       MEMORY_CONFIG_NAMES, DEFAULT_MEMORY_CONFIG)
from state import state
from ui_dialogs import show_about, show_shortcuts
import ops
import ui_globals as G
import key_config
import ui_callbacks as C


def rebuild_recent_menu():
    """Rebuild the recent files menu."""
    if not dpg.does_item_exist("recent_menu"):
        return
    dpg.delete_item("recent_menu", children_only=True)
    
    if not G.recent_files:
        dpg.add_menu_item(label="(none)", parent="recent_menu", enabled=False)
    else:
        for path in G.recent_files:
            import os
            name = os.path.basename(path)
            dpg.add_menu_item(label=name, parent="recent_menu",
                              callback=C.load_recent_file, user_data=path)


def show_confirm_centered(title: str, message: str, callback):
    """Show a centered confirmation dialog with Yes/No buttons."""
    if dpg.does_item_exist("confirm_dlg"):
        dpg.delete_item("confirm_dlg")
    
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    dlg_w, dlg_h = 320, 130
    btn_w = 90
    spacing = 20
    left_margin = (dlg_w - btn_w * 2 - spacing) // 2 - 8
    
    def on_yes():
        dpg.delete_item("confirm_dlg")
        callback()
    
    def on_no():
        dpg.delete_item("confirm_dlg")
    
    with dpg.window(tag="confirm_dlg", label=title, modal=True, no_resize=True,
                    no_collapse=True, width=dlg_w, height=dlg_h,
                    pos=[(vp_w - dlg_w) // 2, (vp_h - dlg_h) // 2]):
        dpg.add_spacer(height=5)
        dpg.add_text(message)
        dpg.add_spacer(height=20)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="Yes", width=btn_w, callback=on_yes)
            dpg.add_spacer(width=spacing)
            dpg.add_button(label="No", width=btn_w, callback=on_no)


def on_delete_songline_confirm():
    def do_delete():
        ops.delete_songline()
    show_confirm_centered("Delete Songline", "Delete current songline?", do_delete)


def on_delete_pattern_confirm():
    def do_delete():
        ops.delete_pattern()
    show_confirm_centered("Delete Pattern", f"Delete pattern {G.fmt(state.selected_pattern)}?", do_delete)


def on_close_request(*args):
    """Handle close request (X button, Alt+F4, File→Exit).
    
    If there are unsaved changes, shows a 3-button confirmation dialog.
    Otherwise closes immediately.
    """
    if not state.song.modified:
        _do_quit()
        return

    # Song has unsaved changes - show confirmation
    tag = "quit_confirm_dlg"
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

    state.set_input_active(True)

    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    dlg_w, dlg_h = 380, 145
    btn_w = 100
    spacing = 12
    total_btns = btn_w * 3 + spacing * 2
    left_margin = (dlg_w - total_btns) // 2 - 8

    def on_save_quit():
        state.set_input_active(False)
        dpg.delete_item(tag)
        # Save first, then quit
        if state.song.file_path:
            ops.save_song()
            _do_quit()
        else:
            # Need Save As - save, then quit when done
            import native_dialog
            path = native_dialog.save_file(
                title="Save Project",
                start_dir=os.path.expanduser("~"),
                filters={"Project Files": "pvq"},
                default_name="untitled.pvq",
            )
            if path:
                from ops.file_ops import _save_file
                _save_file(path)
                _do_quit()
            # If cancelled Save As, don't quit

    def on_quit_no_save():
        state.set_input_active(False)
        dpg.delete_item(tag)
        _do_quit()

    def on_cancel():
        state.set_input_active(False)
        dpg.delete_item(tag)

    with dpg.window(tag=tag, label="Unsaved Changes", modal=True, no_resize=True,
                    no_collapse=True, width=dlg_w, height=dlg_h,
                    pos=[(vp_w - dlg_w) // 2, (vp_h - dlg_h) // 2]):
        dpg.add_spacer(height=5)
        dpg.add_text("You have unsaved changes. What would you like to do?")
        dpg.add_spacer(height=20)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="Save & Quit", width=btn_w, callback=on_save_quit)
            dpg.add_spacer(width=spacing)
            dpg.add_button(label="Quit", width=btn_w, callback=on_quit_no_save)
            dpg.add_spacer(width=spacing)
            dpg.add_button(label="Cancel", width=btn_w, callback=on_cancel)


def _do_quit():
    """Unconditional shutdown - save config and stop DPG."""
    import logging
    logger = logging.getLogger("tracker.main")
    logger.info("Exiting...")
    if G.autosave_enabled and state.song.modified:
        G.do_autosave()
    G.save_config()
    dpg.stop_dearpygui()



# =============================================================================
# SETTINGS DIALOG (modal)
# =============================================================================

_SETTINGS_DLG = "settings_dialog"

def show_settings_dialog(*args):
    """Open the Settings dialog (modal)."""
    if dpg.does_item_exist(_SETTINGS_DLG):
        dpg.delete_item(_SETTINGS_DLG)

    state.set_input_active(True)
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 580, 480

    def on_close():
        state.set_input_active(False)
        G.save_config()
        if dpg.does_item_exist(_SETTINGS_DLG):
            dpg.delete_item(_SETTINGS_DLG)

    def _on_palette_change(sender, value, user_data):
        col_type = user_data  # "note", "inst", "vol", or "ptn"
        if col_type == "note":
            G.note_palette = value
        elif col_type == "inst":
            G.inst_palette = value
        elif col_type == "vol":
            G.vol_palette = value
        elif col_type == "ptn":
            G.ptn_palette = value
        G.save_config()
        # Update preview strip
        _update_preview(col_type, value)
        # Refresh editors to show new colors
        import ui_refresh as ui
        ui.refresh_editor()
        ui.refresh_song_editor()
        ui.refresh_all_pattern_combos()
        ui.refresh_all_instrument_combos()

    def _update_preview(col_type, palette_name):
        """Update the 16-number preview strip for a palette row."""
        for i in range(16):
            tag = f"{_SETTINGS_DLG}_prev_{col_type}_{i}"
            if dpg.does_item_exist(tag):
                if palette_name == "None":
                    dpg.configure_item(tag, color=(160, 160, 160))
                else:
                    from cell_colors import PALETTES
                    colors = PALETTES.get(palette_name)
                    if colors and i < len(colors):
                        dpg.configure_item(tag, color=colors[i])

    def _add_palette_row(label, default, user_data, tooltip_text):
        """Add a palette combo + preview row inside a table."""
        with dpg.table_row():
            # Column 1: label
            with dpg.table_cell():
                dpg.add_text(f"{label}:", color=(180, 180, 180))
            # Column 2: combo
            with dpg.table_cell():
                c = dpg.add_combo(items=PALETTE_NAMES, default_value=default,
                                  width=110, callback=_on_palette_change,
                                  user_data=user_data)
                with dpg.tooltip(c):
                    dpg.add_text(tooltip_text)
            # Column 3: preview strip
            with dpg.table_cell():
                from cell_colors import PALETTES
                colors = PALETTES.get(default, [(160, 160, 160)] * 16)
                with dpg.group(horizontal=True):
                    for i in range(16):
                        lbl = f"{i:X}" if state.hex_mode else f"{i}"
                        col = colors[i] if default != "None" else (160, 160, 160)
                        dpg.add_text(lbl, tag=f"{_SETTINGS_DLG}_prev_{user_data}_{i}",
                                     color=col)

    from cell_colors import PALETTE_NAMES

    with dpg.window(tag=_SETTINGS_DLG, label="Settings", modal=True,
                    width=w, height=h,
                    pos=[(vp_w - w) // 2, (vp_h - h) // 2],
                    no_resize=True, no_collapse=True, on_close=on_close):
        dpg.add_spacer(height=5)

        dpg.add_checkbox(tag="hex_mode_cb", label="Hex mode",
                         default_value=state.hex_mode, callback=C.on_hex_toggle)
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text("Hexadecimal Mode", color=(255, 255, 150))
            dpg.add_separator()
            dpg.add_text("Display all numbers in hexadecimal.")
            dpg.add_text("Useful for Atari programming.")
        dpg.add_spacer(height=5)

        dpg.add_checkbox(tag="autosave_cb", label="Auto-save",
                         default_value=G.autosave_enabled,
                         callback=C.on_autosave_toggle)
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text("Auto-save", color=(255, 255, 150))
            dpg.add_separator()
            dpg.add_text("Automatically save backup every 60 seconds.")
            dpg.add_text("Prevents data loss on crash.")
        dpg.add_spacer(height=5)

        dpg.add_checkbox(tag="piano_keys_cb", label="Piano keys",
                         default_value=G.piano_keys_mode,
                         callback=C.on_piano_keys_toggle)
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text("Keyboard Style", color=(255, 255, 150))
            dpg.add_separator()
            dpg.add_text("Piano mode (ON): 2,3,5,6,7 play sharps")
            dpg.add_text("Tracker mode (OFF): 1 = Note-OFF, 2-3 = Octave")
        dpg.add_spacer(height=5)

        dpg.add_checkbox(tag="coupled_cb", label="Coupled note entry",
                         default_value=G.coupled_entry,
                         callback=C.on_coupled_toggle)
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text("Coupled Entry", color=(255, 255, 150))
            dpg.add_separator()
            dpg.add_text("ON: entering a note stamps instrument + volume.")
            dpg.add_text("OFF: only changes the note (edit mask).")

        dpg.add_spacer(height=10)
        dpg.add_separator()
        dpg.add_spacer(height=6)

        # Cell Colors section
        dpg.add_text("CELL COLORS", color=(200, 200, 100))
        dpg.add_spacer(height=4)

        with dpg.table(header_row=False, borders_innerH=False,
                        borders_outerH=False, borders_innerV=False,
                        borders_outerV=False, pad_outerX=True):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=80)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=120)
            dpg.add_table_column(width_stretch=True)

            _add_palette_row("Note",       G.note_palette, "note",
                             "Color notes by pitch (C through B)")
            _add_palette_row("Instrument", G.inst_palette, "inst",
                             "Color by instrument number (mod 16)")
            _add_palette_row("Volume",     G.vol_palette, "vol",
                             "Color by volume level (0-15)")
            _add_palette_row("Pattern",    G.ptn_palette, "ptn",
                             "Color pattern numbers in Song grid and combos")

        dpg.add_spacer(height=10)
        dpg.add_separator()
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=w - 130)
            dpg.add_button(label="Close", width=80, callback=on_close)


def build_menu():
    """Build the main menu bar."""
    with dpg.menu_bar():
        with dpg.menu(label="File"):
            dpg.add_menu_item(label="New", callback=ops.new_song, shortcut="Ctrl+N")
            dpg.add_menu_item(label="Open...", callback=ops.open_song, shortcut="Ctrl+O")
            with dpg.menu(label="Open Recent", tag="recent_menu"):
                pass
            dpg.add_menu_item(label="Recover Autosave...", callback=C.show_autosave_recovery)
            dpg.add_separator()
            dpg.add_menu_item(label="Save", callback=ops.save_song, shortcut="Ctrl+S")
            dpg.add_menu_item(label="Save As...", callback=ops.save_song_as)
            dpg.add_separator()
            dpg.add_menu_item(label="Import MOD...", callback=ops.import_mod)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Import Amiga MOD", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Import an Amiga ProTracker .MOD file.")
                dpg.add_text("Converts patterns, instruments and song")
                dpg.add_text("arrangement to native tracker format.")
            dpg.add_menu_item(label="Export WAV...", callback=ops.export_wav)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Export to WAV", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Render entire song to a .wav audio file.")
                dpg.add_text("Plays through all songlines once.")
            dpg.add_separator()
            dpg.add_menu_item(label="Exit", callback=on_close_request)
        
        with dpg.menu(label="Edit"):
            dpg.add_menu_item(label="Undo", callback=ops.undo, shortcut="Ctrl+Z")
            dpg.add_menu_item(label="Redo", callback=ops.redo, shortcut="Ctrl+Y")
            dpg.add_separator()
            dpg.add_menu_item(label="Copy", callback=ops.copy_cells, shortcut="Ctrl+C")
            dpg.add_menu_item(label="Cut", callback=ops.cut_cells, shortcut="Ctrl+X")
            dpg.add_menu_item(label="Paste", callback=ops.paste_cells, shortcut="Ctrl+V")
            dpg.add_menu_item(label="Select All", callback=ops.select_all, shortcut="Ctrl+A")
            dpg.add_separator()
            dpg.add_menu_item(label="Clear Pattern", callback=ops.clear_pattern)
        
        with dpg.menu(label="Song"):
            dpg.add_menu_item(label="Add Row", callback=ops.add_songline)
            dpg.add_menu_item(label="Clone Row", callback=ops.clone_songline)
            dpg.add_menu_item(label="Delete Row", callback=on_delete_songline_confirm)
        
        with dpg.menu(label="Pattern"):
            dpg.add_menu_item(label="New", callback=ops.add_pattern)
            dpg.add_menu_item(label="Clone", callback=ops.clone_pattern)
            dpg.add_menu_item(label="Delete", callback=on_delete_pattern_confirm)
            dpg.add_separator()
            dpg.add_menu_item(label="Transpose +1", callback=lambda: ops.transpose(1))
            dpg.add_menu_item(label="Transpose -1", callback=lambda: ops.transpose(-1))
            dpg.add_menu_item(label="Transpose +12", callback=lambda: ops.transpose(12))
            dpg.add_menu_item(label="Transpose -12", callback=lambda: ops.transpose(-12))
            dpg.add_separator()
            dpg.add_menu_item(label="Replace Instrument...", callback=C.on_replace_instrument)
        
        with dpg.menu(label="Editor"):
            dpg.add_menu_item(label="Settings...", callback=show_settings_dialog)
            dpg.add_separator()
            dpg.add_menu_item(label="Keyboard Shortcuts", callback=show_shortcuts, shortcut="F1")
        
        with dpg.menu(label="Help"):
            dpg.add_menu_item(label="About", callback=show_about)


def build_input_row():
    """Build the CURRENT section - brush settings + Mark."""
    with dpg.child_window(height=40, border=True):
        with dpg.group(horizontal=True):
            dpg.add_text("CURRENT:")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Input Settings", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Settings for notes entered via keyboard.")
            dpg.add_spacer(width=8)
            dpg.add_text("Instrument:")
            items = [f"{G.fmt(i)} - {inst.name[:12]}" for i, inst in enumerate(state.song.instruments)]
            inst_combo = dpg.add_combo(tag="input_inst_combo", items=items if items else ["(none)"],
                          default_value=items[0] if items else "(none)", width=150, callback=C.on_input_inst_change)
            with dpg.tooltip(inst_combo):
                dpg.add_text("Current Instrument", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Instrument used when entering new notes.")
            dpg.add_spacer(width=10)
            # Volume section - can be hidden when volume_control is disabled
            with dpg.group(horizontal=True, tag="current_vol_group", show=state.song.volume_control):
                dpg.add_text("Volume:")
                vol_items = [G.fmt_vol(v) for v in range(MAX_VOLUME + 1)]
                vol_combo = dpg.add_combo(tag="input_vol_combo", items=vol_items,
                              default_value=G.fmt_vol(state.volume), width=45, callback=C.on_input_vol_change)
                with dpg.tooltip(vol_combo):
                    dpg.add_text("Current Volume", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Volume for new notes (0-15).")
                dpg.add_spacer(width=10)
            dpg.add_text("Octave:")
            oct_combo = dpg.add_combo(tag="oct_combo", items=["1","2","3"], default_value=str(state.octave),
                          width=40, callback=C.on_octave_change)
            with dpg.tooltip(oct_combo):
                dpg.add_text("Current Octave", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Base octave for keyboard input (1-3).")
            dpg.add_spacer(width=10)
            dpg.add_text("Step:")
            dpg.add_spacer(width=3)
            inp = dpg.add_input_int(tag="step_input", default_value=state.step,
                                    min_value=0, max_value=16, min_clamped=True, max_clamped=True,
                                    width=75, callback=C.on_step_change, on_enter=True)
            with dpg.tooltip(inp):
                dpg.add_text("Cursor Step", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Rows to advance after note entry.")
                dpg.add_text("0 = cursor stays in place.")
            with dpg.item_handler_registry() as h:
                dpg.add_item_activated_handler(callback=G.on_input_focus)
                dpg.add_item_deactivated_handler(callback=G.on_input_blur)
            dpg.bind_item_handler_registry(inp, h)
            dpg.add_spacer(width=10)
            dpg.add_text("Mark:")
            dpg.add_combo(tag="highlight_combo", items=["2", "4", "8", "16"],
                          default_value=str(G.highlight_interval), width=45,
                          callback=C.on_highlight_change)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Row Highlight Interval", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Mark every N rows for visual beat reference.")

def rebuild_editor_grid():
    """Rebuild the pattern editor grid."""
    if dpg.does_item_exist("editor_content"):
        dpg.delete_item("editor_content")
    
    row_num_w = 32 if state.hex_mode else 40
    note_w = 44
    inst_w = 32 if state.hex_mode else 40
    vol_w = 24 if state.hex_mode else 30
    ch_spacer = 12
    
    # Volume column visibility based on song setting
    show_volume = state.song.volume_control
    
    # Resize editor panel to fit content
    new_width = G.compute_editor_width(state.hex_mode, show_volume)
    if dpg.does_item_exist("editor_panel"):
        dpg.configure_item("editor_panel", width=new_width)
    
    with dpg.group(tag="editor_content", parent="editor_panel"):
        # Per-channel data width (must match column headers and data rows)
        ch_data_w = note_w + 8 + inst_w  # IS=8 between buttons
        if show_volume:
            ch_data_w += 8 + vol_w
        
        # Row 1: Channel headers (aligned with data columns via fixed-width containers)
        with dpg.group(horizontal=True):
            # Leading spacer matches: Button(row_num_w) [IS=8] Spacer(4) [IS=8]
            dpg.add_spacer(width=row_num_w + 12)
            for ch in range(MAX_CHANNELS):
                with dpg.child_window(width=ch_data_w, height=50,
                                      border=False, no_scrollbar=True) as cw:
                    dpg.bind_item_theme(cw, "theme_container_nopad")
                    with dpg.group(horizontal=True):
                        cb = dpg.add_checkbox(tag=f"ch_enabled_{ch}", default_value=True,
                                         callback=C.on_channel_toggle, user_data=ch)
                        with dpg.tooltip(cb):
                            dpg.add_text(f"Channel {ch+1} Mute", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text(f"Enable/disable channel {ch+1} playback.")
                        solo_btn = dpg.add_button(tag=f"ch_solo_{ch}", label="S",
                                                  width=20, height=20,
                                                  callback=C.on_solo_click, user_data=ch)
                        with dpg.tooltip(solo_btn):
                            dpg.add_text(f"Solo Channel {ch+1}", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Solo: mute all other channels.")
                            dpg.add_text("Click again to un-solo (enable all).")
                        dpg.add_text(f"Channel {ch+1}", color=COL_CH[ch])
                    with dpg.group(horizontal=True):
                        dpg.add_text("Ptn:", color=(90,90,100))
                        ptn_items = [G.fmt(i) for i in range(len(state.song.patterns))] + ["+"]
                        combo = dpg.add_combo(tag=f"ch_ptn_combo_{ch}", items=ptn_items, default_value="00",
                                      width=55, callback=C.on_editor_pattern_change, user_data=ch)
                        with dpg.tooltip(combo):
                            dpg.add_text(f"Channel {ch+1} Pattern", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text(f"Pattern assigned to this channel.")
                            dpg.add_text("Select '+' to create new pattern.")
                if ch < MAX_CHANNELS - 1:
                    dpg.add_spacer(width=ch_spacer)
        
        # Row 2: Column headers (colored per channel, clickable to move cursor)
        with dpg.group(horizontal=True):
            hdr = dpg.add_button(label="Row", width=row_num_w, height=18, enabled=False)
            dpg.bind_item_theme(hdr, "theme_header_button")
            with dpg.tooltip(hdr):
                dpg.add_text("Row Number", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Row position in pattern.")
            dpg.add_spacer(width=4)
            for ch in range(MAX_CHANNELS):
                hdr = dpg.add_button(label="Note", width=note_w, height=18,
                                     callback=C.editor_header_click, user_data=(ch, COL_NOTE))
                dpg.bind_item_theme(hdr, f"theme_header_ch{ch}")
                with dpg.tooltip(hdr):
                    dpg.add_text(f"Channel {ch+1} - Note", color=COL_CH[ch])
                    dpg.add_separator()
                    dpg.add_text("Click to move cursor here.")
                    dpg.add_text("Enter notes with keyboard:")
                    dpg.add_text("  Z-M = lower octave (C-B)")
                    dpg.add_text("  Q-P = upper octave (C-E)")
                lbl = "Ins" if state.hex_mode else "Inst"
                hdr = dpg.add_button(label=lbl, width=inst_w, height=18,
                                     callback=C.editor_header_click, user_data=(ch, COL_INST))
                dpg.bind_item_theme(hdr, f"theme_header_ch{ch}")
                with dpg.tooltip(hdr):
                    dpg.add_text(f"Channel {ch+1} - Instrument", color=COL_CH[ch])
                    dpg.add_separator()
                    dpg.add_text("Click to move cursor here.")
                    dpg.add_text("Use [ ] keys to change.")
                if show_volume:
                    hdr = dpg.add_button(label="Vol", width=vol_w, height=18,
                                         callback=C.editor_header_click, user_data=(ch, COL_VOL))
                    dpg.bind_item_theme(hdr, f"theme_header_ch{ch}")
                    with dpg.tooltip(hdr):
                        dpg.add_text(f"Channel {ch+1} - Volume", color=COL_CH[ch])
                        dpg.add_separator()
                        dpg.add_text("Click to move cursor here.")
                        dpg.add_text("F = max, 0 = silent.")
                if ch < MAX_CHANNELS - 1:
                    dpg.add_spacer(width=ch_spacer)
        
        dpg.add_separator()
        
        # Data rows
        for vis_row in range(G.visible_rows):
            with dpg.group(horizontal=True, tag=f"editor_row_group_{vis_row}"):
                dpg.add_button(tag=f"row_num_{vis_row}", label="000", width=row_num_w, height=ROW_HEIGHT-4,
                               callback=C.editor_row_click, user_data=vis_row)
                dpg.add_spacer(width=4)
                for ch in range(MAX_CHANNELS):
                    dpg.add_button(tag=f"cell_note_{vis_row}_{ch}", label=" ---", width=note_w,
                                   height=ROW_HEIGHT-4, callback=C.cell_click, user_data=(vis_row, ch, COL_NOTE))
                    dpg.add_button(tag=f"cell_inst_{vis_row}_{ch}", label="---", width=inst_w,
                                   height=ROW_HEIGHT-4, callback=C.cell_click, user_data=(vis_row, ch, COL_INST))
                    if show_volume:
                        dpg.add_button(tag=f"cell_vol_{vis_row}_{ch}", label="--", width=vol_w,
                                       height=ROW_HEIGHT-4, callback=C.cell_click, user_data=(vis_row, ch, COL_VOL))
                    if ch < MAX_CHANNELS - 1:
                        dpg.add_spacer(width=ch_spacer)



# Height of the right-side top row (SONG + PATTERN + SONG INFO panels)
RIGHT_TOP_HEIGHT = 245


def build_main_area():
    """Build main area: [PATTERN EDITOR (left)] | [right column]
    
    Right column layout:
      Top:    [SONG grid] [PATTERN] [SONG INFO]
      Bottom: [INSTRUMENTS]
    """
    with dpg.group(horizontal=True, tag="main_area"):
        # =====================================================================
        # LEFT: Pattern Editor (full height)
        # =====================================================================
        with dpg.child_window(tag="editor_panel",
                              width=G.compute_editor_width(state.hex_mode, state.song.volume_control),
                              height=-25, border=True, no_scrollbar=True, no_scroll_with_mouse=True):
            with dpg.group(horizontal=True):
                dpg.add_text("PATTERN EDITOR")
                dpg.add_spacer(width=20)
                dpg.add_button(label="Play", width=40, callback=C.on_play_pattern_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Play Pattern", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Play current pattern from start.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('play_pattern')}")
                dpg.add_button(label="From Here", width=70, callback=C.on_play_pattern_here)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Play From Here", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Play pattern from current cursor row.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('play_stop_toggle')}")
                dpg.add_button(label="Stop", width=40, callback=C.on_stop_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Stop Playback", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Stop all audio playback.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('stop')} or Escape")
                dpg.add_spacer(width=10)
                dpg.add_checkbox(tag="follow_checkbox", label="Follow",
                                 default_value=state.follow,
                                 callback=C.on_follow_toggle)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Follow Mode", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Cursor follows playback position.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('toggle_follow')}")
            dpg.add_spacer(height=2)
            rebuild_editor_grid()
        
        # =====================================================================
        # RIGHT column
        # =====================================================================
        with dpg.child_window(tag="right_column", width=-1, height=-25,
                              border=False, no_scrollbar=True, no_scroll_with_mouse=True):

            # -----------------------------------------------------------------
            # Right TOP row: SONG | PATTERN | SONG INFO
            # -----------------------------------------------------------------
            with dpg.group(horizontal=True):
                # --- SONG panel ---
                with dpg.child_window(tag="song_panel", width=G.SONG_PANEL_WIDTH,
                                      height=RIGHT_TOP_HEIGHT, border=True,
                                      no_scrollbar=True, no_scroll_with_mouse=True):
                    with dpg.group(horizontal=True):
                        dpg.add_text("SONG")
                        dpg.add_spacer(width=10)
                        dpg.add_button(label="Play", width=40, callback=C.on_play_song_start)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Play Song", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Play from start of song.")
                            dpg.add_text(f"Keyboard: {key_config.get_combo_str('play_song')}")
                        dpg.add_button(label="Here", width=40, callback=C.on_play_song_here)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Play From Here", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Play song from current songline.")
                            dpg.add_text(f"Keyboard: {key_config.get_combo_str('play_from_cursor')}")
                        dpg.add_button(label="Stop", width=40, callback=C.on_stop_click)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Stop Playback", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Stop all audio playback.")
                    
                    dpg.add_spacer(height=2)
                    with dpg.group(horizontal=True):
                        hdr = dpg.add_button(label="Row", width=35, height=18, enabled=False)
                        dpg.bind_item_theme(hdr, "theme_header_button")
                        dpg.add_spacer(width=3)
                        for ch in range(MAX_CHANNELS):
                            hdr = dpg.add_button(label=f"C{ch+1}", width=40, height=18,
                                                 callback=C.song_header_click, user_data=ch)
                            dpg.bind_item_theme(hdr, f"theme_header_ch{ch}")
                            dpg.add_spacer(width=3)
                        hdr = dpg.add_button(label="SPD", width=30, height=18,
                                             callback=C.song_header_click, user_data=MAX_CHANNELS)
                        dpg.bind_item_theme(hdr, "theme_header_spd")
                        with dpg.tooltip(hdr):
                            dpg.add_text("Speed", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("VBLANKs per row (1-255).")
                    
                    for vis_row in range(G.SONG_VISIBLE_ROWS):
                        with dpg.group(horizontal=True, tag=f"song_row_group_{vis_row}"):
                            dpg.add_button(tag=f"song_row_num_{vis_row}", label="000", width=35,
                                           height=ROW_HEIGHT-6, callback=C.select_songline_click,
                                           user_data=vis_row)
                            dpg.add_spacer(width=3)
                            for ch in range(MAX_CHANNELS):
                                dpg.add_button(tag=f"song_cell_{vis_row}_{ch}", label="000", width=40,
                                               height=ROW_HEIGHT-6, callback=C.song_cell_click,
                                               user_data=(vis_row, ch))
                                dpg.add_spacer(width=3)
                            dpg.add_button(tag=f"song_spd_{vis_row}", label="06", width=30,
                                           height=ROW_HEIGHT-6, callback=C.song_spd_click,
                                           user_data=vis_row)
                    
                    dpg.add_spacer(height=3)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Add", width=35, callback=C.on_add_songline_btn)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Add Songline", color=(255, 255, 150))
                        dpg.add_button(label="Clone", width=45, callback=C.on_clone_songline_btn)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Clone Songline", color=(255, 255, 150))
                        dpg.add_button(label="Del", width=35, callback=on_delete_songline_confirm)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Delete Songline", color=(255, 255, 150))
                        dpg.add_button(label="Up", width=30, callback=C.on_move_songline_up)
                        dpg.add_button(label="Dn", width=30, callback=C.on_move_songline_down)
                
                # --- PATTERN panel ---
                with dpg.child_window(tag="pattern_panel", width=150,
                                      height=RIGHT_TOP_HEIGHT, border=True):
                    dpg.add_text("PATTERN")
                    with dpg.group(horizontal=True):
                        dpg.add_text("Selected:")
                        ptn_items = [G.fmt(i) for i in range(len(state.song.patterns))] + ["+"]
                        dpg.add_combo(tag="ptn_select_combo", items=ptn_items, default_value="00",
                                      width=50, callback=C.on_pattern_select)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Pattern Selector", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Choose pattern to edit.")
                            dpg.add_text("Select '+' to create new.")
                    dpg.add_spacer(height=3)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Length:")
                        inp = dpg.add_input_text(tag="ptn_len_input", default_value="64",
                                                 width=50, callback=C.on_ptn_len_change, on_enter=True)
                        with dpg.tooltip(inp):
                            dpg.add_text("Pattern Length", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text(f"Number of rows (1-{MAX_ROWS}).")
                        with dpg.item_handler_registry() as h:
                            dpg.add_item_activated_handler(callback=G.on_input_focus)
                            dpg.add_item_deactivated_handler(callback=G.on_input_blur)
                        dpg.bind_item_handler_registry(inp, h)
                    dpg.add_spacer(height=8)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Add", width=40, callback=ops.add_pattern)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Add Pattern", color=(255, 255, 150))
                        dpg.add_button(label="Clone", width=45, callback=ops.clone_pattern)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Clone Pattern", color=(255, 255, 150))
                        dpg.add_button(label="Del", width=35, callback=on_delete_pattern_confirm)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Delete Pattern", color=(255, 255, 150))
                
                # --- SONG INFO panel ---
                with dpg.child_window(tag="info_panel", width=-1,
                                      height=RIGHT_TOP_HEIGHT, border=True):
                    dpg.add_text("SONG INFO")
                    with dpg.group(horizontal=True):
                        dpg.add_text("Title: ")
                        inp = dpg.add_input_text(tag="title_input", default_value=state.song.title,
                                                 width=-1, callback=lambda s,v: setattr(state.song, 'title', v))
                        with dpg.item_handler_registry() as h:
                            dpg.add_item_activated_handler(callback=G.on_input_focus)
                            dpg.add_item_deactivated_handler(callback=G.on_input_blur)
                        dpg.bind_item_handler_registry(inp, h)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Author:")
                        inp = dpg.add_input_text(tag="author_input", default_value=state.song.author,
                                                 width=-1, callback=lambda s,v: setattr(state.song, 'author', v))
                        with dpg.item_handler_registry() as h:
                            dpg.add_item_activated_handler(callback=G.on_input_focus)
                            dpg.add_item_deactivated_handler(callback=G.on_input_blur)
                        dpg.bind_item_handler_registry(inp, h)
                    dpg.add_spacer(height=3)
                    with dpg.group(horizontal=True):
                        dpg.add_text("System:")
                        sys_combo = dpg.add_combo(items=["PAL", "NTSC"], default_value="PAL",
                                                  width=65, callback=C.on_system_change)
                        with dpg.tooltip(sys_combo):
                            dpg.add_text("Target System", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("PAL = 50Hz  NTSC = 60Hz")
                        dpg.add_spacer(width=5)
                        dpg.add_text("Start: $")
                        start_inp = dpg.add_input_text(tag="start_address_input",
                                           default_value=f"{state.song.start_address:04X}",
                                           hexadecimal=True, uppercase=True,
                                           width=45, callback=C.on_start_address_change)
                        with dpg.tooltip(start_inp):
                            dpg.add_text("Code Start Address", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("$2000 = safe default")
                            dpg.add_text("$0800 = aggressive (+6 KB)")
                        with dpg.item_handler_registry() as h:
                            dpg.add_item_activated_handler(callback=G.on_input_focus)
                            dpg.add_item_deactivated_handler(callback=G.on_input_blur)
                        dpg.bind_item_handler_registry(start_inp, h)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Memory:")
                        mem_combo = dpg.add_combo(tag="memory_config_combo",
                                                 items=MEMORY_CONFIG_NAMES,
                                                 default_value=state.song.memory_config,
                                                 width=90, callback=C.on_memory_config_change)
                        with dpg.tooltip(mem_combo):
                            dpg.add_text("Target Memory Size", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("64 KB = no ext. RAM")
                            dpg.add_text("128 KB = 130XE (4 banks)")
                            dpg.add_text("320-1088 KB = expanded")
                        dpg.add_spacer(width=5)
                        dpg.add_checkbox(tag="volume_control_cb", label="Vol",
                                        default_value=state.song.volume_control,
                                        callback=C.on_volume_control_toggle)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Volume Control", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Enable per-note volume in export.")
                        dpg.add_checkbox(tag="screen_control_cb", label="Screen",
                                        default_value=state.song.screen_control,
                                        callback=C.on_screen_control_toggle)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Screen Control", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Show display during playback.")
                        dpg.add_checkbox(tag="keyboard_control_cb", label="Key",
                                        default_value=state.song.keyboard_control,
                                        callback=C.on_keyboard_control_toggle)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Keyboard Control", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Enable stop/restart keys on Atari.")
                    dpg.add_spacer(height=3)
                    with dpg.group(horizontal=True):
                        dpg.add_button(tag="build_btn", label="BUILD & RUN", width=100,
                                       callback=C.on_build_click)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Build & Run in Emulator", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Validates, creates .XEX, launches emulator.")
                        dpg.add_spacer(width=5)
                        dpg.add_button(label="RESET", width=50, callback=C.on_reset_song)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text("Reset Song", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text("Clear all song data. Instruments kept.")
                        dpg.add_spacer(width=5)
                        dpg.add_text(tag="build_status_label", default_value="", color=COL_DIM)

                    # VU meters: 4 vertical bars at bottom of SONG INFO
                    dpg.add_spacer(height=4)
                    dpg.add_drawlist(tag="vu_drawlist", width=-1, height=55)
            
            dpg.add_spacer(height=2)
            
            # -----------------------------------------------------------------
            # Right BOTTOM: INSTRUMENTS
            # -----------------------------------------------------------------
            with dpg.child_window(tag="inst_panel", height=-1, border=True):
                dpg.add_text("INSTRUMENTS")
                with dpg.child_window(tag="instlist", height=-130, border=False):
                    pass
                with dpg.group(horizontal=True):
                    dpg.add_button(tag="inst_add_btn", label="Add", width=35, callback=ops.add_sample)
                    dpg.bind_item_theme("inst_add_btn", "theme_btn_blink_bright")
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Add Sample", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Browse and select audio files.")
                    dpg.add_button(tag="inst_folder_btn", label="Folder", width=50, callback=ops.add_folder)
                    dpg.bind_item_theme("inst_folder_btn", "theme_btn_blink_bright")
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Add Folder", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Import all samples from folder.")
                    dpg.add_button(tag="inst_edit_btn", label="Edit", width=38, callback=C.on_edit_instrument)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Sample Editor", color=(255, 255, 150))
                    dpg.add_button(label="Replace", width=55, callback=ops.replace_instrument)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Replace Sample", color=(255, 255, 150))
                    dpg.add_button(label="Rename", width=55, callback=ops.rename_instrument)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Rename Instrument", color=(255, 255, 150))
                    dpg.add_button(label="Delete", width=50, callback=ops.remove_instrument)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Delete Instrument", color=(255, 255, 150))
                    dpg.add_button(label="Clone", width=45, callback=ops.clone_instrument)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Clone Instrument", color=(255, 255, 150))
                    dpg.add_button(label="Up", width=30, callback=C.on_move_inst_up)
                    dpg.add_button(label="Down", width=40, callback=C.on_move_inst_down)
                    dpg.add_button(label="RESET", width=55, callback=ops.reset_all_instruments)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Reset Instruments", color=(255, 255, 150))
                
                # VQ Conversion Controls
                dpg.add_separator()
                dpg.add_spacer(height=3)
                
                with dpg.group(horizontal=True):
                    dpg.add_text("Rate:")
                    rate_items = [f"{r} Hz" for r in VQ_RATES]
                    default_rate = f"{VQ_RATE_DEFAULT} Hz"
                    dpg.add_combo(tag="vq_rate_combo", items=rate_items, default_value=default_rate,
                                  width=90, callback=C.on_vq_setting_change)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("POKEY Sample Rate", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Playback rate on Atari hardware.")
                        dpg.add_text("Higher = better quality, more CPU.")
                    
                    dpg.add_spacer(width=8)
                    dpg.add_text("Vec:")
                    vec_items = [str(v) for v in VQ_VECTOR_SIZES]
                    dpg.add_combo(tag="vq_vector_combo", items=vec_items,
                                  default_value=str(VQ_VECTOR_DEFAULT),
                                  width=50, callback=C.on_vq_setting_change)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Vector Size", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Smaller = better quality, more CPU.")
                        dpg.add_text("Default: 8 (good balance)")
                    
                    dpg.add_spacer(width=8)
                    dpg.add_text("Smooth:")
                    smooth_items = [str(v) for v in VQ_SMOOTHNESS_VALUES]
                    dpg.add_combo(tag="vq_smooth_combo", items=smooth_items,
                                  default_value=str(VQ_SMOOTHNESS_DEFAULT),
                                  width=50, callback=C.on_vq_setting_change)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Smoothness (0-100)", color=(255, 255, 150))
                    
                    dpg.add_spacer(width=8)
                    dpg.add_checkbox(tag="vq_enhance_cb", label="Enhance", default_value=True,
                                     callback=C.on_vq_setting_change)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Audio Enhancement", color=(255, 255, 150))
                    
                    dpg.add_spacer(width=8)
                    dpg.add_checkbox(tag="vq_used_only_cb", label="Used Samples",
                                     default_value=False,
                                     callback=C.on_used_only_change)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Convert Used Samples Only", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Only process instruments used in song.")
                
                dpg.add_spacer(height=3)
                
                with dpg.group(horizontal=True):
                    dpg.add_button(tag="vq_optimize_btn", label="OPTIMIZE", width=80,
                                   callback=C.on_optimize_click)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Optimize RAW/VQ per Instrument", color=(255, 255, 150))
                    
                    dpg.add_spacer(width=5)
                    
                    dpg.add_button(tag="vq_convert_btn", label="CONVERT", width=80,
                                   callback=C.on_vq_convert_click)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Convert Instruments to VQ", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Required before BUILD.")
                    
                    dpg.add_spacer(width=15)
                    dpg.add_text(tag="vq_size_label", default_value="", color=COL_DIM)
                    
                    dpg.add_spacer(width=15)
                    dpg.add_checkbox(tag="vq_use_converted_cb", label="Use converted",
                                     default_value=False, enabled=False,
                                     callback=C.on_vq_use_converted_change)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Preview Converted Samples", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Hear how it will sound on Atari.")

def build_status_bar():
    """Build the status bar."""
    with dpg.group(horizontal=True):
        dpg.add_text(tag="status_text", default_value="Ready", color=(150, 200, 150))
        dpg.add_spacer(width=20)
        dpg.add_text(tag="validation_indicator", default_value="", color=(100, 200, 100))
        with dpg.tooltip("validation_indicator"):
            dpg.add_text("Song Validation Status", color=(255, 255, 150))
            dpg.add_separator()
            dpg.add_text(tag="validation_tooltip_text", default_value="Validated automatically when BUILD is clicked")
        dpg.add_spacer(width=20)
        dpg.add_text(tag="focus_indicator", default_value="Focus: EDITOR", color=(100, 150, 200))



def build_ui():
    """Build the main UI."""
    with dpg.window(tag="main_window", no_scrollbar=True):
        build_menu()
        dpg.add_spacer(height=2)
        build_input_row()
        dpg.add_spacer(height=2)
        build_main_area()
        build_status_bar()
    _bind_panel_focus_handlers()


def _bind_panel_focus_handlers():
    """Bind focus detection to panels.
    
    Note: DPG child_windows don't support mvClickedHandler, so panel
    focus switching is handled by on_global_mouse_click() in ui_callbacks.py
    using is_item_hovered(). This function exists as a hook for any future
    panel-specific handlers that DO work on child_windows.
    """
    pass  # Focus detection via global mouse handler
