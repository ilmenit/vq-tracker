"""Atari Sample Tracker - File I/O"""
import json
import gzip
import os
import struct
import wave
import logging
from typing import Optional, Tuple, List
import numpy as np

logger = logging.getLogger("tracker.file_io")

try:
    from scipy.io import wavfile as scipy_wav
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

from constants import PROJECT_EXT, BINARY_EXT, note_to_str, MAX_NOTES
from data_model import Song, Instrument

# =============================================================================
# PROJECT FILES (JSON)
# =============================================================================

def save_project(song: Song, path: str) -> Tuple[bool, str]:
    """Save project to .pvq JSON file."""
    try:
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT
        
        data = song.to_dict()
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        song.file_path = path
        song.modified = False
        return True, f"Saved: {os.path.basename(path)}"
    except PermissionError:
        return False, f"Permission denied: {path}"
    except Exception as e:
        return False, f"Save failed: {e}"


def load_project(path: str) -> Tuple[Optional[Song], str]:
    """Load project from .pvq file."""
    try:
        if not os.path.exists(path):
            return None, f"File not found: {path}"
        
        # Try gzipped first, then plain JSON
        try:
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
        except gzip.BadGzipFile:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        song = Song.from_dict(data)
        song.file_path = path
        song.modified = False
        
        # Reload samples
        base_dir = os.path.dirname(os.path.abspath(path))
        loaded, missing = 0, 0
        for inst in song.instruments:
            if inst.sample_path:
                if _try_load_sample(inst, base_dir):
                    loaded += 1
                else:
                    missing += 1
        
        msg = f"Loaded: {os.path.basename(path)}"
        if loaded:
            msg += f" ({loaded} samples)"
        if missing:
            msg += f" ({missing} missing)"
        return song, msg
        
    except json.JSONDecodeError as e:
        return None, f"Invalid format: {e}"
    except Exception as e:
        return None, f"Load failed: {e}"


def _try_load_sample(inst: Instrument, base_dir: str) -> bool:
    """Try loading sample from various paths."""
    paths_to_try = [
        inst.sample_path if os.path.isabs(inst.sample_path) else None,
        os.path.join(base_dir, inst.sample_path),
        os.path.join(base_dir, os.path.basename(inst.sample_path)),
        os.path.join(base_dir, 'samples', os.path.basename(inst.sample_path)),
    ]
    for p in paths_to_try:
        if p and os.path.exists(p):
            ok, _ = load_sample(inst, p)
            if ok:
                return True
    return False

# =============================================================================
# BINARY EXPORT (.pvg)
# =============================================================================

def export_binary(song: Song, path: str) -> Tuple[bool, str]:
    """Export to binary .pvg format for Atari player."""
    try:
        if not path.lower().endswith(BINARY_EXT):
            path += BINARY_EXT
        
        with open(path, 'wb') as f:
            # Header
            f.write(b'PVG')
            f.write(struct.pack('B', 3))  # Version
            
            # Metadata
            f.write(struct.pack('<B', song.speed))
            f.write(struct.pack('<B', song.system))
            f.write(struct.pack('<H', len(song.songlines)))
            f.write(struct.pack('<H', len(song.patterns)))
            f.write(struct.pack('<B', len(song.instruments)))
            
            # Songlines
            for sl in song.songlines:
                for p in sl.patterns:
                    f.write(struct.pack('B', p))
            
            # Patterns
            for ptn in song.patterns:
                f.write(struct.pack('<H', ptn.length))
                for row in ptn.rows:
                    f.write(struct.pack('BBB', row.note, row.instrument, row.volume))
        
        return True, f"Exported: {os.path.basename(path)}"
    except Exception as e:
        return False, f"Export failed: {e}"

# =============================================================================
# ASM EXPORT
# =============================================================================

def export_asm(song: Song, out_dir: str) -> Tuple[bool, str]:
    """Export to ASM include files for 6502 player.
    
    Uses variable-length event encoding with high-bit flags.
    See EXPORT_FORMAT.md for complete format specification.
    """
    try:
        os.makedirs(out_dir, exist_ok=True)
        
        # Generate SONG_DATA.asm (single file with all song data)
        with open(os.path.join(out_dir, "SONG_DATA.asm"), 'w') as f:
            f.write("; ==========================================================================\n")
            f.write("; SONG DATA - Generated by Atari Sample Tracker\n")
            f.write("; ==========================================================================\n")
            f.write(f"; Song: {song.title}\n")
            f.write(f"; Author: {song.author}\n")
            f.write("; Format: Variable-length events (bit 7 flags for inst/vol)\n")
            f.write("; ==========================================================================\n\n")
            
            # --- SONG HEADER ---
            num_songlines = len(song.songlines)
            f.write("; --- SONG STRUCTURE ---\n")
            f.write(f"SONG_LENGTH:\n    .byte ${num_songlines:02X}\n\n")
            
            # Speed array (per songline)
            f.write("; Speed for each songline (VBLANKs per row)\n")
            f.write("SONG_SPEED:\n    .byte ")
            speeds = [f"${sl.speed:02X}" for sl in song.songlines]
            f.write(",".join(speeds))
            f.write("\n\n")
            
            # Pattern assignments per channel
            for ch in range(3):
                f.write(f"; Pattern indices for channel {ch}\n")
                f.write(f"SONG_PTN_CH{ch}:\n    .byte ")
                ptns = [f"${sl.patterns[ch]:02X}" for sl in song.songlines]
                f.write(",".join(ptns))
                f.write("\n\n")
            
            # --- PATTERN DIRECTORY ---
            num_patterns = len(song.patterns)
            f.write("; --- PATTERN DIRECTORY ---\n")
            f.write(f"PATTERN_COUNT:\n    .byte ${num_patterns:02X}\n\n")
            
            # Pattern lengths
            f.write("; Pattern lengths (rows)\n")
            f.write("PATTERN_LEN:\n    .byte ")
            lens = [f"${p.length:02X}" for p in song.patterns]
            f.write(",".join(lens))
            f.write("\n\n")
            
            # Pattern pointers (low)
            f.write("; Pattern data pointers (low byte)\n")
            f.write("PATTERN_PTR_LO:\n    .byte ")
            ptrs = [f"<PTN_{i:02X}" for i in range(num_patterns)]
            f.write(",".join(ptrs))
            f.write("\n\n")
            
            # Pattern pointers (high)
            f.write("; Pattern data pointers (high byte)\n")
            f.write("PATTERN_PTR_HI:\n    .byte ")
            ptrs = [f">PTN_{i:02X}" for i in range(num_patterns)]
            f.write(",".join(ptrs))
            f.write("\n\n")
            
            # --- PATTERN EVENT DATA (Variable-Length) ---
            f.write("; --- PATTERN EVENT DATA (Variable-Length) ---\n")
            f.write("; Format: row, note[|$80], [inst[|$80]], [vol]\n")
            f.write("; Note bit 7: inst follows. Inst bit 7: vol follows.\n")
            f.write("; End marker: $FF\n\n")
            
            total_events = 0
            total_bytes = 0
            
            for i, ptn in enumerate(song.patterns):
                f.write(f"; Pattern {i:02X} ({ptn.length} rows)\n")
                f.write(f"PTN_{i:02X}:\n")
                
                events = 0
                ptn_bytes = 0
                last_inst = None
                last_vol = None
                
                for row_idx, row in enumerate(ptn.rows):
                    # Skip empty rows and validate note range
                    if row.note < 1 or row.note > MAX_NOTES:
                        continue
                    
                    note_str = note_to_str(row.note)
                    
                    # Determine what needs to be encoded
                    need_inst = (last_inst is None or row.instrument != last_inst)
                    need_vol = (last_vol is None or row.volume != last_vol)
                    
                    # CRITICAL: If volume changed, we MUST include instrument byte
                    # (because vol byte can only follow inst byte in our format)
                    if need_vol:
                        need_inst = True
                    
                    # Build the event bytes
                    event_bytes = []
                    event_bytes.append(f"${row_idx:02X}")  # row
                    
                    note_byte = row.note & 0x3F
                    if need_inst:
                        note_byte |= 0x80
                    event_bytes.append(f"${note_byte:02X}")
                    
                    if need_inst:
                        inst_byte = row.instrument & 0x7F
                        if need_vol:
                            inst_byte |= 0x80
                        event_bytes.append(f"${inst_byte:02X}")
                        last_inst = row.instrument
                    
                    if need_vol:
                        vol_masked = row.volume & 0x0F  # Ensure 4-bit value
                        event_bytes.append(f"${vol_masked:02X}")
                        last_vol = row.volume
                    
                    comment = f"; Row {row_idx:02X}: {note_str}"
                    if need_inst:
                        comment += f" I:{row.instrument:02X}"
                    if need_vol:
                        comment += f" V:{vol_masked:02X}"
                    
                    f.write(f"    .byte {','.join(event_bytes)}  {comment}\n")
                    events += 1
                    ptn_bytes += len(event_bytes)
                
                f.write(f"    .byte $FF  ; End ({events} events, {ptn_bytes + 1} bytes)\n\n")
                total_events += events
                total_bytes += ptn_bytes + 1
            
            f.write(f"; Total: {total_events} events, {total_bytes} bytes pattern data\n")
        
        # Also generate a summary/readme
        with open(os.path.join(out_dir, "README.txt"), 'w') as f:
            f.write(f"Song: {song.title}\n")
            f.write(f"Author: {song.author}\n")
            f.write(f"System: {'PAL' if song.system == 50 else 'NTSC'}\n")
            f.write(f"\n")
            f.write(f"Songlines: {len(song.songlines)}\n")
            f.write(f"Patterns: {len(song.patterns)}\n")
            f.write(f"Instruments: {len(song.instruments)}\n")
            f.write(f"\n")
            f.write(f"To use:\n")
            f.write(f"1. Copy SONG_DATA.asm to your project\n")
            f.write(f"2. Include in song_player.asm (or your player)\n")
            f.write(f"3. Ensure VQ sample data matches instrument order\n")
        
        return True, f"Exported to {os.path.basename(out_dir)}/"
    except Exception as e:
        return False, f"Export failed: {e}"

# =============================================================================
# SAMPLE LOADING
# =============================================================================

def load_sample(inst: Instrument, path: str, is_converted: bool = False) -> Tuple[bool, str]:
    """Load WAV sample into instrument.
    
    Args:
        inst: Instrument to load into
        path: Path to WAV file
        is_converted: If True, this is a converted sample (don't update original_sample_path)
    """
    logger.debug(f"load_sample: path={path}, is_converted={is_converted}")
    try:
        if not os.path.exists(path):
            logger.warning(f"File not found: {path}")
            return False, f"File not found: {path}"
        
        if not path.lower().endswith('.wav'):
            return False, "Unsupported format (WAV only)"
        
        rate, data = _read_wav(path)
        if data is None:
            logger.error(f"Failed to read WAV file: {path}")
            return False, "Failed to read WAV file"
        
        # Convert to mono float32
        if len(data.shape) > 1:
            data = np.mean(data, axis=1)
        
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            data = (data.astype(np.float32) - 128) / 128.0
        elif data.dtype != np.float32:
            data = data.astype(np.float32)
        
        # Normalize
        max_val = np.max(np.abs(data))
        if max_val > 1.0:
            data = data / max_val
        
        inst.sample_data = data
        inst.sample_rate = rate
        inst.sample_path = path
        
        # Set original path only when loading original files (not converted)
        if not is_converted:
            inst.original_sample_path = path
        
        # Auto-name from filename
        if inst.name in ("New", "New Instrument", ""):
            inst.name = os.path.splitext(os.path.basename(path))[0][:16]
        
        duration = len(data) / rate
        logger.info(f"Loaded sample: {inst.name}, {len(data)} samples, {rate}Hz, {duration:.2f}s")
        return True, f"Loaded: {len(data):,} samples, {rate}Hz, {duration:.2f}s"
    except Exception as e:
        logger.error(f"Load failed: {e}")
        return False, f"Load failed: {e}"


def load_samples_multi(paths: List[str]) -> List[Tuple[Instrument, bool, str]]:
    """Load multiple WAV files. Returns list of (instrument, success, message)."""
    results = []
    for path in paths:
        inst = Instrument()
        ok, msg = load_sample(inst, path)
        results.append((inst, ok, msg))
    return results


def load_samples_folder(folder: str, recursive: bool = True) -> List[Tuple[Instrument, bool, str]]:
    """Load all WAV files from folder and optionally subfolders.
    
    Args:
        folder: Root folder path
        recursive: If True, also scan subfolders
    
    Returns:
        List of (Instrument, success, message) tuples
    """
    if not os.path.isdir(folder):
        return []
    
    wav_files = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith('.wav'):
                    wav_files.append(os.path.join(root, f))
    else:
        wav_files = [os.path.join(folder, f) for f in os.listdir(folder)
                     if f.lower().endswith('.wav')]
    
    wav_files.sort()
    return load_samples_multi(wav_files)


def import_pokeyvq(json_path: str) -> Tuple[List[Tuple[Instrument, bool, str]], dict, str]:
    """Import PokeyVQ conversion output.
    
    Args:
        json_path: Path to conversion_info.json
        
    Returns:
        Tuple of (results, config, message) where:
        - results: List of (instrument, success, message) for each sample
        - config: The config dict from JSON (rate, codebook_size, etc.)
        - message: Overall status message
    """
    try:
        if not os.path.exists(json_path):
            return [], {}, f"File not found: {json_path}"
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        config = data.get('config', {})
        samples = data.get('samples', [])
        
        if not samples:
            return [], config, "No samples found in conversion info"
        
        # Base directory for resolving relative paths
        base_dir = os.path.dirname(os.path.abspath(json_path))
        
        results = []
        loaded = 0
        failed = 0
        
        for sample_info in samples:
            inst = Instrument()
            
            # Get instrument file path
            inst_file = sample_info.get('instrument_file', '')
            
            # If path is not absolute, try relative to JSON location
            if inst_file and not os.path.isabs(inst_file):
                inst_file = os.path.join(base_dir, inst_file)
            
            # If still not found, try relative 'instruments' folder
            if inst_file and not os.path.exists(inst_file):
                # Try the instruments subfolder
                basename = os.path.basename(inst_file)
                alt_path = os.path.join(base_dir, 'instruments', basename)
                if os.path.exists(alt_path):
                    inst_file = alt_path
            
            # Set name from original file (without extension)
            original_file = sample_info.get('original_file', '')
            if original_file:
                inst.name = os.path.splitext(original_file)[0][:16]
            
            # Load the sample
            if inst_file and os.path.exists(inst_file):
                ok, msg = load_sample(inst, inst_file)
                if ok:
                    loaded += 1
                else:
                    failed += 1
                results.append((inst, ok, msg))
            else:
                failed += 1
                results.append((inst, False, f"File not found: {inst_file}"))
        
        rate = config.get('rate', 0)
        msg = f"Imported {loaded}/{len(samples)} samples"
        if rate:
            msg += f" (rate: {rate:.0f}Hz)"
        if failed:
            msg += f", {failed} failed"
        
        return results, config, msg
        
    except json.JSONDecodeError as e:
        return [], {}, f"Invalid JSON: {e}"
    except Exception as e:
        logger.error(f"Import PokeyVQ failed: {e}")
        return [], {}, f"Import failed: {e}"


def _read_wav(path: str) -> Tuple[int, Optional[np.ndarray]]:
    """Read WAV file using scipy or wave module."""
    if SCIPY_OK:
        try:
            return scipy_wav.read(path)
        except:
            pass
    
    try:
        with wave.open(path, 'rb') as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            raw = wf.readframes(frames)
            
            dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}
            dtype = dtype_map.get(width)
            if not dtype:
                return rate, None
            
            data = np.frombuffer(raw, dtype=dtype)
            if channels > 1:
                data = data.reshape(-1, channels)
            return rate, data
    except:
        pass
    
    return 44100, None
