"""POKEY VQ Tracker - Custom File Browser with Audio Preview"""
import dearpygui.dearpygui as dpg
import os
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
        self.mode = 'file'  # 'file' or 'folder'
        self.current_items = []  # Paths currently visible in table
        
        # Unique tags for this browser instance
        self.tag_win = f"{tag_prefix}_win"
        self.tag_table = f"{tag_prefix}_table"
        self.tag_path = f"{tag_prefix}_path"
        self.tag_title = f"{tag_prefix}_title"
        self.tag_status = f"{tag_prefix}_status"
        
        # Sorting
        self.sort_key = 'name'  # 'name', 'size', 'time'
        self.sort_dir = 1  # 1=asc, -1=desc
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Build the browser UI."""
        with dpg.window(label="Sample Browser", modal=True, show=False, 
                        tag=self.tag_win, width=800, height=550, 
                        no_resize=False, on_close=self._on_close):
            
            # Title
            dpg.add_text("Select Files", tag=self.tag_title, color=(136, 192, 208))
            dpg.add_spacer(height=5)
            
            # Navigation bar
            with dpg.group(horizontal=True):
                dpg.add_button(label="Up", callback=self.go_up, width=60)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Go to parent folder")
                
                dpg.add_input_text(default_value=self.current_path, tag=self.tag_path, 
                                   width=-80, callback=lambda s, a: self.navigate(a), 
                                   on_enter=True, hint="Enter path and press Enter")
                
                dpg.add_button(label="Go", callback=lambda: self.navigate(dpg.get_value(self.tag_path)), 
                               width=60)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Navigate to entered path")
            
            dpg.add_separator()
            
            # File table - no alternating row colors
            with dpg.child_window(height=-100, border=True):
                with dpg.table(tag=self.tag_table, header_row=True, resizable=True,
                               policy=dpg.mvTable_SizingStretchProp, sortable=True,
                               callback=self.on_sort, 
                               borders_innerH=True, borders_outerH=True,
                               borders_innerV=True, borders_outerV=True,
                               row_background=False,  # Disable alternating colors
                               scrollY=True):
                    
                    # Column: Checkbox for selection
                    dpg.add_table_column(label="Sel", width_fixed=True, init_width_or_weight=35, no_sort=True)
                    
                    # Column: Play button
                    dpg.add_table_column(label="Play", width_fixed=True, init_width_or_weight=50, no_sort=True)
                    
                    # Column: File/folder name (sortable)
                    dpg.add_table_column(label="Name", width_stretch=True, tag=f"{self.tag_table}_col_name")
                    
                    # Column: File size (sortable)
                    dpg.add_table_column(label="Size", width_fixed=True, init_width_or_weight=90, tag=f"{self.tag_table}_col_size")
                    
                    # Column: Modified date (sortable)
                    dpg.add_table_column(label="Modified", width_fixed=True, init_width_or_weight=140, tag=f"{self.tag_table}_col_time")
            
            # Status line
            dpg.add_spacer(height=3)
            dpg.add_text("", tag=self.tag_status, color=(150, 200, 150))
            dpg.add_spacer(height=5)
            
            # Footer buttons - improved layout
            with dpg.group(horizontal=True):
                dpg.add_button(label="Select All", callback=self.select_all, width=100)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Select all visible items")
                
                dpg.add_button(label="Deselect All", callback=self.deselect_all, width=100)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Clear selection")
                
                if AUDIO_PREVIEW_AVAILABLE:
                    dpg.add_spacer(width=20)
                    dpg.add_button(label="Stop Audio", callback=self.stop_playback, width=90)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text("Stop audio preview playback")
                
                # Spacer to push Cancel/Add to the right
                dpg.add_spacer(width=20)
                
                dpg.add_button(label="Cancel", callback=self._on_close, width=100)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Close without adding files")
                
                dpg.add_button(label="Add Selected", callback=self.on_ok, width=120)
                with dpg.tooltip(dpg.last_item()):
                    dpg.add_text("Add selected files/folders to instruments")
            
            dpg.add_spacer(height=3)
            dpg.add_text("Double-click folder to open  |  Check items to select  |  Click column headers to sort", 
                         color=(100, 100, 110))
    
    def show(self, mode: str, callback, start_path: str = None):
        """Show the browser dialog.
        
        Args:
            mode: 'file' for selecting files, 'folder' for selecting folders
            callback: Function to call with list of selected paths
            start_path: Optional starting directory
        """
        from state import state
        
        self.mode = mode
        self.callback = callback
        self.selected.clear()
        
        if start_path and os.path.isdir(start_path):
            self.current_path = start_path
        
        # Update title based on mode
        if mode == 'file':
            title = "Select Audio Files  (WAV, MP3, OGG, FLAC, AIFF, M4A)"
        else:
            title = "Select Folders  (all audio files inside will be imported)"
        dpg.set_value(self.tag_title, title)
        
        # Center window
        vp_w = dpg.get_viewport_width()
        vp_h = dpg.get_viewport_height()
        win_w, win_h = 800, 550
        dpg.set_item_pos(self.tag_win, [(vp_w - win_w) // 2, (vp_h - win_h) // 2])
        
        # Block keyboard input to pattern editor
        state.set_input_active(True)
        
        dpg.show_item(self.tag_win)
        self.refresh()
    
    def _on_close(self):
        """Handle window close - re-enable keyboard input."""
        from state import state
        state.set_input_active(False)
        dpg.hide_item(self.tag_win)
        self.stop_playback()
    
    def hide(self):
        """Hide the browser dialog."""
        self._on_close()
    
    def navigate(self, path: str):
        """Navigate to a directory."""
        if os.path.isdir(path):
            self.current_path = os.path.abspath(path)
            dpg.set_value(self.tag_path, self.current_path)
            self.refresh()
    
    def go_up(self):
        """Go to parent directory."""
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self.navigate(parent)
    
    def on_sort(self, sender, app_data):
        """Handle column sort click."""
        if app_data:
            sort_info = app_data[0]
            col = sort_info[0]
            direction = sort_info[1]
            
            if col == f"{self.tag_table}_col_name":
                self.sort_key = 'name'
            elif col == f"{self.tag_table}_col_size":
                self.sort_key = 'size'
            elif col == f"{self.tag_table}_col_time":
                self.sort_key = 'time'
            
            self.sort_dir = direction
            self.refresh()
    
    def play_file(self, path: str):
        """Play an audio file for preview."""
        if not AUDIO_PREVIEW_AVAILABLE:
            return
        try:
            sd.stop()
            
            # Load with pydub (handles all formats)
            audio = AudioSegment.from_file(path)
            
            # Convert to numpy array for sounddevice
            samples = np.array(audio.get_array_of_samples())
            
            # Handle stereo
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
            
            # Normalize to float32 range [-1, 1]
            max_val = float(2 ** (audio.sample_width * 8 - 1))
            samples = samples.astype(np.float32) / max_val
            
            sd.play(samples, audio.frame_rate)
            dpg.set_value(self.tag_status, f"Playing: {os.path.basename(path)}")
        except Exception as e:
            logger.warning(f"Playback error: {e}")
            dpg.set_value(self.tag_status, f"Playback error: {e}")
    
    def stop_playback(self):
        """Stop audio preview playback."""
        if AUDIO_PREVIEW_AVAILABLE:
            sd.stop()
            # Don't clear status - keep item count visible
    
    def refresh(self):
        """Refresh the file list."""
        # Clear table rows
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
        
        for item in items:
            try:
                if item.name.startswith('.'):
                    continue  # Skip hidden files
                if item.is_dir():
                    dirs.append(item)
                elif item.is_file():
                    ext = os.path.splitext(item.name)[1].lower()
                    if ext in self.get_valid_extensions():
                        files.append(item)
            except (PermissionError, OSError):
                continue
        
        # Sort helper
        def get_key(item):
            try:
                if self.sort_key == 'name':
                    return item.name.lower()
                if self.sort_key == 'size':
                    return item.stat().st_size
                if self.sort_key == 'time':
                    return item.stat().st_mtime
            except:
                pass
            return item.name.lower()
        
        reverse = (self.sort_dir == -1)
        dirs.sort(key=get_key, reverse=reverse)
        files.sort(key=get_key, reverse=reverse)
        
        # Time format helper
        def fmt_time(t):
            return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
        
        self.current_items = []
        
        # Render directories
        for d in dirs:
            try:
                user_path = d.path
                is_sel = user_path in self.selected
                
                with dpg.table_row(parent=self.tag_table):
                    # In folder mode, dirs can be selected
                    if self.mode == 'folder':
                        dpg.add_checkbox(default_value=is_sel, 
                                         callback=lambda s, a, u: self.toggle_select(u, a),
                                         user_data=user_path)
                        self.current_items.append(user_path)
                    else:
                        dpg.add_text("")
                    
                    dpg.add_text("")  # No play button for dirs
                    
                    # Clickable folder name
                    dpg.add_selectable(label=f"[DIR] {d.name}", span_columns=False,
                                       callback=lambda s, a, u: self.navigate(u),
                                       user_data=d.path)
                    dpg.add_text("")  # Size (empty for dirs)
                    dpg.add_text(fmt_time(d.stat().st_mtime))
            except (PermissionError, OSError):
                continue
        
        # Render files (only in file mode)
        if self.mode == 'file':
            for f in files:
                try:
                    user_path = f.path
                    is_sel = user_path in self.selected
                    self.current_items.append(user_path)
                    
                    with dpg.table_row(parent=self.tag_table):
                        # Checkbox
                        dpg.add_checkbox(default_value=is_sel,
                                         callback=lambda s, a, u: self.toggle_select(u, a),
                                         user_data=user_path)
                        
                        # Play button
                        if AUDIO_PREVIEW_AVAILABLE:
                            dpg.add_button(label=">", small=True, width=35,
                                           callback=lambda s, a, u: self.play_file(u),
                                           user_data=user_path)
                        else:
                            dpg.add_text("")
                        
                        # File info
                        dpg.add_text(f.name)
                        size_kb = f.stat().st_size / 1024
                        if size_kb >= 1024:
                            dpg.add_text(f"{size_kb/1024:.1f} MB")
                        else:
                            dpg.add_text(f"{size_kb:.1f} KB")
                        dpg.add_text(fmt_time(f.stat().st_mtime))
                except (PermissionError, OSError):
                    continue
        
        # Update status
        num_selected = len(self.selected)
        if self.mode == 'file':
            num_files = len(files)
            num_dirs = len(dirs)
            status = f"{num_dirs} folders, {num_files} audio files"
        else:
            num_dirs = len(dirs)
            status = f"{num_dirs} folders"
        
        if num_selected > 0:
            status += f"  |  {num_selected} selected"
        dpg.set_value(self.tag_status, status)
    
    def toggle_select(self, path: str, is_selected: bool):
        """Toggle selection of a file/folder."""
        if is_selected:
            self.selected.add(path)
        else:
            self.selected.discard(path)
        
        # Update status count
        num_selected = len(self.selected)
        current_status = dpg.get_value(self.tag_status)
        if "  |  " in current_status:
            base = current_status.split("  |  ")[0]
        else:
            base = current_status
        
        if num_selected > 0:
            dpg.set_value(self.tag_status, f"{base}  |  {num_selected} selected")
        else:
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
            self.callback(list(self.selected))
        self.selected.clear()
        self._on_close()


# Global browser instance
_file_browser: FileBrowser = None


def get_file_browser() -> FileBrowser:
    """Get or create the global file browser instance."""
    global _file_browser
    if _file_browser is None:
        _file_browser = FileBrowser("sample_browser")
    return _file_browser


def show_sample_browser(mode: str, callback, start_path: str = None):
    """Show the sample browser dialog.
    
    Args:
        mode: 'file' to select individual files, 'folder' to select folders
        callback: Function called with list of selected paths
        start_path: Optional starting directory
    """
    browser = get_file_browser()
    browser.show(mode, callback, start_path)
