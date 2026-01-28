
import dearpygui.dearpygui as dpg
import sys
import os

from .core.events import EventBus
from .core.state import StateManager

from .components.file_list import FileList
from .components.param_panel import ParamPanel
from .components.advanced_panel import AdvancedPanel
from .components.log_panel import LogPanel
from .components.action_panel import ActionPanel

class PokeyApp:
    def __init__(self):
        self.event_bus = EventBus()
        self.state = StateManager(self.event_bus)
        
        # Setup DPG
        dpg.create_context()
        self.setup_theme()
        
    def setup_theme(self):
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (35, 39, 46))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (76, 86, 106))
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
        dpg.bind_theme(global_theme)

    def build_ui(self):
        with dpg.window(tag="main_window"):
             dpg.add_spacer(height=5)
             
             # Top Section (Cols)
             with dpg.group(horizontal=True, tag="grp_top"):
                 self.comp_files = FileList("grp_top", self.state)
                 dpg.add_spacer(width=10)
                 self.comp_params = ParamPanel("grp_top", self.state)
                 dpg.add_spacer(width=10)
                 self.comp_advanced = AdvancedPanel("grp_top", self.state)

             dpg.add_spacer(height=10)
             
             # Bottom Section (Log + Action)
             with dpg.group(horizontal=True, tag="grp_bottom"):
                 self.comp_log = LogPanel("grp_bottom", self.state)
                 dpg.add_spacer(width=10)
                 self.comp_action = ActionPanel("grp_bottom", self.state)
             
             # Force UI Sync
             self.state.broadcast_current_state()



    def verify_quit(self, sender=None, app_data=None, user_data=None):
        if dpg.does_item_exist("modal_quit"):
            dpg.delete_item("modal_quit")

        # Center the modal
        vp_width = dpg.get_viewport_width()
        vp_height = dpg.get_viewport_height()
        # Fallback defaults if 0
        if vp_width < 100: vp_width = 1150
        if vp_height < 100: vp_height = 750
        
        mod_w = 300
        mod_h = 120
        pos_x = (vp_width - mod_w) // 2
        pos_y = (vp_height - mod_h) // 2

        with dpg.window(label="Confirm Exit", modal=True, show=True, tag="modal_quit", width=mod_w, height=mod_h, pos=(pos_x, pos_y), no_resize=True, no_move=True):
            dpg.add_spacer(height=5)
            
            # Center text approx (window 300, text ~200?)
            with dpg.group(horizontal=True):
                 dpg.add_spacer(width=45)
                 dpg.add_text("Are you sure you want to quit?")
            
            dpg.add_spacer(height=20)
            
            # Center buttons
            # 300 - 16(pad) = 284. Buttons 200 + 8(gap) = 208. Diff 76. Shift 38.
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=38)
                dpg.add_button(label="Yes, Quit", width=100, callback=lambda: dpg.stop_dearpygui())
                dpg.add_button(label="Cancel", width=100, callback=lambda: dpg.delete_item("modal_quit"))

    def run(self):
        dpg.create_viewport(title="PokeyVQ - 8bit Pokey Player of compressed audio", width=1150, height=750, disable_close=True)
        dpg.set_exit_callback(self.verify_quit)
        self.build_ui()
        
        # Menu Bar
        with dpg.viewport_menu_bar():
            with dpg.menu(label="File"):
                dpg.add_menu_item(label="Quit", callback=self.verify_quit)

        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("main_window", True)
        dpg.start_dearpygui()
        dpg.destroy_context()

if __name__ == "__main__":
    app = PokeyApp()
    app.run()
