
import dearpygui.dearpygui as dpg
import os
import sys
import subprocess
from ..core.events import EventType
from ...cli import get_valid_pal_rates, scan_directory_for_audio
from .file_browser import FileBrowser

import sounddevice as sd
import soundfile as sf

class FileList:
    def __init__(self, parent, state_manager):
        self.state = state_manager
        self.eb = state_manager.eb
        self.files = []
        
        with dpg.child_window(parent=parent, width=340, height=410, border=True):
            dpg.add_text("1. Input Files", color=(136, 192, 208))
            dpg.add_spacer(height=4)
            
            with dpg.group(horizontal=True):
                dpg.add_button(label="+ Add Files", callback=self.on_add_files, width=90)
                dpg.add_button(label="+ Folder", callback=self.on_add_folder, width=90)
                self.btn_clear = dpg.add_button(label="Clear", callback=self.on_clear, width=60, enabled=False)

            dpg.add_spacer(height=4)
            self.lbl_count = dpg.add_text("(0 selected)", color=(136, 136, 136))
            
            with dpg.child_window(height=-1, border=True, tag="file_list_container"):
                self.placeholder = dpg.add_text("No files selected...", tag="file_list_placeholder")

        # Custom Browser
        self.browser = FileBrowser(self._on_browser_files)

        # Subs
        self.eb.subscribe(EventType.FILE_ADDED, self.refresh)
        self.eb.subscribe(EventType.FILE_REMOVED, self.refresh)
        self.eb.subscribe(EventType.FILE_LIST_CLEARED, self.refresh)



    def on_add_files(self): self.browser.show(mode='file')
    def on_add_folder(self): self.browser.show(mode='folder')
    def on_clear(self): self.state.clear_files()
    
    def _on_browser_files(self, selections):
        # Selections can be files or folders depending on mode used
        # We process them all
        final_files = []
        for path in selections:
            if os.path.isdir(path):
                 final_files.extend(scan_directory_for_audio(path))
            else:
                 final_files.append(path)
        
        self.state.add_files(final_files)

    def play_file(self, path):
        if not path or not os.path.exists(path): return
        try:
            sd.stop()
            data, fs = sf.read(path)
            sd.play(data, fs)
        except Exception as e:
            print(f"Playback error: {e}")

    def refresh(self, data=None):
        self.files = self.state.files
        dpg.delete_item("file_list_container", children_only=True)
        
        count = len(self.files)
        dpg.set_value(self.lbl_count, f"({count} selected)")
        dpg.configure_item(self.btn_clear, enabled=(count > 0))
        
        if count == 0:
            dpg.add_text("No files selected...", parent="file_list_container")
            return

        with dpg.table(parent="file_list_container", header_row=False):
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=60)
            
            for f in self.files:
                with dpg.table_row():
                    dpg.add_text(os.path.basename(f))
                    with dpg.group(horizontal=True):
                         dpg.add_button(label=">", width=25, user_data=f, callback=lambda s,a,u: self.play_file(u))
                         dpg.add_button(label="X", width=25, user_data=f, callback=lambda s,a,u: self.state.remove_file(u))
