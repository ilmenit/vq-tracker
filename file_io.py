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

from constants import PROJECT_EXT, BINARY_EXT, note_to_str
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
    """Export to ASM include files for 6502 player."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        
        # song_meta.asm
        with open(os.path.join(out_dir, "song_meta.asm"), 'w') as f:
            f.write(f"; Song: {song.title}\n")
            f.write(f"; Author: {song.author}\n")
            f.write(f"; Generated by Atari Sample Tracker\n\n")
            f.write(f"SONG_SPEED = {song.speed}\n")
            f.write(f"SONG_SYSTEM = {song.system}\n")
            f.write(f"SONG_LENGTH = {len(song.songlines)}\n")
            f.write(f"PATTERN_COUNT = {len(song.patterns)}\n")
            f.write(f"INSTRUMENT_COUNT = {len(song.instruments)}\n")
        
        # song_data.asm
        with open(os.path.join(out_dir, "song_data.asm"), 'w') as f:
            f.write("; Songline data (3 bytes per line: CH1, CH2, CH3)\n")
            f.write("SONGLINES:\n")
            for i, sl in enumerate(song.songlines):
                f.write(f"    .byte ${sl.patterns[0]:02X},${sl.patterns[1]:02X},${sl.patterns[2]:02X}")
                f.write(f" ; Line {i:02X}\n")
        
        # pattern_data.asm
        with open(os.path.join(out_dir, "pattern_data.asm"), 'w') as f:
            f.write("; Pattern pointer tables\n")
            f.write("PATTERN_LO:\n")
            for i in range(len(song.patterns)):
                f.write(f"    .byte <PATTERN_{i:02X}\n")
            f.write("\nPATTERN_HI:\n")
            for i in range(len(song.patterns)):
                f.write(f"    .byte >PATTERN_{i:02X}\n")
            f.write("\nPATTERN_LEN:\n")
            for ptn in song.patterns:
                f.write(f"    .byte ${ptn.length:02X}\n")
            
            # Pattern data
            for i, ptn in enumerate(song.patterns):
                f.write(f"\n; Pattern {i:02X} ({ptn.length} rows)\n")
                f.write(f"PATTERN_{i:02X}:\n")
                for j, row in enumerate(ptn.rows):
                    note_str = note_to_str(row.note)
                    f.write(f"    .byte ${row.note:02X},${row.instrument:02X},${row.volume:X}")
                    f.write(f" ; {j:02X}: {note_str}\n")
        
        # instrument_data.asm
        with open(os.path.join(out_dir, "instrument_data.asm"), 'w') as f:
            f.write("; Instrument definitions\n")
            for i, inst in enumerate(song.instruments):
                sample_name = os.path.basename(inst.sample_path) if inst.sample_path else "none"
                f.write(f"; ${i:02X}: {inst.name} ({sample_name})\n")
        
        # song.asm (main include file)
        with open(os.path.join(out_dir, "song.asm"), 'w') as f:
            f.write("; Main song include file\n")
            f.write("    icl 'song_meta.asm'\n")
            f.write("    icl 'song_data.asm'\n")
            f.write("    icl 'pattern_data.asm'\n")
            f.write("    icl 'instrument_data.asm'\n")
        
        return True, f"Exported to {os.path.basename(out_dir)}/"
    except Exception as e:
        return False, f"Export failed: {e}"

# =============================================================================
# SAMPLE LOADING
# =============================================================================

def load_sample(inst: Instrument, path: str) -> Tuple[bool, str]:
    """Load WAV sample into instrument."""
    logger.debug(f"load_sample: path={path}")
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
