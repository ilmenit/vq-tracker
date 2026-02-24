"""High-level cycle analyzer — runs analysis, aggregates per-row results.

Provides the API that the UI uses for row coloring after BUILD.
"""

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable

from .atari_system import (
    AtariSystem, TickMeasurement, RowResult,
    compute_dma_table, compute_dma_budgets,
)

logger = logging.getLogger(__name__)


@dataclass
class CycleAnalysisResult:
    """Complete analysis result for a song."""
    rows: Dict[Tuple[int, int], RowResult] = field(default_factory=dict)

    worst_dma: int = 0
    best_dma: int = 0
    timer_period: int = 0
    sample_rate: int = 0

    n_overrun_rows: int = 0
    n_tight_rows: int = 0
    overrun_locations: List[Tuple[int, int]] = field(default_factory=list)
    tight_locations: List[Tuple[int, int]] = field(default_factory=list)

    is_pal: bool = True
    analysis_time: float = 0.0
    n_ticks: int = 0

    def get_row_status(self, songline: int, row: int) -> Optional[str]:
        """Get status: 'ok', 'tight', 'overrun', or None if not analyzed."""
        key = (songline, row)
        if key not in self.rows:
            return None
        return self.rows[key].status(self.worst_dma, self.best_dma)

    def get_row_detail(self, songline: int, row: int) -> Optional[str]:
        """Get human-readable detail for status bar."""
        key = (songline, row)
        if key not in self.rows:
            return None
        r = self.rows[key]
        st = r.status(self.worst_dma, self.best_dma)
        margin_w = r.margin_worst(self.worst_dma)
        margin_b = r.margin_best(self.best_dma)
        budget_lo = self.timer_period - self.worst_dma
        budget_hi = self.timer_period - self.best_dma
        return (f"IRQ handler: {r.worst_handler_cycles} cyc | "
                f"Budget: {budget_lo}-{budget_hi} cyc | "
                f"Margin: {margin_w:+d} to {margin_b:+d} | "
                f"{st.upper()}")

    def summary(self) -> str:
        if not self.rows:
            return "Cycle analysis: no data (song may not have played)"
        total = len(self.rows)
        if self.n_overrun_rows == 0 and self.n_tight_rows == 0:
            return f"Cycle analysis: all {total} rows OK ({self.analysis_time:.1f}s)"
        parts = []
        if self.n_overrun_rows > 0:
            locs = ", ".join(f"S{sl}:R{rw}" for sl, rw
                             in self.overrun_locations[:6])
            if self.n_overrun_rows > 6:
                locs += f" +{self.n_overrun_rows - 6} more"
            parts.append(f"{self.n_overrun_rows} OVERRUN ({locs})")
        if self.n_tight_rows > 0:
            parts.append(f"{self.n_tight_rows} tight")
        return f"Cycle analysis: {'; '.join(parts)} ({self.analysis_time:.1f}s)"


class CycleAnalysisState:
    """Thread-safe state container for UI access."""

    def __init__(self):
        self.result: Optional[CycleAnalysisResult] = None
        self.ready = False
        self.running = False
        self.progress_text = ""
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def invalidate(self):
        """Clear results (called on any song edit)."""
        with self._lock:
            self.result = None
            self.ready = False
            self.error = None
            self.progress_text = ""

    def set_result(self, result: CycleAnalysisResult):
        with self._lock:
            self.result = result
            self.ready = True
            self.running = False

    def set_error(self, msg: str):
        with self._lock:
            self.error = msg
            self.running = False
            self.ready = False

    def get_row_status(self, songline: int, row: int) -> Optional[str]:
        """Thread-safe status query."""
        with self._lock:
            if not self.ready or self.result is None:
                return None
            return self.result.get_row_status(songline, row)

    def get_row_detail(self, songline: int, row: int) -> Optional[str]:
        """Thread-safe detail query."""
        with self._lock:
            if not self.ready or self.result is None:
                return None
            return self.result.get_row_detail(songline, row)


# Module-level singleton
analysis_state = CycleAnalysisState()


def run_cycle_analysis(xex_path: str, is_pal: bool = True,
                       progress_cb: Optional[Callable] = None
                       ) -> CycleAnalysisResult:
    """Run cycle analysis on a built .xex file.
    
    Returns CycleAnalysisResult with per-row status.
    """
    t0 = time.time()

    if not os.path.exists(xex_path):
        raise FileNotFoundError(f"XEX not found: {xex_path}")

    system = AtariSystem(is_pal=is_pal)
    ticks = system.run_analysis(
        xex_path,
        max_frames=12000,
        space_delay_frames=5,
        progress_cb=progress_cb,
    )

    if not ticks:
        result = CycleAnalysisResult(is_pal=is_pal)
        result.analysis_time = time.time() - t0
        return result

    # DMA budgets
    dma_table = compute_dma_table(system.memory, is_pal)
    timer_period = ticks[0].timer_period
    worst_dma, best_dma, avg_dma = compute_dma_budgets(
        dma_table, timer_period)

    # Sample rate
    clock = 1773447 if is_pal else 1789773
    sample_rate = int(clock / timer_period) if timer_period > 0 else 0

    # Aggregate per row
    row_ticks: Dict[Tuple[int, int], List[TickMeasurement]] = defaultdict(list)
    for tick in ticks:
        row_ticks[(tick.songline, tick.row)].append(tick)

    rows: Dict[Tuple[int, int], RowResult] = {}
    for key, tlist in row_ticks.items():
        songline, row = key
        rows[key] = RowResult(
            songline=songline,
            row=row,
            worst_handler_cycles=max(t.handler_cycles for t in tlist),
            n_ticks=len(tlist),
            timer_period=timer_period,
        )

    # Build result
    result = CycleAnalysisResult(
        rows=rows,
        worst_dma=worst_dma,
        best_dma=best_dma,
        timer_period=timer_period,
        sample_rate=sample_rate,
        is_pal=is_pal,
        n_ticks=len(ticks),
    )

    for key, r in rows.items():
        st = r.status(worst_dma, best_dma)
        if st == 'overrun':
            result.n_overrun_rows += 1
            result.overrun_locations.append(key)
        elif st == 'tight':
            result.n_tight_rows += 1
            result.tight_locations.append(key)

    result.overrun_locations.sort()
    result.tight_locations.sort()
    result.analysis_time = time.time() - t0

    logger.info(f"Cycle analysis: {len(rows)} rows, {len(ticks)} ticks, "
                f"{result.n_overrun_rows} overruns, {result.n_tight_rows} tight, "
                f"{result.analysis_time:.1f}s")

    return result


def start_analysis_async(xex_path: str, is_pal: bool = True):
    """Start cycle analysis in background thread.
    
    Results available via analysis_state.
    """
    analysis_state.invalidate()
    analysis_state.running = True
    analysis_state.progress_text = "Starting cycle analysis..."

    def _run():
        try:
            def progress(frame, total, sl, rw):
                analysis_state.progress_text = (
                    f"Analyzing... frame {frame}, songline {sl}")

            result = run_cycle_analysis(xex_path, is_pal, progress)
            analysis_state.set_result(result)
            analysis_state.progress_text = result.summary()

        except Exception as e:
            logger.error(f"Cycle analysis failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            analysis_state.set_error(str(e))
            analysis_state.progress_text = f"Analysis failed: {e}"

    thread = threading.Thread(target=_run, daemon=True, name="CycleAnalysis")
    thread.start()
