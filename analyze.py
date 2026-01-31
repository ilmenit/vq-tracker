"""
POKEY VQ Tracker - Cycle Analysis Module
=============================================

Analyzes song for IRQ timing issues by simulating the 6502 cycle budget.

Key constraints:
- PAL CPU clock: 1,773,447 Hz
- Available cycles per IRQ = (1773447 / sample_rate) - overhead
- Overhead: 43 cycles (CPU auto + register save/restore + IRQ ack)

TWO OPTIMIZATION MODES:

SIZE MODE (OPTIMIZE_SPEED=0):
- Nibble-packed data (2 samples per byte)
- Each active channel: 83 cycles (no boundary cross)
- With boundary cross: 145 cycles
- Codebook size: 2KB (256 vectors × 8 bytes)
- Best for: Memory-constrained projects

SPEED MODE (OPTIMIZE_SPEED=1):
- Full bytes with $10 pre-baked
- Each active channel: 63 cycles (no boundary cross)  
- With boundary cross: 125 cycles
- Codebook size: 4KB (256 vectors × 16 bytes)
- Best for: Higher sample rates, smoother playback

Volume Control: +11 cycles per active channel (both modes)

Critical factors:
- Sample rate (determines cycles available)
- Vector size (MIN_VECTOR - affects boundary crossing frequency)
- Number of active channels per row
- Pitch of each note (affects samples advanced per IRQ)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from constants import NOTE_OFF, MAX_NOTES

# CPU and timing constants
PAL_CPU_CLOCK = 1773447

# =============================================================================
# CYCLE COSTS - OPTIMIZED PLAYER (no boundary loop, O(1) crossing)
# =============================================================================
# Boundary crossing handled in one pass using shifts/masks, regardless of count.
# Cycle counts verified by manual trace of tracker_irq_speed.asm / tracker_irq_size.asm
#
# VERIFIED CYCLE BREAKDOWN (2024-01 re-audit after irq_busy removal):
#
# IRQ OVERHEAD (always):
#   CPU auto push (PC, P):   7 cycles
#   Entry (save regs, ack): 21 cycles (sta×3 + lda+sta×2)
#   Exit (restore, rti):    15 cycles (lda×3 + rti)
#   Total:                  43 cycles
#
# COMMON TO BOTH MODES:
#   Inactive channel:        6 cycles (lda zp + beq taken)
#   Active check:            5 cycles (lda zp + beq not taken)
#   Pitch accumulator:      22 cycles (clc + 6×zp ops + beq not taken)
#   Advance offset:         16 cycles (clc + 4×zp ops + lda# + sta)
#   Boundary check (no):     8 cycles (lda + cmp + bcc taken)
#   Boundary check (yes):    7 cycles (lda + cmp + bcc not taken)
#   Boundary cross code:    63 cycles (tax + shifts + add + mask + end check + load)
#   Volume control:        +11 cycles (and + ora + tax + lda abs,y)

IRQ_OVERHEAD = 43           # CPU entry (7) + reg save/ack (21) + reg restore/RTI (15)
CHANNEL_INACTIVE = 6        # lda trk_active (3) + beq taken (3)

# -----------------------------------------------------------------------------
# SIZE MODE - Nibble-packed (OPTIMIZE_SPEED=0)
# -----------------------------------------------------------------------------
# Output section: 32 cycles (worst case, even offset with jmp)
#   lda zp + lsr + tay + lda(),y + tax + lda zp + and# + bne not taken
#   + lda abs,x + sta abs + jmp = 3+2+2+5+2+3+2+2+4+4+3 = 32
#
# Total breakdown:
#   Active check:       5
#   Output:            32
#   Pitch+beq:         22
#   Advance:           16
#   Boundary (no):      8
#   -----------------------
#   NO CROSS:          83 cycles
#
#   Boundary (yes):     7
#   Cross code:        63
#   -----------------------
#   WITH CROSS:       145 cycles (5+32+22+16+7+63)

SIZE_CHANNEL_NO_CROSS = 83
SIZE_CHANNEL_WITH_CROSS = 145

# -----------------------------------------------------------------------------
# SPEED MODE - Full bytes (OPTIMIZE_SPEED=1)
# -----------------------------------------------------------------------------
# Output section: 12 cycles
#   ldy zp + lda(),y + sta abs = 3+5+4 = 12
#
# Total breakdown:
#   Active check:       5
#   Output:            12
#   Pitch+beq:         22
#   Advance:           16
#   Boundary (no):      8
#   -----------------------
#   NO CROSS:          63 cycles
#
#   Boundary (yes):     7
#   Cross code:        63
#   -----------------------
#   WITH CROSS:       125 cycles (5+12+22+16+7+63)

SPEED_CHANNEL_NO_CROSS = 63
SPEED_CHANNEL_WITH_CROSS = 125

# Volume control adds same cost in both modes:
# and #$0F (2) + ora zp (3) + tax (2) + lda abs,x (4) = 11 cycles
# (replaces simple sta with scaled lookup)
VOLUME_CONTROL_COST = 11


@dataclass
class ChannelAnalysis:
    """Analysis result for one channel on one row."""
    note: int = 0
    pitch_multiplier: float = 0.0
    samples_per_irq: float = 0.0
    boundary_crosses: int = 0      # For informational purposes
    cycles: int = 0
    active: bool = False


@dataclass
class RowAnalysis:
    """Analysis result for one row."""
    songline: int
    row: int
    channels: List[ChannelAnalysis]
    total_cycles: int
    available_cycles: int
    overflow: int = 0
    
    @property
    def is_over_budget(self) -> bool:
        return self.overflow > 0
    
    @property
    def utilization(self) -> float:
        return self.total_cycles / self.available_cycles if self.available_cycles > 0 else 0


@dataclass
class AnalysisResult:
    """Complete song analysis result."""
    sample_rate: int
    vector_size: int
    volume_control: bool
    optimize_speed: bool  # True=speed mode, False=size mode
    cycles_per_irq: int
    available_cycles: int
    
    total_rows: int = 0
    problem_rows: List[RowAnalysis] = field(default_factory=list)
    worst_case: Optional[RowAnalysis] = None
    
    # Statistics
    max_cycles: int = 0
    avg_cycles: float = 0.0
    over_budget_count: int = 0
    
    @property
    def is_safe(self) -> bool:
        return self.over_budget_count == 0
    
    @property
    def volume_safe(self) -> bool:
        """Check if sample rate is low enough for volume control."""
        # Volume control needs ~39 extra cycles for 3 channels
        # Safe threshold is around 5757 Hz or lower
        return self.sample_rate <= 5757


def get_pitch_multiplier(note: int) -> float:
    """Get pitch multiplier for note (1-36).
    
    Note encoding:
    - 1 (C-1) = 1.0x (original speed)
    - 13 (C-2) = 2.0x
    - 25 (C-3) = 4.0x
    - 36 (B-3) = ~7.55x
    """
    if note <= 0 or note > MAX_NOTES or note == NOTE_OFF:
        return 0.0
    
    # Each semitone multiplies by 2^(1/12)
    # Note 1 = C-1 = 1.0x (pitch table index 0)
    return 2.0 ** ((note - 1) / 12.0)


def calculate_boundary_crosses(pitch_multiplier: float, vector_size: int) -> int:
    """Calculate expected boundary crosses per IRQ.
    
    With pitch_multiplier samples advanced per IRQ and vector_size samples per vector:
    - Minimum crosses = floor(pitch_multiplier / vector_size)
    - Could be +1 if starting near end of vector (worst case)
    
    Returns average/typical case.
    """
    if pitch_multiplier <= 0:
        return 0
    return int(pitch_multiplier / vector_size)


def calculate_channel_cycles(pitch_multiplier: float, vector_size: int, 
                            volume_control: bool = False,
                            optimize_speed: bool = True) -> Tuple[int, int]:
    """Calculate cycles for one active channel (OPTIMIZED PLAYER).
    
    With optimized player, boundary crossing is O(1) - fixed cost regardless
    of how many boundaries are crossed. This makes high-pitch notes much cheaper!
    
    Args:
        pitch_multiplier: Pitch value (1.0 = original speed, 2.0 = octave up, etc.)
        vector_size: VQ vector size (MIN_VECTOR)
        volume_control: Whether volume control is enabled
        optimize_speed: True=speed mode (~63 cyc), False=size mode (~83 cyc)
    
    Returns: (cycles, boundary_crosses)
    """
    if pitch_multiplier <= 0:
        return CHANNEL_INACTIVE, 0
    
    # Select cycle costs based on optimization mode
    if optimize_speed:
        base_no_cross = SPEED_CHANNEL_NO_CROSS      # 63 cycles
        base_with_cross = SPEED_CHANNEL_WITH_CROSS  # 125 cycles
    else:
        base_no_cross = SIZE_CHANNEL_NO_CROSS       # 83 cycles
        base_with_cross = SIZE_CHANNEL_WITH_CROSS   # 145 cycles
    
    # Calculate expected boundary crosses (for informational purposes)
    boundary_crosses = calculate_boundary_crosses(pitch_multiplier, vector_size)
    
    # OPTIMIZED: Crossing boundaries is FIXED cost, not multiplicative
    # If pitch_multiplier >= vector_size, we WILL cross at least one boundary
    will_cross = pitch_multiplier >= vector_size
    
    if will_cross:
        cycles = base_with_cross  # Fixed cost regardless of how many crossed
    else:
        cycles = base_no_cross
    
    # Add volume control cost if enabled (same for both modes: 11 cycles)
    if volume_control:
        cycles += VOLUME_CONTROL_COST
    
    return cycles, boundary_crosses


def analyze_row(notes: List[int], vector_size: int, available_cycles: int,
                volume_control: bool = False, optimize_speed: bool = True) -> RowAnalysis:
    """Analyze a single row (3 channels).
    
    Args:
        notes: List of 3 note values (0 = inactive, 1-36 = note, 255 = note-off)
        vector_size: VQ vector size (MIN_VECTOR)
        available_cycles: Cycles available after overhead
        volume_control: Whether volume control is enabled
        optimize_speed: True=speed mode (~63 cyc), False=size mode (~83 cyc)
    
    Returns:
        RowAnalysis with per-channel breakdown
    """
    channels = []
    total_cycles = 0
    
    for note in notes:
        if note == 0 or note == NOTE_OFF:
            # Inactive channel
            ch = ChannelAnalysis(
                note=note,
                pitch_multiplier=0.0,
                samples_per_irq=0.0,
                boundary_crosses=0,
                cycles=CHANNEL_INACTIVE,
                active=False
            )
        else:
            # Active channel
            pitch = get_pitch_multiplier(note)
            cycles, crosses = calculate_channel_cycles(pitch, vector_size, volume_control, optimize_speed)
            ch = ChannelAnalysis(
                note=note,
                pitch_multiplier=pitch,
                samples_per_irq=pitch,
                boundary_crosses=crosses,
                cycles=cycles,
                active=True
            )
        
        channels.append(ch)
        total_cycles += ch.cycles
    
    overflow = max(0, total_cycles - available_cycles)
    
    return RowAnalysis(
        songline=0,  # Set by caller
        row=0,       # Set by caller
        channels=channels,
        total_cycles=total_cycles,
        available_cycles=available_cycles,
        overflow=overflow
    )


def analyze_song(song, sample_rate: int, vector_size: int, 
                 optimize_speed: bool = True) -> AnalysisResult:
    """Analyze entire song for IRQ timing issues.
    
    Args:
        song: Song object with songlines and patterns
        sample_rate: VQ sample rate (Hz)
        vector_size: VQ vector size (MIN_VECTOR)
        optimize_speed: True=speed mode (~58 cyc), False=size mode (~83 cyc)
    
    Returns:
        AnalysisResult with all problem rows and statistics
    """
    # Calculate timing budget
    cycles_per_irq = PAL_CPU_CLOCK // sample_rate
    available = cycles_per_irq - IRQ_OVERHEAD
    
    result = AnalysisResult(
        sample_rate=sample_rate,
        vector_size=vector_size,
        volume_control=song.volume_control,
        optimize_speed=optimize_speed,
        cycles_per_irq=cycles_per_irq,
        available_cycles=available
    )
    
    total_cycle_sum = 0
    
    # Iterate through all songlines and rows
    for sl_idx, songline in enumerate(song.songlines):
        patterns = [song.patterns[p] if p < len(song.patterns) else None 
                   for p in songline.patterns]
        max_len = max((p.length if p else 0) for p in patterns)
        
        for row_idx in range(max_len):
            # Get notes for this row on all 3 channels
            notes = []
            for ch, ptn in enumerate(patterns):
                if ptn and row_idx < ptn.length:
                    row = ptn.rows[row_idx] if row_idx < len(ptn.rows) else None
                    notes.append(row.note if row else 0)
                else:
                    notes.append(0)
            
            # Analyze this row
            row_analysis = analyze_row(notes, vector_size, available, song.volume_control, optimize_speed)
            row_analysis.songline = sl_idx
            row_analysis.row = row_idx
            
            # Update statistics
            result.total_rows += 1
            total_cycle_sum += row_analysis.total_cycles
            
            if row_analysis.total_cycles > result.max_cycles:
                result.max_cycles = row_analysis.total_cycles
                result.worst_case = row_analysis
            
            if row_analysis.is_over_budget:
                result.over_budget_count += 1
                result.problem_rows.append(row_analysis)
    
    # Calculate average
    if result.total_rows > 0:
        result.avg_cycles = total_cycle_sum / result.total_rows
    
    return result


def format_analysis_report(result: AnalysisResult) -> str:
    """Format analysis result as human-readable report."""
    lines = []
    
    # Get mode-specific cycle costs for display
    if result.optimize_speed:
        mode_name = "SPEED"
        ch_no_cross = SPEED_CHANNEL_NO_CROSS
        ch_with_cross = SPEED_CHANNEL_WITH_CROSS
    else:
        mode_name = "SIZE"
        ch_no_cross = SIZE_CHANNEL_NO_CROSS
        ch_with_cross = SIZE_CHANNEL_WITH_CROSS
    
    lines.append("=" * 60)
    lines.append(f"SONG TIMING ANALYSIS ({mode_name} MODE)")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Sample Rate: {result.sample_rate} Hz")
    lines.append(f"Vector Size: {result.vector_size}")
    lines.append(f"Optimize Mode: {mode_name}")
    lines.append(f"Volume Control: {'ENABLED' if result.volume_control else 'DISABLED'}")
    lines.append("")
    lines.append(f"Cycles per IRQ: {result.cycles_per_irq}")
    lines.append(f"IRQ Overhead: {IRQ_OVERHEAD}")
    lines.append(f"Available for channels: {result.available_cycles}")
    lines.append("")
    
    # Channel cost breakdown
    lines.append(f"Channel cycle costs ({mode_name} mode):")
    lines.append(f"  Inactive channel: {CHANNEL_INACTIVE} cycles")
    lines.append(f"  Active (no boundary cross): ~{ch_no_cross} cycles")
    lines.append(f"  Active (with boundary cross): ~{ch_with_cross} cycles")
    if result.volume_control:
        lines.append(f"  Volume control: +{VOLUME_CONTROL_COST} cycles/channel")
    lines.append("")
    
    # Volume control warning
    if result.volume_control and not result.volume_safe:
        lines.append("WARNING: Volume control enabled but sample rate too high!")
        lines.append(f"   Recommended: <=5757 Hz (current: {result.sample_rate} Hz)")
        lines.append("")
    
    # Summary
    lines.append("-" * 60)
    lines.append("SUMMARY")
    lines.append("-" * 60)
    lines.append(f"Total rows analyzed: {result.total_rows}")
    lines.append(f"Average cycles/row: {result.avg_cycles:.1f}")
    lines.append(f"Maximum cycles: {result.max_cycles}")
    lines.append(f"Problem rows: {result.over_budget_count}")
    lines.append("")
    
    if result.is_safe:
        lines.append("[PASS] No timing issues detected")
    else:
        pct = (result.over_budget_count / result.total_rows * 100) if result.total_rows > 0 else 0
        lines.append(f"[FAIL] {result.over_budget_count} rows exceed budget ({pct:.1f}%)")
    
    lines.append("")
    
    # Problem rows list
    if result.problem_rows:
        lines.append("-" * 60)
        lines.append("PROBLEM ROWS (exceeding cycle budget)")
        lines.append("-" * 60)
        
        # Show first 20 problem rows
        for row in result.problem_rows[:20]:
            lines.append(f"s:{row.songline:02X}, r:{row.row:02X} - "
                        f"{row.total_cycles} cycles, {row.overflow} overflow")
        
        if len(result.problem_rows) > 20:
            lines.append(f"... and {len(result.problem_rows) - 20} more")
        lines.append("")
    
    # Worst case details
    if result.worst_case:
        lines.append("-" * 60)
        lines.append("WORST CASE ROW DETAILS")
        lines.append("-" * 60)
        wc = result.worst_case
        lines.append(f"Location: Songline {wc.songline:02X}, Row {wc.row:02X}")
        lines.append(f"Total: {wc.total_cycles} cycles ({wc.utilization*100:.0f}% of budget)")
        if wc.overflow > 0:
            lines.append(f"Overflow: {wc.overflow} cycles")
        lines.append("")
        lines.append("Per-channel breakdown:")
        for i, ch in enumerate(wc.channels):
            if ch.active:
                from constants import note_to_str
                note_str = note_to_str(ch.note)
                cross_info = "crosses boundary" if ch.boundary_crosses > 0 else "no boundary cross"
                lines.append(f"  CH{i+1}: {note_str} ({ch.pitch_multiplier:.2f}x) - "
                           f"{ch.cycles} cycles ({cross_info})")
            else:
                lines.append(f"  CH{i+1}: --- (inactive) - {ch.cycles} cycles")
        lines.append("")
    
    # Recommendations
    lines.append("-" * 60)
    lines.append("RECOMMENDATIONS")
    lines.append("-" * 60)
    
    if result.is_safe:
        lines.append("[OK] Song should play correctly on Atari hardware.")
        if result.volume_control and result.volume_safe:
            lines.append("[OK] Volume control is enabled and sample rate is compatible.")
    else:
        lines.append("To fix timing issues, consider:")
        lines.append("")
        
        # Check if lower rate would help
        if result.sample_rate > 5278:
            lines.append(f"* Lower sample rate (current: {result.sample_rate} Hz)")
            lines.append("  - 5278 Hz gives ~293 cycles available")
            lines.append("  - 3958 Hz gives ~405 cycles available")
            lines.append("")
        
        # Note about vector size with optimized player
        lines.append(f"* Vector size {result.vector_size} - with optimized player,")
        lines.append("  high-pitch notes have FIXED cost (no loop penalty)")
        lines.append("")
        
        lines.append("* Reduce number of simultaneous active channels")
        if result.optimize_speed:
            lines.append("  - SPEED mode: ~63-125 cycles per active channel")
        else:
            lines.append("  - SIZE mode: ~83-145 cycles per active channel")
        lines.append(f"  - Inactive channels cost only {CHANNEL_INACTIVE} cycles")
        lines.append("")
        
        if result.volume_control:
            total_vol = VOLUME_CONTROL_COST * 3
            lines.append(f"* Disable volume control to save ~{total_vol} cycles total")
            lines.append(f"  ({VOLUME_CONTROL_COST} cycles per active channel)")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)
