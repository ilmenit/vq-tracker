"""POKEY VQ Tracker - UI Global State and Formatting"""
import dearpygui.dearpygui as dpg
import json
import time
import logging
from pathlib import Path
from constants import (APP_NAME, FOCUS_SONG, FOCUS_PATTERN, FOCUS_INSTRUMENTS, 
                       FOCUS_INFO, FOCUS_EDITOR, MAX_VOLUME, DEFAULT_OCTAVE)
from state import state

logger = logging.getLogger("tracker.ui")

# =============================================================================
# PATHS AND CONSTANTS
# =============================================================================
# Config and autosave locations: relative to app directory (where tracker is)
# These will be set by init_paths() called from main.py
APP_DIR = Path(__file__).parent  # Default to script directory
CONFIG_FILE = APP_DIR / "tracker_config.json"  # Config in app root
AUTOSAVE_DIR = APP_DIR / ".tmp" / "autosave"  # Autosave in .tmp/autosave/
MAX_AUTOSAVES = 20
AUTOSAVE_INTERVAL = 30
MAX_RECENT = 10

def init_paths(app_dir: str):
    """Initialize paths based on application directory."""
    global APP_DIR, CONFIG_FILE, AUTOSAVE_DIR
    APP_DIR = Path(app_dir)
    CONFIG_FILE = APP_DIR / "tracker_config.json"
    AUTOSAVE_DIR = APP_DIR / ".tmp" / "autosave"
    # Create autosave directory
    AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)

# UI SIZING
TOP_PANEL_HEIGHT = 230
EDITOR_WIDTH = 640
SONG_INFO_WIDTH = 225
INPUT_ROW_HEIGHT = 40
EDITOR_HEADER_HEIGHT = 85
MIN_VISIBLE_ROWS = 1
MAX_VISIBLE_ROWS = 50
SONG_VISIBLE_ROWS = 5
SONG_PANEL_WIDTH = 340


def compute_editor_width(hex_mode, show_volume):
    """Calculate the correct editor panel width for current settings.
    
    DPG inserts item_spacing (8px) between EVERY adjacent widget in a
    horizontal group.  We must count all widgets and all gaps exactly.
    
    Row layout (no volume):
      [RowBtn] [Spacer4] [Note1][Inst1] [SpacerCH] [Note2][Inst2] ...
      
    Item count = 1(row) + 1(spc4) + CH*(note+inst) + (CH-1)*spacerCH
    With volume: + CH*vol extra items
    IS gaps = (item_count - 1) * 8
    """
    row_num_w = 32 if hex_mode else 40
    note_w = 44
    inst_w = 32 if hex_mode else 40
    vol_w = 24 if hex_mode else 30
    ch_spacer = 12
    item_spacing = 8  # DPG default horizontal item spacing
    spacer_lead = 4   # small spacer after row number
    
    from constants import MAX_CHANNELS
    
    # Count widgets and their widths
    items_per_ch = 2  # note + inst buttons
    if show_volume:
        items_per_ch = 3  # + vol button
    
    n_items = (1                                 # row number button
               + 1                               # leading spacer(4)
               + MAX_CHANNELS * items_per_ch     # data buttons
               + (MAX_CHANNELS - 1))             # inter-channel spacers
    
    widget_widths = (row_num_w + spacer_lead
                     + MAX_CHANNELS * (note_w + inst_w + (vol_w if show_volume else 0))
                     + (MAX_CHANNELS - 1) * ch_spacer)
    
    is_total = (n_items - 1) * item_spacing
    
    # Window chrome: padding (8px each side) + border (1px each) + scrollbar room
    chrome = 32
    
    return widget_widths + is_total + chrome

# =============================================================================
# SHARED STATE
# =============================================================================
visible_rows = 11
play_row = -1
play_songline = -1
last_autosave = 0
autosave_enabled = True
recent_files = []

# Editor settings (saved to config)
piano_keys_mode = True  # True: number keys play sharps; False: 1-3 select octave (tracker style)
highlight_interval = 4  # Row highlight interval: 2, 4, 8, or 16
coupled_entry = True    # True: note entry always stamps inst+vol; False: only change note in occupied cells

# Cell color palettes (stored in local config, not .pvq)
note_palette = "Chromatic"  # Palette for note column coloring
inst_palette = "Chromatic"  # Palette for instrument column coloring
vol_palette = "Chromatic"   # Palette for volume column coloring
ptn_palette = "Chromatic"   # Palette for pattern number coloring (Song grid, combos)


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
    except (ValueError, TypeError):
        return default


# =============================================================================
# CONFIG MANAGEMENT
# =============================================================================

def load_config():
    """Load configuration from disk."""
    global autosave_enabled, recent_files, piano_keys_mode, highlight_interval, coupled_entry
    global note_palette, inst_palette, vol_palette, ptn_palette
    logger.debug(f"Loading config from: {CONFIG_FILE}")
    try:
        AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                autosave_enabled = cfg.get('autosave_enabled', True)
                recent_files = cfg.get('recent_files', [])[:MAX_RECENT]
                ed = cfg.get('editor_settings', {})
                state.hex_mode = ed.get('hex_mode', True)
                state.octave = ed.get('octave', DEFAULT_OCTAVE)
                state.step = ed.get('step', 1)
                state.follow = ed.get('follow', True)
                # New settings
                piano_keys_mode = ed.get('piano_keys_mode', True)
                highlight_interval = ed.get('highlight_interval', 4)
                coupled_entry = ed.get('coupled_entry', True)
                # Cell color palettes
                colors = ed.get('cell_colors', {})
                note_palette = colors.get('note', 'Chromatic')
                inst_palette = colors.get('instrument', 'Chromatic')
                vol_palette = colors.get('volume', 'Chromatic')
                ptn_palette = colors.get('pattern', 'Chromatic')
                # Validate
                from cell_colors import PALETTE_NAMES
                if note_palette not in PALETTE_NAMES:
                    note_palette = 'Chromatic'
                if inst_palette not in PALETTE_NAMES:
                    inst_palette = 'Chromatic'
                if vol_palette not in PALETTE_NAMES:
                    vol_palette = 'Chromatic'
                if ptn_palette not in PALETTE_NAMES:
                    ptn_palette = 'Chromatic'
                # Validate highlight_interval
                if highlight_interval not in [2, 4, 8, 16]:
                    highlight_interval = 4
                logger.info(f"Config loaded, {len(recent_files)} recent files")
                logger.debug(f"Recent files: {recent_files}")
        else:
            logger.info(f"Config file not found: {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Config load error: {e}")


def save_config():
    """Save configuration to disk."""
    try:
        # Ensure parent directory exists
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg = {
            'autosave_enabled': autosave_enabled,
            'recent_files': recent_files[:MAX_RECENT],
            'editor_settings': {
                'hex_mode': state.hex_mode,
                'octave': state.octave,
                'step': state.step,
                'follow': state.follow,
                'piano_keys_mode': piano_keys_mode,
                'highlight_interval': highlight_interval,
                'coupled_entry': coupled_entry,
                'cell_colors': {
                    'note': note_palette,
                    'instrument': inst_palette,
                    'volume': vol_palette,
                    'pattern': ptn_palette,
                },
            }
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
        logger.debug(f"Config saved to {CONFIG_FILE}")
        logger.debug(f"Recent files: {recent_files}")
    except Exception as e:
        logger.error(f"Config save error: {e}")


def add_recent_file(path: str):
    """Add file to recent files list."""
    global recent_files
    logger.debug(f"add_recent_file: {path}")
    if path in recent_files:
        recent_files.remove(path)
    recent_files.insert(0, path)
    recent_files = recent_files[:MAX_RECENT]
    save_config()
    logger.debug(f"Recent files now: {recent_files}")


def get_autosave_files() -> list:
    """Get list of autosave files sorted by modification time."""
    try:
        files = list(AUTOSAVE_DIR.glob("*.pvq"))
        return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
    except Exception:
        return []


def do_autosave():
    """Perform autosave if enabled and song is modified."""
    global last_autosave
    if not autosave_enabled or not state.song.modified:
        return
    
    try:
        import file_io
        from file_io import save_project, EditorState
        
        # Save original file_path - autosave should not change it
        original_path = state.song.file_path
        original_modified = state.song.modified
        
        # Always use .tmp/autosave folder (not project-specific autosave)
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
            vq_smoothness=state.vq.smoothness,
            vq_enhance=state.vq.settings.enhance,
        )
        
        save_project(state.song, editor_state, str(filename), file_io.work_dir)
        
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
        except Exception as e:
            logger.debug(f"Autosave cleanup error: {e}")
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
