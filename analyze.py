"""
Atari Sample Tracker - Cycle Analysis Module
=============================================

Analyzes song for IRQ timing issues by simulating the 6502 cycle budget.

Key constraints:
- PAL CPU clock: 1,773,447 Hz
- Available cycles per IRQ = (1773447 / sample_rate) - overhead
- Overhead: 43 cycles (IRQ entry, register save/restore, IRQ ack)
- Each active channel: ~83 cycles (no boundary cross)
- Boundary cross: +64 cycles per cross

Critical factors:
- Sample rate (determines cycles available)
- Vector size (MIN_VECTOR - affects boundary crossing frequency)
- Number of active channels per row
- Pitch of each note (affects samples advanced per IRQ, thus boundary crossings)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from constants import NOTE_OFF, MAX_NOTES

# CPU and timing constants
PAL_CPU_CLOCK = 1773447

# Cycle costs (from detailed ASM trace - VERIFIED)
IRQ_OVERHEAD = 43           # CPU entry (7) + reg save (9) + IRQ ack (12) + reg restore + RTI (15)
CHANNEL_INACTIVE = 6        # lda trk_active (3) + beq taken (3)
CHANNEL_BASE = 75           # Active: check(5) + output(31) + pitch_accum(22) + advance(16) = 74, round up
BOUNDARY_CHECK_NO_CROSS = 8 # Final check when no crossing: lda(3) + cmp(2) + bcc taken(3)
BOUNDARY_CROSS_COST = 64    # Per boundary cross: wrap(15) + end_check(9) + reload(38) + overhead(2)

# Volume control adds ~11 cycles per active channel (AND + ORA + TAX + extra LUT)
VOLUME_CONTROL_COST = 11


@dataclass
class ChannelAnalysis:
    """Analysis result for one channel on one row."""
    note: int = 0
    pitch_multiplier: float = 0.0
    samples_per_irq: float = 0.0
    boundary_crosses: int = 0
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


def calculate_channel_cycles(pitch_multiplier: float, vector_size: int, 
                            volume_control: bool = False) -> Tuple[int, int]:
    """Calculate cycles for one active channel.
    
    Returns: (cycles, boundary_crosses)
    """
    if pitch_multiplier <= 0:
        return CHANNEL_INACTIVE, 0
    
    # Calculate boundary crosses per IRQ
    # At pitch 1.0x, we advance 1 sample per IRQ
    # With vector_size samples per vector, we cross every vector_size IRQs
    # Worst case: we could be near end of vector when we start
    samples_per_irq = pitch_multiplier
    
    # Use floor for typical case - this is minimum guaranteed crosses
    # In worst case positioning, could be +1 more
    boundary_crosses = int(samples_per_irq / vector_size)
    
    # Base cost (active check + output + pitch accum + advance)
    cycles = CHANNEL_BASE
    
    # Add boundary check cost
    cycles += BOUNDARY_CHECK_NO_CROSS
    
    # Add boundary crossing costs (each cross adds 64 cycles)
    if boundary_crosses > 0:
        cycles += BOUNDARY_CROSS_COST * boundary_crosses
    
    # Add volume control cost if enabled
    if volume_control:
        cycles += VOLUME_CONTROL_COST
    
    return cycles, boundary_crosses


def analyze_row(notes: List[int], vector_size: int, available_cycles: int,
                volume_control: bool = False) -> RowAnalysis:
    """Analyze a single row (3 channels).
    
    Args:
        notes: List of 3 note values (0 = inactive, 1-36 = note, 255 = note-off)
        vector_size: VQ vector size (MIN_VECTOR)
        available_cycles: Cycles available after overhead
        volume_control: Whether volume control is enabled
    
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
            cycles, crosses = calculate_channel_cycles(pitch, vector_size, volume_control)
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


def analyze_song(song, sample_rate: int, vector_size: int) -> AnalysisResult:
    """Analyze entire song for IRQ timing issues.
    
    Args:
        song: Song object with songlines and patterns
        sample_rate: VQ sample rate (Hz)
        vector_size: VQ vector size (MIN_VECTOR)
    
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
            row_analysis = analyze_row(notes, vector_size, available, song.volume_control)
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
    
    lines.append("=" * 60)
    lines.append("SONG TIMING ANALYSIS")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Sample Rate: {result.sample_rate} Hz")
    lines.append(f"Vector Size: {result.vector_size}")
    lines.append(f"Volume Control: {'ENABLED' if result.volume_control else 'DISABLED'}")
    lines.append("")
    lines.append(f"Cycles per IRQ: {result.cycles_per_irq}")
    lines.append(f"IRQ Overhead: {IRQ_OVERHEAD}")
    lines.append(f"Available for channels: {result.available_cycles}")
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
    
    # Problem rows list (user requested format: "s:05, r:04 - 124 cycles, 45 overflow")
    if result.problem_rows:
        lines.append("-" * 60)
        lines.append("PROBLEM ROWS (exceeding cycle budget)")
        lines.append("-" * 60)
        
        for row in result.problem_rows:
            lines.append(f"s:{row.songline:02X}, r:{row.row:02X} - "
                        f"{row.total_cycles} cycles, {row.overflow} overflow")
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
                lines.append(f"  CH{i+1}: {note_str} ({ch.pitch_multiplier:.2f}x pitch) - "
                           f"{ch.cycles} cycles, {ch.boundary_crosses} boundary crosses")
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
            lines.append("  - 5278 Hz gives +112 cycles headroom")
            lines.append("  - 3958 Hz gives +224 cycles headroom")
            lines.append("")
        
        if result.vector_size < 16:
            lines.append(f"* Use larger vector size (current: {result.vector_size})")
            lines.append("  - Vector size 16 reduces boundary crossing")
            lines.append("  - Each boundary cross costs 64 cycles")
            lines.append("")
        
        lines.append("* Avoid high-octave notes on multiple channels")
        lines.append("  - Octave 3 notes cause more boundary crosses")
        lines.append("  - Try using octave 1-2 for bass/rhythm")
        lines.append("")
        
        lines.append("* Stagger note events across rows")
        lines.append("  - Don't trigger all 3 channels on same row")
        lines.append("")
        
        if result.volume_control:
            lines.append("* Disable volume control to save ~33 cycles")
            lines.append("  (11 cycles per active channel)")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)
