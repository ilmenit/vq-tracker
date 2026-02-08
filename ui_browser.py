"""POKEY VQ Tracker - Custom File Browser with Audio Preview

Interaction model:
  File mode:   click file = select/deselect, double-click file = select & OK,
               click folder = navigate into it
  Folder mode: click folder = select/deselect, double-click folder = navigate,
               files shown dimmed for reference (not selectable)
  Single-select mode (Replace): selecting one deselects all others
"""
import dearpygui.dearpygui as dpg
import os
import time
import datetime
import logging
import numpy as np

logger = logging.getLogger("tracker.browser")

# Audio playback (optional - graceful fallback if not available)
AUDIO_PREVIEW_AVAILABLE = False
try:
    import sounddevice as sd
    from pydub import AudioSegment
    AUDIO_PREVIEW_AVAILABLE = True
except (ImportError, OSError) as e:
    logger.warning(f"Audio preview disabled: {e}")


# =========================================================================
# BROWSER THEMES  (created once, shared by all FileBrowser instances)
# =========================================================================
_browser_themes_created = False


def _ensure_browser_themes():
    """Create browser-specific themes if they haven't been created yet."""
    global _browser_themes_created
    if _browser_themes_created:
        return
    _browser_themes_created = True

    # -- Action buttons (Select All, Deselect All) --
    with dpg.theme(tag="theme_browser_btn_action"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (45, 75, 130))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (55, 95, 160))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (65, 115, 190))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (220, 230, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 6)

    # -- Primary button (Add Selected - the main action) --
    with dpg.theme(tag="theme_browser_btn_primary"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (35, 100, 60))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (45, 125, 75))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (55, 145, 90))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 255, 210))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 14, 6)

    # -- Cancel button --
    with dpg.theme(tag="theme_browser_btn_cancel"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (60, 40, 40))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (85, 50, 50))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (110, 60, 60))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (240, 200, 200))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 6)

    # -- Navigation buttons (Up, Go) --
    with dpg.theme(tag="theme_browser_btn_nav"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (50, 55, 70))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (65, 72, 90))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (80, 88, 110))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (190, 200, 220))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 4)

    # -- Sort column header button --
    with dpg.theme(tag="theme_browser_btn_sort"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (32, 36, 48))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (45, 50, 65))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (55, 62, 80))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (160, 170, 190))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 2)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)

    # -- Active sort column header --
    with dpg.theme(tag="theme_browser_btn_sort_active"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (40, 55, 80))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (50, 68, 100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (60, 80, 115))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (140, 190, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 2)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)

    # -- Play button (small, inline) --
    with dpg.theme(tag="theme_browser_btn_play"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (50, 70, 55))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 90, 65))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (70, 110, 80))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (150, 230, 160))

    # -- Stop audio button --
    with dpg.theme(tag="theme_browser_btn_stop"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (70, 50, 40))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (90, 60, 50))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (110, 70, 55))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (240, 180, 140))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 6)

    # -- Folder row (selectable) --
    with dpg.theme(tag="theme_browser_folder"):
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, (35, 45, 60))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (45, 58, 78))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (140, 190, 230))

    # -- Folder selected row --
    with dpg.theme(tag="theme_browser_folder_selected"):
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, (35, 60, 80))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (45, 72, 98))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (170, 220, 255))

    # -- File row (selectable) --
    with dpg.theme(tag="theme_browser_file"):
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, (30, 38, 48))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (40, 50, 65))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 205, 215))

    # -- Selected file row --
    with dpg.theme(tag="theme_browser_file_selected"):
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, (40, 65, 95))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (50, 78, 115))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (220, 235, 255))

    # -- Dimmed file row (shown in folder mode, not selectable) --
    with dpg.theme(tag="theme_browser_file_dimmed"):
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (90, 95, 110))


# Double-click threshold in seconds
DOUBLE_CLICK_TIME = 0.4


class FileBrowser:
    """Custom file browser with multi-select and audio preview."""

    # Fallback extensions - will be dynamically updated from file_io
    _VALID_AUDIO_EXTS = {'.wav'}

    @classmethod
    def get_valid_extensions(cls):
        """Get valid audio extensions (dynamically from file_io if available)."""
        try:
            from file_io import get_supported_extensions
            return set(get_supported_extensions())
        except ImportError:
            return cls._VALID_AUDIO_EXTS

    def __init__(self, tag_prefix: str = "browser"):
        self.callback = None
        self.current_path = os.path.expanduser("~")
        self.selected = set()
        self.mode = 'file'          # 'file' or 'folder'
        self.allow_multi = True     # False = single-select (for Replace)
        self.current_items = []     # Paths currently visible in table

        # Unique tags for this browser instance
        self.tag_win = f"{tag_prefix}_win"
        self.tag_table = f"{tag_prefix}_table"
        self.tag_path = f"{tag_prefix}_path"
        self.tag_title = f"{tag_prefix}_title"
        self.tag_status = f"{tag_prefix}_status"
        self.tag_btn_ok = f"{tag_prefix}_btn_ok"
        self.tag_btn_selall = f"{tag_prefix}_btn_selall"
        self.tag_btn_deselall = f"{tag_prefix}_btn_deselall"
        self.tag_hint = f"{tag_prefix}_hint"

        # Sorting
        self.sort_key = 'name'
        self.sort_reverse = False

        # Cached counts for status
        self._num_dirs = 0
        self._num_files = 0

        # Double-click tracking
        self._last_click_path = None
        self._last_click_time = 0.0

        _ensure_browser_themes()
        self._setup_ui()

    def _setup_ui(self):
        """Build the browser UI."""
        with dpg.window(label="Sample Browser", modal=True, show=False,
                        tag=self.tag_win, width=820, height=580,
                        no_resize=False, on_close=self._on_close):

            # Title
            dpg.add_text("Select Files", tag=self.tag_title, color=(136, 192, 208))
            dpg.add_spacer(height=4)

            # Navigation bar
            with dpg.group(horizontal=True):
                btn = dpg.add_button(label="\u2191 Up", callback=self.go_up, width=65)
                dpg.bind_item_theme(btn, "theme_browser_btn_nav")
                with dpg.tooltip(btn):
                    dpg.add_text("Go to parent folder")

                dpg.add_input_text(default_value=self.current_path, tag=self.tag_path,
                                   width=-75, callback=lambda s, a: self.navigate(a),
                                   on_enter=True, hint="Enter path and press Enter")

                btn = dpg.add_button(label="Go", callback=lambda: self.navigate(dpg.get_value(self.tag_path)),
                                     width=60)
                dpg.bind_item_theme(btn, "theme_browser_btn_nav")

            dpg.add_spacer(height=2)

            # File table
            with dpg.child_window(height=-105, border=True):
                with dpg.table(tag=self.tag_table, header_row=False, resizable=True,
                               policy=dpg.mvTable_SizingStretchProp,
                               borders_innerH=True, borders_outerH=True,
                               borders_innerV=True, borders_outerV=True,
                               row_background=False,
                               scrollY=True):
                    dpg.add_table_column(label="",    width_fixed=True, init_width_or_weight=30)
                    dpg.add_table_column(label="",    width_fixed=True, init_width_or_weight=40)
                    dpg.add_table_column(label="Name", width_stretch=True, init_width_or_weight=1.0)
                    dpg.add_table_column(label="Ext",  width_fixed=True, init_width_or_weight=55)
                    dpg.add_table_column(label="Size", width_fixed=True, init_width_or_weight=80)
                    dpg.add_table_column(label="Modified", width_fixed=True, init_width_or_weight=130)

            # Status line
            dpg.add_spacer(height=3)
            dpg.add_text("", tag=self.tag_status, color=(150, 200, 150))
            dpg.add_spacer(height=4)

            # Footer buttons
            with dpg.group(horizontal=True):
                btn = dpg.add_button(label="Select All", callback=self.select_all,
                                     width=95, tag=self.tag_btn_selall)
                dpg.bind_item_theme(btn, "theme_browser_btn_action")

                btn = dpg.add_button(label="Deselect All", callback=self.deselect_all,
                                     width=95, tag=self.tag_btn_deselall)
                dpg.bind_item_theme(btn, "theme_browser_btn_action")

                if AUDIO_PREVIEW_AVAILABLE:
                    dpg.add_spacer(width=8)
                    btn = dpg.add_button(label="\u25a0 Stop", callback=self.stop_playback, width=80)
                    dpg.bind_item_theme(btn, "theme_browser_btn_stop")

                # Push right
                dpg.add_spacer(width=-1)

                btn = dpg.add_button(label="Cancel", callback=self._on_close, width=95)
                dpg.bind_item_theme(btn, "theme_browser_btn_cancel")

                dpg.add_spacer(width=6)

                btn = dpg.add_button(label="\u2713 Add Selected", callback=self.on_ok,
                                     width=140, tag=self.tag_btn_ok)
                dpg.bind_item_theme(btn, "theme_browser_btn_primary")

            dpg.add_spacer(height=2)
            dpg.add_text("", tag=self.tag_hint, color=(90, 95, 110))

    # =====================================================================
    # SHOW / HIDE
    # =====================================================================

    def show(self, mode: str, callback, start_path: str = None,
             ok_label: str = None, allow_multi: bool = True,
             title: str = None):
        """Show the browser dialog.

        Args:
            mode: 'file' or 'folder'
            callback: Called with list of selected paths
            start_path: Initial directory
            ok_label: Custom label for OK button (default: mode-dependent)
            allow_multi: If False, only one item can be selected at a time
            title: Custom dialog title (default: mode-dependent)
        """
        from state import state

        self.mode = mode
        self.callback = callback
        self.allow_multi = allow_multi
        self.selected.clear()
        self._last_click_path = None

        if start_path and os.path.isdir(start_path):
            self.current_path = start_path

        # Title
        if title is None:
            if mode == 'file':
                title = "Select Audio Files  (WAV, MP3, OGG, FLAC, AIFF, M4A)"
            else:
                title = "Select Folders  (all audio files inside will be imported)"
        dpg.set_value(self.tag_title, title)

        # OK button label
        if ok_label is None:
            ok_label = "\u2713 Add Files" if mode == 'file' else "\u2713 Add Folders"
        dpg.set_item_label(self.tag_btn_ok, ok_label)

        # Show/hide multi-select buttons
        dpg.configure_item(self.tag_btn_selall, show=allow_multi)
        dpg.configure_item(self.tag_btn_deselall, show=allow_multi)

        # Help text — adapt to mode and single/multi select
        if mode == 'file':
            action = "add" if allow_multi else ok_label.replace("\u2713 ", "").lower()
            hint = f"Click to select  |  Double-click to {action} immediately  |  Click column header to sort"
        else:
            hint = "Click folder to select  |  Double-click to open  |  Click column header to sort"
        dpg.set_value(self.tag_hint, hint)

        # Center window
        vp_w = dpg.get_viewport_width()
        vp_h = dpg.get_viewport_height()
        win_w, win_h = 820, 580
        dpg.set_item_pos(self.tag_win, [(vp_w - win_w) // 2, (vp_h - win_h) // 2])

        # Block keyboard input to pattern editor
        state.set_input_active(True)

        dpg.show_item(self.tag_win)
        self.refresh()

    def _on_close(self):
        """Handle window close."""
        from state import state
        state.set_input_active(False)
        dpg.hide_item(self.tag_win)
        self.stop_playback()

    def hide(self):
        self._on_close()

    # =====================================================================
    # NAVIGATION
    # =====================================================================

    def navigate(self, path: str):
        """Navigate to a directory."""
        path = os.path.expanduser(path.strip())
        if os.path.isdir(path):
            self.current_path = os.path.abspath(path)
            dpg.set_value(self.tag_path, self.current_path)
            self.refresh()
        elif path:
            dpg.set_value(self.tag_status, f"Not a directory: {path}")

    def go_up(self):
        """Go to parent directory."""
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self.navigate(parent)

    # =====================================================================
    # SORTING
    # =====================================================================

    def _cycle_sort(self, key: str):
        """Cycle sort: click once = ascending, again = descending."""
        if self.sort_key == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key = key
            self.sort_reverse = False
        self.refresh()

    def _sort_key_func(self, entry):
        """Return sort key for a DirEntry."""
        try:
            if self.sort_key == 'name':
                return entry.name.lower()
            elif self.sort_key == 'ext':
                return os.path.splitext(entry.name)[1].lower()
            elif self.sort_key == 'size':
                return entry.stat().st_size if entry.is_file() else -1
            elif self.sort_key == 'time':
                return entry.stat().st_mtime
        except (OSError, PermissionError):
            pass
        if self.sort_key in ('size', 'time'):
            return -1
        return ""

    # =====================================================================
    # AUDIO PREVIEW
    # =====================================================================

    def play_file(self, path: str):
        """Play an audio file for preview."""
        if not AUDIO_PREVIEW_AVAILABLE:
            return
        try:
            sd.stop()
            audio = AudioSegment.from_file(path)
            samples = np.array(audio.get_array_of_samples())
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
            max_val = float(2 ** (audio.sample_width * 8 - 1))
            samples = samples.astype(np.float32) / max_val
            sd.play(samples, audio.frame_rate)
            dpg.set_value(self.tag_status, f"\u25b6 Playing: {os.path.basename(path)}")
        except Exception as e:
            logger.warning(f"Playback error: {e}")
            dpg.set_value(self.tag_status, f"Playback error: {e}")

    def stop_playback(self):
        """Stop audio preview playback and restore status bar."""
        if AUDIO_PREVIEW_AVAILABLE:
            sd.stop()
        if dpg.does_item_exist(self.tag_status):
            self._update_status(self._num_dirs, self._num_files)

    # =====================================================================
    # CLICK HANDLERS
    # =====================================================================

    def _is_double_click(self, path: str) -> bool:
        """Check if this click is a double-click on the same path."""
        now = time.time()
        is_double = (self._last_click_path == path and
                     (now - self._last_click_time) < DOUBLE_CLICK_TIME)
        self._last_click_path = path
        self._last_click_time = now
        return is_double

    def _on_folder_click_file_mode(self, sender, path: str):
        """Folder clicked in file mode → navigate into it."""
        dpg.set_value(sender, False)
        self.navigate(path)

    def _on_folder_click_folder_mode(self, path: str, is_selected: bool):
        """Folder clicked in folder mode → select or double-click to navigate."""
        if self._is_double_click(path):
            # Double-click → navigate INTO the folder.
            # Remove from selected entirely: user wanted to open, not select.
            # (The first click added it; this undoes that too.)
            self.selected.discard(path)
            self._last_click_path = None  # prevent triple-click
            self.navigate(path)
            return

        # Single click → toggle selection
        if not self.allow_multi and is_selected:
            self.selected.clear()
        self.toggle_select(path, is_selected)
        self.refresh()

    def _on_file_click(self, path: str, is_selected: bool):
        """File clicked in file mode → select, or double-click to add immediately."""
        if self._is_double_click(path):
            # Double-click → select and confirm
            self.selected.add(path)
            self._last_click_path = None
            self.on_ok()
            return

        # Single click → toggle selection
        if not self.allow_multi and is_selected:
            self.selected.clear()
        self.toggle_select(path, is_selected)
        self.refresh()

    def _on_checkbox_click(self, path: str, is_selected: bool):
        """Checkbox toggled (files or folders)."""
        if not self.allow_multi and is_selected:
            self.selected.clear()
        self.toggle_select(path, is_selected)
        self.refresh()

    # =====================================================================
    # REFRESH / RENDER
    # =====================================================================

    def _render_sort_header(self):
        """Render the clickable sort header row."""
        arrow = " \u25b2" if not self.sort_reverse else " \u25bc"

        with dpg.table_row(parent=self.tag_table):
            dpg.add_text("")  # checkbox column
            dpg.add_text("")  # play column

            for key, label in [('name', 'Name'), ('ext', 'Ext'),
                               ('size', 'Size'), ('time', 'Modified')]:
                is_active = (self.sort_key == key)
                lbl = f"{label}{arrow}" if is_active else label
                theme = "theme_browser_btn_sort_active" if is_active else "theme_browser_btn_sort"
                btn = dpg.add_button(label=lbl,
                                     callback=lambda s, a, k=key: self._cycle_sort(k),
                                     width=-1)
                dpg.bind_item_theme(btn, theme)

    def refresh(self):
        """Refresh the file list."""
        # Clear existing table rows
        if dpg.does_item_exist(self.tag_table):
            children = dpg.get_item_children(self.tag_table, slot=1)
            if children:
                for child in children:
                    dpg.delete_item(child)

        try:
            items = list(os.scandir(self.current_path))
        except PermissionError:
            dpg.set_value(self.tag_status, "Permission denied")
            return
        except Exception as e:
            dpg.set_value(self.tag_status, f"Error: {e}")
            return

        dirs = []
        files = []
        valid_exts = self.get_valid_extensions()

        for item in items:
            try:
                if item.name.startswith('.'):
                    continue
                if item.is_dir():
                    dirs.append(item)
                elif item.is_file():
                    ext = os.path.splitext(item.name)[1].lower()
                    if ext in valid_exts:
                        files.append(item)
            except (PermissionError, OSError):
                continue

        dirs.sort(key=self._sort_key_func, reverse=self.sort_reverse)
        files.sort(key=self._sort_key_func, reverse=self.sort_reverse)

        self._num_dirs = len(dirs)
        self._num_files = len(files)

        # Helpers
        def fmt_time(t):
            return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')

        def fmt_size(size_bytes):
            if size_bytes < 1024:
                return f"{size_bytes} B"
            kb = size_bytes / 1024
            if kb >= 1024:
                return f"{kb / 1024:.1f} MB"
            return f"{kb:.0f} KB"

        self.current_items = []

        # ---- Clickable sort header row ----
        self._render_sort_header()

        # ---- Directories ----
        for d in dirs:
            try:
                user_path = d.path
                is_sel = user_path in self.selected

                with dpg.table_row(parent=self.tag_table):
                    if self.mode == 'folder':
                        # Folder mode: folders are selectable items
                        dpg.add_checkbox(default_value=is_sel,
                                         callback=lambda s, a, u=user_path: self._on_checkbox_click(u, a))
                        self.current_items.append(user_path)

                        dpg.add_text("")  # play column

                        # Click = select, double-click = navigate
                        sel = dpg.add_selectable(
                            label=f"\U0001f4c1 {d.name}", span_columns=False,
                            default_value=is_sel,
                            callback=lambda s, a, u=user_path: self._on_folder_click_folder_mode(u, a))
                        theme = "theme_browser_folder_selected" if is_sel else "theme_browser_folder"
                        dpg.bind_item_theme(sel, theme)
                    else:
                        # File mode: folders are navigation targets
                        dpg.add_text("")  # checkbox column
                        dpg.add_text("")  # play column

                        sel = dpg.add_selectable(
                            label=f"\U0001f4c1 {d.name}", span_columns=False,
                            callback=lambda s, a, u=d.path: self._on_folder_click_file_mode(s, u))
                        dpg.bind_item_theme(sel, "theme_browser_folder")

                    dpg.add_text("")  # ext
                    dpg.add_text("")  # size
                    dpg.add_text(fmt_time(d.stat().st_mtime), color=(130, 135, 150))
            except (PermissionError, OSError):
                continue

        # ---- Files ----
        for f in files:
            try:
                user_path = f.path
                ext = os.path.splitext(f.name)[1].lower()
                name_no_ext = os.path.splitext(f.name)[0]
                stat_result = f.stat()

                if self.mode == 'file':
                    # File mode: files are selectable items
                    is_sel = user_path in self.selected
                    self.current_items.append(user_path)

                    with dpg.table_row(parent=self.tag_table):
                        dpg.add_checkbox(default_value=is_sel,
                                         callback=lambda s, a, u=user_path: self._on_checkbox_click(u, a))

                        if AUDIO_PREVIEW_AVAILABLE:
                            btn = dpg.add_button(label="\u25b6", small=True, width=30,
                                                 callback=lambda s, a, u=user_path: self.play_file(u))
                            dpg.bind_item_theme(btn, "theme_browser_btn_play")
                        else:
                            dpg.add_text("")

                        sel = dpg.add_selectable(
                            label=name_no_ext, span_columns=False,
                            default_value=is_sel,
                            callback=lambda s, a, u=user_path: self._on_file_click(u, a))
                        theme = "theme_browser_file_selected" if is_sel else "theme_browser_file"
                        dpg.bind_item_theme(sel, theme)

                        dpg.add_text(ext, color=(130, 160, 200))
                        dpg.add_text(fmt_size(stat_result.st_size), color=(150, 155, 165))
                        dpg.add_text(fmt_time(stat_result.st_mtime), color=(130, 135, 150))
                else:
                    # Folder mode: show files dimmed for reference (not selectable)
                    with dpg.table_row(parent=self.tag_table):
                        dpg.add_text("")
                        dpg.add_text("")
                        txt = dpg.add_text(f"  {name_no_ext}")
                        dpg.bind_item_theme(txt, "theme_browser_file_dimmed")
                        txt = dpg.add_text(ext)
                        dpg.bind_item_theme(txt, "theme_browser_file_dimmed")
                        txt = dpg.add_text(fmt_size(stat_result.st_size))
                        dpg.bind_item_theme(txt, "theme_browser_file_dimmed")
                        dpg.add_text("")  # no date for dimmed
            except (PermissionError, OSError):
                continue

        # Update status
        self._update_status(self._num_dirs, self._num_files)

    # =====================================================================
    # SELECTION
    # =====================================================================

    def toggle_select(self, path: str, is_selected: bool):
        """Toggle selection of a file/folder."""
        if is_selected:
            self.selected.add(path)
        else:
            self.selected.discard(path)

    def _update_status(self, num_dirs: int, num_files: int):
        """Update the status text from ground truth."""
        if self.mode == 'file':
            base = f"{num_dirs} folder{'s' if num_dirs != 1 else ''}, {num_files} audio file{'s' if num_files != 1 else ''}"
        else:
            parts = [f"{num_dirs} folder{'s' if num_dirs != 1 else ''}"]
            if num_files > 0:
                parts.append(f"{num_files} audio file{'s' if num_files != 1 else ''}")
            base = ", ".join(parts)

        num_selected = len(self.selected)
        # Count selections not visible in current directory
        visible_selected = sum(1 for p in self.selected if p in self.current_items)
        hidden_selected = num_selected - visible_selected

        if num_selected > 0:
            sel_text = f"{num_selected} selected"
            if hidden_selected > 0:
                sel_text += f" ({hidden_selected} in other folders)"
            base += f"  \u2502  {sel_text}"

        dpg.set_value(self.tag_status, base)

    def select_all(self):
        """Select all visible items."""
        for path in self.current_items:
            self.selected.add(path)
        self.refresh()

    def deselect_all(self):
        """Deselect all items."""
        self.selected.clear()
        self.refresh()

    def on_ok(self):
        """Handle OK/Add Selected button."""
        if self.selected and self.callback:
            paths = sorted(self.selected)
            self.selected.clear()
            self._on_close()
            try:
                self.callback(paths)
            except Exception as e:
                logger.error(f"Import callback failed: {e}")
        else:
            self.selected.clear()
            self._on_close()


# =========================================================================
# GLOBAL INSTANCE
# =========================================================================

_file_browser: FileBrowser = None


def get_file_browser() -> FileBrowser:
    """Get or create the global file browser instance."""
    global _file_browser
    if _file_browser is None:
        _file_browser = FileBrowser("sample_browser")
    return _file_browser


def show_sample_browser(mode: str, callback, start_path: str = None,
                        ok_label: str = None, allow_multi: bool = True,
                        title: str = None):
    """Show the sample browser dialog.

    Args:
        mode: 'file' to select individual files, 'folder' to select folders
        callback: Function called with list of selected paths
        start_path: Optional starting directory
        ok_label: Custom OK button label
        allow_multi: If False, only one item can be selected
        title: Custom dialog title
    """
    browser = get_file_browser()
    browser.show(mode, callback, start_path, ok_label=ok_label,
                 allow_multi=allow_multi, title=title)
