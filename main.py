"""POKEY VQ Tracker - Main Entry Point

This is the main entry point that ties together all UI modules:
- ui_globals.py  - Global state, config, formatting functions
- ui_refresh.py  - UI refresh/update functions
- ui_callbacks.py - Event handlers and callbacks
- ui_build.py    - UI construction functions
"""
import sys
import os
import logging
import platform
import shutil

# =============================================================================
# EARLY LOGGING SETUP (before any imports that might fail)
# =============================================================================
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG level for full diagnostic output
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]  # Explicitly use stdout
)
logger = logging.getLogger("tracker.main")

# =============================================================================
# STARTUP DIAGNOSTICS
# =============================================================================
def _setup_ffmpeg_for_pydub():
    """Set up ffmpeg path before importing pydub to avoid warning."""
    if platform.system() != "Windows":
        return  # Linux/macOS typically have ffmpeg in PATH
    
    # Determine app directory
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Search locations for ffmpeg.exe
    candidates = [
        os.path.join(app_dir, "bin", "ffmpeg"),
        os.path.join(app_dir, "bin", "windows_x86_64"),
        os.path.join(app_dir, "ffmpeg"),
        app_dir,
    ]
    
    for candidate in candidates:
        ffmpeg_exe = os.path.join(candidate, "ffmpeg.exe")
        if os.path.isfile(ffmpeg_exe):
            os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
            return

def log_startup_info():
    """Log system and environment information for debugging."""
    logger.info("=" * 60)
    logger.info("POKEY VQ Tracker - Starting")
    logger.info("=" * 60)
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {platform.system()} {platform.release()} ({platform.machine()})")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Script location: {os.path.dirname(os.path.abspath(__file__))}")

def check_dependencies():
    """Check and log status of all dependencies."""
    logger.info("-" * 40)
    logger.info("Checking dependencies...")
    
    # Set up ffmpeg path BEFORE checking pydub to avoid warning
    _setup_ffmpeg_for_pydub()
    
    # Permanently suppress pydub's ffmpeg warnings (they're noisy but harmless)
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="pydub.*")
    
    dependencies = {
        'dearpygui': 'DearPyGui (GUI framework)',
        'numpy': 'NumPy (numerical operations)',
        'scipy': 'SciPy (signal processing)',
        'sounddevice': 'SoundDevice (audio playback)',
        'pydub': 'PyDub (audio format conversion)',
    }
    
    missing = []
    for module, description in dependencies.items():
        try:
            mod = __import__(module)
            version = getattr(mod, '__version__', 'unknown')
            logger.info(f"  [OK] {description}: {version}")
        except ImportError as e:
            logger.warning(f"  [--] {description}: NOT AVAILABLE ({e})")
            missing.append(module)
    
    # Check optional components
    logger.info("Checking external folders...")
    
    # Check runtime paths
    try:
        import runtime
        logger.info(f"  [OK] Runtime mode: {'bundled' if runtime.is_bundled() else 'development'}")
        logger.info(f"       App dir: {runtime.get_app_dir()}")
        
        # Check for ASM folder
        asm_dir = runtime.get_asm_dir()
        if os.path.isdir(asm_dir) and os.path.isfile(os.path.join(asm_dir, "song_player.asm")):
            logger.info(f"  [OK] ASM templates: {asm_dir}")
        else:
            logger.warning(f"  [--] ASM templates: not found at {asm_dir}")
            logger.warning(f"       (BUILD will not work without asm/ folder)")
        
        # Check for bin folder and MADS
        bin_dir = runtime.get_bin_dir()
        mads = runtime.get_mads_path()
        if mads and os.path.isfile(mads):
            logger.info(f"  [OK] MADS assembler: {mads}")
        else:
            logger.info(f"  [--] MADS assembler: not found in {bin_dir}")
            logger.info(f"       (BUILD will not work without MADS)")
        
        # Check for vq_converter / pokey_vq
        # Try to import pokey_vq directly first (bundled or pip-installed)
        try:
            # Add vq_converter to path if it exists
            vq_base = os.path.join(runtime.get_app_dir(), "vq_converter")
            if os.path.isdir(vq_base) and vq_base not in sys.path:
                sys.path.insert(0, vq_base)
            
            from pokey_vq.cli.builder import PokeyVQBuilder
            logger.info(f"  [OK] pokey_vq: direct import available (bundled)")
        except ImportError as e:
            # Fall back to checking for external vq_converter
            vq_base = os.path.join(runtime.get_app_dir(), "vq_converter")
            vq_path = os.path.join(vq_base, "pokey_vq")
            
            if os.path.isdir(vq_path):
                # Check for standalone executable
                if platform.system() == "Windows":
                    exe_path = os.path.join(vq_base, "vq_converter.exe")
                    if os.path.isfile(exe_path):
                        logger.info(f"  [OK] vq_converter: standalone exe found")
                    else:
                        python_found = shutil.which("python") or shutil.which("python3")
                        if python_found:
                            logger.info(f"  [OK] vq_converter: subprocess mode (Python)")
                            logger.info(f"       Note: Requires numpy, scipy, soundfile")
                        else:
                            logger.info(f"  [!!] vq_converter: folder found but no Python!")
                else:
                    exe_found = False
                    for exe_name in ["vq_converter", "vq_converter.bin"]:
                        exe_path = os.path.join(vq_base, exe_name)
                        if os.path.isfile(exe_path) and os.access(exe_path, os.X_OK):
                            logger.info(f"  [OK] vq_converter: standalone binary found")
                            exe_found = True
                            break
                    if not exe_found:
                        python_found = shutil.which("python3") or shutil.which("python")
                        if python_found:
                            logger.info(f"  [OK] vq_converter: subprocess mode (Python)")
                        else:
                            logger.info(f"  [!!] vq_converter: folder found but no Python!")
            else:
                logger.info(f"  [--] vq_converter: not found (import: {e})")
        
        # Check for FFmpeg (needed for MP3/OGG/FLAC import)
        if platform.system() == "Windows":
            app_dir = runtime.get_app_dir()
            ffmpeg_paths = [
                os.path.join(bin_dir, "ffmpeg.exe"),
                os.path.join(app_dir, "bin", "windows_x86_64", "ffmpeg.exe"),
                os.path.join(app_dir, "bin", "ffmpeg", "ffmpeg.exe"),
                os.path.join(app_dir, "ffmpeg", "ffmpeg.exe"),
            ]
            ffprobe_paths = [
                os.path.join(bin_dir, "ffprobe.exe"),
                os.path.join(app_dir, "bin", "windows_x86_64", "ffprobe.exe"),
                os.path.join(app_dir, "bin", "ffmpeg", "ffprobe.exe"),
                os.path.join(app_dir, "ffmpeg", "ffprobe.exe"),
            ]
            ffmpeg_found = any(os.path.isfile(p) for p in ffmpeg_paths)
            ffprobe_found = any(os.path.isfile(p) for p in ffprobe_paths)
            
            if ffmpeg_found and ffprobe_found:
                logger.info(f"  [OK] FFmpeg: found (MP3/OGG/FLAC import enabled)")
            elif ffmpeg_found and not ffprobe_found:
                logger.info(f"  [!!] FFmpeg: ffmpeg.exe found but ffprobe.exe missing!")
                logger.info(f"       MP3/OGG import requires both files")
                logger.info(f"       Download from: https://www.gyan.dev/ffmpeg/builds/")
            else:
                logger.info(f"  [--] FFmpeg: not found (only WAV import available)")
                logger.info(f"       Place ffmpeg.exe and ffprobe.exe in: {os.path.join(app_dir, 'bin', 'windows_x86_64')}")
        
    except Exception as e:
        logger.error(f"  [!!] Runtime module error: {e}")
    
    logger.info("-" * 40)
    
    if 'dearpygui' in missing or 'numpy' in missing:
        logger.error("Critical dependencies missing! Cannot start.")
        return False
    
    if 'sounddevice' in missing:
        logger.warning("Audio playback will not be available")
    
    if 'pydub' in missing:
        logger.warning("Only WAV import supported (pydub not installed)")
    else:
        # pydub is installed - check if ffmpeg is actually available
        try:
            from file_io import FFMPEG_OK
            if not FFMPEG_OK:
                logger.warning("Only WAV import supported (FFmpeg not found)")
        except ImportError:
            pass
    
    return True

# Run early diagnostics
log_startup_info()
if not check_dependencies():
    logger.error("Exiting due to missing critical dependencies")
    sys.exit(1)

# =============================================================================
# MAIN IMPORTS (after dependency check)
# =============================================================================
logger.debug("Loading main modules...")

import dearpygui.dearpygui as dpg
from constants import APP_NAME, APP_VERSION, WIN_WIDTH, WIN_HEIGHT
from state import state
from ui_theme import create_themes
from keyboard import handle_key
import operations as ops
import runtime  # Bundle/dev mode detection

# Import UI modules
import ui_globals as G
import ui_refresh as R
import ui_callbacks as C
import ui_build as B

# Import file_io for working directory
import file_io

logger.debug("All modules loaded successfully")


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
    logger.info("-" * 60)
    logger.info(f"Initializing {APP_NAME} {APP_VERSION}")
    logger.info("-" * 60)
    
    # Get application directory (works in both dev and bundled modes)
    app_dir = runtime.get_app_dir()
    logger.debug(f"Application directory: {app_dir}")
    
    # Initialize working directory
    try:
        work_dir = file_io.init_working_directory(app_dir)
        logger.info(f"Working directory: {work_dir.root}")
    except Exception as e:
        logger.error(f"Failed to initialize working directory: {e}")
        raise
    
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
    
    logger.debug("Instance lock acquired")
    
    # Initialize config paths (must be before load_config)
    G.init_paths(app_dir)
    logger.debug(f"Config file: {G.CONFIG_FILE}")
    logger.debug(f"Autosave dir: {G.AUTOSAVE_DIR}")
    
    # Load config first
    G.load_config()
    logger.debug(f"Loaded {len(G.recent_files)} recent files from config")
    
    # Initialize DearPyGui
    logger.debug("Creating DearPyGui context...")
    dpg.create_context()
    dpg.create_viewport(title=APP_NAME, width=WIN_WIDTH, height=WIN_HEIGHT, 
                        min_width=800, min_height=500)
    
    # Create themes
    create_themes()
    logger.debug("UI themes created")
    
    # Initialize modules with cross-references
    R.set_instrument_callbacks(C.preview_instrument, C.select_inst_click)
    C.init_callbacks(B.rebuild_editor_grid, B.show_confirm_centered)
    
    # Build UI
    logger.debug("Building UI...")
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
    try:
        state.audio.start()
        state.audio.set_song(state.song)  # Link song to audio engine
        logger.info("Audio engine started")
    except Exception as e:
        logger.warning(f"Audio engine failed to start: {e}")
        logger.warning("Audio preview will not be available")
    
    # Try to load last project on startup
    try_load_last_project()
    
    logger.info("-" * 60)
    logger.info("Ready! Entering main loop...")
    logger.info("-" * 60)
    
    # Main loop with autosave check
    try:
        while dpg.is_dearpygui_running():
            state.audio.process_callbacks()  # Process audio engine callbacks
            G.check_autosave()
            C.poll_vq_conversion()  # Poll VQ conversion status (thread-safe)
            C.poll_build_progress()  # Poll build progress (thread-safe)
            C.poll_button_blink()   # Update blinking attention buttons
            dpg.render_dearpygui_frame()
    except Exception as e:
        logger.exception(f"Error in main loop: {e}")
        raise
    finally:
        # Cleanup
        logger.info("Shutting down...")
        G.save_config()  # Save config (including recent files) on exit
        state.audio.stop()
        state.vq.cleanup()  # Clean up VQ temp directory
        instance_lock.release()  # Release instance lock
        dpg.destroy_context()
        logger.info("Tracker closed normally")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        print("\n" + "=" * 60)
        print("FATAL ERROR - Press Enter to exit...")
        print("=" * 60)
        input()  # Keep console open on Windows
        sys.exit(1)
