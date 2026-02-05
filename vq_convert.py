"""POKEY VQ Tracker - VQ Conversion Module

Converts instruments to VQ format using pokey_vq (part of this project).
pokey_vq is always imported directly - never called as a subprocess.

When running from source: vq_converter/ must sit alongside main.py
When running from PyInstaller bundle: pokey_vq is frozen into the executable
"""
import os
import sys
import json
import threading
import queue
import logging
import io
from contextlib import redirect_stdout, redirect_stderr
from typing import Optional, List
from dataclasses import dataclass, field

import runtime
from constants import (VQ_RATE_DEFAULT, VQ_VECTOR_DEFAULT, VQ_SMOOTHNESS_DEFAULT,
                       VQ_VECTOR_SIZES)

# Valid vector sizes (must be even for ASM nibble-packing)
VALID_VECTOR_SIZES = {2, 4, 8, 16}

# ============================================================================
# POKEY_VQ IMPORT
# ============================================================================
POKEY_VQ_AVAILABLE = False
_import_error = None

def _setup_pokey_vq():
    """Make pokey_vq importable, then import it.
    
    When running from source, vq_converter/ contains pokey_vq as a package.
    We add vq_converter/ to sys.path so 'from pokey_vq...' works.
    
    When running from PyInstaller bundle, pokey_vq is already frozen -
    no path setup needed.
    """
    global POKEY_VQ_AVAILABLE, _import_error
    logger = logging.getLogger("vq_convert")
    
    frozen = getattr(sys, 'frozen', False)
    
    # Add vq_converter/ to sys.path when running from source
    if not frozen:
        vq_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vq_converter")
        if os.path.isdir(os.path.join(vq_dir, "pokey_vq")):
            if vq_dir not in sys.path:
                sys.path.insert(0, vq_dir)
                logger.info(f"Added to sys.path: {vq_dir}")
        else:
            logger.warning(f"vq_converter/pokey_vq not found at: {vq_dir}")
    
    try:
        from pokey_vq.cli.builder import PokeyVQBuilder  # noqa: F401
        POKEY_VQ_AVAILABLE = True
        _import_error = None
        logger.info("pokey_vq loaded OK")
    except Exception as e:
        import traceback
        POKEY_VQ_AVAILABLE = False
        _import_error = str(e)
        logger.error(f"pokey_vq import failed: {e}")
        logger.error(f"  Frozen: {frozen}")
        if frozen:
            logger.error(f"  _MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")
        # Full traceback shows the complete import chain that failed
        logger.debug(f"  Full traceback:\n{traceback.format_exc()}")

_setup_pokey_vq()


# ============================================================================
# ARGS DATACLASS (mimics argparse namespace for PokeyVQBuilder)
# ============================================================================
@dataclass
class VQArgs:
    """Arguments object matching what PokeyVQBuilder expects from argparse."""
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
    fast: bool = False
    fast_cpu: bool = False
    
    # Player generation
    no_player: bool = True  # Data only, no assembly player
    
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
    wav: str = "off"
    show_cpu_use: str = "off"
    debug: bool = False
    
    # Set by builder internally
    algo: str = "fixed"
    tracker: bool = True
    pitch: bool = False
    raw: bool = False


# ============================================================================
# VQ SETTINGS AND RESULT
# ============================================================================
@dataclass
class VQSettings:
    """VQ conversion settings from UI."""
    rate: int = VQ_RATE_DEFAULT
    vector_size: int = VQ_VECTOR_DEFAULT
    smoothness: int = VQ_SMOOTHNESS_DEFAULT
    enhance: bool = True
    optimize_speed: bool = True
    
    def __post_init__(self):
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
    total_size: int = 0          # Total size of all output files
    vq_data_size: int = 0        # Size of VQ data that goes into .xex
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
        self._is_converting = False
        
        # Thread-safe output queue (conversion runs in background thread)
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
        self.converted = False
        self.result = None
        self.use_converted = False
    
    def is_converting(self) -> bool:
        return self._is_converting
    
    def cleanup(self):
        self.invalidate()
    
    def cancel_conversion(self):
        # Direct import conversion can't be cleanly cancelled mid-run,
        # but the thread is daemon so it dies with the app
        self._is_converting = False
    
    def get_pending_output(self) -> List[str]:
        """Get all pending output lines (call from main thread)."""
        lines = []
        while True:
            try:
                lines.append(self.output_queue.get_nowait())
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
    """Converts WAV files to VQ format using pokey_vq (direct import)."""
    
    def __init__(self, vq_state: VQState):
        self.vq_state = vq_state
        self.logger = logging.getLogger("tracker.vq_convert")
    
    def _queue_output(self, text: str):
        self.vq_state.output_queue.put(text)
    
    def convert(self, input_files: List[str]):
        """Start VQ conversion in a background thread."""
        self.logger.info(f"convert: {len(input_files)} files")
        
        # Reset state
        self.vq_state.conversion_complete = False
        self.vq_state.completion_result = None
        while not self.vq_state.output_queue.empty():
            try:
                self.vq_state.output_queue.get_nowait()
            except queue.Empty:
                break
        
        # Validate
        if not input_files:
            self._fail("No input files specified")
            return
        
        missing = [f for f in input_files if not os.path.exists(f)]
        if missing:
            names = ', '.join(os.path.basename(f) for f in missing[:3])
            self._fail(f"Missing files: {names}")
            return
        
        if not POKEY_VQ_AVAILABLE:
            self._fail(f"pokey_vq not available: {_import_error}")
            return
        
        # Prepare output directory (clean first to prevent stale files from prior runs)
        app_dir = runtime.get_app_dir()
        asm_output_dir = os.path.join(app_dir, ".tmp", "vq_output")
        if os.path.isdir(asm_output_dir):
            import shutil
            shutil.rmtree(asm_output_dir)
        os.makedirs(asm_output_dir, exist_ok=True)
        
        settings = self.vq_state.settings
        output_name = os.path.join(asm_output_dir,
            f"multi_{len(input_files)}-r{settings.rate}-v{settings.vector_size}"
            f"-s{settings.smoothness}" + ("-enh" if settings.enhance else ""))
        
        # Run in background thread (conversion is CPU-heavy)
        self.vq_state._is_converting = True
        thread = threading.Thread(
            target=self._run_conversion,
            args=(input_files, asm_output_dir, output_name),
            daemon=True
        )
        thread.start()
    
    def _fail(self, message: str):
        """Report immediate failure."""
        self.logger.error(f"Conversion failed: {message}")
        self._queue_output(f"\nERROR: {message}\n")
        result = VQResult(success=False, error_message=message)
        self.vq_state._is_converting = False
        self.vq_state.completion_result = result
        self.vq_state.conversion_complete = True
    
    def _run_conversion(self, input_files: List[str], asm_output_dir: str, output_name: str):
        """Run PokeyVQBuilder directly (background thread)."""
        result = VQResult()
        
        try:
            from pokey_vq.cli.builder import PokeyVQBuilder
            
            settings = self.vq_state.settings
            
            self._queue_output(f"Converting {len(input_files)} file(s)...\n")
            self._queue_output(f"Output: {asm_output_dir}\n")
            self._queue_output(f"Settings: rate={settings.rate}, "
                               f"vec={settings.vector_size}, "
                               f"smooth={settings.smoothness}, "
                               f"enhance={'on' if settings.enhance else 'off'}, "
                               f"optimize={'speed' if settings.optimize_speed else 'size'}\n")
            self._queue_output("-" * 60 + "\n")
            
            args = VQArgs(
                input=input_files,
                output=output_name,
                player="vq_multi_channel",
                rate=settings.rate,
                channels=1,
                optimize="speed" if settings.optimize_speed else "size",
                no_player=True,
                quality=50.0,
                smoothness=float(settings.smoothness),
                codebook=256,
                iterations=50,
                min_vector=settings.vector_size,
                max_vector=settings.vector_size,
                lbg=False,
                voltage="off",
                enhance="on" if settings.enhance else "off",
                wav="off",
            )
            
            # Capture builder's stdout/stderr
            output_buffer = io.StringIO()
            return_code = 1
            
            try:
                with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                    builder = PokeyVQBuilder(args)
                    return_code = builder.run()
            except SystemExit as e:
                # builder.py calls sys.exit() on errors
                return_code = e.code if isinstance(e.code, int) else 1
                self._queue_output(f"\nBuilder exited with code: {return_code}\n")
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
                        if line:
                            self._queue_output(line + '\n')
            
            if return_code != 0:
                result.success = False
                result.error_message = f"Builder returned code {return_code}"
                self._queue_output(f"\nERROR: {result.error_message}\n")
            else:
                # Verify output files exist
                required = ["VQ_BLOB.asm", "VQ_INDICES.asm", "SAMPLE_DIR.asm"]
                found = [f for f in required if os.path.exists(os.path.join(asm_output_dir, f))]
                
                if len(found) >= 2:
                    result.output_dir = asm_output_dir
                    result = self._parse_results(asm_output_dir, result)
                    result.success = True
                    self.vq_state.output_dir = result.output_dir
                    self._queue_output("\n" + "=" * 60 + "\n")
                    self._queue_output(f"SUCCESS: Conversion complete!\n")
                    self._queue_output(f"Output: {result.output_dir}\n")
                    self._queue_output(f"Atari data size: {format_size(result.vq_data_size)}\n")
                    self._queue_output(f"Preview WAVs: {len(result.converted_wavs)} files\n")
                else:
                    result.success = False
                    result.error_message = f"Missing ASM files in {asm_output_dir}"
                    self._queue_output(f"\nWARNING: {result.error_message}\n")
                    self._queue_output(f"Required: {required}\n")
                    self._queue_output(f"Found: {found}\n")
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
        vq_data_size = 0  # Size of actual Atari data (ASM/bin files)
        converted_wavs = []
        
        for filename in os.listdir(output_dir):
            filepath = os.path.join(output_dir, filename)
            if os.path.isfile(filepath):
                fsize = os.path.getsize(filepath)
                total_size += fsize
                # Track VQ data size (ASM files that go into .xex)
                if filename.endswith('.asm'):
                    vq_data_size += fsize
        
        # Try conversion_info.json first
        info_path = os.path.join(output_dir, "conversion_info.json")
        if os.path.isfile(info_path):
            try:
                with open(info_path, 'r') as f:
                    info = json.load(f)
                    if 'samples' in info:
                        for sample_info in info['samples']:
                            if 'instrument_file' in sample_info:
                                wav_path = sample_info['instrument_file']
                                if os.path.exists(wav_path):
                                    converted_wavs.append(wav_path)
            except Exception as e:
                self._queue_output(f"Warning: Could not parse JSON: {e}\n")
        
        # Fallback: scan instruments folder
        if not converted_wavs:
            instruments_dir = os.path.join(output_dir, "instruments")
            if os.path.isdir(instruments_dir):
                for wav in sorted(os.listdir(instruments_dir)):
                    if wav.endswith('.wav'):
                        wav_path = os.path.join(instruments_dir, wav)
                        converted_wavs.append(wav_path)
                        total_size += os.path.getsize(wav_path)
        
        result.total_size = total_size
        result.vq_data_size = vq_data_size if vq_data_size > 0 else total_size
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
    """Get pokey_vq availability status for diagnostics."""
    return POKEY_VQ_AVAILABLE, _import_error
