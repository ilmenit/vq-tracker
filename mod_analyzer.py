#!/usr/bin/env python3
"""MOD File Analyzer — diagnoses speed, truncation, and structure issues.

Usage: python mod_analyzer.py <file.mod>

Analyzes:
  - Song structure (positions, patterns, loops)
  - Speed/BPM commands per position (Fxx)
  - Position jumps (Bxx) that cause truncation
  - Pattern breaks (Dxx) that shorten patterns
  - Bxx/Dxx interaction (Dxx before Bxx prevents Bxx from firing)
  - Sample info and memory estimates
"""

import struct
import sys
import os


# Standard ProTracker period table (finetune 0)
_PERIOD_TABLE = [
    856, 808, 762, 720, 678, 640, 604, 570, 538, 508, 480, 453,
    428, 404, 381, 360, 339, 320, 302, 285, 269, 254, 240, 226,
    214, 202, 190, 180, 170, 160, 151, 143, 135, 127, 120, 113,
]
_NOTE_NAMES = ['C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-']

_EFFECT_NAMES = {
    0x0: "Arpeggio", 0x1: "Slide Up", 0x2: "Slide Down",
    0x3: "Portamento", 0x4: "Vibrato", 0x5: "Porta+VolSlide",
    0x6: "Vib+VolSlide", 0x7: "Tremolo", 0x8: "Set Panning",
    0x9: "Sample Offset", 0xA: "Volume Slide", 0xB: "Position Jump",
    0xC: "Set Volume", 0xD: "Pattern Break", 0xE: "Extended",
    0xF: "Set Speed/BPM",
}


def period_to_note_name(period):
    if period == 0:
        return "---"
    best_idx = 0
    best_dist = abs(_PERIOD_TABLE[0] - period)
    for i, p in enumerate(_PERIOD_TABLE):
        d = abs(p - period)
        if d < best_dist:
            best_dist = d
            best_idx = i
    octave = best_idx // 12 + 1
    note = best_idx % 12
    return f"{_NOTE_NAMES[note]}{octave}"


def analyze_mod(path):
    with open(path, 'rb') as f:
        data = f.read()

    title = data[0:20].decode('ascii', errors='replace').rstrip('\x00')
    print(f"{'='*70}")
    print(f"MOD ANALYZER: {os.path.basename(path)}")
    print(f"{'='*70}")
    print(f"Title: \"{title}\"")
    print(f"File size: {len(data):,} bytes")

    # Signature
    sig = data[1080:1084]
    print(f"Signature: {sig.decode('ascii', errors='replace')}")
    n_channels = 4
    n_samples = 31
    if sig in [b'6CHN']:
        n_channels = 6
    elif sig in [b'8CHN', b'FLT8', b'OCTA']:
        n_channels = 8
    print(f"Channels: {n_channels}")
    print()

    # Samples
    print("=== SAMPLES ===")
    total_sample_bytes = 0
    samples = []
    for i in range(n_samples):
        offset = 20 + i * 30
        name = data[offset:offset+22].decode('ascii', errors='replace').rstrip('\x00')
        length = struct.unpack('>H', data[offset+22:offset+24])[0] * 2
        finetune = data[offset+24] & 0x0F
        volume = data[offset+25]
        rep_start = struct.unpack('>H', data[offset+26:offset+28])[0] * 2
        rep_len = struct.unpack('>H', data[offset+28:offset+30])[0] * 2
        total_sample_bytes += length
        samples.append({
            'name': name, 'length': length, 'finetune': finetune,
            'volume': volume, 'rep_start': rep_start, 'rep_len': rep_len
        })
        if length > 0:
            ft_str = f' ft={finetune}' if finetune else ''
            rep_str = f' loop={rep_start}-{rep_start+rep_len}' if rep_len > 2 else ''
            print(f"  {i+1:2d}: \"{name:22s}\" len={length:6d} vol={volume:2d}{ft_str}{rep_str}")
    print(f"  Total sample data: {total_sample_bytes:,} bytes")
    print()

    # Song positions
    header_end = 20 + n_samples * 30
    song_length = data[header_end]
    restart_pos = data[header_end + 1]
    pattern_order = list(data[header_end + 2:header_end + 130])

    print("=== SONG STRUCTURE ===")
    print(f"Song length: {song_length} positions")
    print(f"Restart position: {restart_pos}")
    max_pattern = max(pattern_order[:song_length])
    n_patterns = max_pattern + 1
    unique_used = sorted(set(pattern_order[:song_length]))
    print(f"Patterns: {n_patterns} total, {len(unique_used)} unique used")
    print()

    # Pattern order
    print("Pattern order:")
    for i in range(0, song_length, 16):
        chunk = pattern_order[i:min(i+16, song_length)]
        line = ' '.join(f'{p:2d}' for p in chunk)
        print(f"  Pos {i:3d}-{min(i+15, song_length-1):3d}: {line}")
    print()

    # Parse all patterns
    pattern_offset = header_end + 130
    # Detect M!K! (>64 patterns)
    if sig == b'M!K!':
        max_pattern = max(pattern_order[:song_length])
    n_patterns = max_pattern + 1

    patterns = []
    for ptn_idx in range(n_patterns):
        ptn_start = pattern_offset + ptn_idx * (64 * n_channels * 4)
        rows = []
        for row in range(64):
            channels = []
            for ch in range(n_channels):
                cell_off = ptn_start + (row * n_channels + ch) * 4
                if cell_off + 4 > len(data):
                    channels.append({'sample': 0, 'period': 0, 'effect': 0,
                                    'effect_data': 0})
                    continue
                b = data[cell_off:cell_off+4]
                sample = (b[0] & 0xF0) | ((b[2] >> 4) & 0x0F)
                period = ((b[0] & 0x0F) << 8) | b[1]
                effect = b[2] & 0x0F
                param = b[3]
                channels.append({
                    'sample': sample, 'period': period,
                    'effect': effect, 'effect_data': param
                })
            rows.append(channels)
        patterns.append(rows)

    # Collect all effects
    print("=== EFFECTS ANALYSIS ===")

    effect_counts = {}
    speed_commands = []    # (pat_idx, row, ch, value)
    bpm_commands = []      # (pat_idx, row, ch, value)
    position_jumps = []    # (pat_idx, row, ch, dest)
    pattern_breaks = []    # (pat_idx, row, ch, dest_row)

    for pat_idx, pat in enumerate(patterns):
        for row_idx, row in enumerate(pat):
            for ch, cell in enumerate(row[:4]):  # limit to 4 channels
                eff = cell['effect']
                param = cell['effect_data']
                if eff == 0 and param == 0:
                    continue

                key = f"E{param >> 4:X}" if eff == 0xE else f"{eff:X}"
                effect_counts[key] = effect_counts.get(key, 0) + 1

                if eff == 0xF:
                    if param == 0:
                        pass
                    elif param <= 31:
                        speed_commands.append((pat_idx, row_idx, ch, param))
                    else:
                        bpm_commands.append((pat_idx, row_idx, ch, param))
                elif eff == 0xB:
                    position_jumps.append((pat_idx, row_idx, ch, param))
                elif eff == 0xD:
                    dest = (param >> 4) * 10 + (param & 0x0F)
                    pattern_breaks.append((pat_idx, row_idx, ch, dest))

    for key in sorted(effect_counts.keys()):
        count = effect_counts[key]
        if key.startswith("E"):
            name = f"Extended ${key}"
        else:
            name = _EFFECT_NAMES.get(int(key, 16), f"${key}")
        print(f"  {name}: {count}x")
    print()

    # Speed commands detail
    print("=== SPEED COMMANDS (Fxx, x <= 31) ===")
    if speed_commands:
        for pat_idx, row, ch, val in speed_commands:
            used_at = [i for i in range(song_length)
                       if pattern_order[i] == pat_idx]
            pos_str = ','.join(str(p) for p in used_at[:5])
            if len(used_at) > 5:
                pos_str += f'... ({len(used_at)} total)'
            mark = " *** ROW 0" if row == 0 else ""
            print(f"  Pattern {pat_idx:2d} Row {row:2d} Ch{ch}: "
                  f"Speed = {val}{mark}  (used at pos {pos_str})")
    else:
        print("  None found")
    print()

    # BPM commands
    if bpm_commands:
        print("=== BPM/TEMPO COMMANDS (Fxx, x > 31) ===")
        for pat_idx, row, ch, val in bpm_commands:
            used_at = [i for i in range(song_length)
                       if pattern_order[i] == pat_idx]
            pos_str = ','.join(str(p) for p in used_at[:5])
            mark = " *** ROW 0" if row == 0 else ""
            print(f"  Pattern {pat_idx:2d} Row {row:2d} Ch{ch}: "
                  f"BPM = {val}{mark}  (used at pos {pos_str})")
        print()

    # Position jumps
    print("=== POSITION JUMPS (Bxx) ===")
    if position_jumps:
        # Build break_map: earliest Dxx row per pattern
        break_map = {}
        for p, r, c, d in pattern_breaks:
            if p not in break_map or r < break_map[p]:
                break_map[p] = r

        for pat_idx, row, ch, dest in position_jumps:
            used_at = [i for i in range(song_length)
                       if pattern_order[i] == pat_idx]

            # Check if a Dxx occurs before this Bxx
            dxx_row = break_map.get(pat_idx)
            blocked = ""
            if dxx_row is not None and dxx_row < row:
                blocked = f" (BLOCKED by Dxx on row {dxx_row})"

            for pos in used_at:
                direction = "BACKWARD" if dest <= pos else "FORWARD"
                truncate = " → TRUNCATES SONG HERE" if dest <= pos and not blocked else ""
                print(f"  Pattern {pat_idx:2d} Row {row:2d} Ch{ch}: "
                      f"B{dest:02X} → jump to pos {dest} "
                      f"({direction} from pos {pos}){blocked}{truncate}")
    else:
        print("  None found")
    print()

    # Pattern breaks
    if pattern_breaks:
        print("=== PATTERN BREAKS (Dxx) ===")
        for pat_idx, row, ch, dest in pattern_breaks:
            used_at = [i for i in range(song_length)
                       if pattern_order[i] == pat_idx]
            pos_str = ','.join(str(p) for p in used_at[:5])
            if len(used_at) > 5:
                pos_str += f'...'
            print(f"  Pattern {pat_idx:2d} Row {row:2d} Ch{ch}: "
                  f"break to row {dest} of next position  (used at pos {pos_str})")
        print()

    # Simulate song playback with speed tracking
    print("=== SONG POSITION DETAILS ===")
    current_speed = 6  # default
    current_bpm = 125  # default

    # Build per-pattern first-row speed
    pat_row0_speed = {}
    pat_row0_bpm = {}
    for pat_idx, row, ch, val in speed_commands:
        if row == 0:
            pat_row0_speed[pat_idx] = val  # last channel wins
    for pat_idx, row, ch, val in bpm_commands:
        if row == 0:
            pat_row0_bpm[pat_idx] = val

    # Build Bxx map (earliest Bxx per pattern, accounting for Dxx blocking)
    pat_bxx = {}  # pat_idx → (row, dest) — only if NOT blocked by Dxx
    for pat_idx, row, ch, dest in position_jumps:
        dxx_row = break_map.get(pat_idx) if pattern_breaks else None
        if dxx_row is not None and dxx_row < row:
            continue  # Dxx fires before Bxx → Bxx never executes
        if pat_idx not in pat_bxx or row < pat_bxx[pat_idx][0]:
            pat_bxx[pat_idx] = (row, dest)

    song_end = None
    for pos in range(song_length):
        ptn = pattern_order[pos]

        # Speed from row 0
        if ptn in pat_row0_speed:
            current_speed = pat_row0_speed[ptn]

        # Mid-pattern speed changes
        mid_speeds = [(r, v) for p, r, c, v in speed_commands
                      if p == ptn and r > 0]

        # Pattern break
        brk = break_map.get(ptn)
        effective_len = min(brk + 1, 64) if brk is not None else 64

        # Bxx check
        bxx_info = ""
        if ptn in pat_bxx:
            bxx_row, bxx_dest = pat_bxx[ptn]
            if bxx_dest <= pos:
                bxx_info = f" *** Bxx→pos {bxx_dest} (LOOP/END)"
                if song_end is None:
                    song_end = pos
            else:
                bxx_info = f" Bxx→pos {bxx_dest} (forward)"

        mid_str = f" +{len(mid_speeds)} mid-speed" if mid_speeds else ""
        brk_str = f" break@row{brk}" if brk is not None else ""

        print(f"  Pos {pos:2d}: Pattern {ptn:2d}  speed={current_speed}"
              f"  len={effective_len}{mid_str}{brk_str}{bxx_info}")

    print()

    # Summary
    print("=== IMPORT PREDICTION ===")
    if song_end is not None:
        print(f"  Song will be TRUNCATED: {song_length} → {song_end + 1} positions")
        print(f"  Reason: Position {song_end} has Bxx that jumps backward (loop)")
        print(f"  Positions {song_end+1}-{song_length-1} are unreachable in playback")
    else:
        print(f"  Song: {song_length} positions (no truncation)")

    # Speed warnings
    if pat_row0_speed:
        print()
        first_ptn = pattern_order[0]
        if first_ptn in pat_row0_speed:
            print(f"  Initial speed: {pat_row0_speed[first_ptn]} "
                  f"(from pattern {first_ptn} row 0)")
            if pat_row0_speed[first_ptn] == 1:
                print(f"  WARNING: Speed 1 = 1 tick/row = VERY FAST playback!")
                print(f"           This might be intentional (speed 1 used as")
                print(f"           a timing technique in some MODs)")
        else:
            print(f"  Initial speed: 6 (default, no Fxx on row 0 of first pattern)")

    # Show per-position speed summary if there are changes
    speeds_seen = set()
    cs = 6
    for pos in range(min(song_length, song_end + 1 if song_end else song_length)):
        ptn = pattern_order[pos]
        if ptn in pat_row0_speed:
            cs = pat_row0_speed[ptn]
        speeds_seen.add(cs)

    if len(speeds_seen) > 1:
        print(f"  Speed values used across song: {sorted(speeds_seen)}")
    print()

    # Detailed first few rows for debugging
    print("=== FIRST PATTERN DETAIL (row 0-7) ===")
    first_ptn = pattern_order[0]
    pat = patterns[first_ptn]
    print(f"  Pattern {first_ptn}:")
    for row_idx in range(min(8, len(pat))):
        cells = []
        for ch in range(min(4, len(pat[row_idx]))):
            cell = pat[row_idx][ch]
            note = period_to_note_name(cell['period'])
            smp = cell['sample']
            eff = cell['effect']
            param = cell['effect_data']
            smp_str = f"{smp:2d}" if smp > 0 else "--"
            if eff == 0 and param == 0:
                eff_str = "---"
            else:
                eff_str = f"{eff:X}{param:02X}"
            cells.append(f"{note} {smp_str} {eff_str}")
        print(f"    Row {row_idx:2d}: {'  |  '.join(cells)}")
    print()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <file.mod>")
        sys.exit(1)
    analyze_mod(sys.argv[1])
