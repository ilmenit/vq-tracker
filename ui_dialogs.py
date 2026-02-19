"""POKEY VQ Tracker - UI Dialogs"""
import dearpygui.dearpygui as dpg
from constants import COL_DIM, COL_ACCENT, COL_TEXT, APP_NAME, APP_VERSION
from state import state


def show_confirm(title: str, message: str, callback):
    """Show confirmation dialog centered on viewport."""
    if dpg.does_item_exist("confirm_dialog"):
        dpg.delete_item("confirm_dialog")
    
    state.set_input_active(True)
    
    def on_ok():
        state.set_input_active(False)
        dpg.delete_item("confirm_dialog")
        callback()
    
    def on_cancel():
        state.set_input_active(False)
        dpg.delete_item("confirm_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 320, 130
    btn_w = 90
    spacing = 20
    # Calculate left margin to center two buttons with spacing
    # Total buttons width = btn_w * 2 + spacing = 200
    # Left margin = (w - 200) / 2 - padding (~16)
    left_margin = (w - btn_w * 2 - spacing) // 2 - 8
    
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
        dpg.add_spacer(height=5)
        # Center the message text
        dpg.add_text(message)
        dpg.add_spacer(height=20)
        # Centered button row
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="OK", width=btn_w, callback=on_ok)
            dpg.add_spacer(width=spacing)
            dpg.add_button(label="Cancel", width=btn_w, callback=on_cancel)


def show_error(title: str, message: str):
    """Show error dialog centered on viewport."""
    if dpg.does_item_exist("error_dialog"):
        dpg.delete_item("error_dialog")
    
    state.set_input_active(True)
    
    def on_close():
        state.set_input_active(False)
        dpg.delete_item("error_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    
    # Estimate height based on message length
    line_count = message.count('\n') + 1
    h = max(140, min(400, 100 + line_count * 20))
    w = 400
    btn_w = 90
    left_margin = (w - btn_w) // 2 - 8
    
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
        dpg.add_spacer(height=5)
        dpg.add_text(message, wrap=380)
        dpg.add_spacer(height=20)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="OK", width=btn_w, callback=on_close)


def show_info(title: str, message: str):
    """Show info dialog centered on viewport."""
    if dpg.does_item_exist("info_dialog"):
        dpg.delete_item("info_dialog")
    
    state.set_input_active(True)
    
    def on_close():
        state.set_input_active(False)
        dpg.delete_item("info_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    
    # Estimate height based on message length
    line_count = message.count('\n') + 1
    h = max(180, min(400, 100 + line_count * 20))
    w = 450
    btn_w = 90
    left_margin = (w - btn_w) // 2 - 8
    
    with dpg.window(
        tag="info_dialog",
        label=title,
        modal=True,
        width=w,
        height=h,
        pos=[(vp_w - w) // 2, (vp_h - h) // 2],
        no_resize=True,
        no_collapse=True
    ):
        dpg.add_spacer(height=5)
        dpg.add_text(message, wrap=430)
        dpg.add_spacer(height=20)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="OK", width=btn_w, callback=on_close)


def show_rename_dialog(title: str, current_name: str, callback):
    """Show rename dialog centered on viewport."""
    if dpg.does_item_exist("rename_dialog"):
        dpg.delete_item("rename_dialog")
    
    state.set_input_active(True)
    
    def on_ok():
        name = dpg.get_value("rename_input")
        state.set_input_active(False)
        dpg.delete_item("rename_dialog")
        callback(name)
    
    def on_cancel():
        state.set_input_active(False)
        dpg.delete_item("rename_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 320, 120
    btn_w = 90
    spacing = 20
    left_margin = (w - btn_w * 2 - spacing) // 2 - 8
    
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
        dpg.add_spacer(height=5)
        dpg.add_input_text(tag="rename_input", default_value=current_name, width=-1)
        dpg.add_spacer(height=20)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="OK", width=btn_w, callback=on_ok)
            dpg.add_spacer(width=spacing)
            dpg.add_button(label="Cancel", width=btn_w, callback=on_cancel)


def show_about():
    """Show about dialog."""
    if dpg.does_item_exist("about_dialog"):
        dpg.delete_item("about_dialog")
    
    state.set_input_active(True)
    
    def on_close():
        state.set_input_active(False)
        dpg.delete_item("about_dialog")
    
    # Calculate center position
    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 340, 210
    btn_w = 90
    left_margin = (w - btn_w) // 2 - 8
    
    with dpg.window(
        tag="about_dialog",
        label="About",
        modal=True,
        width=w,
        height=h,
        pos=[(vp_w - w) // 2, (vp_h - h) // 2],
        no_resize=True,
        no_collapse=True
    ):
        dpg.add_spacer(height=5)
        dpg.add_text(f"{APP_NAME}", color=COL_ACCENT)
        dpg.add_text(f"Version {APP_VERSION}")
        dpg.add_spacer(height=10)
        dpg.add_text("Sample-based music tracker for", color=COL_DIM)
        dpg.add_text("Atari XL/XE 8-bit computers", color=COL_DIM)
        dpg.add_spacer(height=10)
        dpg.add_text("Features:", color=COL_DIM)
        dpg.add_text("  - 4 channel polyphonic playback", color=COL_DIM)
        dpg.add_text("  - WAV sample import", color=COL_DIM)
        dpg.add_text("  - Export to Atari binary (.xex)", color=COL_DIM)
        dpg.add_spacer(height=15)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="Close", width=btn_w, callback=on_close)


def show_shortcuts():
    """Show keyboard shortcuts dialog with dynamically-resolved key bindings."""
    import key_config

    if dpg.does_item_exist("shortcuts_dialog"):
        dpg.delete_item("shortcuts_dialog")

    state.set_input_active(True)

    def on_close():
        state.set_input_active(False)
        dpg.delete_item("shortcuts_dialog")

    # Helper: format "  Key              Description" with aligned columns
    def _kb(action_or_key, desc):
        """Return formatted shortcut line.
        If action_or_key is a known config action, look up its current binding.
        Otherwise use the literal string (for hardcoded keys).
        """
        if action_or_key in key_config.DEFAULT_BINDINGS:
            k = key_config.get_combo_str(action_or_key)
        else:
            k = action_or_key
        return f"  {k:<19s}{desc}"

    vp_w = dpg.get_viewport_width()
    vp_h = dpg.get_viewport_height()
    w, h = 500, 760
    btn_w = 90
    left_margin = (w - btn_w) // 2 - 8

    with dpg.window(
        tag="shortcuts_dialog",
        label="Keyboard Shortcuts",
        modal=True,
        width=w,
        height=h,
        pos=[(vp_w - w) // 2, (vp_h - h) // 2],
        no_resize=True,
        no_collapse=True
    ):
        # Navigation (hardcoded)
        dpg.add_text("NAVIGATION", color=COL_ACCENT)
        dpg.add_text("  Arrow Keys       Move cursor")
        dpg.add_text("  Shift+Arrows     Extend block selection")
        dpg.add_text("  Ctrl+Up/Down     Jump by Step rows")
        dpg.add_text(_kb("step_up",   "Increase Edit Step"))
        dpg.add_text(_kb("step_down", "Decrease Edit Step"))
        dpg.add_text("  Tab              Next channel")
        dpg.add_text("  Shift+Tab        Previous channel")
        dpg.add_text("  Page Up/Down     Jump 16 rows")
        dpg.add_text("  Home/End         First/last row")
        dpg.add_text(_kb("jump_first_songline", "First songline"))
        dpg.add_text(_kb("jump_last_songline",  "Last songline"))

        dpg.add_spacer(height=8)
        dpg.add_text("EDITING", color=COL_ACCENT)
        dpg.add_text("  Z-M, Q-P         Piano keys (2 octaves)")
        dpg.add_text("  2,3,5,6,7,9,0    Sharp notes (piano mode)")
        dpg.add_text("  ` (backtick)     Note OFF (silence)")
        dpg.add_text("  ~ (tilde)        Volume change (V--)")
        dpg.add_text("  1                Note OFF (tracker mode)")
        dpg.add_text("  0-9, A-F         Hex mode: inst/vol")
        dpg.add_text("  Delete           Delete row (shift up)")
        dpg.add_text("  Backspace        Clear cell + jump up")
        dpg.add_text("  Insert           Insert row (shift down)")
        dpg.add_text("  = / +            Octave up")
        dpg.add_text("  -                Octave down")
        dpg.add_text("  [ / ]            Prev/next instrument")

        dpg.add_spacer(height=8)
        dpg.add_text("OCTAVE & PLAYBACK", color=COL_ACCENT)
        dpg.add_text(_kb("octave_1",         "Octave 1"))
        dpg.add_text(_kb("octave_2",         "Octave 2"))
        dpg.add_text(_kb("octave_3",         "Octave 3 (max)"))
        dpg.add_text(_kb("play_song",        "Play song from start"))
        dpg.add_text(_kb("play_pattern",     "Play pattern from start"))
        dpg.add_text(_kb("play_from_cursor", "Play from cursor"))
        dpg.add_text(_kb("stop",             "Stop"))
        dpg.add_text(_kb("show_help",        "Show this help"))
        dpg.add_text(_kb("play_stop_toggle", "Play/stop toggle"))
        dpg.add_text(_kb("preview_row",      "Preview current row"))
        dpg.add_text(_kb("toggle_follow",    "Toggle follow mode"))

        dpg.add_spacer(height=8)
        dpg.add_text("SELECTION & CLIPBOARD", color=COL_ACCENT)
        dpg.add_text("  Shift+Click      Extend selection to cell")
        dpg.add_text(_kb("select_all", "Select all (rows × channels)"))
        dpg.add_text(_kb("copy",  "Copy block (+ OS clipboard)"))
        dpg.add_text(_kb("cut",   "Cut block"))
        dpg.add_text(_kb("paste", "Paste block (OS clipboard first)"))
        dpg.add_text("  Delete           Clear block / delete row")

        dpg.add_spacer(height=8)
        dpg.add_text("FILE", color=COL_ACCENT)
        dpg.add_text(_kb("new_project",     "New project"))
        dpg.add_text(_kb("open_project",    "Open project"))
        dpg.add_text(_kb("save_project",    "Save project"))
        dpg.add_text(_kb("save_project_as", "Save as"))
        dpg.add_text(_kb("undo", "Undo") + " / " + key_config.get_combo_str("redo") + " Redo")
        dpg.add_text("  Escape           Stop / Close / Clear")

        dpg.add_spacer(height=8)
        dpg.add_text("WORKFLOW", color=COL_ACCENT)
        dpg.add_text("  1. Load samples (Add/Folder)")
        dpg.add_text("  2. CONVERT samples to VQ format")
        dpg.add_text("  3. Write your song (patterns/notes)")
        dpg.add_text("  4. BUILD executable (.XEX)")

        # Config file note
        dpg.add_spacer(height=4)
        dpg.add_text("  Shortcuts editable in keyboard.json", color=COL_DIM)

        dpg.add_spacer(height=12)
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=left_margin)
            dpg.add_button(label="Close", width=btn_w, callback=on_close)
