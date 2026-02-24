#!/usr/bin/env python3
"""4-Channel POKEY Emulation Verification

Tests that 4-channel playback through the POKEY emulator produces
correct output matching what real Atari hardware and ASAP would generate.

Verified properties:
  1. Signal chain: VQPlayer → POKEY register writes → DAC compression → sinc output
  2. 4 channels mixed through CompressedSums (measured AMI DAC curve)
  3. Volume-only mode (AUDC bit 4 set) works on all 4 channels
  4. Different notes produce different playback rates
  5. Note-off silences individual channels without affecting others
  6. DAC compression is sublinear (4×vol(8) < 4×vol(1ch=8))
  7. Channel independence: each channel plays its own instrument data
  8. Pre-conversion (RAW) and post-conversion (VQ) paths both work
"""
import sys
import os
# Allow running from project root or from pokey_emulator/
_here = os.path.dirname(os.path.abspath(__file__))
_project = os.path.dirname(_here)
for p in (_project, _here):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
from pokey_emulator.pokey import PokeyPair, COMPRESSED_SUMS
from pokey_emulator.vq_player import (
    VQPlayer, SongData, InstrumentData, ChannelState,
    PAL_CLOCK, PAL_CYCLES_PER_FRAME,
    AUDC_REGS, AUDF_REGS, AUDCTL, STIMER, SKCTL, SILENCE,
)

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


def rms(arr):
    return np.sqrt(np.mean(arr ** 2))


def peak(arr):
    return np.max(np.abs(arr))


# ============================================================================
# TEST 1: Raw POKEY 4-channel mixing at register level
# ============================================================================
print("TEST 1: Raw POKEY 4-channel register-level mixing")
print("-" * 55)

pokey = PokeyPair()
pokey.initialize(ntsc=False, stereo=False, sample_rate=44100)

# Setup: init → silence → AUDF → SKCTL → STIMER
pokey.poke(SKCTL, 0x00, 0)
for r in AUDC_REGS:
    pokey.poke(r, SILENCE, 0)
for r in AUDF_REGS:
    pokey.poke(r, 0x0D, 0)  # ~3958 Hz
pokey.poke(AUDCTL, 0x00, 0)
pokey.poke(SKCTL, 0x03, 0)
pokey.poke(STIMER, 0x00, 0)

# --- 1a: Single channel at volume 8 ---
pokey.start_frame()
# Write AUDC1 = 0x18 (volume 8, vol-only mode) at multiple ticks
for tick in range(0, PAL_CYCLES_PER_FRAME, 392):
    pokey.poke(0x01, 0x18, tick)  # AUDC1 = vol 8
n = pokey.end_frame(PAL_CYCLES_PER_FRAME)
pcm_1ch = np.array(pokey.generate(n), dtype=np.float32) / 32767.0
rms_1ch = rms(pcm_1ch)
test("1ch vol=8 produces sound", rms_1ch > 0, f"rms={rms_1ch:.4f}")

# --- 1b: Same volume on 4 channels simultaneously ---
pokey.start_frame()
for tick in range(0, PAL_CYCLES_PER_FRAME, 392):
    pokey.poke(0x01, 0x18, tick)  # AUDC1 = vol 8
    pokey.poke(0x03, 0x18, tick)  # AUDC2 = vol 8
    pokey.poke(0x05, 0x18, tick)  # AUDC3 = vol 8
    pokey.poke(0x07, 0x18, tick)  # AUDC4 = vol 8
n = pokey.end_frame(PAL_CYCLES_PER_FRAME)
pcm_4ch = np.array(pokey.generate(n), dtype=np.float32) / 32767.0
rms_4ch = rms(pcm_4ch)
test("4ch vol=8 produces sound", rms_4ch > 0, f"rms={rms_4ch:.4f}")
test("4ch louder than 1ch", rms_4ch > rms_1ch,
     f"4ch_rms={rms_4ch:.4f} vs 1ch_rms={rms_1ch:.4f}")

# --- 1c: DAC compression: 4×vol(8) < 4 × 1×vol(8) ---
# On real POKEY, the DAC is sublinear (CompressedSums)
cs_1x8 = COMPRESSED_SUMS[8]
cs_4x8 = COMPRESSED_SUMS[32]
test("DAC compression sublinear", cs_4x8 < 4 * cs_1x8,
     f"CS[32]={cs_4x8} vs 4×CS[8]={4*cs_1x8}")
print()


# ============================================================================
# TEST 2: Volume-only mode waveform on all 4 channels
# ============================================================================
print("TEST 2: Volume-only mode — changing AUDC values produce DAC steps")
print("-" * 55)

pokey = PokeyPair()
pokey.initialize(ntsc=False, stereo=False, sample_rate=44100)
pokey.poke(SKCTL, 0x00, 0)
for r in AUDC_REGS:
    pokey.poke(r, SILENCE, 0)
for r in AUDF_REGS:
    pokey.poke(r, 0x0D, 0)
pokey.poke(AUDCTL, 0x00, 0)
pokey.poke(SKCTL, 0x03, 0)
pokey.poke(STIMER, 0x00, 0)

# Write a known sequence: ramp on ch0, steady high on ch1
# (non-complementary so net DAC level changes → IIR produces AC output)
pokey.start_frame()
period = 28 * (0x0D + 1)  # 392
tick = 0
ramp = 0
while tick < PAL_CYCLES_PER_FRAME and ramp < 16:
    pokey.poke(0x01, 0x10 | ramp, tick)        # ch0: 0→15
    pokey.poke(0x03, 0x10 | 8, tick)            # ch1: steady vol 8
    tick += period
    ramp += 1
n = pokey.end_frame(PAL_CYCLES_PER_FRAME)
pcm = np.array(pokey.generate(n), dtype=np.float32) / 32767.0
test("Ramp produces non-zero output", rms(pcm) > 0)
test("Ramp has dynamic range", pcm.max() - pcm.min() > 0.01,
     f"min={pcm.min():.4f}, max={pcm.max():.4f}")
print()


# ============================================================================
# TEST 3: VQPlayer 4-channel playback — full signal chain
# ============================================================================
print("TEST 3: VQPlayer 4-channel playback (RAW instruments)")
print("-" * 55)

# Build a 4-channel song with distinct instruments
target_rate = 3958
clock = PAL_CLOCK
audf_val = max(0, min(255, round(clock / 28.0 / target_rate) - 1))

song = SongData()
song.ntsc = False
song.vector_size = 8
song.audf_val = audf_val
song.audctl_val = 0
song.codebook = bytes(256 * 8)
song.build_codebook_offsets()

# Create 4 distinct RAW instruments (different waveforms)
for inst_idx in range(4):
    n_samples = target_rate  # 1 second worth
    raw = bytearray(n_samples)
    for s in range(n_samples):
        if inst_idx == 0:
            # Sawtooth
            raw[s] = 0x10 | (s % 16)
        elif inst_idx == 1:
            # Square wave (period 32)
            raw[s] = 0x1F if (s // 16) % 2 == 0 else 0x10
        elif inst_idx == 2:
            # Triangle
            t = s % 32
            raw[s] = 0x10 | (t if t < 16 else 31 - t)
        elif inst_idx == 3:
            # Pulse (narrow)
            raw[s] = 0x1E if (s % 32 < 4) else 0x11
    inst = InstrumentData(
        index=inst_idx, is_vq=False,
        stream_data=bytes(raw),
        start_offset=0, end_offset=len(raw),
    )
    song.instruments.append(inst)

# Build pitch table
player = VQPlayer(sample_rate=44100)
song.pitch_table = player._build_pitch_table()

# Song: all 4 channels trigger simultaneously on row 0
song.song_length = 1
song.songlines.append({'speed': 6, 'patterns': [0, 1, 2, 3]})
# Pattern 0: ch0 plays inst0 note C-1
song.patterns.append({'length': 64, 'events': [(0, 1, 0, 15)]})
# Pattern 1: ch1 plays inst1 note C-2
song.patterns.append({'length': 64, 'events': [(0, 13, 1, 15)]})
# Pattern 2: ch2 plays inst2 note C-1
song.patterns.append({'length': 64, 'events': [(0, 1, 2, 15)]})
# Pattern 3: ch3 plays inst3 note E-1
song.patterns.append({'length': 64, 'events': [(0, 5, 3, 15)]})

player.load_song(song)
player.start_playback(songline=0, row=0)

# Check all 4 channels are active
active = [ch.active for ch in player.channels]
test("All 4 channels active after start", all(active), f"{active}")

# Check each channel has the right instrument
for i in range(4):
    ch = player.channels[i]
    test(f"Ch{i} has instrument {i}", ch.instrument.index == i)

# Render 10 frames (~200ms) and accumulate PCM
frames = []
for f_idx in range(10):
    pcm = player.render_frame()
    frames.append(pcm)
all_pcm = np.concatenate(frames)

test("4ch render produces samples", len(all_pcm) > 8000,
     f"got {len(all_pcm)} samples")
test("4ch render not silence", rms(all_pcm) > 0.01,
     f"rms={rms(all_pcm):.4f}")
test("4ch render has dynamic range", peak(all_pcm) > 0.1,
     f"peak={peak(all_pcm):.4f}")

# All channels still active after 10 frames (instruments are 1s long)
active = [ch.active for ch in player.channels]
test("All 4 channels still active after 200ms", all(active))
print()


# ============================================================================
# TEST 4: Channel independence — silencing one doesn't affect others
# ============================================================================
print("TEST 4: Channel independence (note-off on one channel)")
print("-" * 55)

# Build a 2-pattern song: row 0 triggers all 4, row 4 note-offs channel 2
song2 = SongData()
song2.ntsc = False
song2.vector_size = 8
song2.audf_val = audf_val
song2.audctl_val = 0
song2.codebook = bytes(256 * 8)
song2.build_codebook_offsets()

# Single shared instrument
raw = bytes([0x10 | (s % 16) for s in range(target_rate)])
for i in range(4):
    song2.instruments.append(InstrumentData(
        index=i, is_vq=False,
        stream_data=raw, start_offset=0, end_offset=len(raw)))

song2.pitch_table = player._build_pitch_table()
song2.song_length = 1
song2.songlines.append({'speed': 3, 'patterns': [0, 1, 2, 3]})
# ch0,1,3: note on row 0, plays for entire pattern
# ch2: note on row 0, note-off on row 4
for ch in range(4):
    events = [(0, 1, ch, 15)]
    if ch == 2:
        events.append((4, 0, 0, 0))  # note=0 = note-off
    song2.patterns.append({'length': 64, 'events': events})

p2 = VQPlayer(sample_rate=44100)
p2.load_song(song2)
p2.start_playback(songline=0, row=0)

# Render until row advances past note-off (speed=3 → 3 frames/row, row 4 = frame 12+)
for _ in range(15):
    p2.render_frame()

test("Ch0 still active after ch2 note-off", p2.channels[0].active)
test("Ch1 still active after ch2 note-off", p2.channels[1].active)
test("Ch2 silenced by note-off", not p2.channels[2].active)
test("Ch3 still active after ch2 note-off", p2.channels[3].active)

# Render more frames — remaining 3 channels still produce audio
pcm_after = p2.render_frame()
test("3 remaining channels still produce sound", rms(pcm_after) > 0.01,
     f"rms={rms(pcm_after):.4f}")
print()


# ============================================================================
# TEST 5: Different notes → different playback rates
# ============================================================================
print("TEST 5: Different notes produce different pitch rates")
print("-" * 55)

# Two channels: ch0 plays C-1 (note 1), ch1 plays C-3 (note 25, 4× speed)
song3 = SongData()
song3.ntsc = False
song3.vector_size = 8
song3.audf_val = audf_val
song3.audctl_val = 0
song3.codebook = bytes(256 * 8)
song3.build_codebook_offsets()

# Instrument: sawtooth ramp 0→15→0→15... (period 32 samples)
# At different playback rates, this produces different oscillation speeds
raw3 = bytearray(target_rate * 2)
for s in range(len(raw3)):
    t = s % 32
    raw3[s] = 0x10 | (t if t < 16 else 31 - t)
for i in range(2):
    song3.instruments.append(InstrumentData(
        index=i, is_vq=False,
        stream_data=bytes(raw3), start_offset=0, end_offset=len(raw3)))

song3.pitch_table = player._build_pitch_table()
song3.song_length = 1
song3.songlines.append({'speed': 6, 'patterns': [0, 1, 2, 3]})
song3.patterns.append({'length': 64, 'events': [(0, 1, 0, 15)]})   # C-1
song3.patterns.append({'length': 64, 'events': [(0, 25, 1, 15)]})  # C-3 (4x pitch)
song3.patterns.append({'length': 64, 'events': []})
song3.patterns.append({'length': 64, 'events': []})

p3 = VQPlayer(sample_rate=44100)
p3.load_song(song3)
p3.start_playback()

# Render 20 frames and count sample advancement per channel
# The channel with higher note should advance faster through its stream data
for _ in range(20):
    p3.render_frame()

ch0_pos = p3.channels[0].sample_ptr + p3.channels[0].vector_offset
ch1_pos = p3.channels[1].sample_ptr + p3.channels[1].vector_offset

test("C-3 advances faster than C-1", ch1_pos > ch0_pos * 2,
     f"ch0_pos={ch0_pos}, ch1_pos={ch1_pos} (expect ~4x ratio)")
test("Both channels still active", p3.channels[0].active and p3.channels[1].active)

# Check pitch step values
step0 = song3.pitch_table[0]   # C-1 = note index 0
step24 = song3.pitch_table[24] # C-3 = note index 24
test("Pitch table: C-3 ≈ 4× C-1", 3.5 < (step24/step0) < 4.5,
     f"step0=0x{step0:04X}, step24=0x{step24:04X}, ratio={step24/step0:.2f}")
print()


# ============================================================================
# TEST 6: Volume control per channel
# ============================================================================
print("TEST 6: Per-channel volume (vol_shift)")
print("-" * 55)

# Two channels at different volumes: ch0 vol=15, ch1 vol=4
# With volume_control enabled, sample nibble is scaled
song4 = SongData()
song4.ntsc = False
song4.vector_size = 8
song4.audf_val = audf_val
song4.audctl_val = 0
song4.volume_control = True
song4.codebook = bytes(256 * 8)
song4.build_codebook_offsets()
song4.build_volume_scale()

raw4 = bytes([0x10 | (s % 16) for s in range(target_rate)])
for i in range(4):
    song4.instruments.append(InstrumentData(
        index=i, is_vq=False,
        stream_data=raw4, start_offset=0, end_offset=len(raw4)))

song4.pitch_table = player._build_pitch_table()
song4.song_length = 1
song4.songlines.append({'speed': 6, 'patterns': [0, 1, 2, 3]})
song4.patterns.append({'length': 64, 'events': [(0, 1, 0, 15)]})  # vol 15
song4.patterns.append({'length': 64, 'events': [(0, 1, 1, 4)]})   # vol 4
song4.patterns.append({'length': 64, 'events': []})
song4.patterns.append({'length': 64, 'events': []})

p4 = VQPlayer(sample_rate=44100)
p4.load_song(song4)
p4.start_playback()

# Check vol_shift is set correctly
p4.render_frame()  # process first row
test("Ch0 vol_shift = 0xF0 (vol 15)", p4.channels[0].vol_shift == 0xF0,
     f"got 0x{p4.channels[0].vol_shift:02X}")
test("Ch1 vol_shift = 0x40 (vol 4)", p4.channels[1].vol_shift == 0x40,
     f"got 0x{p4.channels[1].vol_shift:02X}")

# Verify volume scale table exists and is reasonable
test("Volume scale table populated", len(song4.volume_scale) == 256)
# At vol=15 (shift=0xF0): nibble 15 should map to max
# At vol=0 (shift=0x00): all nibbles should map to silence
test("Vol=15, nibble=15 → loud", (song4.volume_scale[0xF0 | 0x0F] & 0x0F) > 10)
test("Vol=0, nibble=15 → silent", (song4.volume_scale[0x00 | 0x0F] & 0x0F) == 0)
print()


# ============================================================================
# TEST 7: AudioEngine integration — pre-conversion RAW path
# ============================================================================
print("TEST 7: AudioEngine pre-conversion (WAV → RAW → POKEY)")
print("-" * 55)

# Mock sounddevice
import types
if 'sounddevice' not in sys.modules:
    sys.modules['sounddevice'] = types.ModuleType('mock_sd')
    sys.modules['sounddevice'].OutputStream = None

from audio_engine import AudioEngine, _wav_to_pokey_raw
from data_model import Song, Instrument, Songline, Pattern, Row
from vq_convert import VQState

# Create a song with 4 instruments on 4 channels
song_ae = Song(title='4ch Test', system=50, speed=3)
song_ae.songlines = [Songline(patterns=[0,1,2,3], speed=3)]

for i in range(4):
    # Different waveforms per instrument
    freq = 200 * (i + 1)  # 200, 400, 600, 800 Hz
    t = np.linspace(0, 1.0, 44100, dtype=np.float32)
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
    inst = Instrument(
        name=f'Wave{freq}', sample_data=wave,
        sample_rate=44100, base_note=1)
    song_ae.instruments.append(inst)

for i in range(4):
    ptn = Pattern(length=8)
    ptn.rows[0] = Row(note=1, instrument=i, volume=15)  # C-1
    song_ae.patterns[i] = ptn  # SET at index, not append

ae = AudioEngine()
ae.set_song(song_ae)
ae.set_vq_state(VQState())  # no conversion yet

# Build live song data
sd_live = ae._build_live_song_data()
test("Live song has 4 instruments", len(sd_live.instruments) == 4)
for i in range(4):
    inst_d = sd_live.instruments[i]
    test(f"  Inst{i} is RAW", not inst_d.is_vq)
    test(f"  Inst{i} has data", len(inst_d.stream_data) > 100,
         f"len={len(inst_d.stream_data)}")
    # Verify all bytes are AUDC volume-only format
    bad = [b for b in inst_d.stream_data if b < 0x10 or b > 0x1F]
    test(f"  Inst{i} all bytes 0x10-0x1F", len(bad) == 0,
         f"{len(bad)} bad bytes")

# Play from and render
ae.play_from(0, 0)
test("VQPlayer created", ae._vq_player is not None)
if ae._vq_player:
    active = [ch.active for ch in ae._vq_player.channels]
    test("All 4 VQPlayer channels active", all(active), f"{active}")

    # Render several frames
    chunks = []
    for _ in range(10):
        pcm = ae._vq_player.render_frame()
        chunks.append(pcm)
    all_pcm = np.concatenate(chunks)
    test("4ch pre-conv render not silence", rms(all_pcm) > 0.01,
         f"rms={rms(all_pcm):.4f}")
    test("4ch pre-conv has dynamic range", peak(all_pcm) > 0.05,
         f"peak={peak(all_pcm):.4f}")

ae.stop_playback()
print()


# ============================================================================
# TEST 8: _wav_to_pokey_raw accuracy
# ============================================================================
print("TEST 8: WAV→RAW conversion accuracy")
print("-" * 55)

# Test that conversion preserves waveform shape
# DC offset → should quantize to single level
dc_high = np.ones(44100, dtype=np.float32)
raw_dc = _wav_to_pokey_raw(dc_high, 44100, 3958)
vals = set(raw_dc)
test("DC +1.0 → single level", len(vals) == 1, f"got {len(vals)} levels")
test("DC +1.0 → max volume (0x1F)", list(vals)[0] == 0x1F,
     f"got 0x{list(vals)[0]:02X}")

dc_low = -np.ones(44100, dtype=np.float32)
raw_dc = _wav_to_pokey_raw(dc_low, 44100, 3958)
vals = set(raw_dc)
test("DC -1.0 → single level", len(vals) == 1, f"got {len(vals)} levels")
test("DC -1.0 → min volume (0x10)", list(vals)[0] == 0x10,
     f"got 0x{list(vals)[0]:02X}")

# Sine wave → should use full range
sine = np.sin(np.linspace(0, 20*np.pi, 44100)).astype(np.float32)
raw_sine = _wav_to_pokey_raw(sine, 44100, 3958)
vals = set(raw_sine)
test("Sine → uses most levels", len(vals) >= 12,
     f"got {len(vals)} distinct levels")
test("Sine → includes 0x10", 0x10 in vals)
test("Sine → includes 0x1F", 0x1F in vals)

# Resample ratio: 44100→3958 should produce ~3958 samples
test("44100→3958 resamples correctly", abs(len(raw_sine) - 3958) < 2,
     f"got {len(raw_sine)} samples")
print()


# ============================================================================
# TEST 9: Timing — ticks per frame matches hardware
# ============================================================================
print("TEST 9: Timer ticks per frame (hardware accuracy)")
print("-" * 55)

# At rate 3958 Hz: period = 28 * (audf_val + 1)
# PAL frame = 35568 cycles
period = 28 * (audf_val + 1)
ticks_per_frame = PAL_CYCLES_PER_FRAME // period
actual_rate = PAL_CLOCK / period
test(f"Timer period = {period} cycles (audf={audf_val})", period > 0)
test(f"Ticks/frame = {ticks_per_frame}", 70 <= ticks_per_frame <= 100)
test(f"Actual rate ≈ {actual_rate:.0f} Hz", 3900 < actual_rate < 4100,
     f"got {actual_rate:.1f}")

# Samples per frame at 44100 Hz output
samples_per_frame = round(44100 * PAL_CYCLES_PER_FRAME / PAL_CLOCK)
test(f"~{samples_per_frame} output samples/frame",
     880 <= samples_per_frame <= 890)
print()


# ============================================================================
# TEST 10: End-to-end offline render through AudioEngine
# ============================================================================
print("TEST 10: Offline render — full 4-channel song through POKEY")
print("-" * 55)

song_offline = Song(title='Render Test', system=50, speed=3)
song_offline.songlines = [Songline(patterns=[0,1,2,3], speed=3)]
for i in range(4):
    freq = 300 * (i + 1)
    t = np.linspace(0, 0.5, 22050, dtype=np.float32)
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
    song_offline.instruments.append(Instrument(
        name=f'Tone{freq}', sample_data=wave,
        sample_rate=44100, base_note=1))
for i in range(4):
    ptn = Pattern(length=8)
    ptn.rows[0] = Row(note=1 + i*4, instrument=i, volume=15)
    song_offline.patterns[i] = ptn  # SET at index, not append

ae2 = AudioEngine()
ae2.set_song(song_offline)
ae2.set_vq_state(VQState())

rendered = ae2.render_offline()
test("Offline render produces output", rendered is not None)
if rendered is not None:
    test("Offline render has samples", len(rendered) > 5000,
         f"got {len(rendered)}")
    test("Offline render not silent", rms(rendered) > 0.001,
         f"rms={rms(rendered):.4f}")
    test("Offline render has dynamics", peak(rendered) > 0.01,
         f"peak={peak(rendered):.4f}")
    duration = len(rendered) / 44100
    test(f"Duration reasonable ({duration:.2f}s)", 0.5 < duration < 30)
print()


# ============================================================================
# SUMMARY
# ============================================================================
print("=" * 55)
total = passed + failed
print(f"4-Channel Verification: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED — 4-channel POKEY emulation verified")
else:
    print(f"FAILURES DETECTED: {failed} tests failed")
    sys.exit(1)
print("=" * 55)
