"""MOD file importer.

Reads Amiga ProTracker .MOD files and converts them into native
Song/Pattern/Instrument structures.  This is a "good enough" import —
effects like portamento, vibrato, arpeggio are ignored; only note,
instrument, volume (Set Volume command $C), and speed (command $F)
are mapped.  Sample loop points are not preserved (we don't support
looping yet).
"""

import struct
import logging
import os
from typing import Optional, Tuple, List

import numpy as np

from data_model import Song, Pattern, Row, Instrument, Songline
from constants import (
    MAX_CHANNELS, MAX_VOLUME, DEFAULT_SPEED, DEFAULT_LENGTH,
    NOTE_OFF, MAX_INSTRUMENTS, MAX_PATTERNS, MAX_ROWS,
)

logger = logging.getLogger("tracker.mod_import")

# ============================================================================
# MOD PERIOD → NOTE NUMBER TABLE
# ============================================================================
# Standard ProTracker period table for finetune 0, octaves 1-3.
# Our note numbers: 1=C-1 ... 12=B-1, 13=C-2 ... 24=B-2, 25=C-3 ... 36=B-3

_PERIOD_TABLE = [
    # Octave 1: notes 1-12
    856, 808, 762, 720, 678, 640, 604, 570, 538, 508, 480, 453,
    # Octave 2: notes 13-24
    428, 404, 381, 360, 339, 320, 302, 285, 269, 254, 240, 226,
    # Octave 3: notes 25-36
    214, 202, 190, 180, 170, 160, 151, 143, 135, 127, 120, 113,
]

# Extended periods (octaves 0 and 4) for tolerant matching
_PERIOD_TABLE_EXT = [
    1712, 1616, 1525, 1440, 1357, 1281, 1209, 1141, 1077, 1017, 961, 907,
] + _PERIOD_TABLE + [
    107, 101, 95, 90, 85, 80, 76, 71, 67, 64, 60, 57,
]

# Effect names for logging
_EFFECT_NAMES = {
    0x0: "Arpeggio", 0x1: "Slide Up", 0x2: "Slide Down",
    0x3: "Tone Portamento", 0x4: "Vibrato",
    0x5: "Tone Port+VolSlide", 0x6: "Vibrato+VolSlide",
    0x7: "Tremolo", 0x8: "Set Panning", 0x9: "Sample Offset",
    0xA: "Volume Slide", 0xB: "Position Jump",
    0xC: "Set Volume", 0xD: "Pattern Break",
    0xE: "Extended", 0xF: "Set Speed/BPM",
}


def _period_to_note(period: int) -> int:
    """Convert MOD period value to our note number (1-36), or 0 if no note.

    Uses closest-match against the standard period table.
    Extended octaves 0 and 4 are clamped to octaves 1 and 3.
    """
    if period == 0:
        return 0

    best_idx = 0
    best_dist = abs(_PERIOD_TABLE[0] - period)
    for i, p in enumerate(_PERIOD_TABLE):
        dist = abs(p - period)
        if dist < best_dist:
            best_dist = dist
            best_idx = i

    # Tolerance: if period is too far from any standard value, check
    # extended octaves and clamp to our supported range.
    if best_dist > 10:
        for i, p in enumerate(_PERIOD_TABLE_EXT):
            dist = abs(p - period)
            if dist < best_dist:
                best_dist = dist
                # Extended table: 12 oct0 + 36 oct1-3 + 12 oct4
                if i < 12:
                    best_idx = 0  # Clamp oct0 → C-1
                elif i >= 48:
                    best_idx = 35  # Clamp oct4 → B-3
                else:
                    best_idx = i - 12

    return best_idx + 1  # note numbers are 1-based


def _mod_vol_to_tracker(mod_vol: int) -> int:
    """Convert MOD volume (0-64) to tracker volume (0-15)."""
    return min(MAX_VOLUME, round(mod_vol * MAX_VOLUME / 64))


# ============================================================================
# MOD FORMAT SIGNATURE DETECTION
# ============================================================================

_SIGNATURES = {
    b'M.K.': 4, b'M!K!': 4, b'FLT4': 4, b'4CHN': 4,
    b'6CHN': 6, b'8CHN': 8, b'OCTA': 8, b'CD81': 8,
}


def _detect_format(data: bytes) -> Tuple[int, int, str]:
    """Detect MOD format.  Returns (num_channels, num_samples, sig_str)."""
    if len(data) >= 1084:
        sig = data[1080:1084]
        if sig in _SIGNATURES:
            return _SIGNATURES[sig], 31, sig.decode('ascii', errors='replace')
        try:
            sig_str = sig.decode('ascii')
            if sig_str.endswith('CHN') and sig_str[0].isdigit():
                return int(sig_str[0]), 31, sig_str
            if sig_str[2:] == 'CH' and sig_str[:2].isdigit():
                return int(sig_str[:2]), 31, sig_str
        except (UnicodeDecodeError, ValueError):
            pass

    return 4, 15, "(none — 15-sample format)"


# ============================================================================
# IMPORT LOG
# ============================================================================

class ImportLog:
    """Collects structured log messages during import."""

    def __init__(self):
        self.lines: List[str] = []
        self.warnings: int = 0
        self.errors: int = 0

    def info(self, msg: str):
        self.lines.append(msg)

    def warn(self, msg: str):
        self.lines.append(f"WARNING: {msg}")
        self.warnings += 1

    def error(self, msg: str):
        self.lines.append(f"ERROR: {msg}")
        self.errors += 1

    def section(self, title: str):
        self.lines.append("")
        self.lines.append(f"--- {title} ---")

    def get_text(self) -> str:
        return "\n".join(self.lines)

    def summary_line(self) -> str:
        parts = []
        if self.warnings:
            parts.append(f"{self.warnings} warning(s)")
        if self.errors:
            parts.append(f"{self.errors} error(s)")
        if not parts:
            return "Import completed successfully."
        return "Import completed with " + ", ".join(parts) + "."


# ============================================================================
# CORE PARSER
# ============================================================================

def parse_mod(data: bytes, log: ImportLog) -> Optional[dict]:
    """Parse raw MOD file bytes into a structured dict."""
    if len(data) < 600:
        log.error(f"File too small: {len(data)} bytes")
        return None

    num_channels, num_samples, sig_str = _detect_format(data)
    log.info(f"Format: {num_channels} channels, {num_samples} samples, "
             f"signature: {sig_str}")

    if num_channels > 4:
        log.warn(f"MOD has {num_channels} channels — only first 4 imported")

    # --- Header ---
    title = data[0:20].decode('ascii', errors='replace').rstrip('\x00').strip()
    log.info(f"Title: \"{title}\"")

    # --- Sample info ---
    samples = []
    for i in range(num_samples):
        offset = 20 + i * 30
        if offset + 30 > len(data):
            log.warn(f"Sample {i + 1} header truncated")
            break
        name = data[offset:offset + 22].decode('ascii', errors='replace') \
            .rstrip('\x00').strip()
        length = struct.unpack('>H', data[offset + 22:offset + 24])[0] * 2
        finetune = data[offset + 24] & 0x0F
        volume = min(64, data[offset + 25])
        rep_start = struct.unpack('>H', data[offset + 26:offset + 28])[0] * 2
        rep_len = struct.unpack('>H', data[offset + 28:offset + 30])[0] * 2

        samples.append({
            'name': name, 'length': length, 'finetune': finetune,
            'volume': volume, 'repeat_start': rep_start,
            'repeat_length': rep_len,
        })

    # --- Song arrangement ---
    header_end = 20 + num_samples * 30
    if header_end + 130 > len(data):
        log.error("File truncated in song header")
        return None

    song_length = data[header_end]
    restart = data[header_end + 1]
    pattern_order = list(data[header_end + 2:header_end + 2 + 128])

    if song_length == 0 or song_length > 128:
        log.error(f"Invalid song length: {song_length}")
        return None

    log.info(f"Song length: {song_length} positions")

    # Number of patterns = highest index in the VALID song positions + 1
    # Only scan pattern_order[:song_length] — entries beyond are undefined
    # and may contain garbage that inflates the pattern count.
    valid_order = pattern_order[:song_length]
    num_patterns = max(valid_order) + 1

    # Validate: check if file is large enough to hold this many patterns
    if num_samples == 31:
        pat_data_offset_check = 1084
    else:
        pat_data_offset_check = header_end + 2 + 128
    bytes_per_pattern = num_channels * 4 * 64
    total_sample_bytes = sum(smp['length'] for smp in samples)
    expected_min_size = pat_data_offset_check + num_patterns * bytes_per_pattern
    if expected_min_size > len(data) + total_sample_bytes:
        log.warn(f"Pattern count ({num_patterns}) seems too high for file size — "
                 f"some patterns may be corrupt")

    log.info(f"Patterns in file: {num_patterns}")

    # --- Pattern data ---
    if num_samples == 31:
        pat_data_offset = 1084
    else:
        pat_data_offset = header_end + 2 + 128

    bytes_per_pattern = num_channels * 4 * 64

    patterns = []
    for pat_idx in range(num_patterns):
        pat_start = pat_data_offset + pat_idx * bytes_per_pattern
        if pat_start + bytes_per_pattern > len(data):
            log.warn(f"Pattern {pat_idx} truncated — padding with silence")
            available = data[pat_start:] if pat_start < len(data) else b''
            padded = available + b'\x00' * (bytes_per_pattern - len(available))
        else:
            padded = data[pat_start:pat_start + bytes_per_pattern]

        rows = []
        for row_idx in range(64):
            channels = []
            for ch in range(min(num_channels, 4)):
                off = row_idx * num_channels * 4 + ch * 4
                b = padded[off:off + 4]
                channels.append({
                    'sample': (b[0] & 0xF0) | (b[2] >> 4),
                    'period': ((b[0] & 0x0F) << 8) | b[1],
                    'effect': b[2] & 0x0F,
                    'effect_data': b[3],
                })
            while len(channels) < 4:
                channels.append({'sample': 0, 'period': 0,
                                 'effect': 0, 'effect_data': 0})
            rows.append(channels)
        patterns.append(rows)

    # --- Sample data ---
    sample_data_offset = pat_data_offset + num_patterns * bytes_per_pattern
    for smp in samples:
        length = smp['length']
        if length <= 0:
            smp['data'] = None
            continue
        end = sample_data_offset + length
        if end > len(data):
            raw = data[sample_data_offset:len(data)]
            if len(raw) < length:
                log.warn(f"Sample \"{smp['name']}\" data truncated: "
                         f"expected {length}, got {len(raw)} bytes")
        else:
            raw = data[sample_data_offset:end]
        sample_data_offset += length

        if len(raw) == 0:
            smp['data'] = None
            continue

        audio = np.frombuffer(raw, dtype=np.int8).astype(np.float32) / 128.0
        smp['data'] = audio

    return {
        'title': title, 'samples': samples,
        'song_length': song_length, 'restart': restart,
        'pattern_order': pattern_order[:song_length],
        'num_patterns': num_patterns,
        'num_channels': min(num_channels, 4),
        'patterns': patterns,
    }


# ============================================================================
# CONVERT PARSED MOD → NATIVE SONG
# ============================================================================

# Amiga PAL master clock
_AMIGA_CLOCK_PAL = 7093790

# The ASM pitch table maps note C-1 (index 0) to 1.0x playback speed.
# Samples must be stored at the C-1 equivalent rate so that the pitch
# table produces correct frequencies for all notes.
#
# C-1 period = 856 → rate = 7093790 / (856 * 2) = 4143 Hz
# C-3 period = 214 → rate = 7093790 / (214 * 2) = 16574 Hz
#
# If stored at 16574 Hz (C-3), note C-1 at 1.0x would play at C-3 speed
# = 2 octaves too high. Storing at 4143 Hz (C-1) fixes this.
_MOD_C1_RATE = _AMIGA_CLOCK_PAL // (856 * 2)   # 4143 Hz (C-1 on PAL)
_MOD_C3_RATE = _AMIGA_CLOCK_PAL // (214 * 2)   # 16574 Hz (C-3 on PAL)


def mod_to_song(mod: dict, log: ImportLog) -> Song:
    """Convert parsed MOD data into a native Song object."""
    song = Song()
    song.title = mod['title'] or "Imported MOD"
    song.speed = DEFAULT_SPEED
    song.songlines = []
    song.patterns = []
    song.instruments = []

    # --- Create instruments ---
    log.section("Instruments")

    inst_map = {}       # MOD sample num (1-based) → tracker index (0-based)
    empty_samples = set()  # MOD sample nums with no audio data
    skipped = 0

    for i, smp in enumerate(mod['samples']):
        if smp['data'] is None or len(smp['data']) < 4:
            if smp['length'] > 0:
                empty_samples.add(i + 1)
            continue

        if len(song.instruments) >= MAX_INSTRUMENTS:
            log.warn(f"Instrument limit ({MAX_INSTRUMENTS}) reached — "
                     f"skipping remaining samples")
            skipped += 1
            continue

        inst = Instrument()
        inst.name = smp['name'][:16] if smp['name'] else f"Sample {i + 1}"
        inst.sample_data = smp['data']
        inst.sample_rate = _MOD_C1_RATE
        inst.base_note = 1  # C-1: matches ASM pitch table (index 0 = 1.0x)

        song.instruments.append(inst)
        inst_map[i + 1] = len(song.instruments) - 1

        vol_pct = round(smp['volume'] * 100 / 64)
        extras = []
        if smp['repeat_length'] > 2:
            dur = len(smp['data']) / _MOD_C3_RATE  # Display duration at C-3 (natural) speed
            extras.append(f"LOOP: plays {dur:.2f}s then stops")
        if smp['finetune'] != 0:
            ft = smp['finetune'] if smp['finetune'] < 8 else smp['finetune'] - 16
            extras.append(f"finetune {ft:+d}")
        extra_str = f" ({', '.join(extras)})" if extras else ""

        log.info(f"  {len(song.instruments) - 1:02d}: \"{inst.name}\" "
                 f"{len(smp['data'])} samples, vol {vol_pct}%{extra_str}")

    # Summary
    loop_count = sum(1 for s in mod['samples']
                     if s['data'] is not None and len(s['data']) >= 4
                     and s['repeat_length'] > 2)
    log.info(f"Loaded {len(song.instruments)} instrument(s)"
             + (f", skipped {skipped}" if skipped else ""))
    if loop_count:
        log.warn(f"{loop_count} sample(s) use looping — sounds will stop "
                 f"at sample end instead of sustaining. Long/sustained "
                 f"instruments may cut off abruptly.")
    if empty_samples:
        log.info(f"  Empty/silent sample numbers: "
                 f"{', '.join(str(s) for s in sorted(empty_samples))}")

    # --- Scan effects for reporting ---
    log.section("Effects")

    effect_counts = {}
    pattern_breaks = []
    position_jumps = []
    pattern_loops = {}   # pat_idx → list of (row, data)
    mid_speed_changes = 0  # Speed changes NOT on row 0

    for pat_idx, mod_pat in enumerate(mod['patterns']):
        for row_idx in range(64):
            for ch in range(MAX_CHANNELS):
                cell = mod_pat[row_idx][ch]
                eff, eff_data = cell['effect'], cell['effect_data']
                if eff == 0 and eff_data == 0:
                    continue
                key = f"E{eff_data >> 4:X}" if eff == 0xE else f"{eff:X}"
                effect_counts[key] = effect_counts.get(key, 0) + 1
                if eff == 0x0D:
                    dest = (eff_data >> 4) * 10 + (eff_data & 0x0F)
                    pattern_breaks.append((pat_idx, row_idx, dest))
                elif eff == 0x0B:
                    position_jumps.append((pat_idx, row_idx, eff_data))
                elif eff == 0x0E and (eff_data >> 4) == 6:
                    # Pattern Loop E6
                    pat_loops = pattern_loops.setdefault(pat_idx, [])
                    pat_loops.append((row_idx, eff_data & 0x0F))
                elif eff == 0x0F and row_idx > 0:
                    mid_speed_changes += 1

    for key in sorted(effect_counts.keys()):
        count = effect_counts[key]
        if key.startswith("E"):
            name = f"Extended ${key}"
        else:
            name = _EFFECT_NAMES.get(int(key, 16), f"${key}")
        status = "imported" if key in ("C", "F") else "ignored"
        log.info(f"  Effect {name}: {count}x ({status})")

    if not effect_counts:
        log.info("  No effects used")

    if pattern_breaks:
        log.info(f"{len(pattern_breaks)} Pattern Break(s) — "
                 f"patterns truncated at break row")
        for pat_idx, row_idx, dest in pattern_breaks:
            if dest > 0:
                log.info(f"    Pattern {pat_idx} row {row_idx}: break to "
                         f"row {dest} of next pattern (dest row ignored, "
                         f"pattern truncated to {row_idx + 1} rows)")
    if position_jumps:
        log.warn(f"{len(position_jumps)} Position Jump(s) — "
                 f"song order may differ from original")
        for pat_idx, row_idx, dest in position_jumps:
            log.info(f"    Pattern {pat_idx} row {row_idx}: "
                     f"jump to song position {dest}")
    if pattern_loops:
        log.warn(f"Pattern Loop (E6) in {len(pattern_loops)} pattern(s) — "
                 f"loops NOT unrolled, repeated sections will be missing")
        for pat_idx in sorted(pattern_loops.keys()):
            entries = pattern_loops[pat_idx]
            desc = ", ".join(f"row {r} E6{d:X}" for r, d in entries)
            log.info(f"    Pattern {pat_idx}: {desc}")
    if mid_speed_changes:
        log.warn(f"{mid_speed_changes} mid-pattern speed change(s) ignored "
                 f"(only row-0 speed changes are imported)")

    # --- Convert patterns ---
    log.section("Patterns")

    break_map = {}  # pat_idx → earliest break row (Dxx or Bxx)
    for pat_idx, row_idx, _ in pattern_breaks:
        if pat_idx not in break_map or row_idx < break_map[pat_idx]:
            break_map[pat_idx] = row_idx
    for pat_idx, row_idx, _ in position_jumps:
        if pat_idx not in break_map or row_idx < break_map[pat_idx]:
            break_map[pat_idx] = row_idx

    patterns_full = False
    vol_change_no_note = 0   # $C on rows without a note trigger
    note_without_sample = 0  # Note with sample_num=0 (uses fallback inst 0)

    for pat_idx, mod_pat in enumerate(mod['patterns']):
        if patterns_full:
            break

        tracker_pats = [Pattern(length=DEFAULT_LENGTH)
                        for _ in range(MAX_CHANNELS)]
        break_row = break_map.get(pat_idx, 64)

        for row_idx in range(64):
            if row_idx > break_row:
                continue  # Leave as empty default

            for ch in range(MAX_CHANNELS):
                cell = mod_pat[row_idx][ch]
                note = _period_to_note(cell['period'])
                sample_num = cell['sample']
                effect = cell['effect']
                effect_data = cell['effect_data']

                row = tracker_pats[ch].rows[row_idx]

                # Empty/silent sample → NOTE_OFF
                if sample_num > 0 and sample_num in empty_samples:
                    if note > 0:
                        row.note = NOTE_OFF
                    continue

                # Set note first
                row.note = note

                # Only populate instrument and volume when there IS a note.
                # Our audio engine ignores these fields on note=0 rows.
                # In MOD, sample-without-period changes the channel state,
                # but we can't represent that — skip to avoid dead data.
                if note > 0:
                    # Map instrument
                    if sample_num > 0 and sample_num in inst_map:
                        row.instrument = inst_map[sample_num]
                    else:
                        row.instrument = 0
                        if sample_num == 0:
                            note_without_sample += 1

                    # Volume from sample default
                    if sample_num > 0 and sample_num in inst_map:
                        smp_idx = sample_num - 1
                        if 0 <= smp_idx < len(mod['samples']):
                            row.volume = _mod_vol_to_tracker(
                                mod['samples'][smp_idx]['volume'])

                    # Effect: Set Volume ($C) — only meaningful with a note
                    if effect == 0x0C:
                        row.volume = _mod_vol_to_tracker(
                            min(64, effect_data))
                else:
                    # No note on this row
                    if effect == 0x0C:
                        vol_change_no_note += 1
                        # $C00 on empty row is channel mute — map to NOTE_OFF
                        if effect_data == 0:
                            row.note = NOTE_OFF

        # Set pattern length based on earliest break point (Dxx/Bxx).
        # MOD patterns are always 64 rows in the file, but Dxx (Pattern Break)
        # and Bxx (Position Jump) end the pattern early. The break row itself
        # plays, so effective length = break_row + 1.
        effective_length = min(break_row + 1, DEFAULT_LENGTH)
        for p in tracker_pats:
            p.length = effective_length
            p.rows = p.rows[:effective_length]

        # All 4 channel patterns must fit — don't add partial sets
        if len(song.patterns) + MAX_CHANNELS > MAX_PATTERNS:
            log.warn(f"Pattern limit ({MAX_PATTERNS}) reached at MOD pattern "
                     f"{pat_idx} — remaining patterns skipped")
            patterns_full = True
            continue

        for p in tracker_pats:
            song.patterns.append(p)

    log.info(f"Converted {mod['num_patterns']} MOD patterns -> "
             f"{len(song.patterns)} tracker patterns")
    if vol_change_no_note:
        muted = sum(1 for pi, mod_pat in enumerate(mod['patterns'])
                    for row in mod_pat for cell in row
                    if cell['effect'] == 0x0C and cell['effect_data'] == 0
                    and cell['period'] == 0)
        vol_fade = vol_change_no_note - muted
        if muted:
            log.info(f"  {muted} volume-mute(s) ($C00 on empty row) mapped to NOTE_OFF")
        if vol_fade:
            log.warn(f"{vol_fade} volume change(s) ($C on non-note rows) lost — "
                     f"our engine can't change volume without re-triggering a note")
    if note_without_sample:
        log.info(f"  {note_without_sample} note(s) without sample number — "
                 f"defaulted to instrument 00")

    # --- Determine initial speed from first PLAYED pattern ---
    # ProTracker processes channels left to right; last $F wins.
    first_pat_num = mod['pattern_order'][0] if mod['pattern_order'] else 0
    if first_pat_num < len(mod['patterns']):
        for ch in range(MAX_CHANNELS):
            cell = mod['patterns'][first_pat_num][0][ch]
            if cell['effect'] == 0x0F and 1 <= cell['effect_data'] <= 31:
                song.speed = cell['effect_data']
                # Don't break — last channel wins

    # --- Build songlines with per-position speed tracking ---
    log.section("Song")

    # Build map of which MOD patterns have Bxx (Position Jump) on any row
    pat_jump_map = {}  # pat_idx → (row, dest_position)
    for pat_idx, row_idx, dest in position_jumps:
        if pat_idx not in pat_jump_map or row_idx < pat_jump_map[pat_idx][0]:
            pat_jump_map[pat_idx] = (row_idx, dest)

    current_speed = song.speed
    bpm_count = 0
    song_end_pos = None  # Will be set if Bxx truncates the song

    for pos_idx, mod_pat_num in enumerate(mod['pattern_order']):
        base = mod_pat_num * MAX_CHANNELS
        patterns = [base + ch for ch in range(MAX_CHANNELS)]
        for ch_idx in range(MAX_CHANNELS):
            if patterns[ch_idx] >= len(song.patterns):
                patterns[ch_idx] = 0

        # Scan row 0 of this pattern for speed commands
        # ProTracker processes channels left to right; last $F wins.
        if mod_pat_num < len(mod['patterns']):
            for ch in range(MAX_CHANNELS):
                cell = mod['patterns'][mod_pat_num][0][ch]
                if cell['effect'] == 0x0F:
                    if 1 <= cell['effect_data'] <= 31:
                        current_speed = cell['effect_data']
                        # Don't break — last channel wins
                    elif cell['effect_data'] > 31:
                        bpm_count += 1

        sl = Songline(patterns=patterns, speed=current_speed)
        song.songlines.append(sl)

        # Check if this position's pattern has a Bxx (Position Jump).
        # Bxx jumps to a different song position after this pattern.
        # If it jumps backward (loop) or to the current position, the song
        # effectively ends here — positions after would never be reached.
        if mod_pat_num in pat_jump_map:
            _, dest_pos = pat_jump_map[mod_pat_num]
            if dest_pos <= pos_idx:
                song_end_pos = pos_idx
                log.info(f"  Position {pos_idx}: Bxx jumps to position "
                         f"{dest_pos} (loop) — song truncated here")
                break

    # Truncate songlines if a backward Bxx was found
    if song_end_pos is not None and len(song.songlines) > song_end_pos + 1:
        song.songlines = song.songlines[:song_end_pos + 1]

    log.info(f"Song: {len(song.songlines)} positions, "
             f"initial speed {song.speed}")
    if bpm_count:
        log.warn(f"{bpm_count} BPM tempo change(s) (speed > 31) ignored")

    # --- Finalize ---
    if not song.songlines:
        song.songlines = [Songline()]
    while len(song.patterns) < MAX_CHANNELS:
        song.patterns.append(Pattern())

    song.modified = True
    return song


# ============================================================================
# PUBLIC API
# ============================================================================

def import_mod_file(path: str, work_dir=None) -> Tuple[Optional[Song], ImportLog]:
    """Import a .MOD file and return a Song object.

    Args:
        path: Path to .MOD file
        work_dir: WorkingDirectory instance for saving sample WAVs

    Returns:
        (song, import_log) — song is None on failure
    """
    log = ImportLog()
    basename = os.path.basename(path)
    log.info(f"Importing: {basename}")

    if not os.path.exists(path):
        log.error(f"File not found: {path}")
        return None, log

    try:
        file_size = os.path.getsize(path)
        log.info(f"File size: {file_size:,} bytes")
    except OSError:
        pass

    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError as e:
        log.error(f"Cannot read file: {e}")
        return None, log

    if len(data) < 600:
        log.error("File too small to be a valid MOD")
        return None, log

    mod = parse_mod(data, log)
    if mod is None:
        return None, log

    song = mod_to_song(mod, log)

    if work_dir:
        _save_samples_to_workdir(song, work_dir, log)

    # Final summary
    log.section("Result")
    log.info(f"Instruments: {len(song.instruments)}")
    log.info(f"Patterns:    {len(song.patterns)}")
    log.info(f"Songlines:   {len(song.songlines)}")
    log.info(f"Speed:       {song.speed}")
    log.info("")
    log.info(log.summary_line())

    return song, log


def _save_samples_to_workdir(song: Song, work_dir, log: ImportLog):
    """Write instrument sample data as WAV files in work_dir.samples."""
    import wave

    samples_dir = work_dir.samples
    try:
        os.makedirs(samples_dir, exist_ok=True)
    except OSError as e:
        log.error(f"Cannot create samples directory: {e}")
        return

    saved = 0
    for idx, inst in enumerate(song.instruments):
        if inst.sample_data is None or len(inst.sample_data) == 0:
            continue

        wav_path = os.path.join(samples_dir, f"{idx:03d}.wav")
        try:
            audio_int16 = np.clip(
                inst.sample_data * 32767, -32768, 32767
            ).astype(np.int16)

            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(inst.sample_rate)
                wf.writeframes(audio_int16.tobytes())

            inst.sample_path = wav_path
            saved += 1
        except Exception as e:
            log.error(f"Failed to save sample {idx} \"{inst.name}\": {e}")

    log.info(f"Saved {saved} WAV file(s) to working directory")
