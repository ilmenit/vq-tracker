"""Atari Sample Tracker - VQ Conversion Module

Handles conversion of instruments to VQ format using pokey_vq subprocess.
"""
import os
import sys
import json
import shutil
import tempfile
import subprocess
import threading
import queue
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field

from constants import (VQ_RATE_DEFAULT, VQ_VECTOR_DEFAULT, VQ_SMOOTHNESS_DEFAULT)


@dataclass
class VQSettings:
    """VQ conversion settings."""
    rate: int = VQ_RATE_DEFAULT
    vector_size: int = VQ_VECTOR_DEFAULT
    smoothness: int = VQ_SMOOTHNESS_DEFAULT
    enhance: bool = True


@dataclass
class VQResult:
    """Result of VQ conversion."""
    success: bool = False
    error_message: str = ""
    total_size: int = 0
    converted_wavs: List[str] = field(default_factory=list)
    asm_files: List[str] = field(default_factory=list)
    json_path: str = ""
    output_dir: str = ""


class VQState:
    """Manages VQ conversion state."""
    
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
    """Handles VQ conversion subprocess."""
    
    def __init__(self, vq_state: VQState):
        self.vq_state = vq_state
        import logging
        self.logger = logging.getLogger(__name__)
    
    def find_vq_converter(self) -> Optional[str]:
        """Find vq_converter folder path."""
        tracker_dir = os.path.dirname(os.path.abspath(__file__))
        self.logger.debug(f"find_vq_converter: tracker_dir={tracker_dir}")
        
        candidates = [
            # Same directory as tracker
            os.path.join(tracker_dir, "vq_converter"),
            # Parent directory  
            os.path.join(os.path.dirname(tracker_dir), "vq_converter"),
            # Sibling directory
            os.path.normpath(os.path.join(tracker_dir, "..", "vq_converter")),
        ]
        
        for path in candidates:
            path = os.path.normpath(path)
            self.logger.debug(f"  Checking: {path}")
            pokey_vq_path = os.path.join(path, "pokey_vq")
            if os.path.isdir(pokey_vq_path):
                cli_path = os.path.join(pokey_vq_path, "cli")
                if os.path.isdir(cli_path):
                    self.logger.debug(f"  Found vq_converter at: {path}")
                    return path
        
        self.logger.warning("vq_converter not found in any candidate path")
        return None
    
    def build_command(self, input_files: List[str], output_name: str) -> List[str]:
        """Build subprocess command.
        
        Args:
            input_files: List of WAV file paths
            output_name: Output name/path for the XEX (ASM files go to parent dir)
        """
        settings = self.vq_state.settings
        
        # vq_multi_channel requires mono (--channels 1)
        # and we use --optimize speed for better tracker performance
        cmd = [
            sys.executable, "-m", "pokey_vq.cli",
            *input_files,
            "-p", "vq_multi_channel",
            "-r", str(settings.rate),
            "--channels", "1",  # Required for vq_multi_channel
            "-miv", str(settings.vector_size),
            "-mav", str(settings.vector_size),
            "-q", "50",  # Quality (default but explicit)
            "-s", str(settings.smoothness),
            "-e", "on" if settings.enhance else "off",
            "--optimize", "speed",  # Fast 2-byte fetch for tracker
            "--wav", "on",
            "-o", output_name  # Output name (XEX created at this path)
        ]
        return cmd
    
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
    
    def _queue_output(self, text: str):
        """Queue output text for main thread to process."""
        self.vq_state.output_queue.put(text)
    
    def convert(self, input_files: List[str]):
        """
        Start conversion in background thread.
        
        Args:
            input_files: List of WAV file paths to convert
            
        Output and completion are handled via VQState queue/flags.
        Call vq_state.get_pending_output() and vq_state.check_completion()
        from main thread to process results.
        """
        self.logger.debug(f"convert: {len(input_files)} files")
        for f in input_files[:5]:  # Log first 5
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
        
        # Find vq_converter
        vq_converter_path = self.find_vq_converter()
        if not vq_converter_path:
            result = VQResult(
                success=False,
                error_message="vq_converter folder not found. Place it alongside the tracker."
            )
            self.vq_state.completion_result = result
            self.vq_state.conversion_complete = True
            return
        
        # Create output directory in tmp-convert folder (same dir as tracker)
        tracker_dir = os.path.dirname(os.path.abspath(__file__))
        output_dirname = self._generate_output_dirname(len(input_files))
        asm_output_dir = os.path.join(tracker_dir, "tmp-convert")
        output_name = os.path.join(asm_output_dir, output_dirname)  # XEX path
        
        # Ensure output directory exists
        os.makedirs(asm_output_dir, exist_ok=True)
        
        # Build command with output name (ASM files go to asm_output_dir)
        cmd = self.build_command(input_files, output_name)
        self.logger.debug(f"Command: {' '.join(cmd[:10])}...")
        self.logger.debug(f"Output name: {output_name}")
        self.logger.debug(f"ASM output dir: {asm_output_dir}")
        
        # Start conversion in thread
        thread = threading.Thread(
            target=self._run_conversion,
            args=(cmd, vq_converter_path, asm_output_dir, output_name, len(input_files)),
            daemon=True
        )
        self.vq_state._is_converting = True
        thread.start()
    
    def _run_conversion(self, cmd: List[str], vq_converter_path: str, 
                        asm_output_dir: str, output_name: str, num_files: int):
        """Run conversion subprocess (called in thread).
        
        Args:
            cmd: Command to run
            vq_converter_path: Path to vq_converter
            asm_output_dir: Directory where ASM files will be created
            output_name: Full path for output XEX
            num_files: Number of input files
        """
        result = VQResult()
        
        try:
            # Set up environment
            env = os.environ.copy()
            env["PYTHONPATH"] = vq_converter_path + os.pathsep + env.get("PYTHONPATH", "")
            
            self._queue_output(f"Starting conversion of {num_files} file(s)...\n")
            self._queue_output(f"VQ Converter: {vq_converter_path}\n")
            self._queue_output(f"Output: {asm_output_dir}\n")
            self._queue_output(f"Settings: rate={self.vq_state.settings.rate}, "
                               f"vec={self.vq_state.settings.vector_size}, "
                               f"smooth={self.vq_state.settings.smoothness}, "
                               f"enhance={'on' if self.vq_state.settings.enhance else 'off'}\n")
            self._queue_output("-" * 60 + "\n")
            
            cwd = vq_converter_path
            
            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                cwd=cwd
            )
            self.vq_state._process = process
            
            # Read output line by line
            output_lines = []
            for line in process.stdout:
                output_lines.append(line)
                self._queue_output(line)
            
            # Wait for completion
            process.wait()
            
            if process.returncode == 0:
                # ASM files are in asm_output_dir (not a subdirectory)
                # Check for required ASM files
                required_files = ["VQ_BLOB.asm", "VQ_INDICES.asm", "SAMPLE_DIR.asm"]
                found_files = [f for f in required_files 
                              if os.path.exists(os.path.join(asm_output_dir, f))]
                
                if len(found_files) >= 2:  # At least VQ_BLOB and SAMPLE_DIR
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
                    self._queue_output(f"Found: {found_files}\n")
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
            
            # Signal completion (main thread will pick this up)
            self.vq_state.completion_result = result
            self.vq_state.conversion_complete = True
    
    def _parse_results(self, output_dir: str, result: VQResult) -> VQResult:
        """Parse conversion results from output directory."""
        # Find JSON file (conversion_info.json)
        json_path = os.path.join(output_dir, "conversion_info.json")
        if os.path.exists(json_path):
            result.json_path = json_path
            
            try:
                with open(json_path, 'r') as f:
                    data = json.load(f)
                
                # Extract converted WAV paths from samples array
                if 'samples' in data:
                    for sample in data['samples']:
                        if 'instrument_file' in sample:
                            wav_path = sample['instrument_file']
                            # instrument_file contains absolute path
                            if os.path.exists(wav_path):
                                result.converted_wavs.append(wav_path)
                            else:
                                # Try relative to output_dir/instruments
                                rel_path = os.path.join(output_dir, "instruments", 
                                                        os.path.basename(wav_path))
                                if os.path.exists(rel_path):
                                    result.converted_wavs.append(rel_path)
                
                # Get total size from stats (not compression)
                if 'stats' in data:
                    result.total_size = data['stats'].get('size_bytes', 0)
                    
            except Exception as e:
                self._queue_output(f"Warning: Could not parse JSON: {e}\n")
        
        # Find ASM files
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith('.asm'):
                    result.asm_files.append(os.path.join(root, f))
        
        # Calculate total size from ASM files if not in JSON
        if result.total_size == 0:
            data_files = ['VQ_BLOB.asm', 'VQ_INDICES.asm', 'SAMPLE_DIR.asm']
            for data_file in data_files:
                file_path = os.path.join(output_dir, data_file)
                if os.path.exists(file_path):
                    try:
                        result.total_size += os.path.getsize(file_path)
                    except:
                        pass
        
        return result


def format_size(size_bytes: int) -> str:
    """Format byte size as human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
