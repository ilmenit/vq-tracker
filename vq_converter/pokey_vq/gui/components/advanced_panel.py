
import dearpygui.dearpygui as dpg
from ..core.events import EventType

class AdvancedPanel:
    def __init__(self, parent, state_manager):
        self.state = state_manager
        self.eb = state_manager.eb
        
        def _add_tooltip(parent, text):
            with dpg.tooltip(parent):
                dpg.add_text(text)
        
        with dpg.child_window(parent=parent, width=340, height=410, border=True):
            dpg.add_text("3. Advanced Configuration", color=(136, 192, 208))
            dpg.add_spacer(height=4)
            
            dpg.add_text("Algorithm:")
            self.combo_cb = dpg.add_combo(["256","128","64","32"], default_value=str(self.state.get('codebook')), label="Codebook",
                 callback=lambda s,a: self.state.set('codebook', a))
                 
            self.input_iter = dpg.add_input_int(default_value=self.state.get('iters'), label="Iters",
                 callback=lambda s,a: self.state.set('iters', a))
            _add_tooltip(self.input_iter, "Max VQ training iterations.")
            
            dpg.add_separator()
            dpg.add_text("Vectors:")
            
            # Standard Controls
            self.input_vmin = dpg.add_input_int(default_value=self.state.get('vec_min'), label="Min Vec",
                 callback=lambda s,a: self.state.set('vec_min', a))
            _add_tooltip(self.input_vmin, "Minimum vector length.")

            self.input_vmax = dpg.add_input_int(default_value=self.state.get('vec_max'), label="Max Vec",
                 callback=lambda s,a: self.state.set('vec_max', a))
            _add_tooltip(self.input_vmax, "Maximum vector length.")

            # Pitch/Tracker Replacement Control (Hidden by default)
            # Reverse order 16..2 usually better so 16 is top? Or 2..16? 
            # User list: 2, 4, 6, 8, 10, 12, 14, 16. Default 16.
            self.vec_opts = [str(x) for x in range(2, 17, 2)] 
            self.combo_veclen = dpg.add_combo(self.vec_opts, default_value="16", label="Vector Len", show=False,
                 callback=self._on_veclen_change)
            _add_tooltip(self.combo_veclen, "Fixed Vector Size (Even values 2-16).\nThe smaller Vector size, the better quality but larger file size.")
                 
            dpg.add_spacer(height=4)
                 
            dpg.add_spacer(height=4)
            with dpg.group(horizontal=True):
                 self.chk_lbg = dpg.add_checkbox(label="LBG init", default_value=self.state.get('lbg'),
                     callback=lambda s,a: self.state.set('lbg', a))
                 dpg.add_spacer(width=15)
                 self.chk_voltage = dpg.add_checkbox(label="Voltage Ctrl", default_value=self.state.get('voltage'),
                     callback=lambda s,a: self.state.set('voltage', a))

            dpg.add_separator()
            dpg.add_spacer(height=8)
            
            # Output Control
            self.chk_player = dpg.add_checkbox(label="Generate Player (.xex)", default_value=self.state.get('gen_player'),
                 callback=lambda s,a: self.state.set('gen_player', a))
            
            with dpg.group(horizontal=True) as self.group_optimize:
                 dpg.add_text("Optimize:")
                 dpg.add_spacer(width=10)
                 self.radio_optimize = dpg.add_radio_button(["Size", "Speed"], default_value=self.state.get('optimize'), horizontal=True,
                     callback=lambda s,a: self.state.set('optimize', a))
            
            with dpg.group(horizontal=True):
                 self.chk_wav = dpg.add_checkbox(label="Simulate WAV", default_value=self.state.get('wav'),
                     callback=lambda s,a: self.state.set('wav', a))
                 dpg.add_spacer(width=15)
                 self.chk_cpu = dpg.add_checkbox(label="Show CPU", default_value=self.state.get('show_cpu'),
                     callback=lambda s,a: self.state.set('show_cpu', a))
                 
            # Subs
            self.eb.subscribe(EventType.STATE_CHANGED, self.sync_ui)

    def _on_veclen_change(self, sender, app_data):
        val = int(app_data)
        # Set both min and max to same value
        self.state.set('vec_min', val)
        self.state.set('vec_max', val)

    def sync_ui(self, data):
        # 1. Config Object Sync (Load)
        if 'config' in data:
            c = data['config']
            # Map keys to UI elements
            if 'codebook' in c: dpg.set_value(self.combo_cb, c['codebook'])
            if 'iters' in c: dpg.set_value(self.input_iter, c['iters'])
            if 'lbg' in c: dpg.set_value(self.chk_lbg, c['lbg'])
            if 'voltage' in c: dpg.set_value(self.chk_voltage, c['voltage'])
            if 'gen_player' in c: dpg.set_value(self.chk_player, c['gen_player'])
            if 'optimize' in c: dpg.set_value(self.radio_optimize, c['optimize'])
            if 'wav' in c: dpg.set_value(self.chk_wav, c['wav'])
            if 'show_cpu' in c: dpg.set_value(self.chk_cpu, c['show_cpu'])
            if 'vec_min' in c: dpg.set_value(self.input_vmin, c['vec_min'])
            if 'vec_max' in c: dpg.set_value(self.input_vmax, c['vec_max'])
        
        # 2. Individual Updates
        if 'codebook' in data: dpg.set_value(self.combo_cb, data['codebook'])
        if 'iters' in data: dpg.set_value(self.input_iter, data['iters'])
        if 'lbg' in data: dpg.set_value(self.chk_lbg, data['lbg'])
        if 'voltage' in data: dpg.set_value(self.chk_voltage, data['voltage'])
        if 'gen_player' in data: dpg.set_value(self.chk_player, data['gen_player'])
        if 'optimize' in data: dpg.set_value(self.radio_optimize, data['optimize'])
        if 'wav' in data: dpg.set_value(self.chk_wav, data['wav'])
        if 'show_cpu' in data: dpg.set_value(self.chk_cpu, data['show_cpu'])

        # Handle Vector Constraints
        # Check if vectors changed (could be forced)
        if 'vec_min' in data: dpg.set_value(self.input_vmin, data['vec_min'])
        if 'vec_max' in data: 
            dpg.set_value(self.input_vmax, data['vec_max'])
            # Also sync combo if value is in list and we are in special mode
            val_str = str(data['vec_max'])
            if val_str in self.vec_opts:
                dpg.set_value(self.combo_veclen, val_str)
        
        # Check enablement and visibility based on current mode
        if 'player_mode' in self.state.config: 
            mode = self.state.config['player_mode']
            
            # Identify special modes: pitch and multi
            is_special = mode in ["vq_pitch", "vq_multi_channel"]
            
            if is_special:
                 dpg.configure_item(self.input_vmin, show=False)
                 dpg.configure_item(self.input_vmax, show=False)
                 dpg.configure_item(self.combo_veclen, show=True)
            else:
                 dpg.configure_item(self.input_vmin, show=True)
                 dpg.configure_item(self.input_vmax, show=True)
                 dpg.configure_item(self.combo_veclen, show=False)
            
            # Hide Optimize for Multi-Channel (Forced to Speed)
            if mode == "vq_multi_channel":
                 dpg.configure_item(self.group_optimize, show=False)
            else:
                 dpg.configure_item(self.group_optimize, show=True)
