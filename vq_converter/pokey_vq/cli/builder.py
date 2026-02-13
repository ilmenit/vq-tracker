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
        self.stats = None            # Compression stats (populated after compress())
        
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
            
            # Process each instrument INDEPENDENTLY for maximum dynamic range.
            # Each sample should use the full [-1,1] range — the tracker's
            # per-note volume (VOLUME_SCALE) handles relative loudness at playback.
            # Global normalization would let loud instruments starve quiet ones
            # of POKEY levels (only 16 levels available).
            for b_idx, (b_start, b_end) in enumerate(self.sample_boundaries):
                seg = audio[b_start:b_end].copy()
                
                # 1. High-Pass Filter (50 Hz) - remove DC offset and sub-bass rumble
                if len(seg) > 12:  # need enough samples for filter
                    sos = scipy.signal.butter(2, 50, 'hp', fs=sr, output='sos')
                    seg = scipy.signal.sosfilt(sos, seg)
                
                # 2. Gain + Soft Limiter — boost quiet content, prevent clipping
                input_gain_db = 6.0
                linear_gain = 10 ** (input_gain_db / 20.0)
                seg = seg * linear_gain
                seg = np.tanh(seg)
                
                # 3. Per-instrument normalize to full range
                max_val = np.max(np.abs(seg))
                if max_val > 0:
                    seg = seg / max_val
                
                audio[b_start:b_end] = seg
            
            print(f"      - Per-instrument: HP 50Hz + gain +6dB + tanh + normalize")
            print(f"      - {len(self.sample_boundaries)} instruments enhanced independently")

        # Store full merged audio for RAW sample generation
        self._merged_audio = audio.copy()
        self._merged_sr = sr
        self._all_boundaries = list(self.sample_boundaries)
        self._all_names = list(self.sample_names)

        # --- Split VQ / RAW instruments ---
        # VQ encoder should only train on VQ instruments to:
        # 1. Produce a codebook optimized for VQ content only
        # 2. Avoid wasting VQ_INDICES bytes on RAW instruments
        # 3. Avoid wasting VQ_BLOB entries on vectors that only RAW audio needs
        sample_modes = getattr(self.args, 'sample_modes', None) or []
        has_any_raw = any(sample_modes[i] for i in range(min(len(sample_modes), len(self._all_boundaries))))
        has_any_vq = any(not sample_modes[i] if i < len(sample_modes) else True
                         for i in range(len(self._all_boundaries)))

        if has_any_raw and has_any_vq:
            # Mixed mode: extract VQ-only audio for encoding
            vq_segments = []
            vq_boundaries = []
            vq_names = []
            vq_orig_indices = []
            vq_pos = 0

            for i, (start, end) in enumerate(self._all_boundaries):
                is_raw = i < len(sample_modes) and sample_modes[i]
                if not is_raw:
                    seg = audio[start:end]
                    vq_boundaries.append((vq_pos, vq_pos + len(seg)))
                    vq_segments.append(seg)
                    vq_names.append(self._all_names[i] if i < len(self._all_names) else f"inst_{i}")
                    vq_orig_indices.append(i)
                    vq_pos += len(seg)

            audio = np.concatenate(vq_segments)
            self.sample_boundaries = vq_boundaries
            self.sample_names = vq_names
            self._vq_orig_indices = vq_orig_indices

            n_vq = len(vq_orig_indices)
            n_raw = len(self._all_boundaries) - n_vq
            print(f"  > Split: {n_vq} VQ + {n_raw} RAW instruments")
            print(f"    VQ audio: {len(audio)} samples ({len(audio)/sr:.2f}s)")
            raw_total = sum(end - start for i, (start, end) in enumerate(self._all_boundaries)
                           if i < len(sample_modes) and sample_modes[i])
            print(f"    RAW audio: {raw_total} samples ({raw_total/sr:.2f}s) — excluded from VQ codebook")
        elif has_any_raw and not has_any_vq:
            # All RAW: no VQ encoding needed
            self._vq_orig_indices = []
            self.sample_boundaries = []
            self.sample_names = []
            print(f"  > All {len(self._all_boundaries)} instruments are RAW — skipping VQ encoding")
        else:
            # All VQ: no split needed (original behavior)
            self._vq_orig_indices = list(range(len(self._all_boundaries)))

        # Use ACTUAL hardware rate for compression to avoid pitch shift
        if not has_any_vq:
            # ALL instruments are RAW — skip VQ encoding entirely
            # Generate minimal VQ stubs so ASM includes don't break
            codebook = [[0.0] * self.args.min_vector]  # 1 dummy vector
            indices = np.array([], dtype=np.uint8)
            size = 0
            decoded = np.array([], dtype=np.float32)
            elapsed = 0.0
            encoder = None

            print(f"  > Skipping VQ encoding (all instruments RAW)")
            print(f"      - Exporting minimal VQ stubs...")
            self._export_data(codebook, indices)

        else:
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
            do_export_in_run = self.output_bin if self.args.algo == 'raw' else None

            # Run Encoder (on VQ-only audio)
            is_fast_cpu = (self.args.optimize == 'speed')
            
            result = encoder.run(audio, sr, bin_export_path=do_export_in_run, fast=is_fast_cpu)
        
        # Default stats (overwritten in the fixed-VQ branch below)
        duration = len(self._merged_audio) / sr
        rmse = psnr = lsd = 0.0
        
        if not has_any_vq:
            # All-RAW path handled above — jump to end of compress
            pass
        elif self.args.algo == 'raw':
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
                 pass
        
        else:
            size, decoded, elapsed, codebook, indices = result
        
            # FIXED MODE (Standard VQ) — VQ-only audio was encoded
            print(f"      - Exporting Fixed VQ Data (VQ instruments only)...")
            self._export_data(codebook, indices)

            # --- Calculate Stats for VQ instruments only ---
            min_len = min(len(audio), len(decoded))
            rmse = calculate_rmse(audio[:min_len], decoded[:min_len])
            psnr = calculate_psnr(audio[:min_len], decoded[:min_len])
            lsd = calculate_lsd(audio[:min_len], decoded[:min_len], sr=sr)
            duration = len(self._merged_audio) / sr  # Total duration (all instruments)
            vq_duration = len(audio) / sr  # VQ-only duration
            bitrate = size * 8 / vq_duration if vq_duration > 0 else 0

        # --- Compute VQ index boundaries (common, outside if/elif/else) ---
        # Maps VQ boundary index → (index_start, index_end) in VQ_INDICES
        vq_index_boundaries = []
        vq_boundary_for_orig = {}

        if has_any_vq and self.args.algo != 'raw' and self.sample_boundaries:
            curr_audio = 0
            boundary_idx = 0
            start_idx = 0
            
            for i, cb_idx in enumerate(indices):
                vec_len = len(codebook[cb_idx])
                next_audio = curr_audio + vec_len
                
                if boundary_idx < len(self.sample_boundaries):
                     _, b_end = self.sample_boundaries[boundary_idx]
                     if next_audio >= b_end:
                         vq_index_boundaries.append((start_idx, i+1))
                         start_idx = i + 1
                         boundary_idx += 1
                         
                curr_audio = next_audio
            
            if start_idx < len(indices) and len(vq_index_boundaries) < len(self.sample_boundaries):
                vq_index_boundaries.append((start_idx, len(indices)))
            
            for vq_idx, orig_idx in enumerate(self._vq_orig_indices):
                if vq_idx < len(vq_index_boundaries):
                    vq_boundary_for_orig[orig_idx] = vq_idx

        # --- Generate Instrument Preview WAVs (ALL instruments, original order) ---
        # Runs for all modes: all-VQ, mixed, and all-RAW
        if self.is_multi_sample and self._all_boundaries:
            import json
            instruments_dir = os.path.join(self.output_subdir, "instruments")
            os.makedirs(instruments_dir, exist_ok=True)
            converted_files_info = []
            
            n_total = len(self._all_boundaries)
            print(f"      - Generating {n_total} instrument previews in: {instruments_dir}")
            
            from pokey_vq.encoders.raw import RawEncoder
            from pokey_vq.core.pokey_table import POKEY_VOLTAGE_TABLE
            
            for orig_idx in range(n_total):
                fname = f"{orig_idx+1:03d}.wav"
                out_path = os.path.join(instruments_dir, fname)
                orig_name = self._all_names[orig_idx] if orig_idx < len(self._all_names) else f"sample_{orig_idx}"
                is_raw = orig_idx < len(sample_modes) and sample_modes[orig_idx]
                
                idx_start = 0
                idx_end = 0
                
                if is_raw:
                    # RAW instrument: quantize audio → POKEY voltage levels → ZOH → WAV
                    a_start, a_end = self._all_boundaries[orig_idx]
                    segment = self._merged_audio[a_start:a_end]
                    use_ns = self.actual_rate >= 6000
                    vol_indices = RawEncoder.quantize(segment, POKEY_VOLTAGE_TABLE,
                                                     noise_shaping=use_ns)
                    # Reconstruct via ZOH (matching VQ preview and real hardware)
                    table_norm = POKEY_VOLTAGE_TABLE / POKEY_VOLTAGE_TABLE[-1]
                    quantized = table_norm[vol_indices]  # [0, 1] range
                    
                    POKEY_CLOCK = 1773447
                    period_int = int(POKEY_CLOCK / self.actual_rate)
                    high_res = np.repeat(quantized, period_int)
                    n_48k = int(len(high_res) * 48000 / POKEY_CLOCK)
                    if n_48k > 0:
                        sim_audio = scipy.signal.resample(high_res, n_48k).astype(np.float32)
                        sim_audio = (sim_audio - 0.5) * 2.0  # [0,1] → [-1,1]
                        audio_int16 = (sim_audio * 32767).astype(np.int16)
                        scipy.io.wavfile.write(out_path, 48000, audio_int16)
                else:
                    # VQ instrument: simulate from VQ indices
                    if orig_idx in vq_boundary_for_orig and encoder is not None:
                        vq_idx = vq_boundary_for_orig[orig_idx]
                        start, end = vq_index_boundaries[vq_idx]
                        idx_start = start
                        idx_end = end
                        if start < end:
                            sub_indices = indices[start:end]
                            sim_audio = encoder.simulate_hardware_glitch(
                                codebook, sub_indices, self.pokey_div, target_sr=48000)
                            if sim_audio is not None:
                                audio_int16 = (sim_audio * 32767).astype(np.int16)
                                scipy.io.wavfile.write(out_path, 48000, audio_int16)
                
                converted_files_info.append({
                    "original_file": orig_name,
                    "instrument_file": os.path.abspath(out_path),
                    "index_start": int(idx_start),
                    "index_end": int(idx_end),
                    "mode": "RAW" if is_raw else "VQ"
                })
            
            # Enhance with full paths
            if len(self.input_files) == len(converted_files_info):
                 for j in range(len(converted_files_info)):
                     converted_files_info[j]["original_path"] = self.input_files[j]
            
            # Create JSON
            actual_size = getattr(self, 'actual_data_size', size)
            vq_dur = vq_duration if has_any_vq and self.args.algo != 'raw' else 0.0
            actual_bitrate = actual_size * 8 / duration if duration > 0 else 0
            
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
                    "size_bytes": actual_size,
                    "bitrate_bps": int(actual_bitrate),
                    "rmse": round(float(rmse), 4),
                    "psnr_db": round(float(psnr), 2),
                    "lsd": round(float(lsd), 4),
                    "duration_seconds": round(float(duration), 2),
                    "vq_duration_seconds": round(float(vq_dur), 2),
                    "state": "success"
                },
                "samples": converted_files_info
            }
            
            self.stats = json_data["stats"]
            
            json_path = os.path.join(self.output_subdir, "conversion_info.json")
            with open(json_path, 'w') as f:
                json.dump(json_data, f, indent=4)
            print(f"      - Saved Metadata: {json_path}")

        # --- Final Stats ---
        if not has_any_vq:
            # All-RAW: no VQ stats
            duration = len(self._merged_audio) / sr
            size = 0
            rmse = psnr = lsd = 0.0
            elapsed = 0.0
        
        actual_size = getattr(self, 'actual_data_size', size)
        actual_bitrate = actual_size * 8 / duration if duration > 0 else 0
        
        print(f"\n  > Compression Results:")
        print(f"    Sample Data: {actual_size:,} bytes")
        if has_any_vq:
            print(f"    Bitrate: {actual_bitrate:.0f} bps (VQ only)")
            print(f"    RMSE:    {rmse:.4f}")
            print(f"    PSNR:    {psnr:.2f} dB")
            print(f"    LSD:     {lsd:.4f}")
            print(f"    Time:    {elapsed:.2f}s")
        else:
            print(f"    (All instruments RAW — no VQ compression stats)")
        print(f"    Output:  {os.path.basename(self.output_bin)}")
        print(f"    ASM:     [Split Files Created]")

        if self.wav_output_path and encoder is not None:
            print(f"    WAV:     {os.path.basename(self.wav_output_path)} (Simulating POKEY Hardware Glitch at 48000 Hz)")
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
        """Export VQ data (codebook/indices) and mixed SAMPLE_DIR + RAW_SAMPLES.
        
        After the compress() refactor:
        - codebook/stream_indices contain VQ-only data (RAW instruments excluded)
        - self.sample_boundaries = VQ-only boundaries
        - self._all_boundaries = ALL instrument boundaries (original ordering)
        - self._vq_orig_indices = maps VQ boundary index → original instrument index
        """
        exporter = MADSExporter()
        
        # Select Table
        if self.args.channels == 1:
             table = POKEY_VOLTAGE_TABLE
             map_full = None
        elif self.args.voltage.lower() == 'on' and 'POKEY_VOLTAGE_TABLE_FULL' in globals():
             table = POKEY_VOLTAGE_TABLE_FULL
             map_full = POKEY_MAP_FULL
        else:
             table = POKEY_VOLTAGE_TABLE_DUAL
             map_full = None
        # Always prebake $10 (AUDC volume-only mode bit) into sample data.
        # The IRQ handler uses conditional assembly:
        #   VOLUME_CONTROL=0: direct STA to AUDC (no ORA needed, saves 2 cycles/ch)
        #   VOLUME_CONTROL=1: AND #$0F to strip bit before volume lookup
        audc_prebake = True
             
        # Export VQ blob/indices/LO/HI (VQ-only data)
        self.actual_data_size = exporter.export(
            self.output_asm, codebook, stream_indices, table, map_full,
            fast=(self.args.fast or (self.args.optimize == 'speed')),
            channels=self.args.channels,
            audc_prebake=audc_prebake)

        # Export SAMPLE_DIR + RAW_SAMPLES for ALL instruments
        all_boundaries = getattr(self, '_all_boundaries', self.sample_boundaries)
        all_names = getattr(self, '_all_names', self.sample_names)
        vq_orig_indices = getattr(self, '_vq_orig_indices', list(range(len(all_boundaries))))
        sample_modes = getattr(self.args, 'sample_modes', None)
        has_multi = (self.is_multi_sample or getattr(self.args, 'pitch', False)
                     or getattr(self.args, 'tracker', False)
                     or self.player_mode == 'vq_samples')
        
        if has_multi and all_boundaries:
            raw_labels = {}

            # Generate RAW AUDC data for RAW instruments
            if sample_modes and any(m for m in sample_modes):
                merged_audio = getattr(self, '_merged_audio', None)
                if merged_audio is not None:
                    # Noise shaping: effective when Nyquist >> audible band
                    use_ns = self.actual_rate >= 6000
                    raw_labels = exporter.export_raw_samples(
                        self.output_asm, all_boundaries,
                        merged_audio, sample_modes,
                        sample_names=all_names,
                        audc_prebake=audc_prebake,
                        noise_shaping=use_ns)
                    n_raw = sum(1 for m in sample_modes if m)
                    total_pages = sum(info[2] for info in raw_labels.values())
                    raw_data_bytes = total_pages * 256
                    self.actual_data_size += raw_data_bytes
                    ns_str = " [noise-shaped]" if use_ns else ""
                    print(f"      - Exported RAW_SAMPLES.asm ({n_raw} RAW instruments, {total_pages} pages, {raw_data_bytes} bytes){ns_str}")

            # Pre-compute VQ stream offsets for VQ instruments
            # Walk VQ-only indices to find stream byte positions per VQ boundary
            vq_stream_starts = []
            vq_stream_ends = []
            
            if self.sample_boundaries and len(stream_indices) > 0:
                curr_audio = 0
                boundary_idx = 0
                vq_stream_starts.append(0)
                
                for i, cb_idx in enumerate(stream_indices):
                    vec_len = len(codebook[cb_idx])
                    next_audio = curr_audio + vec_len
                    
                    while boundary_idx < len(self.sample_boundaries):
                        _, b_end = self.sample_boundaries[boundary_idx]
                        if next_audio >= b_end:
                            vq_stream_ends.append(i + 1)
                            if boundary_idx + 1 < len(self.sample_boundaries):
                                vq_stream_starts.append(i + 1)
                            boundary_idx += 1
                        else:
                            break
                    curr_audio = next_audio
                
                if len(vq_stream_ends) < len(self.sample_boundaries):
                    vq_stream_ends.append(len(stream_indices))
            
            # Build per-instrument addressing: {orig_idx: (stream_start, stream_end)}
            vq_stream_map = {}
            for vq_idx, orig_idx in enumerate(vq_orig_indices):
                if vq_idx < len(vq_stream_starts) and vq_idx < len(vq_stream_ends):
                    vq_stream_map[orig_idx] = (vq_stream_starts[vq_idx], vq_stream_ends[vq_idx])

            exporter.export_sample_directory_mixed(
                self.output_asm, len(all_boundaries),
                vq_stream_map=vq_stream_map,
                raw_labels=raw_labels,
                sample_modes=sample_modes,
                sample_names=all_names)
            print(f"      - Exported SAMPLE_DIR.asm ({len(all_boundaries)} instruments: "
                  f"{len(vq_stream_map)} VQ + {len(raw_labels)} RAW)")
        
        # Generate RAW_SAMPLES.asm stub if none generated
        raw_samples_path = os.path.join(os.path.dirname(self.output_asm), "RAW_SAMPLES.asm")
        if not os.path.exists(raw_samples_path):
            with open(raw_samples_path, 'w') as f:
                f.write("; RAW_SAMPLES.asm - Page-aligned raw AUDC data for RAW instruments\n")
                f.write("; (Empty - all instruments use VQ compression)\n")

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
            artifacts = ["VQ_LENS.asm", "VQ_LO.asm", "VQ_HI.asm", "VQ_BLOB.asm", "VQ_INDICES.asm", "VQ_CFG.asm", "RAW_SAMPLES.asm"]
        
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

