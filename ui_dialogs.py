"""
Atari Sample Tracker - UI Dialogs
File dialogs, confirmation dialogs, about/help.
"""

import dearpygui.dearpygui as dpg
from typing import Callable, Optional

from constants import COLORS, WIN_WIDTH, WIN_HEIGHT, APP_NAME, APP_VERSION

# Callback storage
_callback: Optional[Callable] = None

# =============================================================================
# FILE DIALOG
# =============================================================================

def show_file_dialog(title: str, exts: list, callback: Callable,
                     save_mode: bool = False, dir_mode: bool = False):
    """Show file selection dialog."""
    global _callback
    _callback = callback
    
    if dpg.does_item_exist("file_dlg"):
        dpg.delete_item("file_dlg")
    
    with dpg.file_dialog(
        label=title, directory_selector=dir_mode, show=True,
        callback=_file_ok, cancel_callback=_file_cancel,
        width=620, height=380, modal=True, tag="file_dlg"
    ):
        if not dir_mode:
            for ext in exts:
                dpg.add_file_extension(ext, color=(150, 255, 150, 255))

def _file_ok(sender, data, user_data):
    global _callback
    path = ""
    if data:
        path = data.get('file_path_name', '')
        if not path and 'selections' in data:
            sel = data['selections']
            if sel:
                path = list(sel.values())[0]
    if dpg.does_item_exist("file_dlg"):
        dpg.delete_item("file_dlg")
    if _callback:
        _callback(path)

def _file_cancel(sender, data, user_data):
    if dpg.does_item_exist("file_dlg"):
        dpg.delete_item("file_dlg")

# =============================================================================
# CONFIRMATION DIALOG
# =============================================================================

def show_confirm(title: str, msg: str, on_yes: Callable):
    """Show confirmation dialog."""
    global _callback
    _callback = on_yes
    
    if dpg.does_item_exist("confirm_dlg"):
        dpg.delete_item("confirm_dlg")
    
    with dpg.window(
        label=title, modal=True, show=True, tag="confirm_dlg",
        width=320, height=130, no_resize=True,
        pos=[WIN_WIDTH//2 - 160, WIN_HEIGHT//2 - 65]
    ):
        dpg.add_spacer(height=8)
        dpg.add_text(msg, wrap=300)
        dpg.add_spacer(height=12)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=80)
            dpg.add_button(label="Yes", width=65, callback=_confirm_yes)
            dpg.add_button(label="No", width=65, callback=_confirm_no)

def _confirm_yes(sender, app_data, user_data):
    global _callback
    if dpg.does_item_exist("confirm_dlg"):
        dpg.delete_item("confirm_dlg")
    if _callback:
        _callback()

def _confirm_no(sender, app_data, user_data):
    if dpg.does_item_exist("confirm_dlg"):
        dpg.delete_item("confirm_dlg")

# =============================================================================
# ERROR DIALOG
# =============================================================================

def show_error(title: str, msg: str):
    """Show error dialog."""
    if dpg.does_item_exist("error_dlg"):
        dpg.delete_item("error_dlg")
    
    with dpg.window(
        label=title, modal=True, show=True, tag="error_dlg",
        width=340, height=120, no_resize=True,
        pos=[WIN_WIDTH//2 - 170, WIN_HEIGHT//2 - 60]
    ):
        dpg.add_spacer(height=8)
        dpg.add_text(msg, wrap=320, color=COLORS['accent_red'])
        dpg.add_spacer(height=12)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=125)
            dpg.add_button(label="OK", width=65, callback=lambda s,a,u: dpg.delete_item("error_dlg"))

# =============================================================================
# RENAME DIALOG
# =============================================================================

def show_rename_dlg(title: str, current: str, callback: Callable):
    """Show rename dialog."""
    global _callback
    _callback = callback
    
    if dpg.does_item_exist("rename_dlg"):
        dpg.delete_item("rename_dlg")
    
    with dpg.window(
        label=title, modal=True, show=True, tag="rename_dlg",
        width=280, height=100, no_resize=True,
        pos=[WIN_WIDTH//2 - 140, WIN_HEIGHT//2 - 50]
    ):
        dpg.add_spacer(height=6)
        dpg.add_input_text(default_value=current, tag="rename_inp", width=260)
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=60)
            dpg.add_button(label="OK", width=65, callback=_rename_ok)
            dpg.add_button(label="Cancel", width=65, callback=lambda s,a,u: dpg.delete_item("rename_dlg"))

def _rename_ok(sender, app_data, user_data):
    global _callback
    name = dpg.get_value("rename_inp")
    if dpg.does_item_exist("rename_dlg"):
        dpg.delete_item("rename_dlg")
    if _callback:
        _callback(name)

# =============================================================================
# ABOUT DIALOG
# =============================================================================

def show_about():
    """Show about dialog."""
    if dpg.does_item_exist("about_dlg"):
        dpg.delete_item("about_dlg")
    
    with dpg.window(
        label="About", modal=True, show=True, tag="about_dlg",
        width=380, height=250, no_resize=True,
        pos=[WIN_WIDTH//2 - 190, WIN_HEIGHT//2 - 125]
    ):
        dpg.add_spacer(height=8)
        dpg.add_text(APP_NAME, color=COLORS['accent_cyan'])
        dpg.add_text(f"Version {APP_VERSION}")
        dpg.add_spacer(height=8)
        dpg.add_separator()
        dpg.add_spacer(height=6)
        dpg.add_text("A music tracker for Atari XL/XE computers.")
        dpg.add_spacer(height=6)
        dpg.add_text("Features:", color=COLORS['accent_green'])
        dpg.add_text("• 3-channel sample playback")
        dpg.add_text("• Pattern-based sequencing (RMT style)")
        dpg.add_text("• WAV sample loading")
        dpg.add_text("• Export to 6502 assembly")
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=145)
            dpg.add_button(label="Close", width=65, callback=lambda s,a,u: dpg.delete_item("about_dlg"))

# =============================================================================
# SHORTCUTS DIALOG
# =============================================================================

def show_shortcuts():
    """Show keyboard shortcuts dialog."""
    if dpg.does_item_exist("help_dlg"):
        dpg.delete_item("help_dlg")
    
    with dpg.window(
        label="Keyboard Shortcuts", modal=True, show=True, tag="help_dlg",
        width=460, height=420, pos=[WIN_WIDTH//2 - 230, WIN_HEIGHT//2 - 210]
    ):
        with dpg.collapsing_header(label="Navigation", default_open=True):
            dpg.add_text("↑/↓       Row up/down")
            dpg.add_text("←/→       Column (Note/Ins/Vol)")
            dpg.add_text("Tab       Next channel")
            dpg.add_text("PgUp/Dn   Jump 16 rows")
            dpg.add_text("Home/End  First/last row")
            dpg.add_text("Ctrl+Home First songline")
        
        with dpg.collapsing_header(label="Note Entry", default_open=True):
            dpg.add_text("Z X C V B N M   Lower octave (white)")
            dpg.add_text("S D   G H J     Lower octave (black)")
            dpg.add_text("Q W E R T Y U   Upper octave (white)")
            dpg.add_text("* / -           Octave up/down")
            dpg.add_text("[ / ]           Prev/next instrument")
        
        with dpg.collapsing_header(label="Editing"):
            dpg.add_text("0-9 A-F   Enter hex value")
            dpg.add_text("Delete    Clear cell")
            dpg.add_text("Insert    Insert row")
            dpg.add_text("Ctrl+Z/Y  Undo/Redo")
            dpg.add_text("Ctrl+C/V  Copy/Paste")
        
        with dpg.collapsing_header(label="Playback"):
            dpg.add_text("Space     Play/Stop")
            dpg.add_text("F5        Play pattern")
            dpg.add_text("F6        Play song")
            dpg.add_text("F8        Stop")
            dpg.add_text("Enter     Preview row")
        
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=185)
            dpg.add_button(label="Close", width=65, callback=lambda s,a,u: dpg.delete_item("help_dlg"))
