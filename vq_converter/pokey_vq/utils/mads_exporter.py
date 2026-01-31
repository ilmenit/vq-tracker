import numpy as np
import os
import time

class MADSExporter:
    """
    Exports VQVariable Codebook and Indices to Atari MADS Assembler format.
    Generates 'data.asm' with labels used by the player.
    
    Supported output formats:
    - Single Channel (channels=1): Nibble-packed, 8 bytes per 16-sample vector
    - Dual Channel Size (channels=2, fast=False): Nibble-packed, 16 bytes per 16 samples
    - Dual Channel Speed (channels=2, fast=True): Interleaved pre-masked, 32 bytes per 16 samples
    """
    
    def export(self, filepath, codebook_entries, indices, pokey_table_dual, pokey_map_full=None, fast=False, channels=2):
        """
        Save VQVariable data as multiple MADS .asm files.
        
        Args:
            filepath: Base path for output files
            codebook_entries: List of codebook vectors
            indices: Array of codebook indices
            pokey_table_dual: POKEY voltage quantization table
            pokey_map_full: Optional full POKEY map for constrained quantization
            fast: If True and channels=2, use interleaved format (32 bytes/vector)
            channels: 1 for single channel, 2 for dual channel
        """
        print(f"DEBUG: MADSExporter.export called with fast={fast}, channels={channels}")
        
        # Quantization Table normalization
        table = pokey_table_dual
        if len(table) > 0 and table[-1] > 0: 
            table = table / table[-1]
        
        lengths = []
        blob_offsets = [] 
        blob_bytes = bytearray()
        
        current_offset = 0
        
        # 1. Build Blob and Tables
        for vec in codebook_entries:
            lengths.append(len(vec))
            blob_offsets.append(current_offset)
            
            # Single Channel Packing Buffer
            nibble_buffer = None
            
            # Quantize each sample in vector
            for val in vec:
                # 1. Determine Channel Values
                idx = np.searchsorted(table, val)
                if idx == len(table): idx = len(table) - 1
                elif idx > 0 and np.abs(val - table[idx-1]) < np.abs(val - table[idx]): idx -= 1

                if channels == 1:
                    # --- Single Channel ---
                    if fast:
                        # Optimization: 1 byte per sample (unpacked)
                        # Pre-bake AUDC mask ($10) into the byte to save ORA instruction
                        # Format: $1V where V is 4-bit volume
                        byte_val = (idx & 0x0F) | 0x10  # Hardcoded AUDC mask for now (usually $10)
                        blob_bytes.append(byte_val)
                    else:
                        # --- Single Channel Packing (Size Optimized) ---
                        # idx is the value (0-15) directly (assuming linear table passed)
                        nibble = idx & 0x0F
                        
                        if nibble_buffer is None:
                            # Store Low Nibble (Frame T) - even samples
                            nibble_buffer = nibble
                        else:
                            # Pack High Nibble (Frame T+1) - odd samples
                            # Byte format: [Hi=T+1 | Lo=T]
                            packed = (nibble << 4) | nibble_buffer
                            blob_bytes.append(packed)
                            nibble_buffer = None
                        
                else:
                    # --- Dual Channel ---
                    if pokey_map_full is not None:
                        # Full map case (Standard)
                        byte_val = pokey_map_full[idx]
                        # Standard Full Map: byte = (Ch2 << 4) | Ch1
                        v_ch2 = (byte_val >> 4) & 0x0F
                        v_ch1 = byte_val & 0x0F
                        mask_ch1 = 0x10
                        mask_ch2 = 0x10
                    else:
                        # Standard Balanced (Fallback)
                        v1 = idx // 2
                        v2 = idx - v1
                        # Mapping: Ch1=v2, Ch2=v1 (Low->Ch1, High->Ch2)
                        v_ch1 = v2
                        v_ch2 = v1
                        mask_ch1 = 0x10
                        mask_ch2 = 0x10
    
                    # 2. Store (Fast/Interleaved vs Packed)
                    if fast:
                        # Interleaved: 2 bytes per sample (pre-masked for AUDC)
                        # This format is ready to write directly to AUDC1/AUDC2
                        blob_bytes.append(mask_ch1 | v_ch1)  # AUDC1 value
                        blob_bytes.append(mask_ch2 | v_ch2)  # AUDC2 value
                    else:
                        # Packed: 1 byte per sample
                        # Player extracts: AND #$0F = Ch1 (low nibble), LSR×4 = Ch2 (high nibble)
                        packed = (v_ch2 << 4) | v_ch1
                        blob_bytes.append(packed)
            
            # Handle Odd Lengths (Single Channel)
            if channels == 1 and nibble_buffer is not None:
                # Pad with 0 for last nibble
                packed = (0 << 4) | nibble_buffer
                blob_bytes.append(packed)

            # Update Offsets based on ACTUAL bytes written
            current_offset = len(blob_bytes)
            
        # Pad tables to 256 entries IF size < 256
        target_size = len(lengths)
        if target_size < 256:
            target_size = 256
            while len(lengths) < 256:
                lengths.append(0)
                blob_offsets.append(0)
            
        # 2. Prepare Output Directory
        output_dir = os.path.dirname(filepath)
        if not output_dir: output_dir = "."
        
        # Helper for byte arrays
        def to_mads_array(label, data):
            out = []
            out.append(f"{label}")
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                bytes_str = ",".join(f"${b:02X}" for b in chunk)
                out.append(f" .byte {bytes_str}")
            return "\n".join(out)
            
        def write_asm(filename, content):
            full_path = os.path.join(output_dir, filename)
            with open(full_path, 'w') as f:
                f.write(content)
            # print(f"Saved MADS ASM: {full_path}")

        # 3. Generate Split Files
        
        # VQ_LENS.asm
        lines = [f"VQ_LENS_LEN = {len(lengths)}"]
        lines.append(to_mads_array("VQ_LENS", lengths))
        write_asm("VQ_LENS.asm", "\n".join(lines))
        
        # VQ_LO.asm
        lines = [f"VQ_LO_LEN = {len(blob_offsets)}"]
        lines.append("VQ_LO")
        for i_chunk in range(0, len(blob_offsets), 8): 
            chunk_offsets = blob_offsets[i_chunk:i_chunk+8]
            bytes_str = ",".join(f"<(VQ_BLOB+${off:04X})" for off in chunk_offsets)
            lines.append(f" .byte {bytes_str}")
        write_asm("VQ_LO.asm", "\n".join(lines))

        # VQ_HI.asm
        lines = [f"VQ_HI_LEN = {len(blob_offsets)}"]
        lines.append("VQ_HI")
        for i_chunk in range(0, len(blob_offsets), 8): 
            chunk_offsets = blob_offsets[i_chunk:i_chunk+8]
            bytes_str = ",".join(f">(VQ_BLOB+${off:04X})" for off in chunk_offsets)
            lines.append(f" .byte {bytes_str}")
        write_asm("VQ_HI.asm", "\n".join(lines))
        
        # VQ_BLOB.asm
        lines = [f"VQ_BLOB_LEN = {len(blob_bytes)}"]
        lines.append(to_mads_array("VQ_BLOB", blob_bytes))
        write_asm("VQ_BLOB.asm", "\n".join(lines))
        
        # VQ_INDICES.asm
        lines = [f"VQ_INDICES_LEN = {len(indices)}"]
        lines.append(to_mads_array("VQ_INDICES", indices.astype(np.uint8)))
        write_asm("VQ_INDICES.asm", "\n".join(lines))
        
        # FIX: Generate LUT for single-channel player optimization
        # Only needed if NOT using fast byte stream (which doesn't need LUT)
        # Wait, strictly speaking, existing players might expect LUT if USE_FAST_CPU is handled via LUT.
        # But we correspond USE_FAST_CPU to byte stream now.
        # However, for safety/completeness or mixed modes, we can leave it or disable it.
        # Since we are redefining 'fast' to mean 'bytes', the LUT is useless and wastes space.
        if channels == 1 and not fast:
            self.generate_lut_nibbles(filepath)
        
        # Print summary
        print(f"Exported to {output_dir}:")
        print(f"  - VQ_BLOB: {len(blob_bytes)} bytes")
        print(f"  - VQ_INDICES: {len(indices)} entries")
        print(f"  - Codebook: {len(codebook_entries)} vectors")
        if channels == 1:
            if fast:
                print(f"  - Format: Single channel unpacked (Pre-masked $10, 16 bytes/16 samples)")
            else:
                print(f"  - Format: Single channel, nibble-packed (8 bytes/16 samples)")
                print(f"  - LUT_NIBBLES.asm generated for USE_FAST_CPU optimization")
        elif fast:
            print(f"  - Format: Dual channel interleaved (32 bytes/16 samples)")
        else:
            print(f"  - Format: Dual channel packed (16 bytes/16 samples)")

    def export_sample_directory(self, filepath, sample_boundaries, indices, codebook_entries, sample_names=None):
        """
        Export SAMPLE_DIR.asm with sample start/end offset tables.
        
        Args:
            filepath: Base path for output
            sample_boundaries: List of (audio_start, audio_end) tuples in audio sample units
            indices: The VQ index stream
            codebook_entries: The codebook vectors (to calculate lengths)
            sample_names: Optional list of filenames for comments
        """
        if not sample_boundaries:
            return  # No boundaries to export
        
        output_dir = os.path.dirname(filepath)
        if not output_dir: output_dir = "."
        
        # Calculate stream offsets for each sample
        # We need to map audio sample positions to VQ_INDICES stream positions
        stream_offsets = []
        
        # Calculate cumulative audio position -> stream index mapping
        audio_pos = 0
        stream_pos = 0
        
        # Build a mapping: for each sample boundary, find the stream position
        # where that sample starts in VQ_INDICES
        boundary_stream_start = []
        boundary_stream_end = []
        
        # Track current audio position while walking through indices
        current_audio_pos = 0
        current_stream_pos = 0
        boundary_idx = 0
        
        # First sample always starts at stream position 0
        boundary_stream_start.append(0)
        
        for i, cb_idx in enumerate(indices):
            vec_len = len(codebook_entries[cb_idx])
            next_audio_pos = current_audio_pos + vec_len
            
            # Check if this vector ends at or crosses a sample boundary
            while boundary_idx < len(sample_boundaries):
                _, boundary_end = sample_boundaries[boundary_idx]
                
                if next_audio_pos >= boundary_end:
                    # This vector ends the current sample
                    boundary_stream_end.append(i + 1)  # End is exclusive (next position)
                    
                    # Start of next sample (if exists)
                    if boundary_idx + 1 < len(sample_boundaries):
                        boundary_stream_start.append(i + 1)
                    
                    boundary_idx += 1
                else:
                    break
            
            current_audio_pos = next_audio_pos
        
        # Handle last sample's end
        if len(boundary_stream_end) < len(sample_boundaries):
            boundary_stream_end.append(len(indices))
        
        # Generate SAMPLE_DIR.asm
        lines = []
        lines.append("; Multi-Sample Directory")
        lines.append("; Generated by PokeyVQ")
        lines.append("")
        lines.append(f"SAMPLE_COUNT = {len(sample_boundaries)}")
        lines.append("; MULTI_SAMPLE is defined in VQ_CFG.asm")
        lines.append("")
        
        # Helper to get comment
        def get_cmt(idx):
             if sample_names and idx < len(sample_names):
                 return f" ; {sample_names[idx]}"
             return ""

        # Start offsets (low bytes)
        lines.append("SAMPLE_START_LO")
        for i, offset in enumerate(boundary_stream_start):
            lines.append(f" .byte <(VQ_INDICES+${offset:04X}){get_cmt(i)}")
        lines.append("")
        
        # Start offsets (high bytes)
        lines.append("SAMPLE_START_HI")
        for i, offset in enumerate(boundary_stream_start):
            lines.append(f" .byte >(VQ_INDICES+${offset:04X}){get_cmt(i)}")
        lines.append("")
        
        # End offsets (low bytes)
        lines.append("SAMPLE_END_LO")
        for i, offset in enumerate(boundary_stream_end):
            lines.append(f" .byte <(VQ_INDICES+${offset:04X}){get_cmt(i)}")
        lines.append("")
        
        # End offsets (high bytes)
        lines.append("SAMPLE_END_HI")
        for i, offset in enumerate(boundary_stream_end):
            lines.append(f" .byte >(VQ_INDICES+${offset:04X}){get_cmt(i)}")
        
        full_path = os.path.join(output_dir, "SAMPLE_DIR.asm")
        with open(full_path, 'w') as f:
            f.write("\n".join(lines))

    def generate_lut_nibbles(self, filepath):
        """
        Generates LUT_NIBBLES.asm for Single Channel Speed Mode.
        
        These lookup tables allow the player to extract nibbles without
        using shift instructions, saving ~8 cycles per sample.
        
        LUT_HI[byte] = (byte >> 4) | AUDC1_MASK  (for odd samples)
        LUT_LO[byte] = (byte & 0x0F) | AUDC1_MASK  (for even samples)
        
        Note: Uses MADS expressions so AUDC1_MASK is resolved at assembly time.
        """
        output_dir = os.path.dirname(filepath)
        if not output_dir: output_dir = "."
        
        lines = []
        lines.append("; LUT for Single Channel Nibble Extraction")
        lines.append("; Optimization: Pre-calculated shifts + Mask")
        lines.append("; Used when USE_FAST_CPU is defined")
        lines.append("")
        
        # LUT_HI: (i >> 4) | AUDC1_MASK - for HIGH nibble (odd samples: 1,3,5...)
        lines.append("; High nibble extraction table (for odd sample positions)")
        lines.append("LUT_HI")
        for i in range(256):
            val = i >> 4
            lines.append(f" .byte ${val:02X} | AUDC1_MASK")
        lines.append("")
            
        # LUT_LO: (i & 0x0F) | AUDC1_MASK - for LOW nibble (even samples: 0,2,4...)
        lines.append("; Low nibble extraction table (for even sample positions)")
        lines.append("LUT_LO")
        for i in range(256):
            val = i & 0x0F
            lines.append(f" .byte ${val:02X} | AUDC1_MASK")
            
        out_path = os.path.join(output_dir, "LUT_NIBBLES.asm")
        with open(out_path, 'w') as f:
            f.write("\n".join(lines))
        
        print(f"  - Generated: {out_path}")
