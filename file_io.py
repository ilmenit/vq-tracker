"""
POKEY VQ Tracker - File I/O Module
=======================================

Project file format (.pvq):
    ZIP archive containing:
    - project.json: Song data, editor state, VQ settings
    - samples/: WAV audio files (original sources)
    - metadata.json: Format version, timestamps
    
    NOTE: VQ output is NOT saved in archives. It is auto-regenerated
    on load to ensure the latest conversion algorithm is always used.

Working directory:
    .tmp/ folder in application directory with subdirectories:
    - samples/: Imported/extracted sample files
    - vq_output/: VQ conversion results (regenerated on load)
    - build/: Build artifacts

Instance locking:
    Uses .tmp/lock file to prevent multiple instances
"""

import json
import os
import sys
import shutil
import struct
import wave
import zipfile
import logging
import time
import atexit
import hashlib
import subprocess
import platform
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional, Tuple, List, Dict, Any
import numpy as np

logger = logging.getLogger("tracker.file_io")

# =============================================================================
# FFMPEG AUTO-DETECTION
# =============================================================================
# Look for bundled ffmpeg before importing pydub so it can find it.
# On Windows, ffmpeg.exe and ffprobe.exe should be placed in:
#   - bin/ffmpeg/ (preferred)
#   - bin/windows_x86_64/ (alongside mads.exe)
#   - ffmpeg/ (app root)
# =============================================================================

def _find_bundled_ffmpeg() -> Optional[str]:
    """Find bundled ffmpeg directory."""
    if platform.system() != "Windows":
        return None  # Linux/macOS typically have ffmpeg in PATH
    
    # Determine app directory
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        app_dir = os.path.dirname(sys.executable)
    else:
        # Running as script
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Search locations for ffmpeg.exe
    candidates = [
        os.path.join(app_dir, "bin", "ffmpeg"),
        os.path.join(app_dir, "bin", "windows_x86_64"),
        os.path.join(app_dir, "ffmpeg"),
        app_dir,  # App root itself
    ]
    
    for candidate in candidates:
        ffmpeg_exe = os.path.join(candidate, "ffmpeg.exe")
        if os.path.isfile(ffmpeg_exe):
            logger.info(f"Found bundled ffmpeg: {candidate}")
            return candidate
    
    return None

def _setup_ffmpeg_path():
    """Set up ffmpeg path for pydub before importing it."""
    ffmpeg_dir = _find_bundled_ffmpeg()
    if ffmpeg_dir:
        # Add to PATH so pydub (and subprocess calls) can find it
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        logger.info(f"Added ffmpeg to PATH: {ffmpeg_dir}")
        return ffmpeg_dir
    return None

# Try to set up bundled ffmpeg before importing pydub
_FFMPEG_DIR = _setup_ffmpeg_path()

# Optional audio library for format conversion
try:
    # Permanently suppress pydub's ffmpeg/ffprobe warnings
    # These are harmless if ffmpeg is found, just noisy
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="pydub.*")
    
    from pydub import AudioSegment
    PYDUB_OK = True
    
    # Set pydub's converter paths directly (more reliable than PATH)
    if _FFMPEG_DIR:
        from pydub import AudioSegment as _AS
        ffmpeg_exe = os.path.join(_FFMPEG_DIR, "ffmpeg.exe")
        ffprobe_exe = os.path.join(_FFMPEG_DIR, "ffprobe.exe")
        
        if os.path.isfile(ffmpeg_exe):
            _AS.converter = ffmpeg_exe
            logger.info(f"Set pydub converter: {ffmpeg_exe}")
        else:
            logger.warning(f"ffmpeg.exe not found in {_FFMPEG_DIR}")
            
        if os.path.isfile(ffprobe_exe):
            _AS.ffprobe = ffprobe_exe
            logger.info(f"Set pydub ffprobe: {ffprobe_exe}")
        else:
            # ffprobe is required for format detection (MP3, etc.)
            logger.warning(f"ffprobe.exe not found - MP3/OGG import may fail!")
            logger.warning(f"Please download ffprobe.exe from https://www.gyan.dev/ffmpeg/builds/")
    
    # Check if ffmpeg is actually available
    from pydub.utils import which
    if which("ffmpeg") or (_FFMPEG_DIR and os.path.isfile(os.path.join(_FFMPEG_DIR, "ffmpeg.exe"))):
        logger.info("pydub available with ffmpeg - full audio format support")
        FFMPEG_OK = True
    else:
        logger.info("pydub available - WAV only (ffmpeg not found)")
        FFMPEG_OK = False
except ImportError:
    PYDUB_OK = False
    FFMPEG_OK = False
    logger.warning("pydub not available - only WAV import supported")

try:
    from scipy.io import wavfile as scipy_wav
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

from constants import (PROJECT_EXT, BINARY_EXT, DEFAULT_SPEED, DEFAULT_OCTAVE,
                       DEFAULT_STEP, MAX_VOLUME, PAL_HZ, FOCUS_EDITOR, NOTE_OFF,
                       APP_VERSION, FORMAT_VERSION)
from data_model import Song, Instrument, Pattern, Row

# =============================================================================
# CONSTANTS
# =============================================================================

# Supported audio formats for import
SUPPORTED_AUDIO = {'.wav', '.mp3', '.ogg', '.flac', '.aiff', '.aif', '.m4a', '.wma'}

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
    vq_enhance: bool = True
    vq_optimize_speed: bool = True  # True=speed (full bytes), False=size (nibble-packed)
    
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
                except OSError:
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
            except OSError as e:
                logger.warning(f"Failed to release lock: {e}")
    
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
        except Exception:
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
            except Exception:
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
        # Ensure base .tmp directory exists first
        os.makedirs(self.root, exist_ok=True)
        # Then create subdirectories
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
        logger.debug(f"Converting: {source_path}")
        audio = AudioSegment.from_file(source_path)
        
        # Convert to mono, 16-bit for compatibility
        audio = audio.set_channels(1)
        audio = audio.set_sample_width(2)  # 16-bit
        
        # Export as WAV
        audio.export(dest_path, format="wav")
        
        duration = len(audio) / 1000.0
        return True, f"Converted: {duration:.2f}s, {audio.frame_rate}Hz"
    except FileNotFoundError as e:
        # This usually means ffmpeg/ffprobe wasn't found
        logger.error(f"FFmpeg not found when converting {source_path}: {e}")
        return False, f"Conversion failed: ffmpeg not found. Please install ffmpeg."
    except Exception as e:
        logger.error(f"Conversion error for {source_path}: {type(e).__name__}: {e}")
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
    """Get list of supported audio file extensions.
    
    WAV is always supported.
    Other formats (MP3, OGG, FLAC, etc.) require pydub + ffmpeg.
    """
    if PYDUB_OK and FFMPEG_OK:
        result = sorted(SUPPORTED_AUDIO)
        logger.debug(f"get_supported_extensions: full format support: {result}")
        return result
    else:
        logger.debug(f"get_supported_extensions: WAV only (PYDUB_OK={PYDUB_OK}, FFMPEG_OK={FFMPEG_OK})")
        return ['.wav']


# =============================================================================
# PROJECT FILE (ZIP FORMAT)
# =============================================================================

def save_project(song: Song, editor_state: EditorState, 
                 path: str, work_dir: WorkingDirectory) -> Tuple[bool, str]:
    """Save project as ZIP archive.
    
    Uses Song.to_dict() as single source of truth for serialization.
    Only adds: editor state, sample WAV embedding, and archive metadata.
    
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
        
        # Single source of truth: Song.to_dict()
        project_data = song.to_dict()
        
        # Add editor state (not part of song data)
        project_data['editor'] = editor_state.to_dict()
        project_data['meta']['created'] = datetime.now().isoformat()
        
        # Write to ZIP
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            
            # Embed sample WAV files and record archive paths in instrument dicts
            embedded_count = 0
            missing_samples = []
            for idx, inst_data in enumerate(project_data['instruments']):
                inst = song.instruments[idx]
                
                if inst.sample_path and os.path.exists(inst.sample_path):
                    # Archive path: samples/00_name.wav
                    safe_name = _safe_filename(inst.name)
                    archive_name = f"{SAMPLES_DIR}/{idx:02d}_{safe_name}.wav"
                    zf.write(inst.sample_path, archive_name)
                    inst_data['sample_file'] = archive_name
                    embedded_count += 1
                elif inst.sample_path:
                    # Sample path set but file missing - log warning
                    missing_samples.append(f"{inst.name} ({os.path.basename(inst.sample_path)})")
                    logger.warning(f"Sample file missing, not embedded: {inst.sample_path}")
            
            # Add project.json
            zf.writestr("project.json", json.dumps(project_data, indent=2))
            
            # Add metadata
            metadata = {
                "format": "POKEY VQ Tracker Project",
                "format_version": FORMAT_VERSION,
                "app_version": APP_VERSION,
                "created": datetime.now().isoformat()
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))
        
        song.file_path = path
        song.modified = False
        
        # Build status message
        msg = f"Saved: {os.path.basename(path)}"
        if embedded_count:
            msg += f" ({embedded_count} samples)"
        if missing_samples:
            msg += f" WARNING: {len(missing_samples)} sample(s) not embedded!"
            logger.warning(f"Missing samples not embedded: {', '.join(missing_samples)}")
        
        return True, msg
        
    except PermissionError:
        return False, f"Permission denied: {path}"
    except Exception as e:
        logger.error(f"Save failed: {e}")
        return False, f"Save failed: {e}"


def load_project(path: str, work_dir: WorkingDirectory
                 ) -> Tuple[Optional[Song], Optional[EditorState], str]:
    """Load project from ZIP archive.
    
    Uses Song.from_dict() as single source of truth for deserialization.
    Only handles: ZIP extraction, sample path remapping, and audio loading.
    
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
            zf.extractall(work_dir.root)
        
        # Load project.json
        project_path = os.path.join(work_dir.root, "project.json")
        if not os.path.exists(project_path):
            return None, None, "Invalid project file: missing project.json"
        
        with open(project_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Remap sample paths: archive paths â†’ extracted working directory paths
        # This must happen BEFORE Song.from_dict() so instruments get usable paths
        for inst_data in data.get('instruments', []):
            sample_file = inst_data.get('sample_file')
            if sample_file:
                # File was extracted to work_dir.root/samples/...
                extracted_path = os.path.join(work_dir.root, sample_file)
                # Copy to canonical samples dir
                dest_path = os.path.join(work_dir.samples, os.path.basename(sample_file))
                if os.path.exists(extracted_path):
                    if extracted_path != dest_path:
                        shutil.copy2(extracted_path, dest_path)
                    # Update sample_path to point to working copy
                    inst_data['sample_path'] = dest_path
        
        # Single source of truth: Song.from_dict()
        song = Song.from_dict(data)
        song.file_path = path
        song.modified = False
        
        # Load actual audio data into instruments
        loaded_samples = 0
        missing_samples = 0
        for inst in song.instruments:
            if inst.sample_path and os.path.exists(inst.sample_path):
                ok, msg = load_sample(inst, inst.sample_path, is_converted=True)
                if ok:
                    loaded_samples += 1
                else:
                    missing_samples += 1
                    logger.warning(f"Failed to load sample: {msg}")
            elif inst.sample_path:
                missing_samples += 1
                logger.warning(f"Sample not found: {inst.sample_path}")
        
        # Load editor state
        editor_data = data.get('editor', {})
        editor_state = EditorState.from_dict(editor_data)
        
        # VQ output is NOT loaded from archive - auto-regenerated with latest algorithm
        editor_state.vq_converted = False
        
        # Build message
        msg = f"Loaded: {os.path.basename(path)}"
        if loaded_samples:
            msg += f" ({loaded_samples} samples)"
        if missing_samples:
            msg += f" ({missing_samples} missing)"
        
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
                is_converted: bool = False,
                update_path: bool = True) -> Tuple[bool, str]:
    """Load WAV sample into instrument.
    
    Args:
        inst: Instrument to load into
        path: Path to WAV file
        is_converted: If True, don't update original_sample_path
        update_path: If True, update inst.sample_path (set False when loading converted)
        
    Returns:
        (success, message)
    """
    logger.debug(f"load_sample: path={path}, is_converted={is_converted}, update_path={update_path}")
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
        
        # Only update sample_path if requested (not when loading converted samples)
        if update_path:
            inst.sample_path = path
        
        if not is_converted and update_path:
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
        except Exception as e:
            logger.debug(f"scipy read failed for {path}: {e}")
    
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
    except Exception as e:
        logger.warning(f"wave read failed for {path}: {e}")
    
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
        # Always set original path for error reporting
        inst.original_sample_path = path
        
        # Import and convert to WAV if needed
        dest_path, import_msg = import_audio_file(path, dest_dir, start_index + i)
        
        if dest_path:
            # Load the WAV file
            ok, load_msg = load_sample(inst, dest_path)
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
    logger.debug(f"import_folder_samples: scanning {folder}, extensions={extensions}")
    
    if recursive:
        for root, dirs, files in os.walk(folder):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in extensions:
                    audio_files.append(os.path.join(root, f))
                    logger.debug(f"  Found: {f} (ext={ext})")
    else:
        for f in os.listdir(folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in extensions:
                audio_files.append(os.path.join(folder, f))
                logger.debug(f"  Found: {f} (ext={ext})")
    
    logger.info(f"import_folder_samples: found {len(audio_files)} files")
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
            f.write("; SONG DATA - Generated by POKEY VQ Tracker\n")
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
