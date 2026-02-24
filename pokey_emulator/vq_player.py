"""
pokey_emulator/vq_player.py — VQ Sample Player Engine

Reimplements the Atari tracker's IRQ handler and song sequencer in Python,
driving the POKEY emulator with cycle-accurate register writes.

This replaces the need for a 6502 CPU emulator: we execute the same logic
as tracker_irq_speed.asm and process_row.asm, but in Python, producing
identical POKEY register write sequences.

Classes:
    ChannelState  — Per-channel playback state (mirrors trkN_* zero-page vars)
    VQPlayer      — Complete player: loads VQ data, runs frames, produces PCM

Functions:
    render_vq_wav — One-call offline rendering to WAV file
"""

import struct
import wave
import os
import json
import math
import numpy as np
from typing import List, Optional, Tuple, Dict

from pokey_emulator.pokey import (
    PokeyPair, NEVER_CYCLE,
    PAL_CLOCK, NTSC_CLOCK,
    PAL_CYCLES_PER_FRAME, NTSC_CYCLES_PER_FRAME,
    CYCLES_PER_SCANLINE,
)

# POKEY register offsets (relative to $D200)
AUDF1 = 0x00
AUDC1 = 0x01
AUDF2 = 0x02
AUDC2 = 0x03
AUDF3 = 0x04
AUDC3 = 0x05
AUDF4 = 0x06
AUDC4 = 0x07
AUDCTL = 0x08
STIMER = 0x09
IRQEN = 0x0E
SKCTL = 0x0F

# AUDC and AUDF registers indexed by channel number 0-3
AUDC_REGS = [AUDC1, AUDC2, AUDC3, AUDC4]
AUDF_REGS = [AUDF1, AUDF2, AUDF3, AUDF4]

# Silence: volume-only mode, volume 0
SILENCE = 0x10

# Song event constants
NOTE_OFF = 255
VOL_CHANGE_ASM = 61  # volume-only event marker in ASM export format


# ============================================================================
# Instrument Data
# ============================================================================

class InstrumentData:
    """Binary VQ/RAW data for one instrument, ready for playback.

    For VQ instruments:
        - stream_data contains the VQ index stream
        - start_offset / end_offset mark the range within stream_data
        - Codebook data is shared and stored in SongData

    For RAW instruments:
        - stream_data contains the raw sample bytes (AUDC values)
        - start_offset = 0, end_offset = len(stream_data)
    """

    __slots__ = ('index', 'is_vq', 'stream_data', 'start_offset', 'end_offset')

    def __init__(self, index: int, is_vq: bool,
                 stream_data: bytes, start_offset: int, end_offset: int):
        self.index = index
        self.is_vq = is_vq
        self.stream_data = stream_data
        self.start_offset = start_offset
        self.end_offset = end_offset


# ============================================================================
# Song Data
# ============================================================================

class SongData:
    """Complete song data for the player.

    Built from the tracker's Song model + VQ conversion results.
    """

    def __init__(self):
        self.instruments: List[InstrumentData] = []

        # VQ codebook: packed sample vectors.
        # Indexed by simple offset (NOT Atari addresses).
        self.codebook: bytes = b''

        # Codebook lookup tables: vector_index -> byte offset into codebook.
        # These are ALWAYS simple offsets (0, vector_size, 2*vector_size, ...),
        # NOT Atari memory addresses.
        self.cb_offset_lo: bytes = b''    # Low byte of codebook offset
        self.cb_offset_hi: bytes = b''    # High byte of codebook offset
        self.vector_size: int = 8

        # Song structure
        self.songlines: List[dict] = []   # [{speed, patterns: [p0,p1,p2,p3]}]
        self.patterns: List[dict] = []    # [{length, events: [(row, note, inst, vol)]}]
        self.song_length: int = 0

        # Pitch table (36 entries: notes 1-36 -> 16-bit 8.8 fixed-point step)
        self.pitch_table: List[int] = []

        # Timing
        self.ntsc: bool = False
        self.audf_val: int = 3            # Timer frequency divider
        self.audctl_val: int = 0          # AUDCTL register value

        # Volume control
        self.volume_control: bool = False
        self.volume_scale: bytes = b''    # 256-byte lookup table

    def build_codebook_offsets(self):
        """(Re)compute cb_offset_lo/hi from codebook length and vector_size.

        This replaces any Atari-address-based VQ_LO/VQ_HI tables with simple
        byte-offset tables that index directly into self.codebook.
        """
        vs = self.vector_size
        num_vectors = min(256, len(self.codebook) // vs) if vs > 0 else 0
        lo = bytearray(256)
        hi = bytearray(256)
        for i in range(num_vectors):
            offset = i * vs
            lo[i] = offset & 0xFF
            hi[i] = (offset >> 8) & 0xFF
        self.cb_offset_lo = bytes(lo)
        self.cb_offset_hi = bytes(hi)

    def build_volume_scale(self):
        """Build VOLUME_SCALE lookup table for volume control mode.

        Index = (volume << 4) | sample_nibble
        Output = 0x10 | scaled_nibble
        """
        table = bytearray(256)
        for vol in range(16):
            for sample in range(16):
                idx = (vol << 4) | sample
                # Scale: output = round(sample * vol / 15)
                scaled = round(sample * vol / 15.0) if vol > 0 else 0
                table[idx] = 0x10 | (int(scaled) & 0x0F)
        self.volume_scale = bytes(table)


# ============================================================================
# ChannelState
# ============================================================================

class ChannelState:
    """Per-channel playback state -- mirrors trkN_* zero-page variables.

    All arithmetic uses 8-bit masking to match 6502 behavior exactly.
    """

    __slots__ = (
        'active', 'stream_pos', 'stream_end',
        'sample_ptr', 'vector_offset',
        'pitch_frac', 'pitch_int', 'pitch_step',
        'is_vq', 'instrument', 'has_pitch',
        'vol_shift',
    )

    def __init__(self):
        self.active = False
        self.stream_pos = 0       # Current position in index/raw stream
        self.stream_end = 0       # End position (exclusive)
        self.sample_ptr = 0       # Codebook vector offset (VQ) or data page (RAW)
        self.vector_offset = 0    # 8-bit position within vector (VQ) or page (RAW)
        self.pitch_frac = 0       # 8-bit fractional pitch accumulator
        self.pitch_int = 0        # 8-bit integer pitch accumulator (VQ only)
        self.pitch_step = 0x0100  # 16-bit 8.8 fixed-point pitch (0x0100 = 1.0)
        self.is_vq = True
        self.instrument: Optional[InstrumentData] = None
        self.has_pitch = False
        self.vol_shift = 0        # Volume shift: upper nibble for VOLUME_SCALE

    def trigger(self, inst: InstrumentData, pitch_step: int, song: 'SongData'):
        """Trigger a note -- mirrors PREPARE_CHANNEL + SETUP_CHANNEL."""
        self.active = True
        self.instrument = inst
        self.is_vq = inst.is_vq
        self.stream_pos = inst.start_offset
        self.stream_end = inst.end_offset
        self.vector_offset = 0
        self.pitch_frac = 0
        self.pitch_int = 0
        self.pitch_step = pitch_step
        # "No pitch" detection: step == $0100 means 1:1 playback
        self.has_pitch = (pitch_step != 0x0100)

        if inst.is_vq:
            # Load first codebook vector
            if self.stream_pos < len(inst.stream_data):
                idx = inst.stream_data[self.stream_pos]
                self.sample_ptr = (song.cb_offset_lo[idx]
                                   | (song.cb_offset_hi[idx] << 8))
            else:
                self.active = False
        else:
            # RAW: sample_ptr = 0 (relative to instrument data start)
            self.sample_ptr = 0

    def note_off(self):
        self.active = False


# ============================================================================
# VQPlayer
# ============================================================================

class VQPlayer:
    """Complete VQ player engine: loads song data, drives POKEY, produces PCM.

    Two timing domains:
    1. Frame rate (50/60 Hz): Song sequencer advances rows, triggers notes.
    2. Sample rate (POKEY timer): IRQ handler outputs one AUDC write per tick.
    """

    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.pokey = PokeyPair()
        self.channels = [ChannelState() for _ in range(4)]
        self.song: Optional[SongData] = None

        # Sequencer state
        self.playing = False
        self.seq_songline = 0
        self.seq_row = 0
        self.seq_tick = 0
        self.seq_speed = 6
        self.seq_max_len = 64

        # Per-channel pattern tracking
        self.seq_local_row = [0, 0, 0, 0]
        self.seq_ptn_idx = [0, 0, 0, 0]
        self.seq_evt_pos = [0, 0, 0, 0]
        self.seq_next_evt_row = [0xFF, 0xFF, 0xFF, 0xFF]

        # Timing
        self.ntsc = False
        self.cycles_per_frame = PAL_CYCLES_PER_FRAME
        self.timer_period = 112

        # Channel muting (set by host to mute specific channels)
        self.channel_muted = [False, False, False, False]

    def load_song(self, song: SongData):
        """Load song data and initialize the emulator."""
        self.song = song
        self.ntsc = song.ntsc
        self.cycles_per_frame = (NTSC_CYCLES_PER_FRAME if song.ntsc
                                 else PAL_CYCLES_PER_FRAME)

        # Compute timer period from AUDF and AUDCTL
        if (song.audctl_val & 0x40) != 0:
            # 1.79 MHz clock for channel 1
            self.timer_period = song.audf_val + 4
        elif (song.audctl_val & 1) != 0:
            # 15 kHz clock
            self.timer_period = 114 * (song.audf_val + 1)
        else:
            # 64 kHz clock (default)
            self.timer_period = 28 * (song.audf_val + 1)

        # Ensure codebook offset tables exist
        if not song.cb_offset_lo:
            song.build_codebook_offsets()

        # Build volume scale if needed
        if song.volume_control and not song.volume_scale:
            song.build_volume_scale()

        # Initialize POKEY
        self.pokey.initialize(ntsc=song.ntsc, stereo=False,
                              sample_rate=self.sample_rate)
        self._setup_pokey()

        # Reset sequencer and channels
        self.playing = False
        self.seq_songline = 0
        self.seq_row = 0
        self.seq_tick = 0
        for ch in self.channels:
            ch.active = False

    def _setup_pokey(self):
        """Initialize POKEY registers -- mirrors asm/common/pokey_setup.asm."""
        song = self.song
        # Enter init mode
        self.pokey.poke(SKCTL, 0x00, 0)
        # Silence all channels
        for reg in AUDC_REGS:
            self.pokey.poke(reg, SILENCE, 0)
        # Set timer frequencies
        for reg in AUDF_REGS:
            self.pokey.poke(reg, song.audf_val, 0)
        # Set AUDCTL
        self.pokey.poke(AUDCTL, song.audctl_val, 0)
        # Exit init mode (unmutes channels)
        self.pokey.poke(SKCTL, 0x03, 0)
        # Start timers
        self.pokey.poke(STIMER, 0x00, 0)

    def start_playback(self, songline=0, row=0):
        """Start song playback from a given position."""
        if not self.song:
            return
        self.playing = True
        self.seq_songline = songline
        self.seq_row = row
        self.seq_tick = 0
        self._load_songline()
        if not self.playing:
            # _load_songline set playing=False (songline out of range)
            return

        # Fast-forward each channel's local_row to match the starting row.
        # _load_songline sets local_row=0 and evt_pos=0. We need to advance
        # local_row to `row` and skip past any events before that row,
        # WITHOUT firing those events (they're in the "past").
        if row > 0:
            song = self.song
            for ch_idx in range(4):
                ptn_idx = self.seq_ptn_idx[ch_idx]
                if ptn_idx >= len(song.patterns):
                    continue
                ptn = song.patterns[ptn_idx]
                events = ptn['events']
                ptn_len = ptn['length']

                # Compute effective local_row after `row` advances with wrapping
                local = row % ptn_len
                self.seq_local_row[ch_idx] = local

                # Advance evt_pos past events that precede `local`
                evt_pos = 0
                while evt_pos < len(events) and events[evt_pos][0] < local:
                    evt_pos += 1
                self.seq_evt_pos[ch_idx] = evt_pos

                # Set next_evt_row
                if evt_pos < len(events):
                    self.seq_next_evt_row[ch_idx] = events[evt_pos][0]
                else:
                    self.seq_next_evt_row[ch_idx] = 0xFF

        self._process_row()

    def stop_playback(self):
        """Stop playback and silence all channels."""
        self.playing = False
        for ch in self.channels:
            ch.active = False

    # ========================================================================
    # Frame Rendering -- Core Loop
    # ========================================================================

    def render_frame(self):
        """Run one frame of emulation. Returns PCM as numpy float32 array.

        For each POKEY timer tick within the frame:
        1. For each active channel: read sample byte, write AUDC to POKEY
        2. Advance channel state (vector offset, stream position, pitch)

        At frame end: advance song sequencer, extract PCM from POKEY.
        """
        song = self.song
        if not song:
            return np.zeros(0, dtype=np.float32)

        self.pokey.start_frame()

        codebook = song.codebook
        vol_ctrl = song.volume_control
        vol_table = song.volume_scale

        # Generate timer ticks within the frame
        cycle = 0
        period = self.timer_period
        channels = self.channels

        while cycle < self.cycles_per_frame:
            for ch_idx in range(4):
                ch = channels[ch_idx]
                if not ch.active:
                    continue

                # --- Read sample byte (mirrors the LDA (sample_ptr),Y) ---
                sample_byte = self._read_sample(ch, codebook)

                # --- Apply volume control if enabled ---
                if vol_ctrl and vol_table:
                    nibble = sample_byte & 0x0F
                    idx = ch.vol_shift | nibble
                    sample_byte = vol_table[idx]

                # --- Write to POKEY (cycle-accurate) ---
                # If channel is muted by host, write silence instead
                if self.channel_muted[ch_idx]:
                    self.pokey.poke(AUDC_REGS[ch_idx], SILENCE, cycle)
                else:
                    self.pokey.poke(AUDC_REGS[ch_idx], sample_byte, cycle)

                # --- Advance channel state ---
                if ch.is_vq:
                    self._tick_vq(ch, ch_idx, cycle)
                else:
                    self._tick_raw(ch, ch_idx, cycle)

            cycle += period

        # Advance song sequencer (frame-rate)
        if self.playing:
            self._advance_sequencer()

        # End frame and extract PCM
        num_samples = self.pokey.end_frame(self.cycles_per_frame)
        pcm_s16 = self.pokey.generate(num_samples)

        if pcm_s16:
            return np.array(pcm_s16, dtype=np.float32) / 32767.0
        return np.zeros(0, dtype=np.float32)

    def _read_sample(self, ch: ChannelState, codebook: bytes) -> int:
        """Read current sample byte from codebook (VQ) or raw data (RAW).

        Returns an AUDC-format byte (typically 0x1x for volume-only mode).
        """
        if ch.is_vq:
            # VQ: read from codebook at (sample_ptr + vector_offset)
            # sample_ptr is a codebook offset (NOT an Atari address)
            offset = ch.sample_ptr + ch.vector_offset
            if offset < len(codebook):
                return codebook[offset]
            return SILENCE
        else:
            # RAW: read from instrument data at (sample_ptr + vector_offset)
            # sample_ptr accumulates by 256 on page crosses;
            # vector_offset is the 8-bit offset within the page
            pos = ch.instrument.start_offset + ch.sample_ptr + ch.vector_offset
            data = ch.instrument.stream_data
            if pos < len(data):
                return data[pos]
            return SILENCE

    # ========================================================================
    # Channel Tick -- VQ Mode (mirrors CHANNEL_IRQ_64K VQ paths)
    # ========================================================================

    def _tick_vq(self, ch: ChannelState, ch_idx: int, cycle: int):
        """Advance VQ channel by one timer tick."""
        song = self.song
        vs = song.vector_size

        if not ch.has_pitch:
            # --- VQ NO-PITCH (mirrors ch:1_vq_no_pitch) ---
            # INC vector_offset; CMP #MIN_VECTOR; BCS boundary
            ch.vector_offset += 1
            if ch.vector_offset >= vs:
                ch.vector_offset = 0
                ch.stream_pos += 1
                self._load_vq_vector(ch, ch_idx, cycle)
        else:
            # --- VQ PITCH (mirrors ch:1_vq_pitch) ---
            # 8.8 fixed-point pitch accumulation (exact 6502 arithmetic)
            #
            # CLC; LDA pitch_frac; ADC pitch_step_lo; STA pitch_frac
            frac = ch.pitch_frac + (ch.pitch_step & 0xFF)
            carry = 1 if frac >= 256 else 0
            ch.pitch_frac = frac & 0xFF

            # LDA pitch_int; ADC pitch_step_hi; STA pitch_int; BEQ done
            raw_int = ch.pitch_int + (ch.pitch_step >> 8) + carry
            ch.pitch_int = raw_int & 0xFF  # 6502 stores 8-bit result
            if ch.pitch_int == 0:           # BEQ checks the 8-bit Z flag
                return

            # Non-zero: advance vector_offset by pitch_int amount
            advance = ch.pitch_int
            ch.pitch_int = 0  # LDA #0; STA pitch_int

            # CLC; LDA vector_offset; ADC advance; STA vector_offset
            new_vo = (ch.vector_offset + advance) & 0xFF

            # CMP #MIN_VECTOR; BCC done (no boundary cross)
            if new_vo < vs:
                ch.vector_offset = new_vo
                return

            # --- Boundary crossed ---
            # vectors_crossed = new_vo / MIN_VECTOR (via LSR shifts)
            vectors_crossed = new_vo // vs

            # stream_ptr += vectors_crossed (16-bit add)
            ch.stream_pos += vectors_crossed

            # vector_offset = new_vo AND VECTOR_MASK
            ch.vector_offset = new_vo % vs

            # Load new vector + check end
            self._load_vq_vector(ch, ch_idx, cycle)

    def _load_vq_vector(self, ch: ChannelState, ch_idx: int, cycle: int):
        """Load next codebook vector -- mirrors ch:1_check_end + ch:1_load_vector."""
        if ch.stream_pos >= ch.stream_end:
            # End of sample
            ch.active = False
            self.pokey.poke(AUDC_REGS[ch_idx], SILENCE, cycle)
            return
        # Read VQ index from stream
        idx = ch.instrument.stream_data[ch.stream_pos]
        # Look up codebook entry offset
        song = self.song
        ch.sample_ptr = (song.cb_offset_lo[idx]
                         | (song.cb_offset_hi[idx] << 8))

    # ========================================================================
    # Channel Tick -- RAW Mode (mirrors CHANNEL_IRQ_64K RAW paths)
    # ========================================================================

    def _tick_raw(self, ch: ChannelState, ch_idx: int, cycle: int):
        """Advance RAW channel by one timer tick."""
        if not ch.has_pitch:
            # --- RAW NO-PITCH ---
            # INC vector_offset; BEQ page_cross
            new_vo = (ch.vector_offset + 1) & 0xFF
            ch.vector_offset = new_vo
            if new_vo == 0:
                # Page cross: increment sample_ptr high byte (= +256)
                ch.sample_ptr += 256
                self._check_raw_end(ch, ch_idx, cycle)
        else:
            # --- RAW PITCH ---
            # CLC; LDA pitch_frac; ADC pitch_step_lo; STA pitch_frac
            frac = ch.pitch_frac + (ch.pitch_step & 0xFF)
            carry = 1 if frac >= 256 else 0
            ch.pitch_frac = frac & 0xFF

            # LDA vector_offset; ADC pitch_step_hi; STA vector_offset; BCS page
            advance = (ch.pitch_step >> 8) + carry
            new_vo = ch.vector_offset + advance
            page_cross = (new_vo >= 256)
            ch.vector_offset = new_vo & 0xFF

            if page_cross:
                # INC sample_ptr+1 (= +256 bytes)
                ch.sample_ptr += 256
                self._check_raw_end(ch, ch_idx, cycle)

    def _check_raw_end(self, ch: ChannelState, ch_idx: int, cycle: int):
        """Check if RAW playback reached end -- mirrors ch:1_raw_page_check.

        Compares current position (sample_ptr : vector_offset) against
        stream_end as a 16-bit comparison.
        """
        # Effective position relative to instrument start
        pos = ch.sample_ptr + ch.vector_offset
        end = ch.stream_end - ch.instrument.start_offset
        if pos >= end:
            ch.active = False
            self.pokey.poke(AUDC_REGS[ch_idx], SILENCE, cycle)

    # ========================================================================
    # Song Sequencer
    # ========================================================================

    def _advance_sequencer(self):
        """Advance song sequencer by one frame -- mirrors main_loop tick logic."""
        if not self.playing:
            return

        self.seq_tick += 1
        if self.seq_tick < self.seq_speed:
            return
        self.seq_tick = 0

        # Advance global row counter
        self.seq_row += 1
        if self.seq_row >= self.seq_max_len:
            self.seq_row = 0
            self.seq_songline += 1
            if self.seq_songline >= self.song.song_length:
                self.seq_songline = 0
                self.playing = False
                return
            self._load_songline()

        # Process row events after advancing
        self._process_row()

    def _load_songline(self):
        """Load patterns for current songline -- mirrors seq_load_songline."""
        song = self.song
        if self.seq_songline >= len(song.songlines):
            self.playing = False
            return

        sl = song.songlines[self.seq_songline]
        self.seq_speed = sl['speed']

        max_len = 0
        for ch_idx in range(4):
            ptn_idx = sl['patterns'][ch_idx] if ch_idx < len(sl['patterns']) else 0
            self.seq_ptn_idx[ch_idx] = ptn_idx
            if ptn_idx < len(song.patterns):
                ptn = song.patterns[ptn_idx]
                ptn_len = ptn['length']
                if ptn_len > max_len:
                    max_len = ptn_len
                self.seq_local_row[ch_idx] = 0
                self.seq_evt_pos[ch_idx] = 0
                events = ptn['events']
                self.seq_next_evt_row[ch_idx] = (events[0][0]
                                                  if events else 0xFF)
            else:
                self.seq_local_row[ch_idx] = 0
                self.seq_evt_pos[ch_idx] = 0
                self.seq_next_evt_row[ch_idx] = 0xFF

        self.seq_max_len = max(max_len, 1)

    def _process_row(self):
        """Process current row -- dispatch events, advance local rows.

        Mirrors process_row.asm: DISPATCH_EVENT for each channel,
        then advance seq_local_row per channel with wrap.
        """
        song = self.song
        for ch_idx in range(4):
            ptn_idx = self.seq_ptn_idx[ch_idx]
            if ptn_idx >= len(song.patterns):
                continue
            ptn = song.patterns[ptn_idx]
            events = ptn['events']
            local_row = self.seq_local_row[ch_idx]
            evt_pos = self.seq_evt_pos[ch_idx]

            # Check for event on this row
            if (evt_pos < len(events)
                    and events[evt_pos][0] == local_row):
                _, note, inst_idx, vol = events[evt_pos]
                self.seq_evt_pos[ch_idx] = evt_pos + 1
                # Update next event row
                if evt_pos + 1 < len(events):
                    self.seq_next_evt_row[ch_idx] = events[evt_pos + 1][0]
                else:
                    self.seq_next_evt_row[ch_idx] = 0xFF
                self._dispatch_event(ch_idx, note, inst_idx, vol)

            # Advance local row with pattern wrap
            local_row += 1
            if local_row >= ptn['length']:
                local_row = 0
                self.seq_evt_pos[ch_idx] = 0
                if events:
                    self.seq_next_evt_row[ch_idx] = events[0][0]
            self.seq_local_row[ch_idx] = local_row

    def _dispatch_event(self, ch_idx: int, note: int, inst_idx: int, vol: int):
        """Handle a single event -- mirrors DISPATCH + PREPARE + COMMIT."""
        song = self.song
        ch = self.channels[ch_idx]

        if note == 0:
            # Note-off
            ch.note_off()
            self.pokey.poke(AUDC_REGS[ch_idx], SILENCE, 0)
            return

        if note == VOL_CHANGE_ASM:
            # Volume-only change (no retrigger)
            ch.vol_shift = (vol << 4) & 0xF0
            return

        # Normal note-on
        if inst_idx >= len(song.instruments):
            return
        inst = song.instruments[inst_idx]

        # Look up pitch (notes are 1-based; index 0 = C-1)
        pitch_step = 0x0100  # Default: 1.0x
        note_idx = note - 1
        if 0 <= note_idx < len(song.pitch_table):
            pitch_step = song.pitch_table[note_idx]

        # Trigger
        ch.trigger(inst, pitch_step, song)
        ch.vol_shift = (vol << 4) & 0xF0

    # ========================================================================
    # Data Loading -- From Tracker
    # ========================================================================

    def load_from_tracker(self, song_obj, vq_result, vq_settings):
        """Load data from tracker's Song model + VQ conversion results.

        This is the primary data bridge between the tracker and the player.

        Args:
            song_obj: data_model.Song instance.
            vq_result: vq_convert.VQResult instance (may be None).
            vq_settings: vq_convert.VQSettings instance.
        """
        song_data = SongData()
        song_data.ntsc = (song_obj.system == 60)
        song_data.vector_size = vq_settings.vector_size
        song_data.volume_control = getattr(song_obj, 'volume_control', False)

        # Compute AUDF from target sample rate
        clock = NTSC_CLOCK if song_data.ntsc else PAL_CLOCK
        rate = vq_settings.rate
        song_data.audf_val = max(0, min(255, round(clock / 28.0 / rate) - 1))
        song_data.audctl_val = 0  # Standard 64kHz mode

        # Load VQ data
        if vq_result and vq_result.output_dir:
            self._load_vq_files(song_data, vq_result.output_dir, song_obj)

        # Build codebook offset tables (always recompute, ignoring Atari addresses)
        song_data.build_codebook_offsets()

        # Build pitch table
        song_data.pitch_table = self._build_pitch_table()

        # Build volume scale if needed
        if song_data.volume_control:
            song_data.build_volume_scale()

        # Build song structure
        song_data.song_length = len(song_obj.songlines)
        for sl in song_obj.songlines:
            song_data.songlines.append({
                'speed': max(1, sl.speed),
                'patterns': list(sl.patterns),
            })

        for ptn in song_obj.patterns:
            events = []
            for row_idx in range(ptn.length):
                r = ptn.rows[row_idx]
                if r.note == 0:
                    continue  # Empty row — no event
                # Translate tracker constants to player constants:
                #   Tracker NOTE_OFF (255) → player note-off (0)
                #   Tracker VOL_CHANGE (254) → player VOL_CHANGE_ASM (61)
                if r.note == NOTE_OFF:  # 255
                    events.append((row_idx, 0, 0, 0))
                elif r.note == 254:  # tracker VOL_CHANGE
                    events.append((row_idx, VOL_CHANGE_ASM, r.instrument, r.volume))
                else:
                    events.append((row_idx, r.note, r.instrument, r.volume))
            song_data.patterns.append({
                'length': ptn.length,
                'events': events,
            })

        self.load_song(song_data)

    def _load_vq_files(self, song_data: SongData, output_dir: str, song_obj):
        """Load VQ binary data from the converter's ASM output directory.

        We parse the ASM files for raw byte data, but IGNORE the addresses
        in VQ_LO/VQ_HI -- we recompute offset tables from vector_size.
        """
        vq_blob = self._parse_asm_bytes(
            os.path.join(output_dir, 'VQ_BLOB.asm'))
        vq_indices = self._parse_asm_bytes(
            os.path.join(output_dir, 'VQ_INDICES.asm'))

        song_data.codebook = bytes(vq_blob)
        # VQ_LO/VQ_HI from ASM contain Atari addresses -- we ignore them
        # and recompute from vector_size in build_codebook_offsets()

        # Load conversion_info.json for per-instrument boundaries
        info_path = os.path.join(output_dir, 'conversion_info.json')
        indices_bytes = bytes(vq_indices)

        if os.path.exists(info_path):
            with open(info_path, 'r') as f:
                info = json.load(f)
            samples = info.get('samples', [])

            # Pre-parse RAW_SAMPLES.asm if it exists (builder writes
            # all RAW instrument data into one file with RAW_INST_XX labels)
            raw_samples_path = os.path.join(output_dir, 'RAW_SAMPLES.asm')
            raw_inst_data = {}  # {index: bytes}
            if os.path.exists(raw_samples_path):
                raw_inst_data = self._parse_raw_samples_asm(
                    raw_samples_path)

            for i, s in enumerate(samples):
                start = s.get('index_start', 0)
                end = s.get('index_end', 0)
                mode = s.get('mode', 'vq')
                is_vq = (mode.lower() != 'raw')

                if is_vq:
                    inst = InstrumentData(
                        index=i, is_vq=True,
                        stream_data=indices_bytes,
                        start_offset=start, end_offset=end,
                    )
                else:
                    # RAW: load from pre-parsed RAW_SAMPLES.asm
                    if i in raw_inst_data:
                        raw_bytes = raw_inst_data[i]
                    else:
                        # Legacy fallback: per-instrument file
                        raw_path = os.path.join(output_dir,
                                                f'RAW_SAMPLE_{i}.asm')
                        if os.path.exists(raw_path):
                            raw_bytes = bytes(
                                self._parse_asm_bytes(raw_path))
                        else:
                            raw_bytes = b'\x10'  # silence byte
                    inst = InstrumentData(
                        index=i, is_vq=False,
                        stream_data=raw_bytes,
                        start_offset=0, end_offset=len(raw_bytes),
                    )
                song_data.instruments.append(inst)
        else:
            # Fallback: treat everything as one VQ instrument
            if indices_bytes:
                inst = InstrumentData(
                    index=0, is_vq=True,
                    stream_data=indices_bytes,
                    start_offset=0, end_offset=len(indices_bytes),
                )
                song_data.instruments.append(inst)

    def _parse_asm_bytes(self, path: str) -> list:
        """Parse MADS .asm file containing data directives into byte list.

        Handles: .byte, dta b(), dta, .db directives with hex ($xx) and
        decimal values. Strips comments.
        """
        result = []
        if not os.path.exists(path):
            return result
        with open(path, 'r') as f:
            for line in f:
                # Strip leading whitespace for directive matching
                stripped = line.strip()
                if not stripped or stripped.startswith(';'):
                    continue
                # Skip labels and constant definitions
                if '=' in stripped and not stripped.startswith(('.', 'd')):
                    continue

                # Find data portion -- try various MADS formats
                data_part = None
                lower = stripped.lower()
                if lower.startswith('.byte '):
                    data_part = stripped[6:]
                elif lower.startswith('dta b('):
                    data_part = stripped[6:]
                    data_part = data_part.rstrip(')')
                elif lower.startswith('.dta b('):
                    data_part = stripped[7:]
                    data_part = data_part.rstrip(')')
                elif lower.startswith('.db '):
                    data_part = stripped[4:]
                elif lower.startswith('dta '):
                    rest = stripped[4:].strip()
                    if rest and (rest[0] == '$' or rest[0].isdigit()):
                        data_part = rest

                if data_part is None:
                    continue

                # Remove trailing comment
                for comment_char in (';', '//'):
                    ci = data_part.find(comment_char)
                    if ci >= 0:
                        data_part = data_part[:ci]
                data_part = data_part.strip().rstrip(')')

                # Parse comma-separated values
                for val_str in data_part.split(','):
                    val_str = val_str.strip()
                    if not val_str:
                        continue
                    try:
                        if val_str.startswith('$'):
                            result.append(int(val_str[1:], 16) & 0xFF)
                        elif val_str.startswith('0x') or val_str.startswith('0X'):
                            result.append(int(val_str, 16) & 0xFF)
                        elif val_str.lstrip('-').isdigit():
                            result.append(int(val_str) & 0xFF)
                    except ValueError:
                        continue
        return result

    def _parse_raw_samples_asm(self, path: str) -> dict:
        """Parse RAW_SAMPLES.asm into per-instrument byte data.

        The builder generates one file containing all RAW instruments with
        labels like RAW_INST_00 / RAW_INST_00_END. We extract the byte
        data between each label pair.

        Returns dict {instrument_index: bytes}.
        """
        import re
        result = {}
        if not os.path.exists(path):
            return result

        # First pass: find all RAW_INST_XX labels and their line numbers
        lines = []
        with open(path, 'r') as f:
            lines = f.readlines()

        # Pattern: RAW_INST_00, RAW_INST_01, etc.
        label_re = re.compile(r'^RAW_INST_(\d+)\s*$')
        end_re = re.compile(r'^RAW_INST_(\d+)_END\s*$')

        current_idx = None
        current_bytes = []

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue

            # Check for start label
            m = label_re.match(stripped)
            if m:
                # Save previous instrument if any
                if current_idx is not None and current_bytes:
                    result[current_idx] = bytes(current_bytes)
                current_idx = int(m.group(1))
                current_bytes = []
                continue

            # Check for end label
            m = end_re.match(stripped)
            if m:
                idx = int(m.group(1))
                if current_idx == idx and current_bytes:
                    result[current_idx] = bytes(current_bytes)
                current_idx = None
                current_bytes = []
                continue

            # If we're inside a label block, parse byte data
            if current_idx is not None:
                lower = stripped.lower()
                data_part = None
                if lower.startswith('.byte '):
                    data_part = stripped[6:]
                elif lower.startswith('.align'):
                    continue  # Skip alignment directives
                elif lower.startswith('.'):
                    continue  # Skip other directives

                if data_part:
                    # Remove comments
                    for cc in (';', '//'):
                        ci = data_part.find(cc)
                        if ci >= 0:
                            data_part = data_part[:ci]
                    for val_str in data_part.split(','):
                        val_str = val_str.strip()
                        if not val_str:
                            continue
                        try:
                            if val_str.startswith('$'):
                                current_bytes.append(
                                    int(val_str[1:], 16) & 0xFF)
                            elif val_str.lstrip('-').isdigit():
                                current_bytes.append(
                                    int(val_str) & 0xFF)
                        except ValueError:
                            continue

        # Handle last instrument if file doesn't end with _END label
        if current_idx is not None and current_bytes:
            result[current_idx] = bytes(current_bytes)

        return result

    def _build_pitch_table(self) -> List[int]:
        """Build NOTE_PITCH_LO/HI table -- 36 notes, equal temperament.

        Note 0 (C-1) = 1.0x = $0100. Each semitone = 2^(1/12) ratio.
        Returns list of 16-bit 8.8 fixed-point values.
        """
        return [min(0xFFFF, int(round(2.0 ** (n / 12.0) * 256.0)))
                for n in range(36)]

    # ========================================================================
    # Direct VQ Data Loading (for converter preview)
    # ========================================================================

    def load_vq_direct(self, codebook: bytes, indices: bytes,
                       codebook_lo: bytes = None, codebook_hi: bytes = None,
                       vector_size: int = 8, audf_val: int = 3,
                       audctl_val: int = 0, ntsc: bool = False):
        """Load VQ data directly for single-instrument preview.

        The codebook_lo/codebook_hi parameters are IGNORED -- offset tables
        are always computed from vector_size to avoid address mismatch.
        """
        song = SongData()
        song.ntsc = ntsc
        song.codebook = codebook
        song.vector_size = vector_size
        song.audf_val = audf_val
        song.audctl_val = audctl_val
        song.song_length = 0
        song.pitch_table = self._build_pitch_table()
        song.build_codebook_offsets()

        inst = InstrumentData(
            index=0, is_vq=True,
            stream_data=indices,
            start_offset=0, end_offset=len(indices),
        )
        song.instruments.append(inst)

        self.load_song(song)

        # Auto-trigger on channel 0 at base pitch
        self.channels[0].trigger(inst, 0x0100, song)

    # ========================================================================
    # Batch Rendering
    # ========================================================================

    def render_all_frames(self, max_frames=30000, progress_cb=None):
        """Render frames until playback stops or max_frames reached.

        Returns numpy float32 array of all PCM samples.
        """
        chunks = []
        frame_count = 0
        while frame_count < max_frames:
            pcm = self.render_frame()
            if len(pcm) > 0:
                chunks.append(pcm)
            frame_count += 1
            if progress_cb and frame_count % 50 == 0:
                progress_cb(frame_count)
            # Stop when nothing is playing
            if not self.playing and not any(ch.active for ch in self.channels):
                # Render tail frames for reverb/decay
                for _ in range(10):
                    pcm = self.render_frame()
                    if len(pcm) > 0:
                        chunks.append(pcm)
                break

        if chunks:
            return np.concatenate(chunks)
        return np.zeros(0, dtype=np.float32)


# ============================================================================
# Convenience Functions
# ============================================================================

def render_vq_wav(codebook: bytes, indices: bytes,
                  codebook_lo: bytes = None, codebook_hi: bytes = None,
                  output_path: str = 'output.wav',
                  vector_size: int = 8, audf_val: int = 3,
                  audctl_val: int = 0, ntsc: bool = False,
                  sample_rate: int = 44100):
    """One-call offline rendering: VQ data -> WAV file.

    Returns duration in seconds.
    """
    player = VQPlayer(sample_rate=sample_rate)
    player.load_vq_direct(
        codebook=codebook, indices=indices,
        vector_size=vector_size, audf_val=audf_val,
        audctl_val=audctl_val, ntsc=ntsc,
    )

    pcm = player.render_all_frames()
    if len(pcm) == 0:
        return 0.0

    pcm_s16 = np.clip(pcm * 32767, -32768, 32767).astype(np.int16)

    with wave.open(output_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_s16.tobytes())

    return len(pcm) / sample_rate
