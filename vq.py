"""
pokey_vq/encoders/vq.py - FIXED VERSION

FIXED: PY-1 - Removed invalid slide_interval parameter from exporter.export() call
FIXED: PY-4 - Removed duplicate self.lbg_init assignment
"""

import os
import time
import numpy as np
import scipy.signal
from scipy.spatial.distance import cdist
from ..core.experiment import Encoder
from ..core.pokey_table import POKEY_VOLTAGE_TABLE_DUAL, POKEY_VOLTAGE_TABLE_FULL, POKEY_VOLTAGE_TABLE
from ..utils.mads_exporter import MADSExporter
# POKEY_MAP_FULL import if needed for MADS export
try:
    from ..core.pokey_table import POKEY_MAP_FULL
except ImportError:
    POKEY_MAP_FULL = None



class VQEncoder(Encoder):
    def __init__(self, rate=8000, min_len=2, max_len=16, 
                 lambda_val=0.01, codebook_size=256, 
                 max_iterations=50, max_time=300,
                 vq_alpha=0.0, constrained=False, lbg_init=False,
                 channels=2, sample_boundaries=None):
        super().__init__(f"VQVariable_{rate}Hz_Len{min_len}-{max_len}_L{lambda_val}_A{vq_alpha}{'_Cnst' if constrained else ''}{'_Mono' if channels==1 else ''}")
        self.rate = rate
        self.min_len = min_len
        self.max_len = max_len
        self.lambda_val = lambda_val
        self.codebook_size = codebook_size
        self.max_iterations = max_iterations
        self.max_time = max_time
        self.vq_alpha = vq_alpha
        self.constrained = constrained
        self.lbg_init = lbg_init
        # FIX PY-4: Removed duplicate assignment (was: self.lbg_init = lbg_init twice)
        self.channels = channels
        # Multi-sample: list of (start, end) tuples in sample units
        self.sample_boundaries = sample_boundaries if sample_boundaries else []
        
    def run(self, audio, sr, bin_export_path=None, fast=False):
        # 1. Preprocess
        if sr != self.rate:
            num_samples = int(len(audio) * self.rate / sr)
            audio_resampled = scipy.signal.resample(audio, num_samples)
        else:
            audio_resampled = audio
            
        # FIXED LENGTH CONSTRAINT PADDING
        if self.min_len == self.max_len:
            rem = len(audio_resampled) % self.min_len
            if rem > 0:
                pad_len = self.min_len - rem
                # Pad with silence (value 0.0 before normalization, or -1.0..1.0 domain?)
                # Audio here is typically -1..1 or similar (loaded by soundfile/librosa or wave).
                # Main load logic in cli.py/core loads float -1..1 usually.
                # Just append 0.0 (silence).
                audio_resampled = np.pad(audio_resampled, (0, pad_len), 'constant', constant_values=0.0)
                # print(f"DEBUG: Auto-padded audio by {pad_len} samples to match fixed vector length {self.min_len}.")

            
        # Normalize 0..1
        audio_norm = (audio_resampled + 1.0) / 2.0
        audio_norm = np.clip(audio_norm, 0.0, 1.0)
        
        # 2. Train (Segmental K-Means)
        start_time = time.time()
        
        generator = VariableCodebookGenerator(
            self.codebook_size, 
            self.min_len, 
            self.max_len,
            self.lambda_val,
            self.vq_alpha,
            self.constrained,
            self.lbg_init,
            channels=self.channels,
            sample_boundaries=self.sample_boundaries
        )
        
        codebook_entries, indices = generator.train(
            audio_norm, 
            max_iterations=self.max_iterations, 
            max_time=self.max_time
        )
        
        elapsed = time.time() - start_time
        
        # 3. Decode / Reconstruct
        decoded_audio = self._reconstruct(codebook_entries, indices, len(audio_norm))
        decoded_audio = (decoded_audio - 0.5) * 2.0
        
        # 4. Save
        if bin_export_path:
            # Generates .asm file
            base, ext = os.path.splitext(bin_export_path)
            if ext == '.bin': 
                asm_path = base + ".asm"
            else:
                asm_path = bin_export_path + ".asm"
                
            exporter = MADSExporter()
            
            if self.constrained and 'POKEY_VOLTAGE_TABLE_FULL' in globals():
                 table = POKEY_VOLTAGE_TABLE_FULL
                 map_full = POKEY_MAP_FULL
            else:
                 table = POKEY_VOLTAGE_TABLE_DUAL
                 map_full = None
                 
            # FIX PY-1: Removed invalid slide_interval parameter
            # Old code: exporter.export(asm_path, codebook_entries, indices, table, map_full, fast=fast, slide_interval=0)
            # The MADSExporter.export() method does NOT have a slide_interval parameter!
            exporter.export(asm_path, codebook_entries, indices, table, map_full, fast=fast, channels=self.channels)
            
        # 5. Metrics Prep
        if bin_export_path:
             cb_blob_size = sum(len(e) for e in codebook_entries)
             size = 768 + cb_blob_size + len(indices) # Header overhead estimate
        else:
             cb_blob_size = sum(len(e) for e in codebook_entries)
             size = 768 + cb_blob_size + len(indices)
             
        # Resample back
        if self.rate != sr:
            num_samples = int(len(decoded_audio) * sr / self.rate)
            decoded_resampled = scipy.signal.resample(decoded_audio, num_samples)
        else:
            decoded_resampled = decoded_audio
            
        return size, decoded_resampled, elapsed, codebook_entries, indices



    def _reconstruct(self, codebook_entries, indices, total_samples):
        output = np.zeros(total_samples, dtype=np.float32)
        pos = 0
        for idx in indices:
            vec = codebook_entries[idx]
            l = len(vec)
            if pos + l > total_samples:
                l = total_samples - pos
                output[pos:pos+l] = vec[:l]
                break
            output[pos:pos+l] = vec
            pos += l
        return output

    def simulate_hardware_glitch(self, codebook_entries, indices, pokey_div, target_sr=48000):
        """
        Simulates the mechanical noise/glitch caused by sequential register updates on POKEY.
        
        Logic:
        1. Base Clock: 1.77MHz (PAL) or similar.
        2. Sample Rate: Derived from Divisor.
        3. For every sample transition:
           - Update Channel 1 (AUDC1) -> Glitch State (New Ch1 + Old Ch2)
           - Wait X cycles (ASM instruction delay)
           - Update Channel 2 (AUDC2) -> Stable State (New Ch1 + New Ch2)
        """
        # Constants
        POKEY_CLOCK = 1773447 # PAL
        ASM_DELAY_CYCLES = 11  # STA AUDC1 (4) + LDA/AND/ORA overhead etc ~7-10 cycles. 11 is safe estimate.
        
        # Calculate Period in Cycles
        # Divisor D -> Frequency = Clock / 28 / (D+1) ?? 
        # Standard geometric mean is often used, but POKEY docs say:
        # Fout = Fin / 2 / N   (where N is divisor) -> ACTUALLY depends on AUDCTL
        # 64kHz mode: Fout = 64kHz / (n+1)
        # 15kHz mode: Fout = 15kHz / (n+1)
        # We assume 64kHz mode (Divisor mode generally implies this for soft-synths)
        # 64kHz base clock is ~ 1773447 / 28 = 63337 Hz
        
        base_clock = POKEY_CLOCK / 28.0
        period_cycles = (28.0 * (pokey_div + 1)) # Time in 1.77MHz cycles for one sample
        
        # Supersampling factor
        # generating 1.77MHz signal is too much RAM (10s = 17MB floats). perfectly fine for modern PC.
        # Let's generate at 1.77MHz.
        
        total_samples_out = int(len(indices) * period_cycles) # Rough estimate, might vary slightly
        
        # Reconstruct the sequence of (Ch1, Ch2) values
        # We need the raw nibbles, not the voltage sum.
        
        # 1. Flatten indices to full vector sequence
        full_vectors = []
        for idx in indices:
            vec = codebook_entries[idx]
            full_vectors.extend(vec)
            
        full_vectors = np.array(full_vectors)
            
        # Single Channel Mode: No hardware glitch simulation needed (single channel is stable).
        # We just output the stepped waveform.
        if self.channels == 1:
             # Find nearest voltage in single channel table
             # Note: full_vectors are normalized 0-1 values.
             # POKEY_VOLTAGE_TABLE is 0-0.55. 
             # Wait, training normalized them to POKEY_VOLTAGE_TABLE domain.
             # So full_vectors should match table values closely.
             # We just replicate them.
             
             # Expand to high res
             period_int = int(period_cycles)
             high_res = np.repeat(full_vectors, period_int)
             
             # Resample
             num_target_samples = int(len(high_res) * target_sr / POKEY_CLOCK)
             resampled = scipy.signal.resample(high_res, num_target_samples)
             
             # Center
             # full_vectors is 0..1 (Normalized Audio Domain)
             # Just map to -1..1 for WAV output
             resampled = (resampled - 0.5) * 2.0
             
             return resampled
        
        # 2. Quantize to Ch1/Ch2 Nibbles
        # We need to reverse the POKEY Table mapping.
        # Efficient way: Precompute Map: Voltage -> (v1, v2)
        # Note: We used self.pokey_levels for training which are unique sorted voltages.
        # We need to map those back to 0-15, 0-15 pairs.
        
        # Use simple search in DUAL table to find index, then map to nibbles
        # DUAL table (31 levels) structure: 
        # Index 0..30
        # V1 = Index // 2
        # V2 = Index - V1
        
        # If using FULL table it's harder, but we can search best match in 256 map
        
        # Let's assume DUAL for now as 'constrained' without full table implies DUAL.
        # If 'constrained' + FULL, we need the map.
        
        if self.constrained and 'POKEY_VOLTAGE_TABLE_FULL' in globals():
             # NOT IMPLEMENTED FULLY FOR REVERSE MAPPING YET
             # Fallback to DUAL logic for safety or implement brute force map
             # For this task, we assume the user is hitting the DUAL glitch.
             pass
             
        # Map 0..1 float back to 0..30 integer index
        # We can use digitize or searchsorted on POKEY_VOLTAGE_TABLE_DUAL
        
        # Prepare Output buffer
        # We'll generate chunks to save RAM if needed, but 10s is manageable.
        
        # POKEY VOLTAGE LOOKUP (Single Channel 0-15)
        # We need the non-linear volume table for *single* channel to sum them up manually.
        # POKEY_VOLTAGE_TABLE (16 entries)
        
        vol_lut = POKEY_VOLTAGE_TABLE
        
        # Find nearest index in DUAL table for each target sample
        dual_table = POKEY_VOLTAGE_TABLE_DUAL
        
        # Scale input to match table if needed (it is 0..1 normalized?)
        # full_vectors is 0..1.
        # dual_table is 0..MaxVol (~0.82).
        # We need to scale full_vectors to Voltage Domain before search?
        # NO. VQ Training (VariableCodebookGenerator) normalizes POKEY levels to 0..1.
        #   self.pokey_levels = np.array(table) / max_val
        # So full_vectors (trained codebook entries) are Indices into that 0..1 space.
        # So we should compare full_vectors (0..1) against dual_table normalized (0..1).
        
        max_dual_vol = dual_table[-1]
        dual_table_norm = dual_table / max_dual_vol
        
        # Find indices in 31-level table
        # We iterate and find closest
        indices_31 = np.abs(full_vectors[:, None] - dual_table_norm).argmin(axis=1)
        
        # Convert to (v1, v2)
        v1_vals = indices_31 // 2
        v2_vals = indices_31 - v1_vals
        
        # Generate Waveform
        # We will create a Time-Value list or straight array?
        # Array at 1.77MHz is easiest for logic.
        
        # Output Buffer
        # Duration seconds
        duration = len(full_vectors) * (period_cycles / POKEY_CLOCK)
        num_high_res_samples = int(duration * POKEY_CLOCK)
        
        out_buffer = np.zeros(num_high_res_samples, dtype=np.float32)
        
        current_tick = 0
        
        last_v1 = 0
        last_v2 = 0
        
        # Pre-calc volumes
        vol1_levels = vol_lut[v1_vals]
        vol2_levels = vol_lut[v2_vals]
        
        # We can simulate loop in Python, might be slow. 
        # 500k samples * loop -> slow.
        # Vectorized approach:
        # Create a "Step" array.
        # Each sample is `cycles` long.
        # First `glitch_cycles` is (NewV1 + OldV2)
        # Rest is (NewV1 + NewV2)
        
        period_int = int(period_cycles)
        glitch_int = int(ASM_DELAY_CYCLES)
        
        # Create a repeatable pattern mask? No, values change.
        
        # Repeat elements:
        # We want: [GlitchVal] * 11 + [StableVal] * (Period - 11)
        
        # Shifted V2 (Old V2):
        old_v2_levels = np.roll(vol2_levels, 1)
        old_v2_levels[0] = 0 # Assume silence before start
        
        # Glitch Vol = vol1_levels + old_v2_levels
        # Stable Vol = vol1_levels + vol2_levels
        
        # Apply POKEY Non-Linear Saturation
        # Model: Input 1.0 -> Output 1.0 (Linear)
        #        Input > 1.0 -> Output 1.0 + (Input-1.0)*0.5 (Compressed)
        
        max_single_vol = POKEY_VOLTAGE_TABLE[-1] # This is the knee point
        
        glitch_sum = vol1_levels + old_v2_levels
        stable_sum = vol1_levels + vol2_levels
        
        # Saturation Function
        def saturate(v_sum, limit):
            # If v_sum <= limit: v_sum
            # Else: limit + (v_sum - limit) * 0.5
            return np.where(v_sum <= limit, v_sum, limit + (v_sum - limit) * 0.5)

        glitch_vols = saturate(glitch_sum, max_single_vol)
        stable_vols = saturate(stable_sum, max_single_vol)
        
        # Interleave
        # Stack: [[G0, S0], [G1, S1], ...]
        interleaved_vols = np.dstack((glitch_vols, stable_vols)).flatten()
        
        # Lengths
        # [11, P-11]
        lens = np.array([glitch_int, period_int - glitch_int], dtype=np.int32)
        # Tile lengths to match number of samples
        interleaved_lens = np.tile(lens, len(full_vectors))
        
        # Run Length Encode expansion
        high_res = np.repeat(interleaved_vols, interleaved_lens)
        
        # Resample to Target Rate (e.g. 48kHz)
        # Orig Rate = POKEY_CLOCK
        
        # If array is huge, we might process in chunks.
        # 10s audio * 1.77M = 17M samples. 17M * 4 bytes = 68MB. Safe.
        
        num_target_samples = int(len(high_res) * target_sr / POKEY_CLOCK)
        resampled = scipy.signal.resample(high_res, num_target_samples)
        
        # Normalize (0..MaxVol -> -1..1)
        # We need to determine the max possible value to normalize correctly.
        # It's max_dual_vol (from the table we used/generated).
        
        if max_dual_vol > 0:
             resampled = resampled / max_dual_vol
        
        # Center AC
        resampled = (resampled - 0.5) * 2.0
        
        return resampled



class VariableCodebookGenerator:
    def __init__(self, size, min_len, max_len, lambda_val, vq_alpha=0.0, constrained=False, lbg_init=False, channels=2, sample_boundaries=None):
        self.size = size
        self.min_len = min_len
        self.max_len = max_len
        self.lambda_val = lambda_val
        self.vq_alpha = vq_alpha
        self.constrained = constrained
        self.lbg_init = lbg_init
        self.channels = channels
        
        # Multi-sample boundaries: set of end positions where vectors must terminate
        self.boundary_ends = set()
        if sample_boundaries:
            for start, end in sample_boundaries:
                self.boundary_ends.add(end)
            # CRITICAL: When sample_boundaries exist, force min_len=1 to ensure
            # Viterbi can always reach boundary positions exactly.
            # Without this, boundaries not divisible by min_len become unreachable.
            if self.min_len > 1:
                print(f"    [Multi-Sample] Note: min_len={self.min_len} > 1. Ensure samples are padded/aligned (cli.py should handle this).")
                # self.min_len = 1  # Disabled to allowing testing constant vector lengths
        
        # Prepare POKEY table for 0..1 domain
        if self.constrained:
            if self.channels == 1:
                 # Single Channel: 16 non-linear levels
                 table = POKEY_VOLTAGE_TABLE
            elif 'POKEY_VOLTAGE_TABLE_FULL' in globals():
                 table = POKEY_VOLTAGE_TABLE_FULL
            else:
                 table = POKEY_VOLTAGE_TABLE_DUAL
                 
            # Find max
            max_val = 30 # standard dual max
            if len(table) > 0:
                max_val = max(table)
            
            self.pokey_levels = np.array(table) / max_val
            # Ensure unique and sorted for faster search
            self.pokey_levels = np.unique(self.pokey_levels)

        
    def train(self, audio, max_iterations=20, max_time=60):
        # 1. Initialization
        entries = []
        possible_lengths = list(range(self.min_len, self.max_len + 1))
        
        if self.lbg_init:
             entries = self._initialize_kmeans_pp(audio)
        else:
             # Initialize codebook with random segments from audio
             for i in range(self.size):
                 l = np.random.choice(possible_lengths)
                 start = np.random.randint(0, len(audio) - l)
                 segment = audio[start : start + l]
                 entries.append(segment)
            
        prev_distortion = float('inf')
        
        t_start = time.time()
        
        for iteration in range(max_iterations):
            if time.time() - t_start > max_time:
                break
                
            print(f"Iteration {iteration+1}/{max_iterations}...")
            
            # E-Step: Viterbi Segmentation
            indices, total_cost, segmentation_map = self._viterbi(audio, entries)
            
            distortion = total_cost 
            
            # Check convergence
            if prev_distortion != float('inf') and abs(prev_distortion - distortion) / (prev_distortion + 1e-9) < 0.001:
                break
            prev_distortion = distortion
            
            # M-Step: Update Centroids
            new_entries = self._update_centroids(audio, entries, segmentation_map)
            
            # Adaptation: Handle unused / splitting
            entries = self._adapt_codebook(new_entries, audio, segmentation_map)
            
            # NEW: Prune Empty/Unused Vectors (Optional or handled by adapt?)
            # The _adapt_codebook tries to respawn dead indices.
            
        print(f"\nFinal Cost: {prev_distortion:.4f}")
        return entries, indices
        
    def _viterbi(self, audio, entries):
        n_samples = len(audio)
        n_entries = len(entries)
        
        entries_by_len = {}
        for idx, entry in enumerate(entries):
            l = len(entry)
            if l not in entries_by_len: entries_by_len[l] = []
            entries_by_len[l].append( (idx, entry) )
            
        unique_lengths = sorted(entries_by_len.keys())
        
        dp_cost = np.full(n_samples + 1, float('inf'))
        dp_cost[0] = 0.0
        dp_backptr = np.zeros(n_samples + 1, dtype=np.int32)
        
        best_matches = {} 
        
        for l, items in entries_by_len.items():
            sub_cb_indices = [x[0] for x in items]
            sub_cb_vectors = np.array([x[1] for x in items])
            
            if n_samples < l: continue
            
            # Pre-calc distances for this length
            # Use sliding window view
            strided = np.lib.stride_tricks.sliding_window_view(audio, l)
            dists = cdist(strided, sub_cb_vectors, metric='sqeuclidean')
            
            # For each position, find best match codebook index
            min_dists = np.min(dists, axis=1)
            local_best_indices = np.argmin(dists, axis=1)
            global_best_indices = np.array([sub_cb_indices[i] for i in local_best_indices], dtype=np.int32)
            
            best_matches[l] = (min_dists, global_best_indices)
        
        for t in range(n_samples):
            current_c = dp_cost[t]
            if current_c == float('inf'): continue
            
            for l in unique_lengths:
                if t + l > n_samples: continue
                
                # BOUNDARY CONSTRAINT: Vector cannot cross a sample boundary
                # Check if we're crossing a boundary (but not ending exactly at one)
                end_pos = t + l
                crosses_boundary = False
                for boundary_end in self.boundary_ends:
                    # A vector crosses if it starts before boundary and ends after it
                    if t < boundary_end < end_pos:
                        crosses_boundary = True
                        break
                
                if crosses_boundary:
                    continue  # Skip this transition
                
                d, idx = best_matches[l][0][t], best_matches[l][1][t]
                step_cost = d + self.lambda_val 
                
                if self.vq_alpha > 0 and t > 0:
                    # Smoothness constraint
                    prev_idx = dp_backptr[t]
                    prev_vec = entries[prev_idx]
                    prev_val = prev_vec[-1]
                    curr_vec = entries[idx]
                    curr_val = curr_vec[0]
                    diff = prev_val - curr_val
                    step_cost += self.vq_alpha * (diff * diff)
                
                if current_c + step_cost < dp_cost[t+l]:
                    dp_cost[t+l] = current_c + step_cost
                    dp_backptr[t+l] = idx
        
        # Validate DP found a valid path
        if dp_cost[n_samples] == float('inf'):
            # This happens if min_len mismatch or boundaries unreachable
            raise RuntimeError(f"Viterbi failed: no valid path to end. Check min_len or boundary constraints.")
        
        # Backtrack
        indices = []
        curr = n_samples
        while curr > 0:
            idx = dp_backptr[curr]
            indices.append(idx)
            l = len(entries[idx])
            curr -= l
        indices.reverse()
        
        term_cost = dp_cost[n_samples]
        
        # Build Segmentation Map (for M-Step)
        segmentation_map = {} 
        curr = 0
        for idx in indices:
            if idx not in segmentation_map: segmentation_map[idx] = []
            l = len(entries[idx])
            segmentation_map[idx].append((curr, curr+l))
            curr += l
            
        return np.array(indices, dtype=np.int32), term_cost, segmentation_map

    def _update_centroids(self, audio, old_entries, segmentation_map):
        new_entries = list(old_entries)
        for idx, segments in segmentation_map.items():
            if not segments: continue
            total = np.zeros_like(old_entries[idx])
            count = 0
            for (start, end) in segments:
                total += audio[start:end]
                count += 1
            new_entries[idx] = total / count
            
        if self.constrained:
             new_entries = self._quantize_to_pokey(new_entries)
        return new_entries

    def _quantize_to_pokey(self, entries):
        quantized_entries = []
        levels = self.pokey_levels
        for vec in entries:
            # find nearest level for each sample
            # vec is shape (L,)
            # levels is shape (N,)
            v_reshaped = vec[:, np.newaxis]
            diffs = np.abs(v_reshaped - levels)
            nearest_indices = np.argmin(diffs, axis=1)
            quantized_vec = levels[nearest_indices]
            quantized_entries.append(quantized_vec)
        return quantized_entries

    def _initialize_kmeans_pp(self, audio):
        """
        K-Means++ initialization for variable length segments.
        """
        import random
        
        # 1. Harvest a candidate pool
        pool_size = self.size * 20 # Large pool
        pool = []
        possible_lengths = list(range(self.min_len, self.max_len + 1))
        
        for _ in range(pool_size):
            l = random.choice(possible_lengths)
            if len(audio) > l:
                start = random.randint(0, len(audio) - l)
                pool.append(audio[start:start+l])
        
        if not pool:
            return [np.zeros(self.min_len)] * self.size

        # 2. Pick first centroid
        entries = []
        first = random.choice(pool)
        entries.append(first)
        
        # 3. Pick remaining
        for _ in range(1, self.size):
            # Optimization: approximate K-Means++
            # Sample a chunk of candidates
            candidates = random.sample(pool, 100) 
            
            # Calculate distance of each candidate to the NEAREST existing centroid
            dists = []
            valid_candidates = []
            
            for cand in candidates:
                cand_len = len(cand)
                compatible_entries = [e for e in entries if len(e) == cand_len]
                
                if not compatible_entries:
                     min_dist = 1000.0 # Large constant
                else:
                     # Min dist to compatible
                     min_dist = float('inf')
                     for e in compatible_entries:
                         d = np.sum((cand - e)**2)
                         if d < min_dist:
                             min_dist = d
                
                dists.append(min_dist)
                valid_candidates.append(cand)
            
            # Probabilistic Selection (Weighted Random)
            total_dist = sum(dists)
            if total_dist == 0:
                 best_candidate = random.choice(candidates)
            else:
                 probs = np.array([d / total_dist for d in dists])
                 probs_sum = np.sum(probs)
                 if probs_sum > 0:
                     probs = probs / probs_sum
                 
                 chosen_idx = np.random.choice(len(valid_candidates), p=probs)
                 best_candidate = valid_candidates[chosen_idx]
            
            entries.append(best_candidate)
            
        return entries
            
    def _adapt_codebook(self, entries, audio, segmentation_map):
        used_indices = set(segmentation_map.keys())
        all_indices = set(range(len(entries)))
        dead_indices = list(all_indices - used_indices)
        
        if not dead_indices:
            return entries
            
        errors = []
        for idx in used_indices:
            segs = segmentation_map[idx]
            vec = entries[idx]
            gathered = []
            for s, e in segs:
                gathered.append(audio[s:e])
            if gathered:
                mat = np.array(gathered)
                dist = np.sum((mat - vec)**2)
                errors.append( (dist, idx) )
                
        errors.sort(key=lambda x: x[0], reverse=True)
        
        n_respawn = min(len(dead_indices), len(errors))
        
        for i in range(n_respawn):
            dead_idx = dead_indices[i]
            worst_err, worst_idx = errors[i]
            victim_vec = entries[worst_idx]
            noise = np.random.normal(0, 0.01, size=len(victim_vec))
            entries[dead_idx] = victim_vec + noise
            entries[worst_idx] = victim_vec - noise
            
        return entries
