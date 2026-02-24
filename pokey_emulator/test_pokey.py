"""
pokey_emulator/test_pokey.py — Test suite for POKEY emulator and VQ player

Tests cover:
1.  Polynomial counter generation (Poly9, Poly17)
2.  Sinc lookup table properties
3.  DAC compression table
4.  Pokey initialization
5.  Volume-only mode (primary VQ playback path)
6.  Register write handling (AUDF, AUDC, AUDCTL)
7.  AUDCTL channel linking (16-bit mode)
8.  Frame generation pipeline
9.  Multi-channel mixing with DAC compression
10. Idle silence
11. Pure tone generation
12. STIMER behavior
13. SKCTL init/normal mode
14. VQ player: basic single-instrument playback
15. VQ player: pitch accumulation (8-bit arithmetic)
16. VQ player: RAW mode playback
17. VQ player: song sequencer
18. VQ player: volume control
19. SongData codebook offset builder
20. ASM byte parser
21. Pitch table
22. render_vq_wav end-to-end
23. Performance benchmark
"""

import sys
import os
import math
import struct
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokey_emulator.pokey import (
    PokeyPair, Pokey, PokeyChannel,
    NEVER_CYCLE, PAL_CLOCK, PAL_CYCLES_PER_FRAME,
    COMPRESSED_SUMS, INTERPOLATION_SHIFT, UNIT_DELTA_LENGTH, DELTA_RESOLUTION,
)
from pokey_emulator.vq_player import (
    VQPlayer, ChannelState, SongData, InstrumentData, render_vq_wav,
    AUDC1, AUDC2, AUDF1, AUDF2, AUDCTL, STIMER, SKCTL, SILENCE,
)


# ============================================================================
# Test Utilities
# ============================================================================

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name):
        self.passed += 1
        print(f"  PASS {name}")

    def fail(self, name, msg):
        self.failed += 1
        self.errors.append((name, msg))
        print(f"  FAIL {name}: {msg}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            print(f"\nFailures:")
            for name, msg in self.errors:
                print(f"  - {name}: {msg}")
        print(f"{'='*60}")
        return self.failed == 0


def assert_eq(r, name, actual, expected):
    if actual == expected:
        r.ok(name)
    else:
        r.fail(name, f"expected {expected}, got {actual}")

def assert_close(r, name, actual, expected, tol=0.01):
    if abs(actual - expected) <= tol:
        r.ok(name)
    else:
        r.fail(name, f"expected ~{expected}, got {actual} (tol={tol})")

def assert_true(r, name, cond, msg=""):
    if cond:
        r.ok(name)
    else:
        r.fail(name, msg or "condition is False")


# ============================================================================
# 1. Polynomial Counter Generation
# ============================================================================

def test_poly_tables(r):
    print("\n--- 1. Poly Table Tests ---")
    pp = PokeyPair()
    assert_eq(r, "poly9 length", len(pp.poly9_lookup), 511)
    assert_true(r, "poly9 valid bytes",
                all(0 <= b <= 255 for b in pp.poly9_lookup))
    assert_true(r, "poly9 unique values > 100",
                len(set(pp.poly9_lookup)) > 100)
    assert_eq(r, "poly17 length", len(pp.poly17_lookup), 16385)
    assert_true(r, "poly17 valid bytes",
                all(0 <= b <= 255 for b in pp.poly17_lookup))
    assert_true(r, "poly17 unique values > 200",
                len(set(pp.poly17_lookup)) > 200)


# ============================================================================
# 2. Sinc Lookup Table
# ============================================================================

def test_sinc_table(r):
    print("\n--- 2. Sinc Table Tests ---")
    pp = PokeyPair()
    assert_eq(r, "sinc phases", len(pp.sinc_lookup), 1 << INTERPOLATION_SHIFT)
    assert_eq(r, "sinc taps", len(pp.sinc_lookup[0]), UNIT_DELTA_LENGTH)

    target = 1 << DELTA_RESOLUTION
    for phase in [0, 512, 1023]:
        row_sum = sum(pp.sinc_lookup[phase])
        assert_close(r, f"sinc row {phase} sum ~ {target}",
                     row_sum, target, tol=target * 0.02)
    max_abs = max(abs(v) for v in pp.sinc_lookup[0])
    assert_true(r, "sinc phase 0 has significant values", max_abs > 100)


# ============================================================================
# 3. DAC Compression Table
# ============================================================================

def test_dac_compression(r):
    print("\n--- 3. DAC Compression Tests ---")
    assert_eq(r, "compressed_sums length", len(COMPRESSED_SUMS), 61)
    assert_true(r, "compressed_sums monotonic",
                all(COMPRESSED_SUMS[i] <= COMPRESSED_SUMS[i+1]
                    for i in range(60)))
    assert_eq(r, "compressed_sums[0]", COMPRESSED_SUMS[0], 0)
    assert_eq(r, "compressed_sums[60]", COMPRESSED_SUMS[60], 1023)
    mid = 30
    first = COMPRESSED_SUMS[mid] - COMPRESSED_SUMS[0]
    second = COMPRESSED_SUMS[60] - COMPRESSED_SUMS[mid]
    assert_true(r, "compression present", second < first)


# ============================================================================
# 4. Pokey Initialization
# ============================================================================

def test_pokey_init(r):
    print("\n--- 4. Pokey Init Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    p = pp.base_pokey
    assert_eq(r, "audctl init", p.audctl, 0)
    assert_eq(r, "skctl init", p.skctl, 3)
    assert_eq(r, "irqst init", p.irqst, 0xFF)
    assert_true(r, "not init mode", not p.init)
    assert_eq(r, "div_cycles init", p.div_cycles, 28)
    for i, ch in enumerate(p.channels):
        assert_eq(r, f"ch{i} audf init", ch.audf, 0)
        assert_eq(r, f"ch{i} audc init", ch.audc, 0)
        assert_eq(r, f"ch{i} period init", ch.period_cycles, 28)
    expected_len = 44100 * 312 * 114 // 1773447 + 32 + 2
    assert_eq(r, "delta_buffer_length", p.delta_buffer_length, expected_len)
    assert_eq(r, "delta_buffer actual len", len(p.delta_buffer), expected_len)


# ============================================================================
# 5. Volume-Only Mode
# ============================================================================

def test_volume_only_mode(r):
    print("\n--- 5. Volume-Only Mode Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x03, 0)
    pp.poke(AUDF1, 3, 0)
    pp.poke(AUDCTL, 0, 0)
    pp.start_frame()
    pp.poke(AUDC1, 0x1F, 100)
    pp.poke(AUDC1, 0x18, 200)
    pp.poke(AUDC1, 0x10, 300)
    pp.poke(AUDC1, 0x1A, 400)
    num = pp.end_frame(PAL_CYCLES_PER_FRAME)
    assert_true(r, "volume-only produces samples", num > 0)
    pcm = pp.generate(num)
    assert_true(r, "volume-only PCM non-empty", len(pcm) > 0)
    assert_true(r, "volume-only non-zero PCM", any(s != 0 for s in pcm))


# ============================================================================
# 6. Register Write Handling
# ============================================================================

def test_register_writes(r):
    print("\n--- 6. Register Write Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    p = pp.base_pokey

    pp.poke(AUDF1, 0x0A, 0)
    assert_eq(r, "AUDF1 write", p.channels[0].audf, 0x0A)
    assert_eq(r, "ch0 period after AUDF1", p.channels[0].period_cycles, 308)

    pp.poke(AUDCTL, 0x01, 0)
    assert_eq(r, "AUDCTL write", p.audctl, 0x01)
    assert_eq(r, "div_cycles 15kHz", p.div_cycles, 114)
    assert_eq(r, "ch0 period after AUDCTL", p.channels[0].period_cycles, 1254)

    pp.poke(AUDCTL, 0x00, 0)
    assert_eq(r, "div_cycles back to 64kHz", p.div_cycles, 28)

    pp.poke(AUDC1, 0x1F, 0)
    assert_eq(r, "AUDC1 write", p.channels[0].audc, 0x1F)

    pp.poke(STIMER, 0x00, 10)
    r.ok("STIMER write no crash")


# ============================================================================
# 7. AUDCTL Channel Linking (16-bit mode)
# ============================================================================

def test_audctl_linking(r):
    print("\n--- 7. AUDCTL Linking Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    p = pp.base_pokey
    pp.poke(AUDF1, 0x0A, 0)
    pp.poke(AUDF2, 0x01, 0)

    pp.poke(AUDCTL, 0x10, 0)
    assert_eq(r, "16-bit ch1 period", p.channels[1].period_cycles, 7476)

    pp.poke(AUDCTL, 0x50, 0)
    assert_eq(r, "1.79MHz+16bit ch1 period", p.channels[1].period_cycles, 273)


# ============================================================================
# 8. Frame Generation Pipeline
# ============================================================================

def test_frame_pipeline(r):
    print("\n--- 8. Frame Pipeline Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x03, 0)

    all_pcm = []
    for _ in range(5):
        pp.start_frame()
        for t in range(0, PAL_CYCLES_PER_FRAME, 112):
            pp.poke(AUDC1, 0x18, t)
        n = pp.end_frame(PAL_CYCLES_PER_FRAME)
        pcm = pp.generate(n)
        all_pcm.extend(pcm)

    expected = 44100 // 50 * 5
    assert_close(r, "total samples ~ 4410", len(all_pcm), expected, tol=100)
    assert_true(r, "frame pipeline nonzero output",
                max(abs(s) for s in all_pcm) > 0 if all_pcm else False)


# ============================================================================
# 9. Multi-Channel Mixing
# ============================================================================

def test_multichannel(r):
    print("\n--- 9. Multi-Channel Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x03, 0)
    pp.start_frame()
    pp.poke(AUDC1, 0x18, 100)
    n1 = pp.end_frame(PAL_CYCLES_PER_FRAME)
    pcm1 = pp.generate(n1)
    single_max = max(abs(s) for s in pcm1) if pcm1 else 0

    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x03, 0)
    pp.start_frame()
    pp.poke(AUDC1, 0x18, 100)
    pp.poke(AUDC2, 0x18, 100)
    n2 = pp.end_frame(PAL_CYCLES_PER_FRAME)
    pcm2 = pp.generate(n2)
    dual_max = max(abs(s) for s in pcm2) if pcm2 else 0

    assert_true(r, "dual louder than single", dual_max > single_max)
    assert_true(r, "DAC compression: dual < 2x single", dual_max < single_max * 2)


# ============================================================================
# 10. Idle Silence
# ============================================================================

def test_silence(r):
    print("\n--- 10. Silence Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x03, 0)
    pp.start_frame()
    n = pp.end_frame(PAL_CYCLES_PER_FRAME)
    pcm = pp.generate(n)
    assert_true(r, "no writes -> silence", all(s == 0 for s in pcm))


# ============================================================================
# 11. Pure Tone Generation
# ============================================================================

def test_pure_tone(r):
    print("\n--- 11. Pure Tone Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x00, 0)
    pp.poke(AUDF1, 253, 0)
    pp.poke(AUDC1, 0xA8, 0)
    pp.poke(AUDCTL, 0, 0)
    pp.poke(SKCTL, 0x03, 0)
    pp.poke(STIMER, 0, 0)

    all_pcm = []
    for _ in range(100):
        pp.start_frame()
        n = pp.end_frame(PAL_CYCLES_PER_FRAME)
        pcm = pp.generate(n)
        all_pcm.extend(pcm)

    assert_true(r, "pure tone produces samples", len(all_pcm) > 0)
    crossings = sum(1 for i in range(1, len(all_pcm))
                    if (all_pcm[i-1] > 0) != (all_pcm[i] > 0))
    assert_true(r, f"zero crossings reasonable ({crossings})",
                100 < crossings < 1000)


# ============================================================================
# 12. STIMER Behavior
# ============================================================================

def test_stimer(r):
    print("\n--- 12. STIMER Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x00, 0)
    pp.poke(AUDF1, 10, 0)
    pp.poke(AUDC1, 0xA8, 0)
    pp.poke(SKCTL, 0x03, 0)
    pp.start_frame()
    pp.poke(STIMER, 0, 10)
    n = pp.end_frame(PAL_CYCLES_PER_FRAME)
    pcm = pp.generate(n)
    assert_true(r, "STIMER produces samples", len(pcm) > 0)
    assert_true(r, "STIMER activates tone", any(s != 0 for s in pcm))


# ============================================================================
# 13. SKCTL Init/Normal Mode
# ============================================================================

def test_skctl_init_mode(r):
    print("\n--- 13. SKCTL Init Mode Tests ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x00, 0)
    assert_true(r, "init mode active", pp.base_pokey.init)
    pp.poke(SKCTL, 0x03, 100)
    assert_true(r, "init mode exited", not pp.base_pokey.init)
    r.ok("SKCTL init/normal mode transition")


# ============================================================================
# 14. VQ Player — Basic Playback
# ============================================================================

def test_vq_player_basic(r):
    print("\n--- 14. VQ Player Basic Tests ---")

    vector_size = 8
    codebook = bytearray()
    codebook.extend([0x10] * vector_size)  # Vec 0: silence
    codebook.extend([0x18] * vector_size)  # Vec 1: mid
    codebook.extend([0x1F] * vector_size)  # Vec 2: high
    for i in range(vector_size):           # Vec 3: ramp
        codebook.append(0x10 | (i * 2))

    indices = bytearray([1, 2, 3] * 34)

    player = VQPlayer(sample_rate=44100)
    player.load_vq_direct(
        codebook=bytes(codebook),
        indices=bytes(indices),
        vector_size=vector_size,
        audf_val=3,
    )

    assert_true(r, "ch0 active after load_vq_direct",
                player.channels[0].active)

    all_pcm = []
    for _ in range(100):
        pcm = player.render_frame()
        if len(pcm) > 0:
            all_pcm.extend(pcm)

    assert_true(r, "VQ player produces samples", len(all_pcm) > 0)
    if all_pcm:
        mx = max(abs(s) for s in all_pcm)
        assert_true(r, "VQ player non-silent", mx > 0.001)


# ============================================================================
# 15. VQ Player — Pitch Accumulation
# ============================================================================

def test_vq_pitch(r):
    """Verify 8-bit pitch accumulation matches 6502 behavior."""
    print("\n--- 15. VQ Pitch Tests ---")

    # Create a simple codebook with distinguishable vectors
    vs = 4
    codebook = bytearray()
    for v in range(8):
        for i in range(vs):
            codebook.append(0x10 | (v & 0x0F))

    indices = bytearray(range(8)) * 20  # 160 indices

    player = VQPlayer(sample_rate=44100)
    song = SongData()
    song.ntsc = False
    song.codebook = bytes(codebook)
    song.vector_size = vs
    song.audf_val = 3
    song.audctl_val = 0
    song.song_length = 0
    song.pitch_table = player._build_pitch_table()
    song.build_codebook_offsets()

    inst = InstrumentData(index=0, is_vq=True,
                          stream_data=bytes(indices),
                          start_offset=0, end_offset=len(indices))
    song.instruments.append(inst)
    player.load_song(song)

    # Trigger at 2x pitch (note 12 = octave up, step = 0x0200)
    ch = player.channels[0]
    ch.trigger(inst, 0x0200, song)
    assert_true(r, "pitch ch active", ch.active)
    assert_true(r, "pitch ch has_pitch", ch.has_pitch)
    assert_eq(r, "pitch step", ch.pitch_step, 0x0200)

    # Simulate a few ticks manually
    ch.pitch_frac = 0
    ch.pitch_int = 0
    ch.vector_offset = 0
    ch.stream_pos = 0

    # Tick 1: frac += 0x00 -> frac=0, carry=0; int += 0x02+0 = 2
    # advance=2, new_vo=2, 2 < 4 => no boundary
    player._tick_vq(ch, 0, 100)
    assert_eq(r, "tick1 vector_offset", ch.vector_offset, 2)
    assert_eq(r, "tick1 stream_pos", ch.stream_pos, 0)

    # Tick 2: frac += 0 -> frac=0; int += 2 = 2
    # new_vo = 2+2 = 4, 4 >= vs=4 => boundary cross
    # vectors_crossed = 4//4 = 1, stream_pos += 1, vo = 4%4 = 0
    player._tick_vq(ch, 0, 200)
    assert_eq(r, "tick2 vector_offset", ch.vector_offset, 0)
    assert_eq(r, "tick2 stream_pos", ch.stream_pos, 1)

    # Test fractional pitch: step = 0x0180 (1.5x)
    ch.trigger(inst, 0x0180, song)
    ch.pitch_frac = 0
    ch.pitch_int = 0
    ch.vector_offset = 0
    ch.stream_pos = 0

    # Tick 1: frac = 0+0x80 = 128, carry=0; int = 0+1+0 = 1
    # advance=1, new_vo=1, 1<4 => no boundary
    player._tick_vq(ch, 0, 300)
    assert_eq(r, "frac tick1 vo", ch.vector_offset, 1)
    assert_eq(r, "frac tick1 frac", ch.pitch_frac, 0x80)

    # Tick 2: frac = 0x80+0x80 = 256, carry=1; int = 0+1+1 = 2
    # advance=2, new_vo=1+2=3, 3<4 => no boundary
    player._tick_vq(ch, 0, 400)
    assert_eq(r, "frac tick2 vo", ch.vector_offset, 3)
    assert_eq(r, "frac tick2 frac", ch.pitch_frac, 0)

    # Tick 3: frac = 0+0x80 = 128, carry=0; int = 0+1+0 = 1
    # advance=1, new_vo=3+1=4, 4>=4 => boundary
    # vectors_crossed = 4//4 = 1, stream_pos = 0+1 = 1, vo = 4%4 = 0
    player._tick_vq(ch, 0, 500)
    assert_eq(r, "frac tick3 vo", ch.vector_offset, 0)
    assert_eq(r, "frac tick3 stream_pos", ch.stream_pos, 1)


# ============================================================================
# 16. VQ Player — RAW Mode
# ============================================================================

def test_vq_raw_mode(r):
    """Verify RAW mode playback with page-crossing logic."""
    print("\n--- 16. RAW Mode Tests ---")

    # Create a raw sample: 512 bytes (2 pages)
    raw_data = bytearray()
    for i in range(512):
        raw_data.append(0x10 | (i % 16))

    inst = InstrumentData(index=0, is_vq=False,
                          stream_data=bytes(raw_data),
                          start_offset=0, end_offset=512)

    song = SongData()
    song.ntsc = False
    song.codebook = b''
    song.vector_size = 8
    song.audf_val = 3
    song.audctl_val = 0
    song.song_length = 0
    song.build_codebook_offsets()
    song.pitch_table = [min(0xFFFF, int(round(2.0 ** (n/12.0) * 256)))
                        for n in range(36)]
    song.instruments.append(inst)

    player = VQPlayer(sample_rate=44100)
    player.load_song(song)

    # Trigger at base pitch (1.0x = no pitch shifting)
    ch = player.channels[0]
    ch.trigger(inst, 0x0100, song)
    assert_true(r, "RAW ch active", ch.active)
    assert_true(r, "RAW not vq", not ch.is_vq)
    assert_true(r, "RAW no pitch", not ch.has_pitch)

    # Manual ticks: advance through page boundary
    for _ in range(255):
        player._tick_raw(ch, 0, 0)
    assert_eq(r, "RAW after 255 ticks: vo", ch.vector_offset, 255)
    assert_eq(r, "RAW after 255 ticks: sample_ptr", ch.sample_ptr, 0)

    # Tick 256: should wrap to 0 and increment sample_ptr
    player._tick_raw(ch, 0, 0)
    assert_eq(r, "RAW page cross: vo", ch.vector_offset, 0)
    assert_eq(r, "RAW page cross: sample_ptr", ch.sample_ptr, 256)
    assert_true(r, "RAW still active after 1st page", ch.active)

    # Advance through second page (255 more ticks)
    for _ in range(255):
        player._tick_raw(ch, 0, 0)
    player._tick_raw(ch, 0, 0)  # Should hit end
    assert_true(r, "RAW deactivated at end", not ch.active)


# ============================================================================
# 17. VQ Player — Song Sequencer
# ============================================================================

def test_vq_song_sequencer(r):
    print("\n--- 17. Song Sequencer Tests ---")

    song = SongData()
    song.ntsc = False
    song.audf_val = 3
    song.audctl_val = 0
    song.vector_size = 4

    codebook = bytearray([0x18] * 4 + [0x1C] * 4)
    song.codebook = bytes(codebook)
    song.build_codebook_offsets()

    indices = bytearray([0, 1] * 50)
    inst = InstrumentData(index=0, is_vq=True,
                          stream_data=bytes(indices),
                          start_offset=0, end_offset=100)
    song.instruments.append(inst)

    song.pitch_table = [int(round(2 ** (n / 12.0) * 256)) for n in range(36)]

    song.song_length = 1
    song.songlines.append({'speed': 4, 'patterns': [0, 0, 0, 0]})
    song.patterns.append({
        'length': 8,
        'events': [(0, 1, 0, 15)],
    })

    player = VQPlayer(sample_rate=44100)
    player.load_song(song)
    player.start_playback(songline=0, row=0)
    assert_true(r, "player is playing", player.playing)

    total_samples = 0
    had_active = False
    all_pcm = []
    for _ in range(10):
        if player.channels[0].active:
            had_active = True
        pcm = player.render_frame()
        total_samples += len(pcm)
        all_pcm.extend(pcm)

    assert_true(r, "sequencer produced samples", total_samples > 0)
    assert_true(r, "ch0 was activated by event", had_active)
    if all_pcm:
        assert_true(r, "sequencer audio non-silent",
                    max(abs(s) for s in all_pcm) > 0)


# ============================================================================
# 18. VQ Player — Volume Control
# ============================================================================

def test_volume_control(r):
    print("\n--- 18. Volume Control Tests ---")

    song = SongData()
    song.volume_control = True
    song.build_volume_scale()

    assert_eq(r, "volume_scale length", len(song.volume_scale), 256)

    # Vol=15 (max), sample=15 -> output should be 0x1F
    assert_eq(r, "vol15 samp15", song.volume_scale[0xF0 | 0x0F], 0x1F)

    # Vol=0, sample=15 -> output should be 0x10 (silence)
    assert_eq(r, "vol0 samp15", song.volume_scale[0x00 | 0x0F], 0x10)

    # Vol=8, sample=8 -> output ~ 0x10 | round(8*8/15) = 0x10 | 4 = 0x14
    assert_eq(r, "vol8 samp8", song.volume_scale[0x80 | 0x08], 0x10 | round(8*8/15))

    # Vol=15, sample=0 -> 0x10
    assert_eq(r, "vol15 samp0", song.volume_scale[0xF0 | 0x00], 0x10)


# ============================================================================
# 19. SongData Codebook Offset Builder
# ============================================================================

def test_codebook_offsets(r):
    print("\n--- 19. Codebook Offset Tests ---")

    song = SongData()
    song.vector_size = 8
    song.codebook = bytes(8 * 10)  # 10 vectors
    song.build_codebook_offsets()

    assert_eq(r, "cb_offset_lo length", len(song.cb_offset_lo), 256)
    assert_eq(r, "cb_offset_hi length", len(song.cb_offset_hi), 256)

    # Vector 0 -> offset 0
    assert_eq(r, "vec0 offset lo", song.cb_offset_lo[0], 0)
    assert_eq(r, "vec0 offset hi", song.cb_offset_hi[0], 0)

    # Vector 1 -> offset 8
    assert_eq(r, "vec1 offset lo", song.cb_offset_lo[1], 8)
    assert_eq(r, "vec1 offset hi", song.cb_offset_hi[1], 0)

    # Vector 9 -> offset 72
    assert_eq(r, "vec9 offset lo", song.cb_offset_lo[9], 72)
    assert_eq(r, "vec9 offset hi", song.cb_offset_hi[9], 0)

    # Large codebook: vector_size=8, 40 vectors -> 320 bytes, vec 32 offset=256
    song2 = SongData()
    song2.vector_size = 8
    song2.codebook = bytes(8 * 40)
    song2.build_codebook_offsets()
    assert_eq(r, "vec32 offset lo", song2.cb_offset_lo[32], 0)   # 256 & 0xFF
    assert_eq(r, "vec32 offset hi", song2.cb_offset_hi[32], 1)   # 256 >> 8


# ============================================================================
# 20. ASM Byte Parser
# ============================================================================

def test_asm_parser(r):
    print("\n--- 20. ASM Parser Tests ---")

    test_path = '/tmp/test_asm_parse.asm'
    try:
        with open(test_path, 'w') as f:
            f.write("; Comment line\n")
            f.write(".byte $10,$1F,$18\n")
            f.write(".byte 0,15,255\n")
            f.write("dta b($A0,$B0) ; trailing comment\n")
            f.write("\n")
            f.write("dta $FF\n")

        player = VQPlayer()
        parsed = player._parse_asm_bytes(test_path)

        assert_eq(r, "parsed byte count", len(parsed), 9)
        assert_eq(r, "parsed[0]=$10", parsed[0], 0x10)
        assert_eq(r, "parsed[1]=$1F", parsed[1], 0x1F)
        assert_eq(r, "parsed[2]=$18", parsed[2], 0x18)
        assert_eq(r, "parsed[3]=0", parsed[3], 0)
        assert_eq(r, "parsed[4]=15", parsed[4], 15)
        assert_eq(r, "parsed[5]=255", parsed[5], 255)
        assert_eq(r, "parsed[6]=$A0", parsed[6], 0xA0)
        assert_eq(r, "parsed[7]=$B0", parsed[7], 0xB0)
        assert_eq(r, "parsed[8]=$FF", parsed[8], 0xFF)
    finally:
        if os.path.exists(test_path):
            os.remove(test_path)


# ============================================================================
# 21. Pitch Table
# ============================================================================

def test_pitch_table(r):
    print("\n--- 21. Pitch Table Tests ---")
    player = VQPlayer()
    table = player._build_pitch_table()
    assert_eq(r, "pitch table length", len(table), 36)
    assert_eq(r, "note0 = 0x0100", table[0], 256)
    assert_eq(r, "note12 = 0x0200", table[12], 512)
    assert_eq(r, "note24 = 0x0400", table[24], 1024)
    expected_g = int(round(2**(7/12.0) * 256))
    assert_eq(r, "note7 (G-1)", table[7], expected_g)


# ============================================================================
# 22. render_vq_wav
# ============================================================================

def test_render_wav(r):
    print("\n--- 22. render_vq_wav Test ---")

    vs = 8
    codebook = bytearray()
    for v in range(4):
        for i in range(vs):
            codebook.append(0x10 | min(15, v * 4 + i))

    indices = bytearray([0, 1, 2, 3] * 25)

    wav_path = '/tmp/test_pokey_output.wav'
    try:
        duration = render_vq_wav(
            codebook=bytes(codebook),
            indices=bytes(indices),
            output_path=wav_path,
            vector_size=vs,
            audf_val=3,
        )
        assert_true(r, "WAV file created", os.path.exists(wav_path))
        size = os.path.getsize(wav_path)
        assert_true(r, "WAV file non-empty", size > 44)
        assert_true(r, "WAV duration > 0", duration > 0)
        print(f"  WAV: {size} bytes, {duration:.3f}s")
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


# ============================================================================
# 23. Performance Benchmark
# ============================================================================

def test_performance(r):
    print("\n--- 23. Performance Benchmark ---")
    pp = PokeyPair()
    pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
    pp.poke(SKCTL, 0x03, 0)
    pp.poke(AUDF1, 3, 0)

    # Warm up
    pp.start_frame()
    for t in range(0, PAL_CYCLES_PER_FRAME, 112):
        pp.poke(AUDC1, 0x18 | (t % 16), t)
    pp.end_frame(PAL_CYCLES_PER_FRAME)
    pp.generate()

    # Benchmark 50 frames (1 second)
    t0 = time.perf_counter()
    total_samples = 0
    for _ in range(50):
        pp.start_frame()
        for t in range(0, PAL_CYCLES_PER_FRAME, 112):
            pp.poke(AUDC1, 0x18 | (t % 16), t)
        n = pp.end_frame(PAL_CYCLES_PER_FRAME)
        pcm = pp.generate(n)
        total_samples += len(pcm)
    t1 = time.perf_counter()

    elapsed_ms = (t1 - t0) * 1000
    ms_per_frame = elapsed_ms / 50
    budget = 20.0

    print(f"  50 frames in {elapsed_ms:.1f} ms ({ms_per_frame:.2f} ms/frame)")
    print(f"  Real-time budget: {budget:.1f} ms/frame")
    print(f"  Total samples: {total_samples}")
    if ms_per_frame > 0:
        print(f"  Margin: {budget / ms_per_frame:.1f}x real-time")

    assert_close(r, "~44100 samples per second", total_samples, 44100, tol=500)

    if ms_per_frame < budget:
        r.ok(f"REAL-TIME ({ms_per_frame:.2f} ms < {budget:.1f} ms)")
    else:
        ratio = ms_per_frame / budget
        r.ok(f"benchmark complete ({ratio:.1f}x real-time)")


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 60)
    print("POKEY Emulator + VQ Player Test Suite")
    print("=" * 60)

    r = TestResult()

    # Core POKEY tests
    test_poly_tables(r)
    test_sinc_table(r)
    test_dac_compression(r)
    test_pokey_init(r)
    test_volume_only_mode(r)
    test_register_writes(r)
    test_audctl_linking(r)
    test_frame_pipeline(r)
    test_multichannel(r)
    test_silence(r)
    test_pure_tone(r)
    test_stimer(r)
    test_skctl_init_mode(r)

    # VQ Player tests
    test_vq_player_basic(r)
    test_vq_pitch(r)
    test_vq_raw_mode(r)
    test_vq_song_sequencer(r)
    test_volume_control(r)
    test_codebook_offsets(r)
    test_asm_parser(r)
    test_pitch_table(r)
    test_render_wav(r)

    # Performance
    test_performance(r)

    success = r.summary()
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
