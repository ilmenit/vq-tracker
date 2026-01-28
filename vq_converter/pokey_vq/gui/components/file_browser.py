import dearpygui.dearpygui as dpg
import os
import sounddevice as sd
import soundfile as sf
import threading

class FileBrowser:
    def __init__(self, callback):
        self.callback = callback
        self.current_path = os.getcwd()
        self.selected = set()
        self.mode = 'file' # 'file' or 'folder'
        self.current_items = [] # list of paths currently visible in table (dirs or files depending on mode)
        
        self.tag_win = "win_custom_browser"
        self.tag_table = "table_browser_files"
        self.tag_path = "input_browser_path"
        self.tag_title = "browser_title_label"
        
        # Sorting
        self.sort_key = 'name' # 'name', 'size', 'time'
        self.sort_dir = 1 # 1=asc, -1=desc

        self._setup_ui()

    def _setup_ui(self):
        with dpg.window(label="File Browser", modal=True, show=False, tag=self.tag_win, width=700, height=500, no_resize=False):
            dpg.add_text("Select Files", tag=self.tag_title, color=(136, 192, 208))
            
            # Header
            with dpg.group(horizontal=True):
                dpg.add_button(label="^ Up", callback=self.go_up, width=50)
                dpg.add_input_text(default_value=self.current_path, tag=self.tag_path, width=-100, callback=lambda s,a: self.navigate(a), on_enter=True)
                dpg.add_button(label="Go", callback=lambda: self.navigate(dpg.get_value(self.tag_path)), width=40)

            dpg.add_separator()
            
            # File Table
            with dpg.child_window(height=-50, border=True):
                with dpg.table(tag=self.tag_table, header_row=True, resizable=True, policy=dpg.mvTable_SizingStretchProp, sortable=True, callback=self.on_sort):
                    dpg.add_table_column(label="Sel", width_fixed=True, init_width_or_weight=30, no_sort=True) # Checkbox
                    dpg.add_table_column(label="Play", width_fixed=True, init_width_or_weight=40, no_sort=True) # Play Btn
                    dpg.add_table_column(label="Name", width_stretch=True, tag="col_name")
                    dpg.add_table_column(label="Size", width_fixed=True, init_width_or_weight=80, tag="col_size")
                    dpg.add_table_column(label="Modified", width_fixed=True, init_width_or_weight=120, tag="col_time")
            
            # Footer
            with dpg.group(horizontal=True):
                dpg.add_button(label="Select All", callback=self.select_all)
                dpg.add_button(label="Deselect All", callback=self.deselect_all)
                dpg.add_spacer(width=20)
                dpg.add_button(label="Cancel", callback=self.hide, width=80)
                dpg.add_button(label="Add Selected", callback=self.on_ok, width=120)
            
            dpg.add_text("Double-click folder to open. Check box to select.", color=(150,150,150))

    def show(self, mode='file'):
        self.mode = mode
        title = "Select Audio Files" if mode == 'file' else "Select Folders"
        dpg.set_value(self.tag_title, title)
        
        dpg.show_item(self.tag_win)
        self.refresh()

    def hide(self):
        dpg.hide_item(self.tag_win)
        sd.stop() # Stop playing if closed

    def navigate(self, path):
        if os.path.isdir(path):
            self.current_path = os.path.abspath(path)
            dpg.set_value(self.tag_path, self.current_path)
            self.refresh()

    def go_up(self):
        parent = os.path.dirname(self.current_path)
        self.navigate(parent)

    def on_sort(self, sender, app_data):
        # app_data is usually a list of [column_tag, direction] objects? or just description
        # DPG sort callback: sender=table, app_data=[{'column': tag, 'direction': 1/-1}, ...]
        if app_data:
            sort_info = app_data[0] # Single sort for now
            col = sort_info[0]
            direction = sort_info[1] # 1=asc, -1=desc usually
            
            if col == "col_name": self.sort_key = 'name'
            elif col == "col_size": self.sort_key = 'size'
            elif col == "col_time": self.sort_key = 'time'
            
            self.sort_dir = direction
            self.refresh()

    def play_file(self, path):
        try:
            sd.stop() 
            data, fs = sf.read(path)
            sd.play(data, fs)
        except Exception as e:
            print(f"Playback error: {e}")

    def refresh(self):
        # Clear Table
        if dpg.does_item_exist(self.tag_table):
            # DPG doesn't implement delete_children directly on table well in some versions,
            # but deleting children of table works
            children = dpg.get_item_children(self.tag_table, slot=1)
            if children:
                for child in children:
                    dpg.delete_item(child)
        
        try:
            items = os.scandir(self.current_path)
        except PermissionError:
            return

        dirs = []
        files = []
        
        valid_exts = {'.wav', '.mp3', '.ogg', '.flac', '.aiff'}

        for item in items:
            if item.is_dir():
                dirs.append(item)
            elif item.is_file():
                ext = os.path.splitext(item.name)[1].lower()
                if ext in valid_exts:
                    files.append(item)
        
        
        # Sort Logic (Separate for dirs and files to keep dirs on top)
        def get_key(item):
            if self.sort_key == 'name': return item.name.lower()
            if self.sort_key == 'size': return item.stat().st_size
            if self.sort_key == 'time': return item.stat().st_mtime
            return item.name
            
        reverse = (self.sort_dir == -1)
        dirs.sort(key=get_key, reverse=reverse)
        files.sort(key=get_key, reverse=reverse)
        
        # Time Format Helper
        import datetime
        def fmt_time(t): return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
        
        # Render
        self.current_items = []

        # Render Dirs
        for d in dirs:
            with dpg.table_row(parent=self.tag_table):
                user_path = d.path
                is_sel = user_path in self.selected
                
                # In Folder mode, we can select dirs
                if self.mode == 'folder':
                    dpg.add_checkbox(default_value=is_sel, callback=lambda s, a, u: self.toggle_select(u, a), user_data=user_path)
                    self.current_items.append(user_path)
                else:
                    dpg.add_text("[DIR]", color=(220, 220, 100))
                
                dpg.add_text("") # No play for dirs
                
                # Make name clickable to enter
                dpg.add_selectable(label=d.name, span_columns=True, callback=lambda s, a, u: self.navigate(u), user_data=d.path)
                dpg.add_text("") # Size for dir (empty)
                dpg.add_text(fmt_time(d.stat().st_mtime))

        # Render Files (only in file mode)
        if self.mode == 'file':
            for f in files:
                user_path = f.path
                is_sel = user_path in self.selected
                self.current_items.append(user_path)
                
                with dpg.table_row(parent=self.tag_table):
                    # Checkbox for selection
                    dpg.add_checkbox(default_value=is_sel, callback=lambda s, a, u: self.toggle_select(u, a), user_data=user_path)
                    
                    # Play Button
                    dpg.add_button(label=" > ", small=True, callback=lambda s,a,u: self.play_file(u), user_data=user_path)
                    
                    dpg.add_text(f.name)
                    
                    size_str = f"{f.stat().st_size / 1024:.1f} KB"
                    dpg.add_text(size_str)
                    dpg.add_text(fmt_time(f.stat().st_mtime))

    def toggle_select(self, path, is_selected):
        if is_selected:
            self.selected.add(path)
        else:
            if path in self.selected:
                self.selected.remove(path)

    def select_all(self):
        for path in self.current_items:
            self.selected.add(path)
        self.refresh()

    def deselect_all(self):
        # Only deselect items visible? Or all? Usually current view.
        # But 'Add Selected' implies accumulating.
        # However, expected behavior for 'Deselect All' is usually "clear selection".
        self.selected.clear()
        self.refresh()

    def on_ok(self):
        if self.selected:
            self.callback(list(self.selected))
            self.selected.clear() # Optional: clear after add
            self.hide()
        else:
            # Maybe show warning?
            self.hide()
