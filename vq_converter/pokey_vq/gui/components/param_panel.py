
import dearpygui.dearpygui as dpg
from ..core.events import EventType
from ...cli.helpers import get_valid_pal_rates

class ParamPanel:
    def __init__(self, parent, state_manager):
        self.state = state_manager
        self.eb = state_manager.eb
        
        def _add_tooltip(parent, text):
            with dpg.tooltip(parent):
                dpg.add_text(text)
        
        # Options
        self.player_opts = list(self.state.player_map.keys())
        
        # Rate Options (Full PAL Palette restricted to usable range)
        # User Req: Div $03 (15834 Hz) to Div $29 (1508 Hz)
        raw_rates = get_valid_pal_rates() # {divisor: frequency}
        
        self.rate_list = []
        self.label_to_freq = {}
        self.freq_to_label = {}
        
        for div in range(0x03, 0x2A): # 0x29 inclusive
            if div in raw_rates:
                freq = raw_rates[div]
                # Label format: "Div $XX: YYYYY Hz"
                lbl = f"Div ${div:02X}: {int(freq)} Hz"
                self.rate_list.append(lbl)
                self.label_to_freq[lbl] = freq
                self.freq_to_label[int(freq)] = lbl

        self.rate_labels = self.rate_list
        
        with dpg.child_window(parent=parent, width=340, height=410, border=True):
            dpg.add_text("2. Basic Configuration", color=(136, 192, 208))
            dpg.add_spacer(height=4)
            
            dpg.add_text("Player Mode:")
            init_mode_code = self.state.get('player_mode')
            init_label = self.state.reverse_player_map.get(init_mode_code, "Standard VQ (vq_basic)")
            
            self.combo_player = dpg.add_combo(
                self.player_opts, 
                default_value=init_label,
                callback=self._on_player_change
            )
            _add_tooltip(self.combo_player, "Select playback engine.\nPitch/Multi-Channel modes force Vector Length=16.\nRaw mode disables VQ compression.")
            
            dpg.add_spacer(height=4)
            
            # Channel / Rate
            self.lbl_channels = dpg.add_text("Channels:")
            self.radio_chan = dpg.add_radio_button(
                ["Dual", "Single"], 
                default_value="Dual", 
                horizontal=True,
                callback=lambda s,a: self.state.set('channels', a)
            )
            
            dpg.add_text("Rate:")
            
            # Init Value
            init_freq = self.state.get('rate')
            # Find closest
            init_rate_lbl = self._find_closest_rate_label(init_freq)

            self.combo_rate = dpg.add_combo(
                self.rate_labels,
                default_value=init_rate_lbl,
                callback=self._on_rate_change
            )
            
            dpg.add_separator()
            
            # Quality Slider
            self.slider_qual = dpg.add_slider_int(
                label="Quality", default_value=50, max_value=100,
                callback=lambda s,a: self.state.set('quality', a)
            )
            _add_tooltip(self.slider_qual, "Control trade-off between Size and Fidelity (Lambda).")
            
            self.slider_smooth = dpg.add_slider_int(
                label="Smoothness", default_value=0, max_value=100,
                callback=lambda s,a: self.state.set('smoothness', a)
            )
            _add_tooltip(self.slider_smooth, "Reduce clicking by penalizing large vector changes.")
            
            dpg.add_spacer(height=10)
            self.chk_enhance = dpg.add_checkbox(label="Enhance (HPF+Limit)", default_value=True,
                callback=lambda s,a: self.state.set('enhance', a))
            _add_tooltip(self.chk_enhance, "Apply High-Pass Filter and Limiter to input.")
            
            # Persistence
            dpg.add_spacer(height=10)
            dpg.add_separator()
            dpg.add_text("Preset: None")
            with dpg.group(horizontal=True):
                dpg.add_button(label="Save", width=75, callback=self._on_save_clicked)
                dpg.add_button(label="Load", width=75, callback=self._on_load_clicked)
                dpg.add_spacer(width=10)
                dpg.add_button(label="Reset", width=75, callback=self._on_reset_clicked)
            
            # Subscribe
            self.eb.subscribe(EventType.STATE_CHANGED, self.sync_ui)
            self.eb.subscribe(EventType.PLAYER_MODE_CHANGED, self.sync_mode)
            self.eb.subscribe(EventType.FILE_ADDED, lambda d: self.update_player_options(d))
            self.eb.subscribe(EventType.FILE_REMOVED, lambda d: self.update_player_options(d))
            self.eb.subscribe(EventType.FILE_LIST_CLEARED, lambda d: self.update_player_options([]))

    def update_player_options(self, files):
        # In this event, we might get list of files or it might be state.files
        # Best to rely on state
        current_files = self.state.files 
        count = len(current_files)
        
        # Filter options
        if count > 1:
            filtered = [p for p in self.player_opts if "raw" not in p.lower()]
            dpg.configure_item(self.combo_player, items=filtered)
            
            # Use state config to check current mode
            current_mode = self.state.config['player_mode']
            if current_mode == 'raw':
                 self.state.set_player_mode('vq_basic')
                 self.eb.publish(EventType.LOG_MESSAGE, "Switched to Standard VQ (Raw not supported for multiple files).")
        else:
            # Restore all
            dpg.configure_item(self.combo_player, items=self.player_opts)

    def _on_player_change(self, sender, app_data):
        # Convert Label to Code
        code = self.state.player_map.get(app_data)
        self.state.set_player_mode(code)

    def sync_mode(self, mode_code):
        # Sync Combo Label if changed externally (e.g. by constraint)
        label = self.state.reverse_player_map.get(mode_code)
        if label:
            dpg.set_value(self.combo_player, label)
            
    def _on_rate_change(self, sender, app_data):
        # Look up freq
        freq = self.label_to_freq.get(app_data)
        if freq:
             self.state.set('rate', int(freq))

    def _find_closest_rate_label(self, target_freq):
        # Exact match?
        t_int = int(target_freq)
        if t_int in self.freq_to_label:
            return self.freq_to_label[t_int]
            
        # Find closest
        # We iterate our labels, parse frequencies or use our reverse map items
        closest_dist = float('inf')
        closest_lbl = self.rate_labels[0]
        
        for freq, label in self.freq_to_label.items():
            dist = abs(freq - target_freq)
            if dist < closest_dist:
                closest_dist = dist
                closest_lbl = label
        return closest_lbl

    def sync_ui(self, data):
        # Update enabled states / values
        if 'channels' in data:
            dpg.set_value(self.radio_chan, data['channels'])
            
            # Check if we should disable?
            # Ideally StateManager sends a 'constraint' event or we check state logic
            # Use 'state.config' to see if forced 
            # In our logic, 'Single' forced usually means Mode=Multi.
            is_multi = (self.state.config['player_mode'] == 'vq_multi_channel')
            
            # Use show instead of enabled for Multi-channel
            show_channels = not is_multi
            dpg.configure_item(self.lbl_channels, show=show_channels)
            dpg.configure_item(self.radio_chan, show=show_channels)

        if 'player_mode' in self.state.config: 
             # Re-evaluate all constraints
             mode = self.state.config['player_mode']
             # Quality is relevant for: vq_basic, vq_samples
             # Irrelevant/Hidden for: vq_pitch, vq_multi_channel, raw
             show_qual = mode in ['vq_basic', 'vq_samples']
             dpg.configure_item(self.slider_qual, show=show_qual)

        if 'config' in data:
            # Broad sync if whole config replaced
            c = self.state.config
            if 'quality' in c: dpg.set_value(self.slider_qual, c['quality'])
            if 'smoothness' in c: dpg.set_value(self.slider_smooth, c['smoothness'])
            if 'enhance' in c: dpg.set_value(self.chk_enhance, c['enhance'])
            if 'rate' in c: 
                 lbl = self._find_closest_rate_label(c['rate'])
                 dpg.set_value(self.combo_rate, lbl)
            if 'channels' in c: dpg.set_value(self.radio_chan, c['channels'])
            if 'player_mode' in c:
                lbl = self.state.reverse_player_map.get(c['player_mode'])
                if lbl: dpg.set_value(self.combo_player, lbl)

        if 'rate' in data:
             r = data['rate']
             lbl = self._find_closest_rate_label(r)
             dpg.set_value(self.combo_rate, lbl)

    def _on_save_clicked(self):
        with dpg.file_dialog(
            directory_selector=False, 
            show=True, 
            callback=self._on_file_dialog_ok, 
            user_data="save",
            width=700,
            height=400,
            default_filename="pokey_vq_cfg.json"
        ):
            dpg.add_file_extension(".json", color=(150, 255, 150, 255))
            dpg.add_file_extension(".*")

    def _on_load_clicked(self):
        with dpg.file_dialog(
            directory_selector=False, 
            show=True, 
            callback=self._on_file_dialog_ok, 
            user_data="load",
            width=700,
            height=400
        ):
            dpg.add_file_extension(".json", color=(150, 255, 150, 255))
            dpg.add_file_extension(".*")

    def _on_file_dialog_ok(self, sender, app_data, user_data):
        # app_data varies by DPG version but usually contains 'file_path_name' or 'file_path_name' in dict
        # In recent DPG: app_data = {'file_path_name': ..., 'file_name': ...}
        
        filepath = app_data.get('file_path_name')
        if not filepath:
            return
            
        if user_data == "save":
            self.state.save_configuration(filepath)
        elif user_data == "load":
            self.state.load_configuration(filepath)

    def _on_reset_clicked(self):
        # Confirmation Modal
        if dpg.does_item_exist("modal_reset"):
             dpg.delete_item("modal_reset")
             
        with dpg.window(label="Confirm Reset", modal=True, show=True, tag="modal_reset", width=300, height=150):
             dpg.add_text("Are you sure you want to reset\nall settings to defaults?")
             dpg.add_spacer(height=20)
             with dpg.group(horizontal=True):
                 dpg.add_button(label="Yes, Reset", width=100, callback=self._do_reset)
                 dpg.add_button(label="Cancel", width=100, callback=lambda: dpg.delete_item("modal_reset"))

    def _do_reset(self, sender, app_data):
        dpg.delete_item("modal_reset")
        self.state.reset_to_defaults()
