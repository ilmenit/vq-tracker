
import dearpygui.dearpygui as dpg
from ..core.events import EventType

class LogPanel:
    def __init__(self, parent, state_manager):
        self.state = state_manager
        self.eb = state_manager.eb
        self.tag_log = "log_output_text"
        
        with dpg.child_window(parent=parent, border=True, width=700):
            dpg.add_text("Log Output", color=(100, 110, 120))
            self.input_log = dpg.add_input_text(
                multiline=True, 
                readonly=True, 
                width=-1, 
                height=-1, 
                tag=self.tag_log
            )
            
        # Subscribe
        self.eb.subscribe(EventType.LOG_MESSAGE, self.on_log)
        self.eb.subscribe(EventType.CONSTRAINT_APPLIED, self.on_constraint)
        self.eb.subscribe(EventType.CONSTRAINT_LIFTED, self.on_lifted)

    def log(self, text):
        current = dpg.get_value(self.tag_log) or ""
        msg = str(text)
        # Avoid double newlines if text already has them (e.g. from print redirection)
        # We only add newline if the previous content didn't end with one, or if we want to ensure separation.
        # But here, let's just make sure we don't ADD one if the input already HAS one.
        if not msg.endswith("\n"):
            msg += "\n"
            
        dpg.set_value(self.tag_log, current + msg)
        # Scroll to bottom? DPG auto-scrolls usually

    def on_log(self, data):
        self.log(data)

    def on_constraint(self, msg):
        self.log(f"⚠ NOTICE: {msg}")

    def on_lifted(self, msg):
        self.log(f"ℹ INFO: {msg}")
