import sys
import os
import platform
import shutil
import subprocess
import time
import tempfile
import numpy as np
import scipy.io.wavfile
import scipy.signal
import soundfile as sf

# Project Imports calling parent packages
from ..encoders.vq import VQEncoder
from ..encoders.raw import RawEncoder
from ..utils.quality import calculate_rmse, calculate_psnr, calculate_lsd
from ..utils.mads_exporter import MADSExporter
from ..core.pokey_table import POKEY_VOLTAGE_TABLE_DUAL, POKEY_VOLTAGE_TABLE_FULL, POKEY_MAP_FULL, POKEY_VOLTAGE_TABLE

from .helpers import get_valid_pal_rates, scan_directory_for_audio, merge_samples

class PokeyVQBuilder:
    def __init__(self, args):
        self.args = args
        
        # Determine paths (PyInstaller safe)
        if getattr(sys, 'frozen', False):
            # If running as PyInstaller bundle
            base_path = sys._MEIPASS
            self.pkg_root = base_path # Resources are at root of bundle
        else:
            # Normal Python run
            # script_dir is ".../pokey_vq/cli"
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            # pkg_root is ".../" (atari-player root, containing players/ bin/ etc)
            # dirname(cli) -> pokey_vq
            # dirname(pokey_vq) -> atari-player
            self.pkg_root = os.path.dirname(os.path.dirname(self.script_dir))
            
        self.bin_dir = os.path.join(self.pkg_root, "bin")
        self.players_dir = os.path.join(self.pkg_root, "players")
        
        # Handle input file(s) - support single file or list
        self.input_files = []
        
        # 1. Add direct files
        if isinstance(args.input, list):
            for f in args.input:
                self.input_files.append(os.path.abspath(f))
        elif args.input:
            self.input_files.append(os.path.abspath(args.input))
            
        # 2. Add folder files (Recursive)
        if hasattr(args, 'input_folder') and args.input_folder:
            print(f"  > Scanning input folders: {args.input_folder}")
            for folder in args.input_folder:
                found = scan_directory_for_audio(folder)
                # Avoid duplicates
                for f in found:
                    abs_f = os.path.abspath(f)
                    if abs_f not in self.input_files:
                        self.input_files.append(abs_f)
                print(f"    - Found {len(found)} audio files in '{folder}'")

        if not self.input_files:
             print("Error: No input files specified (use input args or --input-folder).")
             sys.exit(1)
        
        self.is_multi_sample = len(self.input_files) > 1
        self.sample_boundaries = []  # Will be populated during compress()
        self.sample_names = []       # Original filenames
        
        # For backwards compatibility
        self.input_file = self.input_files[0]
        
        # Player Type & Algo Mapping
        # Map --player argument to internal flags
        self.player_mode = args.player
        
        # Defaults
        self.args.algo = 'fixed'
        self.args.tracker = False 
        self.args.pitch = False
        self.player_asm_name = "player.asm"

        if self.player_mode == 'raw':
             self.args.algo = 'raw'
             self.player_asm_name = "raw_player.asm"
             
        elif self.player_mode == 'vq_basic':
             self.args.algo = 'fixed'
             self.player_asm_name = "player.asm"
             
        elif self.player_mode == 'vq_samples':
             self.args.algo = 'fixed'
             self.player_asm_name = "sample_player.asm"
             
        elif self.player_mode == 'vq_pitch':
             self.args.algo = 'fixed'
             self.args.pitch = True
             self.player_asm_name = "pitch_player.asm"
             
        elif self.player_mode == 'vq_multi_channel':
             self.args.algo = 'fixed'
             self.args.tracker = True
             self.player_asm_name = "tracker_player.asm"
             if self.args.channels != 1:
                  print("Error: 'vq_multi_channel' player requires Mono input (--channels 1).")
                  print("       The player uses 3 hardware channels for polyphony, but sources must be mono.")
                  sys.exit(1)

        if self.is_multi_sample:
             if self.player_mode in ['vq_basic', 'raw']:
                 # these players don't support multi-sample strictly speaking (they loop one)
                 # But the encoder can still run. We just warn.
                 print(f"Note: '{self.player_mode}' player does not support interactive sample selection.")
                 print(f"      Multi-sample input will be concatenated into a single continuous track.")

        # Determine Player Type string for internal use if needed
        self.player_type = self.player_mode


        # Determine Output Names
        if args.output:
            # Explicit output specified
            # Check if it looks like a directory (ends in separator)
            if args.output.endswith(os.path.sep) or args.output.endswith('/'):
                # Treat as directory target base
                target_base_dir = os.path.abspath(args.output)
                
                # Auto-generate filename parts (logic reused from auto-gen block below)
                if self.is_multi_sample:
                   base = f"multi_{len(self.input_files)}"
                else:
                   base = os.path.splitext(os.path.basename(self.input_file))[0]
                   
                # Format numbers
                q_str = f"{int(args.quality)}" if args.quality.is_integer() else f"{args.quality}"
                s_str = f"{int(args.smoothness)}" if args.smoothness.is_integer() else f"{args.smoothness}"
                # Player Shorten
                player_short_map = {
                    'vq_basic': 'basic',
                    'vq_samples': 'samp',
                    'vq_pitch': 'pitch',
                    'vq_multi_channel': 'multi',
                    'raw': 'raw'
                }
                p_str = player_short_map.get(self.player_mode, self.player_mode)

                parts = [base, p_str, f"r{args.rate}", f"ch{args.channels}", f"miv{args.min_vector}", f"mav{args.max_vector}", f"q{q_str}", f"s{s_str}"]
                if args.enhance.lower() == 'on': parts.append("enh")
                if args.lbg: parts.append("lbg")
                if args.optimize == 'speed': parts.append("fast")
                if args.iterations != 50: parts.append(f"i{args.iterations}")
                if args.voltage.lower() == 'on': parts.append("vol")

                output_filename = "-".join(parts) + ".xex"
                base_name = os.path.splitext(output_filename)[0]
                
                # Create song-specific subdirectory to avoid collision
                # E.g. players/gen/mk1-scream-fix-enh/
                self.output_subdir = os.path.join(target_base_dir, base_name)
                
                self.final_output_xex = os.path.join(self.output_subdir, output_filename)
                
                # Create the directory
                os.makedirs(self.output_subdir, exist_ok=True)
                
            else:
                # Treat as explicit file path
                self.final_output_xex = os.path.abspath(args.output)
                base_name = os.path.splitext(os.path.basename(args.output))[0]
                self.output_subdir = os.path.dirname(self.final_output_xex)
        else:
            # Auto-generate name based on parameters
            if self.is_multi_sample:
                # Multi-sample: use "multi_N" prefix
                input_base = f"multi_{len(self.input_files)}"
            else:
                input_base = os.path.splitext(os.path.basename(self.input_file))[0]
            
            # Format numbers (remove trailing .0 for integers)
            q_str = f"{int(args.quality)}" if args.quality.is_integer() else f"{args.quality}"
            s_str = f"{int(args.smoothness)}" if args.smoothness.is_integer() else f"{args.smoothness}"
            
            # Player Shorten
            player_short_map = {
                'vq_basic': 'basic',
                'vq_samples': 'samp',
                'vq_pitch': 'pitch',
                'vq_multi_channel': 'multi',
                'raw': 'raw'
            }
            p_str = player_short_map.get(self.player_mode, self.player_mode)

            parts = [input_base, p_str, f"r{args.rate}", f"ch{args.channels}", f"miv{args.min_vector}", f"mav{args.max_vector}", f"q{q_str}", f"s{s_str}"]
            
            if args.enhance.lower() == 'on':
                parts.append("enh")
            if args.lbg:
                parts.append("lbg")
            if args.optimize == 'speed':
                parts.append("fast")
            if args.iterations != 50: # Only add if non-default
                parts.append(f"i{args.iterations}")
            if args.voltage.lower() == 'on':
                 parts.append("vol")
                 
            

            filename = "-".join(parts) + ".xex"
            base_name = os.path.splitext(filename)[0]
            
            # Create structured output directory: "outputs/<base_name>"
            self.output_subdir = os.path.join(os.getcwd(), "outputs", base_name)
            os.makedirs(self.output_subdir, exist_ok=True)
            
            self.final_output_xex = os.path.join(self.output_subdir, filename)

        # WAV Output Determination
        self.wav_output_path = None
        if getattr(args, 'wav', 'off') == 'on':
             base = os.path.splitext(os.path.basename(self.final_output_xex))[0]
             self.wav_output_path = os.path.join(self.output_subdir, base + ".wav")

        # Create Temporary Build Directory
        self.build_dir_obj = tempfile.TemporaryDirectory()
        self.build_dir = self.build_dir_obj.name
        
        # Intermediate Paths (inside temp dir)
        self.output_bin = os.path.join(self.build_dir, base_name + ".bin")
        self.output_asm = os.path.join(self.build_dir, base_name + ".asm")
        self.output_xex = os.path.join(self.build_dir, base_name + ".xex")

        # Rate Validation (Strict PAL POKEY)
        self.valid_rates = get_valid_pal_rates()
        target_rate = args.rate
        
        # Find exact match (within 1 Hz tolerance)
        found_div = -1
        for d, r in self.valid_rates.items():
            if abs(r - target_rate) <= 1.0:
                found_div = d
                break
        
        if found_div == -1:
            # Snap to closest
            closest_div = min(self.valid_rates.keys(), key=lambda d: abs(self.valid_rates[d] - target_rate))
            self.pokey_div = closest_div
            self.actual_rate = self.valid_rates[closest_div]
            print(f"Note: Snapping requested {target_rate} Hz to supported POKEY rate {self.actual_rate:.2f} Hz (Div ${closest_div:02X})")
        else:
            self.pokey_div = found_div
            self.actual_rate = self.valid_rates[found_div]
        
        # Parameter Mapping
        # Quality 0-100 mapped to Lambda 0.5 -> 0.0001 using piecewise log scale
        # 0  -> 0.5 (Low)
        # 50 -> 0.01 (High/Standard)
        # 100 -> 0.0001 (Lossless-ish)
        q = max(0.0, min(100.0, args.quality))
        if q <= 50.0:
            # Range 0-50 maps to 0.5 to 0.01
            # log10(0.5) = -0.301, log10(0.01) = -2.0
            t = q / 50.0
            log_val = -0.30103 + (-2.0 - (-0.30103)) * t
            self.lambda_val = 10 ** log_val
        else:
            # Range 50-100 maps to 0.01 to 0.0001
            # log10(0.01) = -2.0, log10(0.0001) = -4.0
            t = (q - 50.0) / 50.0
            log_val = -2.0 + (-4.0 - (-2.0)) * t
            self.lambda_val = 10 ** log_val
        self.alpha_val = args.smoothness / 100.0

    def print_header(self):
        print("\n" + "="*60)
        print("  PokeyVQ - Atari 8-bit VQ Audio Encoder")
        print("="*60)
        print(f"  Input File:  {os.path.basename(self.input_file)}")
        print(f"  Output File: {os.path.basename(self.final_output_xex)}")
        print("-" * 60)
        print(f"  [General]")
        print(f"  Algorithm:   {self.args.algo.upper()}")
        print(f"  Rate:        {self.actual_rate:.2f} Hz (Divisor ${self.pokey_div:02X})")
        print(f"  Channels:    {self.args.channels} ({'Stereo' if self.args.channels == 2 else 'Mono'})")
        
        opt_str = "Speed (2-byte Fetch)" if self.args.optimize == 'speed' else "Size (1-byte Packed)"
        print(f"  Optimize:    {opt_str}")
        print(f"  Player:      {'Enabled' if not self.args.no_player else 'Disabled'}")
        
        print(f"\n  [Quality]")
        print(f"  Quality:     {self.args.quality} (Lambda: {self.lambda_val:.5f})")
        print(f"  Smoothness:  {self.args.smoothness} (Alpha: {self.alpha_val:.2f})")
        print(f"  Codebook:    {self.args.codebook} entries")
        print(f"  Iterations:  {self.args.iterations}")
        print(f"  Vector Len:  {self.args.min_vector} - {self.args.max_vector}")
        print(f"  LBG Init:    {'Enabled' if self.args.lbg else 'Disabled'}")
        
        vol_state = "Active" if self.args.voltage.lower() == 'on' else "Disabled"
        print(f"  Voltage:     {vol_state} (POKEY Hardware Levels)")
        
        
        print(f"\n  [Processing]")
        enhance_str = "Active (HPF + Limiter + Norm)" if self.args.enhance.lower() == 'on' else "Disabled"
        print(f"  Enhance:     {enhance_str}")
        
        if self.wav_output_path:
            print(f"\n  [Debug]")
            print(f"  WAV Export:  {os.path.basename(self.wav_output_path)}")
            
        print("="*60 + "\n")

    def compress(self):
        print(f"Step 1: Audio Compression")
        print(f"-------------------------")
        
        # Validation
        if self.args.codebook > 256:
             pass

        if self.args.rate > 15000:
             print("Warning: Sample rate > 15000Hz is experimental and may exceed Atari CPU limits.")
             print("         Standard rates are 4000-12000Hz.")

        # Pitch/Tracker Vector Size Validation
        if self.player_mode in ['vq_pitch', 'vq_multi_channel']:
            # Check 1: Min == Max
            if self.args.min_vector != self.args.max_vector:
                print(f"Warning: '{self.player_mode}' requires fixed vector size (Min == Max).")
                print(f"         Forcing Min Vector ({self.args.min_vector}) -> {self.args.max_vector}")
                self.args.min_vector = self.args.max_vector
            
            # Check 2: Even
            if self.args.max_vector % 2 != 0:
                print(f"Warning: '{self.player_mode}' requires EVEN vector size.")
                new_vec = self.args.max_vector + 1
                if new_vec > 16: new_vec = 16 
                print(f"         Rounding {self.args.max_vector} -> {new_vec}")
                self.args.max_vector = new_vec
                self.args.min_vector = new_vec
                
            # Check 3: Range 2-16
            if self.args.max_vector < 2 or self.args.max_vector > 16:
                 # Clamp
                 new_vec = max(2, min(16, self.args.max_vector))
                 print(f"Warning: '{self.player_mode}' requires vector size 2-16.")
                 print(f"         Clamping {self.args.max_vector} -> {new_vec}")
                 self.args.max_vector = new_vec
                 self.args.min_vector = new_vec

        # Multi-sample Safety Override
        if self.is_multi_sample and self.args.algo != 'fixed':
            print(f"Warning: Multi-sample mode requires 'fixed' algorithm (Shared Codebook).")
            print(f"         Switching from '{self.args.algo}' to 'fixed'.")
            self.args.algo = 'fixed'

        # Load audio - handle single or multiple files
        if self.is_multi_sample:
            print(f"  > Loading {len(self.input_files)} audio files (Multi-Sample Mode):")
            
            # Determine alignment from args (if constant vector length requested)
            align = 1
            if self.args.min_vector == self.args.max_vector and self.args.min_vector > 1:
                align = self.args.min_vector
                
            audio, self.sample_boundaries, self.sample_names = merge_samples(
                self.input_files, self.actual_rate, alignment=align
            )
            if audio is None:
                print("Error: Failed to load any audio files.")
                return False
            sr = self.actual_rate  # Already resampled by merge_samples
            print(f"  > Multi-sample: {len(self.sample_boundaries)} samples, boundaries: {self.sample_boundaries}")
        else:
            # Single file mode (original behavior)
            if not os.path.exists(self.input_file):
                raise FileNotFoundError(f"{self.input_file}")

            if os.path.getsize(self.input_file) == 0:
                print(f"Error: Input file is empty: {self.input_file}")
                return False

            print(f"  > Loading audio: {self.input_file}")
            
            # Fast fail on known non-audio types
            ext = os.path.splitext(self.input_file)[1].lower()
            if ext in ['.asm', '.py', '.txt', '.md', '.json', '.c', '.h', '.cpp']:
                print(f"Error: Input file '{os.path.basename(self.input_file)}' does not appear to be an audio file.")
                return False

            try:
                audio, sr = sf.read(self.input_file)
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                audio = audio.astype(np.float32)
            except Exception as e:
                print(f"Error: Failed to load audio file.")
                print(f"       {e}")
                return False

            print(f"    Loaded {len(audio)} samples at {sr} Hz ({len(audio)/sr:.2f}s)")
            
            # Populate boundary for single sample (unified logic)
            self.sample_boundaries = [(0, len(audio))]
            self.sample_names = [os.path.basename(self.input_file)]

        # --- Audio Enhancement Pre-processing ---
        if self.args.enhance.lower() == 'on':
            print("    [ENHANCE] Applying Audio Enhancements...")
            
            # 1. High-Pass Filter (50 Hz) - Gentle cleanup
            print("      - High-Pass Filter (50 Hz)")
            sos = scipy.signal.butter(2, 50, 'hp', fs=sr, output='sos')
            audio = scipy.signal.sosfilt(sos, audio)

            # 2. Dynamic Range Compression / Soft Limiting
            # Goal: Boost average volume (RMS) to compete with 8-bit noise floor,
            # but prevent harsh clipping. 
            print("      - Dynamic Range Compression (Gain + Soft Limiter)")
            
            # Boost gain significantly to bring up quiet details (guitar/vocals)
            input_gain_db = 6.0 
            linear_gain = 10 ** (input_gain_db / 20.0)
            audio = audio * linear_gain
            
            # Soft Limiter (tanh)
            # x_out = tanh(x_in)
            # This "squashes" peaks smoothly instead of hard clipping.
            audio = np.tanh(audio)
            
            # 3. Component Normalization
            # Ensure we use full range -1.0 to 1.0
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio = audio / max_val
            
            print(f"      - Final Peak: {np.max(np.abs(audio)):.2f}")

        # Use ACTUAL hardware rate for compression to avoid pitch shift
        print(f"  > Running VQ Experiment (Rate={self.actual_rate:.2f}Hz, L={self.lambda_val:.5f}, Cb={self.args.codebook})")
        if self.args.lbg:
            print("    [LBG] Using Improved Codebook Initialization (K-Means++ / Splitting)")
        
        # Experiment Selection
        if self.args.algo == 'raw':
            print("    [RAW] Using Pure POKEY Stream (Uncompressed)")
            encoder = RawEncoder(rate=self.actual_rate, dual=(self.args.channels == 2)) 
            
        else: # fixed
            print("    [FIXED] Using Standard VQ")
            encoder = VQEncoder(
                rate=self.actual_rate,
                min_len=self.args.min_vector, 
                max_len=self.args.max_vector,
                lambda_val=self.lambda_val, 
                codebook_size=self.args.codebook,
                max_iterations=self.args.iterations,
                vq_alpha=self.alpha_val, 
                constrained=(self.args.voltage.lower() == 'on'), 
                lbg_init=self.args.lbg,
                channels=self.args.channels,
                sample_boundaries=self.sample_boundaries
            )
        
        # Define export path
        # RAW needs path to generate .raw intermediate. VQ uses manual export.
        do_export_in_run = self.output_bin if self.args.algo == 'raw' else None

        # Run Encoder
        is_fast_cpu = (self.args.optimize == 'speed')
        
        result = encoder.run(audio, sr, bin_export_path=do_export_in_run, fast=is_fast_cpu)
        
        if self.args.algo == 'raw':
            size, decoded, elapsed, final_indices = result
            
            # Setup for WAV simulation
            codebook = [[x] for x in encoder.hw_table]
            indices = final_indices

            # Convert .raw to .asm
            raw_path = do_export_in_run + ".raw"
            if os.path.exists(raw_path):
                with open(raw_path, 'rb') as f:
                    raw_bytes = f.read()
                self._export_raw_asm(raw_bytes)
                print(f"      - Exported RAW ASM: {len(raw_bytes)} bytes")
            else:
                 # RawEncoder might have saved to .bin?
                 # Actually RawEncoder.run logic: if bin_export_path... write .bin, write .raw key
                 pass
        
        else:
            size, decoded, elapsed, codebook, indices = result
        
            # FIXED MODE (Standard VQ)
            # Export manually to ensure Single Channel Table/Packing is used
            print(f"      - Exporting Fixed VQ Data...")
            self._export_data(codebook, indices)

            # --- Calculate Stats for JSON ---
            min_len = min(len(audio), len(decoded))
            rmse = calculate_rmse(audio[:min_len], decoded[:min_len])
            psnr = calculate_psnr(audio[:min_len], decoded[:min_len])
            lsd = calculate_lsd(audio[:min_len], decoded[:min_len], sr=sr)
            duration = len(audio) / sr
            bitrate = size * 8 / duration
            
            # --- Instrument Generation & Metadata ---
            # If tracker mode or multi-sample, generate individual instrument WAVs and JSON
            
            # Use sample boundaries to split indices
            # Re-calculate index boundaries (logic similar to mads_exporter)
            index_boundaries = []
            
            if self.sample_boundaries:
                curr_audio = 0
                boundary_idx = 0
                start_idx = 0
                
                # First sample starts at 0
                
                for i, cb_idx in enumerate(indices):
                    vec_len = len(codebook[cb_idx])
                    next_audio = curr_audio + vec_len
                    
                    if boundary_idx < len(self.sample_boundaries):
                         _, b_end = self.sample_boundaries[boundary_idx]
                         if next_audio >= b_end:
                             # Segment found: start_idx to i+1
                             index_boundaries.append((start_idx, i+1))
                             start_idx = i + 1
                             boundary_idx += 1
                             
                    curr_audio = next_audio
                
                # Catch trailing if any (though loop should cover it)
                if start_idx < len(indices) and len(index_boundaries) < len(self.sample_boundaries):
                    index_boundaries.append((start_idx, len(indices)))
            else:
                # Single sample
                index_boundaries.append((0, len(indices)))

            # Generate Instruments
            import json
            instruments_dir = os.path.join(self.output_subdir, "instruments")
            os.makedirs(instruments_dir, exist_ok=True)
            
            converted_files_info = []
            
            print(f"      - Generating Instruments in: {instruments_dir}")
            
            for i, (start, end) in enumerate(index_boundaries):
                # Valid range?
                if start >= end: continue
                
                # Slice indices
                sub_indices = indices[start:end]
                
                # Simulate
                # Use 48kHz for high quality simulation
                sim_audio = encoder.simulate_hardware_glitch(codebook, sub_indices, self.pokey_div, target_sr=48000)
                
                fname = f"{i+1:03d}.wav"
                out_path = os.path.join(instruments_dir, fname)
                
                if sim_audio is not None:
                     audio_int16 = (sim_audio * 32767).astype(np.int16)
                     scipy.io.wavfile.write(out_path, 48000, audio_int16)
                
                # Info entry
                orig_name = self.sample_names[i] if i < len(self.sample_names) else f"sample_{i}"
                if self.is_multi_sample:
                     # Attempt to find full path from input_files matching basename?
                     # self.input_files are absolute paths.
                     # self.sample_names are basenames.
                     # Let's try to match index if mapping is 1:1
                     # scan_directory_for_audio might reorder? merge_samples returns names.
                     # logic in builder load loop:
                     # self.input_files = [...] (Abs paths)
                     # merge_samples(self.input_files...) -> returns sorted/merged
                     # Currently merge_samples in helpers.py likely preserves order of input list if passed list.
                     # But builder does: for f in found: append.
                     # So self.input_files is the list.
                     # If merge_samples respects that, 1:1 map holds.
                     
                     # However, scan_directory might return recursive list.
                     # self.sample_names came from merge_samples.
                     # Let's hope it's aligned.
                     # Ideally we store full paths in sample_names?
                     # merge_samples implementation: return names as basenames usually.
                     pass

                converted_files_info.append({
                    "original_file": orig_name, # Just basename for display? Request said "full path names to samples"
                    # But sample_names only has basenames from merge_samples.
                    # We need to recover full path if possible. 
                    # If single file -> self.input_files[0]
                    # If multi from folder -> we have self.input_files list.
                    # Assumptions: The order in sample_names matches self.input_files (if merge_samples processes linearly)
                    "instrument_file": os.path.abspath(out_path),
                    "index_start": int(start),
                    "index_end": int(end)
                })
            
            # Enhance converted_info with full paths if possible
            if len(self.input_files) == len(converted_files_info):
                 for j in range(len(converted_files_info)):
                     converted_files_info[j]["original_path"] = self.input_files[j]
            
            # Create JSON
            json_data = {
                "config": {
                    "rate": self.actual_rate,
                    "pokey_divisor": self.pokey_div,
                    "quality": self.args.quality,
                    "codebook_size": self.args.codebook,
                    "min_vector": self.args.min_vector,
                    "max_vector": self.args.max_vector,
                    "channels": self.args.channels,
                    "algorithm": self.args.algo
                },
                "stats": {
                    "size_bytes": size,
                    "bitrate_bps": int(bitrate),
                    "rmse": round(float(rmse), 4),
                    "psnr_db": round(float(psnr), 2),
                    "lsd": round(float(lsd), 4),
                    "duration_seconds": round(float(duration), 2),
                    "state": "success"
                },
                "samples": converted_files_info
            }
            
            json_path = os.path.join(self.output_subdir, "conversion_info.json")
            with open(json_path, 'w') as f:
                json.dump(json_data, f, indent=4)
            print(f"      - Saved Metadata: {json_path}")

        # Quality Metrics (Already calculated above)
        # min_len = min(len(audio), len(decoded))
        # rmse = calculate_rmse(audio[:min_len], decoded[:min_len])
        # psnr = calculate_psnr(audio[:min_len], decoded[:min_len])
        # lsd = calculate_lsd(audio[:min_len], decoded[:min_len], sr=sr)
        # duration = len(audio) / sr
        # bitrate = size * 8 / duration

        print(f"\n  > Compression Results:")
        print(f"    Size:    {size:,} bytes")
        print(f"    Bitrate: {bitrate:.0f} bps")
        print(f"    RMSE:    {rmse:.4f}")
        print(f"    PSNR:    {psnr:.2f} dB")
        print(f"    LSD:     {lsd:.4f}")
        print(f"    Time:    {elapsed:.2f}s")
        print(f"    Output:  {os.path.basename(self.output_bin)}")
        print(f"    ASM:     [Split Files Created]")

        if self.wav_output_path:
            print(f"    WAV:     {os.path.basename(self.wav_output_path)} (Simulating POKEY Hardware Glitch at 48000 Hz)")
            # Use 48kHz target for simulation
            simulated_audio = encoder.simulate_hardware_glitch(
                codebook, indices, self.pokey_div, target_sr=48000
            ) 
            
            # Write WAV
            if simulated_audio is not None:
                audio_int16 = (simulated_audio * 32767).astype(np.int16)
                scipy.io.wavfile.write(self.wav_output_path, 48000, audio_int16)
            else:
                print("    Warning: WAV simulation not implemented for this algorithm.")
            
        # Ensure LUT_NIBBLES.asm exists if needed (for Fixed/Sliding/Raw if using Fast CPU)
        if (self.args.fast or self.args.optimize == 'speed') and self.args.channels == 1:
             # We need an exporter instance
             # Note: MADSExporter is imported
             exporter = MADSExporter()
             exporter.generate_lut_nibbles(self.output_asm)
        
        return True

    def assemble(self):
        print(f"\nStep 2: Player Assembly")
        print(f"-----------------------")
        
        # 1. Locate MADS
        mads = self._find_mads()
        if not mads:
            print("  Error: Could not find MADS assembler.")
            return False

        print(f"  > Using Assembler: {mads}")

        # 2. Use Pre-calculated POKEY Divisor
        print(f"  > POKEY Divisor: ${self.pokey_div:02X} ({self.pokey_div}) -> {self.actual_rate:.2f} Hz")

        # 3. Check for ASM file
        # 3. Check for Split ASM files
        # We expect: VQ_LENS.asm, VQ_LO.asm, VQ_HI.asm, VQ_BLOB.asm, VQ_INDICES.asm
        output_dir = os.path.dirname(self.output_asm)
        if not output_dir: output_dir = "."
        
        split_files = ["VQ_LENS.asm", "VQ_LO.asm", "VQ_HI.asm", "VQ_BLOB.asm", "VQ_INDICES.asm"]
        if self.args.algo == 'raw':
             split_files = ["RAW_DATA.asm"]

        missing = []
        
        for f in split_files:
            src = os.path.join(output_dir, f)
            if not os.path.exists(src):
                missing.append(f)
        
        if missing:
             print(f"  Error: Missing split ASM files: {missing}")
             return False

        # 4. Copy split files to script dir (where MADS runs)
        # Actually MADS runs in current directory or we create a build dir?
        # Original script copied to script_dir.
        # Now script_dir is inside package... we don't want to pollute it.
        # We should copy to . (current CWD) or a build folder.
        # Let's use os.getcwd() for build context or keep them in output_dir.
        
        # NOTE: The split files are ALREADY in output_dir (from compression step).
        # We just need to make sure MADS finds the player ASM and the split files.
        # If we run MADS from output_dir, it's easiest.
        
        build_cwd = output_dir
        
        # 5. Generate vq_cfg.asm
        self._generate_config(build_cwd)


                
        # 6. Copy Player & Lib
        # Select player based on mode
        # self.player_asm_name was determined in __init__
        player_asm_name = self.player_asm_name
        
        src_asm = os.path.join(self.players_dir, player_asm_name)
        dst_asm = os.path.join(build_cwd, player_asm_name)
        
        if not os.path.exists(src_asm):
             print(f"  Error: Could not find player: {src_asm}")
             return False
             
        shutil.copy2(src_asm, dst_asm)
        
        # Copy 'common', 'fixed', 'raw', 'pitch', 'tracker' libraries?
        # Or just copy everything in players/ to build/players/?
        # Our include paths are like "common/pokey_setup.asm".
        # So we need "common" folder in build_cwd.
        
        # Copy common
        src_common = os.path.join(self.players_dir, "common")
        dst_common = os.path.join(build_cwd, "common")
        if os.path.exists(dst_common): shutil.rmtree(dst_common)
        shutil.copytree(src_common, dst_common)
        
        # Copy others depending on need? Or just all for simplicity?
        # All is safer.
        for sub in ['fixed', 'raw', 'pitch', 'tracker']:
             s = os.path.join(self.players_dir, sub)
             d = os.path.join(build_cwd, sub)
             if os.path.exists(s):
                 if os.path.exists(d): shutil.rmtree(d)
                 shutil.copytree(s, d)

        print(f"  > Using Player: {player_asm_name}")
        
        # 7. Build
        cmd = [
            mads,
            player_asm_name,
            f"-o:{os.path.basename(self.output_xex)}"
        ]
        
        try:
            # Run in build_cwd (which is self.build_dir)
            # Capture output so we can print it to the redirected stdout/stderr
            res = subprocess.run(cmd, cwd=build_cwd, capture_output=True, text=True)
            
            # Print MADS output (essential for debugging in GUI)
            if res.stdout: print(res.stdout)
            if res.stderr: print(res.stderr)
            
            if res.returncode != 0:
                 print(f"  Error: Assembly failed (Code {res.returncode})")
                 return False

            print(f"  > Assembly successful!")
            
            # Copy Final XEX to User Location
            shutil.copy2(self.output_xex, self.final_output_xex)
            print(f"  > Created: {self.final_output_xex}")
            
            # Note: Artifact copying moved to run() / _save_vq_data()
            

            
            # Copy lib folder to output as well for completeness/reproducibility? 
            # User asked "Copied to output folder is not fully correct... missing libs". 
            # So yes, we should copy lib folder to output_subdir.
            # Copy all helper folders
            for sub in ['common', 'fixed', 'raw', 'pitch', 'tracker']:
                src_sub = os.path.join(self.players_dir, sub)
                dst_sub = os.path.join(self.output_subdir, sub)
                
                # Safety check: Don't delete source if it maps to destination
                if os.path.abspath(src_sub) == os.path.abspath(dst_sub):
                    continue

                if os.path.exists(src_sub):
                     if os.path.exists(dst_sub): shutil.rmtree(dst_sub)
                     shutil.copytree(src_sub, dst_sub)
            
            print(f"  > Copied player resources to: {self.output_subdir}")
            
            return True
        except Exception as e:
            # General exception (e.g. file not found, permission)
            print(f"  Error during assembly/copy: {e}")
            return False

    def _find_mads(self):
        system = platform.system()
        machine = platform.machine().lower()
        
        # Determine platform folder
        if system == "Linux":
            if "x86_64" in machine:
                plat_dir = "linux_x86_64"
                binary = "mads"
            else:
                 # Fallback or assume x86_64 if unknown?
                 # Or maybe user is on ARM linux (Raspberry Pi)?
                 # We only have x86_64 for now per ls output.
                 plat_dir = "linux_x86_64" 
                 binary = "mads"
        elif system == "Windows":
             plat_dir = "windows_x86_64"
             binary = "mads.exe"
        elif system == "Darwin":
             if "arm64" in machine or "aarch64" in machine:
                 plat_dir = "macos_aarch64"
             else:
                 plat_dir = "macos_x86_64"
             binary = "mads"
        else:
             # Fallback
             plat_dir = "" 
             binary = "mads"

        # Search
        # 1. Check Platform Specific in bin/
        if plat_dir:
            local_path = os.path.join(self.bin_dir, plat_dir, binary)
            if self._is_executable(local_path):
                return local_path
                
        # 2. Check root of bin/ (legacy/fallback)
        local_path = os.path.join(self.bin_dir, binary)
        if self._is_executable(local_path):
             return local_path

        # 3. Check PATH
        path_result = shutil.which(binary)
        if path_result and self._is_executable(path_result):
            return path_result
                
        return None

    def _is_executable(self, filepath):
        if not os.path.exists(filepath):
            return False
        return os.access(filepath, os.X_OK)

    def run(self):
        self.print_header()
        start = time.time()
        try:
            if not self.compress():
                print("\nCompression Failed.")
                return 1
            
            # Generate Config (Needed for both assembly and data export)
            # Use build_dir (which is where assemble expects it)
            self._generate_config(self.build_dir)

            if self.args.no_player:
                print("\nSkipping Player Assembly (--no-player).")
                self._save_vq_data() # Ensure data is saved
                print(f"  > Generated Data only.")
            else:
                if not self.assemble():
                    print("\nAssembly Failed.")
                    return 1
                self._save_vq_data() # Save artifacts after assembly too (keeps consistent behavior)

        except KeyboardInterrupt:
            print("\n\nOperation Cancelled.")
            return 130
        except FileNotFoundError as e:
            print(f"\nError: File not found: {e}")
            return 1
        except Exception as e:
            print(f"\nUnexpected Error: {e}")
            if self.args.debug:
                import traceback
                traceback.print_exc()
            else:
                print("       Use --debug to see full traceback.")
            return 1

        total_time = time.time() - start
        print(f"\n" + "="*60)
        print(f"  DONE! Total Time: {total_time:.2f}s")
        print(f"  Player: {self.final_output_xex}")
        
        # Print total audio length for multi-sample mode
        if self.is_multi_sample and self.sample_boundaries:
            total_samples = self.sample_boundaries[-1][1]  # End of last sample
            total_audio_seconds = total_samples / self.actual_rate
            print(f"  Total Audio Length: {total_audio_seconds:.2f}s ({len(self.sample_boundaries)} samples)")
        
        print("="*60)
        
        # Programmer Info
        print("\n  [NEXT STEPS FOR PROGRAMMERS]")
        print("  1. To include the player in your own project:")
        print("     - Copy 'players/lib/' to your project.")
        print("     - Include 'lib/atari.inc', 'lib/zeropage.inc', 'lib/startup.asm'")
        print(f"     - See '{self.args.algo}-player.asm' in the players/ directory for implementation details.")
        print("  2. To link the data:")
        print("     - The player includes 'VQ_*.asm' files generated in the build step.")
        print("\n" + "="*60 + "\n")
        
        # Cleanup
        # self.build_dir_obj.cleanup() # Automatically called on exit usually
        return 0

    def _export_raw_asm(self, raw_bytes):
        """Export raw byte stream to RAW_DATA.asm for MADS."""
        out_path = os.path.join(os.path.dirname(self.output_asm), "RAW_DATA.asm")
        try:
            with open(out_path, "w") as f:
                f.write(f"RAW_DATA_LEN = {len(raw_bytes)}\n")
                f.write("RAW_DATA\n")
                
                # Write .byte chunks
                chunk_size = 16
                for i in range(0, len(raw_bytes), chunk_size):
                    chunk = raw_bytes[i:i+chunk_size]
                    bytes_str = ",".join([f"${b:02X}" for b in chunk])
                    f.write(f" .byte {bytes_str}\n")
                    
            print(f"Saved MADS ASM: {out_path}")
        except IOError as e:
            print(f"Error writing ASM: {e}")
            
    def _export_data(self, codebook, stream_indices):
        """Manual export for VQ Data."""
        exporter = MADSExporter()
        
        # Select Table
        if self.args.channels == 1:
             # Single Channel: Non-linear 16-level table
             table = POKEY_VOLTAGE_TABLE
             map_full = None
        elif self.args.voltage.lower() == 'on' and 'POKEY_VOLTAGE_TABLE_FULL' in globals():
             table = POKEY_VOLTAGE_TABLE_FULL
             map_full = POKEY_MAP_FULL
        else:
             table = POKEY_VOLTAGE_TABLE_DUAL
             map_full = None
             
        # Export
        exporter.export(self.output_asm, codebook, stream_indices, table, map_full, fast=(self.args.fast or (self.args.optimize == 'speed')), channels=self.args.channels)


        
        # Export Sample Directory if multi-sample mode OR pitch/tracker (which depend on it)
        if (self.is_multi_sample or getattr(self.args, 'pitch', False) or getattr(self.args, 'tracker', False) or self.player_mode == 'vq_samples') and self.sample_boundaries:
            exporter.export_sample_directory(self.output_asm, self.sample_boundaries, stream_indices, codebook, sample_names=self.sample_names)
            print(f"      - Exported SAMPLE_DIR.asm ({len(self.sample_boundaries)} samples)")

    def _generate_config(self, build_cwd):
        """Generate VQ_CFG.asm in the build directory."""
        print(f"  > Generating VQ_CFG.asm...")
        cfg_path = os.path.join(build_cwd, "VQ_CFG.asm")
        with open(cfg_path, "w") as f:
            f.write(f"; Configuration generated by PokeyVQ\n")
            f.write(f"PLAY_RATE = ${self.pokey_div:02X}\n")
            f.write(f"CHANNELS = {self.args.channels}\n")

            if self.args.optimize == 'speed':
                f.write("USE_FAST_CPU = 1\n")
            
            # Standard Config
            f.write("AUDCTL_VAL = $00\n")
            f.write("AUDF1_VAL = PLAY_RATE\n")
            f.write("AUDC1_MASK = $10 ; Vol Only\n")
            f.write("AUDC2_MASK = $10 ; Vol Only\n")
            f.write("IRQ_MASK = 1   ; Timer 1\n")
            
            if self.args.algo == 'raw':
                f.write("ALGO_RAW = 1\n")
            else:
                f.write("ALGO_FIXED = 1\n")
                f.write(f"MIN_VECTOR = {self.args.min_vector}\n")
                f.write(f"MAX_VECTOR = {self.args.max_vector}\n")
                f.write(f"CODEBOOK_SIZE = {self.args.codebook}\n")
            
            # Multi-sample mode
            # Multi-sample / Pitch / Tracker Config
            # Only enable logic for players that support sample selection
            should_enable_multi = self.is_multi_sample and self.player_mode not in ['vq_basic', 'raw']
            
            if should_enable_multi or getattr(self.args, 'pitch', False) or getattr(self.args, 'tracker', False) or self.player_mode == 'vq_samples':
                f.write("MULTI_SAMPLE = 1\n")
                
            if getattr(self.args, 'pitch', False) or getattr(self.args, 'tracker', False):
                f.write("PITCH_CONTROL = 1\n")
            
            # Show CPU Use (0 or 1)
            cpu_val = 1 if (getattr(self.args, 'show_cpu_use', 'on') == 'on') else 0
            f.write(f"SHOW_CPU_USE = {cpu_val}\n")

    def _save_vq_data(self):
        """Copy VQ artifacts to output directory."""
        print(f"  > Copying build artifacts to: {self.output_subdir}")
        
        # Build artifacts list
        if self.args.algo == 'raw':
            artifacts = ["RAW_DATA.asm", "VQ_CFG.asm"]
        else:
            artifacts = ["VQ_LENS.asm", "VQ_LO.asm", "VQ_HI.asm", "VQ_BLOB.asm", "VQ_INDICES.asm", "VQ_CFG.asm"]
        
        if self.args.channels == 1 and not (self.args.fast or self.args.optimize == 'speed'):
            artifacts.append("LUT_NIBBLES.asm")
        
        # Add sample directory if generated (multi-sample OR special players)
        if (self.is_multi_sample or getattr(self.args, 'pitch', False) or getattr(self.args, 'tracker', False) or self.player_mode == 'vq_samples'):
            artifacts.append("SAMPLE_DIR.asm")
        
        # Also copy the main player asm if known
        if hasattr(self, 'player_asm_name'):
             artifacts.append(self.player_asm_name)

        for f_name in artifacts:
            src_artifact = os.path.join(self.build_dir, f_name)
            if os.path.exists(src_artifact):
               shutil.copy2(src_artifact, os.path.join(self.output_subdir, f_name))

