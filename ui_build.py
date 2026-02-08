"""POKEY VQ Tracker - UI Building Functions"""
import dearpygui.dearpygui as dpg
from constants import (MAX_CHANNELS, MAX_VOLUME, MAX_ROWS, ROW_HEIGHT, COL_CH,
                       COL_NOTE, COL_INST, COL_VOL, COL_DIM,
                       VQ_RATES, VQ_RATE_DEFAULT, VQ_VECTOR_SIZES, VQ_VECTOR_DEFAULT,
                       VQ_SMOOTHNESS_VALUES, VQ_SMOOTHNESS_DEFAULT)
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


def on_exit():
    import logging
    logger = logging.getLogger("tracker.main")
    logger.info("Exiting...")
    if G.autosave_enabled and state.song.modified:
        G.do_autosave()
    G.save_config()
    dpg.stop_dearpygui()


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
            dpg.add_menu_item(label="Import vq_converter...", callback=ops.import_vq_converter)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Import vq_converter", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Load instruments from a vq_converter")
                dpg.add_text("conversion_info.json file.")
            dpg.add_menu_item(label="Export .ASM...", callback=ops.export_asm_files)
            dpg.add_separator()
            dpg.add_menu_item(label="Exit", callback=on_exit)
        
        with dpg.menu(label="Edit"):
            dpg.add_menu_item(label="Undo", callback=ops.undo, shortcut="Ctrl+Z")
            dpg.add_menu_item(label="Redo", callback=ops.redo, shortcut="Ctrl+Y")
            dpg.add_separator()
            dpg.add_menu_item(label="Copy", callback=ops.copy_cells, shortcut="Ctrl+C")
            dpg.add_menu_item(label="Cut", callback=ops.cut_cells, shortcut="Ctrl+X")
            dpg.add_menu_item(label="Paste", callback=ops.paste_cells, shortcut="Ctrl+V")
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
        
        with dpg.menu(label="Help"):
            dpg.add_menu_item(label="Keyboard Shortcuts", callback=show_shortcuts, shortcut="F1")
            dpg.add_separator()
            dpg.add_menu_item(label="About", callback=show_about)


def build_top_row():
    """Build the top row: [SONG] | [PATTERN] | [SETTINGS] | [SONG INFO]"""
    with dpg.group(horizontal=True):
        # SONG panel
        with dpg.child_window(tag="song_panel", width=G.SONG_PANEL_WIDTH, height=G.TOP_PANEL_HEIGHT, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("SONG")
                dpg.add_spacer(width=10)
                dpg.add_button(label="Play", width=40, callback=C.on_play_song_start)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Play Song", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Play from start of song.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('play_song')}")
                dpg.add_button(label="From Here", width=70, callback=C.on_play_song_here)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Play From Here", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Play from current songline.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('play_from_cursor')}")
                dpg.add_button(label="Stop", width=40, callback=C.on_stop_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Stop Playback", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Stop all audio playback.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('stop')} or Escape")
            
            dpg.add_spacer(height=2)
            with dpg.group(horizontal=True):
                hdr = dpg.add_button(label="Row", width=35, height=18, enabled=False)
                dpg.bind_item_theme(hdr, "theme_header_button")
                dpg.add_spacer(width=3)
                for ch in range(MAX_CHANNELS):
                    hdr = dpg.add_button(label=f"C{ch+1}", width=40, height=18, enabled=False)
                    dpg.bind_item_theme(hdr, f"theme_header_ch{ch}")
                    dpg.add_spacer(width=3)
                hdr = dpg.add_button(label="SPD", width=30, height=18, enabled=False)
                dpg.bind_item_theme(hdr, "theme_header_spd")
                with dpg.tooltip(hdr):
                    dpg.add_text("Speed", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("VBLANKs per row (1-255).")
                    dpg.add_text("Lower = faster playback.")
            
            for vis_row in range(G.SONG_VISIBLE_ROWS):
                with dpg.group(horizontal=True, tag=f"song_row_group_{vis_row}"):
                    dpg.add_button(tag=f"song_row_num_{vis_row}", label="000", width=35, height=ROW_HEIGHT-6,
                                   callback=C.select_songline_click, user_data=vis_row)
                    dpg.add_spacer(width=3)
                    for ch in range(MAX_CHANNELS):
                        dpg.add_button(tag=f"song_cell_{vis_row}_{ch}", label="000", width=40, height=ROW_HEIGHT-6,
                                       callback=C.song_cell_click, user_data=(vis_row, ch))
                        dpg.add_spacer(width=3)
                    # SPD cell
                    dpg.add_button(tag=f"song_spd_{vis_row}", label="06", width=30, height=ROW_HEIGHT-6,
                                   callback=C.song_spd_click, user_data=vis_row)
            
            dpg.add_spacer(height=3)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Add", width=35, callback=C.on_add_songline_btn)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Add Songline", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Insert new row in song arrangement.")
                    dpg.add_text("Patterns default to 00.")
                dpg.add_button(label="Clone", width=45, callback=C.on_clone_songline_btn)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Clone Songline", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Duplicate current songline below.")
                    dpg.add_text("Same patterns, same speed.")
                dpg.add_button(label="Del", width=35, callback=on_delete_songline_confirm)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Delete Songline", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Remove current songline.")
                    dpg.add_text("Patterns are NOT deleted.")
                dpg.add_button(label="Up", width=30, callback=C.on_move_songline_up)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Move Up", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Move songline up in arrangement.")
                dpg.add_button(label="Down", width=40, callback=C.on_move_songline_down)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Move Down", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Move songline down in arrangement.")
        
        # PATTERN panel
        with dpg.child_window(tag="pattern_panel", width=155, height=G.TOP_PANEL_HEIGHT, border=True):
            dpg.add_text("PATTERN")
            with dpg.group(horizontal=True):
                dpg.add_text("Selected:")
                ptn_items = [G.fmt(i) for i in range(len(state.song.patterns))] + ["+"]
                dpg.add_combo(tag="ptn_select_combo", items=ptn_items, default_value="00",
                              width=50, callback=C.on_pattern_select)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Pattern Selector", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Choose pattern to edit in the grid.")
                    dpg.add_text("Select '+' to create new pattern.")
            dpg.add_spacer(height=3)
            with dpg.group(horizontal=True):
                dpg.add_text("Length:")
                # Use text input to support hex/decimal display based on mode
                inp = dpg.add_input_text(tag="ptn_len_input", default_value="64",
                                         width=50, callback=C.on_ptn_len_change, on_enter=True)
                with dpg.tooltip(inp):
                    dpg.add_text("Pattern Length", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text(f"Number of rows in pattern (1-{MAX_ROWS}).")
                    dpg.add_text("Common values: 32, 64, 128")
                    dpg.add_text("Enter hex or decimal based on mode.")
                with dpg.item_handler_registry() as h:
                    dpg.add_item_activated_handler(callback=G.on_input_focus)
                    dpg.add_item_deactivated_handler(callback=G.on_input_blur)
                dpg.bind_item_handler_registry(inp, h)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Add", width=40, callback=ops.add_pattern)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Add Pattern", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Create new empty pattern.")
                dpg.add_button(label="Clone", width=45, callback=ops.clone_pattern)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Clone Pattern", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Duplicate selected pattern")
                    dpg.add_text("including all notes.")
                dpg.add_button(label="Del", width=35, callback=on_delete_pattern_confirm)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Delete Pattern", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Remove selected pattern.")
                    dpg.add_text("Songlines using it will be cleared.", color=(255, 150, 150))
        
        # SETTINGS panel (wider for new options)
        with dpg.child_window(width=145, height=G.TOP_PANEL_HEIGHT, border=True):
            dpg.add_text("SETTINGS")
            dpg.add_checkbox(tag="hex_mode_cb", label="Hex mode", default_value=state.hex_mode, callback=C.on_hex_toggle)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Hexadecimal Mode", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Display all numbers in hexadecimal.")
                dpg.add_text("Useful for Atari programming.")
            dpg.add_checkbox(tag="autosave_cb", label="Auto-save", default_value=G.autosave_enabled,
                             callback=C.on_autosave_toggle)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Auto-save", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Automatically save backup every 60 seconds.")
                dpg.add_text("Prevents data loss on crash.")
            
            # Piano vs Tracker key mode
            dpg.add_checkbox(tag="piano_keys_cb", label="Piano keys", default_value=G.piano_keys_mode,
                             callback=C.on_piano_keys_toggle)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Keyboard Style", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Piano mode (ON):")
                dpg.add_text("  2,3,5,6,7,9,0 play sharps")
                dpg.add_spacer(height=3)
                dpg.add_text("Tracker mode (OFF):")
                dpg.add_text("  1 = Note-OFF, 2-3 = Octave")
                dpg.add_spacer(height=3)
                dpg.add_text("F1-F3 always select octave.", color=(150, 200, 150))
            
            # Row highlight interval
            dpg.add_spacer(height=3)
            with dpg.group(horizontal=True):
                dpg.add_text("Rows:")
                dpg.add_combo(tag="highlight_combo", items=["2", "4", "8", "16"],
                              default_value=str(G.highlight_interval), width=45,
                              callback=C.on_highlight_change)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Row Highlight Interval", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Highlight every N rows for")
                dpg.add_text("visual beat reference.")
                dpg.add_text("Common: 4 (4/4 time)")
        
        # SONG INFO panel (expandable to fill remaining space)
        with dpg.child_window(tag="info_panel", width=-1, height=G.TOP_PANEL_HEIGHT, border=True):
            dpg.add_text("SONG INFO")
            with dpg.group(horizontal=True):
                dpg.add_text("Title: ")
                inp = dpg.add_input_text(tag="title_input", default_value=state.song.title,
                                         width=-1, callback=lambda s,v: setattr(state.song, 'title', v))
                with dpg.tooltip(inp):
                    dpg.add_text("Song Title", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Name of your composition.")
                    dpg.add_text("Stored in the exported file.")
                with dpg.item_handler_registry() as h:
                    dpg.add_item_activated_handler(callback=G.on_input_focus)
                    dpg.add_item_deactivated_handler(callback=G.on_input_blur)
                dpg.bind_item_handler_registry(inp, h)
            with dpg.group(horizontal=True):
                dpg.add_text("Author:")
                inp = dpg.add_input_text(tag="author_input", default_value=state.song.author,
                                         width=-1, callback=lambda s,v: setattr(state.song, 'author', v))
                with dpg.tooltip(inp):
                    dpg.add_text("Composer Name", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Your name or alias.")
                    dpg.add_text("Stored in the exported file.")
                with dpg.item_handler_registry() as h:
                    dpg.add_item_activated_handler(callback=G.on_input_focus)
                    dpg.add_item_deactivated_handler(callback=G.on_input_blur)
                dpg.bind_item_handler_registry(inp, h)
            dpg.add_spacer(height=3)
            with dpg.group(horizontal=True):
                dpg.add_text("System:")
                sys_combo = dpg.add_combo(items=["PAL", "NTSC"], default_value="PAL", width=70, callback=C.on_system_change)
                with dpg.tooltip(sys_combo):
                    dpg.add_text("Target System", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("PAL = 50Hz (Europe, Australia)")
                    dpg.add_text("NTSC = 60Hz (USA, Japan)")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Affects timing and playback speed.")
                dpg.add_spacer(width=10)
                dpg.add_checkbox(tag="volume_control_cb", label="Vol", 
                                default_value=state.song.volume_control,
                                callback=C.on_volume_control_toggle)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Volume Control", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Enable per-note volume in export.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("When DISABLED (default):", color=(100, 255, 100))
                    dpg.add_text("  Saves ~13 cycles/channel")
                    dpg.add_text("  Volume column hidden")
                    dpg.add_spacer(height=3)
                    dpg.add_text("When ENABLED:", color=(255, 200, 150))
                    dpg.add_text("  Requires sample rate â‰¤5757 Hz")
                    dpg.add_text("  Volume data preserved & used")
                dpg.add_spacer(width=10)
                dpg.add_checkbox(tag="screen_control_cb", label="Screen", 
                                default_value=state.song.screen_control,
                                callback=C.on_screen_control_toggle)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Screen Control", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Enable display during playback.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("When DISABLED (default):", color=(100, 255, 100))
                    dpg.add_text("  ~15% more CPU cycles for IRQ")
                    dpg.add_text("  Screen blanked during playback")
                    dpg.add_spacer(height=3)
                    dpg.add_text("When ENABLED:", color=(255, 200, 150))
                    dpg.add_text("  Shows SONG/ROW/SPD during play")
                    dpg.add_text("  Costs ~15% CPU (ANTIC DMA)")
                dpg.add_spacer(width=10)
                dpg.add_checkbox(tag="keyboard_control_cb", label="Key", 
                                default_value=state.song.keyboard_control,
                                callback=C.on_keyboard_control_toggle)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Keyboard Control", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Enable stop/restart keys during play.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("When DISABLED (default):", color=(100, 255, 100))
                    dpg.add_text("  Saves CPU cycles (no key scan)")
                    dpg.add_text("  Press SPACE to start, plays once")
                    dpg.add_spacer(height=3)
                    dpg.add_text("When ENABLED:", color=(255, 200, 150))
                    dpg.add_text("  SPACE = play/stop toggle")
                    dpg.add_text("  R = restart from beginning")
                dpg.add_spacer(width=10)
                dpg.add_button(label="RESET", width=60, callback=C.on_reset_song)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Reset Song", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Clear all song data and start fresh.")
                    dpg.add_text("Instruments are kept.")
            
            # ANALYZE and BUILD buttons
            # ANALYZE: Check timing feasibility before export
            # BUILD & RUN: Validates song, creates executable, launches emulator
            dpg.add_spacer(height=5)
            with dpg.group(horizontal=True):
                dpg.add_button(tag="analyze_btn", label="ANALYZE", width=80, callback=C.on_analyze_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Analyze Timing", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Simulates Atari IRQ timing to")
                    dpg.add_text("detect potential playback issues.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Checks:", color=(255, 200, 150))
                    dpg.add_text("  â€¢ Cycle budget per row")
                    dpg.add_text("  â€¢ Boundary crossing costs")
                    dpg.add_text("  â€¢ Volume control feasibility")
                dpg.add_spacer(width=5)
                dpg.add_button(tag="build_btn", label="BUILD & RUN", width=100, callback=C.on_build_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Build & Run in Emulator", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Validates song, creates .XEX file,")
                    dpg.add_text("and launches it in the emulator.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Validation checks:", color=(200, 200, 255))
                    dpg.add_text("  â€¢ Pattern lengths (max 254)")
                    dpg.add_text("  â€¢ Notes, instruments, volume")
                    dpg.add_text("  â€¢ Samples loaded & converted")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Requirements:", color=(255, 200, 150))
                    dpg.add_text("  1. Click CONVERT first")
                    dpg.add_text("  2. Song must have patterns/notes")
                dpg.add_spacer(width=10)
                dpg.add_text(tag="build_status_label", default_value="", color=COL_DIM)


def build_input_row():
    """Build the CURRENT section - brush settings."""
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
    
    with dpg.group(tag="editor_content", parent="editor_panel"):
        # Row 1: Channel headers
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=row_num_w + 8)
            for ch in range(MAX_CHANNELS):
                with dpg.group():
                    with dpg.group(horizontal=True):
                        cb = dpg.add_checkbox(tag=f"ch_enabled_{ch}", default_value=True,
                                         callback=C.on_channel_toggle, user_data=ch)
                        with dpg.tooltip(cb):
                            dpg.add_text(f"Channel {ch+1} Mute", color=(255, 255, 150))
                            dpg.add_separator()
                            dpg.add_text(f"Enable/disable channel {ch+1} playback.")
                        dpg.add_text(f"Channel {ch+1}", color=COL_CH[ch])
                    with dpg.group(horizontal=True):
                        dpg.add_text("Pattern:", color=(90,90,100))
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
        
        # Row 2: Column headers
        with dpg.group(horizontal=True):
            hdr = dpg.add_button(label="Row", width=row_num_w, height=18, enabled=False)
            dpg.bind_item_theme(hdr, "theme_header_button")
            with dpg.tooltip(hdr):
                dpg.add_text("Row Number", color=(255, 255, 150))
                dpg.add_separator()
                dpg.add_text("Row position in pattern.")
            dpg.add_spacer(width=4)
            for ch in range(MAX_CHANNELS):
                hdr = dpg.add_button(label="Note", width=note_w, height=18, enabled=False)
                dpg.bind_item_theme(hdr, "theme_header_button")
                with dpg.tooltip(hdr):
                    dpg.add_text("Note Column", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Enter notes with keyboard:")
                    dpg.add_text("  Z-M = lower octave (C-B)")
                    dpg.add_text("  Q-P = upper octave (C-E)")
                lbl = "Ins" if state.hex_mode else "Inst"
                hdr = dpg.add_button(label=lbl, width=inst_w, height=18, enabled=False)
                dpg.bind_item_theme(hdr, "theme_header_button")
                with dpg.tooltip(hdr):
                    dpg.add_text("Instrument Column", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Click to select instrument.")
                    dpg.add_text("Use [ ] keys to change.")
                if show_volume:
                    hdr = dpg.add_button(label="Vol", width=vol_w, height=18, enabled=False)
                    dpg.bind_item_theme(hdr, "theme_header_button")
                    with dpg.tooltip(hdr):
                        dpg.add_text("Volume Column", color=(255, 255, 150))
                        dpg.add_separator()
                        dpg.add_text("Click to select volume (0-15).")
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


def build_bottom_row():
    """Build the bottom row: [PATTERN EDITOR] | [INSTRUMENTS]"""
    with dpg.group(horizontal=True, tag="bottom_row"):
        # PATTERN EDITOR
        with dpg.child_window(tag="editor_panel", width=G.EDITOR_WIDTH, height=-25, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("PATTERN EDITOR")
                dpg.add_spacer(width=20)
                dpg.add_button(label="Play Pattern", width=95, callback=C.on_play_pattern_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Play Pattern", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Play current pattern from start.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('play_pattern')}")
                dpg.add_spacer(width=10)
                dpg.add_button(label="Stop", width=45, callback=C.on_stop_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Stop Playback", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Stop all audio playback.")
                    dpg.add_text(f"Keyboard: {key_config.get_combo_str('stop')} or Escape")
            dpg.add_spacer(height=2)
            rebuild_editor_grid()
        
        # INSTRUMENTS
        with dpg.child_window(tag="inst_panel", height=-25, border=True):
            dpg.add_text("INSTRUMENTS")
            with dpg.child_window(tag="instlist", height=-130, border=False):
                pass
            with dpg.group(horizontal=True):
                # Add/Folder buttons start with blink theme (no samples yet)
                dpg.add_button(tag="inst_add_btn", label="Add", width=35, callback=ops.add_sample)
                dpg.bind_item_theme("inst_add_btn", "theme_btn_blink_bright")
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Add Sample", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Browse and select audio files.")
                    dpg.add_text("Preview before adding!")
                    dpg.add_text("Multi-select supported.")
                dpg.add_button(tag="inst_folder_btn", label="Folder", width=50, callback=ops.add_folder)
                dpg.bind_item_theme("inst_folder_btn", "theme_btn_blink_bright")
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Add Folder", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Select folders containing audio files.")
                    dpg.add_text("All samples inside will be imported.")
                    dpg.add_text("Great for sample packs!")
                dpg.add_button(label="Repl", width=38, callback=ops.replace_instrument)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Replace Sample", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Replace selected instrument's audio")
                    dpg.add_text("with a different file.")
                    dpg.add_text("Keeps position and pattern data.")
                dpg.add_button(label="Rename", width=55, callback=ops.rename_instrument)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Rename Instrument", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Change the name of selected instrument.")
                dpg.add_button(label="Delete", width=50, callback=ops.remove_instrument)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Delete Instrument", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Remove selected instrument from list.")
                    dpg.add_text("Pattern data using it will be cleared.", color=(255, 150, 150))
                dpg.add_button(label="Up", width=30, callback=C.on_move_inst_up)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Move Up", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Move selected instrument up in list.")
                    dpg.add_text("Changes instrument numbers in patterns.")
                dpg.add_button(label="Down", width=40, callback=C.on_move_inst_down)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Move Down", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Move selected instrument down in list.")
                    dpg.add_text("Changes instrument numbers in patterns.")
                dpg.add_button(label="RESET", width=55, callback=ops.reset_all_instruments)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Reset Instruments", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Remove ALL instruments from list.")
                    dpg.add_text("Useful if wrong folder was imported.")
            
            # VQ Conversion Controls
            dpg.add_separator()
            dpg.add_spacer(height=3)
            
            # Rate, Vector, Smoothness row
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
                    dpg.add_text("Higher = better audio quality, more CPU.")
                    dpg.add_text("Lower = less CPU, reduced frequency range.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Max rate depends on Optimize mode:", color=(200, 200, 255))
                    dpg.add_text("  Speed mode: up to 6011 Hz (4 ch)")
                    dpg.add_text("  Size mode:  up to 4729 Hz (4 ch)")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Default: 4524 Hz (safe for both modes)", color=(150, 200, 150))
                
                dpg.add_spacer(width=8)
                dpg.add_text("Vec:")
                vec_items = [str(v) for v in VQ_VECTOR_SIZES]
                dpg.add_combo(tag="vq_vector_combo", items=vec_items, default_value=str(VQ_VECTOR_DEFAULT),
                              width=50, callback=C.on_vq_setting_change)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Vector Size (samples per pattern)", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Controls compression granularity.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Smaller (2-4):", color=(150, 255, 150))
                    dpg.add_text("  + Best quality, sharpest attack")
                    dpg.add_text("  - More CPU (frequent boundary cross)")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Larger (8-16):", color=(255, 200, 150))
                    dpg.add_text("  + Less CPU, smaller file size")
                    dpg.add_text("  - Slightly softer transients")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Default: 8 (good balance)", color=(150, 200, 150))
                
                dpg.add_spacer(width=8)
                dpg.add_text("Smooth:")
                smooth_items = [str(v) for v in VQ_SMOOTHNESS_VALUES]
                dpg.add_combo(tag="vq_smooth_combo", items=smooth_items, default_value=str(VQ_SMOOTHNESS_DEFAULT),
                              width=50, callback=C.on_vq_setting_change)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Smoothness (0-100)", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Reduces clicking/popping artifacts")
                    dpg.add_text("by penalizing sudden jumps between vectors.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("0 = No smoothing (pure quality)")
                    dpg.add_text("20-50 = Light smoothing (try if clicking)")
                    dpg.add_text("100 = Maximum smoothing")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Recommended: 0 (default)", color=(150, 200, 150))
                
                dpg.add_spacer(width=8)
                dpg.add_checkbox(tag="vq_enhance_cb", label="Enhance", default_value=True,
                                 callback=C.on_vq_setting_change)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Audio Enhancement", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Apply preprocessing to improve quality:")
                    dpg.add_text("  - Normalization")
                    dpg.add_text("  - Noise reduction")
                    dpg.add_text("  - Frequency optimization for POKEY")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Recommended: ON", color=(150, 200, 150))
            
            # Second row: Optimize mode
            with dpg.group(horizontal=True):
                dpg.add_text("Optimize:")
                dpg.add_combo(tag="vq_optimize_combo", items=["Speed", "Size"], 
                              default_value="Speed", width=70, callback=C.on_vq_setting_change)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("IRQ Optimization Mode", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Controls CPU usage vs memory trade-off:")
                    dpg.add_spacer(height=5)
                    dpg.add_text("SPEED (recommended):", color=(100, 255, 100))
                    dpg.add_text("  + ~58 cycles/channel (fast!)")
                    dpg.add_text("  + Enables 6011 Hz sample rate")
                    dpg.add_text("  + Smoother playback")
                    dpg.add_text("  - 2x codebook memory (4KB)")
                    dpg.add_spacer(height=5)
                    dpg.add_text("SIZE:", color=(255, 200, 100))
                    dpg.add_text("  + Compact codebook (2KB)")
                    dpg.add_text("  - ~83 cycles/channel (slower)")
                    dpg.add_text("  - Max 4729 Hz for 4 channels")
                    dpg.add_spacer(height=5)
                    dpg.add_text("Max Rate with 4 Channels:", color=(200, 200, 255))
                    dpg.add_text("  Speed mode: 6011 Hz")
                    dpg.add_text("  Size mode:  4729 Hz")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Recommended: Speed", color=(150, 200, 150))
            
            dpg.add_spacer(height=3)
            
            # Convert button and status row
            with dpg.group(horizontal=True):
                dpg.add_button(tag="vq_convert_btn", label="CONVERT", width=80, 
                               callback=C.on_vq_convert_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Convert Instruments to VQ", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("Converts all loaded instruments to")
                    dpg.add_text("POKEY-compatible VQ format using")
                    dpg.add_text("the settings above.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("This prepares samples for Atari playback.")
                    dpg.add_text("Required before BUILD.", color=(255, 200, 150))
                
                dpg.add_spacer(width=15)
                dpg.add_text(tag="vq_size_label", default_value="", color=COL_DIM)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Total size of converted VQ data")
                
                dpg.add_spacer(width=15)
                dpg.add_checkbox(tag="vq_use_converted_cb", label="Use converted", 
                                 default_value=False, enabled=False,
                                 callback=C.on_vq_use_converted_change)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Preview Converted Samples", color=(255, 255, 150))
                    dpg.add_separator()
                    dpg.add_text("When checked, note preview uses the")
                    dpg.add_text("converted (VQ compressed) samples.")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Unchecked = Original WAV quality")
                    dpg.add_text("Checked = Atari playback quality")
                    dpg.add_spacer(height=3)
                    dpg.add_text("Use to hear how it will sound on Atari.", color=(150, 200, 150))


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
        build_top_row()
        dpg.add_spacer(height=2)
        build_input_row()
        dpg.add_spacer(height=2)
        build_bottom_row()
        build_status_bar()
