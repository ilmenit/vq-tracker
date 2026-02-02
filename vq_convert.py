"""POKEY VQ Tracker - VQ Conversion Module

Handles conversion of instruments to VQ format.

Supports two modes:
1. Direct import (bundled or pip-installed pokey_vq)
2. Subprocess fallback (external vq_converter folder)
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
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field

import runtime  # Bundle/dev mode detection
from constants import (VQ_RATE_DEFAULT, VQ_VECTOR_DEFAULT, VQ_SMOOTHNESS_DEFAULT,
                       VQ_VECTOR_SIZES)

# Valid vector sizes (must be powers of 2 for ASM optimization)
VALID_VECTOR_SIZES = {2, 4, 8, 16}

# Check if pokey_vq can be imported directly
POKEY_VQ_AVAILABLE = False
_import_error = None

def _try_import_pokey_vq():
    """Try to import pokey_vq and return availability status."""
    global POKEY_VQ_AVAILABLE, _import_error
    try:
        # First, try to add vq_converter to path if it exists
        vq_paths = [
            os.path.join(runtime.get_app_dir(), "vq_converter"),
            os.path.join(os.path.dirname(__file__), "vq_converter"),
        ]
        for vq_path in vq_paths:
            if os.path.isdir(vq_path) and vq_path not in sys.path:
                sys.path.insert(0, vq_path)
        
        # Now try to import
        from pokey_vq.cli.builder import PokeyVQBuilder
        POKEY_VQ_AVAILABLE = True
        return True
    except ImportError as e:
        _import_error = str(e)
        POKEY_VQ_AVAILABLE = False
        return False

# Try import at module load time
_try_import_pokey_vq()


@dataclass
class VQArgs:
    """Arguments object mimicking argparse for PokeyVQBuilder."""
    input: List[str] = field(default_factory=list)
    input_folder: List[str] = field(default_factory=list)
    output: str = ""
    player: str = "vq_multi_channel"
    rate: int = 5278
    channels: int = 1
    optimize: str = "speed"  # 'speed' or 'size'
    no_player: bool = False
    quality: float = 50.0
    smoothness: float = 50.0
    codebook: int = 256
    iterations: int = 50
    min_vector: int = 8
    max_vector: int = 8
    lbg: bool = False
    voltage: str = "off"
    enhance: str = "on"
    # Set by builder
    algo: str = "fixed"
    tracker: bool = True
    pitch: bool = False


@dataclass
class VQSettings:
    """VQ conversion settings."""
    rate: int = VQ_RATE_DEFAULT
    vector_size: int = VQ_VECTOR_DEFAULT
    smoothness: int = VQ_SMOOTHNESS_DEFAULT
    enhance: bool = True
    optimize_speed: bool = True  # True=speed (full bytes), False=size (nibble-packed)
    
    def __post_init__(self):
        """Validate and fix vector_size if necessary."""
        if self.vector_size not in VALID_VECTOR_SIZES:
            # Find nearest valid size
            if self.vector_size < 2:
                self.vector_size = 2
            elif self.vector_size > 16:
                self.vector_size = 16
            else:
                # Round down to nearest power of 2
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
        
        # Thread-safe queue for output lines (to be processed by main thread)
        self.output_queue: queue.Queue = queue.Queue()
        # Completion result (set by thread, read by main)
        self.completion_result: Optional[VQResult] = None
        self.conversion_complete = False
    
    # Convenience properties for easier access
    @property
    def is_valid(self) -> bool:
        """Alias for converted - check if VQ conversion is valid."""
        return self.converted
    
    @property
    def rate(self) -> int:
        """Get current sample rate setting."""
        return self.settings.rate
    
    @property
    def vector_size(self) -> int:
        """Get current vector size setting."""
        return self.settings.vector_size
    
    @property
    def smoothness(self) -> int:
        """Get current smoothness setting."""
        return self.settings.smoothness
    
    def invalidate(self):
        """Mark conversion as invalid (needs re-conversion)."""
        self.converted = False
        self.result = None
        self.use_converted = False
    
    def is_converting(self) -> bool:
        """Check if conversion is in progress."""
        return self._is_converting
    
    def cleanup(self):
        """Clean up - called on app exit."""
        self.invalidate()
    
    def cancel_conversion(self):
        """Cancel ongoing conversion."""
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


class VQConverter:
    """Handles VQ conversion using pokey_vq.
    
    Supports two modes:
    1. Direct import (if pokey_vq is available as Python module)
    2. Subprocess fallback (external Python or vq_converter.exe)
    """
    
    def __init__(self, vq_state: VQState):
        self.vq_state = vq_state
        self.logger = logging.getLogger("tracker.vq_convert")
        self._vq_converter_path = None
    
    def find_vq_converter(self) -> Optional[str]:
        """Find the vq_converter folder path."""
        # Get application directory (different in bundled vs dev mode)
        if runtime.is_bundled():
            bundle_dir = runtime.get_bundle_dir()
            app_dir = runtime.get_app_dir()
            candidates = [
                os.path.join(bundle_dir, "vq_converter"),  # Inside bundle
                os.path.join(app_dir, "vq_converter"),     # Alongside exe
            ]
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            candidates = [
                os.path.join(script_dir, "vq_converter"),
                os.path.join(os.path.dirname(script_dir), "vq_converter"),
            ]
        
        self.logger.debug(f"find_vq_converter: bundle_dir={runtime.get_bundle_dir()}, app_dir={runtime.get_app_dir()}")
        
        for path in candidates:
            self.logger.debug(f"  Checking: {path}")
            if os.path.isdir(path):
                # Verify it has pokey_vq module
                if os.path.isdir(os.path.join(path, "pokey_vq")):
                    self.logger.debug(f"  Found vq_converter at: {path}")
                    return path
        
        self.logger.warning("vq_converter not found in any candidate path")
        return None
    
    def _queue_output(self, text: str):
        """Queue output text for main thread to process."""
        self.vq_state.output_queue.put(text)
    
    def _generate_output_dirname(self, num_files: int) -> str:
        """Generate output directory name based on settings."""
        settings = self.vq_state.settings
        
        # Pattern: multi_{num}-r{rate}-v{vec}-s{smooth}[-enh]
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
        
        # Check all files exist
        missing = [f for f in input_files if not os.path.exists(f)]
        if missing:
            result = VQResult(
                success=False, 
                error_message=f"Missing files: {', '.join(os.path.basename(f) for f in missing[:3])}"
            )
            self.vq_state.completion_result = result
            self.vq_state.conversion_complete = True
            return
        
        # Create output directory in .tmp folder
        app_dir = runtime.get_app_dir()
        output_dirname = self._generate_output_dirname(len(input_files))
        asm_output_dir = os.path.join(app_dir, ".tmp", "vq_output")
        output_name = os.path.join(asm_output_dir, output_dirname)  # XEX path
        
        # Ensure output directory exists
        os.makedirs(asm_output_dir, exist_ok=True)
        
        self.logger.debug(f"Output dir: {asm_output_dir}")
        self.logger.debug(f"Output name: {output_name}")
        
        # Choose conversion method
        if POKEY_VQ_AVAILABLE:
            self.logger.info("Using direct import for VQ conversion")
            thread = threading.Thread(
                target=self._run_direct_conversion,
                args=(input_files, asm_output_dir, output_name),
                daemon=True
            )
        else:
            self.logger.info(f"Using subprocess for VQ conversion (import error: {_import_error})")
            thread = threading.Thread(
                target=self._run_subprocess_conversion,
                args=(input_files, asm_output_dir, output_name),
                daemon=True
            )
        
        self.vq_state._is_converting = True
        thread.start()
    
    def _run_direct_conversion(self, input_files: List[str], asm_output_dir: str, output_name: str):
        """Run conversion using direct Python import (called in thread)."""
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
                               f"enhance={'on' if settings.enhance else 'off'}\n")
            self._queue_output("-" * 60 + "\n")
            
            # Build args object
            args = VQArgs(
                input=input_files,
                output=output_name,
                player="vq_multi_channel",
                rate=settings.rate,
                channels=1,
                optimize="speed" if settings.optimize_speed else "size",
                no_player=False,
                quality=50.0,
                smoothness=float(settings.smoothness),
                codebook=256,
                iterations=50,
                min_vector=settings.vector_size,
                max_vector=settings.vector_size,
                lbg=False,
                voltage="off",
                enhance="on" if settings.enhance else "off",
            )
            
            # Capture stdout/stderr
            output_buffer = io.StringIO()
            
            try:
                with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                    builder = PokeyVQBuilder(args)
                    builder.run()
            except Exception as e:
                self._queue_output(f"\nBuilder error: {e}\n")
                raise
            finally:
                # Get captured output
                captured = output_buffer.getvalue()
                if captured:
                    for line in captured.split('\n'):
                        self._queue_output(line + '\n')
            
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
        """Run conversion using subprocess (called in thread)."""
        result = VQResult()
        
        try:
            # Find vq_converter
            vq_converter_path = self.find_vq_converter()
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
                result.error_message = ("CONVERT requires vq_converter.exe OR Python with dependencies.\n"
                                       "Options:\n"
                                       "1. Place vq_converter.exe in vq_converter\\ folder, OR\n"
                                       "2. Install Python 3.8+ with: pip install numpy scipy soundfile")
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
            
            # Start process
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
                self.vq_state.completion_result = result
                self.vq_state.conversion_complete = True
                return
            
            self.vq_state._process = process
            self._queue_output(f"Process started (PID: {process.pid})\n")
            
            # Read output with timeout handling
            import time
            start_time = time.time()
            TIMEOUT_SECONDS = 300
            first_line_timeout = 10
            got_first_line = False
            
            while True:
                elapsed = time.time() - start_time
                if elapsed > TIMEOUT_SECONDS:
                    self._queue_output(f"\nERROR: Conversion timed out after {TIMEOUT_SECONDS}s\n")
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
                    got_first_line = True
                    self._queue_output(line)
                elif not got_first_line and elapsed > first_line_timeout:
                    self._queue_output(f"\nWARNING: No output after {first_line_timeout}s\n")
                    self._queue_output("This may indicate missing dependencies.\n")
                    first_line_timeout = float('inf')
            
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
                    self._queue_output(f"Output: {result.output_dir}\n")
                    self._queue_output(f"Total size: {result.total_size:,} bytes\n")
                else:
                    result.success = False
                    result.error_message = f"Missing ASM files"
                    self._queue_output(f"\nWARNING: {result.error_message}\n")
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
    
    def _build_subprocess_command(self, input_files: List[str], output_name: str, 
                                   vq_converter_path: str) -> List[str]:
        """Build subprocess command for vq_converter."""
        settings = self.vq_state.settings
        optimize_mode = "speed" if settings.optimize_speed else "size"
        
        # Check for standalone executable first
        if sys.platform == 'win32':
            exe_path = os.path.join(vq_converter_path, "vq_converter.exe")
            if os.path.isfile(exe_path):
                cmd = [exe_path]
                self.logger.info(f"Using standalone: {exe_path}")
            else:
                # Fall back to Python
                python_cmd = self._find_system_python()
                if not python_cmd:
                    return []
                cmd = [python_cmd, "-m", "pokey_vq.cli"]
        else:
            # Linux/macOS - check for executable
            exe_found = False
            for exe_name in ["vq_converter", "vq_converter.bin"]:
                exe_path = os.path.join(vq_converter_path, exe_name)
                if os.path.isfile(exe_path) and os.access(exe_path, os.X_OK):
                    cmd = [exe_path]
                    exe_found = True
                    break
            
            if not exe_found:
                python_cmd = self._find_system_python()
                if not python_cmd:
                    return []
                cmd = [python_cmd, "-m", "pokey_vq.cli"]
        
        # Add arguments
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
            "-o", output_name
        ])
        
        return cmd
    
    def _find_system_python(self) -> Optional[str]:
        """Find system Python executable."""
        for name in ["python3", "python"]:
            path = shutil.which(name)
            if path:
                self.logger.debug(f"Found system Python: {path}")
                return path
        return None
    
    def _list_directory(self, path: str):
        """List directory contents for debugging."""
        self._queue_output(f"\nContents of {path}:\n")
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    self._queue_output(f"  [DIR] {item}/\n")
                else:
                    self._queue_output(f"  {item}\n")
        except:
            pass
    
    def _parse_results(self, output_dir: str, result: VQResult) -> VQResult:
        """Parse conversion results from output directory."""
        # Calculate total size of ASM files
        total_size = 0
        converted_wavs = []
        
        for filename in os.listdir(output_dir):
            filepath = os.path.join(output_dir, filename)
            if os.path.isfile(filepath):
                total_size += os.path.getsize(filepath)
        
        # Look for conversion_info.json for more details
        info_path = os.path.join(output_dir, "conversion_info.json")
        if os.path.isfile(info_path):
            try:
                with open(info_path, 'r') as f:
                    info = json.load(f)
                    if 'converted_files' in info:
                        converted_wavs = info['converted_files']
                    if 'total_size' in info:
                        total_size = info['total_size']
            except Exception as e:
                self._queue_output(f"Warning: Could not parse JSON: {e}\n")
        
        # Also check instruments folder
        instruments_dir = os.path.join(output_dir, "instruments")
        if os.path.isdir(instruments_dir):
            for wav in os.listdir(instruments_dir):
                if wav.endswith('.wav'):
                    converted_wavs.append(wav)
                    total_size += os.path.getsize(os.path.join(instruments_dir, wav))
        
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
