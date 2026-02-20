"""POKEY VQ Tracker - Build Module

Exports song data to ASM format and builds standalone Atari XEX executables.
"""
import os
import sys
import shutil
import subprocess
import platform
import logging
import threading
import queue
from typing import Optional, Tuple, List, Callable
from dataclasses import dataclass, field

from data_model import Song, Pattern, Row
from state import state
from constants import MAX_INSTRUMENTS, MAX_VOLUME, MAX_NOTES, MAX_CHANNELS
import runtime  # For path detection in bundled mode

logger = logging.getLogger(__name__)


# =============================================================================
# VALIDATION - Check song data before export
# =============================================================================

@dataclass
class ValidationIssue:
    """Single validation issue."""
    severity: str  # "error", "warning"
    location: str  # e.g., "Pattern 3, Row 12" or "Songline 5"
    message: str
    
    def __str__(self):
        icon = "âŒ" if self.severity == "error" else "âš ï¸"
        return f"{icon} {self.location}: {self.message}"


@dataclass 
class ValidationResult:
    """Result of song validation."""
    valid: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    
    def add_error(self, location: str, message: str):
        self.issues.append(ValidationIssue("error", location, message))
        self.valid = False
    
    def add_warning(self, location: str, message: str):
        self.issues.append(ValidationIssue("warning", location, message))
    
    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")
    
    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")
    
    def format_summary(self) -> str:
        if not self.issues:
            return "âœ“ Song validation passed"
        parts = []
        if self.error_count:
            parts.append(f"{self.error_count} error(s)")
        if self.warning_count:
            parts.append(f"{self.warning_count} warning(s)")
        return "Validation: " + ", ".join(parts)


def validate_song(song: Song, check_samples: bool = True) -> ValidationResult:
    """Validate song data for Atari export.
    
    Checks:
    - Pattern lengths are valid (1-254)
    - All notes are in valid range (0, 1-MAX_NOTES, or 255)
    - All instrument references exist
    - All instruments have samples loaded (if check_samples=True)
    - All songline pattern references are valid
    - No empty song
    
    Args:
        song: Song to validate
        check_samples: Whether to check for loaded samples
        
    Returns:
        ValidationResult with issues found
    """
    result = ValidationResult()
    
    # Check song has content
    if not song.songlines:
        result.add_error("Song", "No songlines defined")
        return result
    
    if not song.patterns:
        result.add_error("Song", "No patterns defined")
        return result
    
    # Track which instruments are actually used
    used_instruments = set()
    
    # Check patterns
    for ptn_idx, pattern in enumerate(song.patterns):
        loc_ptn = f"Pattern {ptn_idx:02d}"
        
        # Check pattern length
        if pattern.length < 1:
            result.add_error(loc_ptn, f"Length is {pattern.length}, must be at least 1")
        elif pattern.length > 254:
            result.add_error(loc_ptn, f"Length is {pattern.length}, max is 254 (row 255 is reserved)")
        
        # Check rows
        for row_idx, row in enumerate(pattern.rows):
            if row_idx >= pattern.length:
                break
                
            loc_row = f"Pattern {ptn_idx:02d}, Row {row_idx:02d}"
            
            # Check note value
            if row.note != 0 and row.note not in (255, 254):  # 0=empty, 255=OFF, 254=VOL_CHANGE
                if row.note < 1 or row.note > MAX_NOTES:
                    result.add_error(loc_row, f"Note value {row.note} out of range (valid: 1-{MAX_NOTES})")
            
            # Check instrument
            if row.note > 0 and row.note not in (255, 254):  # Has actual note
                if row.instrument < 0:
                    result.add_error(loc_row, f"Instrument index {row.instrument} is negative")
                elif row.instrument >= MAX_INSTRUMENTS:
                    result.add_error(loc_row, f"Instrument index {row.instrument} exceeds max ({MAX_INSTRUMENTS - 1})")
                else:
                    used_instruments.add(row.instrument)
            
            # Check volume
            if row.volume < 0 or row.volume > MAX_VOLUME:
                result.add_error(loc_row, f"Volume {row.volume} out of range (valid: 0-{MAX_VOLUME})")
    
    # Check songlines reference valid patterns
    num_patterns = len(song.patterns)
    for sl_idx, songline in enumerate(song.songlines):
        loc_sl = f"Songline {sl_idx:02d}"
        
        for ch, ptn_idx in enumerate(songline.patterns):
            if ptn_idx < 0 or ptn_idx >= num_patterns:
                result.add_error(loc_sl, f"Channel {ch+1} references pattern {ptn_idx} but only {num_patterns} patterns exist")
        
        # Check speed
        if songline.speed < 1 or songline.speed > 255:
            result.add_error(loc_sl, f"Speed {songline.speed} out of range (valid: 1-255)")
    
    # Check instrument references
    num_instruments = len(song.instruments)
    for inst_idx in sorted(used_instruments):
        if inst_idx >= num_instruments:
            result.add_error(f"Instrument {inst_idx:02d}", 
                           f"Referenced in patterns but only {num_instruments} instruments defined")
    
    # Check samples are loaded (if requested)
    if check_samples:
        for inst_idx in sorted(used_instruments):
            if inst_idx < num_instruments:
                inst = song.instruments[inst_idx]
                if not inst.is_loaded():
                    result.add_warning(f"Instrument {inst_idx:02d} ({inst.name})",
                                      "No sample loaded - will be silent")
    
    # Check for empty patterns in use
    patterns_in_use = set()
    for sl in song.songlines:
        patterns_in_use.update(sl.patterns)
    
    for ptn_idx in patterns_in_use:
        if 0 <= ptn_idx < len(song.patterns):
            pattern = song.patterns[ptn_idx]
            has_notes = any(row.note != 0 for row in pattern.rows[:pattern.length])
            if not has_notes:
                result.add_warning(f"Pattern {ptn_idx:02d}", "Empty pattern (no notes)")
    
    return result


def validate_for_build(song: Song) -> ValidationResult:
    """Full validation required before build (includes VQ check)."""
    result = validate_song(song, check_samples=True)
    
    # Additional checks for build
    if not state.vq.result:
        result.add_error("VQ Conversion", "No VQ conversion done - run CONVERT first")
    elif not state.vq.result.success:
        result.add_error("VQ Conversion", "VQ conversion failed - fix errors and re-convert")
    
    return result


@dataclass
class BuildResult:
    """Result of build operation."""
    success: bool = False
    xex_path: str = ""
    error_message: str = ""
    build_dir: str = ""
    # Memory upgrade suggestion (set when bank packing fails)
    needs_upgrade: bool = False
    suggested_config: str = ""      # e.g. "320 KB"
    suggested_banks: int = 0        # e.g. 16
    current_config: str = ""        # e.g. "128 KB"
    total_sample_bytes: int = 0     # for display in dialog


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


def export_song_data(song: Song, output_path: str, output_func=None,
                     region_a_limit: int = 0) -> Tuple[bool, str]:
    """Export song data to SONG_DATA.asm format.
    
    Also generates SONG_CFG.asm with equates that need to be included early
    (before ORG) for conditional assembly.
    
    When region_a_limit > 0 (banking mode), song data is split:
      SONG_DATA.asm   — metadata + patterns fitting in region_a_limit bytes
      SONG_DATA_2.asm — overflow patterns (may be empty)
    Pattern labels (PTN_N) are referenced by PATTERN_PTR_LO/HI across files;
    MADS resolves these since both are included in the same assembly scope.
    
    Args:
        song: Song object to export
        output_path: Path to write SONG_DATA.asm
        output_func: Optional function for debug output
        region_a_limit: If > 0, split patterns at this byte boundary.
                        Generates SONG_DATA_2.asm alongside SONG_DATA.asm.
        
    Returns:
        (success, error_message)
    """
    # Validate song data before export
    validation = validate_song(song, check_samples=False)
    if not validation.valid:
        error_lines = [str(i) for i in validation.issues if i.severity == "error"]
        error_msg = "Song validation failed:\n" + "\n".join(error_lines[:5])
        if len(error_lines) > 5:
            error_msg += f"\n...and {len(error_lines) - 5} more errors"
        if output_func:
            output_func(f"\n{error_msg}\n")
        return False, error_msg
    
    # Show warnings but continue
    if validation.warning_count > 0 and output_func:
        output_func(f"\nValidation warnings ({validation.warning_count}):\n")
        for issue in validation.issues:
            if issue.severity == "warning":
                output_func(f"  {issue}\n")
    try:
        # Generate SONG_CFG.asm - equates needed BEFORE the ORG directive
        # These must be separate because SONG_DATA.asm contains .byte directives
        # that would be placed at the wrong address if included before ORG
        cfg_path = output_path.replace("SONG_DATA.asm", "SONG_CFG.asm")
        cfg_lines = []
        cfg_lines.append("; ==========================================================================")
        cfg_lines.append("; SONG_CFG.asm - Song Configuration (include before ORG)")
        cfg_lines.append("; ==========================================================================")
        cfg_lines.append("; This file contains only equates (no .byte data) and must be included")
        cfg_lines.append("; before the ORG directive for conditional assembly to work correctly.")
        cfg_lines.append("; The actual song data is in SONG_DATA.asm (include after code).")
        cfg_lines.append("; ==========================================================================")
        cfg_lines.append("")
        vol_val = 1 if song.volume_control else 0
        cfg_lines.append(f"VOLUME_CONTROL = {vol_val}  ; 1=enable volume scaling, 0=disable")
        cfg_lines.append("")
        # Screen control: screen_control=True (default) means show display, so BLANK_SCREEN=0
        # screen_control=False means blank display, so BLANK_SCREEN=1
        blank_val = 0 if song.screen_control else 1
        cfg_lines.append(f"BLANK_SCREEN = {blank_val}  ; 1=no display (~15% more CPU), 0=normal display")
        cfg_lines.append("")
        # Keyboard control: 1=enable stop/restart during playback, 0=play-once mode
        key_ctrl_val = 1 if song.keyboard_control else 0
        cfg_lines.append(f"KEY_CONTROL = {key_ctrl_val}  ; 1=enable stop/restart keys, 0=play-once (saves cycles)")
        cfg_lines.append("")
        cfg_lines.append(f"START_ADDRESS = ${song.start_address:04X}  ; ORG address for player code")
        cfg_lines.append("")
        # Banking mode
        from constants import MEMORY_CONFIGS
        use_banking = song.memory_config != "64 KB"
        if use_banking:
            n_banks = 0
            for name, banks, _ in MEMORY_CONFIGS:
                if name == song.memory_config:
                    n_banks = banks
                    break
            cfg_lines.append(f"USE_BANKING = 1  ; Extended memory mode")
            cfg_lines.append(f"MAX_BANKS = {n_banks}  ; Available banks for {song.memory_config}")
            cfg_lines.append("")
        cfg_lines.append(f"NUM_CHANNELS = {MAX_CHANNELS}  ; Number of polyphonic channels (AUDC1-AUDC4)")
        cfg_lines.append("")
        
        with open(cfg_path, 'w') as f:
            f.write('\n'.join(cfg_lines))
        
        # Generate SONG_DATA.asm - actual data (include AFTER code)
        lines = []
        lines.append("; ==========================================================================")
        lines.append("; SONG_DATA.asm - Exported from POKEY VQ Tracker")
        lines.append("; ==========================================================================")
        lines.append(f"; Title:  {song.title}")
        lines.append(f"; Author: {song.author}")
        lines.append("; ==========================================================================")
        lines.append("; NOTE: Include this file AFTER your code (in the data section).")
        lines.append("; Include SONG_CFG.asm before ORG for VOLUME_CONTROL equate.")
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
        for ch in range(MAX_CHANNELS):
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
        
        if output_func:
            output_func("\n  --- Pattern Encoding Debug ---\n")
        
        # Pre-encode ALL patterns to determine byte counts for split
        encoded_patterns = []
        for i, pattern in enumerate(song.patterns):
            event_bytes = _encode_pattern_events(pattern, i, song.instruments, output_func)
            encoded_patterns.append((i, event_bytes))
        
        if output_func:
            output_func("  --- End Pattern Encoding ---\n")
        
        # Calculate metadata byte count (everything before pattern event data)
        # SONG_SPEED + SONG_PTN_CH0-3 + PATTERN_LEN + PTR_LO + PTR_HI
        metadata_bytes = 5 * num_songlines + 3 * num_patterns
        
        # Determine split point (only if region_a_limit > 0)
        split_idx = num_patterns  # default: all patterns in region A
        if region_a_limit > 0:
            cumulative = metadata_bytes
            for i, (ptn_idx, event_bytes) in enumerate(encoded_patterns):
                ptn_size = max(len(event_bytes), 1)  # at least 1 ($FF for empty)
                if cumulative + ptn_size > region_a_limit and i > 0:
                    split_idx = i
                    if output_func:
                        output_func(f"  Split at pattern {i}: region A = {cumulative} bytes, "
                                    f"remaining patterns → region B\n")
                    break
                cumulative += ptn_size
        
        # Write pattern data for region A (up to split_idx)
        for i, event_bytes in encoded_patterns[:split_idx]:
            lines.append("")
            lines.append(f"PTN_{i}:")
            if not event_bytes:
                lines.append("    .byte $FF  ; Empty pattern")
            else:
                for j in range(0, len(event_bytes), 16):
                    chunk = event_bytes[j:j+16]
                    hex_bytes = ','.join(f'${b:02X}' for b in chunk)
                    lines.append(f"    .byte {hex_bytes}")
        
        lines.append("")
        if split_idx < num_patterns:
            lines.append(f"; === END OF SONG DATA REGION A ({split_idx} of {num_patterns} patterns) ===")
            lines.append(f"; Remaining {num_patterns - split_idx} patterns in SONG_DATA_2.asm (region B)")
        else:
            lines.append("; === END OF SONG DATA ===")
        
        # Write SONG_DATA.asm
        with open(output_path, 'w') as f:
            f.write('\n'.join(lines))
        
        # Generate SONG_DATA_2.asm (overflow patterns or empty stub)
        if region_a_limit > 0:
            lines2 = []
            lines2.append("; ==========================================================================")
            lines2.append("; SONG_DATA_2.asm - Overflow pattern data (Region B: $D800-$FBFF)")
            lines2.append("; ==========================================================================")
            
            if split_idx < num_patterns:
                lines2.append(f"; Patterns {split_idx}-{num_patterns-1} "
                              f"({num_patterns - split_idx} patterns)")
                lines2.append("")
                for i, event_bytes in encoded_patterns[split_idx:]:
                    lines2.append(f"PTN_{i}:")
                    if not event_bytes:
                        lines2.append("    .byte $FF  ; Empty pattern")
                    else:
                        for j in range(0, len(event_bytes), 16):
                            chunk = event_bytes[j:j+16]
                            hex_bytes = ','.join(f'${b:02X}' for b in chunk)
                            lines2.append(f"    .byte {hex_bytes}")
                    lines2.append("")
                lines2.append("; === END OF SONG DATA REGION B ===")
            else:
                lines2.append("; (All patterns fit in region A — no overflow)")
            
            path2 = output_path.replace("SONG_DATA.asm", "SONG_DATA_2.asm")
            with open(path2, 'w') as f:
                f.write('\n'.join(lines2))
        
        logger.info(f"Exported song data to {output_path}"
                     f" (split at pattern {split_idx}/{num_patterns})"
                     if split_idx < num_patterns else
                     f"Exported song data to {output_path}")
        return True, ""
        
    except Exception as e:
        logger.error(f"Failed to export song data: {e}")
        return False, str(e)


def _encode_pattern_events(pattern: Pattern, pattern_idx: int, instruments: list, output_func=None) -> List[int]:
    """Encode pattern rows to variable-length event format.
    
    Args:
        pattern: Pattern to encode
        pattern_idx: Pattern index for debug output
        instruments: List of Instrument objects (for base_note lookup)
        output_func: Optional function to call with debug output
    
    Returns list of bytes representing all events in the pattern.
    
    Note encoding (with PITCH_OFFSET=24 for extended 5-octave table):
        export_note = gui_note + PITCH_OFFSET - (base_note - 1)
        
        For default base_note=1 (non-MOD):
          GUI C-1 (1)  -> export 25 -> ASM idx 24 -> pitch 1.0x
          GUI C-3 (25) -> export 49 -> ASM idx 48 -> pitch 4.0x
        
        For MOD base_note=25 (sample pitched at C-3):
          GUI C-1 (1)  -> export  1 -> ASM idx  0 -> pitch 0.25x
          GUI C-3 (25) -> export 25 -> ASM idx 24 -> pitch 1.0x
    """
    PITCH_OFFSET = 24  # must match pitch_tables.asm
    
    events = []
    last_inst = -1
    last_vol = -1
    
    if output_func:
        output_func(f"\n  Pattern {pattern_idx} (length={pattern.length}):\n")
        output_func(f"    NOTE ENCODING: GUI note -> export byte -> ASM pitch index\n")
    logger.debug(f"Encoding pattern {pattern_idx}: length={pattern.length}")
    
    for row_num, row in enumerate(pattern.rows):
        if row_num >= pattern.length:
            break
            
        if row.note == 0:
            continue  # Skip empty rows
        
        # Handle NOTE_OFF (255 in GUI -> 0 in ASM for silence)
        if row.note == 255:  # NOTE_OFF
            note = 0  # ASM player treats note 0 as note-off
        elif row.note == 254:  # VOL_CHANGE
            note = 61  # ASM: volume-only event, no retrigger
        else:
            # Apply base_note pitch correction:
            # Samples are resampled to POKEY rate, so base_note should map to 1.0x pitch.
            # PITCH_OFFSET shifts the table so index 24 = 1.0x.
            inst_idx = row.instrument
            base_note = 1  # default
            if 0 <= inst_idx < len(instruments):
                base_note = getattr(instruments[inst_idx], 'base_note', 1)
            
            note = row.note + PITCH_OFFSET - (base_note - 1)
            note = max(1, min(note, 60))  # clamp to valid range (1-60)
        
        inst = row.instrument
        vol = row.volume
        
        # Convert note to display string for debug
        NOTE_NAMES = ['C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-']
        if note == 0:
            pitch_idx = -1  # N/A for note-off
        elif note == 61:
            pitch_idx = -1  # N/A for volume change
        else:
            # Show original GUI note for clarity
            gui_note = row.note
            gui_name = NOTE_NAMES[(gui_note-1) % 12] + str(((gui_note-1) // 12) + 1) if gui_note != 255 else "OFF"
            pitch_idx = note - 1
            pitch_mult = 2.0 ** ((pitch_idx - PITCH_OFFSET) / 12.0)
        
        if output_func:
            if note == 0:
                output_func(f"    Row {row_num:02d}: OFF inst={inst} vol={vol:2d}")
            elif note == 61:
                output_func(f"    Row {row_num:02d}: V-- vol={vol:2d}")
            else:
                output_func(f"    Row {row_num:02d}: {gui_name} (gui={gui_note:2d} export={note:2d} idx={pitch_idx:2d} pitch={pitch_mult:.3f}x) inst={inst} vol={vol:2d}")
        logger.debug(f"  Row {row_num}: note={note}, inst={inst}, vol={vol}")
        
        # First event in pattern must include inst+vol
        if last_inst == -1:
            # Full event: row, note|$80, inst|$80, vol
            events.append(row_num)
            events.append(note | 0x80)
            events.append(inst | 0x80)
            events.append(vol)
            if output_func:
                output_func(f" -> ${row_num:02X} ${note|0x80:02X} ${inst|0x80:02X} ${vol:02X}\n")
            logger.debug(f"    -> Full event: ${row_num:02X} ${note|0x80:02X} ${inst|0x80:02X} ${vol:02X}")
            last_inst = inst
            last_vol = vol
        elif note == 61 or inst != last_inst or vol != last_vol:
            # Instrument or volume changed
            if vol != last_vol:
                # Volume changed - must include inst byte too
                events.append(row_num)
                events.append(note | 0x80)
                events.append(inst | 0x80)
                events.append(vol)
                if output_func:
                    output_func(f" -> ${row_num:02X} ${note|0x80:02X} ${inst|0x80:02X} ${vol:02X}\n")
                logger.debug(f"    -> Vol changed: ${row_num:02X} ${note|0x80:02X} ${inst|0x80:02X} ${vol:02X}")
            else:
                # Only instrument changed
                events.append(row_num)
                events.append(note | 0x80)
                events.append(inst)
                if output_func:
                    output_func(f" -> ${row_num:02X} ${note|0x80:02X} ${inst:02X}\n")
                logger.debug(f"    -> Inst changed: ${row_num:02X} ${note|0x80:02X} ${inst:02X}")
            last_inst = inst
            last_vol = vol
        else:
            # Same inst+vol as before
            events.append(row_num)
            events.append(note)
            if output_func:
                output_func(f" -> ${row_num:02X} ${note:02X}\n")
            logger.debug(f"    -> Same: ${row_num:02X} ${note:02X}")
    
    # End marker
    events.append(0xFF)
    if output_func:
        output_func(f"    -> {len(events)} bytes total\n")
    logger.debug(f"  -> End marker, total {len(events)} bytes")
    
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
    
    # Try bundled/local bin directory first (works for both bundled and dev)
    mads_path = runtime.get_mads_path()
    if mads_path and os.path.isfile(mads_path):
        # Ensure executable on Unix
        if system != "Windows" and not os.access(mads_path, os.X_OK):
            try:
                os.chmod(mads_path, 0o755)
            except OSError:
                pass
        if os.access(mads_path, os.X_OK) or system == "Windows":
            return mads_path
    
    # Check in VQ converter's bin directory (legacy/fallback)
    if state.vq.result and state.vq.result.output_dir:
        vq_base = os.path.dirname(os.path.dirname(state.vq.result.output_dir))
        
        # Try platform-specific paths
        if system == "Linux":
            plat_dir = "linux_x86_64"
        elif system == "Darwin":
            plat_dir = "macos_aarch64" if "arm" in machine or "aarch" in machine else "macos_x86_64"
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
    
    # Check in app directory (for portable installs)
    app_dir = runtime.get_app_dir()
    local_mads = os.path.join(app_dir, binary)
    if os.path.isfile(local_mads) and os.access(local_mads, os.X_OK):
        return local_mads
    
    # Check PATH
    mads_path = shutil.which(binary)
    if mads_path:
        return mads_path
    
    return None


def _output(text: str):
    """Output text to both queue and console."""
    build_state.queue_output(text)
    print(text, end='', flush=True)  # flush=True ensures immediate output


# =============================================================================
# BANKING BUILD SUPPORT
# =============================================================================

def _estimate_data_sizes(build_dir: str, use_banking: bool) -> dict:
    """Estimate data sizes from generated ASM files by counting .byte directives.
    
    In banking mode, song data spans two regions:
      Region A ($8000-$CFFF): SONG_DATA.asm   — 20,480 bytes max
      Region B ($D800-$FBFF): SONG_DATA_2.asm —  9,216 bytes max
    All other tables are placed before $4000 and don't count.
    
    In 64KB mode, everything is contiguous from START_ADDRESS.
    
    Returns dict of {filename: byte_count} for data in the main region.
    """
    sizes = {}
    
    if use_banking:
        # Banking mode: song data split across two regions.
        # Both count against the total budget (29,696 bytes).
        data_files = ["SONG_DATA.asm", "SONG_DATA_2.asm"]
    else:
        # 64KB mode: everything is contiguous
        data_files = [
            "SONG_DATA.asm",
            "SAMPLE_DIR.asm",
            "VQ_LO.asm",
            "VQ_HI.asm",
            "VQ_BLOB.asm",
            "VQ_INDICES.asm",
            "RAW_SAMPLES.asm",
        ]
    
    for filename in data_files:
        filepath = os.path.join(build_dir, filename)
        if os.path.exists(filepath):
            byte_count = _count_asm_bytes(filepath)
            if byte_count > 0:
                sizes[filename] = byte_count
    
    if not use_banking:
        # Fixed overheads (player code + pitch tables + volume scale + staging)
        # Only relevant in 64KB mode where everything shares the address space
        sizes["player code+tables"] = 3800
        sizes["staging variables"] = 150
    
    return sizes


def _count_asm_bytes(filepath: str) -> int:
    """Count total bytes from .byte directives in an ASM file.
    
    Handles: .byte $XX,$YY,...  and  .byte <(expr),>(expr)  and .ds N
    Also accounts for .align $100 padding.
    """
    total = 0
    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            # Strip comments
            semi = stripped.find(';')
            if semi >= 0:
                stripped = stripped[:semi].strip()
            if not stripped:
                continue
            
            lower = stripped.lower()
            if '.byte' in lower:
                idx = lower.index('.byte')
                rest = stripped[idx + 5:].strip()
                if rest:
                    # Count comma-separated values
                    total += len([v for v in rest.split(',') if v.strip()])
            elif '.ds' in lower:
                # .ds N — reserve N bytes
                idx = lower.index('.ds')
                rest = stripped[idx + 3:].strip()
                try:
                    total += int(rest)
                except ValueError:
                    pass
            elif '.align' in lower:
                # .align $100 — worst case adds up to 255 bytes
                # Average: 128 bytes per alignment directive
                total += 128
    
    return total


def _parse_asm_bytes(filepath: str) -> bytes:
    """Parse .byte directives from an ASM file and return raw binary data."""
    data = bytearray()
    if not os.path.exists(filepath):
        return bytes(data)
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            # Handle comments
            idx = line.find(';')
            if idx >= 0:
                line = line[:idx].strip()
            if not line:
                continue
            # Find .byte directive
            lower = line.lower()
            if '.byte' in lower:
                # Extract the part after .byte
                byte_idx = lower.index('.byte')
                rest = line[byte_idx + 5:].strip()
                if not rest:
                    continue
                for val_str in rest.split(','):
                    val_str = val_str.strip()
                    if not val_str:
                        continue
                    try:
                        if val_str.startswith('$'):
                            data.append(int(val_str[1:], 16))
                        elif val_str.startswith('0x'):
                            data.append(int(val_str, 16))
                        else:
                            data.append(int(val_str))
                    except ValueError:
                        pass  # Skip expressions like <(label)
    return bytes(data)


def _extract_raw_blocks(filepath: str) -> dict:
    """Parse RAW_SAMPLES.asm and extract per-instrument byte arrays.
    
    Returns: {instrument_idx: bytes} for each RAW instrument.
    """
    blocks = {}
    if not os.path.exists(filepath):
        return blocks
    
    current_idx = None
    current_data = bytearray()
    
    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            # Strip trailing colon if present (MADS labels may or may not have it)
            label_candidate = stripped.rstrip(':')
            # Detect label: RAW_INST_NN or RAW_INST_NN_END (converter output)
            # Also support RAW_SAMPLES_N for backwards compat
            is_raw_label = (
                (label_candidate.startswith('RAW_INST_') or 
                 label_candidate.startswith('RAW_SAMPLES_'))
                and not '.byte' in stripped.lower()
                and not stripped.startswith(';')
            )
            if is_raw_label:
                if '_END' in label_candidate:
                    # End of block — save
                    if current_idx is not None and current_data:
                        blocks[current_idx] = bytes(current_data)
                    current_idx = None
                    current_data = bytearray()
                else:
                    # Start of new block — extract instrument index
                    try:
                        # Handle RAW_INST_00 or RAW_SAMPLES_0 format
                        if label_candidate.startswith('RAW_INST_'):
                            idx_str = label_candidate.replace('RAW_INST_', '')
                        else:
                            idx_str = label_candidate.replace('RAW_SAMPLES_', '')
                        current_idx = int(idx_str)
                        current_data = bytearray()
                    except ValueError:
                        current_idx = None
            elif current_idx is not None and '.byte' in stripped.lower():
                # Parse bytes
                idx = stripped.lower().index('.byte')
                rest = stripped[idx + 5:].split(';')[0].strip()
                for val_str in rest.split(','):
                    val_str = val_str.strip()
                    try:
                        if val_str.startswith('$'):
                            current_data.append(int(val_str[1:], 16))
                        elif val_str.startswith('0x'):
                            current_data.append(int(val_str, 16))
                        elif val_str.isdigit():
                            current_data.append(int(val_str))
                    except (ValueError, IndexError):
                        pass
    
    # Handle case where file doesn't have _END label for last block
    if current_idx is not None and current_data:
        blocks[current_idx] = bytes(current_data)
    
    return blocks


def _extract_vq_streams(vq_indices_path: str, sample_dir_path: str, 
                         n_instruments: int) -> dict:
    """Extract per-instrument VQ index streams.
    
    Parses VQ_INDICES.asm for the full blob, then uses byte-offset info
    from SAMPLE_DIR.asm (VQ_INDICES+$xxxx expressions) to slice per instrument.
    
    Returns: {instrument_idx: bytes} for each VQ instrument.
    """
    import re
    streams = {}
    
    # Parse full VQ indices blob
    all_indices = _parse_asm_bytes(vq_indices_path)
    if not all_indices:
        logger.debug("_extract_vq_streams: no VQ indices data found")
        return streams
    
    if not os.path.exists(sample_dir_path):
        logger.warning(f"_extract_vq_streams: SAMPLE_DIR not found: {sample_dir_path}")
        return streams
    
    with open(sample_dir_path, 'r') as f:
        content = f.read()
    
    # Walk through SAMPLE_DIR sections to find VQ instrument offsets.
    # Format: SAMPLE_START_LO section has lines like:
    #   .byte <(VQ_INDICES+$0000) ; inst_name ; VQ
    # The $xxxx is the full byte offset into VQ_INDICES.
    vq_start_offsets = {}  # inst_idx -> offset
    vq_end_offsets = {}    # inst_idx -> offset
    
    section = None  # 'start' or 'end'
    idx = 0
    
    for line in content.split('\n'):
        stripped = line.strip()
        
        # Detect section headers (label lines without .byte)
        if '.byte' not in stripped.lower():
            if 'SAMPLE_START_LO' in stripped and not stripped.startswith(';'):
                section = 'start'
                idx = 0
            elif 'SAMPLE_END_LO' in stripped and not stripped.startswith(';'):
                section = 'end'
                idx = 0
            elif any(h in stripped for h in ['SAMPLE_START_HI', 'SAMPLE_END_HI', 'SAMPLE_MODE']):
                if not stripped.startswith(';'):
                    section = None  # Skip HI sections (same offsets as LO)
            continue
        
        if section is None:
            continue
        
        # Extract offset from VQ_INDICES+$xxxx pattern
        match = re.search(r'VQ_INDICES\+\$([0-9A-Fa-f]+)', stripped)
        if match:
            offset = int(match.group(1), 16)
            if section == 'start':
                vq_start_offsets[idx] = offset
            elif section == 'end':
                vq_end_offsets[idx] = offset
        
        idx += 1
    
    # Slice VQ indices per instrument
    for inst_idx in vq_start_offsets:
        if inst_idx not in vq_end_offsets:
            logger.warning(f"VQ inst {inst_idx}: has start but no end offset")
            continue
        start = vq_start_offsets[inst_idx]
        end = vq_end_offsets[inst_idx]
        if end <= start:
            logger.warning(f"VQ inst {inst_idx}: end ({end}) <= start ({start})")
            continue
        if end > len(all_indices):
            logger.warning(f"VQ inst {inst_idx}: end ({end}) > indices size ({len(all_indices)})")
            end = len(all_indices)
        if start >= len(all_indices):
            continue
        streams[inst_idx] = all_indices[start:end]
    
    logger.info(f"Extracted {len(streams)} VQ streams from {len(all_indices)} bytes")
    return streams


def _parse_vq_blob(vq_blob_path: str) -> list:
    """Parse VQ_BLOB.asm to extract raw codebook bytes.
    
    Returns list of integers (raw AUDC bytes, typically $10|vol).
    """
    blob_bytes = []
    if not os.path.exists(vq_blob_path):
        return blob_bytes
    
    with open(vq_blob_path, 'r') as f:
        for line in f:
            stripped = line.strip()
            # Strip inline comments before parsing
            semi = stripped.find(';')
            if semi >= 0:
                stripped = stripped[:semi].strip()
            if not stripped:
                continue
            if stripped.startswith('.byte') or stripped.startswith('.BYTE'):
                # Parse .byte $XX,$XX,...
                data_part = stripped[5:].strip()
                for token in data_part.split(','):
                    token = token.strip()
                    if not token:
                        continue
                    try:
                        if token.startswith('$'):
                            blob_bytes.append(int(token[1:], 16))
                        elif token.startswith('0x'):
                            blob_bytes.append(int(token, 16))
                        else:
                            blob_bytes.append(int(token))
                    except ValueError:
                        continue
    return blob_bytes


def _get_vec_size_from_cfg(vq_output_dir: str) -> int:
    """Read MIN_VECTOR from VQ_CFG.asm to determine vector size."""
    cfg_path = os.path.join(vq_output_dir, "VQ_CFG.asm")
    if not os.path.exists(cfg_path):
        return 8  # default
    with open(cfg_path, 'r') as f:
        for line in f:
            if 'MIN_VECTOR' in line and '=' in line:
                parts = line.split('=')
                if len(parts) >= 2:
                    try:
                        return int(parts[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
    return 8


def _reencode_bank_vq(bank_vq_indices: bytes, global_codebook: list,
                      vec_size: int, n_iter: int = 20) -> tuple:
    """Re-encode VQ index stream with a per-bank codebook.
    
    Takes the original indices (referencing the global codebook),
    reconstructs the audio vectors, trains a bank-specific 256-entry
    codebook via k-means, and re-encodes all vectors.
    
    If near-silent vectors exist, codebook[0] is reserved for silence.
    
    Args:
        bank_vq_indices: Raw VQ index bytes from this bank
        global_codebook: Global codebook as flat byte list
                        (256 entries × vec_size bytes each)
        vec_size: Samples per codebook vector (e.g. 4, 8)
        n_iter: K-means iterations
    
    Returns:
        (codebook_bytes, reencoded_indices) where:
         codebook_bytes: 256 * vec_size bytes (per-bank codebook, AUDC-ready)
         reencoded_indices: bytes (same length as bank_vq_indices)
    """
    import numpy as np
    
    n_codes = 256
    indices = np.frombuffer(bank_vq_indices, dtype=np.uint8)
    n_indices = len(indices)
    
    if n_indices == 0:
        # Empty bank — return silence codebook ($10 = AUDC vol 0) + empty indices
        return bytes([0x10] * (n_codes * vec_size)), b''
    
    # Validate global codebook has enough data
    codebook_len = len(global_codebook)
    if codebook_len < vec_size:
        # Codebook too small or empty — can't reconstruct vectors
        logger.warning(f"Global codebook too small ({codebook_len} bytes, "
                       f"need {vec_size}+). Returning silence codebook.")
        silence_cb = bytes([0x10] * (n_codes * vec_size))
        # Map all indices to 0 (silence)
        return silence_cb, bytes(n_indices)
    
    # Reconstruct vectors from global codebook
    # global_codebook is flat: entry i = global_codebook[i*vec_size : (i+1)*vec_size]
    vectors = np.zeros((n_indices, vec_size), dtype=np.uint8)
    for i, idx in enumerate(indices):
        start = int(idx) * vec_size
        end = start + vec_size
        if end <= codebook_len:
            entry = global_codebook[start:end]
            # Defensive: verify we actually got vec_size bytes
            if len(entry) == vec_size:
                vectors[i] = entry
            else:
                vectors[i] = 0x10  # silence fallback
    
    # Strip AUDC $10 mask — work with volume nibbles (0-15) for k-means
    volumes = (vectors & 0x0F).astype(np.float32)
    
    # Silence detection (adapted from stream player)
    max_level = 15  # POKEY volume range 0-15
    thresh = max(1, max_level // 15)  # ~1
    if vec_size >= 16:
        thresh = max(thresh, 2)
    near_silent_mask = np.all(volumes <= thresh, axis=1)
    n_near_silent = int(near_silent_mask.sum())
    
    if n_near_silent > 0 and n_near_silent < n_indices:
        # Reserve codebook[0] for silence, train 255 entries on non-silent
        non_silent = volumes[~near_silent_mask]
        cb_rest = _bank_kmeans(non_silent, n_codes - 1, n_iter, max_level)
        
        codebook_vol = np.zeros((n_codes, vec_size), dtype=np.float32)
        codebook_vol[1:n_codes] = cb_rest[:n_codes - 1]
    elif n_near_silent == n_indices:
        # Entire bank is silent
        codebook_vol = np.zeros((n_codes, vec_size), dtype=np.float32)
    else:
        # No silence — use all 256 codes
        codebook_vol = _bank_kmeans(volumes, n_codes, n_iter, max_level)
    
    # Quantize codebook to integer volumes (0-15)
    codebook_int = np.clip(np.round(codebook_vol), 0, max_level).astype(np.uint8)
    
    # Re-encode: assign each vector to nearest codebook entry
    cb_f = codebook_int.astype(np.float32)
    chunk_size = min(50000, n_indices)
    assignments = np.empty(n_indices, dtype=np.uint8)
    for s in range(0, n_indices, chunk_size):
        e = min(s + chunk_size, n_indices)
        d = np.sum((volumes[s:e, None, :] - cb_f[None, :, :]) ** 2, axis=2)
        assignments[s:e] = np.argmin(d, axis=1).astype(np.uint8)
    
    # Build final codebook bytes with $10 AUDC mask
    codebook_bytes = bytearray(n_codes * vec_size)
    for i in range(n_codes):
        for j in range(vec_size):
            codebook_bytes[i * vec_size + j] = 0x10 | codebook_int[i, j]
    
    return bytes(codebook_bytes), assignments.tobytes()


def _bank_kmeans(vectors, n_codes, n_iter, max_level):
    """K-means clustering for per-bank VQ codebook.
    
    Args:
        vectors: (N, vec_size) float32 array of volume vectors
        n_codes: Number of codebook entries to produce
        n_iter: Max iterations
        max_level: Maximum volume value (for clamping)
    
    Returns:
        (n_codes, vec_size) float32 codebook
    """
    import numpy as np
    
    n_vecs, vec_size = vectors.shape
    
    if n_vecs == 0:
        # No vectors to cluster — return silence codebook
        return np.zeros((n_codes, vec_size), dtype=np.float32)
    
    vf = vectors.astype(np.float32)
    
    if n_vecs <= n_codes:
        rng = np.random.RandomState(42)
        codebook = np.zeros((n_codes, vec_size), dtype=np.float32)
        codebook[:n_vecs] = vf
        for i in range(n_vecs, n_codes):
            codebook[i] = vf[rng.randint(n_vecs)]
        return codebook
    
    # K-means++ init
    rng = np.random.RandomState(42)
    indices = [rng.randint(n_vecs)]
    for _ in range(1, min(n_codes, n_vecs)):
        cb_so_far = vf[indices]
        dists = np.min(
            np.sum((vf[:, None, :] - cb_so_far[None, :, :]) ** 2, axis=2),
            axis=1)
        total = dists.sum()
        if total < 1e-30:
            probs = np.ones(n_vecs) / n_vecs
        else:
            probs = dists / total
            probs = probs / probs.sum()
        indices.append(rng.choice(n_vecs, p=probs))
    
    codebook = vf[indices].copy()
    chunk_size = min(50000, n_vecs)
    
    for iteration in range(n_iter):
        # Assign
        assignments = np.empty(n_vecs, dtype=np.int32)
        for s in range(0, n_vecs, chunk_size):
            e = min(s + chunk_size, n_vecs)
            d = np.sum((vf[s:e, None, :] - codebook[None, :, :]) ** 2, axis=2)
            assignments[s:e] = np.argmin(d, axis=1)
        
        # Update centroids
        new_cb = codebook.copy()
        for c in range(n_codes):
            members = vf[assignments == c]
            if len(members) > 0:
                new_cb[c] = np.mean(members, axis=0)
        
        if np.allclose(new_cb, codebook, atol=0.01):
            codebook = new_cb
            break
        codebook = new_cb
    
    return codebook


def _generate_banking_vq_tables(build_dir: str, vec_size: int):
    """Generate VQ_LO.asm and VQ_HI.asm for banking mode.
    
    In banking mode, codebook entries are at $4000 + index * vec_size
    within the bank window.
    """
    bank_base = 0x4000
    
    # VQ_LO.asm
    lines = ["; VQ_LO.asm - Banking mode (per-bank codebook at $4000)"]
    lines.append(f"VQ_LO_LEN = 256")
    lines.append("VQ_LO")
    for i in range(0, 256, 8):
        vals = []
        for j in range(8):
            idx = i + j
            addr = bank_base + idx * vec_size
            vals.append(f"${addr & 0xFF:02X}")
        lines.append(f" .byte {','.join(vals)}")
    
    with open(os.path.join(build_dir, "VQ_LO.asm"), 'w') as f:
        f.write('\n'.join(lines))
    
    # VQ_HI.asm
    lines = ["; VQ_HI.asm - Banking mode (per-bank codebook at $4000)"]
    lines.append(f"VQ_HI_LEN = 256")
    lines.append("VQ_HI")
    for i in range(0, 256, 8):
        vals = []
        for j in range(8):
            idx = i + j
            addr = bank_base + idx * vec_size
            vals.append(f"${(addr >> 8) & 0xFF:02X}")
        lines.append(f" .byte {','.join(vals)}")
    
    with open(os.path.join(build_dir, "VQ_HI.asm"), 'w') as f:
        f.write('\n'.join(lines))


def _generate_banking_build(build_dir: str, vq_output_dir: str,
                            song: Song, output_func=None) -> Optional[str]:
    """Generate banking build files with per-bank VQ codebooks.
    
    Each bank stores its own 256-entry codebook at $4000, trained via
    k-means on that bank's audio content. This dramatically improves
    VQ quality vs. a single global codebook.
    
    Returns error message on failure, None on success.
    """
    from constants import MEMORY_CONFIGS
    from bank_packer import pack_into_banks, generate_bank_asm, BANK_SIZE, BANK_BASE, DBANK_TABLE
    
    _out = output_func or _output
    
    # Determine available banks
    max_banks = 4  # default to 130XE
    for name, banks, _ in MEMORY_CONFIGS:
        if name == song.memory_config:
            max_banks = banks
            break
    
    _out(f"\n  Banking mode: {song.memory_config} ({max_banks} banks)\n")
    
    # Get vector size for codebook overhead calculation
    vec_size = _get_vec_size_from_cfg(vq_output_dir)
    codebook_size = 256 * vec_size  # bytes reserved at start of each bank
    _out(f"  Per-bank codebook: {codebook_size} bytes (vec_size={vec_size})\n")
    
    # Parse global codebook from VQ_BLOB.asm (needed for per-bank re-encoding)
    vq_blob_path = os.path.join(build_dir, "VQ_BLOB.asm")
    global_codebook = _parse_vq_blob(vq_blob_path)
    if global_codebook:
        _out(f"  Global codebook: {len(global_codebook)} bytes "
             f"({len(global_codebook) // vec_size} entries)\n")
    
    # Extract per-instrument binary data
    _out("  Extracting sample data from converter output...\n")
    
    vq_indices_path = os.path.join(vq_output_dir, "VQ_INDICES.asm")
    raw_samples_path = os.path.join(vq_output_dir, "RAW_SAMPLES.asm")
    sample_dir_path = os.path.join(vq_output_dir, "SAMPLE_DIR.asm")
    
    n_inst = len(song.instruments)
    
    # Get VQ stream data per instrument
    vq_streams = _extract_vq_streams(vq_indices_path, sample_dir_path, n_inst)
    
    # Get RAW data per instrument
    raw_blocks = _extract_raw_blocks(raw_samples_path)
    
    # Determine which instruments are VQ vs RAW
    inst_sizes = []
    for i in range(n_inst):
        if i in vq_streams:
            inst_sizes.append((i, len(vq_streams[i])))
            _out(f"    Inst {i}: VQ, {len(vq_streams[i])} bytes\n")
        elif i in raw_blocks:
            inst_sizes.append((i, len(raw_blocks[i])))
            _out(f"    Inst {i}: RAW, {len(raw_blocks[i])} bytes\n")
        else:
            inst_sizes.append((i, 0))
    
    # Build set of VQ instrument indices for two-phase packing.
    # VQ banks get codebook overhead, RAW banks use full 16KB.
    vq_set = set(vq_streams.keys())
    n_raw = sum(1 for idx, sz in inst_sizes if sz > 0 and idx not in vq_set)
    if vq_set:
        _out(f"  VQ instruments: {len(vq_set)} → banks with "
             f"{codebook_size}B codebook\n")
        _out(f"  RAW instruments: {n_raw} → "
             f"full 16KB banks\n")
    else:
        _out("  All instruments RAW — no codebook overhead\n")
    
    # Append BANK_CODEBOOK_BYTES to VQ_CFG.asm in build dir.
    # VQ_CFG.asm is included before tracker_irq_banked.asm, so this
    # constant is available when the IRQ handler computes CODEBOOK_SIZE.
    # Note: this is the VQ codebook size (may be 0 if no VQ instruments).
    effective_cb = codebook_size if vq_set else 0
    vq_cfg_build = os.path.join(build_dir, "VQ_CFG.asm")
    if os.path.exists(vq_cfg_build):
        # Read existing config
        with open(vq_cfg_build, 'r') as f:
            cfg_lines = f.readlines()
        
        def _defines_label(lines, label):
            """True if any active (non-comment) line is an assignment of `label`."""
            for l in lines:
                stripped = l.strip()
                if stripped.startswith(';'):
                    continue
                # Strip inline comment
                semi = stripped.find(';')
                code = stripped[:semi].strip() if semi >= 0 else stripped
                if not code.startswith(label):
                    continue
                # Ensure we matched the full label (not a prefix like
                # MIN_VECTOR_NOTE) by checking the next char is whitespace or '='
                rest = code[len(label):]
                if rest and rest.lstrip().startswith('='):
                    return True
            return False
        
        # Track which constants already exist
        has_min_vector = _defines_label(cfg_lines, 'MIN_VECTOR')
        has_algo_fixed = _defines_label(cfg_lines, 'ALGO_FIXED')
        has_multi_sample = _defines_label(cfg_lines, 'MULTI_SAMPLE')
        has_pitch_control = _defines_label(cfg_lines, 'PITCH_CONTROL')
        
        with open(vq_cfg_build, 'w') as f:
            for line in cfg_lines:
                stripped = line.strip()
                # Strip converter's CODEBOOK_SIZE — tracker_irq_banked.asm
                # is the single source of truth (derives CODEBOOK_SIZE from
                # BANK_CODEBOOK_BYTES).  MADS labels are immutable, so
                # having both would cause "Label declared twice" errors.
                if (stripped.startswith("CODEBOOK_SIZE") and
                        stripped[len("CODEBOOK_SIZE"):].lstrip().startswith('=')):
                    f.write(f"; {stripped}  ; (overridden by BANK_CODEBOOK_BYTES below)\n")
                else:
                    f.write(line)
            
            f.write(f"\n; === Tracker build pipeline additions ===\n")
            f.write(f"BANK_CODEBOOK_BYTES = {effective_cb}\n")
            
            # Ensure tracker-required constants exist.
            # The VQ converter omits these when algo=raw (all instruments
            # are RAW samples). The tracker player needs them for the
            # mixed VQ/RAW code paths even if VQ is never used at runtime.
            if not has_min_vector:
                f.write(f"MIN_VECTOR = {vec_size}  ; (added by tracker build — "
                        f"converter omitted for raw-only)\n")
            if not has_algo_fixed:
                f.write(f"ALGO_FIXED = 1  ; (required by tracker player)\n")
            if not has_multi_sample:
                f.write(f"MULTI_SAMPLE = 1  ; (required by tracker player)\n")
            if not has_pitch_control:
                f.write(f"PITCH_CONTROL = 1  ; (required by tracker player)\n")
    
    # Pack into banks (two-phase: VQ with codebook, RAW without)
    _out("  Packing into banks...\n")
    pack_result = pack_into_banks(inst_sizes, max_banks,
                                  codebook_size=codebook_size,
                                  vq_instruments=vq_set)
    
    if not pack_result.success:
        # Find the smallest config that would work
        total = sum(sz for _, sz in inst_sizes if sz > 0)
        suggested_cfg = None
        
        for cfg_name, cfg_banks, cfg_desc in MEMORY_CONFIGS:
            if cfg_banks <= max_banks or cfg_banks == 0:
                continue  # skip smaller/equal configs and 64KB
            
            test_result = pack_into_banks(inst_sizes, cfg_banks,
                                          codebook_size=codebook_size,
                                          vq_instruments=vq_set)
            if test_result.success:
                suggested_cfg = (cfg_name, cfg_banks)
                break
        
        if suggested_cfg:
            cfg_name, cfg_banks = suggested_cfg
            _out(f"\n  Sample data ({total:,} bytes) does not fit "
                 f"in {song.memory_config} ({max_banks} banks).\n")
            _out(f"  Minimum required: {cfg_name} ({cfg_banks} banks).\n")
            _out(f"\n  Change Memory setting to \"{cfg_name}\" or higher "
                 f"and rebuild.\n")
            # Return special UPGRADE: prefix so build_xex_sync can offer
            # the user an interactive upgrade dialog
            return (f"UPGRADE:{cfg_name}:{cfg_banks}:{total}:"
                    f"{song.memory_config}")
        else:
            # Even max config won't fit — give detailed breakdown
            max_cfg = MEMORY_CONFIGS[-1]
            max_cap = max_cfg[1] * (BANK_SIZE - codebook_size)
            _out(f"\n  Sample data ({total:,} bytes) does not fit in any "
                 f"memory configuration.\n")
            _out(f"  Even {max_cfg[0]} ({max_cfg[1]} banks, "
                 f"{max_cap // 1024}KB effective) is not enough.\n")
            _out(f"  Reduce sample lengths, convert more instruments to VQ,\n")
            _out(f"  or lower the sample rate.\n")
            return (f"Sample data too large ({total:,} bytes / "
                    f"{total // 1024}KB).\n\n"
                    f"Even {max_cfg[0]} ({max_cfg[1]} banks, "
                    f"{max_cap // 1024}KB effective) is not enough.\n\n"
                    f"To fix: reduce sample lengths, convert more "
                    f"instruments to VQ, or lower the sample rate.")
    
    _out(f"    Used {pack_result.n_banks_used} of {max_banks} banks\n")
    for bi, util in enumerate(pack_result.bank_utilization):
        _out(f"    Bank {bi}: {util*100:.0f}% full\n")
    
    # Per-bank VQ re-encoding
    bank_codebooks = {}  # bank_idx -> codebook_bytes (256*vec_size)
    bank_reencoded = {}  # (inst_idx, bank_idx) -> reencoded_bytes
    
    if vq_streams and not global_codebook:
        logger.warning("VQ instruments found but global codebook is empty — "
                       "per-bank re-encoding skipped, audio quality will suffer")
        _out("  WARNING: Could not parse VQ_BLOB.asm — per-bank codebooks disabled\n")
    
    if global_codebook and vq_streams:
        _out("  Per-bank VQ re-encoding...\n")        
        # bank_raw_indices: concatenated original indices per bank (for training)
        # bank_chunk_order: tracks (inst_idx, chunk_len) per bank in concat order
        bank_raw_indices = {}  # bank_idx -> bytearray
        bank_chunk_order = {}  # bank_idx -> [(inst_idx, chunk_len), ...]
        
        # Group VQ instrument data by bank
        for inst_idx in sorted(vq_streams.keys()):
            stream = vq_streams[inst_idx]
            if inst_idx not in pack_result.placements:
                continue
            p = pack_result.placements[inst_idx]
            
            effective_bank_size = BANK_SIZE - codebook_size
            remaining = bytearray(stream)
            
            for bi_offset, bank_idx in enumerate(p.bank_indices):
                chunk_size = min(len(remaining), effective_bank_size)
                if chunk_size == 0:
                    break  # no more data to pack
                chunk = bytes(remaining[:chunk_size])
                remaining = remaining[chunk_size:]
                
                if bank_idx not in bank_raw_indices:
                    bank_raw_indices[bank_idx] = bytearray()
                    bank_chunk_order[bank_idx] = []
                bank_raw_indices[bank_idx].extend(chunk)
                bank_chunk_order[bank_idx].append((inst_idx, len(chunk)))
        
        # Train per-bank codebooks and re-encode
        for bank_idx in sorted(bank_raw_indices.keys()):
            all_bank_indices = bytes(bank_raw_indices[bank_idx])
            if not all_bank_indices:
                continue  # skip banks with no VQ data
            try:
                cb_bytes, reencoded = _reencode_bank_vq(
                    all_bank_indices, global_codebook, vec_size)
            except Exception as e:
                logger.error(f"VQ re-encoding failed for bank {bank_idx}: {e}",
                             exc_info=True)
                _out(f"  WARNING: Bank {bank_idx} VQ re-encoding failed: {e}\n")
                _out(f"           Using global codebook (lower quality)\n")
                # Fallback: use global codebook bytes directly
                cb_bytes = bytes(global_codebook[:256 * vec_size])
                if len(cb_bytes) < 256 * vec_size:
                    cb_bytes += bytes([0x10] * (256 * vec_size - len(cb_bytes)))
                reencoded = all_bank_indices  # keep original indices
            bank_codebooks[bank_idx] = cb_bytes
            
            # Split re-encoded indices back in the SAME order they were concatenated
            pos = 0
            for inst_idx, chunk_len in bank_chunk_order[bank_idx]:
                key = (inst_idx, bank_idx)
                bank_reencoded[key] = reencoded[pos:pos + chunk_len]
                pos += chunk_len
            
            _out(f"    Bank {bank_idx}: re-encoded {len(all_bank_indices)} indices\n")
    
    # Generate BANK_CFG.asm
    bank_cfg_asm = generate_bank_asm(pack_result, n_inst,
                                      codebook_bytes=codebook_size,
                                      vq_instruments=vq_set)
    bank_cfg_path = os.path.join(build_dir, "BANK_CFG.asm")
    with open(bank_cfg_path, 'w') as f:
        f.write(bank_cfg_asm)
    _out(f"    + BANK_CFG.asm\n")
    
    # Generate banking-aware SAMPLE_DIR.asm with absolute $4000+ addresses
    _generate_bank_sample_dir(build_dir, n_inst, pack_result, 
                               vq_streams, raw_blocks, song)
    _out(f"    + SAMPLE_DIR.asm (banking)\n")
    
    # Generate per-bank data files (with codebook prefix)
    _generate_bank_data_files(build_dir, pack_result, vq_streams, raw_blocks,
                               bank_codebooks, bank_reencoded, codebook_size)
    n_vq_banks = sum(pack_result.bank_has_codebook) if pack_result.bank_has_codebook else 0
    if n_vq_banks > 0:
        _out(f"    + {pack_result.n_banks_used} BANK_DATA files "
             f"({n_vq_banks} VQ with codebook, "
             f"{pack_result.n_banks_used - n_vq_banks} RAW)\n")
    else:
        _out(f"    + {pack_result.n_banks_used} BANK_DATA files (all RAW, no codebook)\n")
    
    # Generate banking-mode VQ_LO/VQ_HI (pointing to $4000+ codebook in bank)
    _generate_banking_vq_tables(build_dir, vec_size)
    _out(f"    + VQ_LO.asm, VQ_HI.asm (banking mode, codebook at $4000)\n")
    
    # Generate bank_loader.asm (top-level source for MADS)
    _generate_bank_loader(build_dir, pack_result)
    _out(f"    + bank_loader.asm\n")
    
    # Copy mem_detect.asm to build dir
    our_asm_dir = runtime.get_asm_dir()
    banking_src = os.path.join(our_asm_dir, "banking")
    banking_dst = os.path.join(build_dir, "banking")
    if os.path.isdir(banking_src):
        os.makedirs(banking_dst, exist_ok=True)
        for fn in os.listdir(banking_src):
            shutil.copy2(os.path.join(banking_src, fn), banking_dst)
        _out(f"    + banking/\n")
    
    # Generate MEM_ERR_TEXT.asm with config-specific error screen
    # Goes in build_dir/ (not banking/) because bank_loader.asm includes
    # it at the top level: icl 'MEM_ERR_TEXT.asm'
    _generate_mem_err_text(build_dir, song.memory_config,
                           pack_result.n_banks_used, song.title)
    _out(f"    + MEM_ERR_TEXT.asm\n")
    
    return None  # Success


def _generate_bank_sample_dir(build_dir: str, n_inst: int,
                                pack_result, vq_streams: dict, 
                                raw_blocks: dict, song: Song):
    """Generate SAMPLE_DIR.asm with absolute addresses for banking mode."""
    from bank_packer import BANK_BASE, BANK_SIZE
    
    lines = []
    lines.append("; SAMPLE_DIR.asm - Banking Mode (absolute addresses in bank window)")
    lines.append("; Generated by POKEY VQ Tracker")
    lines.append("")
    lines.append(f"SAMPLE_COUNT = {n_inst}")
    lines.append("")
    
    # Compute addresses for each instrument
    # In banking mode:
    #   - stream start/end are addresses within the bank window ($4000-$7FFF)
    #   - For multi-bank samples, start=$4000, end=end address in LAST bank
    
    start_addrs = []
    end_addrs = []
    modes = []
    
    for i in range(n_inst):
        if i in pack_result.placements:
            p = pack_result.placements[i]
            start_addrs.append(p.offset)  # $4000 + codebook_size + offset
            
            # Use pre-computed end address from bank_packer
            # (already accounts for codebook_size in multi-bank case)
            end_addr = (p.end_addr_hi << 8) | p.end_addr_lo
            end_addrs.append(end_addr)
            
            # Mode: VQ if in vq_streams, RAW if in raw_blocks
            if i in vq_streams:
                modes.append(0)
            else:
                modes.append(0xFF)
        else:
            # Unused instrument: safe sentinel (start == end → immediate silence)
            start_addrs.append(BANK_BASE)
            end_addrs.append(BANK_BASE)
            modes.append(0)
    
    # SAMPLE_START_LO
    lines.append("SAMPLE_START_LO:")
    for i in range(n_inst):
        lines.append(f" .byte ${start_addrs[i] & 0xFF:02X}")
    lines.append("")
    
    # SAMPLE_START_HI
    lines.append("SAMPLE_START_HI:")
    for i in range(n_inst):
        lines.append(f" .byte ${(start_addrs[i] >> 8) & 0xFF:02X}")
    lines.append("")
    
    # SAMPLE_END_LO
    lines.append("SAMPLE_END_LO:")
    for i in range(n_inst):
        lines.append(f" .byte ${end_addrs[i] & 0xFF:02X}")
    lines.append("")
    
    # SAMPLE_END_HI
    lines.append("SAMPLE_END_HI:")
    for i in range(n_inst):
        lines.append(f" .byte ${(end_addrs[i] >> 8) & 0xFF:02X}")
    lines.append("")
    
    # SAMPLE_MODE
    lines.append("SAMPLE_MODE:")
    for i in range(n_inst):
        lines.append(f" .byte ${modes[i]:02X}")
    
    with open(os.path.join(build_dir, "SAMPLE_DIR.asm"), 'w') as f:
        f.write('\n'.join(lines))


def _generate_bank_data_files(build_dir: str, pack_result, 
                                vq_streams: dict, raw_blocks: dict,
                                bank_codebooks: dict = None,
                                bank_reencoded: dict = None,
                                codebook_size: int = 0):
    """Generate BANK_DATA_N.asm files with per-bank codebooks.
    
    VQ bank layout (when codebook_size > 0 and bank has VQ data):
      $4000 + 0                    : codebook (256 * vec_size bytes)
      $4000 + codebook_size        : VQ index data
      ...up to $7FFF
    
    RAW bank layout (no codebook overhead):
      $4000 + 0                    : RAW sample data
      ...up to $7FFF
    
    For VQ instruments, uses re-encoded indices (bank_reencoded) that
    reference the per-bank codebook instead of the global one.
    """
    from bank_packer import BANK_SIZE, BANK_BASE
    
    if bank_codebooks is None:
        bank_codebooks = {}
    if bank_reencoded is None:
        bank_reencoded = {}
    
    # Build per-bank byte arrays
    n_banks = pack_result.n_banks_used
    bank_data = [bytearray() for _ in range(n_banks)]
    
    # Determine which banks have codebook from pack result
    has_cb = pack_result.bank_has_codebook if pack_result.bank_has_codebook else []
    
    # Step 1: Prepend codebook ONLY to VQ banks (bank_has_codebook=True)
    for bank_idx in range(n_banks):
        is_vq_bank = bank_idx < len(has_cb) and has_cb[bank_idx]
        if codebook_size > 0 and is_vq_bank:
            if bank_idx in bank_codebooks:
                cb = bank_codebooks[bank_idx]
                if len(cb) < codebook_size:
                    cb = cb + bytes(codebook_size - len(cb))  # pad
                bank_data[bank_idx] = bytearray(cb[:codebook_size])
            else:
                # VQ bank but no codebook trained — fill with silence
                bank_data[bank_idx] = bytearray([0x10] * codebook_size)
        # RAW-only banks: no codebook prefix, data starts at $4000
    
    # Sort placements by (first_bank, offset) for correct write ordering
    sorted_placements = sorted(
        pack_result.placements.values(),
        key=lambda p: (p.bank_indices[0], p.offset)
    )
    
    for p in sorted_placements:
        inst_idx = p.inst_idx
        is_vq = inst_idx in vq_streams
        
        if p.n_banks == 1:
            bank_idx = p.bank_indices[0]
            
            # Use re-encoded data if available
            key = (inst_idx, bank_idx)
            if is_vq and key in bank_reencoded:
                data = bank_reencoded[key]
            elif is_vq:
                data = vq_streams[inst_idx]
            elif inst_idx in raw_blocks:
                data = raw_blocks[inst_idx]
            else:
                logger.warning(f"Bank data: inst {inst_idx} placed but no data found")
                continue
            
            # Offset within bank (already accounts for codebook via bank_packer)
            offset_in_bank = p.offset - BANK_BASE
            while len(bank_data[bank_idx]) < offset_in_bank:
                bank_data[bank_idx].append(0)
            bank_data[bank_idx].extend(data)
            if len(bank_data[bank_idx]) > BANK_SIZE:
                logger.error(f"Bank {bank_idx} overflow: {len(bank_data[bank_idx])} > {BANK_SIZE}")
        else:
            # Multi-bank: per-instrument effective size depends on VQ vs RAW
            inst_cb = codebook_size if is_vq else 0
            effective_bank_size = BANK_SIZE - inst_cb
            
            if is_vq:
                # Use per-bank re-encoded data
                for bi in p.bank_indices:
                    key = (inst_idx, bi)
                    if key in bank_reencoded:
                        chunk = bank_reencoded[key]
                    else:
                        # Fallback: slice from original stream
                        bi_offset = p.bank_indices.index(bi)
                        start = bi_offset * effective_bank_size
                        chunk = vq_streams[inst_idx][start:start + effective_bank_size]
                    bank_data[bi].extend(chunk)
                    if len(bank_data[bi]) > BANK_SIZE:
                        logger.error(f"Bank {bi} overflow: {len(bank_data[bi])} > {BANK_SIZE}")
            elif inst_idx in raw_blocks:
                remaining = bytearray(raw_blocks[inst_idx])
                for bi in p.bank_indices:
                    chunk_size = min(len(remaining), effective_bank_size)
                    chunk = remaining[:chunk_size]
                    remaining = remaining[chunk_size:]
                    bank_data[bi].extend(chunk)
                    if len(bank_data[bi]) > BANK_SIZE:
                        logger.error(f"Bank {bi} overflow: {len(bank_data[bi])} > {BANK_SIZE}")
            else:
                logger.warning(f"Bank data: inst {inst_idx} placed but no data found")
    
    # Write .asm files
    for bank_idx in range(n_banks):
        data = bank_data[bank_idx]
        is_vq_bank = bank_idx < len(has_cb) and has_cb[bank_idx]
        lines = []
        if is_vq_bank and codebook_size > 0:
            data_bytes = len(data) - codebook_size
            lines.append(f"; BANK_DATA_{bank_idx}.asm - Bank {bank_idx} VQ "
                        f"(codebook: {codebook_size}B + data: {data_bytes}B)")
        else:
            lines.append(f"; BANK_DATA_{bank_idx}.asm - Bank {bank_idx} RAW "
                        f"({len(data)}B data)")
        lines.append(f"; {len(data)} bytes total")
        lines.append("")
        
        # Write .byte lines (16 bytes per line)
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_vals = ','.join(f'${b:02X}' for b in chunk)
            lines.append(f" .byte {hex_vals}")
        
        path = os.path.join(build_dir, f"BANK_DATA_{bank_idx}.asm")
        with open(path, 'w') as f:
            f.write('\n'.join(lines))


def _generate_song_info(build_dir: str, song_title: str, song_author: str):
    """Generate SONG_INFO.asm — song name and author for splash screen.
    
    Produces two contiguous 40-byte text lines (ANTIC Mode 2 screen codes
    via dta d) that are the FIRST two lines on screen.
    
    Args:
        build_dir: Build directory (MADS CWD)
        song_title: Song title (will be uppercased and sanitized)
        song_author: Song author (will be uppercased and sanitized)
    """
    def _sanitize_line(text, max_len=40):
        """Sanitize and center text for MADS dta d: uppercase, safe ATASCII."""
        if not text or not text.strip():
            return " " * max_len
        raw = text.strip().upper()[:max_len]
        # Only keep chars that dta d can convert to screen codes
        safe = ''.join(c if (c.isalnum() or c in ' .-_!(),:;/') else ' '
                       for c in raw)
        return safe.strip().center(max_len)[:max_len]
    
    name_line = _sanitize_line(song_title)
    author_line = _sanitize_line(song_author)
    
    content = (
        "; SONG_INFO.asm — song name and author (generated by build pipeline)\n"
        "; Included by song_player.asm as text lines 1 and 2.\n"
        "; Must be exactly 80 bytes (2 x 40) for ANTIC continuation lines.\n"
        ";\n"
        f';          1234567890123456789012345678901234567890\n'
        f'    dta d"{name_line}"\n'
        f'    dta d"{author_line}"\n'
    )
    
    path = os.path.join(build_dir, "SONG_INFO.asm")
    with open(path, 'w') as f:
        f.write(content)


def _generate_mem_err_text(output_dir: str, memory_config: str,
                           required_banks: int, song_title: str = ""):
    """Generate MEM_ERR_TEXT.asm — error screen for insufficient memory.
    
    Creates a user-friendly error display shown when the XEX detects
    too few extended RAM banks.  All text is pre-formatted at build time
    except the FOUND digit pair which is patched at runtime by
    mem_error_screen in mem_detect.asm.
    
    Screen layout (ANTIC Mode 2, 40 cols, vertically centered):
    
        Line 1:  "       NOT ENOUGH MEMORY               "
        Line 2:  (blank)
        Line 3:  "  THIS PROGRAM NEEDS 320 KB RAM         "
        Line 4:  (blank)
        Line 5:  "  REQUIRED: 16  FOUND: ?? BANKS         "
    
    The "??" is labelled mem_err_found_digits for runtime patching.
    
    Args:
        output_dir: Build directory (where MEM_ERR_TEXT.asm goes — must be
                    the MADS CWD so bank_loader.asm can icl 'MEM_ERR_TEXT.asm')
        memory_config: Human-readable config name (e.g. "320 KB")
        required_banks: Number of banks needed (e.g. 16)
        song_title: Song title (shown on error screen if non-empty)
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Helper: pad/truncate string to exactly 40 chars
    def pad40(s):
        return s[:40].ljust(40)
    
    # Format values for display
    need_str = f"{required_banks:02d}"
    mem_str = memory_config.strip().upper()
    
    # Clean song title: uppercase, only safe ATASCII chars
    title = ""
    if song_title and song_title.strip():
        raw = song_title.strip().upper()[:30]
        title = ''.join(c if (c.isalnum() or c in ' .-_!') else ' ' for c in raw)
        title = title.strip()  # drop if sanitization left only spaces
    
    # --- Build the 5 (or 6) text lines ---
    line1 = pad40("       NOT ENOUGH MEMORY")
    line2 = pad40("")
    line3 = pad40(f"  THIS PROGRAM NEEDS {mem_str} RAM")
    line4 = pad40("")
    
    # Line 5 is split across 3 dta directives so mem_err_found_digits
    # labels the exact 2-byte position for runtime digit patching.
    line5_pre = f"  REQUIRED: {need_str}  FOUND: "   # 23 chars
    line5_post_content = " BANKS"                      # 6 chars
    line5_post_pad = 40 - len(line5_pre) - 2 - len(line5_post_content)
    line5_post = line5_post_content + " " * max(0, line5_post_pad)
    
    # Optional line 6: song title (if provided)
    has_title = bool(title)
    if has_title:
        line6 = pad40("")
        line7 = pad40(f"  {title}")
        n_text_lines = 7
    else:
        n_text_lines = 5
    
    # --- Compute vertical centering ---
    # ANTIC Mode 2: 8 scanlines per text line, ~240 visible (NTSC)
    text_scanlines = n_text_lines * 8
    blank_above = max(48, (240 - text_scanlines) // 2)
    n_blank_bytes = blank_above // 8  # $70 = 8 blank scanlines each
    
    # --- Build the ASM file ---
    lines = []
    lines.append("; ==========================================================================")
    lines.append("; MEM_ERR_TEXT.ASM - Error screen text (generated by build pipeline)")
    lines.append("; ==========================================================================")
    lines.append(f"; Memory config: {memory_config}, Required banks: {required_banks}")
    lines.append("; Only the FOUND digit pair is patched at runtime.")
    lines.append("; ==========================================================================")
    lines.append("")
    lines.append("    ORG $2000")
    lines.append("")
    
    # Display list
    lines.append("; Display list (ANTIC Mode 2, vertically centered)")
    lines.append("mem_err_dl:")
    
    # Emit blank scanline bytes in groups of 8
    for i in range(0, n_blank_bytes, 8):
        chunk = min(8, n_blank_bytes - i)
        blanks = ','.join(['$70'] * chunk)
        lines.append(f"    .byte {blanks}")
    
    # First text line with LMS
    lines.append("    .byte $42                       ; Mode 2 + LMS")
    lines.append("    .word mem_err_text              ; -> text block start")
    
    # Continuation lines (contiguous memory, no LMS needed)
    cont_count = n_text_lines - 1
    if cont_count > 0:
        conts = ','.join(['$02'] * cont_count)
        lines.append(f"    .byte {conts}")
    
    # Jump-and-wait-for-VBI
    lines.append("    .byte $41                       ; JVB")
    lines.append("    .word mem_err_dl")
    lines.append("")
    
    # Text data
    lines.append(f"; Screen text ({n_text_lines} x 40 = {n_text_lines * 40}"
                 f" bytes, ANTIC screen codes via dta d)")
    lines.append(";          1234567890123456789012345678901234567890")
    lines.append("mem_err_text:")
    lines.append(f'    dta d"{line1}"')
    lines.append(f'    dta d"{line2}"')
    lines.append(f'    dta d"{line3}"')
    lines.append(f'    dta d"{line4}"')
    
    # Line 5: split so mem_err_found_digits labels the "??" bytes
    lines.append(f'    dta d"{line5_pre}"')
    lines.append("mem_err_found_digits:")
    lines.append(f'    dta d"??"')
    lines.append(f'    dta d"{line5_post}"')
    
    # Optional title lines
    if has_title:
        lines.append(f'    dta d"{line6}"')
        lines.append(f'    dta d"{line7}"')
    
    lines.append("")
    
    path = os.path.join(output_dir, "MEM_ERR_TEXT.asm")
    with open(path, 'w') as f:
        f.write('\n'.join(lines))


def _generate_bank_loader(build_dir: str, pack_result):
    """Generate bank_loader.asm — top-level source for banking mode.
    
    This is the main file MADS assembles. It creates a multi-segment
    XEX with INI blocks for memory detection, bank switching, and data
    loading, followed by the main player code.
    """
    from bank_packer import DBANK_TABLE
    
    n_required = pack_result.n_banks_used
    lines = []
    lines.append("; ==========================================================================")
    lines.append("; bank_loader.asm - Multi-Segment XEX with Extended Memory Banking")
    lines.append("; ==========================================================================")
    lines.append("; Generated by POKEY VQ Tracker")
    lines.append("; ==========================================================================")
    lines.append("")
    
    # Segment 1: Memory detection + validation INI
    # mem_detect.asm places code at $0600 and screen data at $2000.
    # After the icl, PC is at ~$20D5. The validate stub lands there,
    # which is fine — it runs via INI then gets overwritten by song_player.
    lines.append("; --- Segment 1: Memory Detection + Validation (INI) ---")
    lines.append("    ORG $0600")
    lines.append(f"REQUIRED_BANKS = {n_required}")
    lines.append("    icl 'banking/mem_detect.asm'")
    lines.append("    icl 'MEM_ERR_TEXT.asm'         ; error screen (has own ORG $2000)")
    lines.append("")
    lines.append("mem_detect_and_validate:")
    lines.append("    jsr mem_detect")
    lines.append("    jsr mem_validate")
    lines.append("    rts")
    lines.append("    ini mem_detect_and_validate")
    lines.append("")
    
    # Per-bank: switch INI + data at $4000
    # Each switch stub can reuse $0600 since mem_detect already ran
    for bank_idx in range(pack_result.n_banks_used):
        portb = DBANK_TABLE[bank_idx] if bank_idx < len(DBANK_TABLE) else 0xFF
        lines.append(f"; --- Bank {bank_idx}: Switch + Data ---")
        lines.append("    ORG $0600")
        lines.append(f"switch_bank_{bank_idx}:")
        lines.append(f"    lda #${portb:02X}")
        lines.append("    sta $D301")
        lines.append("    rts")
        lines.append(f"    ini switch_bank_{bank_idx}")
        lines.append("")
        lines.append("    ORG $4000")
        lines.append(f"    icl 'BANK_DATA_{bank_idx}.asm'")
        lines.append("")
    
    # Restore main RAM INI (keep OS ROM enabled for remaining XEX loading!)
    lines.append("; --- Restore Main RAM ---")
    lines.append("    ORG $0600")
    lines.append("restore_main:")
    lines.append(f"    lda #$FF              ; deselect banks + OS ROM ON (loading continues)")
    lines.append("    sta $D301")
    lines.append("    rts")
    lines.append("    ini restore_main")
    lines.append("")
    
    # Main player code (song_player.asm handles ORG START_ADDRESS + ORG $8000)
    lines.append("; --- Main Player Code ---")
    lines.append("    icl 'song_player.asm'")
    
    path = os.path.join(build_dir, "bank_loader.asm")
    with open(path, 'w') as f:
        f.write('\n'.join(lines))



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
    
    # Create build directory in .tmp (persistent for debugging)
    # Use runtime.get_app_dir() to work correctly in both dev and bundled modes
    tracker_dir = runtime.get_app_dir()
    build_dir = os.path.join(tracker_dir, ".tmp", "build")
    
    # Clean and create build directory
    if os.path.exists(build_dir):
        try:
            shutil.rmtree(build_dir)
        except Exception as e:
            logger.warning(f"Could not clean build dir: {e}")
    os.makedirs(build_dir, exist_ok=True)
    
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
            "SAMPLE_DIR.asm",
            "RAW_SAMPLES.asm"
        ]
        
        missing_files = []
        for vq_file in vq_files:
            src = os.path.join(vq_output_dir, vq_file)
            if os.path.exists(src):
                shutil.copy2(src, build_dir)
                _output(f"    + {vq_file}\n")
                logger.debug(f"Copied: {vq_file}")
            elif vq_file == "RAW_SAMPLES.asm":
                # Fallback stub if converter didn't generate one
                stub_path = os.path.join(build_dir, vq_file)
                with open(stub_path, 'w') as f:
                    f.write("; RAW_SAMPLES.asm - empty (all instruments use VQ)\n")
                _output(f"    + {vq_file} (generated stub)\n")
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
        
        # CRITICAL: Copy our UPDATED support files to overwrite VQ converter versions
        # Our asm/ directory has fixes for sequencer variables, IRQ optimization, etc.
        _output("\n  Copying tracker-specific support files...\n")
        # Use runtime.get_asm_dir() which handles both dev and bundled modes
        our_asm_dir = runtime.get_asm_dir()
        _output(f"    Looking for ASM files in: {our_asm_dir}\n")
        logger.debug(f"Tracker ASM directory: {our_asm_dir}")
        
        if os.path.isdir(our_asm_dir):
            for subdir in support_dirs:
                our_subdir = os.path.join(our_asm_dir, subdir)
                if os.path.isdir(our_subdir):
                    dst_subdir = os.path.join(build_dir, subdir)
                    os.makedirs(dst_subdir, exist_ok=True)
                    for filename in os.listdir(our_subdir):
                        src_file = os.path.join(our_subdir, filename)
                        dst_file = os.path.join(dst_subdir, filename)
                        if os.path.isfile(src_file):
                            shutil.copy2(src_file, dst_file)
                            _output(f"    + {subdir}/{filename} (updated)\n")
                            logger.debug(f"Copied updated: {subdir}/{filename}")
                else:
                    _output(f"    ! Subdir not found: {our_subdir}\n")
        else:
            _output(f"    ! ASM directory not found: {our_asm_dir}\n")
            _output(f"    ! You may need to manually copy asm/ files from tracker package\n")
        
        # Verify critical support files exist
        critical_files = [
            "common/atari.inc",
            "common/zeropage.inc",
            "common/macros.inc",
            "common/pokey_setup.asm",
            "tracker/tracker_api.asm",
            "pitch/pitch_tables.asm",
        ]
        
        # Check for IRQ handler
        if not os.path.exists(os.path.join(build_dir, "tracker/tracker_irq_speed.asm")):
            critical_files.append("tracker/tracker_irq_speed.asm")
        
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
        # Banking mode: split song data across two regions (I/O gap at $D000)
        # Region A: $8000-$CFFF = 20,480 bytes
        # Region B: $D800-$FBFF =  9,216 bytes  (charset at $FC00)
        REGION_A_SIZE = 0xD000 - 0x8000   # 20480
        REGION_B_SIZE = 0xFC00 - 0xD800   #  9216
        BANKING_SONG_BUDGET = REGION_A_SIZE + REGION_B_SIZE  # 29696
        
        use_banking = song.memory_config != "64 KB"
        region_a_limit = REGION_A_SIZE if use_banking else 0
        ok, err = export_song_data(song, song_data_path,
                                    region_a_limit=region_a_limit)
        if not ok:
            result.error_message = f"Failed to export song data: {err}"
            _output(f"ERROR: {result.error_message}\n")
            return result
        # Show summary with byte count
        try:
            song_bytes = _count_asm_bytes(song_data_path)
            _output(f"    + SONG_DATA.asm ({len(song.patterns)} patterns, "
                    f"{len(song.songlines)} songlines, ~{song_bytes//1024}KB)\n")
            # Check for region B overflow
            if use_banking:
                path2 = os.path.join(build_dir, "SONG_DATA_2.asm")
                if os.path.exists(path2):
                    song2_bytes = _count_asm_bytes(path2)
                    if song2_bytes > 0:
                        _output(f"    + SONG_DATA_2.asm ({song2_bytes:,} bytes in region B)\n")
                    else:
                        _output(f"    + SONG_DATA_2.asm (empty — all data fits in region A)\n")
        except Exception:
            _output(f"    + SONG_DATA.asm ({len(song.patterns)} patterns, "
                    f"{len(song.songlines)} songlines)\n")
        
        # Copy song_player.asm from our asm/ directory
        # Use runtime.get_asm_dir() which handles both dev and bundled modes
        player_src = os.path.join(runtime.get_asm_dir(), "song_player.asm")
        if os.path.exists(player_src):
            shutil.copy2(player_src, build_dir)
            _output(f"    + song_player.asm\n")
            logger.debug("Copied: song_player.asm")
        else:
            result.error_message = f"song_player.asm not found at {player_src}"
            _output(f"ERROR: {result.error_message}\n")
            return result
        
        # Generate SONG_INFO.asm (song name + author for splash screen)
        _generate_song_info(build_dir, song.title, song.author)
        _output(f"    + SONG_INFO.asm\n")
        
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
        
        # Banking mode: generate bank data, loader, config
        if use_banking:
            _output("\n  Generating banking build files...\n")
            bank_err = _generate_banking_build(build_dir, vq_output_dir, song, _output)
            if bank_err:
                # Check for upgrade suggestion (structured signal from packer)
                if bank_err.startswith("UPGRADE:"):
                    # Format: "UPGRADE:config_name:n_banks:total_bytes:current_config"
                    parts = bank_err.split(":")
                    if len(parts) >= 5:
                        result.needs_upgrade = True
                        result.suggested_config = parts[1]
                        result.suggested_banks = int(parts[2])
                        result.total_sample_bytes = int(parts[3])
                        result.current_config = parts[4]
                        result.error_message = (
                            f"Sample data doesn't fit in {result.current_config}.\n\n"
                            f"Upgrade to \"{result.suggested_config}\" to build.")
                        return result
                
                result.error_message = bank_err
                _output(f"\nERROR: {bank_err}\n")
                return result
        
        # Pre-compute data sizes for better error reporting
        data_sizes = _estimate_data_sizes(build_dir, use_banking)
        total_data = sum(data_sizes.values())
        _output(f"\n  Estimated data: ~{total_data//1024}KB\n")
        for name, sz in sorted(data_sizes.items(), key=lambda x: -x[1]):
            if sz >= 512:
                _output(f"    {name}: {sz:,}\n")
        
        # Pre-flight memory check: catch overflow BEFORE running MADS
        if use_banking:
            # Song data spans two regions (I/O gap at $D000-$D7FF):
            #   Region A: $8000-$CFFF = 20,480 bytes
            #   Region B: $D800-$FBFF =  9,216 bytes
            available = (0xD000 - 0x8000) + (0xFC00 - 0xD800)  # 29,696
            region = "$8000–$CFFF + $D800–$FBFF"
        else:
            available = 0xC000 - song.start_address
            region = f"${song.start_address:04X}–$BFFF"
        
        if total_data > available:
            overflow = total_data - available
            top = sorted(data_sizes.items(), key=lambda x: -x[1])[:5]
            breakdown = "\n".join(f"  {n}: {s:,} bytes ({s//1024}KB)" 
                                  for n, s in top if s >= 256)
            
            result.error_message = (
                f"Memory overflow by ~{overflow:,} bytes ({overflow//1024}KB)!\n\n"
                f"Available: {available:,} bytes ({available//1024}KB) "
                f"in {region}.\n"
                f"Estimated total: ~{total_data:,} bytes ({total_data//1024}KB).\n\n"
                f"Breakdown:\n{breakdown}\n\n"
                f"To fix: reduce the number of patterns, use shorter patterns,\n"
                f"remove unused instruments, or lower the VQ vector size.")
            _output(f"\nERROR: Data overflow by ~{overflow:,} bytes ({overflow//1024}KB)!\n")
            _output(f"  Available: {available:,} bytes ({available//1024}KB) in {region}\n")
            _output(f"  Estimated: {total_data:,} bytes ({total_data//1024}KB)\n")
            _output(f"  Breakdown:\n")
            for n, s in sorted(data_sizes.items(), key=lambda x: -x[1]):
                if s >= 256:
                    pct = s * 100 // total_data
                    _output(f"    {n}: {s:,} bytes ({s//1024}KB) — {pct}%\n")
            if use_banking:
                _output(f"\n  In banking mode, song data (patterns + songlines) spans\n")
                _output(f"  {region} (~29KB, split around I/O at $D000).\n")
                _output(f"  Tables and staging are before $4000. Samples in banks.\n")
                _output(f"\n  To fix: reduce patterns/songlines, use shorter patterns,\n")
                _output(f"  disable Volume Control, or remove unused instruments.\n")
            else:
                _output(f"\n  The data region ({region}) holds all code, tables,\n")
                _output(f"  song data, sample data, and codebook.\n")
                _output(f"\n  To fix: switch to extended memory (128KB+), use VQ mode\n")
                _output(f"  on large instruments, or lower the sample rate.\n")
            return result
        
        # Run MADS
        _output("\n  Assembling with MADS...\n")
        output_xex = os.path.join(build_dir, "song.xex")
        
        if use_banking:
            # Banking: assemble bank_loader.asm (includes song_player.asm)
            main_asm = os.path.join(build_dir, "bank_loader.asm")
            _output(f"    Source: bank_loader.asm (banking mode)\n")
        else:
            # 64KB: assemble song_player.asm directly
            main_asm = os.path.join(build_dir, "song_player.asm")
        
        cmd = [mads_path, main_asm, "-o:" + output_xex]
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
            error_lines = [l for l in error_output.split('\n') if 'error' in l.lower()]
            
            # Check for our specific memory overflow errors
            overflow_patterns = ['memory overflow', 'data overflow', 
                                 'exceeds $4000', 'exceeds $c000',
                                 'song_data too large', 'too large for']
            is_overflow = any(any(pat in l.lower() for pat in overflow_patterns)
                             for l in error_output.split('\n'))
            
            if is_overflow:
                is_bank_code = any('exceeds $4000' in l.lower() for l in error_output.split('\n'))
                
                if use_banking and is_bank_code:
                    code_space = 0x4000 - song.start_address
                    result.error_message = (
                        f"Player code overflow!\n\n"
                        f"Code exceeds bank window at $4000.\n"
                        f"Available for code: {code_space:,} bytes "
                        f"(${song.start_address:04X}–$3FFF).\n\n"
                        f"To fix: lower Start Address to give code more room.")
                    _output(f"\nERROR: Player code exceeds $4000 bank window!\n")
                    _output(f"  Available: {code_space:,} bytes (${song.start_address:04X}–$3FFF)\n")
                    _output(f"  To fix: lower Start Address.\n")
                else:
                    if use_banking:
                        avail = 0xC000 - 0x8000
                        region = "$8000–$BFFF"
                    else:
                        avail = 0xC000 - song.start_address
                        region = f"${song.start_address:04X}–$BFFF"
                    
                    overflow = max(0, total_data - avail)
                    
                    # Build top contributors
                    top = sorted(data_sizes.items(), key=lambda x: -x[1])[:5]
                    breakdown = ", ".join(f"{n}: {s//1024}KB" for n, s in top if s >= 1024)
                    breakdown_detail = "\n".join(
                        f"    {n}: {s:,} bytes ({s//1024}KB) — {s*100//total_data}%"
                        for n, s in top if s >= 256)
                    
                    result.error_message = (
                        f"Memory overflow by ~{overflow:,} bytes ({overflow//1024}KB)!\n\n"
                        f"Available: {avail:,} bytes ({avail//1024}KB) "
                        f"in {region}.\n"
                        f"Data: ~{total_data:,} bytes ({total_data//1024}KB).\n\n"
                        f"Biggest: {breakdown}\n\n"
                        f"To fix: reduce patterns/songlines, use VQ on large instruments,\n"
                        f"lower sample rate, or switch to extended memory.")
                    
                    _output(f"\nERROR: Data overflow by ~{overflow:,} bytes ({overflow//1024}KB)!\n")
                    _output(f"  Available: {avail:,} bytes ({avail//1024}KB) in {region}\n")
                    _output(f"  Estimated: {total_data:,} bytes ({total_data//1024}KB)\n")
                    _output(f"  Breakdown:\n{breakdown_detail}\n")
            elif error_lines:
                result.error_message = f"Assembly error:\n\n{error_lines[0][:200]}"
            else:
                result.error_message = f"Assembly failed:\n\n{error_output[:500]}"
            _output(f"\nERROR: Assembly failed\n")
            for line in error_output.split('\n')[:30]:
                if line.strip():
                    _output(f"  {line.strip()}\n")
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
        
        # CRITICAL: Sync file to disk before emulator launch
        # Prevents race condition where emulator reads incomplete/stale file
        try:
            with open(output_xex_path, 'rb') as f:
                os.fsync(f.fileno())
            # Also sync parent directory to ensure directory entry is updated (Linux/macOS)
            if hasattr(os, 'O_DIRECTORY'):
                parent_dir = os.path.dirname(os.path.abspath(output_xex_path))
                dir_fd = os.open(parent_dir, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except Exception as sync_err:
            logger.warning(f"File sync warning: {sync_err}")
        
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
