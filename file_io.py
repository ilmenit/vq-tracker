"""
Atari Sample Tracker - File I/O
Project files (.pvq), WAV loading, ASM export.
"""

import json
import gzip
import os
from typing import Optional, Tuple
import numpy as np
import wave

try:
    from scipy.io import wavfile as scipy_wav
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

from constants import PROJECT_EXT, note_to_str
from data_model import Song, Instrument

# =============================================================================
# PROJECT FILES
# =============================================================================

def save_project(song: Song, path: str) -> Tuple[bool, str]:
    """Save project to .pvq file."""
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
        base = os.path.dirname(os.path.abspath(path))
        loaded, missing = 0, 0
        for inst in song.instruments:
            if inst.sample_path:
                if _try_load(inst, base):
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


def _try_load(inst: Instrument, base: str) -> bool:
    """Try loading sample from various paths."""
    paths = [
        inst.sample_path if os.path.isabs(inst.sample_path) else None,
        os.path.join(base, inst.sample_path),
        os.path.join(base, os.path.basename(inst.sample_path)),
        os.path.join(base, 'samples', os.path.basename(inst.sample_path)),
    ]
    for p in paths:
        if p and os.path.exists(p):
            ok, _ = load_sample(inst, p)
            if ok:
                return True
    return False

# =============================================================================
# SAMPLE LOADING
# =============================================================================

def load_sample(inst: Instrument, path: str) -> Tuple[bool, str]:
    """Load WAV sample into instrument."""
    try:
        if not os.path.exists(path):
            return False, f"File not found: {path}"
        
        if not path.lower().endswith('.wav'):
            return False, f"Unsupported format"
        
        rate, data = _load_wav(path)
        if data is None:
            return False, "Failed to read WAV"
        
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
        
        mx = np.max(np.abs(data))
        if mx > 1.0:
            data = data / mx
        
        inst.sample_data = data
        inst.sample_rate = rate
        inst.sample_path = path
        
        if inst.name in ("New Instrument", "Untitled", ""):
            inst.name = os.path.splitext(os.path.basename(path))[0]
        
        dur = len(data) / rate
        return True, f"Loaded: {len(data):,} samples, {rate}Hz, {dur:.2f}s"
    except Exception as e:
        return False, f"Load failed: {e}"


def _load_wav(path: str) -> Tuple[int, Optional[np.ndarray]]:
    """Load WAV file."""
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
            
            dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
            if not dtype:
                return rate, None
            
            data = np.frombuffer(raw, dtype=dtype)
            if channels > 1:
                data = data.reshape(-1, channels)
            return rate, data
    except:
        pass
    
    return 44100, None

# =============================================================================
# ASM EXPORT
# =============================================================================

def export_asm(song: Song, out_dir: str) -> Tuple[bool, str]:
    """Export to ASM files."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        
        # Metadata
        with open(os.path.join(out_dir, "song_metadata.asm"), 'w') as f:
            f.write(f"; Song: {song.title}\n; Author: {song.author}\n")
            f.write(f"SONG_SPEED = {song.speed}\n")
            f.write(f"SONG_SYSTEM = {song.system}\n")
            f.write(f"SONG_LENGTH = {len(song.songlines)}\n")
        
        # Songlines
        with open(os.path.join(out_dir, "song_data.asm"), 'w') as f:
            f.write("; Songline data\nSONGLINES:\n")
            for i, sl in enumerate(song.songlines):
                f.write(f"    .byte ${sl.patterns[0]:02X},${sl.patterns[1]:02X},${sl.patterns[2]:02X} ; {i:02X}\n")
        
        # Patterns
        with open(os.path.join(out_dir, "pattern_data.asm"), 'w') as f:
            f.write("; Pattern data\n")
            f.write("PATTERN_LO:\n")
            for i in range(len(song.patterns)):
                f.write(f"    .byte <PTN_{i:02X}\n")
            f.write("PATTERN_HI:\n")
            for i in range(len(song.patterns)):
                f.write(f"    .byte >PTN_{i:02X}\n")
            f.write("PATTERN_LEN:\n")
            for i, p in enumerate(song.patterns):
                f.write(f"    .byte ${p.length:02X}\n")
            
            for i, ptn in enumerate(song.patterns):
                f.write(f"\nPTN_{i:02X}:\n")
                for j, r in enumerate(ptn.rows):
                    f.write(f"    .byte ${r.note:02X},${r.instrument:02X},${r.volume:X} ; {note_to_str(r.note)}\n")
        
        # Instruments
        with open(os.path.join(out_dir, "instrument_data.asm"), 'w') as f:
            f.write("; Instruments\n")
            for i, inst in enumerate(song.instruments):
                f.write(f"; ${i:02X}: {inst.name} ({os.path.basename(inst.sample_path)})\n")
        
        return True, f"Exported to {os.path.basename(out_dir)}/"
    except Exception as e:
        return False, f"Export failed: {e}"
