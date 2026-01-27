"""Atari Sample Tracker - UI Dialogs"""
import dearpygui.dearpygui as dpg
from constants import COL_DIM, COL_ACCENT, COL_TEXT, APP_NAME, APP_VERSION

# Callback storage
_file_callback = None
_file_multi = False

def show_file_dialog(title: str, extensions: list, callback, 
                     save_mode: bool = False, dir_mode: bool = False, multi: bool = False):
    """Show file dialog."""
    global _file_callback, _file_multi
    _file_callback = callback
    _file_multi = multi
    
    if dpg.does_item_exist("file_dialog"):
        dpg.delete_item("file_dialog")
    
    with dpg.file_dialog(
        tag="file_dialog",
        directory_selector=dir_mode,
        show=True,
        callback=_on_file_ok,
        cancel_callback=_on_file_cancel,
        width=700,
        height=450,
        modal=True
    ):
        if extensions:
            for ext in extensions:
                dpg.add_file_extension(ext)
            dpg.add_file_extension(".*")


def _on_file_ok(sender, data):
    global _file_callback, _file_multi
    if _file_callback:
        if _file_multi and 'selections' in data and len(data['selections']) > 0:
            paths = list(data['selections'].values())
            _file_callback(paths)
        elif 'file_path_name' in data:
            _file_callback(data['file_path_name'])
        elif 'selections' in data and data['selections']:
            _file_callback(list(data['selections'].values())[0])
    _file_callback = None


def _on_file_cancel(sender, data):
    global _file_callback
    _file_callback = None


def show_confirm(title: str, message: str, callback):
    """Show confirmation dialog centered on viewport."""
    if dpg.does_item_exist("confirm_dialog"):
        dpg.delete_item("confirm_dialog")
    
    def on_ok():
        dpg.delete_item("confirm_dialog")
        callback()
    
    def on_cancel():
        dpg.delete_item("confirm_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 320, 120
    
    with dpg.window(
        tag="confirm_dialog",
        label=title,
        modal=True,
        width=w,
        height=h,
        pos=[(vp_w - w) // 2, (vp_h - h) // 2],
        no_resize=True,
        no_collapse=True
    ):
        dpg.add_text(message)
        dpg.add_spacer(height=15)
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=80, callback=on_ok)
            dpg.add_spacer(width=10)
            dpg.add_button(label="Cancel", width=80, callback=on_cancel)


def show_error(title: str, message: str):
    """Show error dialog centered on viewport."""
    if dpg.does_item_exist("error_dialog"):
        dpg.delete_item("error_dialog")
    
    def on_close():
        dpg.delete_item("error_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 360, 130
    
    with dpg.window(
        tag="error_dialog",
        label=title,
        modal=True,
        width=w,
        height=h,
        pos=[(vp_w - w) // 2, (vp_h - h) // 2],
        no_resize=True,
        no_collapse=True
    ):
        dpg.add_text(message, wrap=340)
        dpg.add_spacer(height=15)
        dpg.add_button(label="OK", width=80, callback=on_close)


def show_rename_dialog(title: str, current_name: str, callback):
    """Show rename dialog centered on viewport."""
    if dpg.does_item_exist("rename_dialog"):
        dpg.delete_item("rename_dialog")
    
    def on_ok():
        name = dpg.get_value("rename_input")
        dpg.delete_item("rename_dialog")
        callback(name)
    
    def on_cancel():
        dpg.delete_item("rename_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 320, 110
    
    with dpg.window(
        tag="rename_dialog",
        label=title,
        modal=True,
        width=w,
        height=h,
        pos=[(vp_w - w) // 2, (vp_h - h) // 2],
        no_resize=True,
        no_collapse=True
    ):
        dpg.add_input_text(tag="rename_input", default_value=current_name, width=-1)
        dpg.add_spacer(height=15)
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=80, callback=on_ok)
            dpg.add_spacer(width=10)
            dpg.add_button(label="Cancel", width=80, callback=on_cancel)


def show_about():
    """Show about dialog."""
    if dpg.does_item_exist("about_dialog"):
        dpg.delete_item("about_dialog")
    
    def on_close():
        dpg.delete_item("about_dialog")
    
    with dpg.window(
        tag="about_dialog",
        label="About",
        modal=True,
        width=340,
        height=200,
        pos=[530, 340],
        no_resize=True,
        no_collapse=True
    ):
        dpg.add_text(f"{APP_NAME}", color=COL_ACCENT)
        dpg.add_text(f"Version {APP_VERSION}")
        dpg.add_spacer(height=10)
        dpg.add_text("Sample-based music tracker for", color=COL_DIM)
        dpg.add_text("Atari XL/XE 8-bit computers", color=COL_DIM)
        dpg.add_spacer(height=10)
        dpg.add_text("Features:", color=COL_DIM)
        dpg.add_text("  - 3 channel polyphonic playback", color=COL_DIM)
        dpg.add_text("  - WAV sample import", color=COL_DIM)
        dpg.add_text("  - Export to ASM/binary", color=COL_DIM)
        dpg.add_spacer(height=10)
        dpg.add_button(label="Close", width=80, callback=on_close)


def show_shortcuts():
    """Show keyboard shortcuts dialog (no unicode)."""
    if dpg.does_item_exist("shortcuts_dialog"):
        dpg.delete_item("shortcuts_dialog")
    
    def on_close():
        dpg.delete_item("shortcuts_dialog")
    
    with dpg.window(
        tag="shortcuts_dialog",
        label="Keyboard Shortcuts",
        modal=True,
        width=450,
        height=520,
        pos=[475, 180],
        no_resize=True,
        no_collapse=True
    ):
        # Navigation
        dpg.add_text("NAVIGATION", color=COL_ACCENT)
        dpg.add_text("  Arrow Keys     Move cursor")
        dpg.add_text("  Shift+Up/Down  Extend selection")
        dpg.add_text("  Tab            Next channel")
        dpg.add_text("  Shift+Tab      Previous channel")
        dpg.add_text("  Page Up/Down   Jump 16 rows")
        dpg.add_text("  Home/End       First/last row")
        dpg.add_text("  Ctrl+Home/End  First/last songline")
        
        dpg.add_spacer(height=8)
        dpg.add_text("EDITING", color=COL_ACCENT)
        dpg.add_text("  Z-M, Q-P       Piano keys (2 octaves)")
        dpg.add_text("  2,3,5,6,7,9,0  Sharp notes")
        dpg.add_text("  0-9, A-F       Hex values (inst/vol)")
        dpg.add_text("  Delete         Clear cell")
        dpg.add_text("  Backspace      Clear and move up")
        dpg.add_text("  Insert         Insert row")
        dpg.add_text("  * (numpad)     Octave up")
        dpg.add_text("  - (minus)      Octave down")
        dpg.add_text("  [ / ]          Prev/next instrument")
        
        dpg.add_spacer(height=8)
        dpg.add_text("CLIPBOARD", color=COL_ACCENT)
        dpg.add_text("  Ctrl+C         Copy cells")
        dpg.add_text("  Ctrl+X         Cut cells")
        dpg.add_text("  Ctrl+V         Paste cells")
        
        dpg.add_spacer(height=8)
        dpg.add_text("PLAYBACK", color=COL_ACCENT)
        dpg.add_text("  Space          Play/stop")
        dpg.add_text("  F5             Play pattern")
        dpg.add_text("  F6             Play song from start")
        dpg.add_text("  F7             Play from current line")
        dpg.add_text("  F8             Stop")
        dpg.add_text("  Enter          Preview current row")
        
        dpg.add_spacer(height=8)
        dpg.add_text("FILE", color=COL_ACCENT)
        dpg.add_text("  Ctrl+N         New project")
        dpg.add_text("  Ctrl+O         Open project")
        dpg.add_text("  Ctrl+S         Save project")
        dpg.add_text("  Ctrl+Shift+S   Save as")
        dpg.add_text("  Ctrl+Z / Y     Undo / Redo")
        
        dpg.add_spacer(height=12)
        dpg.add_button(label="Close", width=80, callback=on_close)
