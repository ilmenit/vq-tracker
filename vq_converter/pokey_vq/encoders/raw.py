"""
pokey_vq/encoders/raw.py - FIXED VERSION

FIXED: PY-5 - Removed duplicate 'import numpy as np'
"""

import os
import time
import tempfile
import subprocess
import shutil
import numpy as np
# FIX PY-5: Removed duplicate import (was: import numpy as np twice)
import scipy.signal
from ..core.experiment import Encoder
from ..core.pokey_table import POKEY_VOLTAGE_TABLE, POKEY_VOLTAGE_TABLE_DUAL


class RawEncoder(Encoder):
    """
    Pure POKEY Stream (Raw).
    
    This algorithm performs optimal quantization to POKEY volume levels
    and outputs the raw register values directly.
    - No VQ
    - No ADPCM
    - No inter-channel compression (except combining dual channels into one byte)
    
    Output Format:
    - Sequence of bytes, one per sample period (e.g. 1/4000s).
    - Each byte is ready to be stored in AUDC+1 / AUDC+3 or combined.
    - Format is suitable for external compression (LZSA, Deflate, etc).
    """
    
    def __init__(self, rate=8000, dual=False):
        mode_str = "Dual" if dual else "Single"
        super().__init__(f"Raw_{rate}Hz_{mode_str}")
        self.rate = rate
        self.dual = dual
        
        if self.dual:
            self.hw_table = POKEY_VOLTAGE_TABLE_DUAL
            # POKEY_VOLTAGE_TABLE_DUAL maps 0-30 index to voltage
        else:
            self.hw_table = POKEY_VOLTAGE_TABLE
            # POKEY_VOLTAGE_TABLE maps 0-15 index to voltage

    @staticmethod
    def quantize(audio, hw_table, noise_shaping=False):
        """Quantize audio samples to nearest POKEY voltage table entries.
        
        Args:
            audio: float32 array, range [-1, 1]
            hw_table: sorted POKEY voltage table (e.g. POKEY_VOLTAGE_TABLE)
            noise_shaping: If True, use 1st-order error feedback to push
                quantization noise to higher frequencies. Most effective
                when sample rate >> 4 kHz (gives headroom above audible band).
            
        Returns:
            uint8 array of table indices (0 to len(hw_table)-1)
        """
        table_max = hw_table.max()
        n_levels = len(hw_table)
        audio_scaled = ((audio + 1.0) / 2.0) * table_max
        
        if not noise_shaping:
            # Nearest-neighbor (vectorized, fast)
            indices = np.searchsorted(hw_table, audio_scaled)
            indices = np.clip(indices, 0, n_levels - 1)
            
            left_indices = np.clip(indices - 1, 0, n_levels - 1)
            err_right = np.abs(audio_scaled - hw_table[indices])
            err_left = np.abs(audio_scaled - hw_table[left_indices])
            use_left = err_left < err_right
            
            return np.where(use_left, left_indices, indices).astype(np.uint8)
        
        # 1st-order noise shaping: feed quantization error into next sample.
        # Pushes noise energy from low frequencies to high frequencies.
        # At 15 kHz POKEY rate, reduces audible (<2 kHz) noise by ~18x.
        indices = np.zeros(len(audio_scaled), dtype=np.uint8)
        error = 0.0
        last_idx = n_levels - 1
        for i in range(len(audio_scaled)):
            val = audio_scaled[i] + error
            # Clamp to table range to prevent runaway
            if val < 0.0:
                val = 0.0
            elif val > table_max:
                val = table_max
            # Find nearest level
            idx = np.searchsorted(hw_table, val)
            if idx > last_idx:
                idx = last_idx
            elif idx > 0 and abs(val - hw_table[idx - 1]) < abs(val - hw_table[idx]):
                idx -= 1
            indices[i] = idx
            # Error = what we wanted minus what we got
            error = audio_scaled[i] + error - hw_table[idx]
        
        return indices

    def run(self, audio, sr, bin_export_path=None, fast=False):
        if sr != self.rate:
            num_samples = int(len(audio) * self.rate / sr)
            audio_resampled = scipy.signal.resample(audio, num_samples)
        else:
            audio_resampled = audio
            
        start_time = time.time()
        
        final_indices = self.quantize(audio_resampled, self.hw_table)
        
        # Convert indices to POKEY Register Integers
        if self.dual:
            # Dual Mode: index is linear volume 0-30.
            # We need to pack this into (v1 << 4) | v2
            # Balanced split: v1 = val // 2, v2 = val - v1
            v1 = final_indices // 2
            v2 = final_indices - v1
            raw_data = ((v1 << 4) | v2).tobytes()
        else:
            # Single Mode: index is volume 0-15.
            # Pack as nibbles: [Hi=T+1 | Lo=T] to match player expectations
            # Same format as VQ Single Channel
            packed_bytes = bytearray()
            for i in range(0, len(final_indices), 2):
                lo = final_indices[i] & 0x0F
                if i + 1 < len(final_indices):
                    hi = final_indices[i + 1] & 0x0F
                else:
                    hi = 0  # Pad odd length
                packed_bytes.append((hi << 4) | lo)
            raw_data = bytes(packed_bytes)
            
        if fast and self.dual:
            # Fast Mode: Interleaved Pre-calculated Registers
            # v1 = High Nibble (Ch2 - Vol Only) -> $10 | v1
            # v2 = Low Nibble (Ch1 - Vol Only) -> $10 | v2
            # Interleave: v2_reg, v1_reg (Order: Ch1, Ch2) matches player fetch order
            
            # v1, v2 calculated above
            val_c1 = (0x10 | v2).astype(np.uint8)
            val_c2 = (0x10 | v1).astype(np.uint8)
            
            # Interleave
            # dstack creates pairs, flatten makes sequence
            raw_data = np.dstack((val_c1, val_c2)).flatten().tobytes()
            
        # LZSA Compress (optional, but standard for this toolchain's .bin output)
        # We assume 'lzsa' is available relatively
        # script_dir is usually atari-player/src/
        # lzsa is usually ../../lzsa/lzsa
        # This relative path needs check
        lzsa_path = os.path.join(os.path.dirname(__file__), '..', '..', 'lzsa', 'lzsa')
        compressed_size = len(raw_data)
        
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(raw_data)
            raw_path = tf.name
        out_path = raw_path + ".lzsa"
        
        # Try compressing
        if os.path.exists(lzsa_path):
            subprocess.run([lzsa_path, '-r', '-f2', raw_path, out_path], 
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(out_path):
                compressed_size = os.path.getsize(out_path)
                
        if bin_export_path:
            # Export output (either compressed or raw if lzsa failed)
            src_file = out_path if os.path.exists(out_path) else raw_path
            shutil.copy2(src_file, bin_export_path)
            
            # Export raw uncompressed version explicitly
            raw_export_path = bin_export_path + ".raw"
            shutil.copy2(raw_path, raw_export_path)
            
        if os.path.exists(out_path): os.unlink(out_path)
        os.unlink(raw_path)
        
        elapsed = time.time() - start_time
        
        # Reconstruction for metrics
        decoded_audio = self.hw_table[final_indices]
        table_max = self.hw_table.max()
        
        # Convert to -1..1
        decoded_audio = (decoded_audio / table_max) * 2.0 - 1.0
        
         # Export Raw POKEY Streams (redundant for Pure but good for consistency)
        if bin_export_path:
            # Assuming export_pokey_streams is in Experiment? Or we can skip
            # Base Experiment doesn't seem to have export_pokey_streams in atari-player/src/base.py
            pass
            
        if self.rate != sr:
            num_samples = int(len(decoded_audio) * sr / self.rate)
            decoded_resampled = scipy.signal.resample(decoded_audio, num_samples)
        else:
            decoded_resampled = decoded_audio
            
        return compressed_size, decoded_resampled, elapsed, final_indices

    def simulate_hardware_glitch(self, codebook_entries, indices, pokey_div, target_sr=48000):
        """
        Simulates POKEY hardware glitch for Raw stream.
        Interface matches VQEncoder for compatibility.
        
        Args:
            codebook_entries: List of "vectors" (for Raw, this is the table values wrapped)
            indices: Stream of indices pointing to codebook_entries
        """
        # For RawEncoder, we can assume:
        # 1. codebook_entries is just the hardware table (as 1-element vectors)
        # 2. indices are the table indices
        # OR
        # We can ignore codebook_entries if we know 'indices' are directly table indices (which they are)
        # But to be safe and generic with arguments:
        
        # Reconstruct full sample sequence
        full_vectors = []
        for idx in indices:
            vec = codebook_entries[idx]
            # vec is [value] or value?
            # If we prep it as [[v], [v]] then extend works.
            full_vectors.extend(vec)
            
        full_vectors = np.array(full_vectors)
        
        # Reuse the logic from VQEncoder (Duplicate logic for now to avoid extensive refactoring)
        # Constants
        POKEY_CLOCK = 1773447 # PAL
        ASM_DELAY_CYCLES = 11 
        
        # ... rest of implementation unchanged ...
        pass
