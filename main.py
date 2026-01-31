"""POKEY VQ Tracker - Main Entry Point (v3.17 - ZIP Project Format)

This is the main entry point that ties together all UI modules:
- ui_globals.py  - Global state, config, formatting functions
- ui_refresh.py  - UI refresh/update functions
- ui_callbacks.py - Event handlers and callbacks
- ui_build.py    - UI construction functions
"""
import dearpygui.dearpygui as dpg
import logging
import sys
import os
from constants import APP_NAME, APP_VERSION, WIN_WIDTH, WIN_HEIGHT
from state import state
from ui_theme import create_themes
from keyboard import handle_key
import operations as ops

# Import UI modules
import ui_globals as G
import ui_refresh as R
import ui_callbacks as C
import ui_build as B

# Import file_io for working directory
import file_io

# =============================================================================
# LOGGING SETUP
# =============================================================================
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("tracker.main")


# =============================================================================
# OPERATIONS CALLBACKS SETUP
# =============================================================================
def setup_operations_callbacks():
    """Wire up operations module to UI refresh functions."""
    from ui_dialogs import show_error, show_file_dialog, show_rename_dialog
    
    ops.refresh_all = R.refresh_all
    ops.refresh_editor = R.refresh_editor
    ops.refresh_song_editor = R.refresh_song_editor
    ops.refresh_songlist = R.refresh_song_editor
    ops.refresh_instruments = R.refresh_instruments
    ops.refresh_pattern_combo = R.refresh_pattern_info
    ops.refresh_all_pattern_combos = R.refresh_all_pattern_combos
    ops.refresh_all_instrument_combos = R.refresh_all_instrument_combos
    ops.update_controls = R.update_controls
    ops.show_status = G.show_status
    ops.update_title = G.update_title
    ops.show_error = show_error
    ops.show_confirm = B.show_confirm_centered
    ops.show_file_dialog = show_file_dialog
    ops.show_rename_dialog = show_rename_dialog
    ops.rebuild_recent_menu = B.rebuild_recent_menu
    ops.set_playback_row_callback(C.on_playback_row)
    ops.set_playback_stop_callback(C.on_playback_stop)


def try_load_last_project():
    """Try to load the most recent project on startup."""
    from file_io import load_project
    from constants import MAX_VOLUME
    
    if not G.recent_files:
        logger.info("No recent files to load")
        return
    
    # Try the most recent file
    last_file = G.recent_files[0]
    if not os.path.exists(last_file):
        logger.info(f"Last project not found: {last_file}")
        return
    
    logger.info(f"Loading last project: {last_file}")
    
    try:
        song, editor_state, msg = load_project(last_file, file_io.work_dir)
        if song:
            state.audio.stop_playback()
            state.song = song
            state.undo.clear()
            
            # Restore editor state if available
            if editor_state:
                state.songline = editor_state.songline
                state.row = editor_state.row
                state.channel = editor_state.channel
                state.column = editor_state.column
                state.song_cursor_row = editor_state.song_cursor_row
                state.song_cursor_col = editor_state.song_cursor_col
                state.octave = editor_state.octave
                state.step = editor_state.step
                state.instrument = editor_state.instrument
                state.volume = editor_state.volume
                state.selected_pattern = editor_state.selected_pattern
                state.hex_mode = editor_state.hex_mode
                state.follow = editor_state.follow
                
                # Restore VQ settings (conversion will happen automatically)
                state.vq.settings.rate = editor_state.vq_rate
                state.vq.settings.vector_size = editor_state.vq_vector_size
                state.vq.settings.smoothness = editor_state.vq_smoothness
                state.vq.settings.enhance = editor_state.vq_enhance
                state.vq.settings.optimize_speed = editor_state.vq_optimize_speed
                
                # VQ output not loaded - will be regenerated
                state.vq.invalidate()
            else:
                state.songline = state.row = state.channel = 0
                state.instrument = 0
                state.song_cursor_row = state.song_cursor_col = 0
                state.volume = MAX_VOLUME
                state.vq.invalidate()
            
            state.selection.clear()
            state.audio.set_song(state.song)
            R.refresh_all()
            G.update_title()
            G.show_status(f"Loaded: {os.path.basename(last_file)}")
            logger.info(f"Successfully loaded: {last_file}")
            
            # Auto-convert samples to regenerate VQ data with latest algorithm
            _trigger_auto_conversion_startup()
        else:
            logger.warning(f"Failed to load last project: {msg}")
    except Exception as e:
        logger.error(f"Error loading last project: {e}")


def _trigger_auto_conversion_startup():
    """Auto-trigger VQ conversion after loading project at startup.
    
    Uses sample_path (extracted files in work_dir) rather than original_sample_path,
    since the original files may no longer exist on the user's disk.
    """
    # Collect input files from extracted samples
    input_files = []
    for inst in state.song.instruments:
        if inst.sample_path and os.path.exists(inst.sample_path):
            input_files.append(inst.sample_path)
    
    if not input_files:
        return
    
    # Trigger conversion with extracted samples
    C.show_vq_conversion_window(input_files)


# =============================================================================
# MAIN
# =============================================================================
def main():
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
    
    # Get application directory
    app_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Initialize working directory
    work_dir = file_io.init_working_directory(app_dir)
    logger.info(f"Working directory: {work_dir.root}")
    
    # Check instance lock
    instance_lock = file_io.InstanceLock(app_dir)
    ok, lock_msg = instance_lock.acquire()
    if not ok:
        # Show error dialog and exit
        logger.error(f"Instance lock failed: {lock_msg}")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Instance Already Running",
                f"{APP_NAME} is already running.\n\n{lock_msg}\n\n"
                "Please close the other instance first."
            )
            root.destroy()
        except:
            print(f"ERROR: {lock_msg}")
        sys.exit(1)
    
    logger.info("Instance lock acquired")
    
    # Initialize config paths (must be before load_config)
    G.init_paths(app_dir)
    
    # Load config first
    G.load_config()
    
    # Initialize DearPyGui
    dpg.create_context()
    dpg.create_viewport(title=APP_NAME, width=WIN_WIDTH, height=WIN_HEIGHT, 
                        min_width=800, min_height=500)
    
    # Create themes
    create_themes()
    
    # Initialize modules with cross-references
    R.set_instrument_callbacks(C.preview_instrument, C.select_inst_click)
    C.init_callbacks(B.rebuild_editor_grid, B.show_confirm_centered)
    
    # Build UI
    B.build_ui()
    B.rebuild_recent_menu()
    
    # Initialize custom file browser (must be after DPG context created)
    from ui_browser import get_file_browser
    get_file_browser()  # Creates the browser window
    
    # Setup operations callbacks
    setup_operations_callbacks()
    
    # Initial refresh
    R.refresh_all()
    G.update_title()
    
    # Register handlers
    with dpg.handler_registry():
        dpg.add_key_press_handler(callback=handle_key)
        dpg.add_mouse_click_handler(callback=C.on_global_mouse_click)
    
    # Viewport resize handler
    dpg.set_viewport_resize_callback(C.on_viewport_resize)
    
    # Setup and show
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    
    # Initial visible rows calculation
    G.visible_rows = C.calculate_visible_rows()
    B.rebuild_editor_grid()
    R.refresh_editor()
    
    # Start audio
    state.audio.start()
    state.audio.set_song(state.song)  # Link song to audio engine
    logger.info("Audio engine started")
    
    # Try to load last project on startup
    try_load_last_project()
    
    # Main loop with autosave check
    while dpg.is_dearpygui_running():
        state.audio.process_callbacks()  # Process audio engine callbacks
        G.check_autosave()
        C.poll_vq_conversion()  # Poll VQ conversion status (thread-safe)
        C.poll_build_progress()  # Poll build progress (thread-safe)
        C.poll_button_blink()   # Update blinking attention buttons
        dpg.render_dearpygui_frame()
    
    # Cleanup
    G.save_config()  # Save config (including recent files) on exit
    state.audio.stop()
    state.vq.cleanup()  # Clean up VQ temp directory
    instance_lock.release()  # Release instance lock
    dpg.destroy_context()
    logger.info("Tracker closed")


if __name__ == "__main__":
    main()
