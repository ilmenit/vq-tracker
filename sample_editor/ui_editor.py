"""POKEY VQ Tracker  - Sample Editor UI (v2)

Full-featured non-destructive sample editor with:
- Dual-trace waveform (ghost=input, bright=output of selected effect)
- Click-to-set playback markers (left=start, right=end)
- Animated playback cursor line
- Piano key preview (Z-M / Q-P rows)
- Visual trim via waveform markers
- Clean effects chain list with aligned controls
- Comprehensive tooltips and empty-state guide
"""
import logging
import time
import threading
import numpy as np

try:
    import dearpygui.dearpygui as dpg
except ImportError:
    dpg = None

try:
    import sounddevice as sd
    _has_sd = True
except (ImportError, OSError):
    _has_sd = False

from sample_editor.commands import (
    SampleCommand, COMMAND_DEFAULTS, COMMAND_LABELS, COMMAND_TOOLBAR,
    COMMAND_APPLY, TOOLBAR_ORDER, get_summary,
)
from sample_editor.pipeline import run_pipeline_at

logger = logging.getLogger("tracker.sample_editor")

TAG = "sample_editor_win"
_instance = None  # singleton

# Effect toolbar groups (label, [keys])
_TOOLBAR_GROUPS = [
    ("Edit",       ['trim', 'reverse']),
    ("Amplitude",  ['gain', 'normalize', 'adsr']),
    ("Modulation", ['tremolo', 'vibrato', 'pitch_env']),
    ("Effects",    ['overdrive', 'echo', 'octave']),
]

# Tooltip descriptions per effect
_EFFECT_TIPS = {
    'trim':      "Crop the sample to a time range.\n"
                 "Set points by clicking the waveform when selected.",
    'reverse':   "Reverse the sample end-to-start.",
    'gain':      "Boost or attenuate volume in decibels.",
    'normalize': "Scale the sample so the peak reaches a target level.",
    'adsr':      "Attack / Decay / Sustain / Release amplitude envelope.",
    'tremolo':   "Amplitude modulation (volume wobble).",
    'vibrato':   "Pitch modulation (pitch wobble).",
    'pitch_env': "Linear pitch sweep from start to end semitones.",
    'overdrive': "Soft-clip distortion via tanh waveshaping.",
    'echo':      "Feed-forward delay with adjustable repeats.",
    'octave':    "Transpose by whole octaves via resampling.",
}

# Parameter panel definitions per effect type
# (param_key, label, min, max, default, format, is_int, tooltip)
PARAM_DEFS = {
    'trim': [
        ('start_ms', 'Start (ms)', 0.0, 10000.0, 0.0, '%.1f', False,
         "Crop start point. Left-click waveform to set visually."),
        ('end_ms', 'End (ms)', 0.0, 10000.0, 0.0, '%.1f', False,
         "Crop end point (0 = end of sample). Right-click waveform to set."),
    ],
    'reverse': [],
    'gain': [
        ('db', 'Gain (dB)', -24.0, 24.0, 0.0, '%.1f', False,
         "Volume change in decibels. +6 dB ~ double volume."),
    ],
    'normalize': [
        ('peak', 'Peak Level', 0.1, 1.0, 0.95, '%.2f', False,
         "Target peak amplitude (0.95 leaves headroom)."),
    ],
    'adsr': [
        ('attack_ms', 'Attack', 0.0, 2000.0, 10.0, '%.0f', False,
         "Fade-in time in milliseconds."),
        ('decay_ms', 'Decay', 0.0, 2000.0, 50.0, '%.0f', False,
         "Time to fall from peak to sustain level."),
        ('sustain', 'Sustain', 0.0, 1.0, 1.0, '%.2f', False,
         "Sustain amplitude level (0-1)."),
        ('release_ms', 'Release', 0.0, 5000.0, 100.0, '%.0f', False,
         "Fade-out time at end of sample."),
    ],
    'tremolo': [
        ('rate_hz', 'Rate (Hz)', 0.5, 30.0, 6.0, '%.1f', False,
         "LFO speed in cycles per second."),
        ('depth', 'Depth', 0.0, 1.0, 0.4, '%.2f', False,
         "Modulation depth (0 = none, 1 = full)."),
    ],
    'vibrato': [
        ('rate_hz', 'Rate (Hz)', 0.5, 15.0, 5.0, '%.1f', False,
         "LFO speed in cycles per second."),
        ('depth_cents', 'Depth (cents)', 1.0, 100.0, 20.0, '%.0f', False,
         "Pitch deviation in cents (100 = 1 semitone)."),
    ],
    'pitch_env': [
        ('start_semi', 'Start', -24.0, 24.0, 0.0, '%.1f', False,
         "Starting pitch offset in semitones."),
        ('end_semi', 'End', -24.0, 24.0, 0.0, '%.1f', False,
         "Ending pitch offset in semitones."),
    ],
    'overdrive': [
        ('drive', 'Drive', 1.0, 20.0, 4.0, '%.1f', False,
         "Distortion amount (higher = more clipping)."),
    ],
    'echo': [
        ('delay_ms', 'Delay (ms)', 10.0, 1000.0, 120.0, '%.0f', False,
         "Time between echoes in milliseconds."),
        ('decay', 'Decay', 0.0, 0.9, 0.5, '%.2f', False,
         "Volume multiplier for each repeat."),
        ('count', 'Repeats', 1.0, 10.0, 3.0, '%.0f', True,
         "Number of echo repeats."),
    ],
    'octave': [
        ('octaves', 'Octaves', -3.0, 3.0, -1.0, '%.0f', True,
         "Transpose by whole octaves (-1 = down one octave)."),
    ],
}

# Colours
_COL_MARKER_S = (80, 200, 120, 180)   # green start marker
_COL_MARKER_E = (240, 100, 100, 180)  # red end marker
_COL_CURSOR   = (255, 220, 80, 200)   # yellow playback cursor
_COL_DIM      = (100, 100, 140, 80)   # ghost trace
_COL_BOLD     = (120, 220, 255, 255)  # bright trace
_COL_SEL      = (50, 70, 110)         # selected row bg
_COL_HEADER   = (180, 200, 220)       # section headers
_COL_HINT     = (130, 135, 150)       # hint text


class SampleEditor:
    """Sample editor window controller.

    IMPORTANT: Never cache Instrument references across frames.
    The undo system replaces song.instruments with new objects.
    Always use _get_inst() to get the current live reference.
    """

    def __init__(self):
        self.inst_idx = -1
        self.selected = -1          # selected chain index (-1 = End)
        self._undo_saved = False
        self._octave = 1            # editor-local octave for piano preview
        # Markers (seconds, on the currently displayed waveform timescale)
        self._marker_start = 0.0
        self._marker_end = 0.0      # 0 = not set
        self._bold_duration = 0.0
        self._dim_duration = 0.0    # input duration (for trim slider max)
        # Playback cursor
        self._playing = False
        self._play_start_time = 0.0
        self._play_duration = 0.0
        self._play_offset = 0.0     # start offset for range play
        self._cursor_thread = None
        self._play_gen = 0            # generation counter for cursor thread
        self._themes_created = False

    # -----------------------------------------------------------------
    # Instrument lookup (never stale)
    # -----------------------------------------------------------------

    def _get_inst(self):
        from state import state
        if 0 <= self.inst_idx < len(state.song.instruments):
            return state.song.instruments[self.inst_idx]
        return None

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def open(self, inst_idx):
        self.inst_idx = inst_idx
        self.selected = -1
        self._undo_saved = False
        self._marker_start = 0.0
        self._marker_end = 0.0

        if dpg.does_item_exist(TAG):
            dpg.configure_item(TAG, show=True)
            dpg.focus_item(TAG)
            self._rebuild()
            return
        self._ensure_themes()
        self._create_window()

    def update_instrument(self, inst_idx):
        self.inst_idx = inst_idx
        self.selected = -1
        self._undo_saved = False
        self._marker_start = 0.0
        self._marker_end = 0.0
        if dpg.does_item_exist(TAG):
            self._rebuild()

    def refresh(self):
        inst = self._get_inst()
        if inst is None and self.inst_idx >= 0:
            self.close()
            return
        self._undo_saved = False
        if self.selected >= 0 and inst:
            if self.selected >= len(inst.effects):
                self.selected = -1
        if dpg.does_item_exist(TAG):
            self._rebuild()

    def close(self):
        self._stop_playback()
        if dpg.does_item_exist(f"{TAG}_plot_handlers"):
            dpg.delete_item(f"{TAG}_plot_handlers")
        if dpg.does_item_exist(TAG):
            dpg.delete_item(TAG)

    def is_open(self) -> bool:
        if dpg is None:
            return False
        return (dpg.does_item_exist(TAG) and
                dpg.is_item_shown(TAG))

    # -----------------------------------------------------------------
    # Themes (created once, persist across open/close)
    # -----------------------------------------------------------------

    def _ensure_themes(self):
        if self._themes_created:
            return
        self._themes_created = True

        with dpg.theme(tag=f"{TAG}_th_dim"):
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, _COL_DIM)

        with dpg.theme(tag=f"{TAG}_th_bold"):
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, _COL_BOLD)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.5)

        with dpg.theme(tag=f"{TAG}_th_ms"):
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, _COL_MARKER_S)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.5)

        with dpg.theme(tag=f"{TAG}_th_me"):
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, _COL_MARKER_E)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.5)

        with dpg.theme(tag=f"{TAG}_th_cur"):
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, _COL_CURSOR)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 2.0)

        with dpg.theme(tag=f"{TAG}_th_sel"):
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, _COL_SEL)

        with dpg.theme(tag=f"{TAG}_th_btn"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (50, 55, 70))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,
                                    (70, 80, 100))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,
                                    (90, 100, 130))
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 4)

    # -----------------------------------------------------------------
    # Window creation
    # -----------------------------------------------------------------

    def _create_window(self):
        title = self._window_title()
        with dpg.window(tag=TAG, label=title, width=740, height=680,
                        modal=True, no_collapse=True,
                        on_close=self._on_close, no_scrollbar=True):

            # -- Waveform ------------------------------------------
            with dpg.plot(tag=f"{TAG}_plot", height=190, width=-1,
                          no_box_select=True, no_menus=True):
                dpg.add_plot_axis(dpg.mvXAxis, tag=f"{TAG}_xaxis",
                                  no_gridlines=True)
                dpg.add_plot_axis(dpg.mvYAxis, tag=f"{TAG}_yaxis",
                                  no_gridlines=True, no_tick_labels=True,
                                  no_tick_marks=True)
                dpg.set_axis_limits(f"{TAG}_yaxis", -1.05, 1.05)
                for s in ("_dim", "_bold", "_ms", "_me", "_cur"):
                    dpg.add_line_series([], [], tag=f"{TAG}{s}",
                                        parent=f"{TAG}_yaxis")

            # Plot click handlers (separate for left and right button)
            with dpg.item_handler_registry(tag=f"{TAG}_plot_handlers"):
                dpg.add_item_clicked_handler(
                    button=0, callback=self._on_plot_left_click)
                dpg.add_item_clicked_handler(
                    button=1, callback=self._on_plot_right_click)
            dpg.bind_item_handler_registry(f"{TAG}_plot",
                                           f"{TAG}_plot_handlers")

            # -- Playback Row --------------------------------------
            with dpg.group(horizontal=True):
                b = dpg.add_button(label="Play", width=65,
                                   callback=self._on_play)
                with dpg.tooltip(b):
                    dpg.add_text("Play processed sample (Space)")

                b = dpg.add_button(label="Range", width=65,
                                   callback=self._on_play_range)
                with dpg.tooltip(b):
                    dpg.add_text("Play between markers")
                    dpg.add_text("Left-click waveform -> start",
                                 color=_COL_MARKER_S[:3])
                    dpg.add_text("Right-click waveform -> end",
                                 color=_COL_MARKER_E[:3])

                b = dpg.add_button(label="Original", width=75,
                                   callback=self._on_play_original)
                with dpg.tooltip(b):
                    dpg.add_text("Play unprocessed original sample")

                b = dpg.add_button(label="Stop", width=55,
                                   callback=self._stop_playback)
                with dpg.tooltip(b):
                    dpg.add_text("Stop playback")

                dpg.add_spacer(width=12)
                dpg.add_text(tag=f"{TAG}_duration", default_value="0.00s",
                             color=(180, 180, 180))
                dpg.add_spacer(width=12)

                dpg.add_text("Octave:", color=_COL_HINT)
                c = dpg.add_combo(tag=f"{TAG}_oct_combo",
                                  items=["1", "2", "3"],
                                  default_value="1", width=40,
                                  callback=self._on_octave_change)
                with dpg.tooltip(c):
                    dpg.add_text("Octave for piano key preview")
                    dpg.add_text("Keys: Z S X D C V G B H N J M")
                    dpg.add_text("       Q 2 W 3 E R 5 T 6 Y 7 U")
                    dpg.add_text("Numpad +/- = change octave")

            dpg.add_spacer(height=4)

            # -- Add Effect Toolbar --------------------------------
            dpg.add_text("ADD EFFECT", color=_COL_HEADER)
            with dpg.group(horizontal=True, tag=f"{TAG}_toolbar"):
                for _glabel, keys in _TOOLBAR_GROUPS:
                    for key in keys:
                        label = COMMAND_TOOLBAR.get(key, key)
                        btn = dpg.add_button(label=label, width=50,
                                             callback=self._make_add_cb(key))
                        dpg.bind_item_theme(btn, f"{TAG}_th_btn")
                        with dpg.tooltip(btn):
                            dpg.add_text(
                                COMMAND_LABELS.get(key, key),
                                color=(255, 255, 150))
                            dpg.add_text(_EFFECT_TIPS.get(key, ""))
                    dpg.add_spacer(width=4)

            dpg.add_spacer(height=4)

            # -- Effects Chain -------------------------------------
            dpg.add_text("EFFECTS CHAIN", color=_COL_HEADER)
            with dpg.child_window(tag=f"{TAG}_chain", height=150,
                                  border=True):
                pass  # rebuilt dynamically

            dpg.add_spacer(height=4)

            # -- Parameters ----------------------------------------
            dpg.add_text("PARAMETERS", color=_COL_HEADER)
            with dpg.child_window(tag=f"{TAG}_params", height=120,
                                  border=True):
                pass  # rebuilt dynamically

            dpg.add_spacer(height=5)

            # -- Bottom Bar ----------------------------------------
            with dpg.group(horizontal=True):
                b = dpg.add_button(label="Reset All", width=80,
                                   callback=self._on_reset_all)
                with dpg.tooltip(b):
                    dpg.add_text("Remove all effects from chain")
                dpg.add_spacer(width=490)
                b = dpg.add_button(label="Close", width=70,
                                   callback=lambda *a: self.close())
                with dpg.tooltip(b):
                    dpg.add_text("Close editor (Escape)")

        # Apply themes to plot series
        dpg.bind_item_theme(f"{TAG}_dim", f"{TAG}_th_dim")
        dpg.bind_item_theme(f"{TAG}_bold", f"{TAG}_th_bold")
        dpg.bind_item_theme(f"{TAG}_ms", f"{TAG}_th_ms")
        dpg.bind_item_theme(f"{TAG}_me", f"{TAG}_th_me")
        dpg.bind_item_theme(f"{TAG}_cur", f"{TAG}_th_cur")

        self._rebuild()

    def _window_title(self):
        inst = self._get_inst()
        if inst:
            return (f"Sample Editor  - {inst.name} "
                    f"(Inst {self.inst_idx:02d})")
        return "Sample Editor"

    def _on_close(self, *args):
        self._stop_playback()

    # -----------------------------------------------------------------
    # Plot mouse interaction
    # -----------------------------------------------------------------

    def _on_plot_left_click(self, sender, app_data):
        """Left click on waveform -> set start marker."""
        try:
            x, _y = dpg.get_plot_mouse_pos()
        except Exception:
            return
        x = max(0.0, x)
        self._marker_start = x
        if self._marker_end > 0 and x >= self._marker_end:
            self._marker_end = 0.0
        self._sync_trim_from_markers()
        self._update_markers()

    def _on_plot_right_click(self, sender, app_data):
        """Right click on waveform -> set end marker."""
        try:
            x, _y = dpg.get_plot_mouse_pos()
        except Exception:
            return
        x = max(0.0, x)
        if x <= self._marker_start:
            x = self._marker_start + 0.001
        self._marker_end = x
        self._sync_trim_from_markers()
        self._update_markers()

    def _sync_trim_from_markers(self):
        """If the selected effect is trim, update params from markers."""
        inst = self._get_inst()
        if not inst:
            return
        idx = self.selected
        if idx < 0 or idx >= len(inst.effects):
            return
        cmd = inst.effects[idx]
        if cmd.type != 'trim':
            return

        if not self._undo_saved:
            self._save_undo("Adjust Trim")
            self._undo_saved = True

        cmd.params['start_ms'] = self._marker_start * 1000.0
        cmd.params['end_ms'] = (self._marker_end * 1000.0
                                if self._marker_end > 0 else 0.0)
        inst.invalidate_cache()
        self._mark_modified()
        self._update_waveform()
        self._rebuild_params()
        self._rebuild_chain()

    # -----------------------------------------------------------------
    # Rebuild / Refresh
    # -----------------------------------------------------------------

    def _rebuild(self):
        if not dpg.does_item_exist(TAG):
            return
        dpg.configure_item(TAG, label=self._window_title())
        self._update_waveform()     # first: computes durations
        self._rebuild_chain()
        self._rebuild_params()      # uses durations for trim slider max

    def _rebuild_chain(self):
        parent = f"{TAG}_chain"
        if not dpg.does_item_exist(parent):
            return
        for child in dpg.get_item_children(parent, 1) or []:
            dpg.delete_item(child)

        inst = self._get_inst()
        if not inst:
            return
        effects = inst.effects

        # Empty state: show welcome guide
        if not effects:
            self._show_welcome(parent)
            return

        # Table layout ensures buttons are right-aligned
        with dpg.table(parent=parent, header_row=False,
                       borders_innerH=False, borders_outerH=False,
                       borders_innerV=False, borders_outerV=False,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(init_width_or_weight=76,
                                 width_fixed=True)

            # Effect rows
            for i, cmd in enumerate(effects):
                is_sel = (i == self.selected)
                label = COMMAND_LABELS.get(cmd.type, cmd.type)
                summary = get_summary(cmd)

                with dpg.table_row() as row:
                    if is_sel:
                        dpg.bind_item_theme(row, f"{TAG}_th_sel")

                    # Left: checkbox + name + summary
                    with dpg.group(horizontal=True):
                        cb = dpg.add_checkbox(
                            default_value=cmd.enabled,
                            callback=self._make_toggle_cb(i))
                        with dpg.tooltip(cb):
                            dpg.add_text(
                                "Disable" if cmd.enabled
                                else "Enable")

                        sel_icon = ">" if is_sel else " "
                        dis = "" if cmd.enabled else " (off)"
                        sel_btn = dpg.add_button(
                            label=f"{sel_icon} {i+1}. {label}{dis}",
                            width=165,
                            callback=self._make_select_cb(i))
                        with dpg.tooltip(sel_btn):
                            dpg.add_text(
                                "Click to select and edit parameters")

                        dpg.add_text(summary,
                                     color=(180, 180, 140))

                    # Right: move + remove buttons
                    with dpg.group(horizontal=True):
                        if i > 0:
                            b = dpg.add_button(
                                label="^", width=22,
                                callback=self._make_move_cb(i, -1))
                            with dpg.tooltip(b):
                                dpg.add_text("Move up")
                        else:
                            dpg.add_spacer(width=22)

                        if i < len(effects) - 1:
                            b = dpg.add_button(
                                label="v", width=22,
                                callback=self._make_move_cb(i, +1))
                            with dpg.tooltip(b):
                                dpg.add_text("Move down")
                        else:
                            dpg.add_spacer(width=22)

                        b = dpg.add_button(
                            label="X", width=22,
                            callback=self._make_remove_cb(i))
                        with dpg.tooltip(b):
                            dpg.add_text("Remove")

            # Output row
            is_end = (self.selected < 0
                      or self.selected >= len(effects))
            with dpg.table_row() as end_row:
                if is_end:
                    dpg.bind_item_theme(end_row, f"{TAG}_th_sel")
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=26)
                    sel_icon = ">" if is_end else " "
                    b = dpg.add_button(
                        label=f"{sel_icon} Output", width=165,
                        callback=self._make_select_cb(-1))
                    with dpg.tooltip(b):
                        dpg.add_text(
                            "View final output after all effects")
                    n_active = sum(1 for c in effects if c.enabled)
                    dpg.add_text(f"({n_active} active)",
                                 color=_COL_HINT)
                dpg.add_spacer()  # empty right column

    def _show_welcome(self, parent):
        """Show help text when effects chain is empty."""
        with dpg.group(parent=parent):
            dpg.add_spacer(height=8)
            dpg.add_text("  *  Non-Destructive Effects Editor",
                         color=(140, 200, 255))
            dpg.add_spacer(height=6)
            dpg.add_text("  1. Click an effect button above to add it",
                         color=_COL_HINT)
            dpg.add_text("  2. Adjust parameters in the panel below",
                         color=_COL_HINT)
            dpg.add_text("  3. Reorder, disable, or remove effects "
                         "in the chain", color=_COL_HINT)
            dpg.add_text("  4. Press piano keys (Z-M, Q-P)"
                         " to preview your sound", color=_COL_HINT)
            dpg.add_spacer(height=6)
            dpg.add_text("  Dim trace = input before current effect",
                         color=_COL_DIM[:3])
            dpg.add_text("  Bright trace = output of current effect",
                         color=_COL_BOLD[:3])

    def _rebuild_params(self):
        parent = f"{TAG}_params"
        if not dpg.does_item_exist(parent):
            return
        for child in dpg.get_item_children(parent, 1) or []:
            dpg.delete_item(child)

        inst = self._get_inst()
        if not inst:
            dpg.add_text("No instrument", parent=parent, color=_COL_HINT)
            return

        effects = inst.effects
        idx = self.selected

        if idx < 0 or idx >= len(effects):
            if effects:
                n = sum(1 for c in effects if c.enabled)
                dpg.add_text(
                    f"  Viewing final output   -  "
                    f"{n} effect(s) active",
                    parent=parent, color=_COL_HINT)
            else:
                dpg.add_text("  Add an effect to get started.",
                             parent=parent, color=_COL_HINT)
            return

        cmd = effects[idx]
        label = COMMAND_LABELS.get(cmd.type, cmd.type)

        # Header
        with dpg.group(horizontal=True, parent=parent):
            dpg.add_text(f"  {label}", color=(255, 255, 150))
            if not cmd.enabled:
                dpg.add_text("  (disabled)", color=(200, 100, 100))

        # Special hint for trim
        if cmd.type == 'trim':
            dpg.add_text(
                "  Tip: Left-click waveform = start, "
                "Right-click = end",
                parent=parent, color=(120, 180, 120))

        params_def = PARAM_DEFS.get(cmd.type, [])

        if not params_def:
            dpg.add_text("  (no adjustable parameters)",
                         parent=parent, color=_COL_HINT)
        else:
            # For trim: compute max from input audio duration
            trim_max_ms = self._dim_duration * 1000.0 if cmd.type == 'trim' else 0

            for pdef in params_def:
                pkey = pdef[0]
                plabel = pdef[1]
                pmin, pmax, pdefault = pdef[2], pdef[3], pdef[4]
                pfmt = pdef[5]
                is_int = pdef[6]
                tip = pdef[7] if len(pdef) > 7 else ""

                # Override max for trim sliders
                if cmd.type == 'trim' and trim_max_ms > 0:
                    pmax = trim_max_ms

                val = cmd.params.get(pkey, pdefault)
                if is_int:
                    val = int(val)
                with dpg.group(horizontal=True, parent=parent):
                    dpg.add_text(f"  {plabel}:",
                                 color=(180, 180, 180))
                    fn = (dpg.add_slider_int if is_int
                          else dpg.add_slider_float)
                    kw = dict(
                        default_value=int(val) if is_int else float(val),
                        min_value=int(pmin) if is_int else pmin,
                        max_value=int(pmax) if is_int else pmax,
                        width=250,
                        callback=self._make_param_cb(idx, pkey, is_int),
                    )
                    if not is_int:
                        kw['format'] = pfmt
                    s = fn(**kw)
                    if tip:
                        with dpg.tooltip(s):
                            dpg.add_text(tip)

        with dpg.group(horizontal=True, parent=parent):
            dpg.add_spacer(width=500)
            b = dpg.add_button(label="Reset Defaults", width=100,
                               callback=self._make_reset_cb(idx))
            with dpg.tooltip(b):
                dpg.add_text("Reset parameters to defaults")

    # -----------------------------------------------------------------
    # Waveform
    # -----------------------------------------------------------------

    def _update_waveform(self):
        if not dpg.does_item_exist(f"{TAG}_plot"):
            return

        inst = self._get_inst()
        if not inst or not inst.is_loaded():
            for s in ("_dim", "_bold", "_ms", "_me", "_cur"):
                dpg.set_value(f"{TAG}{s}", [[], []])
            dpg.set_value(f"{TAG}_duration", "No sample")
            return

        effects = inst.effects
        idx = (self.selected if 0 <= self.selected < len(effects)
               else len(effects))

        dim_audio, bold_audio = run_pipeline_at(
            inst.sample_data, inst.sample_rate, effects, idx)

        self._dim_duration = (len(dim_audio) / inst.sample_rate
                              if len(dim_audio) > 0 else 0)

        dim_x, dim_y = self._downsample(dim_audio, inst.sample_rate)
        bold_x, bold_y = self._downsample(bold_audio, inst.sample_rate)

        # For trim: offset bold trace so it sits between the markers
        # instead of being left-aligned at x=0
        is_trim = (0 <= self.selected < len(effects)
                   and effects[self.selected].type == 'trim')
        if is_trim:
            cmd = effects[self.selected]
            trim_start_s = cmd.params.get('start_ms', 0) / 1000.0
            if trim_start_s > 0 and bold_x:
                bold_x = [x + trim_start_s for x in bold_x]

        dpg.set_value(f"{TAG}_dim", [dim_x, dim_y])
        dpg.set_value(f"{TAG}_bold", [bold_x, bold_y])

        dur = (len(bold_audio) / inst.sample_rate
               if len(bold_audio) > 0 else 0)
        self._bold_duration = dur
        dpg.set_value(f"{TAG}_duration", f"{dur:.3f}s")

        # For trim: show the input waveform timescale and sync markers
        display_dur = dur
        if is_trim:
            dim_dur = (len(dim_audio) / inst.sample_rate
                       if len(dim_audio) > 0 else 0)
            display_dur = dim_dur
            self._marker_start = cmd.params.get('start_ms', 0) / 1000.0
            end_ms = cmd.params.get('end_ms', 0)
            self._marker_end = (end_ms / 1000.0 if end_ms > 0
                                else dim_dur)

        dpg.set_axis_limits(f"{TAG}_xaxis", 0, max(display_dur, 0.01))
        self._update_markers()

    def _update_markers(self):
        if not dpg.does_item_exist(f"{TAG}_ms"):
            return
        if self._marker_start > 0:
            x = self._marker_start
            dpg.set_value(f"{TAG}_ms", [[x, x], [-1.05, 1.05]])
        else:
            dpg.set_value(f"{TAG}_ms", [[], []])
        if self._marker_end > 0:
            x = self._marker_end
            dpg.set_value(f"{TAG}_me", [[x, x], [-1.05, 1.05]])
        else:
            dpg.set_value(f"{TAG}_me", [[], []])

    @staticmethod
    def _downsample(audio, sr, max_points=2000):
        n = len(audio)
        if n == 0:
            return [], []
        step = max(1, n // max_points)
        indices = np.arange(0, n, step)
        return (indices / sr).tolist(), audio[indices].tolist()

    # -----------------------------------------------------------------
    # Callbacks  - effect mutations
    # -----------------------------------------------------------------

    def _save_undo(self, label="Edit Effect"):
        from ops.base import save_undo
        save_undo(label)

    def _mark_modified(self):
        from state import state
        state.song.modified = True

    def _after_change(self):
        inst = self._get_inst()
        if inst:
            inst.invalidate_cache()
        self._mark_modified()
        self._undo_saved = False
        # Clear markers — _update_waveform will restore them if trim is selected
        self._marker_start = 0.0
        self._marker_end = 0.0
        self._rebuild()

    def _make_add_cb(self, effect_type):
        def cb(*args):
            inst = self._get_inst()
            if not inst:
                return
            self._save_undo(
                f"Add {COMMAND_LABELS.get(effect_type, effect_type)}")
            defaults = dict(COMMAND_DEFAULTS.get(effect_type, {}))
            cmd = SampleCommand(type=effect_type, params=defaults)
            effects = inst.effects
            if 0 <= self.selected < len(effects):
                effects.insert(self.selected + 1, cmd)
                self.selected += 1
            else:
                effects.append(cmd)
                self.selected = len(effects) - 1
            self._after_change()
        return cb

    def _make_select_cb(self, index):
        def cb(*args):
            old_sel = self.selected
            self.selected = index
            self._undo_saved = False
            # Clear markers when leaving trim (they were auto-synced)
            inst = self._get_inst()
            if inst:
                effects = inst.effects
                was_trim = (0 <= old_sel < len(effects)
                            and effects[old_sel].type == 'trim')
                is_trim = (0 <= index < len(effects)
                           and effects[index].type == 'trim')
                if was_trim and not is_trim:
                    self._marker_start = 0.0
                    self._marker_end = 0.0
            self._rebuild()
        return cb

    def _make_toggle_cb(self, index):
        def cb(sender, value, *args):
            inst = self._get_inst()
            if not inst or index >= len(inst.effects):
                return
            self._save_undo("Toggle Effect")
            inst.effects[index].enabled = value
            self._after_change()
        return cb

    def _make_move_cb(self, index, direction):
        def cb(*args):
            inst = self._get_inst()
            if not inst:
                return
            effects = inst.effects
            new_idx = index + direction
            if 0 <= new_idx < len(effects):
                self._save_undo("Reorder Effect")
                effects[index], effects[new_idx] = (
                    effects[new_idx], effects[index])
                self.selected = new_idx
                self._after_change()
        return cb

    def _make_remove_cb(self, index):
        def cb(*args):
            inst = self._get_inst()
            if not inst or index >= len(inst.effects):
                return
            self._save_undo("Remove Effect")
            inst.effects.pop(index)
            if self.selected >= len(inst.effects):
                self.selected = -1
            self._after_change()
        return cb

    def _make_param_cb(self, index, param_key, is_int):
        def cb(sender, value, *args):
            inst = self._get_inst()
            if not inst or index >= len(inst.effects):
                return
            if not self._undo_saved:
                self._save_undo("Change Parameter")
                self._undo_saved = True
            cmd = inst.effects[index]
            cmd.params[param_key] = (int(value) if is_int
                                     else float(value))
            inst.invalidate_cache()
            self._mark_modified()
            self._update_waveform()
            self._rebuild_chain()
        return cb

    def _make_reset_cb(self, index):
        def cb(*args):
            inst = self._get_inst()
            if not inst or index >= len(inst.effects):
                return
            cmd = inst.effects[index]
            self._save_undo(
                f"Reset {COMMAND_LABELS.get(cmd.type, cmd.type)}")
            cmd.params = dict(COMMAND_DEFAULTS.get(cmd.type, {}))
            self._after_change()
        return cb

    def _on_reset_all(self, *args):
        inst = self._get_inst()
        if not inst or not inst.effects:
            return
        self._save_undo("Reset All Effects")
        inst.effects.clear()
        self.selected = -1
        self._after_change()

    def _on_octave_change(self, sender, value, *args):
        try:
            self._octave = int(value)
        except (ValueError, TypeError):
            pass

    # -----------------------------------------------------------------
    # Playback
    # -----------------------------------------------------------------

    def _stop_playback(self, *args):
        self._playing = False
        self._play_gen += 1  # invalidate any running cursor thread
        if _has_sd:
            sd.stop()
        if dpg.does_item_exist(f"{TAG}_cur"):
            dpg.set_value(f"{TAG}_cur", [[], []])

    def _on_play(self, *args):
        inst = self._get_inst()
        if not inst or not inst.is_loaded():
            return
        effects = inst.effects
        idx = (self.selected if 0 <= self.selected < len(effects)
               else len(effects))
        _, audio = run_pipeline_at(
            inst.sample_data, inst.sample_rate, effects, idx)
        self._play_audio(audio, inst.sample_rate, 0.0)

    def _on_play_range(self, *args):
        inst = self._get_inst()
        if not inst or not inst.is_loaded():
            return
        # Always play from the full pipeline output (End position)
        # This ensures marker coordinates match the displayed waveform
        # EXCEPT when trim is selected — markers are in input coords,
        # so we play from the input (dim) waveform instead.
        effects = inst.effects
        sel = self.selected
        is_trim_sel = (0 <= sel < len(effects)
                       and effects[sel].type == 'trim')

        if is_trim_sel:
            # Markers are in input (dim) coords — play the input audio
            dim_audio, _ = run_pipeline_at(
                inst.sample_data, inst.sample_rate, effects, sel)
            audio = dim_audio
        else:
            idx = (sel if 0 <= sel < len(effects) else len(effects))
            _, audio = run_pipeline_at(
                inst.sample_data, inst.sample_rate, effects, idx)

        sr = inst.sample_rate
        s0 = int(self._marker_start * sr)
        s1 = (int(self._marker_end * sr) if self._marker_end > 0
              else len(audio))
        s0 = max(0, min(s0, len(audio)))
        s1 = max(s0, min(s1, len(audio)))
        if s1 <= s0:
            return
        self._play_audio(audio[s0:s1], sr, self._marker_start)

    def _on_play_original(self, *args):
        inst = self._get_inst()
        if not inst or not inst.is_loaded():
            return
        self._play_audio(inst.sample_data, inst.sample_rate, 0.0)

    def _play_audio(self, audio, sr, offset=0.0):
        if not _has_sd or len(audio) == 0:
            return
        # Stop any existing playback and cursor thread
        self._playing = False
        sd.stop()
        # Bump generation so old cursor thread exits
        self._play_gen += 1
        gen = self._play_gen
        # Start new playback
        self._playing = True
        self._play_start_time = time.time()
        self._play_duration = len(audio) / sr
        self._play_offset = offset
        sd.play(audio, sr)
        self._start_cursor_thread(gen)

    def play_note(self, semitone):
        """Play a note using the audio engine (piano key preview)."""
        inst = self._get_inst()
        if not inst or not inst.is_loaded():
            return
        from state import state
        from constants import MAX_VOLUME, MAX_NOTES
        note = (self._octave - 1) * 12 + semitone + 1
        if 1 <= note <= MAX_NOTES:
            state.audio.preview_note(0, note, inst, MAX_VOLUME)

    # -----------------------------------------------------------------
    # Playback cursor thread
    # -----------------------------------------------------------------

    def _start_cursor_thread(self, gen):
        # Always start a new thread — old one will exit via generation check
        self._cursor_thread = threading.Thread(
            target=self._cursor_loop, args=(gen,), daemon=True)
        self._cursor_thread.start()

    def _cursor_loop(self, gen):
        while self._playing and self._play_gen == gen:
            elapsed = time.time() - self._play_start_time
            if elapsed >= self._play_duration:
                self._playing = False
                break
            pos = self._play_offset + elapsed
            try:
                if dpg.does_item_exist(f"{TAG}_cur"):
                    dpg.set_value(f"{TAG}_cur",
                                  [[pos, pos], [-1.05, 1.05]])
            except Exception:
                break
            time.sleep(0.033)
        # Only clear cursor if we're still the active generation
        if self._play_gen == gen:
            try:
                if dpg.does_item_exist(f"{TAG}_cur"):
                    dpg.set_value(f"{TAG}_cur", [[], []])
            except Exception:
                pass


# =====================================================================
# Module-level API
# =====================================================================

def open_editor(inst_idx):
    global _instance
    if _instance is None:
        _instance = SampleEditor()
    _instance.open(inst_idx)


def update_editor_instrument(inst_idx):
    if _instance and _instance.is_open():
        _instance.update_instrument(inst_idx)


def refresh_editor():
    if _instance and _instance.is_open():
        _instance.refresh()


def close_editor():
    global _instance
    if _instance:
        _instance.close()


def is_editor_open():
    return _instance.is_open() if _instance else False


def handle_editor_key(key):
    """Handle keyboard input while editor is shown.

    Called from keyboard.py before the main key handler.
    Returns True if the key was consumed (blocks pass-through).
    """
    if _instance is None or not _instance.is_open():
        return False

    # Escape closes editor
    if key == dpg.mvKey_Escape:
        _instance.close()
        return True

    # Octave change via numpad +/-
    if key == dpg.mvKey_Add:
        _instance._octave = min(3, _instance._octave + 1)
        if dpg.does_item_exist(f"{TAG}_oct_combo"):
            dpg.set_value(f"{TAG}_oct_combo", str(_instance._octave))
        return True
    if key == dpg.mvKey_Subtract:
        _instance._octave = max(1, _instance._octave - 1)
        if dpg.does_item_exist(f"{TAG}_oct_combo"):
            dpg.set_value(f"{TAG}_oct_combo", str(_instance._octave))
        return True

    # Piano keys
    from keyboard import KEY_MAP
    from constants import NOTE_KEYS
    char = KEY_MAP.get(key)
    if char:
        semitone = NOTE_KEYS.get(char.lower())
        if semitone is not None:
            _instance.play_note(semitone)
            return True

    # Space = play processed
    if key == dpg.mvKey_Spacebar:
        _instance._on_play()
        return True

    return True  # consume all other keys (modal behaviour)
