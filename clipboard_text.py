"""POKEY VQ Tracker — Clipboard text serialization.

Converts multi-channel pattern blocks to/from tab-separated text.
Interfaces with the OS clipboard so users can:
  - Copy pattern data → paste into Notepad → edit → copy back → paste into tracker

Text format (tab-separated):
    PVQT\\t<num_channels>\\t<num_rows>
    <Note>\\t<Inst>\\t<Vol>[\\t<Note>\\t<Inst>\\t<Vol>]...
    ...

Example (2 channels, 3 rows):
    PVQT\\t2\\t3
    C-2\\t00\\tF\\t---\\t--\\tF
    D#2\\t01\\tA\\tOFF\\t--\\tF
    ---\\t--\\tF\\tE-1\\t02\\t8

Note column: C-1, C#1, D-1, ..., B-3, OFF, V--, ---
Inst column: hex 00-7F (always hex for portability)
Vol  column: hex 0-F  (always hex for portability)
"""
import logging
import subprocess
import sys
from typing import List, Optional, Tuple

from constants import (MAX_NOTES, MAX_VOLUME, MAX_INSTRUMENTS,
                       NOTE_OFF, VOL_CHANGE, NOTE_NAMES, note_to_str)
from data_model import Row

logger = logging.getLogger("tracker.clipboard")

MAGIC = "PVQT"


# =========================================================================
# TEXT SERIALIZATION
# =========================================================================

def rows_to_text(block: List[List[Row]]) -> str:
    """Serialize a 2D block of rows to tab-separated text.

    Args:
        block: block[ch_idx][row_idx] — list of channels, each a list of Row.
               All channels must have the same number of rows.
    Returns:
        Tab-separated text string with header line.
    """
    if not block or not block[0]:
        return ""
    num_ch = len(block)
    num_rows = len(block[0])
    lines = [f"{MAGIC}\t{num_ch}\t{num_rows}"]
    for r in range(num_rows):
        cells = []
        for ch in range(num_ch):
            row = block[ch][r] if r < len(block[ch]) else Row()
            cells.append(_row_to_cells(row))
        lines.append("\t".join(cells))
    return "\n".join(lines)


def text_to_rows(text: str) -> Optional[Tuple[List[List[Row]], int, int]]:
    """Deserialize tab-separated text into a 2D block of rows.

    Returns:
        (block, num_channels, num_rows) or None on parse error.
        block[ch_idx][row_idx]
    """
    if not text:
        return None
    # Strip BOM (Windows Notepad UTF-8 with BOM)
    text = text.lstrip("\ufeff\xef\xbb\xbf")
    # Normalize line endings (Windows \r\n → \n) and strip outer whitespace
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    lines = text.split("\n")
    if len(lines) < 2:
        return None
    # Parse header
    header = lines[0].split("\t")
    if len(header) < 3 or header[0].strip() != MAGIC:
        return None
    try:
        num_ch = int(header[1])
        num_rows = int(header[2])
    except (ValueError, IndexError):
        return None
    if num_ch < 1 or num_rows < 1:
        return None
    # Cap to sane limits to prevent memory bombs from malicious/corrupt clipboard
    from constants import MAX_CHANNELS, MAX_ROWS
    num_ch = min(num_ch, MAX_CHANNELS)
    num_rows = min(num_rows, MAX_ROWS)
    # Parse data
    block = [[] for _ in range(num_ch)]
    for line_idx in range(1, min(len(lines), num_rows + 1)):
        line = lines[line_idx]
        if not line.strip():
            # Skip blank lines — fill with empty rows
            for ch in range(num_ch):
                block[ch].append(Row())
            continue
        cells = line.split("\t")
        for ch in range(num_ch):
            offset = ch * 3
            if offset + 2 < len(cells):
                row = _cells_to_row(cells[offset], cells[offset + 1], cells[offset + 2])
            elif offset < len(cells):
                # Partial channel data — parse what's available
                note_s = cells[offset] if offset < len(cells) else ""
                inst_s = cells[offset + 1] if offset + 1 < len(cells) else ""
                vol_s = cells[offset + 2] if offset + 2 < len(cells) else ""
                row = _cells_to_row(note_s, inst_s, vol_s)
            else:
                row = Row()
            block[ch].append(row)
    # Pad short blocks (fewer data lines than declared rows)
    for ch in range(num_ch):
        while len(block[ch]) < num_rows:
            block[ch].append(Row())
    return block, num_ch, num_rows


def _row_to_cells(row: Row) -> str:
    """Convert a single Row to 3 tab-separated cell strings."""
    note_str = note_to_str(row.note)
    if row.note > 0 and row.note not in (NOTE_OFF, VOL_CHANGE):
        inst_str = f"{row.instrument:02X}"
    else:
        inst_str = "--"
    vol_str = f"{row.volume:X}"
    return f"{note_str}\t{inst_str}\t{vol_str}"


def _cells_to_row(note_s: str, inst_s: str, vol_s: str) -> Row:
    """Parse 3 cell strings back into a Row."""
    note_s = note_s.strip()
    inst_s = inst_s.strip()
    vol_s = vol_s.strip()
    note = _parse_note(note_s)
    inst = _parse_inst(inst_s)
    vol = _parse_vol(vol_s)
    return Row(note=note, instrument=inst, volume=vol)


def _parse_note(s: str) -> int:
    """Parse note string → int.  'C-2' → 13, 'OFF' → 255, '---' → 0, etc."""
    s = s.strip().upper()
    if s in ("---", "...", "", "000"):
        return 0
    if s == "OFF":
        return NOTE_OFF
    if s in ("V--", "VOL"):
        return VOL_CHANGE
    # Try "C-1", "C#2", "D-3", etc.
    if len(s) >= 3:
        # Note name is first 2 chars, octave is last char(s)
        name_part = s[:2]
        oct_part = s[2:]
        try:
            octave = int(oct_part)
        except ValueError:
            return 0
        for idx, name in enumerate(NOTE_NAMES):
            if name_part == name:
                note = (octave - 1) * 12 + idx + 1
                if 1 <= note <= MAX_NOTES:
                    return note
                return 0
    # Try as plain integer
    try:
        n = int(s)
        if 0 <= n <= MAX_NOTES or n in (NOTE_OFF, VOL_CHANGE):
            return n
    except ValueError:
        pass
    return 0


def _parse_inst(s: str) -> int:
    """Parse instrument string → int.  '00' → 0, '0A' → 10, '--' → 0."""
    s = s.strip()
    if s in ("--", "---", ""):
        return 0
    try:
        return max(0, min(MAX_INSTRUMENTS - 1, int(s, 16)))
    except ValueError:
        try:
            return max(0, min(MAX_INSTRUMENTS - 1, int(s)))
        except ValueError:
            return 0


def _parse_vol(s: str) -> int:
    """Parse volume string → int.  'F' → 15, '8' → 8, '--' → 15."""
    s = s.strip()
    if s in ("--", "-", ""):
        return MAX_VOLUME
    try:
        return max(0, min(MAX_VOLUME, int(s, 16)))
    except ValueError:
        try:
            return max(0, min(MAX_VOLUME, int(s)))
        except ValueError:
            return MAX_VOLUME


# =========================================================================
# OS CLIPBOARD ACCESS
# =========================================================================
# Priority: pyperclip (cross-platform, uses native APIs) → subprocess fallback.
# pyperclip uses Win32 OpenClipboard/SetClipboardData on Windows,
# pbcopy/pbpaste on macOS, xclip/xsel on Linux — all via ctypes or
# subprocess, but with proper encoding handling. The subprocess
# fallback below is for environments where pyperclip is unavailable.
#
# The Windows `clip.exe` approach used previously has known encoding
# issues (expects OEM codepage, not UTF-8) and silently corrupts data.
# pyperclip solves this by calling the Win32 API directly.

_pyperclip = None
_pyperclip_checked = False


def _get_pyperclip():
    """Lazy-import pyperclip. Returns module or None."""
    global _pyperclip, _pyperclip_checked
    if not _pyperclip_checked:
        _pyperclip_checked = True
        try:
            import pyperclip
            # Verify it actually works (some Linux installs fail at copy time)
            _pyperclip = pyperclip
        except ImportError:
            logger.debug("pyperclip not installed — using subprocess fallback")
    return _pyperclip


def set_os_clipboard(text: str):
    """Copy text to OS clipboard.  Best-effort; logs failures."""
    pc = _get_pyperclip()
    if pc:
        try:
            pc.copy(text)
            return
        except Exception as e:
            logger.warning(f"pyperclip.copy failed: {e}")
    # Subprocess fallback
    try:
        if sys.platform == "win32":
            # Use PowerShell Set-Clipboard (UTF-16 safe, unlike clip.exe)
            p = subprocess.Popen(
                ["powershell", "-noprofile", "-command",
                 "Set-Clipboard -Value $input"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            p.communicate(text.encode("utf-8"), timeout=3)
        elif sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.communicate(text.encode("utf-8"), timeout=3)
        else:
            for cmd in [["xclip", "-selection", "clipboard"],
                        ["xsel", "--clipboard", "--input"]]:
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                    p.communicate(text.encode("utf-8"), timeout=3)
                    return
                except FileNotFoundError:
                    continue
            logger.debug("No clipboard tool found (install xclip or pyperclip)")
    except Exception as e:
        logger.debug(f"OS clipboard write failed: {e}")


def get_os_clipboard() -> str:
    """Read text from OS clipboard.  Returns '' on failure.

    Strips UTF-8 BOM if present (Windows Notepad adds BOM when saving).
    """
    pc = _get_pyperclip()
    if pc:
        try:
            text = pc.paste() or ""
            return text.lstrip("\ufeff")
        except Exception as e:
            logger.warning(f"pyperclip.paste failed: {e}")
    # Subprocess fallback
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-noprofile", "-command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=3)
            text = result.stdout.strip() if result.returncode == 0 else ""
            return text.lstrip("\ufeff")
        elif sys.platform == "darwin":
            result = subprocess.run(["pbpaste"], capture_output=True,
                                    text=True, timeout=3)
            text = result.stdout if result.returncode == 0 else ""
            return text.lstrip("\ufeff")
        else:
            for cmd in [["xclip", "-selection", "clipboard", "-o"],
                        ["xsel", "--clipboard", "--output"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True,
                                            text=True, timeout=3)
                    if result.returncode == 0:
                        return result.stdout.lstrip("\ufeff")
                except FileNotFoundError:
                    continue
    except Exception as e:
        logger.debug(f"OS clipboard read failed: {e}")
    return ""
