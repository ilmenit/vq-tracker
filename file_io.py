"""
Atari Sample Tracker - File I/O Module
=======================================

Project file format (.pvq):
    ZIP archive containing:
    - project.json: Song data, editor state, VQ settings
    - samples/: WAV audio files (embedded)
    - vq_output/: VQ conversion output (ASM files, if converted)
    - metadata.json: Format version, timestamps

Working directory:
    .tmp/ folder in application directory with subdirectories:
    - samples/: Imported/extracted sample files
    - vq_output/: VQ conversion results
    - build/: Build artifacts

Instance locking:
    Uses .tmp/lock file to prevent multiple instances
"""

import json
import os
import shutil
import struct
import wave
import zipfile
import logging
import time
import atexit
import hashlib
import subprocess
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional, Tuple, List, Dict, Any
import numpy as np

logger = logging.getLogger("tracker.file_io")

# Optional audio library for format conversion
try:
    from pydub import AudioSegment
    PYDUB_OK = True
    logger.info("pydub available - multi-format audio import enabled")
except ImportError:
    PYDUB_OK = False
    logger.warning("pydub not available - only WAV import supported")

try:
    from scipy.io import wavfile as scipy_wav
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

from constants import (PROJECT_EXT, BINARY_EXT, DEFAULT_SPEED, DEFAULT_OCTAVE,
                       DEFAULT_STEP, MAX_VOLUME, PAL_HZ, FOCUS_EDITOR, NOTE_OFF)
from data_model import Song, Instrument, Pattern, Row

# =============================================================================
# CONSTANTS
# =============================================================================

# Supported audio formats for import
SUPPORTED_AUDIO = {'.wav', '.mp3', '.ogg', '.flac', '.aiff', '.aif', '.m4a', '.wma'}

# Project format version
FORMAT_VERSION = 1

# Working directory structure
WORK_DIR = ".tmp"
SAMPLES_DIR = "samples"
VQ_OUTPUT_DIR = "vq_output"
BUILD_DIR = "build"
LOCK_FILE = "tracker.lock"

# =============================================================================
# EDITOR STATE (for persistence)
# =============================================================================

@dataclass
class EditorState:
    """Persistent editor state saved with project."""
    
    # Cursor position
    songline: int = 0
    row: int = 0
    channel: int = 0
    column: int = 0
    
    # Song editor cursor
    song_cursor_row: int = 0
    song_cursor_col: int = 0
    
    # Input settings
    octave: int = DEFAULT_OCTAVE
    step: int = DEFAULT_STEP
    instrument: int = 0
    volume: int = MAX_VOLUME
    selected_pattern: int = 0
    
    # Display settings
    hex_mode: bool = True
    follow: bool = True
    focus: int = FOCUS_EDITOR
    
    # VQ settings
    vq_converted: bool = False
    vq_rate: int = 7917
    vq_vector_size: int = 2
    vq_smoothness: int = 0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> 'EditorState':
        # Only use keys that exist in the dataclass
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


# =============================================================================
# INSTANCE LOCKING
# =============================================================================

class InstanceLock:
    """Manages single-instance lock via lock file."""
    
    def __init__(self, app_dir: str):
        self.lock_path = os.path.join(app_dir, WORK_DIR, LOCK_FILE)
        self.locked = False
        self.pid = os.getpid()
    
    def acquire(self) -> Tuple[bool, str]:
        """Try to acquire lock. Returns (success, message)."""
        lock_dir = os.path.dirname(self.lock_path)
        os.makedirs(lock_dir, exist_ok=True)
        
        # Check existing lock
        if os.path.exists(self.lock_path):
            try:
                with open(self.lock_path, 'r') as f:
                    data = json.load(f)
                    old_pid = data.get('pid', 0)
                    timestamp = data.get('timestamp', '')
                    
                    # Check if process is still running
                    if self._is_process_running(old_pid):
                        return False, f"Another instance is already running (PID: {old_pid})"
                    else:
                        # Stale lock file - remove it
                        logger.info(f"Removing stale lock from PID {old_pid}")
                        os.remove(self.lock_path)
            except (json.JSONDecodeError, KeyError, OSError):
                # Corrupt lock file - remove it
                try:
                    os.remove(self.lock_path)
                except:
                    pass
        
        # Create new lock
        try:
            with open(self.lock_path, 'w') as f:
                json.dump({
                    'pid': self.pid,
                    'timestamp': datetime.now().isoformat()
                }, f)
            self.locked = True
            atexit.register(self.release)
            return True, "Lock acquired"
        except Exception as e:
            return False, f"Failed to create lock: {e}"
    
    def release(self):
        """Release lock."""
        if self.locked and os.path.exists(self.lock_path):
            try:
                os.remove(self.lock_path)
                self.locked = False
            except:
                pass
    
    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running."""
        if pid <= 0:
            return False
        try:
            # Unix/Mac: send signal 0 (doesn't kill, just checks)
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except:
            # Windows fallback
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            except:
                return False


# =============================================================================
# WORKING DIRECTORY MANAGEMENT
# =============================================================================

class WorkingDirectory:
    """Manages the .tmp working directory structure."""
    
    def __init__(self, app_dir: str):
        self.app_dir = app_dir
        self.root = os.path.join(app_dir, WORK_DIR)
        self.samples = os.path.join(self.root, SAMPLES_DIR)
        self.vq_output = os.path.join(self.root, VQ_OUTPUT_DIR)
        self.build = os.path.join(self.root, BUILD_DIR)
    
    def init(self):
        """Initialize directory structure."""
        os.makedirs(self.samples, exist_ok=True)
        os.makedirs(self.vq_output, exist_ok=True)
        os.makedirs(self.build, exist_ok=True)
    
    def clear_samples(self):
        """Clear samples directory."""
        if os.path.exists(self.samples):
            shutil.rmtree(self.samples)
        os.makedirs(self.samples, exist_ok=True)
    
    def clear_vq_output(self):
        """Clear VQ output directory."""
        if os.path.exists(self.vq_output):
            shutil.rmtree(self.vq_output)
        os.makedirs(self.vq_output, exist_ok=True)
    
    def clear_build(self):
        """Clear build directory."""
        if os.path.exists(self.build):
            shutil.rmtree(self.build)
        os.makedirs(self.build, exist_ok=True)
    
    def clear_all(self):
        """Clear all working directories (for new project)."""
        self.clear_samples()
        self.clear_vq_output()
        self.clear_build()


# Global working directory instance (initialized in main.py)
work_dir: Optional[WorkingDirectory] = None


def init_working_directory(app_dir: str) -> WorkingDirectory:
    """Initialize working directory for the application."""
    global work_dir
    work_dir = WorkingDirectory(app_dir)
    work_dir.init()
    return work_dir


# =============================================================================
# AUDIO FORMAT CONVERSION
# =============================================================================

def _safe_filename(name: str) -> str:
    """Convert name to safe filename."""
    # Remove/replace problematic characters
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return safe.strip()[:64] or "sample"


def convert_to_wav(source_path: str, dest_path: str) -> Tuple[bool, str]:
    """Convert audio file to WAV format.
    
    Args:
        source_path: Path to source audio file
        dest_path: Path for output WAV file
        
    Returns:
        (success, message)
    """
    if not PYDUB_OK:
        return False, "pydub not installed - cannot convert audio formats"
    
    try:
        # Load audio (pydub auto-detects format)
        audio = AudioSegment.from_file(source_path)
        
        # Convert to mono, 16-bit for compatibility
        audio = audio.set_channels(1)
        audio = audio.set_sample_width(2)  # 16-bit
        
        # Export as WAV
        audio.export(dest_path, format="wav")
        
        duration = len(audio) / 1000.0
        return True, f"Converted: {duration:.2f}s, {audio.frame_rate}Hz"
    except Exception as e:
        return False, f"Conversion failed: {e}"


def import_audio_file(source_path: str, dest_dir: str, 
                      index: int = 0) -> Tuple[Optional[str], str]:
    """Import audio file to working directory, converting if needed.
    
    Args:
        source_path: Path to source audio file
        dest_dir: Destination directory (usually work_dir.samples)
        index: Instrument index for filename prefix
        
    Returns:
        (dest_path or None, message)
    """
    if not os.path.exists(source_path):
        return None, f"File not found: {source_path}"
    
    ext = os.path.splitext(source_path)[1].lower()
    basename = os.path.splitext(os.path.basename(source_path))[0]
    safe_name = _safe_filename(basename)
    
    # Generate destination filename with index prefix
    dest_filename = f"{index:02d}_{safe_name}.wav"
    dest_path = os.path.join(dest_dir, dest_filename)
    
    # Ensure unique filename
    counter = 1
    while os.path.exists(dest_path):
        dest_filename = f"{index:02d}_{safe_name}_{counter}.wav"
        dest_path = os.path.join(dest_dir, dest_filename)
        counter += 1
    
    if ext == '.wav':
        # Just copy WAV files
        try:
            shutil.copy2(source_path, dest_path)
            return dest_path, "Copied"
        except Exception as e:
            return None, f"Copy failed: {e}"
    elif ext in SUPPORTED_AUDIO:
        # Convert other formats to WAV
        ok, msg = convert_to_wav(source_path, dest_path)
        if ok:
            return dest_path, msg
        return None, msg
    else:
        return None, f"Unsupported format: {ext}"


def get_supported_extensions() -> List[str]:
    """Get list of supported audio file extensions."""
    if PYDUB_OK:
        return sorted(SUPPORTED_AUDIO)
    else:
        return ['.wav']


# =============================================================================
# PROJECT FILE (ZIP FORMAT)
# =============================================================================

def save_project(song: Song, editor_state: EditorState, 
                 path: str, work_dir: WorkingDirectory) -> Tuple[bool, str]:
    """Save project as ZIP archive.
    
    Args:
        song: Song data
        editor_state: Editor state to persist
        path: Output file path
        work_dir: Working directory instance
        
    Returns:
        (success, message)
    """
    try:
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT
        
        # Build project data
        project_data = {
            "version": FORMAT_VERSION,
            "meta": {
                "title": song.title,
                "author": song.author,
                "system": song.system,
                "volume_control": song.volume_control,
                "created": datetime.now().isoformat(),
            },
            "editor": editor_state.to_dict(),
            "songlines": [{'patterns': sl.patterns, 'speed': sl.speed} 
                          for sl in song.songlines],
            "patterns": [p.to_dict() for p in song.patterns],
            "instruments": []
        }
        
        # Write to ZIP
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            
            # Add samples and build instrument list
            for idx, inst in enumerate(song.instruments):
                inst_data = {
                    "name": inst.name,
                    "base_note": inst.base_note,
                    "original_path": inst.original_sample_path or inst.sample_path,
                    "sample_file": None
                }
                
                # Add sample file if exists
                if inst.sample_path and os.path.exists(inst.sample_path):
                    # Archive path: samples/00_name.wav
                    safe_name = _safe_filename(inst.name)
                    archive_name = f"{SAMPLES_DIR}/{idx:02d}_{safe_name}.wav"
                    zf.write(inst.sample_path, archive_name)
                    inst_data["sample_file"] = archive_name
                
                project_data["instruments"].append(inst_data)
            
            # Add project.json
            zf.writestr("project.json", json.dumps(project_data, indent=2))
            
            # Add VQ output if exists and converted
            if editor_state.vq_converted and os.path.isdir(work_dir.vq_output):
                vq_files = []
                for root, dirs, files in os.walk(work_dir.vq_output):
                    for file in files:
                        src = os.path.join(root, file)
                        arc = os.path.relpath(src, work_dir.vq_output)
                        arc_path = f"{VQ_OUTPUT_DIR}/{arc}"
                        zf.write(src, arc_path)
                        vq_files.append(arc_path)
                
                if vq_files:
                    logger.info(f"Added {len(vq_files)} VQ output files to archive")
            
            # Add metadata
            metadata = {
                "format": "Atari Sample Tracker Project",
                "format_version": FORMAT_VERSION,
                "app_version": "3.0",
                "created": datetime.now().isoformat(),
                "vq_converted": editor_state.vq_converted
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))
        
        song.file_path = path
        song.modified = False
        
        return True, f"Saved: {os.path.basename(path)}"
        
    except PermissionError:
        return False, f"Permission denied: {path}"
    except Exception as e:
        logger.error(f"Save failed: {e}")
        return False, f"Save failed: {e}"


def load_project(path: str, work_dir: WorkingDirectory
                 ) -> Tuple[Optional[Song], Optional[EditorState], str]:
    """Load project from ZIP archive.
    
    Args:
        path: Project file path
        work_dir: Working directory instance
        
    Returns:
        (song or None, editor_state or None, message)
    """
    try:
        if not os.path.exists(path):
            return None, None, f"File not found: {path}"
        
        # Clear working directories for new project
        work_dir.clear_all()
        
        # Extract ZIP to working directory
        with zipfile.ZipFile(path, 'r') as zf:
            # Extract all files
            zf.extractall(work_dir.root)
        
        # Load project.json
        project_path = os.path.join(work_dir.root, "project.json")
        if not os.path.exists(project_path):
            return None, None, "Invalid project file: missing project.json"
        
        with open(project_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Build Song object
        meta = data.get('meta', {})
        song = Song(
            title=meta.get('title', 'Untitled'),
            author=meta.get('author', ''),
            system=meta.get('system', PAL_HZ),
            volume_control=meta.get('volume_control', False)
        )
        song.file_path = path
        song.modified = False
        
        # Load songlines
        raw_songlines = data.get('songlines', [[0, 1, 2]])
        from data_model import Songline
        song.songlines = []
        for sl in raw_songlines:
            if isinstance(sl, dict):
                song.songlines.append(Songline(
                    patterns=list(sl.get('patterns', [0, 0, 0])),
                    speed=sl.get('speed', DEFAULT_SPEED)
                ))
            else:
                song.songlines.append(Songline(patterns=list(sl)))
        
        # Load patterns
        song.patterns = [Pattern.from_dict(p) for p in data.get('patterns', [])]
        while len(song.patterns) < 3:
            song.patterns.append(Pattern())
        
        # Load instruments with samples
        samples_dir = os.path.join(work_dir.root, SAMPLES_DIR)
        loaded_samples = 0
        missing_samples = 0
        
        for inst_data in data.get('instruments', []):
            inst = Instrument(
                name=inst_data.get('name', 'New'),
                base_note=inst_data.get('base_note', 1)
            )
            inst.original_sample_path = inst_data.get('original_path', '')
            
            # Load sample from archive
            sample_file = inst_data.get('sample_file')
            if sample_file:
                sample_path = os.path.join(work_dir.root, sample_file)
                if os.path.exists(sample_path):
                    # Copy to samples dir with consistent naming
                    dest_path = os.path.join(work_dir.samples, os.path.basename(sample_file))
                    if sample_path != dest_path:
                        shutil.copy2(sample_path, dest_path)
                    ok, msg = load_sample(inst, dest_path)
                    if ok:
                        loaded_samples += 1
                    else:
                        missing_samples += 1
                        logger.warning(f"Failed to load sample: {msg}")
                else:
                    missing_samples += 1
                    logger.warning(f"Sample not found in archive: {sample_file}")
            
            song.instruments.append(inst)
        
        # Load editor state
        editor_data = data.get('editor', {})
        editor_state = EditorState.from_dict(editor_data)
        
        # Check if VQ output exists
        vq_dir = os.path.join(work_dir.root, VQ_OUTPUT_DIR)
        if os.path.isdir(vq_dir) and os.listdir(vq_dir):
            # Copy to proper vq_output location
            if vq_dir != work_dir.vq_output:
                if os.path.exists(work_dir.vq_output):
                    shutil.rmtree(work_dir.vq_output)
                shutil.copytree(vq_dir, work_dir.vq_output)
            editor_state.vq_converted = True
        
        # Build message
        msg = f"Loaded: {os.path.basename(path)}"
        if loaded_samples:
            msg += f" ({loaded_samples} samples)"
        if missing_samples:
            msg += f" ({missing_samples} missing)"
        if editor_state.vq_converted:
            msg += " [VQ ready]"
        
        return song, editor_state, msg
        
    except zipfile.BadZipFile:
        return None, None, "Invalid project file: not a valid ZIP archive"
    except json.JSONDecodeError as e:
        return None, None, f"Invalid project file: JSON error - {e}"
    except Exception as e:
        logger.error(f"Load failed: {e}")
        return None, None, f"Load failed: {e}"


# =============================================================================
# SAMPLE LOADING
# =============================================================================

def load_sample(inst: Instrument, path: str, 
                is_converted: bool = False) -> Tuple[bool, str]:
    """Load WAV sample into instrument.
    
    Args:
        inst: Instrument to load into
        path: Path to WAV file
        is_converted: If True, don't update original_sample_path
        
    Returns:
        (success, message)
    """
    logger.debug(f"load_sample: path={path}, is_converted={is_converted}")
    try:
        if not os.path.exists(path):
            return False, f"File not found: {path}"
        
        if not path.lower().endswith('.wav'):
            return False, "File must be WAV format (use import_audio_file for conversion)"
        
        rate, data = _read_wav(path)
        if data is None:
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
        
        if not is_converted:
            inst.original_sample_path = path
        
        # Auto-name from filename if empty
        if inst.name in ("New", "New Instrument", ""):
            inst.name = os.path.splitext(os.path.basename(path))[0][:16]
        
        duration = len(data) / rate
        return True, f"Loaded: {len(data):,} samples, {rate}Hz, {duration:.2f}s"
        
    except Exception as e:
        logger.error(f"Load failed: {e}")
        return False, f"Load failed: {e}"


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


# =============================================================================
# MULTI-FILE / FOLDER IMPORT
# =============================================================================

def import_samples_multi(paths: List[str], dest_dir: str, 
                         start_index: int = 0
                         ) -> List[Tuple[Instrument, bool, str]]:
    """Import multiple audio files.
    
    Args:
        paths: List of source file paths
        dest_dir: Destination directory for converted WAV files
        start_index: Starting instrument index for filename prefixes
        
    Returns:
        List of (instrument, success, message) tuples
    """
    results = []
    
    for i, path in enumerate(paths):
        inst = Instrument()
        
        # Import and convert to WAV if needed
        dest_path, import_msg = import_audio_file(path, dest_dir, start_index + i)
        
        if dest_path:
            # Load the WAV file
            ok, load_msg = load_sample(inst, dest_path)
            # Store original path
            inst.original_sample_path = path
            results.append((inst, ok, f"{import_msg}; {load_msg}" if ok else import_msg))
        else:
            results.append((inst, False, import_msg))
    
    return results


def import_samples_folder(folder: str, dest_dir: str, 
                          recursive: bool = True,
                          start_index: int = 0
                          ) -> List[Tuple[Instrument, bool, str]]:
    """Import all audio files from folder.
    
    Args:
        folder: Source folder path
        dest_dir: Destination directory for converted WAV files
        recursive: If True, scan subfolders
        start_index: Starting instrument index
        
    Returns:
        List of (instrument, success, message) tuples
    """
    if not os.path.isdir(folder):
        return []
    
    # Find all supported audio files
    audio_files = []
    extensions = get_supported_extensions()
    
    if recursive:
        for root, dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in extensions:
                    audio_files.append(os.path.join(root, f))
    else:
        audio_files = [
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in extensions
        ]
    
    audio_files.sort()
    return import_samples_multi(audio_files, dest_dir, start_index)


# =============================================================================
# BINARY EXPORT (.pvg) - Legacy format
# =============================================================================

def export_binary(song: Song, path: str) -> Tuple[bool, str]:
    """Export to binary .pvg format for Atari player."""
    try:
        if not path.lower().endswith(BINARY_EXT):
            path += BINARY_EXT
        
        with open(path, 'wb') as f:
            f.write(b'PVG')
            f.write(struct.pack('B', 3))
            f.write(struct.pack('<B', song.speed))
            f.write(struct.pack('<B', song.system))
            f.write(struct.pack('<H', len(song.songlines)))
            f.write(struct.pack('<H', len(song.patterns)))
            f.write(struct.pack('<B', len(song.instruments)))
            
            for sl in song.songlines:
                for p in sl.patterns:
                    f.write(struct.pack('B', p))
            
            for ptn in song.patterns:
                f.write(struct.pack('<H', ptn.length))
                for row in ptn.rows:
                    f.write(struct.pack('BBB', row.note, row.instrument, row.volume))
        
        return True, f"Exported: {os.path.basename(path)}"
    except Exception as e:
        return False, f"Export failed: {e}"


# =============================================================================
# ASM EXPORT - Song Data
# =============================================================================

def export_asm(song: Song, out_dir: str) -> Tuple[bool, str]:
    """Export song data to ASM include files."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        
        with open(os.path.join(out_dir, "SONG_DATA.asm"), 'w') as f:
            f.write("; ==========================================================================\n")
            f.write("; SONG DATA - Generated by Atari Sample Tracker\n")
            f.write("; ==========================================================================\n")
            f.write(f"; Song: {song.title}\n")
            f.write(f"; Author: {song.author}\n")
            f.write("; ==========================================================================\n\n")
            
            # Configuration flags
            vol_val = 1 if song.volume_control else 0
            f.write("; Configuration\n")
            f.write(f"VOLUME_CONTROL = {vol_val}  ; 1=enable volume scaling, 0=disable\n\n")
            
            # Song length
            num_songlines = len(song.songlines)
            f.write(f"SONG_LENGTH = {num_songlines}\n\n")
            
            # Speed per songline
            f.write("; Speed per songline\n")
            f.write("SONG_SPEED:\n    .byte ")
            f.write(",".join(f"${sl.speed:02X}" for sl in song.songlines))
            f.write("\n\n")
            
            # Pattern assignments per channel
            for ch in range(3):
                f.write(f"SONG_PTN_CH{ch}:\n    .byte ")
                f.write(",".join(f"${sl.patterns[ch]:02X}" for sl in song.songlines))
                f.write("\n\n")
            
            # Pattern directory
            num_patterns = len(song.patterns)
            f.write(f"PATTERN_COUNT = {num_patterns}\n\n")
            
            f.write("PATTERN_LEN:\n    .byte ")
            f.write(",".join(f"${p.length:02X}" for p in song.patterns))
            f.write("\n\n")
            
            f.write("PATTERN_PTR_LO:\n    .byte ")
            f.write(",".join(f"<PTN_{i:02X}" for i in range(num_patterns)))
            f.write("\n\n")
            
            f.write("PATTERN_PTR_HI:\n    .byte ")
            f.write(",".join(f">PTN_{i:02X}" for i in range(num_patterns)))
            f.write("\n\n")
            
            # Pattern data (variable-length events)
            f.write("; Pattern event data\n")
            
            for i, ptn in enumerate(song.patterns):
                f.write(f"PTN_{i:02X}:\n")
                
                last_inst = -1
                last_vol = -1
                
                for row_num, row in enumerate(ptn.rows):
                    if row_num >= ptn.length or row.note == 0:
                        continue
                    
                    # Handle NOTE_OFF: export as note=0 (ASM player interprets as silence)
                    export_note = 0 if row.note == NOTE_OFF else row.note
                    
                    # Build event bytes
                    if last_inst == -1:
                        # Full event
                        f.write(f"    .byte ${row_num:02X},${export_note|0x80:02X},${row.instrument|0x80:02X},${row.volume:02X}\n")
                        last_inst = row.instrument
                        last_vol = row.volume
                    elif row.instrument != last_inst or row.volume != last_vol:
                        if row.volume != last_vol:
                            f.write(f"    .byte ${row_num:02X},${export_note|0x80:02X},${row.instrument|0x80:02X},${row.volume:02X}\n")
                        else:
                            f.write(f"    .byte ${row_num:02X},${export_note|0x80:02X},${row.instrument:02X}\n")
                        last_inst = row.instrument
                        last_vol = row.volume
                    else:
                        f.write(f"    .byte ${row_num:02X},${export_note:02X}\n")
                
                f.write("    .byte $FF\n\n")
        
        return True, f"Exported to {out_dir}/"
    except Exception as e:
        return False, f"Export failed: {e}"


# =============================================================================
# VQ_CONVERTER IMPORT (Legacy compatibility)
# =============================================================================

def import_pokeyvq(json_path: str) -> Tuple[List[Tuple[Instrument, bool, str]], dict, str]:
    """Import vq_converter output (conversion_info.json).
    
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
                basename = os.path.basename(inst_file)
                alt_path = os.path.join(base_dir, 'instruments', basename)
                if os.path.exists(alt_path):
                    inst_file = alt_path
            
            # Set name from original file
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
        logger.error(f"Import vq_converter failed: {e}")
        return [], {}, f"Import failed: {e}"
