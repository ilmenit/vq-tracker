"""Instrument RAW/VQ optimizer — CPU-overrun-aware.

The optimizer's primary goal is to prevent audio glitches caused by CPU
overrun (IRQ handler taking longer than the IRQ period). Secondary goal
is audio quality (RAW has no VQ artifacts).

Strategy:
  Phase 1 — Fix overruns: switch instruments to RAW where doing so
            eliminates the most overrun-IRQs per memory byte spent.
  Phase 2 — Quality: promote remaining instruments to RAW if budget allows,
            shortest first (least memory waste from page alignment).

The optimizer simulates the entire song, tracking when instruments actually
expire (based on sample length and pitch), to get accurate per-row
active-channel counts. A short hihat (80ms) that dies mid-row doesn't
count as "active" for the rest of that row.
"""

import logging
import math
import numpy as np
from typing import List, Optional, Tuple, Set, Dict
from dataclasses import dataclass, field
from collections import Counter

from constants import (
    MAX_CHANNELS, NOTE_OFF, MAX_NOTES,
    compute_memory_budget
)

logger = logging.getLogger(__name__)

# =============================================================================
# 6502 CYCLE CONSTANTS (measured from tracker_irq_speed.asm)
# =============================================================================
IRQ_OVERHEAD_CYCLES = 48    # Register save/restore, IRQEN, process_row check, RTI
CH_BASE_NOVOL = 35          # Active channel, no volume scaling
CH_BASE_VOL = 46            # Active channel, with volume scaling
CH_INACTIVE = 8             # Inactive channel (lda + bne-not-taken + jmp)

BANKING_OVERHEAD_CYCLES = 24 # 6 cycles × 4 channels for PORTB bank switching
CH_PITCH_EXTRA = 9          # Average extra for pitch accumulation
VQ_BOUNDARY_CYCLES = 53     # VQ codebook lookup (every vector_size samples)
RAW_BOUNDARY_CYCLES = 20    # RAW page advance (every 256 samples)
RAW_PAGE_SIZE = 256
CPU_CLOCK_PAL = 1773447
CPU_CLOCK_NTSC = 1789773

# Pitch multiplier table: 60 entries for 5-octave extended table
# pitch[n] = 2^((n-24)/12) — index 24 = 1.0x base pitch
PITCH_OFFSET = 24
PITCH_MULTIPLIERS = [2.0 ** ((n - PITCH_OFFSET) / 12.0) for n in range(60)]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class InstrumentAnalysis:
    """Per-instrument analysis results."""
    index: int
    name: str
    raw_size: int = 0
    raw_size_aligned: int = 0
    vq_size: int = 0
    duration_ms: int = 0
    suggest_raw: bool = False
    reason: str = ""
    cpu_cost_vq: float = 0.0
    cpu_cost_raw: float = 0.0
    cpu_saving: float = 0.0
    skipped: bool = False  # True if unused (Used Samples mode)
    # Song usage (filled by simulation)
    overrun_irqs_if_vq: int = 0     # How many overrun-IRQs this inst participates in
    overrun_irqs_fixed: int = 0     # How many of those switching to RAW would fix


@dataclass
class CpuAnalysis:
    """CPU budget analysis."""
    sample_rate: int = 0
    irq_period: float = 0.0
    total_overrun_irqs: int = 0     # Total overrun-IRQs across entire song
    worst_row_pct: float = 0.0
    worst_active_channels: int = 0
    overrun: bool = False
    warning: str = ""


@dataclass
class OptimizeResult:
    """Result of the optimize analysis."""
    analyses: List[InstrumentAnalysis] = field(default_factory=list)
    total_raw_size: int = 0
    total_vq_size: int = 0
    total_mixed_size: int = 0
    memory_budget: int = 0  # Set by caller from compute_memory_budget()
    fits_all_raw: bool = False
    summary: str = ""
    cpu: CpuAnalysis = field(default_factory=CpuAnalysis)


# =============================================================================
# SIZE COMPUTATIONS
# =============================================================================

def compute_raw_size(sample_data, sample_rate: int, target_rate: int) -> int:
    if sample_data is None or len(sample_data) == 0:
        return 0
    duration = len(sample_data) / sample_rate
    n_samples = int(duration * target_rate)
    return max(n_samples, 1)


def compute_raw_size_aligned(raw_size: int) -> int:
    if raw_size <= 0:
        return 0
    return ((raw_size + RAW_PAGE_SIZE - 1) // RAW_PAGE_SIZE) * RAW_PAGE_SIZE


def estimate_vq_size(sample_data, sample_rate: int,
                     target_rate: int, vector_size: int) -> int:
    if sample_data is None or len(sample_data) == 0:
        return 0
    duration = len(sample_data) / sample_rate
    n_samples = int(duration * target_rate)
    return max((n_samples + vector_size - 1) // vector_size, 1)


# =============================================================================
# CPU COST COMPUTATION
# =============================================================================

def _channel_cycles_vq(vector_size: int, has_pitch: bool,
                       volume_control: bool) -> float:
    base = CH_BASE_VOL if volume_control else CH_BASE_NOVOL
    if has_pitch:
        base += CH_PITCH_EXTRA
    return base + VQ_BOUNDARY_CYCLES / vector_size


def _channel_cycles_raw(has_pitch: bool, volume_control: bool) -> float:
    base = CH_BASE_VOL if volume_control else CH_BASE_NOVOL
    if has_pitch:
        base += CH_PITCH_EXTRA
    return base + RAW_BOUNDARY_CYCLES / RAW_PAGE_SIZE


def _irq_cost(active_channels: List[Tuple[int, bool]],
              mode_map: Dict[int, bool],
              vector_size: int, volume_control: bool) -> float:
    """Compute IRQ cycle cost for a set of active (inst_idx, has_pitch) channels.
    mode_map: {inst_idx: True=RAW, False=VQ}
    """
    total = IRQ_OVERHEAD_CYCLES
    n_active = len(active_channels)
    n_inactive = MAX_CHANNELS - n_active
    total += n_inactive * CH_INACTIVE

    for inst_idx, has_pitch in active_channels:
        is_raw = mode_map.get(inst_idx, False)
        if is_raw:
            total += _channel_cycles_raw(has_pitch, volume_control)
        else:
            total += _channel_cycles_vq(vector_size, has_pitch, volume_control)

    return total


# =============================================================================
# SONG SIMULATION
# =============================================================================

@dataclass
class _Segment:
    """A time segment within a row where the active channel set is constant."""
    n_irqs: int
    active: List[Tuple[int, bool]]  # [(inst_idx, has_pitch), ...]


def _compute_inst_duration_irqs(raw_size: int, pitch_mult: float) -> int:
    """How many IRQs an instrument plays before its sample runs out.
    raw_size = number of samples at target rate (1 byte per IRQ at 1x pitch).
    pitch_mult = playback speed multiplier (C-1=1.0, C-2=2.0, C-3=4.0).
    """
    if raw_size <= 0 or pitch_mult <= 0:
        return 0
    return max(int(raw_size / pitch_mult), 1)


def _simulate_song(song, inst_raw_sizes: Dict[int, int],
                   target_rate: int, system_hz: int,
                   inst_notes_map: Optional[Dict] = None,
                   instruments: Optional[list] = None
                   ) -> List[List[_Segment]]:
    """Walk every row in the song, tracking instrument expiration.

    Returns a list of rows, each row being a list of _Segments.
    """
    if not song or not song.songlines or not song.patterns:
        return []

    all_rows: List[List[_Segment]] = []

    # Per-channel state: (inst_idx, remaining_irqs, has_pitch)
    ch_inst = [None] * MAX_CHANNELS       # instrument index or None
    ch_remaining = [0] * MAX_CHANNELS     # IRQs left for this instrument
    ch_pitch = [False] * MAX_CHANNELS     # whether this note uses pitch

    # Track which notes each instrument is played at (for pitch detection)
    inst_note_set: Dict[int, Set[int]] = inst_notes_map or {}

    for sl in song.songlines:
        speed = sl.speed
        row_irqs = int(speed * target_rate / system_hz)

        patterns = []
        max_len = 0
        for ch_idx in range(MAX_CHANNELS):
            pat_idx = sl.patterns[ch_idx] if ch_idx < len(sl.patterns) else 0
            pat = song.get_pattern(pat_idx)
            patterns.append(pat)
            max_len = max(max_len, pat.length)

        for row_idx in range(max_len):
            # Process note events for this row
            for ch in range(MAX_CHANNELS):
                pat = patterns[ch]
                if row_idx >= pat.length:
                    continue
                row = pat.rows[row_idx]

                if row.note == NOTE_OFF:
                    ch_inst[ch] = None
                    ch_remaining[ch] = 0
                    ch_pitch[ch] = False
                elif row.note > 0 and 1 <= row.note <= MAX_NOTES:
                    inst_idx = row.instrument
                    # Apply base_note pitch correction (same as build.py export)
                    base_note = 1
                    if instruments and 0 <= inst_idx < len(instruments):
                        base_note = getattr(instruments[inst_idx], 'base_note', 1)
                    note_idx = row.note + PITCH_OFFSET - (base_note - 1) - 1  # 0-based
                    note_idx = max(0, min(note_idx, len(PITCH_MULTIPLIERS) - 1))
                    pitch_mult = PITCH_MULTIPLIERS[note_idx]

                    raw_sz = inst_raw_sizes.get(inst_idx, 0)
                    dur = _compute_inst_duration_irqs(raw_sz, pitch_mult)

                    ch_inst[ch] = inst_idx
                    ch_remaining[ch] = dur
                    # has_pitch = pitch_mult != 1.0
                    ch_pitch[ch] = abs(pitch_mult - 1.0) > 0.001

                    # Track note set
                    if inst_idx not in inst_note_set:
                        inst_note_set[inst_idx] = set()
                    inst_note_set[inst_idx].add(row.note)

            # Build segments within this row (active set can change as
            # instruments expire mid-row)
            segments = _build_row_segments(
                ch_inst, ch_remaining, ch_pitch, row_irqs)
            all_rows.append(segments)

            # Advance time: subtract row_irqs from remaining
            for ch in range(MAX_CHANNELS):
                if ch_inst[ch] is not None:
                    ch_remaining[ch] -= row_irqs
                    if ch_remaining[ch] <= 0:
                        ch_inst[ch] = None
                        ch_remaining[ch] = 0
                        ch_pitch[ch] = False

    return all_rows


def _build_row_segments(ch_inst, ch_remaining, ch_pitch,
                        row_irqs: int) -> List[_Segment]:
    """Break a row into segments where the active set is constant.

    Instruments can expire mid-row, changing the active set.
    """
    # Collect expiration times within this row
    events = []  # (irq_offset, channel_idx) — when channel expires
    for ch in range(MAX_CHANNELS):
        if ch_inst[ch] is not None and ch_remaining[ch] < row_irqs:
            events.append((ch_remaining[ch], ch))

    events.sort(key=lambda e: e[0])

    # Build active set snapshot
    active_chs = set()
    for ch in range(MAX_CHANNELS):
        if ch_inst[ch] is not None and ch_remaining[ch] > 0:
            active_chs.add(ch)

    segments = []
    prev_time = 0

    for expire_time, ch_expire in events:
        if expire_time <= 0:
            active_chs.discard(ch_expire)
            continue
        if expire_time > prev_time:
            # Segment from prev_time to expire_time
            dur = expire_time - prev_time
            active_list = [(ch_inst[ch], ch_pitch[ch]) for ch in range(MAX_CHANNELS)
                           if ch in active_chs]
            if dur > 0:
                segments.append(_Segment(n_irqs=dur, active=active_list))
        active_chs.discard(ch_expire)
        prev_time = expire_time

    # Final segment (from last expiration to end of row)
    remaining = row_irqs - prev_time
    if remaining > 0:
        active_list = [(ch_inst[ch], ch_pitch[ch]) for ch in range(MAX_CHANNELS)
                       if ch in active_chs]
        segments.append(_Segment(n_irqs=remaining, active=active_list))

    return segments if segments else [_Segment(n_irqs=row_irqs, active=[])]


# =============================================================================
# OVERRUN ANALYSIS
# =============================================================================

def _count_overrun_irqs(all_rows: List[List[_Segment]],
                        mode_map: Dict[int, bool],
                        vector_size: int, volume_control: bool,
                        irq_period: float) -> int:
    """Count total IRQs across the song where CPU exceeds the budget."""
    total = 0
    for segments in all_rows:
        for seg in segments:
            cost = _irq_cost(seg.active, mode_map, vector_size, volume_control)
            if cost > irq_period:
                total += seg.n_irqs
    return total


def _count_overrun_irqs_involving(all_rows: List[List[_Segment]],
                                   mode_map: Dict[int, bool],
                                   inst_idx: int,
                                   vector_size: int, volume_control: bool,
                                   irq_period: float) -> Tuple[int, int]:
    """For a given instrument, count:
    - overrun IRQs where this instrument is active (participating)
    - overrun IRQs that would be FIXED by switching this inst to RAW

    Returns (participating, fixed).
    """
    participating = 0
    fixed = 0

    # Precompute what the cost would be if this inst were RAW
    mode_if_raw = dict(mode_map)
    mode_if_raw[inst_idx] = True

    for segments in all_rows:
        for seg in segments:
            # Is this instrument active in this segment?
            inst_active = any(idx == inst_idx for idx, _ in seg.active)
            if not inst_active:
                continue

            cost_current = _irq_cost(seg.active, mode_map,
                                     vector_size, volume_control)
            if cost_current <= irq_period:
                continue  # Not an overrun segment

            participating += seg.n_irqs

            # Would switching this inst to RAW fix it?
            cost_if_raw = _irq_cost(seg.active, mode_if_raw,
                                    vector_size, volume_control)
            if cost_if_raw <= irq_period:
                fixed += seg.n_irqs

    return participating, fixed


# =============================================================================
# MAIN OPTIMIZER
# =============================================================================

def analyze_instruments(instruments, target_rate: int, vector_size: int,
                        memory_budget: int = 0,
                        vq_result=None,
                        song=None,
                        volume_control: bool = False,
                        system_hz: int = 50,
                        used_indices: set = None,
                        use_banking: bool = False,
                        banking_budget: int = 0,
                        max_banks: int = 0) -> OptimizeResult:
    """Analyze instruments and suggest RAW vs VQ for each.
    
    Args:
        used_indices: If not None, only these instrument indices are considered
                      for memory budget and mode optimization. Unused instruments
                      get suggest_raw=False (VQ, minimal overhead) and are excluded
                      from size totals.
        use_banking: If True, adds banking overhead to cycle budget.
        banking_budget: Override memory budget for banking mode (n_banks × 16KB).
        max_banks: Number of physical 16KB banks available. Used for trial-pack
                   verification when use_banking=True. If 0, derived from
                   banking_budget.
    """
    # In banking mode, override memory budget with bank capacity
    if use_banking and banking_budget > 0:
        memory_budget = banking_budget
        if max_banks == 0:
            max_banks = banking_budget // 16384
    
    result = OptimizeResult(memory_budget=memory_budget)

    if not instruments:
        result.summary = "No instruments to analyze."
        return result

    cpu_clock = CPU_CLOCK_PAL if system_hz == 50 else CPU_CLOCK_NTSC
    irq_period = cpu_clock / target_rate
    
    # Banking mode: reduce effective IRQ period by bank-switching overhead
    if use_banking:
        irq_period -= BANKING_OVERHEAD_CYCLES
    
    result.cpu.sample_rate = target_rate
    result.cpu.irq_period = irq_period

    codebook_size = 256 * vector_size

    # --- Per-instrument size analysis ---
    inst_raw_sizes: Dict[int, int] = {}

    for i, inst in enumerate(instruments):
        a = InstrumentAnalysis(index=i, name=inst.name or f"inst_{i}")

        # Mark unused instruments when used_only filtering is active
        if used_indices is not None and i not in used_indices:
            a.skipped = True
            a.reason = "unused in song"

        if inst.is_loaded():
            # Get effects-processed audio (Sustain, trim, etc.)
            # processed_data is a lazy cache — may be None after effect edits
            if inst.effects and inst.processed_data is None:
                try:
                    from sample_editor.pipeline import run_pipeline
                    inst.processed_data = run_pipeline(
                        inst.sample_data, inst.sample_rate, inst.effects)
                except Exception:
                    pass  # Fall back to raw sample_data below
            data = (inst.processed_data if inst.processed_data is not None
                    else inst.sample_data)
            sr = inst.sample_rate

            a.raw_size = compute_raw_size(data, sr, target_rate)
            a.raw_size_aligned = compute_raw_size_aligned(a.raw_size)
            inst_raw_sizes[i] = a.raw_size

            if vq_result and i < len(vq_result.inst_vq_sizes):
                a.vq_size = vq_result.inst_vq_sizes[i]
            else:
                a.vq_size = estimate_vq_size(data, sr, target_rate, vector_size)

            a.duration_ms = int(len(data) / sr * 1000)

            # CPU cost (pitch=True is worst case for estimation without song)
            a.cpu_cost_vq = _channel_cycles_vq(vector_size, True, volume_control)
            a.cpu_cost_raw = _channel_cycles_raw(True, volume_control)
            a.cpu_saving = a.cpu_cost_vq - a.cpu_cost_raw

        result.analyses.append(a)

    # --- Totals (only count non-skipped instruments) ---
    active = [a for a in result.analyses if not a.skipped]
    result.total_raw_size = sum(a.raw_size_aligned for a in active)
    result.total_vq_size = (sum(a.vq_size for a in active)
                            + codebook_size)
    result.fits_all_raw = result.total_raw_size <= memory_budget

    # --- Simulate song (if available) ---
    all_rows = _simulate_song(song, inst_raw_sizes, target_rate, system_hz,
                               instruments=instruments)

    # Start with all VQ
    mode_map: Dict[int, bool] = {a.index: False for a in result.analyses}

    # --- CPU analysis ---
    if all_rows:
        total_overruns = _count_overrun_irqs(
            all_rows, mode_map, vector_size, volume_control, irq_period)
        result.cpu.total_overrun_irqs = total_overruns
        result.cpu.overrun = total_overruns > 0

        # Find worst segment for reporting
        worst_pct = 0.0
        worst_n_ch = 0
        for segments in all_rows:
            for seg in segments:
                cost = _irq_cost(seg.active, mode_map,
                                 vector_size, volume_control)
                pct = (cost / irq_period) * 100 if irq_period else 0
                if pct > worst_pct:
                    worst_pct = pct
                    worst_n_ch = len(seg.active)
        result.cpu.worst_row_pct = worst_pct
        result.cpu.worst_active_channels = worst_n_ch

        if result.cpu.overrun:
            overrun_ms = total_overruns / target_rate * 1000
            result.cpu.warning = (
                f"{worst_n_ch}ch peak at {worst_pct:.0f}% of IRQ period. "
                f"{total_overruns} overrun IRQs ({overrun_ms:.0f}ms of glitches)")
    else:
        # No song — estimate worst case assuming all instruments on separate channels
        n_ch = min(len(result.analyses), MAX_CHANNELS)
        ch_cost = _channel_cycles_vq(vector_size, True, volume_control)
        worst_cost = IRQ_OVERHEAD_CYCLES + n_ch * ch_cost + (MAX_CHANNELS - n_ch) * CH_INACTIVE
        result.cpu.worst_row_pct = (worst_cost / irq_period) * 100
        result.cpu.worst_active_channels = n_ch
        result.cpu.overrun = worst_cost > irq_period
        if result.cpu.overrun:
            result.cpu.warning = (
                f"Estimated {n_ch}ch at {result.cpu.worst_row_pct:.0f}% "
                f"(no song data)")

    # --- Assign modes ---
    _assign_modes(result, mode_map, all_rows, codebook_size,
                  vector_size, volume_control, irq_period)

    # --- Banking: verify the result actually fits in banks ---
    # The flat-budget check in _assign_modes doesn't account for bin-packing
    # fragmentation (multi-bank instruments waste partial banks) and per-bank
    # codebook overhead.  Run a trial pack to catch overcommit.
    if use_banking and max_banks > 0:
        _verify_banking_fit(result, mode_map, codebook_size, max_banks,
                            all_rows, vector_size, volume_control, irq_period)

    return result


def _assign_modes(result: OptimizeResult, mode_map: Dict[int, bool],
                  all_rows: List[List[_Segment]], codebook_size: int,
                  vector_size: int, volume_control: bool,
                  irq_period: float):
    """Assign RAW/VQ modes. Priority: fix overruns first, then quality."""
    analyses = result.analyses
    budget = result.memory_budget
    
    # Filter out skipped (unused) instruments — they stay VQ, no budget impact
    active_analyses = [a for a in analyses if not a.skipped]

    # === TRIVIAL: all RAW fits ===
    if result.fits_all_raw:
        for a in active_analyses:
            a.suggest_raw = True
            a.reason = "Fits in memory"
            mode_map[a.index] = True
        result.total_mixed_size = result.total_raw_size
        _build_summary(result, mode_map, all_rows, vector_size,
                       volume_control, irq_period)
        return

    # === Even all-VQ overflows memory ===
    if result.total_vq_size > budget:
        for a in active_analyses:
            a.suggest_raw = False
            a.reason = "Budget exceeded even with VQ"
        result.total_mixed_size = result.total_vq_size
        result.summary = (f"WARNING: All VQ exceeds budget "
                         f"({_fmt_size(result.total_vq_size)} > "
                         f"{_fmt_size(budget)}). "
                         f"Lower sample rate or remove instruments.")
        return

    # === PHASE 1: Fix CPU overruns ===
    remaining = budget - result.total_vq_size  # memory headroom for RAW promotions
    n_raw = 0

    if all_rows and result.cpu.overrun:
        # Iteratively promote instruments to eliminate overruns.
        # Two tiers:
        #   Tier A: candidate that directly fixes overrun IRQs (crosses threshold)
        #   Tier B: candidate that reduces severity (lowers cost in overrun segments)
        #           so that a SUBSEQUENT promotion can cross the threshold
        max_iterations = len(analyses)
        for iteration in range(max_iterations):
            current_overruns = _count_overrun_irqs(
                all_rows, mode_map, vector_size, volume_control, irq_period)
            if current_overruns == 0:
                break

            best_idx = -1
            best_score = -1.0
            best_fixed = 0
            best_mem = 0
            best_tier = 'none'

            # Also track best severity-reduction candidate (Tier B)
            best_b_idx = -1
            best_b_score = -1.0
            best_b_severity = 0.0
            best_b_mem = 0

            for a in active_analyses:
                if mode_map[a.index]:
                    continue
                extra_mem = max(a.raw_size_aligned - a.vq_size, 0)
                if extra_mem > remaining:
                    continue

                participating, fixed = _count_overrun_irqs_involving(
                    all_rows, mode_map, a.index,
                    vector_size, volume_control, irq_period)

                if participating == 0:
                    continue

                if fixed > 0:
                    # Tier A: directly fixes overruns
                    score = fixed / max(extra_mem / 1024.0, 0.001)
                    if score > best_score:
                        best_score = score
                        best_idx = a.index
                        best_fixed = fixed
                        best_mem = extra_mem
                        best_tier = 'A'
                else:
                    # Tier B: reduces severity (no threshold crossing yet)
                    # Score by how much total cycle-debt it removes.
                    # cycle_saving × participating_irqs / memory_cost
                    severity = a.cpu_saving * participating
                    if extra_mem > 0:
                        b_score = severity / (extra_mem / 1024.0)
                    else:
                        b_score = float('inf')
                    if b_score > best_b_score:
                        best_b_score = b_score
                        best_b_idx = a.index
                        best_b_severity = severity
                        best_b_mem = extra_mem

            # Pick winner: prefer Tier A, fall back to Tier B
            if best_idx >= 0:
                chosen = best_idx
                chosen_mem = best_mem
                a = analyses[chosen]
                a.suggest_raw = True
                a.reason = f"fixes {best_fixed} overrun IRQs"
            elif best_b_idx >= 0:
                chosen = best_b_idx
                chosen_mem = best_b_mem
                a = analyses[chosen]
                a.suggest_raw = True
                a.reason = f"reduces overrun severity"
            else:
                break  # No candidate participates in any overrun

            mode_map[chosen] = True
            remaining -= chosen_mem
            n_raw += 1

    # === PHASE 2: Quality promotion (remaining budget) ===
    # Sort remaining VQ instruments by extra memory cost ascending
    remaining_vq = [(a.index, a.raw_size_aligned - a.vq_size, a)
                    for a in active_analyses if not mode_map[a.index]]
    remaining_vq.sort(key=lambda t: t[1])

    for idx, extra_mem, a in remaining_vq:
        if extra_mem < 0:
            extra_mem = 0
        if extra_mem <= remaining:
            mode_map[idx] = True
            a.suggest_raw = True
            a.reason = f"quality ({a.duration_ms}ms)"
            remaining -= extra_mem
            n_raw += 1
        else:
            a.suggest_raw = False
            if not a.reason:
                a.reason = "VQ saves memory"

    # Fill in reasons for any active instrument still without one
    for a in active_analyses:
        if not a.reason:
            a.reason = "VQ saves memory"

    # === Compute final totals (only active instruments) ===
    result.total_mixed_size = sum(
        a.raw_size_aligned if a.suggest_raw else a.vq_size
        for a in active_analyses
    )
    if any(not a.suggest_raw for a in active_analyses):
        result.total_mixed_size += codebook_size

    _build_summary(result, mode_map, all_rows, vector_size,
                   volume_control, irq_period)


def _build_summary(result: OptimizeResult, mode_map: Dict[int, bool],
                   all_rows: List[List[_Segment]],
                   vector_size: int, volume_control: bool,
                   irq_period: float):
    """Build human-readable summary string."""
    analyses = result.analyses
    active = [a for a in analyses if not a.skipped]
    budget = result.memory_budget
    n_raw = sum(1 for a in active if a.suggest_raw)
    n_vq = len(active) - n_raw
    n_skipped = len(analyses) - len(active)

    parts = []

    if n_vq == 0:
        parts.append(f"All {n_raw} RAW ({_fmt_size(result.total_mixed_size)} / "
                     f"{_fmt_size(budget)})")
    else:
        parts.append(f"Hybrid: {n_raw} RAW + {n_vq} VQ "
                     f"({_fmt_size(result.total_mixed_size)} / "
                     f"{_fmt_size(budget)})")
    if n_skipped:
        parts.append(f"{n_skipped} unused skipped")

    # Post-optimization CPU
    if all_rows:
        post_overruns = _count_overrun_irqs(
            all_rows, mode_map, vector_size, volume_control, irq_period)

        # Find worst segment after optimization
        worst_pct = 0.0
        for segments in all_rows:
            for seg in segments:
                cost = _irq_cost(seg.active, mode_map,
                                 vector_size, volume_control)
                pct = (cost / irq_period) * 100 if irq_period else 0
                worst_pct = max(worst_pct, pct)

        parts.append(f"CPU peak: {worst_pct:.0f}%")

        if result.cpu.total_overrun_irqs > 0:
            if post_overruns == 0:
                parts.append(f"overruns fixed!")
            else:
                post_ms = post_overruns / result.cpu.sample_rate * 1000
                parts.append(f"{post_overruns} overrun IRQs remain "
                             f"({post_ms:.0f}ms)")
    elif result.cpu.worst_row_pct > 0:
        parts.append(f"CPU est: {result.cpu.worst_row_pct:.0f}%")

    if result.cpu.warning and not any("overrun" in p.lower() for p in parts[1:]):
        parts.append(result.cpu.warning)

    result.summary = ". ".join(parts)


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB"


def _verify_banking_fit(result: OptimizeResult, mode_map: Dict[int, bool],
                        codebook_size: int, max_banks: int,
                        all_rows: List[List[_Segment]],
                        vector_size: int, volume_control: bool,
                        irq_period: float):
    """Verify optimized modes actually fit in banks; demote RAW→VQ if not.
    
    The flat-budget check in _assign_modes doesn't account for:
    - Multi-bank instruments wasting partial banks (fragmentation)
    - Page alignment waste (~128 bytes per instrument)
    - Per-bank codebook overhead (2048 bytes per VQ bank)
    
    This function runs a trial bin-pack.  If it fails, it iteratively
    demotes the largest RAW instruments to VQ (biggest fragmentation
    savings) until the pack succeeds.
    """
    logger = logging.getLogger("optimize")
    
    try:
        from bank_packer import pack_into_banks, BANK_SIZE
    except ImportError:
        logger.warning("bank_packer not available — skipping trial pack")
        return
    
    active = [a for a in result.analyses if not a.skipped]
    if not active:
        return
    
    def _build_inst_sizes():
        """Build (inst_idx, size) list from current mode_map."""
        sizes = []
        for a in active:
            sz = a.raw_size_aligned if mode_map[a.index] else a.vq_size
            if sz > 0:
                sizes.append((a.index, sz))
        return sizes
    
    def _vq_set():
        """Set of instrument indices currently in VQ mode."""
        return {a.index for a in active if not mode_map[a.index]}
    
    # Trial pack with current modes
    inst_sizes = _build_inst_sizes()
    pack = pack_into_banks(inst_sizes, max_banks,
                           codebook_size=codebook_size,
                           vq_instruments=_vq_set())
    
    if pack.success:
        return  # Fits — nothing to do
    
    logger.info(f"Trial pack failed with {max_banks} banks: {pack.error}")
    logger.info("Demoting RAW instruments to VQ to reduce fragmentation...")
    
    # Iteratively demote the RAW instrument that saves the most bank space.
    # Large multi-bank RAW instruments cause the most fragmentation because
    # ceil(size/16384) × 16384 ≫ size.  Converting to VQ shrinks the data
    # so it fits in fewer banks with less waste.
    max_demotions = sum(1 for a in active if mode_map.get(a.index, False))
    
    for iteration in range(max_demotions):
        # Find the RAW instrument whose demotion saves the most bytes
        # (i.e. biggest difference between raw_size_aligned and vq_size)
        best_idx = -1
        best_saving = -1
        for a in active:
            if not mode_map.get(a.index, False):
                continue  # already VQ
            saving = a.raw_size_aligned - a.vq_size
            if saving > best_saving:
                best_saving = saving
                best_idx = a.index
        
        if best_idx < 0:
            break  # No more RAW instruments to demote
        
        # Demote this instrument to VQ
        mode_map[best_idx] = False
        a_demoted = result.analyses[best_idx]
        a_demoted.suggest_raw = False
        a_demoted.reason = "VQ (bank fragmentation)"
        
        logger.info(f"  Demoted inst {best_idx} ({a_demoted.name}): "
                     f"RAW {a_demoted.raw_size_aligned} → VQ {a_demoted.vq_size} "
                     f"(saves {best_saving})")
        
        # Retry trial pack
        inst_sizes = _build_inst_sizes()
        pack = pack_into_banks(inst_sizes, max_banks,
                               codebook_size=codebook_size,
                               vq_instruments=_vq_set())
        
        if pack.success:
            logger.info(f"  Trial pack succeeded after {iteration + 1} demotion(s): "
                         f"{pack.n_banks_used}/{max_banks} banks used")
            break
    
    if not pack.success:
        logger.warning(f"Trial pack still fails after all demotions: {pack.error}")
    
    # Recompute totals and summary with updated modes
    result.total_mixed_size = sum(
        a.raw_size_aligned if a.suggest_raw else a.vq_size
        for a in active
    )
    if any(not a.suggest_raw for a in active):
        result.total_mixed_size += codebook_size
    
    result.fits_all_raw = False  # We had to demote — not all-RAW anymore
    
    _build_summary(result, mode_map, all_rows, vector_size,
                   volume_control, irq_period)
