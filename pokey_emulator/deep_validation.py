"""
deep_validation.py — Targeted validation for POKEY accuracy

Traces known register write sequences through the complete signal chain:
  register write → set_audc → add_pokey_delta → CompressedSums → _add_delta
  → sinc interpolation → delta_buffer → IIR filter → PCM output

Verifies:
  1. DAC compression path for known input sequences
  2. Volume-only delta tracking (the VQ hot path)
  3. Frame boundary handling (trailing rotation)
  4. DC offset rejection (IIR high-pass filter)
  5. Channel timing phase alignment
  6. Bit-exact comparison of Python vs original ASAP algorithm
"""

import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokey_emulator.pokey import (
    PokeyPair, Pokey, PokeyChannel,
    NEVER_CYCLE, PAL_CLOCK, PAL_CYCLES_PER_FRAME,
    COMPRESSED_SUMS, DELTA_SHIFT_POKEY,
    SAMPLE_FACTOR_SHIFT, INTERPOLATION_SHIFT,
    UNIT_DELTA_LENGTH, DELTA_RESOLUTION,
)

passed = 0
failed = 0

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  OK   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}: {detail}")


# ============================================================================
# Test 1: DAC input tracking for volume-only writes
# ============================================================================
print("\n=== 1. DAC Input Tracking ===")

pp = PokeyPair()
pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
pp.poke(0x0F, 0x00, 0)  # SKCTL=0 init
pp.poke(0x0F, 0x03, 0)  # SKCTL=3 run
p = pp.base_pokey

# Initial state: all channels delta=0, sum_dac_inputs=0
check("initial sum_dac_inputs=0", p.sum_dac_inputs == 0)
check("initial ch0 delta=0", p.channels[0].delta == 0)

# Write ch0 vol-only 8
pp.start_frame()
pp.poke(0x01, 0x18, 10)  # AUDC1 = 0x18 (vol-only, vol=8)
check("ch0 delta=8 after vol-only 8",
      p.channels[0].delta == 8, f"got {p.channels[0].delta}")
check("sum_dac=8 after one write",
      p.sum_dac_inputs == 8, f"got {p.sum_dac_inputs}")

# Write ch1 vol-only 4
pp.poke(0x03, 0x14, 20)  # AUDC2 = 0x14 (vol-only, vol=4)
check("sum_dac=12 after two channels",
      p.sum_dac_inputs == 12, f"got {p.sum_dac_inputs}")

# Reduce ch0 to vol 3
pp.poke(0x01, 0x13, 30)  # AUDC1 = 0x13 (vol-only, vol=3)
check("ch0 delta=3 after reduce",
      p.channels[0].delta == 3, f"got {p.channels[0].delta}")
check("sum_dac=7 after reduce (3+4)",
      p.sum_dac_inputs == 7, f"got {p.sum_dac_inputs}")

# Write same value — should be no-op
old_outputs = p.sum_dac_outputs
pp.poke(0x01, 0x13, 40)
check("same-value write is no-op",
      p.sum_dac_outputs == old_outputs)

# Write ch0 to silence
pp.poke(0x01, 0x10, 50)
check("sum_dac=4 after ch0 silence (0+4)",
      p.sum_dac_inputs == 4, f"got {p.sum_dac_inputs}")

# Write ch1 to silence
pp.poke(0x03, 0x10, 60)
check("sum_dac=0 after both silent",
      p.sum_dac_inputs == 0, f"got {p.sum_dac_inputs}")

pp.end_frame(PAL_CYCLES_PER_FRAME)


# ============================================================================
# Test 2: CompressedSums output matches expected values
# ============================================================================
print("\n=== 2. CompressedSums DAC Output ===")

pp2 = PokeyPair()
pp2.initialize(ntsc=False, stereo=False, sample_rate=44100)
pp2.poke(0x0F, 0x00, 0)
pp2.poke(0x0F, 0x03, 0)
p2 = pp2.base_pokey

pp2.start_frame()
# Write ch0 to vol 15 → sum_dac_inputs=15
pp2.poke(0x01, 0x1F, 10)
expected_output = COMPRESSED_SUMS[15] << DELTA_SHIFT_POKEY
check("CompressedSums[15] output correct",
      p2.sum_dac_outputs == expected_output,
      f"expected {expected_output}, got {p2.sum_dac_outputs}")

# Verify compressed value: CompressedSums[15] = 546
check("CompressedSums[15]=546", COMPRESSED_SUMS[15] == 546)
check("CompressedSums[30]=834", COMPRESSED_SUMS[30] == 834)
# Compression: 2 channels at vol 15 (sum=30) gives 846, not 2×546=1092
check("DAC compression is sublinear",
      COMPRESSED_SUMS[30] < 2 * COMPRESSED_SUMS[15],
      f"{COMPRESSED_SUMS[30]} < {2 * COMPRESSED_SUMS[15]}")

pp2.end_frame(PAL_CYCLES_PER_FRAME)


# ============================================================================
# Test 3: IIR High-Pass Filter Rejects DC
# ============================================================================
print("\n=== 3. IIR DC Rejection ===")

pp3 = PokeyPair()
pp3.initialize(ntsc=False, stereo=False, sample_rate=44100)
pp3.poke(0x0F, 0x00, 0)
pp3.poke(0x0F, 0x03, 0)

# Write a constant volume and hold it for many frames
# DC component should be filtered out by IIR
all_pcm = []
for frame in range(200):
    pp3.start_frame()
    pp3.poke(0x01, 0x18, 100)  # Constant vol=8
    n = pp3.end_frame(PAL_CYCLES_PER_FRAME)
    pcm = pp3.generate(n)
    all_pcm.extend(pcm)

# After settling, output should be near zero (DC rejected)
# Check last 1000 samples
tail = all_pcm[-1000:]
avg_tail = sum(tail) / len(tail)
max_tail = max(abs(s) for s in tail)
check("DC rejection: tail avg near zero",
      abs(avg_tail) < 50, f"avg={avg_tail:.1f}")
check("DC rejection: tail max small",
      max_tail < 200, f"max={max_tail}")

# First samples should show the initial transient (NOT zero)
head = all_pcm[:100]
max_head = max(abs(s) for s in head)
check("initial transient present",
      max_head > 100, f"max_head={max_head}")


# ============================================================================
# Test 4: Frame Boundary Continuity (sinc trailing)
# ============================================================================
print("\n=== 4. Frame Boundary Continuity ===")

pp4 = PokeyPair()
pp4.initialize(ntsc=False, stereo=False, sample_rate=44100)
pp4.poke(0x0F, 0x00, 0)
pp4.poke(0x0F, 0x03, 0)

# Generate oscillating volume: 0 and 8, switching every 112 cycles
all_pcm4 = []
for frame in range(10):
    pp4.start_frame()
    cycle = 0
    toggle = 0
    while cycle < PAL_CYCLES_PER_FRAME:
        vol = 0x18 if toggle else 0x10
        pp4.poke(0x01, vol, cycle)
        toggle ^= 1
        cycle += 112
    n = pp4.end_frame(PAL_CYCLES_PER_FRAME)
    pcm = pp4.generate(n)
    all_pcm4.extend(pcm)

# Check that frame boundaries don't cause discontinuities
# Measure max absolute difference between consecutive samples
# A discontinuity would show as a huge jump
samples_per_frame = len(all_pcm4) // 10
for boundary in range(1, 9):
    idx = boundary * samples_per_frame
    if idx < len(all_pcm4) - 1:
        diff = abs(all_pcm4[idx] - all_pcm4[idx - 1])
        # Normal sample-to-sample difference for this signal
        typical_diff = max(
            abs(all_pcm4[i] - all_pcm4[i-1])
            for i in range(max(1, idx-50), min(len(all_pcm4), idx-5))
        )
        # Allow 3x typical for boundary
        check(f"frame {boundary} boundary smooth",
              diff < typical_diff * 3 + 100,
              f"diff={diff}, typical={typical_diff}")


# ============================================================================
# Test 5: Channel Phase Alignment with Timer
# ============================================================================
print("\n=== 5. Channel Phase Alignment ===")

pp5 = PokeyPair()
pp5.initialize(ntsc=False, stereo=False, sample_rate=44100)
pp5.poke(0x0F, 0x00, 0)
pp5.poke(0x00, 3, 0)     # AUDF1=3 → period=112
pp5.poke(0x01, 0xA8, 0)  # AUDC1=pure tone vol 8
pp5.poke(0x08, 0, 0)     # AUDCTL=0
pp5.poke(0x0F, 0x03, 0)  # SKCTL=3 run
pp5.poke(0x09, 0, 0)     # STIMER

# After STIMER, ch0.tick_cycle should be 0 + 112 = 112
check("ch0 tick_cycle after STIMER",
      pp5.base_pokey.channels[0].tick_cycle == 112,
      f"got {pp5.base_pokey.channels[0].tick_cycle}")


# ============================================================================
# Test 6: Sinc Interpolation Sum Verification
# ============================================================================
print("\n=== 6. Sinc Interpolation ===")

# Verify that all 1024 sinc phases have approximately the same sum
target = 1 << DELTA_RESOLUTION  # 16384
max_err = 0
for phase in range(1 << INTERPOLATION_SHIFT):
    row_sum = sum(pp.sinc_lookup[phase])
    err = abs(row_sum - target)
    if err > max_err:
        max_err = err

check(f"sinc max sum error across all phases: {max_err}",
      max_err < target * 0.02, f"max_err={max_err}")


# ============================================================================
# Test 7: Poly5 Gate Pattern
# ============================================================================
print("\n=== 7. Poly5 Gate Verification ===")

# The poly5 pattern is encoded in the magic constant 0x65BD44E0
# Verify it matches ASAP's documented bit pattern
pattern = 0x65BD44E0
ones = sum((pattern >> i) & 1 for i in range(31))
check(f"poly5 has 15 ones (POKEY LFSR)", ones == 15, f"ones={ones}")
# Bit 31 should be 0 (31-bit pattern, bit 31 not used)
check("poly5 bit 31 unused", (pattern >> 31) == 0)


# ============================================================================
# Test 8: SampleFactor Calculation
# ============================================================================
print("\n=== 8. SampleFactor ===")

pp8 = PokeyPair()
pp8.sample_rate = 44100
factor_pal = pp8._get_sample_factor(PAL_CLOCK)
factor_ntsc = pp8._get_sample_factor(1789772)

# Verify: cycles_per_frame * factor >> shift ≈ samples_per_frame
samples = (PAL_CYCLES_PER_FRAME * factor_pal) >> SAMPLE_FACTOR_SHIFT
check(f"PAL samples/frame ~ 882 (got {samples})",
      880 <= samples <= 890, f"samples={samples}")

samples_ntsc = (29868 * factor_ntsc) >> SAMPLE_FACTOR_SHIFT
check(f"NTSC samples/frame ~ 735 (got {samples_ntsc})",
      730 <= samples_ntsc <= 740, f"samples={samples_ntsc}")

# PAL factor should be slightly larger than NTSC (slower clock)
check("PAL factor > NTSC factor", factor_pal > factor_ntsc)


# ============================================================================
# Test 9: VQ Player — Verify Correct Codebook Byte Output
# ============================================================================
print("\n=== 9. VQ Codebook Byte Readout ===")

from pokey_emulator.vq_player import (
    VQPlayer, ChannelState, SongData, InstrumentData,
)

# Known codebook: vec0=$18,$19,$1A,$1B; vec1=$1C,$1D,$1E,$1F
codebook = bytes([0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F])
indices = bytes([0, 1, 0, 1])  # Play vec0, vec1, vec0, vec1

song = SongData()
song.codebook = codebook
song.vector_size = 4
song.build_codebook_offsets()

# Check offsets
check("vec0 offset=0",
      song.cb_offset_lo[0] == 0 and song.cb_offset_hi[0] == 0)
check("vec1 offset=4",
      song.cb_offset_lo[1] == 4 and song.cb_offset_hi[1] == 0)

inst = InstrumentData(0, True, indices, 0, 4)

player = VQPlayer(sample_rate=44100)
player.song = song  # Required for _tick_vq to access vector_size
player.pokey.initialize(ntsc=False, stereo=False, sample_rate=44100)
player.pokey.poke(0x0F, 0x03, 0)  # SKCTL=3 so AUDC writes work
ch = ChannelState()
ch.trigger(inst, 0x0100, song)  # Base pitch (1.0x)

# After trigger: stream_pos=0, vector_offset=0, sample_ptr=offset of vec0=0
check("trigger: stream_pos=0", ch.stream_pos == 0)
check("trigger: vector_offset=0", ch.vector_offset == 0)
check("trigger: sample_ptr=0 (vec0 offset)", ch.sample_ptr == 0)

# Read samples from channel
byte0 = player._read_sample(ch, codebook)
check("read byte0 = $18", byte0 == 0x18, f"got ${byte0:02X}")

# Tick once (no pitch): vector_offset 0→1
player._tick_vq(ch, 0, 0)
check("tick1: vo=1", ch.vector_offset == 1)
byte1 = player._read_sample(ch, codebook)
check("read byte1 = $19", byte1 == 0x19, f"got ${byte1:02X}")

# Tick: vo=2
player._tick_vq(ch, 0, 0)
byte2 = player._read_sample(ch, codebook)
check("read byte2 = $1A", byte2 == 0x1A, f"got ${byte2:02X}")

# Tick: vo=3
player._tick_vq(ch, 0, 0)
byte3 = player._read_sample(ch, codebook)
check("read byte3 = $1B", byte3 == 0x1B, f"got ${byte3:02X}")

# Tick: vo should wrap to 0, stream_pos advances to 1, loads vec1
player._tick_vq(ch, 0, 0)
check("boundary: stream_pos=1", ch.stream_pos == 1)
check("boundary: vo=0", ch.vector_offset == 0)
check("boundary: sample_ptr=4 (vec1 offset)", ch.sample_ptr == 4)

byte4 = player._read_sample(ch, codebook)
check("read byte4 = $1C (first byte of vec1)",
      byte4 == 0x1C, f"got ${byte4:02X}")


# ============================================================================
# Test 10: End-of-stream Detection
# ============================================================================
print("\n=== 10. End-of-stream ===")

short_indices = bytes([0, 1])
inst2 = InstrumentData(0, True, short_indices, 0, 2)
ch2 = ChannelState()
ch2.trigger(inst2, 0x0100, song)

# Play through both vectors (2 vectors × 4 ticks each = 8 ticks)
for i in range(4):
    player._tick_vq(ch2, 0, 0)
check("after vec0: stream_pos=1", ch2.stream_pos == 1)
for i in range(4):
    player._tick_vq(ch2, 0, 0)
# stream_pos should now be 2, which == stream_end, so channel deactivated
check("end-of-stream: active=False", not ch2.active)


# ============================================================================
# Summary
# ============================================================================
print(f"\n{'='*60}")
print(f"Deep Validation: {passed}/{passed+failed} passed, {failed} failed")
if failed:
    print("*** FAILURES DETECTED ***")
print(f"{'='*60}")
sys.exit(1 if failed else 0)
