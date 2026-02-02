"""POKEY VQ Tracker - VQ Conversion Module

Handles conversion of instruments to VQ format using pokey_vq.

Supports two modes:
1. Direct import (bundled with PyInstaller or development mode)
2. Subprocess fallback (external vq_converter.exe or system Python)

The direct import mode is preferred as it:
- Works in PyInstaller bundles without external Python
- Runs faster (no subprocess overhead)
- Has better error handling
"""
import os
import sys
import json
import shutil
import subprocess
import threading
import queue
import logging
import io
from contextlib import redirect_stdout, redirect_stderr
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

import runtime  # Bundle/dev mode detection
from constants import (VQ_RATE_DEFAULT, VQ_VECTOR_DEFAULT, VQ_SMOOTHNESS_DEFAULT,
                       VQ_VECTOR_SIZES)

# Valid vector sizes (must be even for ASM optimization)
VALID_VECTOR_SIZES = {2, 4, 8, 16}

# ============================================================================
# POKEY_VQ IMPORT HANDLING
# ============================================================================
# Try to import pokey_vq at module load time. This allows:
# - Bundled mode: PyInstaller includes vq_converter in bundle
# - Dev mode: vq_converter folder alongside tracker
# - Installed mode: pip install pokey_vq

POKEY_VQ_AVAILABLE = False
_import_error = None

def _setup_vq_converter_path():
    """Add vq_converter to sys.path if it exists."""
    candidates = [
        # Bundled with PyInstaller (inside temp extraction)
        os.path.join(runtime.get_bundle_dir(), "vq_converter"),
        # Alongside executable/script
        os.path.join(runtime.get_app_dir(), "vq_converter"),
        # Development mode (same folder)
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "vq_converter"),
    ]
    
    for path in candidates:
        if os.path.isdir(path) and os.path.isdir(os.path.join(path, "pokey_vq")):
            if path not in sys.path:
                sys.path.insert(0, path)
            return path
    return None

def _try_import_pokey_vq():
    """Try to import pokey_vq and return availability status."""
    global POKEY_VQ_AVAILABLE, _import_error
    
    # Setup path first
    _setup_vq_converter_path()
    
    try:
        from pokey_vq.cli.builder import PokeyVQBuilder
        POKEY_VQ_AVAILABLE = True
        _import_error = None
        return True
    except ImportError as e:
        _import_error = str(e)
        POKEY_VQ_AVAILABLE = False
        return False
    except Exception as e:
        _import_error = f"Unexpected: {e}"
        POKEY_VQ_AVAILABLE = False
        return False

# Try import at module load
_try_import_pokey_vq()


# ============================================================================
# ARGS DATACLASS (mimics argparse namespace for PokeyVQBuilder)
# ============================================================================
@dataclass
class VQArgs:
    """Arguments object mimicking argparse namespace for PokeyVQBuilder.
    
    This provides all the attributes that PokeyVQBuilder expects from argparse.
    """
    # Input/Output
    input: List[str] = field(default_factory=list)
    input_folder: List[str] = field(default_factory=list)
    output: str = ""
    
    # Player mode
    player: str = "vq_multi_channel"
    
    # Audio settings
    rate: int = 5278
    channels: int = 1
    
    # Optimization
    optimize: str = "speed"  # 'speed' or 'size'
    fast: bool = False       # Legacy alias for speed mode
    fast_cpu: bool = False   # Legacy alias
    
    # Player generation
    no_player: bool = True   # CRITICAL: Skip assembly, data only!
    
    # Quality settings
    quality: float = 50.0
    smoothness: float = 0.0
    codebook: int = 256
    iterations: int = 50
    
    # Vector settings
    min_vector: int = 8
    max_vector: int = 8
    window_size: int = 255
    
    # Processing options
    lbg: bool = False
    voltage: str = "off"
    constrained: bool = False
    enhance: str = "on"
    no_enhance: bool = False
    
    # Output options
    wav: str = "off"  # Don't generate preview WAV
    show_cpu_use: str = "off"
    debug: bool = False
    
    # Set by builder internally
    algo: str = "fixed"
    tracker: bool = True
    pitch: bool = False
    raw: bool = False


# ============================================================================
# VQ SETTINGS AND RESULT DATACLASSES
# ============================================================================
@dataclass
class VQSettings:
    """VQ conversion settings from UI."""
    rate: int = VQ_RATE_DEFAULT
    vector_size: int = VQ_VECTOR_DEFAULT
    smoothness: int = VQ_SMOOTHNESS_DEFAULT
    enhance: bool = True
    optimize_speed: bool = True  # True=speed (full bytes), False=size (nibble-packed)
    
    def __post_init__(self):
        """Validate and fix vector_size if necessary."""
        if self.vector_size not in VALID_VECTOR_SIZES:
            if self.vector_size < 2:
                self.vector_size = 2
            elif self.vector_size > 16:
                self.vector_size = 16
            else:
                for valid in sorted(VALID_VECTOR_SIZES, reverse=True):
                    if self.vector_size >= valid:
                        self.vector_size = valid
                        break


@dataclass
class VQResult:
    """Result of VQ conversion."""
    success: bool = False
    output_dir: Optional[str] = None
    total_size: int = 0
    converted_wavs: List[str] = field(default_factory=list)
    error_message: str = ""


# ============================================================================
# VQ STATE MANAGER
# ============================================================================
class VQState:
    """State manager for VQ conversion."""
    
    def __init__(self):
        self.settings = VQSettings()
        self.converted = False
        self.result: Optional[VQResult] = None
        self.use_converted = False
        self.output_dir: Optional[str] = None
        self._process: Optional[subprocess.Popen] = None
        self._is_converting = False
        
        # Thread-safe queue for output lines
        self.output_queue: queue.Queue = queue.Queue()
        self.completion_result: Optional[VQResult] = None
        self.conversion_complete = False
    
    @property
    def is_valid(self) -> bool:
        return self.converted
    
    @property
    def rate(self) -> int:
        return self.settings.rate
    
    @property
    def vector_size(self) -> int:
        return self.settings.vector_size
    
    @property
    def smoothness(self) -> int:
        return self.settings.smoothness
    
    def invalidate(self):
        """Mark conversion as invalid."""
        self.converted = False
        self.result = None
        self.use_converted = False
    
    def is_converting(self) -> bool:
        return self._is_converting
    
    def cleanup(self):
        self.invalidate()
    
    def cancel_conversion(self):
        if self._process:
            try:
                self._process.terminate()
            except:
                pass
        self._is_converting = False
    
    def get_pending_output(self) -> List[str]:
        """Get all pending output lines (call from main thread)."""
        lines = []
        while True:
            try:
                line = self.output_queue.get_nowait()
                lines.append(line)
            except queue.Empty:
                break
        return lines
    
    def check_completion(self) -> Optional[VQResult]:
        """Check if conversion completed (call from main thread)."""
        if self.conversion_complete:
            self.conversion_complete = False
            return self.completion_result
        return None


# ============================================================================
# VQ CONVERTER
# ============================================================================
class VQConverter:
    """Handles VQ conversion using pokey_vq.
    
    Supports two modes:
    1. Direct import (preferred) - runs in-process, works in PyInstaller bundle
    2. Subprocess fallback - uses external Python or vq_converter.exe
    """
    
    def __init__(self, vq_state: VQState):
        self.vq_state = vq_state
        self.logger = logging.getLogger("tracker.vq_convert")
        self._vq_converter_path = None
    
    def _queue_output(self, text: str):
        """Queue output text for main thread."""
        self.vq_state.output_queue.put(text)
    
    def _generate_output_dirname(self, num_files: int) -> str:
        """Generate output directory name based on settings."""
        settings = self.vq_state.settings
        parts = [
            f"multi_{num_files}",
            f"r{settings.rate}",
            f"v{settings.vector_size}",
            f"s{settings.smoothness}",
        ]
        if settings.enhance:
            parts.append("enh")
        return "-".join(parts)
    
    def convert(self, input_files: List[str]):
        """Start conversion in background thread."""
        self.logger.debug(f"convert: {len(input_files)} files")
        for f in input_files[:5]:
            self.logger.debug(f"  - {f}")
        if len(input_files) > 5:
            self.logger.debug(f"  ... and {len(input_files) - 5} more")
        
        # Reset state
        self.vq_state.conversion_complete = False
        self.vq_state.completion_result = None
        
        # Clear output queue
        while not self.vq_state.output_queue.empty():
            try:
                self.vq_state.output_queue.get_nowait()
            except queue.Empty:
                break
        
        # Validate inputs
        if not input_files:
            result = VQResult(success=False, error_message="No input files specified")
            self.vq_state.completion_result = result
            self.vq_state.conversion_complete = True
            return
        
        missing = [f for f in input_files if not os.path.exists(f)]
        if missing:
            result = VQResult(
                success=False, 
                error_message=f"Missing: {', '.join(os.path.basename(f) for f in missing[:3])}"
            )
            self.vq_state.completion_result = result
            self.vq_state.conversion_complete = True
            return
        
        # Create output directory
        app_dir = runtime.get_app_dir()
        output_dirname = self._generate_output_dirname(len(input_files))
        asm_output_dir = os.path.join(app_dir, ".tmp", "vq_output")
        output_name = os.path.join(asm_output_dir, output_dirname)
        
        os.makedirs(asm_output_dir, exist_ok=True)
        
        self.logger.debug(f"Output dir: {asm_output_dir}")
        self.logger.debug(f"Output name: {output_name}")
        self.logger.info(f"POKEY_VQ_AVAILABLE: {POKEY_VQ_AVAILABLE}")
        
        # Choose conversion method
        if POKEY_VQ_AVAILABLE:
            self.logger.info("Using direct import for VQ conversion")
            thread = threading.Thread(
                target=self._run_direct_conversion,
                args=(input_files, asm_output_dir, output_name),
                daemon=True
            )
        else:
            self.logger.info(f"Using subprocess (import error: {_import_error})")
            thread = threading.Thread(
                target=self._run_subprocess_conversion,
                args=(input_files, asm_output_dir, output_name),
                daemon=True
            )
        
        self.vq_state._is_converting = True
        thread.start()
    
    def _run_direct_conversion(self, input_files: List[str], asm_output_dir: str, output_name: str):
        """Run conversion using direct Python import (in-process)."""
        result = VQResult()
        
        try:
            from pokey_vq.cli.builder import PokeyVQBuilder
            
            settings = self.vq_state.settings
            
            self._queue_output(f"Starting conversion of {len(input_files)} file(s)...\n")
            self._queue_output(f"Mode: Direct import (bundled)\n")
            self._queue_output(f"Output: {asm_output_dir}\n")
            self._queue_output(f"Settings: rate={settings.rate}, "
                               f"vec={settings.vector_size}, "
                               f"smooth={settings.smoothness}, "
                               f"enhance={'on' if settings.enhance else 'off'}, "
                               f"optimize={'speed' if settings.optimize_speed else 'size'}\n")
            self._queue_output("-" * 60 + "\n")
            
            # Build args object with all required attributes
            args = VQArgs(
                input=input_files,
                output=output_name,
                player="vq_multi_channel",
                rate=settings.rate,
                channels=1,
                optimize="speed" if settings.optimize_speed else "size",
                no_player=True,  # CRITICAL: Data only, no assembly!
                quality=50.0,
                smoothness=float(settings.smoothness),
                codebook=256,
                iterations=50,
                min_vector=settings.vector_size,
                max_vector=settings.vector_size,
                lbg=False,
                voltage="off",
                enhance="on" if settings.enhance else "off",
                wav="off",  # Don't generate preview WAV
            )
            
            # Capture stdout/stderr from builder
            output_buffer = io.StringIO()
            
            try:
                with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                    builder = PokeyVQBuilder(args)
                    return_code = builder.run()
            except SystemExit as e:
                # builder.py calls sys.exit(1) on errors - catch it!
                self._queue_output(f"\nBuilder exited with code: {e.code}\n")
                result.success = False
                result.error_message = f"Builder error (exit code {e.code})"
                return_code = e.code if isinstance(e.code, int) else 1
            except Exception as e:
                self._queue_output(f"\nBuilder error: {e}\n")
                import traceback
                self._queue_output(traceback.format_exc())
                result.success = False
                result.error_message = str(e)
                return_code = 1
            finally:
                captured = output_buffer.getvalue()
                if captured:
                    for line in captured.split('\n'):
                        if line:  # Skip empty lines
                            self._queue_output(line + '\n')
            
            if return_code != 0:
                result.success = False
                result.error_message = f"Builder returned code {return_code}"
                self._queue_output(f"\nERROR: {result.error_message}\n")
            else:
                # Check for required ASM files
                required_files = ["VQ_BLOB.asm", "VQ_INDICES.asm", "SAMPLE_DIR.asm"]
                found_files = [f for f in required_files 
                              if os.path.exists(os.path.join(asm_output_dir, f))]
                
                if len(found_files) >= 2:
                    result.output_dir = asm_output_dir
                    result = self._parse_results(asm_output_dir, result)
                    result.success = True
                    self.vq_state.output_dir = result.output_dir
                    self._queue_output("\n" + "=" * 60 + "\n")
                    self._queue_output(f"SUCCESS: Conversion complete!\n")
                    self._queue_output(f"Output: {result.output_dir}\n")
                    self._queue_output(f"Total size: {result.total_size:,} bytes\n")
                    self._queue_output(f"Converted WAVs: {len(result.converted_wavs)}\n")
                else:
                    result.success = False
                    result.error_message = f"Missing ASM files in {asm_output_dir}"
                    self._queue_output(f"\nWARNING: {result.error_message}\n")
                    self._queue_output(f"Required: {required_files}\n")
                    self._queue_output(f"Found: {found_files}\n")
                    self._list_directory(asm_output_dir)
        
        except Exception as e:
            result.success = False
            result.error_message = str(e)
            self._queue_output(f"\nERROR: {result.error_message}\n")
            import traceback
            self._queue_output(traceback.format_exc())
        
        finally:
            self.vq_state._is_converting = False
            
            if result.success:
                self.vq_state.converted = True
                self.vq_state.result = result
            
            self.vq_state.completion_result = result
            self.vq_state.conversion_complete = True
    
    def _run_subprocess_conversion(self, input_files: List[str], asm_output_dir: str, output_name: str):
        """Run conversion using subprocess (fallback mode)."""
        result = VQResult()
        
        try:
            # Find vq_converter
            vq_converter_path = self._find_vq_converter()
            if not vq_converter_path:
                result.success = False
                result.error_message = "vq_converter folder not found."
                self._queue_output(f"ERROR: {result.error_message}\n")
                self.vq_state.completion_result = result
                self.vq_state.conversion_complete = True
                return
            
            # Build command
            cmd = self._build_subprocess_command(input_files, output_name, vq_converter_path)
            if not cmd:
                result.success = False
                result.error_message = ("CONVERT requires Python with pokey_vq dependencies.\n"
                                       "Install: pip install numpy scipy soundfile")
                self._queue_output(f"ERROR: {result.error_message}\n")
                self.vq_state.completion_result = result
                self.vq_state.conversion_complete = True
                return
            
            settings = self.vq_state.settings
            self._queue_output(f"Starting conversion of {len(input_files)} file(s)...\n")
            self._queue_output(f"Mode: Subprocess\n")
            self._queue_output(f"Command: {cmd[0]}\n")
            self._queue_output(f"Output: {asm_output_dir}\n")
            self._queue_output(f"Settings: rate={settings.rate}, "
                               f"vec={settings.vector_size}, "
                               f"smooth={settings.smoothness}, "
                               f"enhance={'on' if settings.enhance else 'off'}\n")
            self._queue_output("-" * 60 + "\n")
            
            # Set up environment
            env = os.environ.copy()
            env["PYTHONPATH"] = vq_converter_path + os.pathsep + env.get("PYTHONPATH", "")
            
            # Platform-specific process creation
            startupinfo = None
            creationflags = 0
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW
            
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                    cwd=vq_converter_path,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
            except FileNotFoundError as e:
                self._queue_output(f"\nERROR: Command not found: {cmd[0]}\n")
                result.success = False
                result.error_message = f"Command not found: {cmd[0]}"
                self.vq_state._is_converting = False  # Reset flag!
                self.vq_state.completion_result = result
                self.vq_state.conversion_complete = True
                return
            
            self.vq_state._process = process
            self._queue_output(f"Process started (PID: {process.pid})\n")
            
            # Read output with timeout
            import time
            start_time = time.time()
            TIMEOUT_SECONDS = 300
            
            while True:
                elapsed = time.time() - start_time
                if elapsed > TIMEOUT_SECONDS:
                    self._queue_output(f"\nERROR: Timeout after {TIMEOUT_SECONDS}s\n")
                    process.kill()
                    break
                
                poll_result = process.poll()
                if poll_result is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        self._queue_output(remaining)
                    break
                
                line = process.stdout.readline()
                if line:
                    self._queue_output(line)
            
            if process.poll() is None:
                process.wait(timeout=5)
            
            if process.returncode == 0:
                required_files = ["VQ_BLOB.asm", "VQ_INDICES.asm", "SAMPLE_DIR.asm"]
                found_files = [f for f in required_files 
                              if os.path.exists(os.path.join(asm_output_dir, f))]
                
                if len(found_files) >= 2:
                    result.output_dir = asm_output_dir
                    result = self._parse_results(asm_output_dir, result)
                    result.success = True
                    self.vq_state.output_dir = result.output_dir
                    self._queue_output("\n" + "=" * 60 + "\n")
                    self._queue_output(f"SUCCESS: Conversion complete!\n")
                else:
                    result.success = False
                    result.error_message = "Missing ASM files"
                    self._list_directory(asm_output_dir)
            else:
                result.success = False
                result.error_message = f"Process exited with code {process.returncode}"
                self._queue_output(f"\nERROR: {result.error_message}\n")
        
        except Exception as e:
            result.success = False
            result.error_message = str(e)
            self._queue_output(f"\nERROR: {result.error_message}\n")
            import traceback
            self._queue_output(traceback.format_exc())
        
        finally:
            self.vq_state._process = None
            self.vq_state._is_converting = False
            
            if result.success:
                self.vq_state.converted = True
                self.vq_state.result = result
            
            self.vq_state.completion_result = result
            self.vq_state.conversion_complete = True
    
    def _find_vq_converter(self) -> Optional[str]:
        """Find vq_converter folder path."""
        candidates = [
            os.path.join(runtime.get_bundle_dir(), "vq_converter"),
            os.path.join(runtime.get_app_dir(), "vq_converter"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "vq_converter"),
        ]
        
        for path in candidates:
            if os.path.isdir(path) and os.path.isdir(os.path.join(path, "pokey_vq")):
                return path
        
        return None
    
    def _build_subprocess_command(self, input_files: List[str], output_name: str, 
                                   vq_converter_path: str) -> List[str]:
        """Build subprocess command."""
        settings = self.vq_state.settings
        optimize_mode = "speed" if settings.optimize_speed else "size"
        
        # Find Python
        python_cmd = None
        for name in ["python3", "python"]:
            path = shutil.which(name)
            if path:
                python_cmd = path
                break
        
        if not python_cmd:
            return []
        
        cmd = [python_cmd, "-m", "pokey_vq.cli"]
        
        cmd.extend([
            *input_files,
            "-p", "vq_multi_channel",
            "-r", str(settings.rate),
            "--channels", "1",
            "-miv", str(settings.vector_size),
            "-mav", str(settings.vector_size),
            "-q", "50",
            "-s", str(settings.smoothness),
            "-e", "on" if settings.enhance else "off",
            "--optimize", optimize_mode,
            "--no-player",  # CRITICAL: Data only!
            "--wav", "off",  # No preview WAV
            "-o", output_name
        ])
        
        return cmd
    
    def _list_directory(self, path: str):
        """List directory contents for debugging."""
        self._queue_output(f"\nContents of {path}:\n")
        try:
            for item in sorted(os.listdir(path)):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    self._queue_output(f"  [DIR] {item}/\n")
                else:
                    size = os.path.getsize(item_path)
                    self._queue_output(f"  {item} ({size:,} bytes)\n")
        except Exception as e:
            self._queue_output(f"  Error listing: {e}\n")
    
    def _parse_results(self, output_dir: str, result: VQResult) -> VQResult:
        """Parse conversion results from output directory."""
        total_size = 0
        converted_wavs = []
        
        self._queue_output(f"\nParsing results from: {output_dir}\n")
        
        for filename in os.listdir(output_dir):
            filepath = os.path.join(output_dir, filename)
            if os.path.isfile(filepath):
                total_size += os.path.getsize(filepath)
        
        # Check for conversion_info.json (optional, for metadata)
        info_path = os.path.join(output_dir, "conversion_info.json")
        if os.path.isfile(info_path):
            try:
                with open(info_path, 'r') as f:
                    info = json.load(f)
                    # Note: builder.py uses 'samples' key, not 'converted_files'
                    if 'samples' in info:
                        # Extract instrument_file paths from samples array
                        for sample_info in info['samples']:
                            if 'instrument_file' in sample_info:
                                wav_path = sample_info['instrument_file']
                                if os.path.exists(wav_path):
                                    converted_wavs.append(wav_path)
                        self._queue_output(f"  Found {len(converted_wavs)} WAVs from JSON\n")
            except Exception as e:
                self._queue_output(f"Warning: Could not parse JSON: {e}\n")
        
        # If no WAVs from JSON, check instruments folder directly
        if not converted_wavs:
            instruments_dir = os.path.join(output_dir, "instruments")
            if os.path.isdir(instruments_dir):
                wav_files = sorted([f for f in os.listdir(instruments_dir) if f.endswith('.wav')])
                self._queue_output(f"  Scanning instruments folder: {len(wav_files)} WAV files\n")
                for wav in wav_files:
                    wav_path = os.path.join(instruments_dir, wav)
                    converted_wavs.append(wav_path)
                    total_size += os.path.getsize(wav_path)
                    self._queue_output(f"    {wav} -> {wav_path}\n")
            else:
                self._queue_output(f"  No instruments folder found at: {instruments_dir}\n")
        
        self._queue_output(f"  Total converted WAVs: {len(converted_wavs)}\n")
        
        result.total_size = total_size
        result.converted_wavs = converted_wavs
        return result


def format_size(size_bytes: int) -> str:
    """Format byte size for display."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def get_pokey_vq_status() -> tuple:
    """Get pokey_vq availability status for diagnostics.
    
    Returns:
        (available: bool, error: str or None)
    """
    return POKEY_VQ_AVAILABLE, _import_error
