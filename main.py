"""Atari Sample Tracker - Main Entry Point (v3.16 - Refactored)

This is the main entry point that ties together all UI modules:
- ui_globals.py  - Global state, config, formatting functions
- ui_refresh.py  - UI refresh/update functions
- ui_callbacks.py - Event handlers and callbacks
- ui_build.py    - UI construction functions
"""
import dearpygui.dearpygui as dpg
import logging
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
    ops.set_playback_row_callback(C.on_playback_row)
    ops.set_playback_stop_callback(C.on_playback_stop)


# =============================================================================
# MAIN
# =============================================================================
def main():
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
    
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
    
    # Main loop with autosave check
    while dpg.is_dearpygui_running():
        state.audio.process_callbacks()  # Process audio engine callbacks
        G.check_autosave()
        C.poll_vq_conversion()  # Poll VQ conversion status (thread-safe)
        C.poll_build_progress()  # Poll build progress (thread-safe)
        dpg.render_dearpygui_frame()
    
    # Cleanup
    state.audio.stop()
    state.vq.cleanup()  # Clean up VQ temp directory
    dpg.destroy_context()
    logger.info("Tracker closed")


if __name__ == "__main__":
    main()
