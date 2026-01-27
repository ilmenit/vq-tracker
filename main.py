"""
Atari Sample Tracker - Main Entry Point
UI creation and main loop.
"""

import dearpygui.dearpygui as dpg
import os

from constants import (
    COLORS, WIN_WIDTH, WIN_HEIGHT, MAX_CHANNELS, PAL_HZ, NTSC_HZ,
    APP_NAME, APP_VERSION, note_to_str, VISIBLE_ROWS
)
from state import state
from audio_engine import AUDIO_OK
from ui_theme import setup_theme
from ui_dialogs import show_file_dialog, show_confirm, show_error, show_rename_dlg, show_about, show_shortcuts
import operations as ops
import keyboard

# =============================================================================
# HELPER
# =============================================================================

def fmt(val: int, width: int = 2) -> str:
    return f"{val:0{width}X}" if state.hex_mode else f"{val:0{width}d}"

def update_title():
    title = f"{APP_NAME} v{APP_VERSION}"
    if state.song.file_path:
        title += f" - {os.path.basename(state.song.file_path)}"
    else:
        title += " - New Project"
    if state.song.modified:
        title += " *"
    dpg.set_viewport_title(title)

def show_status(msg: str):
    if dpg.does_item_exist("status"):
        dpg.set_value("status", msg)

# =============================================================================
# UI REFRESH
# =============================================================================

def refresh_all():
    refresh_songlist()
    refresh_instruments()
    refresh_editor()
    refresh_pattern_combo()
    update_metadata()
    update_octave()
    update_step()
    update_pattern_len()
    refresh_mute_solo()

def refresh_songlist():
    if not dpg.does_item_exist("songlist_container"):
        return
    dpg.delete_item("songlist_container", children_only=True)
    
    play_sl = -1
    if state.audio.is_playing():
        play_sl, _ = state.audio.get_position()
    
    for i, sl in enumerate(state.song.songlines):
        is_cur = (i == state.songline)
        is_play = (i == play_sl)
        
        with dpg.group(horizontal=True, parent="songlist_container"):
            color = COLORS['playing'] if is_play else (COLORS['cursor'] if is_cur else COLORS['text_dim'])
            mark = "▶" if is_play else ("●" if is_cur else " ")
            dpg.add_text(f"{mark}{fmt(i)}", color=color)
            
            for ch in range(MAX_CHANNELS):
                tag = f"sl_{i}_{ch}"
                dpg.add_button(label=fmt(sl.patterns[ch]), tag=tag, width=40,
                               callback=lambda s,a,u: _click_songline(u[0], u[1]),
                               user_data=(i, ch))
                if is_cur and ch == state.channel:
                    dpg.bind_item_theme(tag, "th_cursor")

def _click_songline(sl: int, ch: int):
    state.songline = sl
    state.channel = ch
    state.row = 0
    refresh_all()

def refresh_instruments():
    if not dpg.does_item_exist("inst_container"):
        return
    dpg.delete_item("inst_container", children_only=True)
    
    if not state.song.instruments:
        dpg.add_text("No instruments", parent="inst_container", color=COLORS['text_dim'])
        dpg.add_text("[+] to add", parent="inst_container", color=COLORS['text_muted'])
        return
    
    for i, inst in enumerate(state.song.instruments):
        is_cur = (i == state.instrument)
        with dpg.group(horizontal=True, parent="inst_container"):
            mark = "▶" if is_cur else " "
            dpg.add_text(mark, color=COLORS['accent_green'] if is_cur else COLORS['text_dim'])
            dpg.add_text(fmt(i), color=COLORS['accent_green'] if is_cur else COLORS['text_dim'])
            
            loaded = "●" if inst.is_loaded() else "○"
            name = inst.name[:12] if len(inst.name) > 12 else inst.name
            tag = f"inst_{i}"
            dpg.add_button(label=f"{loaded} {name}", tag=tag, width=-1,
                           callback=lambda s,a,u: ops.select_instrument(u), user_data=i)
            if is_cur:
                dpg.bind_item_theme(tag, "th_cursor")

def refresh_editor():
    if not dpg.does_item_exist("editor_grid"):
        return
    dpg.delete_item("editor_grid", children_only=True)
    
    ptns = state.patterns()
    patterns = [state.song.get_pattern(p) for p in ptns]
    max_len = max(p.length for p in patterns)
    
    # Playing position
    play_row = -1
    play_sl = -1
    if state.audio.is_playing():
        play_sl, play_row = state.audio.get_position()
    is_cur_sl_playing = (play_sl == state.songline)
    
    # Visible range - use constant
    visible = VISIBLE_ROWS
    half = visible // 2
    start = max(0, state.row - half)
    end = min(max_len, start + visible)
    if end - start < visible:
        start = max(0, end - visible)
    
    # Header
    with dpg.group(horizontal=True, parent="editor_grid"):
        dpg.add_text("Row ", color=COLORS['text_dim'])
        for ch in range(MAX_CHANNELS):
            colors = [COLORS['ch1'], COLORS['ch2'], COLORS['ch3']]
            dpg.add_text(f"   CH{ch+1} [{fmt(ptns[ch])}]    ", color=colors[ch])
    dpg.add_separator(parent="editor_grid")
    
    # Rows
    for r in range(start, end):
        is_cursor_row = (r == state.row)
        is_playing_row = is_cur_sl_playing and (r == play_row)
        
        with dpg.group(horizontal=True, parent="editor_grid"):
            # Row number
            row_color = COLORS['playing'] if is_playing_row else (COLORS['cursor'] if is_cursor_row else COLORS['text_dim'])
            dpg.add_text(f"{fmt(r)} ", color=row_color)
            
            # Channels
            for ch_idx, ptn in enumerate(patterns):
                is_cursor_ch = (ch_idx == state.channel)
                
                if r < ptn.length:
                    row = ptn.get_row(r)
                    has_note = row.note > 0
                    note = note_to_str(row.note)
                    ins = fmt(row.instrument) if has_note else "--"
                    vol = fmt(row.volume, 1) if has_note else "-"
                else:
                    note, ins, vol = "...", "..", "."
                    has_note = False
                
                # Note cell
                is_cur_cell = is_cursor_row and is_cursor_ch and state.column == 0
                tag_n = f"n_{r}_{ch_idx}"
                dpg.add_button(label=note, tag=tag_n, width=55,
                               callback=lambda s,a,u: _click_cell(u[0], u[1], 0), user_data=(r, ch_idx))
                if is_cur_cell:
                    dpg.bind_item_theme(tag_n, "th_cursor")
                elif is_playing_row:
                    dpg.bind_item_theme(tag_n, "th_playing")
                elif has_note:
                    dpg.bind_item_theme(tag_n, "th_note_on")
                else:
                    dpg.bind_item_theme(tag_n, "th_note_off")
                
                # Inst cell
                is_cur_cell = is_cursor_row and is_cursor_ch and state.column == 1
                tag_i = f"i_{r}_{ch_idx}"
                dpg.add_button(label=ins, tag=tag_i, width=40,
                               callback=lambda s,a,u: _click_cell(u[0], u[1], 1), user_data=(r, ch_idx))
                if is_cur_cell:
                    dpg.bind_item_theme(tag_i, "th_cursor")
                
                # Vol cell
                is_cur_cell = is_cursor_row and is_cursor_ch and state.column == 2
                tag_v = f"v_{r}_{ch_idx}"
                dpg.add_button(label=vol, tag=tag_v, width=30,
                               callback=lambda s,a,u: _click_cell(u[0], u[1], 2), user_data=(r, ch_idx))
                if is_cur_cell:
                    dpg.bind_item_theme(tag_v, "th_cursor")
                
                dpg.add_text("  ", color=COLORS['border'])

def _click_cell(row: int, ch: int, col: int):
    state.clear_pending()
    state.row = row
    state.channel = ch
    state.column = col
    refresh_editor()

def refresh_pattern_combo():
    if dpg.does_item_exist("ptn_combo"):
        items = [fmt(i) for i in range(len(state.song.patterns))]
        dpg.configure_item("ptn_combo", items=items)
        dpg.set_value("ptn_combo", fmt(state.focused_pattern_idx()))

def refresh_mute_solo():
    for ch in range(MAX_CHANNELS):
        if dpg.does_item_exist(f"mute_{ch}"):
            muted = state.audio.is_muted(ch)
            dpg.configure_item(f"mute_{ch}", label="M*" if muted else "M")
            dpg.bind_item_theme(f"mute_{ch}", "th_muted" if muted else "th_default")
        
        if dpg.does_item_exist(f"solo_{ch}"):
            solo = state.audio.is_solo(ch)
            dpg.configure_item(f"solo_{ch}", label="S*" if solo else "S")
            dpg.bind_item_theme(f"solo_{ch}", "th_solo" if solo else "th_default")

def update_metadata():
    if dpg.does_item_exist("title_inp"):
        dpg.set_value("title_inp", state.song.title)
    if dpg.does_item_exist("author_inp"):
        dpg.set_value("author_inp", state.song.author)
    if dpg.does_item_exist("speed_inp"):
        dpg.set_value("speed_inp", state.song.speed)
    if dpg.does_item_exist("system_combo"):
        dpg.set_value("system_combo", "PAL" if state.song.system == PAL_HZ else "NTSC")

def update_octave():
    if dpg.does_item_exist("octave_txt"):
        dpg.set_value("octave_txt", str(state.octave))

def update_step():
    if dpg.does_item_exist("step_inp"):
        dpg.set_value("step_inp", state.step)

def update_pattern_len():
    if dpg.does_item_exist("len_inp"):
        dpg.set_value("len_inp", state.current_pattern().length)

# =============================================================================
# CALLBACKS
# =============================================================================

def on_title_change(s, v, u):
    state.song.title = v
    state.song.modified = True
    update_title()

def on_author_change(s, v, u):
    state.song.author = v
    state.song.modified = True

def on_speed_change(s, v, u):
    state.song.speed = max(1, min(255, v))
    state.audio.set_speed(state.song.speed)
    state.song.modified = True

def on_system_change(s, v, u):
    state.song.system = PAL_HZ if v == "PAL" else NTSC_HZ
    state.audio.set_system(state.song.system)
    state.song.modified = True

def on_step_change(s, v, u):
    state.step = max(0, min(16, v))

def on_len_change(s, v, u):
    ops.set_pattern_length(v)

def on_ptn_select(s, v, u):
    try:
        idx = int(v, 16) if state.hex_mode else int(v)
        ops.set_songline_pattern(state.channel, idx)
    except ValueError:
        pass

def on_hex_toggle(s, v, u):
    state.hex_mode = v
    refresh_all()

def on_follow_toggle(s, v, u):
    state.follow = v

def toggle_mute(ch: int):
    state.audio.toggle_mute(ch)
    refresh_mute_solo()

def toggle_solo(ch: int):
    state.audio.toggle_solo(ch)
    refresh_mute_solo()

def on_row_change(sl: int, row: int):
    if state.follow:
        if state.audio.get_mode() == 'song':
            state.songline = sl
        state.row = row
    refresh_editor()
    if state.audio.get_mode() == 'song':
        refresh_songlist()

def on_stop():
    refresh_editor()
    show_status("Stopped")

def try_quit():
    if state.song.modified:
        show_confirm("Unsaved Changes", "Quit anyway?", _do_quit)
    else:
        _do_quit()

def _do_quit():
    dpg.stop_dearpygui()

# =============================================================================
# UI CREATION
# =============================================================================

def create_menu():
    with dpg.menu_bar():
        with dpg.menu(label="File"):
            dpg.add_menu_item(label="New", callback=ops.new_song, shortcut="Ctrl+N")
            dpg.add_menu_item(label="Open...", callback=ops.open_song, shortcut="Ctrl+O")
            dpg.add_separator()
            dpg.add_menu_item(label="Save", callback=ops.save_song, shortcut="Ctrl+S")
            dpg.add_menu_item(label="Save As...", callback=ops.save_song_as)
            dpg.add_separator()
            dpg.add_menu_item(label="Export ASM...", callback=ops.export_asm_files)
            dpg.add_separator()
            dpg.add_menu_item(label="Exit", callback=try_quit)
        
        with dpg.menu(label="Edit"):
            dpg.add_menu_item(label="Undo", callback=ops.undo, shortcut="Ctrl+Z")
            dpg.add_menu_item(label="Redo", callback=ops.redo, shortcut="Ctrl+Y")
            dpg.add_separator()
            dpg.add_menu_item(label="Copy", callback=ops.copy_row, shortcut="Ctrl+C")
            dpg.add_menu_item(label="Cut", callback=ops.cut_row, shortcut="Ctrl+X")
            dpg.add_menu_item(label="Paste", callback=ops.paste_row, shortcut="Ctrl+V")
            dpg.add_separator()
            dpg.add_menu_item(label="Clear Cell", callback=ops.clear_cell, shortcut="Del")
            dpg.add_menu_item(label="Insert Row", callback=ops.insert_row, shortcut="Ins")
            dpg.add_menu_item(label="Delete Row", callback=ops.delete_row)
        
        with dpg.menu(label="Song"):
            dpg.add_menu_item(label="Add Songline", callback=ops.add_songline)
            dpg.add_menu_item(label="Clone Songline", callback=ops.clone_songline)
            dpg.add_menu_item(label="Delete Songline", callback=ops.delete_songline)
        
        with dpg.menu(label="Pattern"):
            dpg.add_menu_item(label="New", callback=ops.add_pattern)
            dpg.add_menu_item(label="Clone", callback=ops.clone_pattern)
            dpg.add_menu_item(label="Delete", callback=ops.delete_pattern)
            dpg.add_menu_item(label="Clear", callback=ops.clear_pattern)
            dpg.add_separator()
            dpg.add_menu_item(label="Transpose +1", callback=lambda: ops.transpose(1))
            dpg.add_menu_item(label="Transpose -1", callback=lambda: ops.transpose(-1))
            dpg.add_menu_item(label="Transpose +12", callback=lambda: ops.transpose(12))
            dpg.add_menu_item(label="Transpose -12", callback=lambda: ops.transpose(-12))
        
        with dpg.menu(label="Instrument"):
            dpg.add_menu_item(label="Add", callback=ops.add_instrument)
            dpg.add_menu_item(label="Load Sample...", callback=ops.load_sample_dlg)
            dpg.add_menu_item(label="Rename...", callback=ops.rename_instrument)
            dpg.add_menu_item(label="Remove", callback=ops.remove_instrument)
        
        with dpg.menu(label="Play"):
            dpg.add_menu_item(label="Play/Stop", callback=ops.play_stop, shortcut="Space")
            dpg.add_menu_item(label="Play Pattern", callback=ops.play_pattern, shortcut="F5")
            dpg.add_menu_item(label="Play Song", callback=ops.play_song_start, shortcut="F6")
            dpg.add_menu_item(label="Play Here", callback=ops.play_song_here, shortcut="F7")
            dpg.add_menu_item(label="Stop", callback=ops.stop_playback, shortcut="F8")
            dpg.add_separator()
            dpg.add_menu_item(label="Preview Row", callback=ops.preview_row, shortcut="Enter")
        
        with dpg.menu(label="Help"):
            dpg.add_menu_item(label="Shortcuts...", callback=show_shortcuts, shortcut="F1")
            dpg.add_separator()
            dpg.add_menu_item(label="About...", callback=show_about)

def create_panels():
    with dpg.group(horizontal=True):
        # Song panel
        with dpg.child_window(width=260, height=290, border=True):
            dpg.add_text("SONG", color=COLORS['accent_blue'])
            dpg.add_separator()
            with dpg.child_window(height=190, tag="songlist_container", border=False):
                pass
            with dpg.group(horizontal=True):
                dpg.add_button(label="+", width=45, callback=ops.add_songline)
                dpg.add_button(label="Clone", width=70, callback=ops.clone_songline)
                dpg.add_button(label="Del", width=55, callback=ops.delete_songline)
        
        # Instrument panel
        with dpg.child_window(width=300, height=290, border=True):
            dpg.add_text("INSTRUMENTS", color=COLORS['accent_green'])
            dpg.add_separator()
            with dpg.child_window(height=190, tag="inst_container", border=False):
                pass
            with dpg.group(horizontal=True):
                dpg.add_button(label="+", width=40, callback=ops.add_instrument)
                dpg.add_button(label="Load", width=65, callback=ops.load_sample_dlg)
                dpg.add_button(label="Rename", width=75, callback=ops.rename_instrument)
                dpg.add_button(label="Del", width=50, callback=ops.remove_instrument)
        
        # Controls panel
        with dpg.child_window(width=400, height=290, border=True):
            dpg.add_text("SONG INFO", color=COLORS['accent_yellow'])
            dpg.add_separator()
            
            with dpg.group(horizontal=True):
                dpg.add_text("Title:", color=COLORS['text_dim'])
                dpg.add_input_text(tag="title_inp", width=-1, callback=on_title_change, on_enter=True)
            
            with dpg.group(horizontal=True):
                dpg.add_text("Author:", color=COLORS['text_dim'])
                dpg.add_input_text(tag="author_inp", width=-1, callback=on_author_change, on_enter=True)
            
            dpg.add_spacer(height=4)
            with dpg.group(horizontal=True):
                dpg.add_text("Speed:", color=COLORS['text_dim'])
                dpg.add_input_int(tag="speed_inp", width=80, min_value=1, max_value=255,
                                  min_clamped=True, max_clamped=True, callback=on_speed_change)
                dpg.add_spacer(width=15)
                dpg.add_text("System:", color=COLORS['text_dim'])
                dpg.add_combo(tag="system_combo", items=["PAL","NTSC"], default_value="PAL",
                              width=90, callback=on_system_change)
            
            with dpg.group(horizontal=True):
                dpg.add_text("Octave:", color=COLORS['text_dim'])
                dpg.add_button(label="-", width=35, callback=ops.octave_down)
                dpg.add_text(tag="octave_txt", default_value="2")
                dpg.add_button(label="+", width=35, callback=ops.octave_up)
                dpg.add_spacer(width=15)
                dpg.add_text("Step:", color=COLORS['text_dim'])
                dpg.add_input_int(tag="step_inp", width=70, min_value=0, max_value=16,
                                  min_clamped=True, max_clamped=True, callback=on_step_change)
            
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="Hex", default_value=True, callback=on_hex_toggle)
                dpg.add_spacer(width=20)
                dpg.add_checkbox(label="Follow Playback", default_value=True, callback=on_follow_toggle)
        
        # Pattern panel
        with dpg.child_window(width=340, height=290, border=True):
            dpg.add_text("PATTERN", color=COLORS['accent_purple'])
            dpg.add_separator()
            
            with dpg.group(horizontal=True):
                dpg.add_text("Ptn:", color=COLORS['text_dim'])
                dpg.add_combo(tag="ptn_combo", items=["00"], default_value="00", width=80, callback=on_ptn_select)
                dpg.add_spacer(width=15)
                dpg.add_text("Len:", color=COLORS['text_dim'])
                dpg.add_input_int(tag="len_inp", width=80, min_value=1, max_value=256,
                                  min_clamped=True, max_clamped=True, callback=on_len_change)
            
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label="New", width=70, callback=ops.add_pattern)
                dpg.add_button(label="Clone", width=70, callback=ops.clone_pattern)
                dpg.add_button(label="Delete", width=75, callback=ops.delete_pattern)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Clear", width=70, callback=ops.clear_pattern)
            
            dpg.add_spacer(height=8)
            dpg.add_text("Channels:", color=COLORS['text_dim'])
            with dpg.group(horizontal=True):
                colors = [COLORS['ch1'], COLORS['ch2'], COLORS['ch3']]
                for ch in range(MAX_CHANNELS):
                    dpg.add_text(f"CH{ch+1}:", color=colors[ch])
                    dpg.add_button(label="M", tag=f"mute_{ch}", width=35,
                                   callback=lambda s,a,u: toggle_mute(u), user_data=ch)
                    dpg.add_button(label="S", tag=f"solo_{ch}", width=35,
                                   callback=lambda s,a,u: toggle_solo(u), user_data=ch)
                    if ch < 2:
                        dpg.add_spacer(width=10)

def create_editor():
    dpg.add_text("PATTERN EDITOR", color=COLORS['accent_cyan'])
    dpg.add_separator()
    with dpg.child_window(tag="editor_grid", border=True, height=-45):
        pass
    dpg.add_spacer(height=4)
    with dpg.group(horizontal=True):
        dpg.add_text("Ready", tag="status", color=COLORS['text_dim'])
        dpg.add_spacer(width=30)
        audio_txt = "Audio: OK" if AUDIO_OK else "Audio: N/A"
        dpg.add_text(audio_txt, color=COLORS['accent_green'] if AUDIO_OK else COLORS['accent_red'])
        dpg.add_spacer(width=30)
        dpg.add_text("F1=Help  Space=Play", color=COLORS['text_muted'])

# =============================================================================
# MAIN
# =============================================================================

def run():
    # Wire up operations module
    ops.refresh_all = refresh_all
    ops.refresh_editor = refresh_editor
    ops.refresh_songlist = refresh_songlist
    ops.refresh_instruments = refresh_instruments
    ops.refresh_pattern_combo = refresh_pattern_combo
    ops.update_pattern_len = update_pattern_len
    ops.show_status = show_status
    ops.update_title = update_title
    ops.show_error = show_error
    ops.show_confirm = show_confirm
    ops.show_file_dialog = show_file_dialog
    ops.show_rename_dlg = show_rename_dlg
    
    # Init DPG
    dpg.create_context()
    setup_theme()
    
    dpg.create_viewport(title=f"{APP_NAME} v{APP_VERSION}", width=WIN_WIDTH, height=WIN_HEIGHT,
                        min_width=1200, min_height=800)
    
    # Main window
    with dpg.window(tag="main"):
        create_menu()
        create_panels()
        dpg.add_spacer(height=8)
        create_editor()
    
    # Keyboard handler
    with dpg.handler_registry():
        dpg.add_key_press_handler(callback=keyboard.handle_key)
    
    # Init audio
    if AUDIO_OK:
        state.audio.start()
    state.audio.set_song(state.song)
    state.audio.on_row = on_row_change
    state.audio.on_stop = on_stop
    
    # Initial refresh
    refresh_all()
    update_title()
    
    # Setup and run
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main", True)
    
    # Main loop
    while dpg.is_dearpygui_running():
        state.audio.process_callbacks()
        dpg.render_dearpygui_frame()
    
    # Cleanup
    state.audio.stop()
    dpg.destroy_context()

if __name__ == "__main__":
    run()
