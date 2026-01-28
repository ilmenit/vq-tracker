
import dearpygui.dearpygui as dpg
import os
import sys
import subprocess
import sounddevice as sd
import soundfile as sf
from ..core.events import EventType

class ActionPanel:
    def __init__(self, parent, state_manager):
        self.state = state_manager
        self.eb = state_manager.eb
        
        # Theme for huge button
        with dpg.theme() as self.convert_theme:
             with dpg.theme_component(dpg.mvButton):
                 dpg.add_theme_color(dpg.mvThemeCol_Button, (163, 190, 140))
                 dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (180, 210, 155))
                 dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (140, 170, 120))
                 dpg.add_theme_color(dpg.mvThemeCol_Text, (30, 35, 40))


        with dpg.child_window(parent=parent, width=-1, height=-1, border=True):
             self.btn_convert = dpg.add_button(
                 label="CONVERT", 
                 width=-1, 
                 height=50, 
                 callback=lambda: self.state.start_build()
             )
             dpg.bind_item_theme(self.btn_convert, self.convert_theme)
             
             dpg.add_spacer(height=10)
             
             with dpg.child_window(height=-1, border=True, tag="history_container"):
                 dpg.add_text("No files generated yet...", color=(85, 85, 85))

        # Subs
        self.eb.subscribe(EventType.HISTORY_UPDATED, self.refresh_history)
        self.eb.subscribe(EventType.BUILD_STARTED, lambda d: dpg.configure_item(self.btn_convert, label="Building...", enabled=False))
        self.eb.subscribe(EventType.BUILD_FINISHED, lambda d: dpg.configure_item(self.btn_convert, label="CONVERT", enabled=True))

    def play_wav(self, path):
        if not path or not os.path.exists(path): return
        try:
            sd.stop()
            data, fs = sf.read(path)
            sd.play(data, fs)
        except Exception as e:
            print(f"Playback error: {e}")

    def refresh_history(self, history_list):
        dpg.delete_item("history_container", children_only=True)
        if not history_list:
            dpg.add_text("No files generated yet...", parent="history_container", color=(85, 85, 85))
            return
            
        for item in history_list:
            name = os.path.basename(item['path'])
            has_wav = os.path.exists(item['wav'])
            
            with dpg.group(parent="history_container"):
                dpg.add_text(name, color=(200, 200, 200))
                with dpg.group(horizontal=True):
                    dpg.add_button(label="xex", width=40, callback=self.open_file, user_data=item['path'])
                    
                    if has_wav:
                        dpg.add_button(label="> wav", width=50, callback=lambda s,a,u: self.play_wav(u), user_data=item['wav'])
                    else:
                        dpg.add_button(label="wav", width=40, enabled=False)
                        
                    dpg.add_button(label="Dir", width=40, callback=self.open_folder, user_data=item['dir'])
                    
                    # Size label (if exists)
                    if os.path.exists(item['path']):
                        sz = os.path.getsize(item['path'])
                        dpg.add_text(f"xex: {sz:,} bytes", color=(100, 255, 100))
                dpg.add_separator()

    def open_file(self, sender, app_data, path):
        if not path or not os.path.exists(path): return
        try:
            if sys.platform == 'win32': os.startfile(path)
            elif sys.platform == 'darwin': subprocess.run(['open', path])
            else: subprocess.run(['xdg-open', path])
        except: pass

    def open_folder(self, sender, app_data, path):
        if not path or not os.path.exists(path): return
        try:
            if sys.platform == 'win32': os.startfile(path)
            elif sys.platform == 'darwin': subprocess.run(['open', path])
            else: subprocess.run(['xdg-open', path])
        except: pass
