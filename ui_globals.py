"""Atari Sample Tracker - UI Global State and Formatting"""
import dearpygui.dearpygui as dpg
import json
import time
import logging
from pathlib import Path
from constants import (APP_NAME, FOCUS_SONG, FOCUS_PATTERN, FOCUS_INSTRUMENTS, 
                       FOCUS_INFO, FOCUS_EDITOR, MAX_VOLUME)
from state import state

logger = logging.getLogger("tracker.ui")

# =============================================================================
# PATHS AND CONSTANTS
# =============================================================================
CONFIG_DIR = Path.home() / ".atari_tracker"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTOSAVE_DIR = CONFIG_DIR / "autosave"
MAX_AUTOSAVES = 20
AUTOSAVE_INTERVAL = 30
MAX_RECENT = 10

# UI SIZING
TOP_PANEL_HEIGHT = 230
EDITOR_WIDTH = 560
SONG_INFO_WIDTH = 225
INPUT_ROW_HEIGHT = 40
EDITOR_HEADER_HEIGHT = 85
MIN_VISIBLE_ROWS = 1
MAX_VISIBLE_ROWS = 50
SONG_VISIBLE_ROWS = 5
SONG_PANEL_WIDTH = 295

# =============================================================================
# SHARED STATE
# =============================================================================
visible_rows = 13
play_row = -1
play_songline = -1
last_autosave = 0
autosave_enabled = True
recent_files = []

# Editor settings (saved to config)
piano_keys_mode = True  # True: number keys play sharps; False: 1-3 select octave (tracker style)
highlight_interval = 4  # Row highlight interval: 2, 4, 8, or 16


# =============================================================================
# FORMATTING FUNCTIONS
# =============================================================================

def fmt(val: int, width: int = 2) -> str:
    """Format number - hex or decimal based on mode."""
    if state.hex_mode:
        return f"{val:0{width}X}"
    else:
        dec_width = max(width + 1, 3)
        return f"{val:0{dec_width}d}"


def fmt_inst(val: int) -> str:
    """Format instrument number."""
    return f"{val:02X}" if state.hex_mode else f"{val:03d}"


def fmt_vol(val: int) -> str:
    """Format volume value."""
    return f"{val:X}" if state.hex_mode else f"{val:02d}"


def parse_int_value(text: str, default: int = 0) -> int:
    """Parse int from string in current mode."""
    try:
        if state.hex_mode:
            text = text.strip().upper()
            if text.startswith("0X"):
                text = text[2:]
            return int(text, 16)
        else:
            return int(text.strip())
    except:
        return default


# =============================================================================
# CONFIG MANAGEMENT
# =============================================================================

def load_config():
    """Load configuration from disk."""
    global autosave_enabled, recent_files, piano_keys_mode, highlight_interval
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                autosave_enabled = cfg.get('autosave_enabled', True)
                recent_files = cfg.get('recent_files', [])[:MAX_RECENT]
                ed = cfg.get('editor_settings', {})
                state.hex_mode = ed.get('hex_mode', True)
                state.octave = ed.get('octave', 2)
                state.step = ed.get('step', 1)
                state.follow = ed.get('follow', True)
                # New settings
                piano_keys_mode = ed.get('piano_keys_mode', True)
                highlight_interval = ed.get('highlight_interval', 4)
                # Validate highlight_interval
                if highlight_interval not in [2, 4, 8, 16]:
                    highlight_interval = 4
                logger.info("Config loaded")
    except Exception as e:
        logger.error(f"Config load error: {e}")


def save_config():
    """Save configuration to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = {
            'autosave_enabled': autosave_enabled,
            'recent_files': recent_files[:MAX_RECENT],
            'editor_settings': {
                'hex_mode': state.hex_mode,
                'octave': state.octave,
                'step': state.step,
                'follow': state.follow,
                # New settings
                'piano_keys_mode': piano_keys_mode,
                'highlight_interval': highlight_interval,
            }
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"Config save error: {e}")


def add_recent_file(path: str):
    """Add file to recent files list."""
    global recent_files
    if path in recent_files:
        recent_files.remove(path)
    recent_files.insert(0, path)
    recent_files = recent_files[:MAX_RECENT]
    save_config()


def get_autosave_files() -> list:
    """Get list of autosave files sorted by modification time."""
    try:
        files = list(AUTOSAVE_DIR.glob("*.pvq"))
        return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
    except:
        return []


def do_autosave():
    """Perform autosave if enabled and song is modified."""
    global last_autosave
    if not autosave_enabled or not state.song.modified:
        return
    
    try:
        from file_io import save_project, EditorState, work_dir
        
        # Save original file_path - autosave should not change it
        original_path = state.song.file_path
        original_modified = state.song.modified
        
        # Determine autosave folder
        # If project has been saved, use autosave folder next to project
        # Otherwise use global config autosave folder
        if original_path:
            project_dir = Path(original_path).parent
            autosave_dir = project_dir / "autosave"
        else:
            autosave_dir = AUTOSAVE_DIR
        
        autosave_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        title = state.song.title or "untitled"
        title = "".join(c for c in title if c.isalnum() or c in "_ -")[:20]
        filename = autosave_dir / f"autosave_{title}_{timestamp}.pvq"
        
        # Create editor state from current state
        editor_state = EditorState(
            songline=state.songline,
            row=state.row,
            channel=state.channel,
            column=state.column,
            song_cursor_row=state.song_cursor_row,
            song_cursor_col=state.song_cursor_col,
            octave=state.octave,
            step=state.step,
            instrument=state.instrument,
            volume=state.volume,
            selected_pattern=state.selected_pattern,
            hex_mode=state.hex_mode,
            follow=state.follow,
            focus=state.focus,
            vq_converted=state.vq.is_valid,
            vq_rate=state.vq.rate,
            vq_vector_size=state.vq.vector_size,
            vq_smoothness=state.vq.smoothness
        )
        
        save_project(state.song, editor_state, str(filename), work_dir)
        
        # Restore original path and modified flag - autosave is invisible to user
        state.song.file_path = original_path
        state.song.modified = original_modified
        
        last_autosave = time.time()
        logger.info(f"Autosaved: {filename}")
        
        # Clean up old autosaves in this folder
        try:
            autosaves = sorted(autosave_dir.glob("autosave_*.pvq"), 
                             key=lambda f: f.stat().st_mtime, reverse=True)
            for old in autosaves[MAX_AUTOSAVES:]:
                old.unlink()
        except:
            pass
    except Exception as e:
        logger.error(f"Autosave error: {e}")


def check_autosave():
    """Check if autosave is needed."""
    global last_autosave
    if autosave_enabled and state.song.modified:
        if time.time() - last_autosave >= AUTOSAVE_INTERVAL:
            do_autosave()


# =============================================================================
# FOCUS AND STATUS
# =============================================================================

def set_focus(area: int):
    """Set focus to a UI area and update panel themes."""
    state.focus = area
    
    panels = [
        ("song_panel", FOCUS_SONG),
        ("pattern_panel", FOCUS_PATTERN),
        ("inst_panel", FOCUS_INSTRUMENTS),
        ("editor_panel", FOCUS_EDITOR),
    ]
    
    for tag, focus_id in panels:
        if dpg.does_item_exist(tag):
            if area == focus_id:
                dpg.bind_item_theme(tag, "theme_panel_focused")
            else:
                dpg.bind_item_theme(tag, "theme_panel_normal")
    
    update_focus_indicator()


def update_focus_indicator():
    """Update focus indicator in status bar."""
    if not dpg.does_item_exist("focus_indicator"):
        return
    focus_names = {
        FOCUS_SONG: "SONG",
        FOCUS_PATTERN: "PATTERN",
        FOCUS_INSTRUMENTS: "INSTRUMENTS",
        FOCUS_INFO: "INFO",
        FOCUS_EDITOR: "EDITOR"
    }
    dpg.set_value("focus_indicator", f"Focus: {focus_names.get(state.focus, 'EDITOR')}")


def show_status(msg: str):
    """Show status message in status bar."""
    if dpg.does_item_exist("status_text"):
        dpg.set_value("status_text", msg)


def update_title():
    """Update window title with song name and modified indicator."""
    mod = "*" if state.song.modified else ""
    name = state.song.title or "Untitled"
    dpg.set_viewport_title(f"{mod}{name} - {APP_NAME}")


def on_input_focus(sender, data):
    """Called when a text input gains focus."""
    state.set_input_active(True)


def on_input_blur(sender, data):
    """Called when a text input loses focus."""
    state.set_input_active(False)
