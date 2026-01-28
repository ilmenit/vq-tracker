"""Atari Sample Tracker - Build Module

Exports song data to ASM format and builds standalone Atari XEX executables.
"""
import os
import sys
import shutil
import subprocess
import platform
import tempfile
import logging
import threading
import queue
from typing import Optional, Tuple, List, Callable
from dataclasses import dataclass, field

from data_model import Song, Pattern, Row
from state import state

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Result of build operation."""
    success: bool = False
    xex_path: str = ""
    error_message: str = ""
    build_dir: str = ""


class BuildState:
    """Manages build state for threaded builds."""
    
    def __init__(self):
        self.output_queue: queue.Queue = queue.Queue()
        self.is_building = False
        self.build_complete = False
        self.completion_result: Optional[BuildResult] = None
    
    def reset(self):
        """Reset state for new build."""
        self.build_complete = False
        self.completion_result = None
        # Clear output queue
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except queue.Empty:
                break
    
    def queue_output(self, text: str):
        """Queue output text for main thread."""
        self.output_queue.put(text)
    
    def get_pending_output(self) -> Optional[str]:
        """Get pending output (non-blocking)."""
        try:
            return self.output_queue.get_nowait()
        except queue.Empty:
            return None


# Global build state
build_state = BuildState()


def export_song_data(song: Song, output_path: str) -> Tuple[bool, str]:
    """Export song data to SONG_DATA.asm format.
    
    Args:
        song: Song object to export
        output_path: Path to write SONG_DATA.asm
        
    Returns:
        (success, error_message)
    """
    try:
        lines = []
        lines.append("; ==========================================================================")
        lines.append("; SONG_DATA.asm - Exported from Atari Sample Tracker")
        lines.append("; ==========================================================================")
        lines.append(f"; Title:  {song.title}")
        lines.append(f"; Author: {song.author}")
        lines.append("; ==========================================================================")
        lines.append("")
        
        # Song header
        num_songlines = len(song.songlines)
        num_patterns = len(song.patterns)
        
        lines.append(f"SONG_LENGTH = {num_songlines}")
        lines.append("")
        
        # Songline arrays
        lines.append("; --- Songline Data ---")
        
        # Speed per songline
        speeds = [str(sl.speed) for sl in song.songlines]
        lines.append(f"SONG_SPEED:")
        lines.append(f"    .byte {','.join(speeds)}")
        lines.append("")
        
        # Patterns per channel
        for ch in range(3):
            ptns = [str(sl.patterns[ch] if ch < len(sl.patterns) else 0) for sl in song.songlines]
            lines.append(f"SONG_PTN_CH{ch}:")
            lines.append(f"    .byte {','.join(ptns)}")
        lines.append("")
        
        # Pattern directory
        lines.append("; --- Pattern Directory ---")
        lines.append(f"PATTERN_COUNT = {num_patterns}")
        lines.append("")
        
        # Pattern lengths
        lens = [str(p.length) for p in song.patterns]
        lines.append("PATTERN_LEN:")
        lines.append(f"    .byte {','.join(lens)}")
        lines.append("")
        
        # Pattern pointers
        lines.append("PATTERN_PTR_LO:")
        ptrs_lo = [f"<PTN_{i}" for i in range(num_patterns)]
        lines.append(f"    .byte {','.join(ptrs_lo)}")
        lines.append("")
        
        lines.append("PATTERN_PTR_HI:")
        ptrs_hi = [f">PTN_{i}" for i in range(num_patterns)]
        lines.append(f"    .byte {','.join(ptrs_hi)}")
        lines.append("")
        
        # Pattern data (variable-length events)
        lines.append("; --- Pattern Event Data ---")
        for i, pattern in enumerate(song.patterns):
            lines.append("")
            lines.append(f"PTN_{i}:")
            event_bytes = _encode_pattern_events(pattern, i)
            
            if not event_bytes:
                lines.append("    .byte $FF  ; Empty pattern")
            else:
                # Write in chunks for readability
                for j in range(0, len(event_bytes), 16):
                    chunk = event_bytes[j:j+16]
                    hex_bytes = ','.join(f'${b:02X}' for b in chunk)
                    lines.append(f"    .byte {hex_bytes}")
        
        lines.append("")
        lines.append("; === END OF SONG DATA ===")
        
        # Write file
        with open(output_path, 'w') as f:
            f.write('\n'.join(lines))
        
        logger.info(f"Exported song data to {output_path}")
        return True, ""
        
    except Exception as e:
        logger.error(f"Failed to export song data: {e}")
        return False, str(e)


def _encode_pattern_events(pattern: Pattern, pattern_idx: int) -> List[int]:
    """Encode pattern rows to variable-length event format.
    
    Returns list of bytes representing all events in the pattern.
    """
    events = []
    last_inst = -1  # Track last instrument for delta encoding
    last_vol = -1   # Track last volume for delta encoding
    
    for row_num, row in enumerate(pattern.rows):
        if row_num >= pattern.length:
            break
            
        if row.note == 0:
            continue  # Skip empty rows
        
        # Determine what needs to be encoded
        note = row.note
        inst = row.instrument
        vol = row.volume
        
        # First event in pattern must include inst+vol
        if last_inst == -1:
            # Full event: row, note|$80, inst|$80, vol
            events.append(row_num)
            events.append(note | 0x80)
            events.append(inst | 0x80)
            events.append(vol)
            last_inst = inst
            last_vol = vol
        elif inst != last_inst or vol != last_vol:
            # Instrument or volume changed
            if vol != last_vol:
                # Volume changed - must include inst byte too
                events.append(row_num)
                events.append(note | 0x80)
                events.append(inst | 0x80)
                events.append(vol)
            else:
                # Only instrument changed
                events.append(row_num)
                events.append(note | 0x80)
                events.append(inst)
            last_inst = inst
            last_vol = vol
        else:
            # Same inst+vol as before
            events.append(row_num)
            events.append(note)
    
    # End marker
    events.append(0xFF)
    
    return events


def find_mads() -> Optional[str]:
    """Find MADS assembler executable."""
    system = platform.system()
    machine = platform.machine().lower()
    
    # Determine binary name
    if system == "Windows":
        binary = "mads.exe"
    else:
        binary = "mads"
    
    # Check in VQ converter's bin directory
    if state.vq.result and state.vq.result.output_dir:
        vq_base = os.path.dirname(os.path.dirname(state.vq.result.output_dir))
        
        # Try platform-specific paths
        if system == "Linux":
            plat_dir = "linux_x86_64"
        elif system == "Darwin":
            plat_dir = "macos_aarch64" if "arm" in machine else "macos_x86_64"
        elif system == "Windows":
            plat_dir = "windows_x86_64"
        else:
            plat_dir = ""
        
        if plat_dir:
            mads_path = os.path.join(vq_base, "bin", plat_dir, binary)
            if os.path.isfile(mads_path) and os.access(mads_path, os.X_OK):
                return mads_path
        
        # Try root bin
        mads_path = os.path.join(vq_base, "bin", binary)
        if os.path.isfile(mads_path) and os.access(mads_path, os.X_OK):
            return mads_path
    
    # Check PATH
    mads_path = shutil.which(binary)
    if mads_path:
        return mads_path
    
    return None


def _output(text: str):
    """Output text to both queue and console."""
    build_state.queue_output(text)
    print(text, end='')


def build_xex_sync(song: Song, output_xex_path: str) -> BuildResult:
    """Build standalone Atari XEX executable (synchronous version with queue output).
    
    Args:
        song: Song to build
        output_xex_path: Path for output .xex file
        
    Returns:
        BuildResult with success status and paths
    """
    result = BuildResult()
    
    _output("=" * 60 + "\n")
    _output("  BUILDING ATARI EXECUTABLE\n")
    _output("=" * 60 + "\n")
    
    # Validate VQ conversion
    if not state.vq.converted or not state.vq.result:
        result.error_message = "VQ conversion not done.\n\nPlease run CONVERT first."
        _output(f"ERROR: {result.error_message}\n")
        return result
    
    vq_output_dir = state.vq.result.output_dir
    if not vq_output_dir or not os.path.isdir(vq_output_dir):
        result.error_message = f"VQ output directory not found:\n{vq_output_dir}\n\nPlease run CONVERT again."
        _output(f"ERROR: {result.error_message}\n")
        return result
    
    _output(f"  VQ Data: {vq_output_dir}\n")
    _output(f"  Output:  {output_xex_path}\n")
    _output("-" * 60 + "\n")
    
    # Find MADS
    mads_path = find_mads()
    if not mads_path:
        result.error_message = ("MADS assembler not found.\n\n"
                                "Please ensure MADS is installed and in your PATH,\n"
                                "or place it in the vq_converter/bin/ directory.")
        _output(f"ERROR: MADS assembler not found\n")
        return result
    
    _output(f"  Using MADS: {mads_path}\n")
    logger.info(f"Using MADS: {mads_path}")
    
    # Create build directory
    build_dir = tempfile.mkdtemp(prefix="tracker_build_")
    result.build_dir = build_dir
    _output(f"  Build directory: {build_dir}\n")
    logger.info(f"Build directory: {build_dir}")
    
    try:
        # Copy VQ data files
        _output("\n  Copying VQ data files...\n")
        vq_files = [
            "VQ_CFG.asm",
            "VQ_LO.asm", 
            "VQ_HI.asm",
            "VQ_BLOB.asm",
            "VQ_INDICES.asm",
            "SAMPLE_DIR.asm"
        ]
        
        missing_files = []
        for vq_file in vq_files:
            src = os.path.join(vq_output_dir, vq_file)
            if os.path.exists(src):
                shutil.copy2(src, build_dir)
                _output(f"    + {vq_file}\n")
                logger.debug(f"Copied: {vq_file}")
            else:
                missing_files.append(vq_file)
                _output(f"    ! MISSING: {vq_file}\n")
                logger.warning(f"VQ file not found: {src}")
        
        if missing_files:
            result.error_message = f"Missing VQ files: {', '.join(missing_files)}\n\nRe-run VQ conversion."
            _output(f"\nERROR: Missing required VQ files\n")
            return result
        
        # Copy player support directories from VQ output
        _output("\n  Copying player support files...\n")
        support_dirs = ["common", "tracker", "pitch"]
        for subdir in support_dirs:
            src_dir = os.path.join(vq_output_dir, subdir)
            if os.path.isdir(src_dir):
                dst_dir = os.path.join(build_dir, subdir)
                shutil.copytree(src_dir, dst_dir)
                _output(f"    + {subdir}/\n")
                logger.debug(f"Copied directory: {subdir}/")
            else:
                _output(f"    ! {subdir}/ not found\n")
                logger.warning(f"Support directory not found: {src_dir}")
        
        # Verify critical support files exist
        critical_files = [
            "common/atari.inc",
            "common/zeropage.inc",
            "common/macros.inc",
            "common/pokey_setup.asm",
            "tracker/tracker_api.asm",
            "tracker/tracker_irq.asm",
            "pitch/pitch_tables.asm",
            "pitch/LUT_NIBBLES.asm"
        ]
        
        missing_critical = []
        for cf in critical_files:
            if not os.path.exists(os.path.join(build_dir, cf)):
                missing_critical.append(cf)
        
        if missing_critical:
            result.error_message = (f"Missing player support files:\n"
                                    f"{chr(10).join(missing_critical[:5])}\n\n"
                                    f"VQ conversion may have failed to copy player files.")
            _output(f"\nERROR: Missing critical support files\n")
            for f in missing_critical[:5]:
                _output(f"    - {f}\n")
            return result
        
        # Export song data
        _output("\n  Exporting song data...\n")
        song_data_path = os.path.join(build_dir, "SONG_DATA.asm")
        ok, err = export_song_data(song, song_data_path)
        if not ok:
            result.error_message = f"Failed to export song data: {err}"
            _output(f"ERROR: {result.error_message}\n")
            return result
        _output(f"    + SONG_DATA.asm ({len(song.patterns)} patterns, {len(song.songlines)} songlines)\n")
        
        # Copy song_player.asm from our asm/ directory
        tracker_dir = os.path.dirname(os.path.abspath(__file__))
        player_src = os.path.join(tracker_dir, "asm", "song_player.asm")
        if os.path.exists(player_src):
            shutil.copy2(player_src, build_dir)
            _output(f"    + song_player.asm\n")
            logger.debug("Copied: song_player.asm")
        else:
            result.error_message = f"song_player.asm not found at {player_src}"
            _output(f"ERROR: {result.error_message}\n")
            return result
        
        # Also check for copy_os_ram.asm (may be needed)
        copy_os_src = os.path.join(vq_output_dir, "common", "copy_os_ram.asm")
        if not os.path.exists(os.path.join(build_dir, "common", "copy_os_ram.asm")):
            # Try to create a minimal one if missing
            copy_os_path = os.path.join(build_dir, "common", "copy_os_ram.asm")
            os.makedirs(os.path.dirname(copy_os_path), exist_ok=True)
            if not os.path.exists(copy_os_path):
                with open(copy_os_path, 'w') as f:
                    f.write("; copy_os_ram.asm - stub\n")
                    f.write("; OS RAM copy handled by player initialization\n")
        
        # Run MADS
        _output("\n  Assembling with MADS...\n")
        player_asm = os.path.join(build_dir, "song_player.asm")
        output_xex = os.path.join(build_dir, "song.xex")
        
        cmd = [mads_path, player_asm, "-o:" + output_xex]
        logger.info(f"Running: {' '.join(cmd)}")
        
        proc = subprocess.run(
            cmd,
            cwd=build_dir,
            capture_output=True,
            text=True
        )
        
        if proc.returncode != 0:
            # Extract useful error info
            error_output = proc.stdout + "\n" + proc.stderr
            # Find first error line
            error_lines = [l for l in error_output.split('\n') if 'error' in l.lower()]
            if error_lines:
                result.error_message = f"MADS assembly error:\n\n{error_lines[0][:200]}"
            else:
                result.error_message = f"MADS assembly failed:\n\n{error_output[:500]}"
            _output(f"\nERROR: Assembly failed\n")
            _output(error_output[:500] + "\n")
            logger.error(f"MADS failed: {error_output}")
            return result
        
        _output("    Assembly successful!\n")
        
        # Check output exists
        if not os.path.exists(output_xex):
            result.error_message = "MADS succeeded but XEX file not created"
            _output(f"ERROR: {result.error_message}\n")
            return result
        
        # Get file size
        xex_size = os.path.getsize(output_xex)
        
        # Copy to final destination
        os.makedirs(os.path.dirname(os.path.abspath(output_xex_path)), exist_ok=True)
        shutil.copy2(output_xex, output_xex_path)
        
        result.success = True
        result.xex_path = output_xex_path
        
        _output("\n" + "=" * 60 + "\n")
        _output("  BUILD SUCCESSFUL!\n")
        _output("=" * 60 + "\n")
        _output(f"  Output: {output_xex_path}\n")
        _output(f"  Size:   {xex_size:,} bytes\n")
        _output("=" * 60 + "\n")
        
        logger.info(f"Build successful: {output_xex_path}")
        
    except Exception as e:
        result.error_message = f"Build error: {e}"
        _output(f"\nERROR: {result.error_message}\n")
        logger.error(result.error_message, exc_info=True)
    
    return result


def start_build_async(song: Song, output_xex_path: str):
    """Start build in background thread.
    
    Args:
        song: Song to build  
        output_xex_path: Path for output .xex file
        
    Call build_state.get_pending_output() to get output lines.
    Check build_state.build_complete for completion.
    Access build_state.completion_result for result.
    """
    build_state.reset()
    build_state.is_building = True
    
    def build_thread():
        try:
            result = build_xex_sync(song, output_xex_path)
            build_state.completion_result = result
        except Exception as e:
            result = BuildResult(success=False, error_message=str(e))
            build_state.completion_result = result
        finally:
            build_state.is_building = False
            build_state.build_complete = True
    
    thread = threading.Thread(target=build_thread, daemon=True)
    thread.start()


# Keep old function name for compatibility but redirect to sync version
def build_xex(song: Song, output_xex_path: str) -> BuildResult:
    """Build standalone Atari XEX executable."""
    return build_xex_sync(song, output_xex_path)


def get_default_xex_path(song: Song) -> str:
    """Get default output path for XEX file."""
    # Use song title if available, otherwise "untitled"
    name = song.title.strip() if song.title.strip() else "untitled"
    # Sanitize filename
    name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    name = name.strip().replace(" ", "_")
    
    # Put in same directory as VQ output if available
    if state.vq.result and state.vq.result.output_dir:
        return os.path.join(state.vq.result.output_dir, f"{name}.xex")
    
    # Otherwise use current directory
    return os.path.join(os.getcwd(), f"{name}.xex")
