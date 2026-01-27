"""Atari Sample Tracker - Main UI (v3.6)"""
import dearpygui.dearpygui as dpg
import os
import json
import time
import logging
from pathlib import Path
from constants import (APP_NAME, APP_VERSION, WIN_WIDTH, WIN_HEIGHT, ROW_HEIGHT,
                       MAX_CHANNELS, MAX_OCTAVES, MAX_VOLUME, MAX_ROWS, MAX_INSTRUMENTS,
                       MAX_NOTES, PAL_HZ, NTSC_HZ, note_to_str, FOCUS_SONG, FOCUS_PATTERN,
                       FOCUS_INSTRUMENTS, FOCUS_INFO, FOCUS_EDITOR, COL_CH,
                       COL_NOTE, COL_INST, COL_VOL, NOTE_NAMES, COL_INACTIVE)
from state import state
from ui_theme import create_themes, get_cell_theme
from ui_dialogs import (show_file_dialog, show_error, show_rename_dialog, show_about, show_shortcuts)
import operations as ops
from keyboard import handle_key

# =============================================================================
# LOGGING SETUP
# =============================================================================
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("tracker.main")

# =============================================================================
# CONFIGURATION
# =============================================================================
CONFIG_DIR = Path.home() / ".atari_tracker"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTOSAVE_DIR = CONFIG_DIR / "autosave"
MAX_AUTOSAVES = 20
AUTOSAVE_INTERVAL = 30
MAX_RECENT = 10

# UI SIZING
TOP_PANEL_HEIGHT = 195
EDITOR_WIDTH = 500
SONG_INFO_WIDTH = 225
INPUT_ROW_HEIGHT = 40
EDITOR_HEADER_HEIGHT = 85  # Height of editor header (title, buttons, column headers)
MIN_VISIBLE_ROWS = 5
MAX_VISIBLE_ROWS = 50

# =============================================================================
# GLOBALS
# =============================================================================
_visible_rows = 13
_play_row = -1
_play_songline = -1
_last_autosave = 0
_autosave_enabled = True
_recent_files = []

# =============================================================================
# CONFIG
# =============================================================================

def load_config():
    global _autosave_enabled, _recent_files
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                _autosave_enabled = cfg.get('autosave_enabled', True)
                _recent_files = cfg.get('recent_files', [])[:MAX_RECENT]
                ed = cfg.get('editor_settings', {})
                state.hex_mode = ed.get('hex_mode', True)
                state.octave = ed.get('octave', 2)
                state.step = ed.get('step', 1)
                state.follow = ed.get('follow', True)
                logger.info(f"Config loaded")
    except Exception as e:
        logger.error(f"Config load error: {e}")

def save_config():
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = {
            'autosave_enabled': _autosave_enabled,
            'recent_files': _recent_files[:MAX_RECENT],
            'editor_settings': {
                'hex_mode': state.hex_mode, 'octave': state.octave,
                'step': state.step, 'follow': state.follow,
            }
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"Config save error: {e}")

def add_recent_file(path: str):
    global _recent_files
    if path in _recent_files:
        _recent_files.remove(path)
    _recent_files.insert(0, path)
    _recent_files = _recent_files[:MAX_RECENT]
    save_config()

def get_autosave_files():
    try:
        files = list(AUTOSAVE_DIR.glob("autosave_*.pvq"))
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return files
    except:
        return []

def do_autosave():
    global _last_autosave
    if not _autosave_enabled:
        return
    try:
        AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = AUTOSAVE_DIR / f"autosave_{timestamp}.pvq"
        from file_io import save_project
        save_project(state.song, str(filename))
        for f in get_autosave_files()[MAX_AUTOSAVES:]:
            try: f.unlink()
            except: pass
        _last_autosave = time.time()
        show_status("Auto-saved")
    except Exception as e:
        logger.error(f"Autosave error: {e}")

def check_autosave():
    global _last_autosave
    if _autosave_enabled and state.song.modified:
        if time.time() - _last_autosave >= AUTOSAVE_INTERVAL:
            do_autosave()

# =============================================================================
# UI HELPERS
# =============================================================================

def fmt(val: int, width: int = 2) -> str:
    return f"{val:0{width}X}" if state.hex_mode else f"{val:0{width}d}"

def fmt_inst(val: int) -> str:
    return f"{val:02X}" if state.hex_mode else f"{val:03d}"

def fmt_vol(val: int) -> str:
    return f"{val:X}" if state.hex_mode else f"{val:02d}"

def set_focus(area: int):
    state.set_focus(area)

def on_input_focus(sender, data):
    state.set_input_active(True)

def on_input_blur(sender, data):
    state.set_input_active(False)

# =============================================================================
# REFRESH
# =============================================================================

def refresh_all():
    refresh_songlist()
    refresh_pattern_info()
    refresh_instruments()
    refresh_editor()
    update_controls()

def refresh_songlist():
    if not dpg.does_item_exist("songlist"):
        return
    dpg.delete_item("songlist", children_only=True)
    
    with dpg.group(horizontal=True, parent="songlist"):
        dpg.add_text("   ", color=(100,100,100))
        dpg.add_text("C1", color=COL_CH[0])
        dpg.add_spacer(width=5)
        dpg.add_text("C2", color=COL_CH[1])
        dpg.add_spacer(width=5)
        dpg.add_text("C3", color=COL_CH[2])
    
    for i, sl in enumerate(state.song.songlines):
        is_current = (i == state.songline)
        marker = ">" if is_current else " "
        with dpg.group(horizontal=True, parent="songlist"):
            btn = dpg.add_button(label=f"{marker}{fmt(i)}", width=35, height=18,
                                 callback=select_songline_click, user_data=i)
            if is_current:
                dpg.bind_item_theme(btn, "theme_cell_cursor")
            for ch in range(MAX_CHANNELS):
                ptn_items = [fmt(p) for p in range(len(state.song.patterns))] + ["ADD"]
                dpg.add_combo(items=ptn_items, default_value=fmt(sl.patterns[ch]),
                              width=40, callback=on_songline_pattern_change, user_data=(i, ch))

def refresh_pattern_info():
    if dpg.does_item_exist("ptn_select_combo"):
        ptn_items = [f"{fmt(i)}" for i in range(len(state.song.patterns))] + ["ADD"]
        dpg.configure_item("ptn_select_combo", items=ptn_items)
        dpg.set_value("ptn_select_combo", fmt(state.selected_pattern))
    if dpg.does_item_exist("ptn_len_input"):
        ptn = state.song.get_pattern(state.selected_pattern)
        dpg.set_value("ptn_len_input", ptn.length)

def refresh_instruments():
    if not dpg.does_item_exist("instlist"):
        return
    dpg.delete_item("instlist", children_only=True)
    
    for i, inst in enumerate(state.song.instruments):
        is_current = (i == state.instrument)
        with dpg.group(horizontal=True, parent="instlist"):
            # Index number (fixed width)
            dpg.add_text(f"{fmt(i)}", color=(100,100,110))
            dpg.add_spacer(width=3)
            # Play button
            play_btn = dpg.add_button(label=">", width=22, height=18,
                                      callback=preview_instrument, user_data=i)
            with dpg.tooltip(play_btn):
                dpg.add_text("Preview sample")
            dpg.add_spacer(width=3)
            # Name button (left-aligned, no star prefix)
            name = inst.name[:22] if inst.name else "(unnamed)"
            btn = dpg.add_button(label=name, width=-1, height=18,
                                 callback=select_inst_click, user_data=i)
            if is_current:
                dpg.bind_item_theme(btn, "theme_cell_cursor")
    
    if dpg.does_item_exist("input_inst_combo"):
        items = [f"{fmt(i)} - {inst.name[:12]}" for i, inst in enumerate(state.song.instruments)]
        dpg.configure_item("input_inst_combo", items=items if items else ["(none)"])
        if state.song.instruments and state.instrument < len(state.song.instruments):
            dpg.set_value("input_inst_combo", items[state.instrument] if items else "(none)")

def refresh_editor():
    ptns = state.get_patterns()
    patterns = [state.song.get_pattern(p) for p in ptns]
    max_len = state.song.max_pattern_length(state.songline)
    
    half = _visible_rows // 2
    start_row = max(0, state.row - half)
    if start_row + _visible_rows > max_len:
        start_row = max(0, max_len - _visible_rows)
    
    for ch in range(MAX_CHANNELS):
        combo_tag = f"ch_ptn_combo_{ch}"
        if dpg.does_item_exist(combo_tag):
            ptn_items = [fmt(p) for p in range(len(state.song.patterns))] + ["ADD"]
            dpg.configure_item(combo_tag, items=ptn_items)
            dpg.set_value(combo_tag, fmt(ptns[ch]))
        cb_tag = f"ch_enabled_{ch}"
        if dpg.does_item_exist(cb_tag):
            dpg.set_value(cb_tag, state.audio.is_channel_enabled(ch))
    
    for vis_row in range(_visible_rows):
        row_idx = start_row + vis_row
        is_cursor_row = (row_idx == state.row)
        is_playing = (row_idx == _play_row and state.songline == _play_songline)
        
        row_tag = f"row_num_{vis_row}"
        if dpg.does_item_exist(row_tag):
            if row_idx < max_len:
                dpg.set_value(row_tag, fmt(row_idx))
                # Green for playing, blue for cursor row, grey otherwise
                if is_playing:
                    col = (80,200,100)
                elif is_cursor_row:
                    col = (100,160,255)
                else:
                    col = (100,100,110)
                dpg.configure_item(row_tag, color=col)
            else:
                dpg.set_value(row_tag, "")
        
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
            
            # Determine theme - cursor row highlight even when not on that cell
            note_tag = f"cell_note_{vis_row}_{ch}"
            if dpg.does_item_exist(note_tag):
                if r and row_idx < max_len:
                    note_str = note_to_str(r.note)
                    prefix = "~" if is_repeat and actual_row == 0 else " "
                    dpg.configure_item(note_tag, label=f"{prefix}{note_str}")
                    is_note_cursor = is_cursor and state.column == COL_NOTE
                    if is_note_cursor:
                        theme = "theme_cell_cursor"
                    elif is_playing:
                        theme = "theme_cell_playing"
                    elif is_cursor_row:
                        theme = "theme_cell_current_row"
                    elif not ch_enabled:
                        theme = "theme_cell_inactive"
                    else:
                        theme = get_cell_theme(False, False, is_selected, is_repeat, has_note, not ch_enabled)
                    dpg.bind_item_theme(note_tag, theme)
                else:
                    dpg.configure_item(note_tag, label="")
            
            inst_tag = f"cell_inst_{vis_row}_{ch}"
            if dpg.does_item_exist(inst_tag):
                if r and row_idx < max_len:
                    inst_str = fmt_inst(r.instrument) if r.note > 0 else ("--" if state.hex_mode else "---")
                    dpg.configure_item(inst_tag, label=inst_str)
                    is_inst_cursor = is_cursor and state.column == COL_INST
                    if is_inst_cursor:
                        theme = "theme_cell_cursor"
                    elif is_playing:
                        theme = "theme_cell_playing"
                    elif is_cursor_row:
                        theme = "theme_cell_current_row"
                    elif not ch_enabled:
                        theme = "theme_cell_inactive"
                    else:
                        theme = get_cell_theme(False, False, is_selected, is_repeat, has_note, not ch_enabled)
                    dpg.bind_item_theme(inst_tag, theme)
                else:
                    dpg.configure_item(inst_tag, label="")
            
            vol_tag = f"cell_vol_{vis_row}_{ch}"
            if dpg.does_item_exist(vol_tag):
                if r and row_idx < max_len:
                    vol_str = fmt_vol(r.volume) if r.note > 0 else ("-" if state.hex_mode else "--")
                    dpg.configure_item(vol_tag, label=vol_str)
                    is_vol_cursor = is_cursor and state.column == COL_VOL
                    if is_vol_cursor:
                        theme = "theme_cell_cursor"
                    elif is_playing:
                        theme = "theme_cell_playing"
                    elif is_cursor_row:
                        theme = "theme_cell_current_row"
                    elif not ch_enabled:
                        theme = "theme_cell_inactive"
                    else:
                        theme = get_cell_theme(False, False, is_selected, is_repeat, has_note, not ch_enabled)
                    dpg.bind_item_theme(vol_tag, theme)
                else:
                    dpg.configure_item(vol_tag, label="")

def update_controls():
    if dpg.does_item_exist("oct_combo"):
        dpg.set_value("oct_combo", str(state.octave))
    if dpg.does_item_exist("step_input"):
        dpg.set_value("step_input", state.step)
    if dpg.does_item_exist("speed_input"):
        dpg.set_value("speed_input", state.song.speed)
    if dpg.does_item_exist("ptn_len_input"):
        ptn = state.song.get_pattern(state.selected_pattern)
        dpg.set_value("ptn_len_input", ptn.length)

def update_title():
    mod = "*" if state.song.modified else ""
    name = state.song.title or "Untitled"
    dpg.set_viewport_title(f"{mod}{name} - {APP_NAME}")

def show_status(msg: str):
    if dpg.does_item_exist("status_text"):
        dpg.set_value("status_text", msg)

# =============================================================================
# CLICK HANDLERS
# =============================================================================

def select_songline_click(sender, app_data, user_data):
    set_focus(FOCUS_SONG)
    ops.select_songline(user_data)

def select_inst_click(sender, app_data, user_data):
    set_focus(FOCUS_INSTRUMENTS)
    state.instrument = user_data
    refresh_instruments()
    show_status(f"Instrument: {fmt(user_data)}")

def preview_instrument(sender, app_data, user_data):
    idx = user_data
    logger.debug(f"Preview instrument {idx}")
    if idx < len(state.song.instruments):
        inst = state.song.instruments[idx]
        logger.debug(f"Instrument '{inst.name}' loaded={inst.is_loaded()}, sample_data={inst.sample_data is not None}")
        if inst.is_loaded():
            note = (state.octave - 1) * 12 + 1
            logger.debug(f"Triggering preview: ch=0, note={note}, vol={MAX_VOLUME}")
            logger.debug(f"Audio running={state.audio.running}")
            state.audio.preview_note(0, note, inst, MAX_VOLUME)
            show_status(f"Playing: {inst.name}")
        else:
            show_status(f"Instrument not loaded")

def cell_click(sender, app_data, user_data):
    vis_row, channel, column = user_data
    set_focus(FOCUS_EDITOR)
    
    max_len = state.song.max_pattern_length(state.songline)
    half = _visible_rows // 2
    start_row = max(0, state.row - half)
    if start_row + _visible_rows > max_len:
        start_row = max(0, max_len - _visible_rows)
    row = start_row + vis_row
    if row >= max_len:
        return
    
    state.row = row
    state.channel = channel
    state.column = column
    state.selection.clear()
    
    # Get mouse position for popup placement
    mouse_pos = dpg.get_mouse_pos(local=False)
    
    if column == COL_INST and state.song.instruments:
        show_instrument_popup(row, channel, mouse_pos)
    elif column == COL_VOL:
        show_volume_popup(row, channel, mouse_pos)
    elif column == COL_NOTE:
        show_note_popup(row, channel, mouse_pos)
    
    refresh_editor()

def show_instrument_popup(row: int, channel: int, pos: tuple):
    if dpg.does_item_exist("popup_inst"):
        dpg.delete_item("popup_inst")
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_inst = ptn.get_row(row % ptn.length).instrument
    items = [f"{fmt_inst(i)} - {inst.name}" for i, inst in enumerate(state.song.instruments)]
    if not items:
        return
    
    def on_select(sender, value):
        state.set_input_active(False)
        try:
            idx = int(value.split(" - ")[0], 16 if state.hex_mode else 10)
            ops.set_cell_instrument(row, channel, idx)
        except: pass
        dpg.delete_item("popup_inst")
    
    state.set_input_active(True)
    with dpg.window(tag="popup_inst", popup=True, no_title_bar=True, modal=True,
                    pos=[int(pos[0]), int(pos[1])], min_size=(200, 100), max_size=(300, 300)):
        dpg.add_text("Select Instrument:")
        idx = min(current_inst, len(items)-1) if items else 0
        dpg.add_listbox(items=items, default_value=items[idx] if items else "",
                        num_items=min(8, len(items)), callback=on_select, width=-1)

def show_volume_popup(row: int, channel: int, pos: tuple):
    if dpg.does_item_exist("popup_vol"):
        dpg.delete_item("popup_vol")
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_vol = ptn.get_row(row % ptn.length).volume
    items = [fmt_vol(v) for v in range(MAX_VOLUME + 1)]
    
    def on_select(sender, value):
        state.set_input_active(False)
        try:
            vol = int(value, 16) if state.hex_mode else int(value)
            ops.set_cell_volume(row, channel, vol)
        except: pass
        dpg.delete_item("popup_vol")
    
    state.set_input_active(True)
    with dpg.window(tag="popup_vol", popup=True, no_title_bar=True, modal=True,
                    pos=[int(pos[0]), int(pos[1])], min_size=(60, 180)):
        dpg.add_text("Volume:")
        dpg.add_listbox(items=items, default_value=fmt_vol(current_vol),
                        num_items=10, callback=on_select, width=-1)

def show_note_popup(row: int, channel: int, pos: tuple):
    if dpg.does_item_exist("popup_note"):
        dpg.delete_item("popup_note")
    ptn_idx = state.get_patterns()[channel]
    ptn = state.song.get_pattern(ptn_idx)
    current_note = ptn.get_row(row % ptn.length).note
    notes = ["--- (empty)"] + [note_to_str(n) for n in range(1, MAX_NOTES + 1)]
    current_val = notes[current_note] if current_note < len(notes) else notes[0]
    
    def on_select(sender, value):
        state.set_input_active(False)
        if value == "--- (empty)":
            ops.set_cell_note(row, channel, 0)
        else:
            try:
                idx = notes.index(value)
                ops.set_cell_note(row, channel, idx)
            except: pass
        dpg.delete_item("popup_note")
    
    state.set_input_active(True)
    with dpg.window(tag="popup_note", popup=True, no_title_bar=True, modal=True,
                    pos=[int(pos[0]), int(pos[1])], min_size=(100, 200), max_size=(130, 400)):
        dpg.add_text("Note:")
        dpg.add_listbox(items=notes, default_value=current_val,
                        num_items=12, callback=on_select, width=-1)

# =============================================================================
# CALLBACKS
# =============================================================================

def on_octave_change(sender, value):
    try:
        state.octave = int(value)
        save_config()
    except: pass

def on_step_change(sender, value):
    state.step = max(0, min(16, value))
    save_config()

def on_speed_change(sender, value):
    state.song.speed = max(1, min(255, value))
    state.song.modified = True

def on_ptn_len_change(sender, value):
    value = max(1, min(MAX_ROWS, value))
    ops.set_pattern_length(value, state.selected_pattern)

def on_pattern_select(sender, value):
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
        except: pass

def on_songline_pattern_change(sender, value, user_data):
    sl_idx, ch = user_data
    if value == "ADD":
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[sl_idx].patterns[ch] = idx
            state.selected_pattern = idx
            ops.save_undo("Add pattern")
            refresh_all()
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            state.song.songlines[sl_idx].patterns[ch] = idx
            state.selected_pattern = idx
            state.song.modified = True
            refresh_pattern_info()
            refresh_editor()
        except: pass

def on_editor_pattern_change(sender, value, user_data):
    ch = user_data
    if value == "ADD":
        idx = state.song.add_pattern()
        if idx >= 0:
            state.song.songlines[state.songline].patterns[ch] = idx
            state.selected_pattern = idx
            ops.save_undo("Add pattern")
            refresh_all()
    else:
        try:
            idx = int(value, 16) if state.hex_mode else int(value)
            state.song.songlines[state.songline].patterns[ch] = idx
            state.selected_pattern = idx
            state.song.modified = True
            refresh_pattern_info()
            refresh_editor()
        except: pass

def on_channel_toggle(sender, value, user_data):
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
    save_config()
    refresh_all()

def on_autosave_toggle(sender, value):
    global _autosave_enabled
    _autosave_enabled = value
    save_config()

def on_input_inst_change(sender, value):
    try:
        idx = int(value.split(" - ")[0], 16 if state.hex_mode else 10)
        state.instrument = idx
        refresh_instruments()
    except: pass

def on_reset_song():
    def do_reset():
        state.song.reset()
        state.songline = state.row = state.channel = state.column = 0
        state.selected_pattern = 0
        refresh_all()
        update_title()
        show_status("Song reset")
    show_confirm_centered("Reset Song", "Clear all song data?", do_reset)

def on_playback_row(songline: int, row: int):
    global _play_row, _play_songline
    _play_row, _play_songline = row, songline
    if state.follow and state.audio.is_playing():
        if state.songline != songline:
            state.songline = songline
            refresh_songlist()
        state.row = row
    refresh_editor()

def on_playback_stop():
    global _play_row, _play_songline
    _play_row, _play_songline = -1, -1
    refresh_editor()

# =============================================================================
# PLAYBACK BUTTONS - Pattern plays current pattern, Song plays from start
# =============================================================================

def on_play_pattern_click(sender, app_data):
    """Play current pattern from current row."""
    logger.debug("Play Pattern clicked")
    ops.play_stop()

def on_play_song_click(sender, app_data):
    """Play entire song from beginning."""
    logger.debug("Play Song clicked")
    ops.play_song_start()

def on_stop_click(sender, app_data):
    logger.debug("Stop clicked")
    ops.stop_playback()

# =============================================================================
# INSTRUMENT MANAGEMENT
# =============================================================================

def on_move_inst_up(sender, app_data):
    """Move selected instrument up in the list."""
    if state.instrument > 0 and state.instrument < len(state.song.instruments):
        idx = state.instrument
        state.song.instruments[idx], state.song.instruments[idx-1] = \
            state.song.instruments[idx-1], state.song.instruments[idx]
        state.instrument -= 1
        state.song.modified = True
        refresh_instruments()
        show_status(f"Moved instrument up")

def on_move_inst_down(sender, app_data):
    """Move selected instrument down in the list."""
    if state.instrument < len(state.song.instruments) - 1:
        idx = state.instrument
        state.song.instruments[idx], state.song.instruments[idx+1] = \
            state.song.instruments[idx+1], state.song.instruments[idx]
        state.instrument += 1
        state.song.modified = True
        refresh_instruments()
        show_status(f"Moved instrument down")

# =============================================================================
# DYNAMIC ROW CALCULATION
# =============================================================================

def calculate_visible_rows() -> int:
    """Calculate how many rows fit in the editor based on window height."""
    try:
        vp_height = dpg.get_viewport_height()
        # Calculate available height for editor grid
        # Total height minus: top panels, input row, editor header, status bar, margins
        fixed_height = TOP_PANEL_HEIGHT + INPUT_ROW_HEIGHT + EDITOR_HEADER_HEIGHT + 60  # 60 for margins/status
        available = vp_height - fixed_height
        rows = max(MIN_VISIBLE_ROWS, min(MAX_VISIBLE_ROWS, available // ROW_HEIGHT))
        return rows
    except:
        return 13  # Default fallback

def on_viewport_resize(sender=None, app_data=None):
    """Handle viewport resize - recalculate visible rows."""
    global _visible_rows
    new_rows = calculate_visible_rows()
    if new_rows != _visible_rows:
        _visible_rows = new_rows
        logger.debug(f"Viewport resized, new visible rows: {_visible_rows}")
        rebuild_editor_grid()
        refresh_editor()

# =============================================================================
# GLOBAL MOUSE HANDLER
# =============================================================================

def on_global_mouse_click(sender, app_data):
    """Handle global mouse clicks to set focus based on click position."""
    # Only handle left clicks
    if app_data != 0:  # 0 = left click
        return
    
    # Get mouse position
    mouse_pos = dpg.get_mouse_pos(local=False)
    
    # Check if click is in editor panel area
    if dpg.does_item_exist("editor_panel"):
        try:
            pos = dpg.get_item_pos("editor_panel")
            rect = dpg.get_item_rect_size("editor_panel")
            if pos and rect:
                if (pos[0] <= mouse_pos[0] <= pos[0] + rect[0] and
                    pos[1] <= mouse_pos[1] <= pos[1] + rect[1]):
                    set_focus(FOCUS_EDITOR)
                    return
        except:
            pass
    
    # Check if click is in instruments panel area
    if dpg.does_item_exist("inst_panel"):
        try:
            pos = dpg.get_item_pos("inst_panel")
            rect = dpg.get_item_rect_size("inst_panel")
            if pos and rect:
                if (pos[0] <= mouse_pos[0] <= pos[0] + rect[0] and
                    pos[1] <= mouse_pos[1] <= pos[1] + rect[1]):
                    set_focus(FOCUS_INSTRUMENTS)
                    return
        except:
            pass

# =============================================================================
# RECENT FILES
# =============================================================================

def load_recent_file(sender, app_data, user_data):
    path = user_data
    if not os.path.exists(path):
        show_error("File Not Found", f"File no longer exists:\n{path}")
        return
    if state.song.modified and _autosave_enabled:
        do_autosave()
    from file_io import load_project, load_instrument_samples
    song, err = load_project(path)
    if err:
        show_error("Load Error", err)
        return
    state.song = song
    load_instrument_samples(state.song)
    state.audio.set_song(state.song)
    add_recent_file(path)
    state.songline = state.row = state.channel = state.selected_pattern = 0
    refresh_all()
    update_title()
    show_status(f"Loaded: {os.path.basename(path)}")

def rebuild_recent_menu():
    if dpg.does_item_exist("recent_menu"):
        dpg.delete_item("recent_menu", children_only=True)
        for path in _recent_files:
            dpg.add_menu_item(label=os.path.basename(path), parent="recent_menu",
                              callback=load_recent_file, user_data=path)
        autosaves = get_autosave_files()
        if autosaves:
            dpg.add_separator(parent="recent_menu")
            dpg.add_text("Autosaves:", parent="recent_menu", color=(150,150,160))
            for f in autosaves[:5]:
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
                dpg.add_menu_item(label=mtime, parent="recent_menu",
                                  callback=load_recent_file, user_data=str(f))

# =============================================================================
# DIALOGS
# =============================================================================

def show_confirm_centered(title: str, message: str, callback):
    if dpg.does_item_exist("confirm_dlg"):
        dpg.delete_item("confirm_dlg")
    vp_w, vp_h = dpg.get_viewport_width(), dpg.get_viewport_height()
    w, h = 320, 120
    state.set_input_active(True)
    
    def on_ok():
        state.set_input_active(False)
        dpg.delete_item("confirm_dlg")
        callback()
    def on_cancel():
        state.set_input_active(False)
        dpg.delete_item("confirm_dlg")
    
    with dpg.window(tag="confirm_dlg", label=title, modal=True,
                    width=w, height=h, pos=[(vp_w-w)//2, (vp_h-h)//2],
                    no_resize=True, no_collapse=True):
        dpg.add_text(message)
        dpg.add_spacer(height=15)
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=80, callback=on_ok)
            dpg.add_spacer(width=10)
            dpg.add_button(label="Cancel", width=80, callback=on_cancel)

def on_delete_songline_confirm():
    show_confirm_centered("Delete Row", "Delete this song row?", ops.delete_songline)

def on_delete_pattern_confirm():
    ptn_idx = state.selected_pattern
    if state.song.pattern_in_use(ptn_idx):
        show_error("Cannot Delete", "Pattern is in use")
        return
    show_confirm_centered("Delete Pattern", f"Delete pattern {fmt(ptn_idx)}?", ops.delete_pattern)

# =============================================================================
# BUILD UI
# =============================================================================

def build_menu():
    with dpg.menu_bar():
        with dpg.menu(label="File"):
            dpg.add_menu_item(label="New", callback=ops.new_song, shortcut="Ctrl+N")
            dpg.add_menu_item(label="Open...", callback=ops.open_song, shortcut="Ctrl+O")
            with dpg.menu(label="Open Recent", tag="recent_menu"):
                pass
            dpg.add_separator()
            dpg.add_menu_item(label="Save", callback=ops.save_song, shortcut="Ctrl+S")
            dpg.add_menu_item(label="Save As...", callback=ops.save_song_as)
            dpg.add_separator()
            with dpg.menu(label="Export"):
                dpg.add_menu_item(label="Binary (.pvg)...", callback=ops.export_binary_file)
                dpg.add_menu_item(label="ASM Files...", callback=ops.export_asm_files)
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

def on_exit():
    logger.info("Exiting...")
    if _autosave_enabled and state.song.modified:
        do_autosave()
    save_config()
    dpg.stop_dearpygui()

def build_top_row():
    """[SONG] | [PATTERN] | [SONG INFO] | [SETTINGS]"""
    with dpg.group(horizontal=True):
        # SONG
        with dpg.child_window(tag="song_panel", width=200, height=TOP_PANEL_HEIGHT, border=True):
            dpg.add_text("SONG")
            with dpg.child_window(tag="songlist", height=125, border=False):
                pass
            with dpg.group(horizontal=True):
                dpg.add_button(label="Add", width=45, callback=ops.add_songline)
                dpg.add_button(label="Clone", width=50, callback=ops.clone_songline)
                dpg.add_button(label="Del", width=40, callback=on_delete_songline_confirm)
        
        # PATTERN
        with dpg.child_window(tag="pattern_panel", width=155, height=TOP_PANEL_HEIGHT, border=True):
            dpg.add_text("PATTERN")
            with dpg.group(horizontal=True):
                dpg.add_text("Select:")
                ptn_items = [fmt(i) for i in range(len(state.song.patterns))] + ["ADD"]
                dpg.add_combo(tag="ptn_select_combo", items=ptn_items, default_value="00",
                              width=55, callback=on_pattern_select)
            dpg.add_spacer(height=3)
            dpg.add_text("Length:")
            inp = dpg.add_input_int(tag="ptn_len_input", default_value=64, min_value=1,
                                    max_value=MAX_ROWS, min_clamped=True, max_clamped=True,
                                    width=80, callback=on_ptn_len_change, on_enter=True)
            with dpg.item_handler_registry() as h:
                dpg.add_item_activated_handler(callback=on_input_focus)
                dpg.add_item_deactivated_handler(callback=on_input_blur)
            dpg.bind_item_handler_registry(inp, h)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Add", width=40, callback=ops.add_pattern)
                dpg.add_button(label="Clone", width=45, callback=ops.clone_pattern)
                dpg.add_button(label="Del", width=35, callback=on_delete_pattern_confirm)
        
        # SONG INFO (vertical)
        with dpg.child_window(tag="info_panel", width=SONG_INFO_WIDTH, height=TOP_PANEL_HEIGHT, border=True):
            dpg.add_text("SONG INFO")
            with dpg.group(horizontal=True):
                dpg.add_text("Title: ")
                inp = dpg.add_input_text(tag="title_input", default_value=state.song.title,
                                         width=160, callback=lambda s,v: setattr(state.song, 'title', v))
                with dpg.item_handler_registry() as h:
                    dpg.add_item_activated_handler(callback=on_input_focus)
                    dpg.add_item_deactivated_handler(callback=on_input_blur)
                dpg.bind_item_handler_registry(inp, h)
            with dpg.group(horizontal=True):
                dpg.add_text("Author:")
                inp = dpg.add_input_text(tag="author_input", default_value=state.song.author,
                                         width=160, callback=lambda s,v: setattr(state.song, 'author', v))
                with dpg.item_handler_registry() as h:
                    dpg.add_item_activated_handler(callback=on_input_focus)
                    dpg.add_item_deactivated_handler(callback=on_input_blur)
                dpg.bind_item_handler_registry(inp, h)
            dpg.add_spacer(height=3)
            with dpg.group(horizontal=True):
                dpg.add_text("System:")
                dpg.add_combo(items=["PAL", "NTSC"], default_value="PAL", width=70, callback=on_system_change)
            with dpg.group(horizontal=True):
                dpg.add_text("Speed: ")
                inp = dpg.add_input_int(tag="speed_input", default_value=state.song.speed,
                                        min_value=1, max_value=255, min_clamped=True, max_clamped=True,
                                        width=70, callback=on_speed_change, on_enter=True)
                with dpg.item_handler_registry() as h:
                    dpg.add_item_activated_handler(callback=on_input_focus)
                    dpg.add_item_deactivated_handler(callback=on_input_blur)
                dpg.bind_item_handler_registry(inp, h)
            dpg.add_spacer(height=8)
            dpg.add_button(label="RESET Song", width=120, callback=on_reset_song)
        
        # SETTINGS (vertical)
        with dpg.child_window(width=-1, height=TOP_PANEL_HEIGHT, border=True):
            dpg.add_text("SETTINGS")
            dpg.add_checkbox(label="Hex mode", default_value=True, callback=on_hex_toggle)
            dpg.add_checkbox(tag="autosave_cb", label="Auto-save", default_value=_autosave_enabled,
                             callback=on_autosave_toggle)

def build_input_row():
    """INPUT section - horizontal"""
    with dpg.child_window(height=40, border=True):
        with dpg.group(horizontal=True):
            dpg.add_text("INPUT:")
            dpg.add_spacer(width=8)
            dpg.add_text("Instrument:")
            items = [f"{fmt(i)} - {inst.name[:12]}" for i, inst in enumerate(state.song.instruments)]
            dpg.add_combo(tag="input_inst_combo", items=items if items else ["(none)"],
                          default_value=items[0] if items else "(none)", width=150, callback=on_input_inst_change)
            dpg.add_spacer(width=15)
            dpg.add_text("Octave:")
            dpg.add_combo(tag="oct_combo", items=["1","2","3"], default_value=str(state.octave),
                          width=40, callback=on_octave_change)
            dpg.add_spacer(width=15)
            dpg.add_text("Step:")
            inp = dpg.add_input_int(tag="step_input", default_value=state.step,
                                    min_value=0, max_value=16, min_clamped=True, max_clamped=True,
                                    width=60, callback=on_step_change, on_enter=True)
            with dpg.item_handler_registry() as h:
                dpg.add_item_activated_handler(callback=on_input_focus)
                dpg.add_item_deactivated_handler(callback=on_input_blur)
            dpg.bind_item_handler_registry(inp, h)

def rebuild_editor_grid():
    if dpg.does_item_exist("editor_content"):
        dpg.delete_item("editor_content")
    
    with dpg.group(tag="editor_content", parent="editor_panel"):
        # Header row
        with dpg.group(horizontal=True):
            dpg.add_text("Row", color=(100,100,110))
            dpg.add_spacer(width=10)
            for ch in range(MAX_CHANNELS):
                with dpg.group():
                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(tag=f"ch_enabled_{ch}", default_value=True,
                                         callback=on_channel_toggle, user_data=ch)
                        dpg.add_text(f"Channel {ch+1}", color=COL_CH[ch])
                    with dpg.group(horizontal=True):
                        dpg.add_text("Pattern:", color=(90,90,100))
                        ptn_items = [fmt(i) for i in range(len(state.song.patterns))] + ["ADD"]
                        dpg.add_combo(tag=f"ch_ptn_combo_{ch}", items=ptn_items, default_value="00",
                                      width=50, callback=on_editor_pattern_change, user_data=ch)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Note", color=(90,90,100))
                        dpg.add_spacer(width=8)
                        dpg.add_text("Ins" if state.hex_mode else "Inst", color=(90,90,100))
                        dpg.add_spacer(width=3)
                        dpg.add_text("Vol", color=(90,90,100))
                if ch < MAX_CHANNELS - 1:
                    dpg.add_spacer(width=12)
        
        dpg.add_separator()
        
        for vis_row in range(_visible_rows):
            with dpg.group(horizontal=True):
                dpg.add_text(tag=f"row_num_{vis_row}", default_value="00", color=(100,100,110))
                dpg.add_spacer(width=6)
                for ch in range(MAX_CHANNELS):
                    dpg.add_button(tag=f"cell_note_{vis_row}_{ch}", label=" ---", width=44,
                                   height=ROW_HEIGHT-4, callback=cell_click, user_data=(vis_row, ch, COL_NOTE))
                    inst_w = 30 if state.hex_mode else 36
                    dpg.add_button(tag=f"cell_inst_{vis_row}_{ch}", label="--", width=inst_w,
                                   height=ROW_HEIGHT-4, callback=cell_click, user_data=(vis_row, ch, COL_INST))
                    vol_w = 22 if state.hex_mode else 26
                    dpg.add_button(tag=f"cell_vol_{vis_row}_{ch}", label="-", width=vol_w,
                                   height=ROW_HEIGHT-4, callback=cell_click, user_data=(vis_row, ch, COL_VOL))
                    if ch < MAX_CHANNELS - 1:
                        dpg.add_spacer(width=10)

def build_bottom_row():
    """[GRID EDITOR with playback] | [INSTRUMENTS]"""
    with dpg.group(horizontal=True, tag="bottom_row"):
        # PATTERN EDITOR with playback buttons - height=-1 fills remaining space
        with dpg.child_window(tag="editor_panel", width=EDITOR_WIDTH, height=-30, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("PATTERN EDITOR")
                dpg.add_spacer(width=40)
                # "Pattern" = play current pattern from cursor position
                # "Song" = play entire song from beginning
                dpg.add_button(label="Pattern", width=60, callback=on_play_pattern_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Play pattern from cursor (Space)")
                dpg.add_button(label="Song", width=50, callback=on_play_song_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Play song from start (F6)")
                dpg.add_button(label="Stop", width=45, callback=on_stop_click)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Stop playback (F8)")
            dpg.add_spacer(height=2)
            rebuild_editor_grid()
        
        # INSTRUMENTS - also uses dynamic height
        with dpg.child_window(tag="inst_panel", height=-30, border=True):
            dpg.add_text("INSTRUMENTS")
            with dpg.child_window(tag="instlist", height=-75, border=False):
                pass
            # Row 1: Add Sample, Add Folder
            with dpg.group(horizontal=True):
                dpg.add_button(label="Add Sample", width=90, callback=ops.add_sample)
                dpg.add_button(label="Add Folder", width=90, callback=ops.add_folder)
            # Row 2: Rename, Delete, Move Up, Move Down
            with dpg.group(horizontal=True):
                dpg.add_button(label="Rename", width=60, callback=ops.rename_instrument)
                dpg.add_button(label="Delete", width=55, callback=ops.remove_instrument)
                dpg.add_button(label="Up", width=30, callback=on_move_inst_up)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Move instrument up")
                dpg.add_button(label="Down", width=45, callback=on_move_inst_down)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Move instrument down")

def build_status_bar():
    with dpg.group(horizontal=True):
        dpg.add_text(tag="status_text", default_value="Ready", color=(150, 200, 150))

def build_ui():
    with dpg.window(tag="main_window"):
        build_menu()
        dpg.add_spacer(height=4)
        build_top_row()
        dpg.add_spacer(height=4)
        build_input_row()
        dpg.add_spacer(height=4)
        build_bottom_row()
        dpg.add_spacer(height=4)
        build_status_bar()

# =============================================================================
# MAIN
# =============================================================================

def setup_operations_callbacks():
    ops.refresh_all = refresh_all
    ops.refresh_editor = refresh_editor
    ops.refresh_songlist = refresh_songlist
    ops.refresh_instruments = refresh_instruments
    ops.refresh_pattern_combo = refresh_pattern_info
    ops.update_controls = update_controls
    ops.show_status = show_status
    ops.update_title = update_title
    ops.show_error = show_error
    ops.show_confirm = show_confirm_centered
    ops.show_file_dialog = show_file_dialog
    ops.show_rename_dialog = show_rename_dialog
    
    original_save = ops.save_song
    def save_with_recent(*args):
        original_save(*args)
        if state.song.file_path:
            add_recent_file(state.song.file_path)
    ops.save_song = save_with_recent

def main():
    global _last_autosave, _visible_rows
    
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
    load_config()
    
    dpg.create_context()
    dpg.create_viewport(title=APP_NAME, width=WIN_WIDTH, height=WIN_HEIGHT)
    
    with dpg.font_registry():
        for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                     "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
                     "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
                     "C:/Windows/Fonts/consola.ttf",
                     "/System/Library/Fonts/Monaco.ttf"]:
            try:
                if os.path.exists(path):
                    dpg.bind_font(dpg.add_font(path, 15))
                    logger.debug(f"Font loaded: {path}")
                    break
            except: pass
    
    # Calculate initial visible rows based on default window height
    _visible_rows = calculate_visible_rows()
    logger.info(f"Initial visible rows: {_visible_rows}")
    
    create_themes()
    build_ui()
    setup_operations_callbacks()
    
    state.audio.on_row = on_playback_row
    state.audio.on_stop = on_playback_stop
    
    with dpg.handler_registry():
        dpg.add_key_press_handler(callback=handle_key)
        dpg.add_mouse_click_handler(callback=on_global_mouse_click)
    
    # Register viewport resize callback
    dpg.set_viewport_resize_callback(on_viewport_resize)
    
    state.audio.set_song(state.song)
    logger.info("Starting audio engine...")
    result = state.audio.start()
    logger.info(f"Audio engine start result: {result}, running: {state.audio.running}")
    
    refresh_all()
    update_title()
    rebuild_recent_menu()
    set_focus(FOCUS_EDITOR)
    _last_autosave = time.time()
    
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    
    # Recalculate rows after first frame (viewport size is now accurate)
    dpg.render_dearpygui_frame()
    on_viewport_resize()
    
    logger.info("Entering main loop")
    while dpg.is_dearpygui_running():
        state.audio.process_callbacks()
        check_autosave()
        dpg.render_dearpygui_frame()
    
    logger.info("Shutting down...")
    if _autosave_enabled and state.song.modified:
        do_autosave()
    save_config()
    state.audio.stop()
    dpg.destroy_context()
    logger.info("Shutdown complete")

if __name__ == "__main__":
    main()
