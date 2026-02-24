"""
pokey_emulator/pokey.py — Cycle-accurate POKEY chip emulator

Faithful Python port of ASAP's pokey.fu by Piotr Fusik.
Original: Copyright (C) 2010-2026 Piotr Fusik, GPLv2+
Port: preserves all algorithms, constants, and behavior exactly.

Classes:
    PokeyChannel — Single audio channel (×4 per chip)
    Pokey        — One POKEY chip: 4 channels, register handling, DAC, sinc output
    PokeyPair    — Stereo pair with polynomial lookup tables and sinc precomputation
"""

import math

# ============================================================================
# Constants
# ============================================================================

NEVER_CYCLE = 0x800000

# Mute flag bits
MUTE_INIT = 1
MUTE_USER = 2
MUTE_SERIAL_INPUT = 4
MUTE_SONG_INIT = 8

# Sinc interpolation parameters
INTERPOLATION_SHIFT = 10          # 1024 phase offsets
UNIT_DELTA_LENGTH = 32            # Sinc kernel length
DELTA_RESOLUTION = 14             # 16384 amplitude levels
SAMPLE_FACTOR_SHIFT = 18          # Fixed-point shift for clock→sample

# DAC compression shift
DELTA_SHIFT_POKEY = 16

# Clocks
PAL_CLOCK = 1773447
NTSC_CLOCK = 1789772
PAL_SCANLINES = 312
NTSC_SCANLINES = 262
CYCLES_PER_SCANLINE = 114
PAL_CYCLES_PER_FRAME = PAL_SCANLINES * CYCLES_PER_SCANLINE    # 35568
NTSC_CYCLES_PER_FRAME = NTSC_SCANLINES * CYCLES_PER_SCANLINE  # 29868

# Sample formats
FORMAT_U8 = 0
FORMAT_S16LE = 1
FORMAT_S16BE = 2

# DAC compression table — from measurements of AMI-produced POKEY chips.
# Maps summed channel DAC inputs (0..60) to compressed output level.
COMPRESSED_SUMS = [
    0, 35, 73, 111, 149, 189, 228, 266, 304, 342, 379, 415, 450, 484, 516, 546,
    575, 602, 628, 652, 674, 695, 715, 733, 750, 766, 782, 796, 809, 822, 834, 846,
    856, 867, 876, 886, 894, 903, 911, 918, 926, 933, 939, 946, 952, 958, 963, 969,
    974, 979, 984, 988, 993, 997, 1001, 1005, 1009, 1013, 1016, 1019, 1023
]


# ============================================================================
# PokeyChannel
# ============================================================================

class PokeyChannel:
    """Single POKEY audio channel state and processing."""

    __slots__ = (
        'audf', 'audc', 'period_cycles', 'tick_cycle', 'timer_cycle',
        'mute', 'out', 'delta',
    )

    def __init__(self):
        self.initialize()

    def initialize(self, apokeysnd=False):
        self.audf = 0
        self.audc = 0
        self.period_cycles = 28
        self.tick_cycle = NEVER_CYCLE
        self.timer_cycle = NEVER_CYCLE
        self.mute = 0 if apokeysnd else MUTE_SONG_INIT
        self.out = 0
        self.delta = 0

    def _add_delta(self, pokey, pokeys, cycle, delta):
        pokey.add_pokey_delta(
            pokeys, cycle, delta,
            (self.mute & (MUTE_USER | MUTE_SONG_INIT)) != 0
        )

    def _slope(self, pokey, pokeys, cycle):
        self.delta = -self.delta
        self._add_delta(pokey, pokeys, cycle, self.delta)

    def do_tick(self, pokey, pokeys, cycle, ch):
        """Process one channel tick — core waveform generation."""
        self.tick_cycle += self.period_cycles
        audc = self.audc

        if (audc & 0xB0) == 0xA0:
            # Pure tone (no polynomial distortion)
            self.out ^= 1
        elif (audc & 0x10) != 0 or pokey.init:
            # Volume-only mode or init mode — no output change
            return
        else:
            poly = cycle + pokey.poly_index - ch

            # Poly5 gate: magic constant encodes the 31-bit poly5 pattern
            # Pattern: 0000011100100010101111011010011
            if audc < 0x80 and (0x65BD44E0 & (1 << (poly % 31))) == 0:
                return

            if (audc & 0x20) != 0:
                # Toggle output
                self.out ^= 1
            else:
                if (audc & 0x40) != 0:
                    # Poly4 (15 bits): 000011101100101
                    new_out = (0x5370 >> (poly % 15)) & 1
                elif pokey.audctl < 0x80:
                    # Poly17 (131071 bits)
                    p = poly % 131071
                    new_out = (pokeys.poly17_lookup[p >> 3] >> (p & 7)) & 1
                else:
                    # Poly9 (511 bits)
                    new_out = pokeys.poly9_lookup[poly % 511] & 1

                if self.out == new_out:
                    return
                self.out = new_out

        self._slope(pokey, pokeys, cycle)

    def slope_down(self, pokey, pokeys, cycle):
        """High-pass filter: force slope down if delta positive and unmuted."""
        if self.delta > 0 and self.mute == 0:
            self._slope(pokey, pokeys, cycle)

    def do_stimer(self, pokey, pokeys, cycle, reload):
        """STIMER register reset: restart timer and reset output."""
        if self.tick_cycle != NEVER_CYCLE:
            self.tick_cycle = cycle + reload
        if self.out != 0:
            self.out = 0
            self._slope(pokey, pokeys, cycle)

    def set_mute(self, enable, mask, cycle):
        """Set or clear a mute flag."""
        if enable:
            self.mute |= mask
            self.tick_cycle = NEVER_CYCLE
        else:
            self.mute &= ~mask
            if self.mute == 0 and self.tick_cycle == NEVER_CYCLE:
                self.tick_cycle = cycle

    def set_audc(self, pokey, pokeys, data, cycle):
        """Handle AUDC register write — volume-only mode and delta updates."""
        if self.audc == data:
            return
        pokey.generate_until_cycle(pokeys, cycle)
        self.audc = data

        if (data & 0x10) != 0:
            # Volume-only mode
            data &= 0xF
            if self.delta > 0:
                self._add_delta(pokey, pokeys, cycle, data - self.delta)
            else:
                self._add_delta(pokey, pokeys, cycle, data)
            self.delta = data
        else:
            data &= 0xF
            if self.delta > 0:
                self._add_delta(pokey, pokeys, cycle, data - self.delta)
                self.delta = data
            else:
                self.delta = -data

    def end_frame(self, cycle):
        if self.timer_cycle != NEVER_CYCLE:
            self.timer_cycle -= cycle


# ============================================================================
# Pokey
# ============================================================================

class Pokey:
    """Single POKEY chip: 4 channels, register handling, band-limited output."""

    __slots__ = (
        'channels', 'audctl', 'skctl', 'irqst', 'init',
        'div_cycles', 'reload_cycles1', 'reload_cycles3', 'poly_index',
        'delta_buffer_length', 'delta_buffer',
        'sum_dac_inputs', 'sum_dac_outputs',
        'iir_rate', 'iir_acc', 'trailing',
    )

    def __init__(self):
        self.channels = [PokeyChannel() for _ in range(4)]
        self.audctl = 0
        self.skctl = 3
        self.irqst = 0xFF
        self.init = False
        self.div_cycles = 28
        self.reload_cycles1 = 28
        self.reload_cycles3 = 28
        self.poly_index = 15 * 31 * 131071
        self.delta_buffer_length = 0
        self.delta_buffer = None
        self.sum_dac_inputs = 0
        self.sum_dac_outputs = 0
        self.iir_rate = 6
        self.iir_acc = 0
        self.trailing = 0

    def initialize(self, sample_rate=44100, apokeysnd=False):
        sr = sample_rate
        self.delta_buffer_length = (
            sr * PAL_SCANLINES * CYCLES_PER_SCANLINE // PAL_CLOCK
            + UNIT_DELTA_LENGTH + 2
        )
        self.delta_buffer = [0] * self.delta_buffer_length
        self.trailing = self.delta_buffer_length

        for c in self.channels:
            c.initialize(apokeysnd)

        self.audctl = 0
        self.skctl = 3
        self.irqst = 0xFF
        self.init = False
        self.div_cycles = 28
        self.reload_cycles1 = 28
        self.reload_cycles3 = 28
        self.poly_index = 15 * 31 * 131071
        self.iir_acc = 0
        self.iir_rate = 44100 * 6 // sample_rate
        self.sum_dac_inputs = 0
        self.sum_dac_outputs = 0
        self.start_frame()

    def start_frame(self):
        """Rotate trailing delta buffer data to start; zero the rest."""
        buf = self.delta_buffer
        t = self.trailing
        length = self.delta_buffer_length
        keep = length - t
        buf[:keep] = buf[t:t + keep]
        for i in range(keep, length):
            buf[i] = 0
        self.trailing = self.delta_buffer_length

    def _add_delta(self, pokeys, cycle, delta):
        """Insert sinc-interpolated delta into the output buffer."""
        if delta == 0:
            return
        i = cycle * pokeys.sample_factor + pokeys.sample_offset
        fraction = (
            (i >> (SAMPLE_FACTOR_SHIFT - INTERPOLATION_SHIFT))
            & ((1 << INTERPOLATION_SHIFT) - 1)
        )
        i >>= SAMPLE_FACTOR_SHIFT
        delta >>= DELTA_RESOLUTION
        sinc_row = pokeys.sinc_lookup[fraction]
        buf = self.delta_buffer
        for j in range(UNIT_DELTA_LENGTH):
            buf[i + j] += delta * sinc_row[j]

    def add_pokey_delta(self, pokeys, cycle, delta, muted):
        """Apply DAC compression and insert delta."""
        self.sum_dac_inputs += delta
        if muted:
            return
        new_output = COMPRESSED_SUMS[self.sum_dac_inputs] << DELTA_SHIFT_POKEY
        self._add_delta(pokeys, cycle, new_output - self.sum_dac_outputs)
        self.sum_dac_outputs = new_output

    def add_external_delta(self, pokeys, cycle, delta):
        if (self.channels[0].mute & MUTE_SONG_INIT) == 0:
            self._add_delta(pokeys, cycle, delta)

    def generate_until_cycle(self, pokeys, cycle_limit):
        """Generate audio up to cycle_limit by ticking all channels."""
        ch = self.channels
        while True:
            # Find the earliest pending tick across all 4 channels
            cycle = cycle_limit
            for c in ch:
                tc = c.tick_cycle
                if cycle > tc:
                    cycle = tc
            if cycle == cycle_limit:
                break

            # Process channels in hardware order: 2, 3, 0, 1
            if cycle == ch[2].tick_cycle:
                if (self.audctl & 4) != 0:
                    ch[0].slope_down(self, pokeys, cycle)
                ch[2].do_tick(self, pokeys, cycle, 2)

            if cycle == ch[3].tick_cycle:
                if (self.audctl & 8) != 0:
                    ch[2].tick_cycle = cycle + self.reload_cycles3
                if (self.audctl & 2) != 0:
                    ch[1].slope_down(self, pokeys, cycle)
                ch[3].do_tick(self, pokeys, cycle, 3)

            if cycle == ch[0].tick_cycle:
                if (self.skctl & 0x88) == 8:  # two-tone
                    ch[1].tick_cycle = cycle + ch[1].period_cycles
                ch[0].do_tick(self, pokeys, cycle, 0)

            if cycle == ch[1].tick_cycle:
                if (self.audctl & 0x10) != 0:
                    ch[0].tick_cycle = cycle + self.reload_cycles1
                elif (self.skctl & 8) != 0:  # two-tone
                    ch[0].tick_cycle = cycle + ch[0].period_cycles
                ch[1].do_tick(self, pokeys, cycle, 1)

    def end_frame(self, pokeys, cycle):
        """Finalize a frame: generate remaining audio, update poly index."""
        self.generate_until_cycle(pokeys, cycle)
        self.poly_index += cycle
        m = 15 * 31 * 511 if (self.audctl & 0x80) != 0 else 15 * 31 * 131071
        if self.poly_index >= 2 * m:
            self.poly_index -= m
        for c in self.channels:
            tc = c.tick_cycle
            if tc != NEVER_CYCLE:
                c.tick_cycle = tc - cycle

    def is_silent(self):
        return all((c.audc & 0xF) == 0 for c in self.channels)

    def mute_mask(self, mask):
        for i in range(4):
            self.channels[i].set_mute((mask & (1 << i)) != 0, MUTE_USER, 0)

    def end_song_init(self):
        for c in self.channels:
            c.set_mute(False, MUTE_SONG_INIT, 0)

    def _init_mute(self, cycle):
        init = self.init
        audctl = self.audctl
        self.channels[0].set_mute(init and (audctl & 0x40) == 0, MUTE_INIT, cycle)
        self.channels[1].set_mute(init and (audctl & 0x50) != 0x50, MUTE_INIT, cycle)
        self.channels[2].set_mute(init and (audctl & 0x20) == 0, MUTE_INIT, cycle)
        self.channels[3].set_mute(init and (audctl & 0x28) != 0x28, MUTE_INIT, cycle)

    def poke(self, pokeys, addr, data, cycle):
        """Handle a register write. Returns next event cycle for timer IRQs."""
        next_event_cycle = NEVER_CYCLE
        reg = addr & 0xF
        ch = self.channels

        if reg == 0x00:  # AUDF1
            if data == ch[0].audf:
                return next_event_cycle
            self.generate_until_cycle(pokeys, cycle)
            ch[0].audf = data
            mode = self.audctl & 0x50
            if mode == 0x00:
                ch[0].period_cycles = self.div_cycles * (data + 1)
            elif mode == 0x10:
                ch[1].period_cycles = self.div_cycles * (data + (ch[1].audf << 8) + 1)
                self.reload_cycles1 = self.div_cycles * (data + 1)
            elif mode == 0x40:
                ch[0].period_cycles = data + 4
            elif mode == 0x50:
                ch[1].period_cycles = data + (ch[1].audf << 8) + 7
                self.reload_cycles1 = data + 4

        elif reg == 0x01:  # AUDC1
            ch[0].set_audc(self, pokeys, data, cycle)

        elif reg == 0x02:  # AUDF2
            if data == ch[1].audf:
                return next_event_cycle
            self.generate_until_cycle(pokeys, cycle)
            ch[1].audf = data
            mode = self.audctl & 0x50
            if mode in (0x00, 0x40):
                ch[1].period_cycles = self.div_cycles * (data + 1)
            elif mode == 0x10:
                ch[1].period_cycles = self.div_cycles * (ch[0].audf + (data << 8) + 1)
            elif mode == 0x50:
                ch[1].period_cycles = ch[0].audf + (data << 8) + 7

        elif reg == 0x03:  # AUDC2
            ch[1].set_audc(self, pokeys, data, cycle)

        elif reg == 0x04:  # AUDF3
            if data == ch[2].audf:
                return next_event_cycle
            self.generate_until_cycle(pokeys, cycle)
            ch[2].audf = data
            mode = self.audctl & 0x28
            if mode == 0x00:
                ch[2].period_cycles = self.div_cycles * (data + 1)
            elif mode == 0x08:
                ch[3].period_cycles = self.div_cycles * (data + (ch[3].audf << 8) + 1)
                self.reload_cycles3 = self.div_cycles * (data + 1)
            elif mode == 0x20:
                ch[2].period_cycles = data + 4
            elif mode == 0x28:
                ch[3].period_cycles = data + (ch[3].audf << 8) + 7
                self.reload_cycles3 = data + 4

        elif reg == 0x05:  # AUDC3
            ch[2].set_audc(self, pokeys, data, cycle)

        elif reg == 0x06:  # AUDF4
            if data == ch[3].audf:
                return next_event_cycle
            self.generate_until_cycle(pokeys, cycle)
            ch[3].audf = data
            mode = self.audctl & 0x28
            if mode in (0x00, 0x20):
                ch[3].period_cycles = self.div_cycles * (data + 1)
            elif mode == 0x08:
                ch[3].period_cycles = self.div_cycles * (ch[2].audf + (data << 8) + 1)
            elif mode == 0x28:
                ch[3].period_cycles = ch[2].audf + (data << 8) + 7

        elif reg == 0x07:  # AUDC4
            ch[3].set_audc(self, pokeys, data, cycle)

        elif reg == 0x08:  # AUDCTL
            if data == self.audctl:
                return next_event_cycle
            self.generate_until_cycle(pokeys, cycle)
            self.audctl = data
            self.div_cycles = 114 if (data & 1) != 0 else 28
            # Recalculate periods for channels 0+1
            mode01 = data & 0x50
            if mode01 == 0x00:
                ch[0].period_cycles = self.div_cycles * (ch[0].audf + 1)
                ch[1].period_cycles = self.div_cycles * (ch[1].audf + 1)
            elif mode01 == 0x10:
                ch[0].period_cycles = self.div_cycles << 8
                ch[1].period_cycles = self.div_cycles * (ch[0].audf + (ch[1].audf << 8) + 1)
                self.reload_cycles1 = self.div_cycles * (ch[0].audf + 1)
            elif mode01 == 0x40:
                ch[0].period_cycles = ch[0].audf + 4
                ch[1].period_cycles = self.div_cycles * (ch[1].audf + 1)
            elif mode01 == 0x50:
                ch[0].period_cycles = 256
                ch[1].period_cycles = ch[0].audf + (ch[1].audf << 8) + 7
                self.reload_cycles1 = ch[0].audf + 4
            # Recalculate periods for channels 2+3
            mode23 = data & 0x28
            if mode23 == 0x00:
                ch[2].period_cycles = self.div_cycles * (ch[2].audf + 1)
                ch[3].period_cycles = self.div_cycles * (ch[3].audf + 1)
            elif mode23 == 0x08:
                ch[2].period_cycles = self.div_cycles << 8
                ch[3].period_cycles = self.div_cycles * (ch[2].audf + (ch[3].audf << 8) + 1)
                self.reload_cycles3 = self.div_cycles * (ch[2].audf + 1)
            elif mode23 == 0x20:
                ch[2].period_cycles = ch[2].audf + 4
                ch[3].period_cycles = self.div_cycles * (ch[3].audf + 1)
            elif mode23 == 0x28:
                ch[2].period_cycles = 256
                ch[3].period_cycles = ch[2].audf + (ch[3].audf << 8) + 7
                self.reload_cycles3 = ch[2].audf + 4
            self._init_mute(cycle)

        elif reg == 0x09:  # STIMER
            self.generate_until_cycle(pokeys, cycle)
            ch[0].do_stimer(self, pokeys, cycle,
                            ch[0].period_cycles if (self.audctl & 0x10) == 0
                            else self.reload_cycles1)
            ch[1].do_stimer(self, pokeys, cycle, ch[1].period_cycles)
            ch[2].do_stimer(self, pokeys, cycle,
                            ch[2].period_cycles if (self.audctl & 8) == 0
                            else self.reload_cycles3)
            ch[3].do_stimer(self, pokeys, cycle, ch[3].period_cycles)

        elif reg == 0x0E:  # IRQEN
            self.irqst |= data ^ 0xFF
            i = 3
            while True:
                if (data & self.irqst & (i + 1)) != 0:
                    if ch[i].timer_cycle == NEVER_CYCLE:
                        t = ch[i].tick_cycle
                        while t < cycle:
                            t += ch[i].period_cycles
                        ch[i].timer_cycle = t
                        if next_event_cycle > t:
                            next_event_cycle = t
                else:
                    ch[i].timer_cycle = NEVER_CYCLE
                if i == 0:
                    break
                i >>= 1

        elif reg == 0x0F:  # SKCTL
            if data == self.skctl:
                return next_event_cycle
            self.generate_until_cycle(pokeys, cycle)
            self.skctl = data
            is_init = (data & 3) == 0
            if self.init and not is_init:
                if (self.audctl & 0x80) != 0:
                    self.poly_index = 15 * 31 * 511 - 1 - cycle
                else:
                    self.poly_index = 15 * 31 * 131071 - 1 - cycle
            self.init = is_init
            self._init_mute(cycle)
            ch[2].set_mute((data & 0x10) != 0, MUTE_SERIAL_INPUT, cycle)
            ch[3].set_mute((data & 0x10) != 0, MUTE_SERIAL_INPUT, cycle)

        return next_event_cycle

    def check_irq(self, cycle, next_event_cycle):
        """Check and fire timer IRQs. Returns updated next_event_cycle."""
        i = 3
        while True:
            timer_cycle = self.channels[i].timer_cycle
            if cycle >= timer_cycle:
                self.irqst &= ~(i + 1)
                self.channels[i].timer_cycle = NEVER_CYCLE
            elif next_event_cycle > timer_cycle:
                next_event_cycle = timer_cycle
            if i == 0:
                break
            i >>= 1
        return next_event_cycle

    def store_sample(self, i):
        """Extract one PCM sample from delta buffer through IIR filter.
        Returns signed 16-bit sample value."""
        self.iir_acc += self.delta_buffer[i] - (self.iir_rate * self.iir_acc >> 11)
        sample = self.iir_acc >> 11
        if sample < -32767:
            sample = -32767
        elif sample > 32767:
            sample = 32767
        return sample

    def accumulate_trailing(self, i):
        self.trailing = i


# ============================================================================
# PokeyPair
# ============================================================================

# ============================================================================
# Cached Lookup Tables (computed once, shared by all PokeyPair instances)
# ============================================================================

_cached_poly9 = None
_cached_poly17 = None
_cached_sinc = None


def _build_poly9():
    poly9 = bytearray(511)
    reg = 0x1FF
    for i in range(511):
        reg = (((reg >> 5 ^ reg) & 1) << 8) + (reg >> 1)
        poly9[i] = reg & 0xFF
    return poly9


def _build_poly17():
    poly17 = bytearray(16385)
    reg = 0x1FFFF
    for i in range(16385):
        reg = (((reg >> 5 ^ reg) & 0xFF) << 9) + (reg >> 8)
        poly17[i] = (reg >> 1) & 0xFF
    return poly17


def _build_sinc():
    sinc_lookup = [[0] * UNIT_DELTA_LENGTH
                    for _ in range(1 << INTERPOLATION_SHIFT)]
    for i in range(1 << INTERPOLATION_SHIFT):
        sinc_sum = 0.0
        left_sum = 0.0
        norm = 0.0
        sinc = [0.0] * (UNIT_DELTA_LENGTH - 1)
        for j in range(-UNIT_DELTA_LENGTH, UNIT_DELTA_LENGTH):
            if j == -UNIT_DELTA_LENGTH // 2:
                left_sum = sinc_sum
            elif j == UNIT_DELTA_LENGTH // 2 - 1:
                norm = sinc_sum
            x = (math.pi / (1 << INTERPOLATION_SHIFT)
                 * ((j << INTERPOLATION_SHIFT) - i))
            s = 1.0 if x == 0.0 else math.sin(x) / x
            if -UNIT_DELTA_LENGTH // 2 <= j < UNIT_DELTA_LENGTH // 2 - 1:
                sinc[UNIT_DELTA_LENGTH // 2 + j] = s
            sinc_sum += s
        norm = (1 << DELTA_RESOLUTION) / (norm + (1 - sinc_sum) * 0.5)
        sinc_lookup[i][0] = round(
            (left_sum + (1 - sinc_sum) * 0.5) * norm)
        for j in range(1, UNIT_DELTA_LENGTH):
            sinc_lookup[i][j] = round(sinc[j - 1] * norm)
    return sinc_lookup


def _get_cached_tables():
    """Return (poly9, poly17, sinc_lookup), computing on first call."""
    global _cached_poly9, _cached_poly17, _cached_sinc
    if _cached_sinc is None:
        _cached_poly9 = _build_poly9()
        _cached_poly17 = _build_poly17()
        _cached_sinc = _build_sinc()
    return _cached_poly9, _cached_poly17, _cached_sinc


# ============================================================================
# PokeyPair
# ============================================================================

class PokeyPair:
    """Stereo POKEY pair with polynomial lookup tables, sinc precomputation,
    and PCM sample generation."""

    __slots__ = (
        'poly9_lookup', 'poly17_lookup', 'extra_pokey_mask',
        'base_pokey', 'extra_pokey',
        'sample_rate', 'sinc_lookup', 'sample_factor', 'sample_offset',
        'ready_samples_start', 'ready_samples_end',
    )

    def __init__(self):
        # Use cached lookup tables (computed once across all instances)
        poly9, poly17, sinc = _get_cached_tables()
        self.poly9_lookup = poly9
        self.poly17_lookup = poly17
        self.sinc_lookup = sinc

        self.extra_pokey_mask = 0
        self.base_pokey = Pokey()
        self.extra_pokey = Pokey()
        self.sample_rate = 44100
        self.sample_factor = 0
        self.sample_offset = 0
        self.ready_samples_start = 0
        self.ready_samples_end = 0

    def _get_sample_factor(self, clock):
        return (
            ((self.sample_rate << (SAMPLE_FACTOR_SHIFT - 5))
             + (clock >> 6))
            // (clock >> 5)
        )

    def initialize(self, ntsc=False, stereo=False, sample_rate=44100):
        """Initialize emulator for playback.

        Args:
            ntsc: True for NTSC clock, False for PAL.
            stereo: True for dual POKEY (stereo).
            sample_rate: Output PCM sample rate.
        """
        self.extra_pokey_mask = 0x10 if stereo else 0
        self.sample_rate = sample_rate
        self.base_pokey.initialize(sample_rate, apokeysnd=True)
        self.extra_pokey.initialize(sample_rate, apokeysnd=True)
        clock = NTSC_CLOCK if ntsc else PAL_CLOCK
        self.sample_factor = self._get_sample_factor(clock)
        self.sample_offset = 0
        self.ready_samples_start = 0
        self.ready_samples_end = 0

    def poke(self, addr, data, cycle):
        """Write a POKEY register. Routes to base or extra POKEY."""
        if (addr & self.extra_pokey_mask) != 0:
            pokey = self.extra_pokey
        else:
            pokey = self.base_pokey
        return pokey.poke(self, addr, data, cycle)

    def peek(self, addr, cycle):
        """Read a POKEY register."""
        if (addr & self.extra_pokey_mask) != 0:
            pokey = self.extra_pokey
        else:
            pokey = self.base_pokey
        reg = addr & 0xF
        if reg == 0x0A:  # RANDOM
            if pokey.init:
                return 0xFF
            i = cycle + pokey.poly_index
            if (pokey.audctl & 0x80) != 0:
                return self.poly9_lookup[i % 511]
            i %= 131071
            j = i >> 3
            bit = i & 7
            return ((self.poly17_lookup[j] >> bit)
                    + (self.poly17_lookup[j + 1] << (8 - bit))) & 0xFF
        elif reg == 0x0E:  # IRQST
            return pokey.irqst
        return 0xFF

    def start_frame(self):
        self.base_pokey.start_frame()
        if self.extra_pokey_mask != 0:
            self.extra_pokey.start_frame()

    def end_frame(self, cycle):
        """End frame. Returns number of ready samples."""
        self.base_pokey.end_frame(self, cycle)
        if self.extra_pokey_mask != 0:
            self.extra_pokey.end_frame(self, cycle)
        self.sample_offset += cycle * self.sample_factor
        self.ready_samples_start = 0
        self.ready_samples_end = self.sample_offset >> SAMPLE_FACTOR_SHIFT
        self.sample_offset &= (1 << SAMPLE_FACTOR_SHIFT) - 1
        return self.ready_samples_end

    def generate(self, num_samples=-1):
        """Generate PCM samples as a list of signed 16-bit values.

        Args:
            num_samples: Max samples to generate. -1 = all ready samples.

        Returns:
            List of signed 16-bit integers (mono, or interleaved stereo).
        """
        i = self.ready_samples_start
        samples_end = self.ready_samples_end
        if num_samples >= 0 and num_samples < samples_end - i:
            samples_end = i + num_samples
        else:
            num_samples = samples_end - i

        result = []
        if num_samples > 0:
            while i < samples_end:
                result.append(self.base_pokey.store_sample(i))
                if self.extra_pokey_mask != 0:
                    result.append(self.extra_pokey.store_sample(i))
                i += 1
            if i == self.ready_samples_end:
                self.base_pokey.accumulate_trailing(i)
                self.extra_pokey.accumulate_trailing(i)
            self.ready_samples_start = i
        return result

    def is_silent(self):
        return self.base_pokey.is_silent() and self.extra_pokey.is_silent()
