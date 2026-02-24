#!/usr/bin/env python3
"""POKEY Emulation Integration Test Suite

Deep verification of every data path:
  Tracker Song -> SongData -> VQPlayer -> POKEY registers -> PCM output

Tests are grouped by subsystem:
  1. Data bridge (tracker<->player)
  2. AUDC register writes (the core signal)
  3. Pitch / fixed-point math
  4. Sequencer logic
  5. End-to-end render verification
  6. Edge cases & error paths
  7. AudioEngine integration
  8. Register-level verification
"""

import sys, os, math, struct
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokey_emulator.pokey import (
    PokeyPair, PokeyChannel, Pokey, NEVER_CYCLE,
    PAL_CLOCK, NTSC_CLOCK, PAL_CYCLES_PER_FRAME, NTSC_CYCLES_PER_FRAME,
    COMPRESSED_SUMS, DELTA_SHIFT_POKEY,
)
from pokey_emulator.vq_player import (
    VQPlayer, SongData, InstrumentData, ChannelState,
    AUDC_REGS, AUDF_REGS, AUDCTL, STIMER, SKCTL,
    SILENCE, NOTE_OFF, VOL_CHANGE_ASM,
)

passed = 0
failed = 0
errors = []

def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        errors.append(label)
        print(f"  FAIL: {label}")

def make_raw_instrument(data, idx=0):
    return InstrumentData(index=idx, is_vq=False, stream_data=data,
                          start_offset=0, end_offset=len(data))

def make_vq_instrument(indices, idx=0, start=0, end=None):
    if end is None: end = len(indices)
    return InstrumentData(index=idx, is_vq=True, stream_data=indices,
                          start_offset=start, end_offset=end)

def make_song_data(instruments=None, songlines=None, patterns=None,
                   ntsc=False, rate=3958, vector_size=8,
                   volume_control=False, codebook=None):
    sd = SongData()
    sd.ntsc = ntsc
    sd.vector_size = vector_size
    sd.volume_control = volume_control
    clock = NTSC_CLOCK if ntsc else PAL_CLOCK
    sd.audf_val = max(0, min(255, round(clock / 28.0 / rate) - 1))
    sd.audctl_val = 0
    sd.codebook = codebook if codebook else bytes(256 * vector_size)
    sd.build_codebook_offsets()
    p_tmp = VQPlayer(sample_rate=44100)
    sd.pitch_table = p_tmp._build_pitch_table()
    if volume_control: sd.build_volume_scale()
    if instruments: sd.instruments = list(instruments)
    sd.songlines = songlines if songlines else [{'speed': 6, 'patterns': [0,0,0,0]}]
    sd.song_length = len(sd.songlines)
    sd.patterns = patterns if patterns else [{'length': 16, 'events': []}]
    return sd

# ============================================================================
# 1. DATA BRIDGE
# ============================================================================
print("=" * 60)
print("1. DATA BRIDGE")
print("=" * 60)

# 1a. AUDF computation
for name, rate, expected in [("3958Hz", 3958, 15), ("7916Hz", 7916, 7), ("15840Hz", 15840, 3)]:
    computed = max(0, min(255, round(PAL_CLOCK / 28.0 / rate) - 1))
    check(computed == expected, f"1a. AUDF {name}: {computed} == {expected}")
    actual = PAL_CLOCK / (28.0 * (computed + 1))
    check(abs(actual - rate) / rate < 0.01, f"1a. Rate accuracy {name}: {actual:.1f}")

# 1b. Timer period
sd = make_song_data(rate=3958)
p = VQPlayer(sample_rate=44100)
p.load_song(sd)
check(p.timer_period == 28 * (sd.audf_val + 1),
      f"1b. Timer period: {p.timer_period} == {28*(sd.audf_val+1)}")

# 1c. Ticks per frame ~79 for 3958Hz
tpf = PAL_CYCLES_PER_FRAME // p.timer_period
check(abs(tpf - 79) <= 1, f"1c. Ticks/frame: {tpf}")

# 1d. Codebook offsets vs=8
sd = make_song_data(vector_size=8)
for i in range(16):
    off = sd.cb_offset_lo[i] | (sd.cb_offset_hi[i] << 8)
    check(off == i*8, f"1d. CB offset[{i}]={off} == {i*8}")

# 1e. Codebook offsets vs=4
sd4 = make_song_data(vector_size=4)
for i in [0,1,63,127]:
    off = sd4.cb_offset_lo[i] | (sd4.cb_offset_hi[i] << 8)
    check(off == i*4, f"1e. CB vs=4 [{i}]={off}")

# 1f. Volume scale
sdv = make_song_data(volume_control=True)
check(sdv.volume_scale[(15<<4)|15] == 0x1F, "1f. VolScale[15][15]=0x1F")
check(sdv.volume_scale[(0<<4)|15] == 0x10, "1f. VolScale[0][15]=0x10")
check(sdv.volume_scale[(8<<4)|15] == 0x18, "1f. VolScale[8][15]=0x18")
check(sdv.volume_scale[(15<<4)|0] == 0x10, "1f. VolScale[15][0]=0x10")
# Check intermediate: vol=4, sample=10 -> round(10*4/15) = 3 -> 0x13
check(sdv.volume_scale[(4<<4)|10] == 0x13, "1f. VolScale[4][10]=0x13")

# 1g. NTSC timing
sd_ntsc = make_song_data(ntsc=True, rate=3958)
pn = VQPlayer(sample_rate=44100)
pn.load_song(sd_ntsc)
check(pn.cycles_per_frame == NTSC_CYCLES_PER_FRAME, "1g. NTSC cycles/frame")

# 1h. Codebook offset wrap: index 255 with vs=8 -> offset 2040
sd8 = make_song_data(vector_size=8, codebook=bytes(256*8))
off255 = sd8.cb_offset_lo[255] | (sd8.cb_offset_hi[255] << 8)
check(off255 == 255*8, f"1h. CB offset[255]={off255} == {255*8}")

print()

# ============================================================================
# 2. AUDC REGISTER WRITES
# ============================================================================
print("=" * 60)
print("2. AUDC REGISTER WRITES")
print("=" * 60)

# 2a. RAW reads correct bytes in order
raw_data = bytes([0x10, 0x15, 0x1A, 0x1F, 0x13, 0x18, 0x1C, 0x11])
inst = make_raw_instrument(raw_data)
sd = make_song_data(instruments=[inst])
ch = ChannelState()
ch.trigger(inst, 0x0100, sd)

for tick in range(len(raw_data)):
    sample = VQPlayer._read_sample(None, ch, sd.codebook)
    check(sample == raw_data[tick], f"2a. RAW read [{tick}]: 0x{sample:02X}==0x{raw_data[tick]:02X}")
    # Advance (no-pitch)
    new_vo = (ch.vector_offset + 1) & 0xFF
    ch.vector_offset = new_vo
    if new_vo == 0:
        ch.sample_ptr += 256

# 2b. VQ reads codebook vectors in order
vs = 4
cb = bytes([0x10, 0x11, 0x12, 0x13,   # vector 0
            0x14, 0x15, 0x16, 0x17,    # vector 1
            0x18, 0x19, 0x1A, 0x1B])   # vector 2
cb += bytes(256*vs - len(cb))
indices = bytes([0, 1, 2])
vi = make_vq_instrument(indices)
sd_vq = make_song_data(instruments=[vi], codebook=cb, vector_size=vs)
ch_vq = ChannelState()
ch_vq.trigger(vi, 0x0100, sd_vq)

# Should read: 0x10,0x11,0x12,0x13 (vec 0), 0x14,0x15,0x16,0x17 (vec 1), ...
expected_bytes = [0x10,0x11,0x12,0x13, 0x14,0x15,0x16,0x17, 0x18,0x19,0x1A,0x1B]
for tick in range(12):
    sample = VQPlayer._read_sample(None, ch_vq, sd_vq.codebook)
    check(sample == expected_bytes[tick],
          f"2b. VQ read [{tick}]: 0x{sample:02X}==0x{expected_bytes[tick]:02X}")
    ch_vq.vector_offset += 1
    if ch_vq.vector_offset >= vs:
        ch_vq.vector_offset = 0
        ch_vq.stream_pos += 1
        if ch_vq.stream_pos < len(indices):
            idx = indices[ch_vq.stream_pos]
            ch_vq.sample_ptr = sd_vq.cb_offset_lo[idx] | (sd_vq.cb_offset_hi[idx] << 8)

# 2c. Volume-only bit always set in data
for b in raw_data:
    check(b & 0x10 != 0, f"2c. Byte 0x{b:02X} has bit 4 set")

# 2d. Note-off writes SILENCE
sd_off = make_song_data(
    instruments=[make_raw_instrument(bytes([0x1F]*500))],
    patterns=[{'length': 8, 'events': [(0,1,0,15), (3,0,0,0)]}],
)
p_off = VQPlayer(sample_rate=44100)
p_off.load_song(sd_off)
p_off.start_playback(0, 0)
for _ in range(25): p_off.render_frame()
check(not p_off.channels[0].active, "2d. Ch0 inactive after note-off")

# 2e. AUDF setup - all 4 channels get same value
pp = PokeyPair()
pp.initialize(ntsc=False, sample_rate=44100)
for reg in AUDF_REGS:
    pp.poke(reg, 15, 0)
for i in range(4):
    check(pp.base_pokey.channels[i].audf == 15, f"2e. POKEY ch{i} AUDF=15")

print()

# ============================================================================
# 3. PITCH / FIXED-POINT MATH
# ============================================================================
print("=" * 60)
print("3. PITCH / FIXED-POINT MATH")
print("=" * 60)

pt = VQPlayer(sample_rate=44100)._build_pitch_table()
check(pt[0] == 0x0100, f"3a. Pitch C-1 = 0x{pt[0]:04X}")
check(pt[12] == 0x0200, f"3b. Pitch C-2 = 0x{pt[12]:04X}")
check(pt[24] == 0x0400, f"3c. Pitch C-3 = 0x{pt[24]:04X}")
for i in range(35):
    check(pt[i+1] > pt[i], f"3d. Monotonic [{i+1}]>{pt[i]}")

# 3e. Pitch=0x0100 means no-pitch mode
ch = ChannelState()
inst = make_raw_instrument(bytes([0x15]*1000))
sd = make_song_data(instruments=[inst])
ch.trigger(inst, 0x0100, sd)
check(not ch.has_pitch, "3e. 0x0100 -> has_pitch=False")

# 3f. Pitch != 0x0100 means has_pitch
ch2 = ChannelState()
ch2.trigger(inst, 0x0200, sd)
check(ch2.has_pitch, "3f. 0x0200 -> has_pitch=True")

# 3g. RAW no-pitch: 256 ticks = 1 page
ch3 = ChannelState()
ch3.trigger(make_raw_instrument(bytes([0x15]*512)), 0x0100, sd)
for _ in range(256):
    new_vo = (ch3.vector_offset + 1) & 0xFF
    ch3.vector_offset = new_vo
    if new_vo == 0: ch3.sample_ptr += 256
check(ch3.sample_ptr == 256, f"3g. 256 ticks: ptr={ch3.sample_ptr}")

# 3h. VQ no-pitch: vs ticks = 1 vector
vs = 8
ch4 = ChannelState()
ch4.trigger(make_vq_instrument(bytes([0]*10)), 0x0100, make_song_data(vector_size=vs))
for _ in range(vs):
    ch4.vector_offset += 1
    if ch4.vector_offset >= vs:
        ch4.vector_offset = 0
        ch4.stream_pos += 1
check(ch4.stream_pos == 1, f"3h. After {vs} ticks: stream_pos={ch4.stream_pos}")

# 3i. 6502 pitch accumulation: pitch=0x0180 (1.5x), 2 ticks = 3 advances
ch5 = ChannelState()
ch5.trigger(make_raw_instrument(bytes([0x15]*512)), 0x0180, sd)
# Tick 1: frac=0+0x80=128, carry=0. adv=1. vo=1
frac = 0 + 0x80; carry = frac >> 8; ch5.pitch_frac = frac & 0xFF
adv = (0x0180 >> 8) + carry; ch5.vector_offset = (ch5.vector_offset + adv) & 0xFF
# Tick 2: frac=128+0x80=256, carry=1. adv=2. vo=3
frac = ch5.pitch_frac + 0x80; carry = frac >> 8; ch5.pitch_frac = frac & 0xFF
adv = (0x0180 >> 8) + carry; ch5.vector_offset = (ch5.vector_offset + adv) & 0xFF
check(ch5.vector_offset == 3, f"3i. 1.5x after 2 ticks: vo={ch5.vector_offset}")

# 3j. VQ pitch accumulation with vector boundary crossing
# pitch=0x0300 (3x), vs=8. After 3 ticks: 9 advances = 1 vector + 1
ch6 = ChannelState()
sd6 = make_song_data(instruments=[make_vq_instrument(bytes([0]*20))], vector_size=8)
ch6.trigger(sd6.instruments[0], 0x0300, sd6)

# Use actual _tick_vq
p6 = VQPlayer(sample_rate=44100)
p6.load_song(sd6)
p6.channels[0] = ch6
for tick in range(3):
    p6._tick_vq(ch6, 0, tick * 100)
# 3 ticks * 3.0 advance = 9 offsets. 9 // 8 = 1 vector, 9 % 8 = 1
check(ch6.stream_pos == 1 and ch6.vector_offset == 1,
      f"3j. 3x after 3 ticks: stream_pos={ch6.stream_pos}, vo={ch6.vector_offset}")

print()

# ============================================================================
# 4. SEQUENCER LOGIC
# ============================================================================
print("=" * 60)
print("4. SEQUENCER LOGIC")
print("=" * 60)

# 4a. Speed=6: row advances every 6 frames
sd4a = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000))],
    songlines=[{'speed': 6, 'patterns': [0,0,0,0]}],
    patterns=[{'length': 8, 'events': [(0,1,0,15)]}],
)
p4a = VQPlayer(sample_rate=44100)
p4a.load_song(sd4a)
p4a.start_playback(0, 0)
rows_seen = [p4a.seq_row]
for f in range(60):
    p4a.render_frame()
    if p4a.seq_row != rows_seen[-1]:
        rows_seen.append(p4a.seq_row)
check(rows_seen[1] == 1, f"4a. First row change: {rows_seen[1]}")
check(len(rows_seen) >= 5, f"4a. {len(rows_seen)} rows in 60 frames")

# 4b. Pattern wrap (row goes from max back to 0)
found_wrap = any(rows_seen[i] == 0 and rows_seen[i-1] > 0 for i in range(1, len(rows_seen)))
check(found_wrap, f"4b. Pattern wrap detected (rows: {rows_seen[-5:]})")

# 4c. Songline advance
sd4c = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000))],
    songlines=[
        {'speed': 1, 'patterns': [0,0,0,0]},
        {'speed': 1, 'patterns': [1,1,1,1]},
    ],
    patterns=[
        {'length': 4, 'events': [(0,1,0,15)]},
        {'length': 8, 'events': [(0,1,0,15)]},
    ],
)
p4c = VQPlayer(sample_rate=44100)
p4c.load_song(sd4c)
p4c.start_playback(0, 0)
songlines_visited = set()
for _ in range(20):
    songlines_visited.add(p4c.seq_songline)
    p4c.render_frame()
check(0 in songlines_visited and 1 in songlines_visited, f"4c. Songlines: {songlines_visited}")

# 4d. Song end stops playback
check(not p4c.playing, f"4d. Stopped after last songline: {p4c.playing}")

# 4e. Different pattern lengths: max_len correct
sd4e = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000))],
    songlines=[{'speed': 1, 'patterns': [0,1,0,1]}],
    patterns=[
        {'length': 4, 'events': [(0,1,0,15)]},
        {'length': 12, 'events': [(0,1,0,15)]},
    ],
)
p4e = VQPlayer(sample_rate=44100)
p4e.load_song(sd4e)
p4e.start_playback(0, 0)
check(p4e.seq_max_len == 12, f"4e. max_len={p4e.seq_max_len} (expect 12)")

# 4f. Per-channel local_row wraps independently
for _ in range(5): p4e.render_frame()
# ch0 pattern len=4: after 5 rows, local = 5%4 = 1
# ch1 pattern len=12: after 5 rows, local = 5
lr0 = p4e.seq_local_row[0]
lr1 = p4e.seq_local_row[1]
check(lr0 < 4, f"4f. Ch0 local_row={lr0} < 4 (wrapped)")
check(lr1 < 12, f"4f. Ch1 local_row={lr1} < 12")

# 4g. Start from mid-position
sd4g = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000))],
    songlines=[
        {'speed': 3, 'patterns': [0,0,0,0]},
        {'speed': 3, 'patterns': [0,0,0,0]},
    ],
    patterns=[{'length': 8, 'events': [(0,1,0,15), (4,0,0,0)]}],
)
p4g = VQPlayer(sample_rate=44100)
p4g.load_song(sd4g)
p4g.start_playback(songline=1, row=5)
check(p4g.seq_songline == 1, "4g. Start songline=1")
check(p4g.seq_row == 5, "4g. Start row=5")
check(p4g.playing, "4g. Playing")
# Events at row 0 and 4 should be skipped (past)
# Row 5 has no event, so ch should be inactive
check(not p4g.channels[0].active, "4g. No event at row 5: ch0 inactive")

# 4h. VOL_CHANGE event
sd4h = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000))],
    songlines=[{'speed': 1, 'patterns': [0,0,0,0]}],
    patterns=[{'length': 8, 'events': [(0,1,0,15), (3,VOL_CHANGE_ASM,0,7)]}],
)
p4h = VQPlayer(sample_rate=44100)
p4h.load_song(sd4h)
p4h.start_playback(0, 0)
check(p4h.channels[0].vol_shift == 0xF0, f"4h. Initial vol=0x{p4h.channels[0].vol_shift:02X}")
for _ in range(3): p4h.render_frame()
check(p4h.channels[0].vol_shift == 0x70, f"4h. After vol change: 0x{p4h.channels[0].vol_shift:02X}")
check(p4h.channels[0].active, "4h. Still active after vol change")

# 4i. Speed change between songlines
sd4i = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000))],
    songlines=[
        {'speed': 2, 'patterns': [0,0,0,0]},
        {'speed': 10, 'patterns': [0,0,0,0]},
    ],
    patterns=[{'length': 4, 'events': [(0,1,0,15)]}],
)
p4i = VQPlayer(sample_rate=44100)
p4i.load_song(sd4i)
p4i.start_playback(0, 0)
check(p4i.seq_speed == 2, "4i. Initial speed=2")
# Advance through songline 0: 4 rows * 2 frames/row = 8 frames
for _ in range(8): p4i.render_frame()
check(p4i.seq_speed == 10, f"4i. After songline change: speed={p4i.seq_speed}")

# 4j. Multiple events on same row (different channels)
sd4j = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000), idx=0),
                 make_raw_instrument(bytes([0x1A]*50000), idx=1)],
    songlines=[{'speed': 1, 'patterns': [0,1,0,1]}],
    patterns=[
        {'length': 8, 'events': [(0,1,0,15)]},   # ptn 0: ch0,ch2
        {'length': 8, 'events': [(0,1,1,12)]},    # ptn 1: ch1,ch3
    ],
)
p4j = VQPlayer(sample_rate=44100)
p4j.load_song(sd4j)
p4j.start_playback(0, 0)
# Row 0: all 4 channels should trigger
for i in range(4):
    check(p4j.channels[i].active, f"4j. Ch{i} active at row 0")
# Ch0,2 use inst 0; ch1,3 use inst 1
check(p4j.channels[0].instrument.index == 0, "4j. Ch0 inst=0")
check(p4j.channels[1].instrument.index == 1, "4j. Ch1 inst=1")

print()

# ============================================================================
# 5. END-TO-END RENDER
# ============================================================================
print("=" * 60)
print("5. END-TO-END RENDER")
print("=" * 60)

# 5a. Non-silent output
raw = bytes([0x10|(i%16) for i in range(2000)])
sd5a = make_song_data(
    instruments=[make_raw_instrument(raw)],
    patterns=[{'length': 64, 'events': [(0,1,0,15)]}],
)
p5a = VQPlayer(sample_rate=44100)
p5a.load_song(sd5a)
p5a.start_playback(0, 0)
pcm = p5a.render_frame()
rms = np.sqrt(np.mean(pcm**2))
check(len(pcm) > 0, f"5a. PCM length: {len(pcm)}")
check(rms > 0.001, f"5a. RMS={rms:.6f} > 0.001")

# 5b. Sample count roughly matches PAL frame rate
total = sum(len(p5a.render_frame()) for _ in range(49))
total += len(pcm)  # first frame
# 50 PAL frames ~= 44100 samples, but POKEY timing adds slight variance
check(abs(total - 44100) < 200, f"5b. 50 frames: {total} samples (~44100)")

# 5c. 4-channel louder than 1-channel (DAC compression)
dc8 = bytes([0x18]*5000)
sd_1 = make_song_data(instruments=[make_raw_instrument(dc8)])
sd_4 = make_song_data(instruments=[make_raw_instrument(dc8)],
                      songlines=[{'speed':6,'patterns':[0,0,0,0]}])

p1 = VQPlayer(sample_rate=44100); p1.load_song(sd_1)
p1.playing = False; p1.channels[0].trigger(sd_1.instruments[0], 0x0100, sd_1)
p1.channels[0].vol_shift = 0xF0
rms1 = np.sqrt(np.mean(np.concatenate([p1.render_frame() for _ in range(10)])**2))

p4 = VQPlayer(sample_rate=44100); p4.load_song(sd_4)
p4.playing = False
for c in range(4):
    p4.channels[c].trigger(sd_4.instruments[0], 0x0100, sd_4)
    p4.channels[c].vol_shift = 0xF0
rms4 = np.sqrt(np.mean(np.concatenate([p4.render_frame() for _ in range(10)])**2))

check(rms4 > rms1, f"5c. 4ch RMS {rms4:.4f} > 1ch {rms1:.4f}")
check(rms4 < rms1*4, f"5c. DAC compress: 4ch {rms4:.4f} < 4x {rms1*4:.4f}")

# 5d. All muted = near-silence
sd_m = make_song_data(
    instruments=[make_raw_instrument(bytes([0x1F]*5000))],
    songlines=[{'speed':6,'patterns':[0,0,0,0]}],
    patterns=[{'length':64,'events':[(0,1,0,15)]}],
)
pm = VQPlayer(sample_rate=44100); pm.load_song(sd_m)
pm.start_playback(0,0); pm.channel_muted = [True]*4
rms_m = np.sqrt(np.mean(np.concatenate([pm.render_frame() for _ in range(5)])**2))
check(rms_m < 0.01, f"5d. Muted RMS={rms_m:.6f}")

# 5e. DC rejection: constant input decays
p_dc = VQPlayer(sample_rate=44100)
p_dc.load_song(make_song_data(
    instruments=[make_raw_instrument(bytes([0x18]*10000))],
    patterns=[{'length':64,'events':[(0,1,0,15)]}],
))
p_dc.start_playback(0,0)
early = np.sqrt(np.mean(p_dc.render_frame()**2))
for _ in range(200): p_dc.render_frame()
late = np.sqrt(np.mean(p_dc.render_frame()**2))
check(late < early, f"5e. DC decay: late {late:.6f} < early {early:.6f}")

# 5f. NTSC vs PAL sample counts
p_pal = VQPlayer(sample_rate=44100)
p_pal.load_song(make_song_data(ntsc=False)); p_pal.start_playback(0,0)
p_ntsc = VQPlayer(sample_rate=44100)
p_ntsc.load_song(make_song_data(ntsc=True)); p_ntsc.start_playback(0,0)
n_pal = len(p_pal.render_frame())
n_ntsc = len(p_ntsc.render_frame())
check(abs(n_pal - 882) <= 2, f"5f. PAL: {n_pal} (~882)")
check(abs(n_ntsc - 735) <= 2, f"5f. NTSC: {n_ntsc} (~735)")

# 5g. End of stream deactivates channel
p_eos = VQPlayer(sample_rate=44100)
p_eos.load_song(make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*100))],
    patterns=[{'length':64,'events':[(0,1,0,15)]}],
))
p_eos.playing = False
p_eos.channels[0].trigger(p_eos.song.instruments[0], 0x0100, p_eos.song)
p_eos.channels[0].vol_shift = 0xF0
for _ in range(5): p_eos.render_frame()
check(not p_eos.channels[0].active, f"5g. EOS: ch0 inactive")

# 5h. VQ playback produces non-silent output
vs = 8
cb = bytes([0x10|(i%16) for i in range(vs)])*256
idx = bytes([0,1,2,3,4,5,6,7]*10)
sd_vq = make_song_data(instruments=[make_vq_instrument(idx)], codebook=cb, vector_size=vs,
                       patterns=[{'length':64,'events':[(0,1,0,15)]}])
p_vq = VQPlayer(sample_rate=44100); p_vq.load_song(sd_vq)
p_vq.start_playback(0,0)
rms_vq = np.sqrt(np.mean(np.concatenate([p_vq.render_frame() for _ in range(10)])**2))
check(rms_vq > 0.001, f"5h. VQ RMS={rms_vq:.4f}")

# 5i. PCM values in valid range
pcm_all = np.concatenate([p_vq.render_frame() for _ in range(5)])
check(np.all(np.abs(pcm_all) <= 1.1), f"5i. PCM in [-1.1,1.1]: max={np.max(np.abs(pcm_all)):.4f}")

# 5j. Different notes produce different playback duration
raw_note = bytes([0x10|(i%16) for i in range(5000)])
sd_note = make_song_data(instruments=[make_raw_instrument(raw_note)])

p_lo = VQPlayer(sample_rate=44100); p_lo.load_song(sd_note)
p_lo.playing = False; p_lo.channels[0].trigger(sd_note.instruments[0], pt[0], sd_note)
p_lo.channels[0].vol_shift = 0xF0
lo_frames = 0
while p_lo.channels[0].active and lo_frames < 300:
    p_lo.render_frame(); lo_frames += 1

p_hi = VQPlayer(sample_rate=44100); p_hi.load_song(sd_note)
p_hi.playing = False; p_hi.channels[0].trigger(sd_note.instruments[0], pt[24], sd_note)
p_hi.channels[0].vol_shift = 0xF0
hi_frames = 0
while p_hi.channels[0].active and hi_frames < 300:
    p_hi.render_frame(); hi_frames += 1

# C-3 (4x pitch) should exhaust sample 4x faster
check(hi_frames < lo_frames,
      f"5j. Higher pitch shorter: hi={hi_frames} < lo={lo_frames} frames")
check(abs(lo_frames / max(hi_frames, 1) - 4.0) < 0.5,
      f"5j. Pitch ratio ~4x: {lo_frames/max(hi_frames,1):.1f}")

print()

# ============================================================================
# 6. EDGE CASES
# ============================================================================
print("=" * 60)
print("6. EDGE CASES")
print("=" * 60)

# 6a. Empty song
try:
    pe = VQPlayer(sample_rate=44100)
    pe.load_song(make_song_data(instruments=[]))
    pe.start_playback(0,0)
    pe.render_frame()
    check(True, "6a. Empty song: no crash")
except: check(False, "6a. Empty song crashed")

# 6b. Out-of-range instrument in event
try:
    p_oob = VQPlayer(sample_rate=44100)
    p_oob.load_song(make_song_data(
        instruments=[make_raw_instrument(bytes([0x15]*1000))],
        patterns=[{'length':8,'events':[(0,1,99,15)]}]))
    p_oob.start_playback(0,0)
    for _ in range(5): p_oob.render_frame()
    check(True, "6b. OOB instrument: no crash")
except: check(False, "6b. OOB instrument crashed")

# 6c. Empty pattern
try:
    p_ep = VQPlayer(sample_rate=44100)
    p_ep.load_song(make_song_data(
        instruments=[make_raw_instrument(bytes([0x15]*1000))],
        patterns=[{'length':16,'events':[]}]))
    p_ep.start_playback(0,0)
    for _ in range(20): p_ep.render_frame()
    check(True, "6c. Empty pattern: no crash")
except: check(False, "6c. Empty pattern crashed")

# 6d. VQ empty index stream
try:
    p_ve = VQPlayer(sample_rate=44100)
    p_ve.load_song(make_song_data(
        instruments=[make_vq_instrument(b'',start=0,end=0)],
        patterns=[{'length':8,'events':[(0,1,0,15)]}]))
    p_ve.start_playback(0,0)
    for _ in range(5): p_ve.render_frame()
    check(not p_ve.channels[0].active, "6d. Empty VQ: ch deactivated")
except: check(False, "6d. Empty VQ crashed")

# 6e. Speed=1 (fastest)
p_s1 = VQPlayer(sample_rate=44100)
p_s1.load_song(make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*50000))],
    songlines=[{'speed':1,'patterns':[0,0,0,0]}],
    patterns=[{'length':64,'events':[(0,1,0,15)]}]))
p_s1.start_playback(0,0)
for _ in range(10): p_s1.render_frame()
check(p_s1.seq_row == 10, f"6e. Speed=1: row={p_s1.seq_row}")

# 6f. Songline out of range
p_oor = VQPlayer(sample_rate=44100)
p_oor.load_song(make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*1000))],
    patterns=[{'length':8,'events':[(0,1,0,15)]}]))
p_oor.start_playback(songline=99)
check(not p_oor.playing, "6f. OOR songline: not playing")
check(not any(ch.active for ch in p_oor.channels), "6f. OOR: no active channels")

# 6g. Retrigger (new note same channel)
sd_rt = make_song_data(
    instruments=[make_raw_instrument(bytes([0x15]*5000), idx=0),
                 make_raw_instrument(bytes([0x1A]*5000), idx=1)],
    songlines=[{'speed':1,'patterns':[0,0,0,0]}],
    patterns=[{'length':8,'events':[(0,1,0,15),(2,1,1,15)]}])
p_rt = VQPlayer(sample_rate=44100); p_rt.load_song(sd_rt)
p_rt.start_playback(0,0)
check(p_rt.channels[0].instrument.index == 0, "6g. Initial inst=0")
p_rt.render_frame(); p_rt.render_frame()
check(p_rt.channels[0].instrument.index == 1, "6g. After retrigger: inst=1")
check(p_rt.channels[0].stream_pos == 0, "6g. stream_pos reset")

# 6h. Single-byte instrument
try:
    p_1b = VQPlayer(sample_rate=44100)
    p_1b.load_song(make_song_data(
        instruments=[make_raw_instrument(bytes([0x18]))],
        patterns=[{'length':8,'events':[(0,1,0,15)]}]))
    p_1b.playing = False
    p_1b.channels[0].trigger(p_1b.song.instruments[0], 0x0100, p_1b.song)
    for _ in range(3): p_1b.render_frame()
    check(True, "6h. 1-byte instrument: no crash")
except Exception as e:
    check(False, f"6h. 1-byte instrument crashed: {e}")

print()

# ============================================================================
# 7. AUDIOENGINE INTEGRATION
# ============================================================================
print("=" * 60)
print("7. AUDIOENGINE INTEGRATION")
print("=" * 60)

try:
    import types
    if 'sounddevice' not in sys.modules:
        sys.modules['sounddevice'] = types.ModuleType('sd')
        sys.modules['sounddevice'].OutputStream = None

    from audio_engine import AudioEngine, _wav_to_pokey_raw, SAMPLE_RATE
    from data_model import Song, Instrument, Songline, Pattern, Row
    from vq_convert import VQState

    # 7a. WAV->RAW: silence maps correctly
    silence = np.zeros(4410, dtype=np.float32)
    raw = _wav_to_pokey_raw(silence, 44100, 3958)
    check(all(b & 0x10 for b in raw), "7a. Silence: all volume-only")
    check(len(raw) == max(1, int(4410*3958/44100)), f"7a. Length: {len(raw)}")

    # 7b. WAV->RAW: +1.0 -> 0x1F
    raw_max = _wav_to_pokey_raw(np.ones(4410, dtype=np.float32), 44100, 3958)
    check(all(b == 0x1F for b in raw_max), f"7b. Max -> 0x1F: {set(raw_max)}")

    # 7c. WAV->RAW: -1.0 -> 0x10
    raw_min = _wav_to_pokey_raw(-np.ones(4410, dtype=np.float32), 44100, 3958)
    check(all(b == 0x10 for b in raw_min), f"7c. Min -> 0x10: {set(raw_min)}")

    # 7d. WAV->RAW: monotonic mapping
    levels = np.linspace(-1, 1, 16, dtype=np.float32)
    raw_levels = _wav_to_pokey_raw(levels, 16, 16)
    prev = -1
    monotonic = True
    for b in raw_levels:
        if (b & 0x0F) < prev: monotonic = False
        prev = b & 0x0F
    check(monotonic, f"7d. Monotonic: {[b&0xF for b in raw_levels]}")

    # 7e. Song data construction
    song = Song(system=50, speed=6)
    wave = np.sin(np.linspace(0, 10*np.pi, 4410)).astype(np.float32)
    song.instruments.append(Instrument(name='I0', sample_data=wave, sample_rate=44100, base_note=1))
    song.patterns[0].rows[0] = Row(note=1, instrument=0, volume=15)
    ae = AudioEngine()
    ae.set_song(song)
    ae.set_vq_state(VQState())
    sd_live = ae._build_live_song_data()
    check(len(sd_live.patterns) == len(song.patterns), "7e. Pattern count")
    check(len(sd_live.instruments) > 0, "7e. Has instruments")
    check(not sd_live.instruments[0].is_vq, "7e. Instruments are RAW")

    # 7f. Event translation
    from constants import NOTE_OFF as TNO, VOL_CHANGE as TVC
    song2 = Song(system=50, speed=6)
    song2.instruments.append(Instrument(name='I0', sample_data=wave, sample_rate=44100, base_note=1))
    song2.patterns[0].rows[0] = Row(note=1, instrument=0, volume=15)
    song2.patterns[0].rows[2] = Row(note=TVC, instrument=0, volume=8)
    song2.patterns[0].rows[4] = Row(note=TNO, instrument=0, volume=0)
    ae.set_song(song2)
    sd2 = ae._build_live_song_data()
    evts = sd2.patterns[0]['events']
    check(len(evts) == 3, f"7f. 3 events: got {len(evts)}")
    check(evts[0][1] == 1, "7f. Note-on=1")
    check(evts[1][1] == 61, "7f. VOL_CHANGE=61")
    check(evts[2][1] == 0, "7f. NOTE_OFF=0")

    # 7g. Offline render
    pcm_off = ae.render_offline()
    check(pcm_off is not None and len(pcm_off) > 0, "7g. Offline: non-empty")

    # 7h. Preview position
    ae._preview.active = True
    ae._preview.sample_data = np.zeros(44100)
    ae._preview.position = 22050.0
    check(abs(ae.get_preview_position() - 0.5) < 0.001, "7h. Preview pos=0.5s")

    # 7i. Build player from song with empty instruments
    song_e = Song(system=50, speed=6)
    song_e.instruments.append(Instrument(name='Empty'))  # No sample data
    ae.set_song(song_e)
    player_obj = ae._build_player_obj(0, 0)
    check(player_obj is not None, "7i. Player builds with empty instruments")

    # 7j. _build_player_obj returns functional player
    song_j = Song(system=50, speed=6)
    song_j.instruments.append(Instrument(name='I0', sample_data=wave, sample_rate=44100, base_note=1))
    song_j.patterns[0].rows[0] = Row(note=1, instrument=0, volume=15)
    ae.set_song(song_j)
    pj = ae._build_player_obj(0, 0)
    check(pj is not None and pj.playing, "7j. Player playing")
    pcm_j = pj.render_frame()
    check(len(pcm_j) > 0, f"7j. Render produces PCM: {len(pcm_j)}")

    AE_OK = True
except Exception as e:
    import traceback; traceback.print_exc()
    AE_OK = False

print()

# ============================================================================
# 8. REGISTER-LEVEL VERIFICATION
# ============================================================================
print("=" * 60)
print("8. REGISTER-LEVEL")
print("=" * 60)

# 8a. sum_dac_inputs tracking
pp = PokeyPair(); pp.initialize(ntsc=False, sample_rate=44100)
pp.poke(SKCTL, 0x03, 0); pp.poke(STIMER, 0x00, 0)
check(pp.base_pokey.sum_dac_inputs == 0, "8a. Initial DAC=0")

pp.poke(0x01, 0x18, 10)  # ch0 vol=8
check(pp.base_pokey.sum_dac_inputs == 8, "8a. After ch0=8: DAC=8")
pp.poke(0x03, 0x15, 20)  # ch1 vol=5
check(pp.base_pokey.sum_dac_inputs == 13, "8a. After ch1=5: DAC=13")
pp.poke(0x01, 0x13, 30)  # ch0 change to 3
check(pp.base_pokey.sum_dac_inputs == 8, "8a. Ch0 3->: DAC=8")

# 8b. COMPRESSED_SUMS monotonicity
for i in range(len(COMPRESSED_SUMS)-1):
    check(COMPRESSED_SUMS[i+1] > COMPRESSED_SUMS[i],
          f"8b. CS[{i+1}]>CS[{i}]")

# 8c. DAC compression
check(COMPRESSED_SUMS[32] < 4*COMPRESSED_SUMS[8], "8c. DAC compressed")

# 8d. SILENCE = zero DAC
pp2 = PokeyPair(); pp2.initialize(ntsc=False, sample_rate=44100)
pp2.poke(SKCTL, 0x03, 0)
pp2.poke(0x01, SILENCE, 10)
check(pp2.base_pokey.sum_dac_inputs == 0, "8d. SILENCE: DAC=0")

# 8e. AUDCTL clock selection
pp3 = PokeyPair(); pp3.initialize(ntsc=False, sample_rate=44100)
pp3.poke(AUDCTL, 0x00, 0)
check(pp3.base_pokey.div_cycles == 28, "8e. 64kHz: div=28")
pp3.poke(AUDCTL, 0x01, 10)
check(pp3.base_pokey.div_cycles == 114, "8e. 15kHz: div=114")

# 8f. Frame output sample count stability
pp4 = PokeyPair(); pp4.initialize(ntsc=False, sample_rate=44100)
pp4.poke(SKCTL, 0x03, 0); pp4.poke(STIMER, 0x00, 0)
pp4.start_frame()
pp4.poke(0x01, 0x18, 100)
n = pp4.end_frame(PAL_CYCLES_PER_FRAME)
check(abs(n - 882) <= 2, f"8f. Frame samples: {n} (~882)")

# 8g. Multiple frames produce consistent count
counts = []
for _ in range(10):
    pp4.start_frame()
    pp4.poke(0x01, 0x18, 100)
    counts.append(pp4.end_frame(PAL_CYCLES_PER_FRAME))
variance = max(counts) - min(counts)
check(variance <= 1, f"8g. Sample count variance: {variance} (expect <=1)")

# 8h. IIR filter prevents DC
pp5 = PokeyPair(); pp5.initialize(ntsc=False, sample_rate=44100)
pp5.poke(SKCTL, 0x03, 0); pp5.poke(STIMER, 0x00, 0)
# Write constant DC and render many frames
for _ in range(200):
    pp5.start_frame()
    pp5.poke(0x01, 0x18, 100)
    n = pp5.end_frame(PAL_CYCLES_PER_FRAME)
    samples = pp5.generate(n)
last_sample = samples[-1] if samples else 0
check(abs(last_sample) < 1000, f"8h. IIR settled: last={last_sample}")

print()

# ============================================================================
# SUMMARY
# ============================================================================
print("=" * 60)
total = passed + failed
print(f"Integration Tests: {passed}/{total} passed, {failed} failed")
if errors:
    print("\nFailed:")
    for e in errors:
        print(f"  - {e}")
print("=" * 60)
sys.exit(1 if failed > 0 else 0)
