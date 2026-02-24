"""Atari 800 system emulator for cycle-accurate timing analysis.

Ties together py65 CPU, ANTIC DMA model, and POKEY timer to measure
exactly how many cycles each IRQ handler invocation takes and whether
it fits within the timer period.

This is NOT a general-purpose Atari emulator. It models only what's
needed for timing analysis: CPU execution, timer IRQs, DMA cycle
stealing, and VCOUNT for the player's frame detection loop.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Callable

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

logger = logging.getLogger(__name__)

# =========================================================================
# Atari hardware constants
# =========================================================================

PAL_SCANLINES = 312
NTSC_SCANLINES = 262
CYCLES_PER_SCANLINE = 114
PAL_FRAME_CYCLES = PAL_SCANLINES * CYCLES_PER_SCANLINE   # 35568
NTSC_FRAME_CYCLES = NTSC_SCANLINES * CYCLES_PER_SCANLINE  # 29868

# Hardware register addresses
DMACTL = 0xD400
VCOUNT = 0xD40B
NMIEN  = 0xD40E
DLISTL = 0xD402
DLISTH = 0xD403

# POKEY registers
AUDF1  = 0xD200
AUDC1  = 0xD201
AUDF2  = 0xD202
AUDF3  = 0xD204
AUDF4  = 0xD206
AUDCTL = 0xD208
STIMER_W = 0xD209  # Write: start timers
KBCODE_R = 0xD209  # Read: keyboard code (same addr)
SKSTAT_R = 0xD20F  # Read: serial port status
SKCTL_W  = 0xD20F  # Write: serial port control
IRQEN_W  = 0xD20E  # Write: IRQ enable
IRQST_R  = 0xD20E  # Read: IRQ status
RANDOM_R = 0xD20A  # Read: random number

# GTIA
CONSOL = 0xD01F
COLBK  = 0xD01A

# PIA
PORTB  = 0xD301

# Interrupt vectors (in RAM-under-ROM)
NMI_VECTOR = 0xFFFA
IRQ_VECTOR = 0xFFFE

# Zero-page addresses for the tracker player (from zeropage.inc)
ZP_SEQ_ROW      = 0x8D
ZP_SEQ_TICK     = 0x8E
ZP_SEQ_PLAYING  = 0x8F
ZP_SEQ_SONGLINE = 0x9D
ZP_SEQ_SPEED    = 0xAD


# =========================================================================
# DMA model
# =========================================================================

def compute_dma_table(memory, is_pal: bool = True) -> List[int]:
    """Build per-scanline DMA cycle cost from the display list in memory.

    Returns list of DMA cycles stolen per scanline.
    """
    n_lines = PAL_SCANLINES if is_pal else NTSC_SCANLINES
    dma = [9] * n_lines  # Memory refresh: 9 cycles every line

    try:
        dmactl_val = memory[DMACTL]
    except (IndexError, TypeError):
        return dma

    if not (dmactl_val & 0x20):  # Bit 5 = DL DMA enable
        return dma

    dl_addr = memory[DLISTL] | (memory[DLISTH] << 8)
    pf_width = dmactl_val & 0x03
    width_chars = {0: 0, 1: 32, 2: 40, 3: 48}.get(pf_width, 0)

    scanline = 0
    for _ in range(256):
        if scanline >= n_lines or dl_addr > 0xFFFF:
            break

        opcode = memory[dl_addr]
        dl_addr = (dl_addr + 1) & 0xFFFF
        mode = opcode & 0x0F

        if mode == 0:
            n_blank = ((opcode >> 4) & 0x07) + 1
            scanline += n_blank
            continue

        if mode == 1:
            target = memory[dl_addr] | (memory[(dl_addr + 1) & 0xFFFF] << 8)
            dl_addr = (dl_addr + 2) & 0xFFFF
            if opcode & 0x40:
                break  # JVB
            dl_addr = target
            continue

        mode_scanlines = {
            2: 8, 3: 10, 4: 8, 5: 16, 6: 8, 7: 16,
            8: 8, 9: 4, 10: 4, 11: 2, 12: 1, 13: 2, 14: 1, 15: 1,
        }
        mode_dma = {
            2: width_chars, 3: width_chars, 4: width_chars, 5: width_chars,
            6: width_chars // 2, 7: width_chars // 2,
            8: width_chars // 4, 9: width_chars // 4,
            10: width_chars // 2, 11: width_chars // 2,
            12: width_chars // 2, 13: width_chars // 2,
            14: width_chars, 15: width_chars,
        }

        n_sl = mode_scanlines.get(mode, 8)
        dma_cost = mode_dma.get(mode, 0)

        if opcode & 0x40:  # LMS
            dl_addr = (dl_addr + 2) & 0xFFFF

        for sl in range(n_sl):
            line = scanline + sl
            if line < n_lines:
                dma[line] += dma_cost
                if sl == 0:
                    dma[line] += 1  # DL fetch
                if mode <= 7 and sl == 0:
                    dma[line] += width_chars  # Char name table

        scanline += n_sl

    return dma


def compute_dma_budgets(dma_table: List[int], timer_period: int) -> tuple:
    """Compute worst/best/avg DMA cost per timer period.

    Returns (worst_dma, best_dma, avg_dma).
    """
    n_lines = len(dma_table)
    if timer_period <= 0 or n_lines == 0:
        return 0, 0, 0

    span_lines = max(1, (timer_period + CYCLES_PER_SCANLINE - 1) //
                     CYCLES_PER_SCANLINE)

    worst = 0
    best = 999999
    total = 0

    for start_line in range(n_lines):
        dma_sum = 0
        for d in range(span_lines):
            dma_sum += dma_table[(start_line + d) % n_lines]
        worst = max(worst, dma_sum)
        best = min(best, dma_sum)
        total += dma_sum

    avg = total // n_lines
    return worst, best, avg


# =========================================================================
# Tick measurement
# =========================================================================

@dataclass
class TickMeasurement:
    """One timer IRQ tick measurement."""
    frame: int
    tick_in_frame: int
    songline: int
    row: int
    handler_cycles: int
    timer_period: int

    @property
    def margin_no_dma(self) -> int:
        return self.timer_period - self.handler_cycles

    def margin_with_dma(self, dma_cycles: int) -> int:
        return self.timer_period - self.handler_cycles - dma_cycles


@dataclass
class RowResult:
    """Aggregated result for one song row."""
    songline: int
    row: int
    worst_handler_cycles: int
    n_ticks: int
    timer_period: int
    n_active: int = 0

    def status(self, worst_dma: int, best_dma: int) -> str:
        budget_worst = self.timer_period - worst_dma
        if self.worst_handler_cycles > budget_worst:
            return 'overrun'
        budget_best = self.timer_period - best_dma
        if self.worst_handler_cycles > budget_best * 0.85:
            return 'tight'
        return 'ok'

    def margin_worst(self, worst_dma: int) -> int:
        return self.timer_period - self.worst_handler_cycles - worst_dma

    def margin_best(self, best_dma: int) -> int:
        return self.timer_period - self.worst_handler_cycles - best_dma


# =========================================================================
# Atari System Emulator
# =========================================================================

class AtariSystem:
    """Minimal Atari 800 emulation for timing analysis."""

    def __init__(self, is_pal: bool = True):
        self.is_pal = is_pal
        self.frame_cycles = PAL_FRAME_CYCLES if is_pal else NTSC_FRAME_CYCLES
        self.n_scanlines = PAL_SCANLINES if is_pal else NTSC_SCANLINES

        self.memory = ObservableMemory()
        self.cpu = MPU(memory=self.memory, pc=0)

        # POKEY timer state
        self.timer_period = 0
        self.timer_counter = 0
        self.timer_irq_enabled = False
        self.audctl = 0
        self.audf1 = 0

        # Frame tracking
        self.frame_cycle = 0
        self.frame_count = 0

        # IRQ state
        self._in_irq = False
        self._tick_in_frame = 0

        # Keyboard simulation
        self._key_pressed = False
        self._key_code = 0xFF

        # Results
        self.ticks: List[TickMeasurement] = []

        self._setup_observers()

    def _setup_observers(self):
        mem = self.memory

        # POKEY writes
        mem.subscribe_to_write([AUDF1], self._on_audf1_write)
        mem.subscribe_to_write([AUDCTL], self._on_audctl_write)
        mem.subscribe_to_write([STIMER_W], self._on_stimer_write)
        mem.subscribe_to_write([IRQEN_W], self._on_irqen_write)

        # Absorb writes to audio regs, GTIA, PIA, etc.
        for addr in [AUDC1, 0xD203, 0xD205, 0xD207,
                     AUDF2, 0xD204, 0xD206,
                     PORTB, DMACTL, 0xD400,
                     COLBK, 0xD016, 0xD017, 0xD018, 0xD01A,
                     NMIEN, SKCTL_W,
                     DLISTL, DLISTH]:
            mem.subscribe_to_write([addr], lambda a, v: None)

        # POKEY reads
        mem.subscribe_to_read([IRQST_R], self._on_irqst_read)
        mem.subscribe_to_read([KBCODE_R], self._on_kbcode_read)
        mem.subscribe_to_read([SKSTAT_R], self._on_skstat_read)
        mem.subscribe_to_read([RANDOM_R], self._on_random_read)

        # ANTIC reads
        mem.subscribe_to_read([VCOUNT], self._on_vcount_read)

        # GTIA reads
        mem.subscribe_to_read([CONSOL], lambda a: 0x07)

    def _on_audf1_write(self, addr, val):
        self.audf1 = val
        self._recalc_timer_period()

    def _on_audctl_write(self, addr, val):
        self.audctl = val
        self._recalc_timer_period()

    def _on_stimer_write(self, addr, val):
        if self.timer_period > 0:
            self.timer_counter = self.timer_period

    def _on_irqen_write(self, addr, val):
        self.timer_irq_enabled = bool(val & 0x01)

    def _on_irqst_read(self, addr):
        return 0xFE if self._in_irq else 0xFF

    def _on_kbcode_read(self, addr):
        return self._key_code

    def _on_skstat_read(self, addr):
        return 0xFB if self._key_pressed else 0xFF

    def _on_random_read(self, addr):
        return (self.frame_cycle * 7 + 13) & 0xFF

    def _on_vcount_read(self, addr):
        scanline = self.frame_cycle // CYCLES_PER_SCANLINE
        return min((scanline >> 1) & 0xFF, 155)

    def _recalc_timer_period(self):
        divisor = 114 if (self.audctl & 0x40) else 28
        self.timer_period = divisor * (self.audf1 + 1)

    def load_xex(self, xex_data: bytes) -> Optional[int]:
        from .xex_loader import parse_xex, load_into_memory
        xex = parse_xex(xex_data)
        return load_into_memory(self.memory, xex)

    def run_analysis(self, xex_path: str, max_frames: int = 20000,
                     space_delay_frames: int = 5,
                     progress_cb: Optional[Callable] = None
                     ) -> List[TickMeasurement]:
        """Run the .xex player and collect IRQ timing measurements."""

        with open(xex_path, 'rb') as f:
            xex_data = f.read()

        run_addr = self.load_xex(xex_data)
        if run_addr is None:
            raise ValueError("XEX has no RUN address")

        # Init CPU
        self.cpu.pc = run_addr
        self.cpu.sp = 0xFF
        self.cpu.a = 0
        self.cpu.x = 0
        self.cpu.y = 0
        self.cpu.p = MPU.BREAK | MPU.UNUSED | MPU.INTERRUPT
        self.cpu.processorCycles = 0

        # Reset state
        self._key_pressed = False
        self._key_code = 0xFF
        self.frame_cycle = 0
        self.frame_count = 0
        self.ticks = []
        self._in_irq = False
        self.timer_counter = 0
        self.timer_period = 0
        self.timer_irq_enabled = False

        was_playing = False
        song_started = False
        prev_songline = -1
        max_songline_seen = -1

        logger.info(f"Analysis: RUN=${run_addr:04X}, max_frames={max_frames}")

        for frame in range(max_frames):
            self.frame_count = frame

            # Keyboard: press SPACE, then release
            if frame == space_delay_frames:
                self._key_pressed = True
                self._key_code = 0x21  # SPACE
            elif frame == space_delay_frames + 4:
                self._key_pressed = False
                self._key_code = 0xFF

            self.frame_cycle = 0
            self._tick_in_frame = 0

            safety = 0
            while self.frame_cycle < self.frame_cycles:
                # Step one instruction
                before = self.cpu.processorCycles
                self.cpu.step()
                elapsed = self.cpu.processorCycles - before
                self.frame_cycle += elapsed

                # Timer countdown
                if self.timer_period > 0 and self.timer_irq_enabled:
                    self.timer_counter -= elapsed
                    while self.timer_counter <= 0:
                        self.timer_counter += self.timer_period
                        # Try to fire IRQ
                        self._try_fire_irq()

                safety += 1
                if safety > 500000:
                    logger.warning(f"Frame {frame}: safety limit")
                    break

            # Check song state
            playing = self.memory[ZP_SEQ_PLAYING]
            if playing != 0 and not song_started:
                song_started = True
                logger.info(f"Song started at frame {frame}")
            if song_started and playing == 0:
                logger.info(f"Song ended at frame {frame}")
                break

            # Detect songline wrap (song played through once)
            if song_started:
                cur_songline = self.memory[ZP_SEQ_SONGLINE]
                if cur_songline > max_songline_seen:
                    max_songline_seen = cur_songline
                elif (prev_songline > 0 and cur_songline == 0
                      and max_songline_seen > 0):
                    logger.info(f"Song wrapped at frame {frame} "
                                f"(max songline={max_songline_seen})")
                    break
                prev_songline = cur_songline

            if progress_cb and frame % 100 == 0:
                sl = self.memory[ZP_SEQ_SONGLINE]
                rw = self.memory[ZP_SEQ_ROW]
                progress_cb(frame, max_frames, sl, rw)

        logger.info(f"Done: {len(self.ticks)} ticks across "
                    f"{self.frame_count + 1} frames, "
                    f"timer_period={self.timer_period}")
        return self.ticks

    def _try_fire_irq(self):
        """Attempt to fire timer IRQ and measure handler."""
        # If I flag set, IRQ is pending but can't fire yet
        if self.cpu.p & MPU.INTERRUPT:
            return

        self._in_irq = True

        # Snapshot song position before handler runs
        songline = self.memory[ZP_SEQ_SONGLINE]
        row = self.memory[ZP_SEQ_ROW]

        # Fire IRQ — py65 pushes PC+P, sets I, loads $FFFE vector
        entry_cycles = self.cpu.processorCycles
        old_pc = self.cpu.pc
        self.cpu.irq()

        if self.cpu.pc == old_pc:
            # irq() did nothing (shouldn't happen since we checked I flag)
            self._in_irq = False
            return

        # Execute handler until RTI (opcode $40)
        for _ in range(5000):
            opcode = self.memory[self.cpu.pc]
            self.cpu.step()
            if opcode == 0x40:  # RTI
                break

        handler_cost = self.cpu.processorCycles - entry_cycles
        self._in_irq = False

        # Record tick
        tick = TickMeasurement(
            frame=self.frame_count,
            tick_in_frame=self._tick_in_frame,
            songline=songline,
            row=row,
            handler_cycles=handler_cost,
            timer_period=self.timer_period,
        )
        self.ticks.append(tick)
        self._tick_in_frame += 1

        # Account for handler time in frame and timer
        self.frame_cycle += handler_cost
        self.timer_counter -= handler_cost
