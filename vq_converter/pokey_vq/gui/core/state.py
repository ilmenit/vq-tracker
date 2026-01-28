from .events import EventType
import threading
import os
import sys
from types import SimpleNamespace
from contextlib import redirect_stdout, redirect_stderr
import copy

# Load Defaults
try:
    import json
    _def_path = os.path.join(os.path.dirname(__file__), '../default_config.json')
    with open(_def_path, 'r') as f:
        DEFAULT_CONFIG = json.load(f)
except Exception as e:
    print(f"WARNING: Could not load default_config.json: {e}. Using hardcoded defaults.")
    DEFAULT_CONFIG = {
        'player_mode': 'vq_basic',
        'channels': 'Dual',
        'rate': 7917, # Approx
        'quality': 50,
        'smoothness': 0,
        'enhance': True,
        'codebook': "256",
        'iters': 50,
        'vec_min': 1,
        'vec_max': 16,
        'lbg': False,
        'voltage': False,
        'optimize': 'Size',
        'wav': True,
        'show_cpu': True,
        'gen_player': True
    }

# Import Builder
# Try relative first, then absolute path hack if needed
try:
    from ...cli import PokeyVQBuilder
except ImportError:
    # If running from root without package context sometimes
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
    from pokey_vq.cli import PokeyVQBuilder

class EventLogStream:
    """Redirects writes to EventBus."""
    def __init__(self, eb):
        self.eb = eb
    def write(self, text):
        if text:
            self.eb.publish(EventType.LOG_MESSAGE, text)
    def flush(self): pass


class StateManager:
    def __init__(self, event_bus):
        self.eb = event_bus
        self._suppress_autosave = False
        
        
        # State Data
        self.files = []
        self.history = []
        
        # Config State
        self.config = copy.deepcopy(DEFAULT_CONFIG)


        # User Preference Memory (for restoration)
        self.saved_state = {}

        # Mappings
        self.player_map = {
             "Standard VQ (vq_basic)": "vq_basic",
             "Multi-Sample (vq_samples)": "vq_samples",
             "Pitch Control (vq_pitch)": "vq_pitch",
             "Multi-Channel (vq_multi_channel)": "vq_multi_channel",
             "Raw Uncompressed (raw)": "raw"
        }
        self.reverse_player_map = {v: k for k, v in self.player_map.items()}

        # Check for Auto-Save
        self._check_for_autosave()

    def broadcast_current_state(self):
        """Force broadcast of all current state."""
        self.eb.publish(EventType.STATE_CHANGED, {'config': self.config})
        
        if self.files:
            self.eb.publish(EventType.FILE_ADDED, self.files)
            self._check_file_constraints()
        else:
            self.eb.publish(EventType.FILE_LIST_CLEARED)
            
        if self.history:
              self.eb.publish(EventType.HISTORY_UPDATED, self.history)
              
        # Mode
        self.eb.publish(EventType.PLAYER_MODE_CHANGED, self.config['player_mode'])

    def get(self, key):
        return self.config.get(key)

    def set(self, key, value, silent=False):
        """Generic setter."""
        if key == 'player_mode':
             self.set_player_mode(value)
             return

        if self.config.get(key) != value:
            self.config[key] = value
            if not silent:
                self.eb.publish(EventType.STATE_CHANGED, {key: value})
                self._auto_save()

    # --- Specific Actions ---

    def add_files(self, new_files):
        """Add files to the list."""
        added_count = 0
        for f in new_files:
            if f not in self.files:
                self.files.append(f)
                added_count += 1
        
        if added_count > 0:
            self.eb.publish(EventType.FILE_ADDED, self.files)
            self._check_file_constraints()
            self._auto_save()

    def remove_file(self, filepath):
        if filepath in self.files:
            self.files.remove(filepath)
            self.eb.publish(EventType.FILE_REMOVED, self.files)
            self._check_file_constraints()
            self._auto_save()

    def clear_files(self):
        self.files = []
        self.eb.publish(EventType.FILE_LIST_CLEARED)
        
        # Reset Options logic
        # When clearing files, we should ensure 'Raw' is available again if it was hidden
        # The constraint logic usually runs on set_player_mode or check_file_constraints.
        # We might need to "refresh" constraints.
        self._check_file_constraints()
        self._auto_save()

    def set_player_mode(self, mode_code):
        """Set player mode and handle constraints."""
        if mode_code not in self.player_map.values():
             # maybe it's the label?
             if mode_code in self.player_map:
                 mode_code = self.player_map[mode_code]
        
        old_mode = self.config['player_mode']
        if old_mode == mode_code:
            return

        self.config['player_mode'] = mode_code
        self.eb.publish(EventType.PLAYER_MODE_CHANGED, mode_code)
        
        # Apply Constraints
        self._apply_player_constraints(mode_code, old_mode)

    def _apply_player_constraints(self, new_mode, old_mode):
        """Logic for dependency handling."""
        
        is_raw = (new_mode == "raw")
        is_pitch = (new_mode in ["vq_pitch", "vq_multi_channel"])
        
        # 1. RAW Mode Constraints
        if is_raw:
             # Logic to disable VQ params is handled by UI listening to mode change
             pass
        
        if is_pitch:
             # Check if we need to save state
             # (We assume if we aren't in pitch mode, we are in 'user' mode for vectors)
             if old_mode not in ["vq_pitch", "vq_multi_channel"]:
                 self.saved_state['vectors'] = (self.config['vec_min'], self.config['vec_max'])
                 
             self.config['vec_min'] = 16
             self.config['vec_max'] = 16
             
             self.eb.publish(EventType.STATE_CHANGED, {'vec_min': 16, 'vec_max': 16})
             self.eb.publish(EventType.CONSTRAINT_APPLIED, "Forced Vector Size to 16/16 (Required for Pitch/Multi-Channel).")
             
        elif old_mode in ["vq_pitch", "vq_multi_channel"] and not is_raw:
             # Restore
             if 'vectors' in self.saved_state:
                 vmin, vmax = self.saved_state.pop('vectors')
                 self.config['vec_min'] = vmin
                 self.config['vec_max'] = vmax
                 self.eb.publish(EventType.STATE_CHANGED, {'vec_min': vmin, 'vec_max': vmax})
                 self.eb.publish(EventType.CONSTRAINT_LIFTED, f"Restored Vector Size to {vmin}/{vmax}.")

        if new_mode == "vq_multi_channel":
             if self.config['channels'] != "Single":
                 self.saved_state['channels'] = self.config['channels']
                 
             self.config['channels'] = "Single"
             self.eb.publish(EventType.STATE_CHANGED, {'channels': "Single"})
             
             # Also force Optimize=Speed (Tracker player requires fast lookup)
             if self.config['optimize'] != "Speed":
                  self.saved_state['optimize'] = self.config['optimize']
                  
             self.config['optimize'] = "Speed"
             self.eb.publish(EventType.STATE_CHANGED, {'optimize': "Speed"})
             
             self.eb.publish(EventType.CONSTRAINT_APPLIED, "Forced 'Single' Channel & 'Speed' Opt (Required for Multi-Channel).")
             
        elif old_mode == "vq_multi_channel":
             # Restore
             if 'channels' in self.saved_state:
                 val = self.saved_state.pop('channels')
                 self.config['channels'] = val
                 self.eb.publish(EventType.STATE_CHANGED, {'channels': val})
                 
             if 'optimize' in self.saved_state:
                 val = self.saved_state.pop('optimize')
                 self.config['optimize'] = val
                 self.eb.publish(EventType.STATE_CHANGED, {'optimize': val})
                 
             self.eb.publish(EventType.CONSTRAINT_LIFTED, f"Restored constraints.")


    def _check_file_constraints(self):
        """Constraints based on file count."""
        count = len(self.files)
        
        # Multi-file -> No Raw
        if count > 1:
            if self.config['player_mode'] == 'raw':
                self.eb.publish(EventType.LOG_MESSAGE, "Switched to Standard VQ (Raw not supported for multiple files).")
                self.set_player_mode('vq_basic')
            
            # Broadcast constraint for UI to hide 'Raw'
            # We can use a special event or just let UI check count
            pass

    # --- Build Logic ---

    def start_build(self):
        """Start build in thread."""
        if not self.files:
            self.eb.publish(EventType.LOG_MESSAGE, "ERROR: No files selected.")
            return

        self.eb.publish(EventType.BUILD_STARTED, None)
        thread = threading.Thread(target=self._execute_build)
        thread.start()

    def _execute_build(self):
        try:
            # Construct Args from Config
            c = self.config
            args = SimpleNamespace(
                input=self.files if len(self.files) > 1 else self.files[0],
                output=None,
                quality=c['quality'],
                smoothness=c['smoothness'],
                player=c['player_mode'],
                rate=c['rate'],
                min_vector=c['vec_min'],
                max_vector=c['vec_max'],
                iterations=c['iters'],
                enhance='on' if c['enhance'] else 'off',
                lbg=c['lbg'],
                voltage='on' if c['voltage'] else 'off',
                codebook=int(c['codebook']),
                wav='on' if c['wav'] else 'off',
                no_player=not c['gen_player'],
                fast=False,
                fast_cpu=False,
                optimize=c['optimize'].lower(),
                channels=1 if c['channels'] == 'Single' else 2,
                show_cpu_use='on' if c['show_cpu'] else 'off',
                debug=False
            )

            # Log Command
            cmd = f"python3 -m pokey_vq ... --player {c['player_mode']} ..."
            self.eb.publish(EventType.LOG_MESSAGE, f"Starting Build...\nParams: {c}\nFiles: {len(self.files)}")

            builder = PokeyVQBuilder(args)
            stream = EventLogStream(self.eb)
            
            with redirect_stdout(stream), redirect_stderr(stream):
                 ret = builder.run()
            
            if ret == 0:
                self.eb.publish(EventType.LOG_MESSAGE, "\nSUCCESS: Build Complete.")
                
                # Add to history
                if hasattr(builder, 'final_output_xex') and builder.final_output_xex:
                     self._add_history_item(builder.final_output_xex)

                self.eb.publish(EventType.BUILD_FINISHED, True)
                
                # Report Stats from JSON
                try:
                    if hasattr(builder, 'output_subdir'):
                        json_path = os.path.join(builder.output_subdir, "conversion_info.json")
                        if os.path.exists(json_path):
                            with open(json_path, 'r') as f:
                                info = json.load(f)
                            
                            if 'stats' in info:
                                s = info['stats']
                                msg = (
                                    f"\n[Conversion Results]\n"
                                    f"  Status:  {s.get('state', 'Unknown').upper()}\n"
                                    f"  Size:    {s.get('size_bytes', 0):,} bytes\n"
                                    f"  Bitrate: {s.get('bitrate_bps', 0)} bps\n"
                                    f"  RMSE:    {s.get('rmse', 0):.4f}\n"
                                    f"  PSNR:    {s.get('psnr_db', 0):.2f} dB\n"
                                    f"  LSD:     {s.get('lsd', 0):.4f}"
                                )
                                self.eb.publish(EventType.LOG_MESSAGE, msg)
                except Exception as e:
                    self.eb.publish(EventType.LOG_MESSAGE, f"Warning: Could not read conversion stats: {e}")
            else:
                self.eb.publish(EventType.LOG_MESSAGE, "\nFAILURE: Build Failed.")
                self.eb.publish(EventType.BUILD_FINISHED, False)
                
        except Exception as e:
            import traceback
            self.eb.publish(EventType.LOG_MESSAGE, f"CRITICAL ERROR: {e}\n{traceback.format_exc()}")
            self.eb.publish(EventType.BUILD_FINISHED, False)

    def _add_history_item(self, filepath):
        """Add item to history."""
        filename = os.path.basename(filepath)
        wav_path = os.path.splitext(filepath)[0] + ".wav"
        output_dir = os.path.dirname(filepath)
        
        # Remove duplicate based on filename
        self.history = [h for h in self.history if os.path.basename(h['path']) != filename]
        
        # Add to top
        new_item = {
            'path': filepath,
            'dir': output_dir,
            'wav': wav_path
        }
        self.history.insert(0, new_item)
        self.eb.publish(EventType.HISTORY_UPDATED, self.history)

    # --- Persistence ---

    def save_configuration(self, filepath):
        """Save current configuration to JSON."""
        import json
        try:
            data = {
                'config': self.config,
                'files': self.files
            }
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
            self.eb.publish(EventType.LOG_MESSAGE, f"Configuration saved to: {filepath}")
        except Exception as e:
            self.eb.publish(EventType.LOG_MESSAGE, f"ERROR saving configuration: {e}")

    def load_configuration(self, filepath):
        """Load configuration from JSON."""
        self._suppress_autosave = True
        import json
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Restore files
            if 'files' in data:
                self.files = []
                # Filter valid files
                for p in data['files']:
                    if os.path.exists(p):
                        self.files.append(p)
                
                self.eb.publish(EventType.FILE_LIST_CLEARED)
                if self.files:
                    self.eb.publish(EventType.FILE_ADDED, self.files)
                    self._check_file_constraints()
            
            # Restore Config
            if 'config' in data:
                loaded_conf = data['config']
                # Update specific keys to avoid overwriting defaults with old bad data if schema changes,
                # but for now blind update is okay as long as keys match.
                for k, v in loaded_conf.items():
                    if k in self.config:
                        self.set(k, v)
                
                # Force mode sync
                if 'player_mode' in loaded_conf:
                    self.set_player_mode(loaded_conf['player_mode'])

            # Broadcast full config sync for UI
            self.eb.publish(EventType.STATE_CHANGED, {'config': self.config})

            self.eb.publish(EventType.LOG_MESSAGE, f"Configuration loaded from: {filepath}")
            
        except Exception as e:
            self.eb.publish(EventType.LOG_MESSAGE, f"ERROR loading configuration: {e}")
        finally:
            self._suppress_autosave = False

    # --- Reliability ---
    
    def _auto_save(self):
        """Auto-save current state to restart-config.json."""
        if self._suppress_autosave:
            return
            
        try:
             # We can just reuse save_configuration but suppress logs or check verbose
             # Use current dir
             import json
             path = "restart-config.json"
             data = {
                 'config': self.config,
                 'files': self.files
             }
             # Atomic write would be better but simple write is okay/fast
             with open(path, 'w') as f:
                 json.dump(data, f, indent=4)
        except Exception:
             # Silent fail
             pass

    def _check_for_autosave(self):
         path = "restart-config.json"
         if os.path.exists(path):
             self.eb.publish(EventType.LOG_MESSAGE, "Restoring previous session...")
             self.load_configuration(path)
             
    def reset_to_defaults(self):
         """Reset all settings to defaults."""
         self.config = copy.deepcopy(DEFAULT_CONFIG)
         self.files = []
         self.saved_state = {}
         
         self.eb.publish(EventType.FILE_LIST_CLEARED)
         self.eb.publish(EventType.STATE_CHANGED, {'config': self.config})
         # Ensure mode sync
         self.eb.publish(EventType.PLAYER_MODE_CHANGED, self.config['player_mode'])
         
         self.eb.publish(EventType.LOG_MESSAGE, "All settings reset to defaults.")
         self._auto_save()
