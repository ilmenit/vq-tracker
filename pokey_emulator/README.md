# pokey_emulator — Cycle-Accurate POKEY Chip Emulator + VQ Player

Python port of the ASAP (Another Slight Atari Player) POKEY emulator by
Piotr Fusik, combined with a VQ sample player engine for Raster Music Tracker.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  VQPlayer                       │
│  ┌───────────┐  ┌──────────────────┐            │
│  │ Song       │  │ Channel States   │            │
│  │ Sequencer  │  │ (VQ/RAW modes)   │            │
│  │ (50/60 Hz) │  │ (timer tick rate) │            │
│  └─────┬─────┘  └────────┬─────────┘            │
│        │ trigger/         │ AUDC writes          │
│        │ note-off         │ (cycle-accurate)     │
│        ▼                  ▼                      │
│  ┌───────────────────────────────────────┐       │
│  │          PokeyPair (POKEY Emulator)   │       │
│  │  ┌─────────────────────────────────┐  │       │
│  │  │ Pokey (4 channels)              │  │       │
│  │  │ - Polynomial counters (5/9/17)  │  │       │
│  │  │ - DAC compression               │  │       │
│  │  │ - Sinc-interpolated delta buf   │  │       │
│  │  │ - IIR high-pass filter          │  │       │
│  │  └─────────────────────────────────┘  │       │
│  └────────────────┬──────────────────────┘       │
│                   │ PCM samples                  │
│                   ▼                              │
│            float32 numpy array                   │
└─────────────────────────────────────────────────┘
```

## Files

| File | Lines | Description |
|------|-------|-------------|
| `pokey.py` | 716 | Core POKEY emulator (PokeyChannel, Pokey, PokeyPair) |
| `vq_player.py` | 656 | VQ/RAW player + song sequencer + data loading |
| `test_pokey.py` | 570 | 125-assertion test suite |
| `__init__.py` | 32 | Package exports |

## Quick Start

### Direct VQ Preview (converter integration)
```python
from pokey_emulator import VQPlayer, render_vq_wav

# One-call WAV rendering
render_vq_wav(
    codebook=codebook_bytes,
    indices=index_stream_bytes,
    output_path='preview.wav',
    vector_size=8,
    audf_val=3,
)

# Frame-by-frame (real-time)
player = VQPlayer(sample_rate=44100)
player.load_vq_direct(codebook, indices, vector_size=8, audf_val=3)
while player.channels[0].active:
    pcm_float32 = player.render_frame()  # ~882 samples
    audio_output.write(pcm_float32)
```

### Song Playback (tracker integration)
```python
player = VQPlayer(sample_rate=44100)
player.load_from_tracker(song_obj, vq_result, vq_settings)
player.start_playback(songline=0, row=0)
while player.playing:
    pcm = player.render_frame()
    audio_output.write(pcm)
```

### Low-Level POKEY (register-level access)
```python
from pokey_emulator import PokeyPair, PAL_CYCLES_PER_FRAME

pp = PokeyPair()
pp.initialize(ntsc=False, stereo=False, sample_rate=44100)
pp.poke(0x0F, 0x00, 0)    # SKCTL=0 (init)
pp.poke(0x01, 0xAF, 0)    # AUDC1=pure tone vol 15
pp.poke(0x00, 100, 0)     # AUDF1=100
pp.poke(0x0F, 0x03, 0)    # SKCTL=3 (run)
pp.poke(0x09, 0x00, 0)    # STIMER

pp.start_frame()
# ... write registers at cycle-accurate positions ...
num = pp.end_frame(PAL_CYCLES_PER_FRAME)
pcm = pp.generate(num)    # list of signed 16-bit values
```

## Two Timing Domains

The player separates two independent clocks:

1. **Frame rate (50/60 Hz)**: Song sequencer advances rows, triggers notes,
   processes events. One `render_frame()` call = one frame.

2. **POKEY timer rate (~4-16 kHz)**: IRQ handler outputs one AUDC byte per
   tick. Timer period = `28 * (AUDF + 1)` cycles in standard 64 kHz mode.

Within each frame, the player computes timer tick positions and feeds
cycle-accurate AUDC writes to the POKEY emulator.

## Performance

Pure Python, no C extensions required:

- **108x real-time** on typical hardware (0.18 ms per 20 ms frame)
- ~125 AUDC register writes per frame per channel
- 882 PCM samples per frame at 44100 Hz / 50 fps

## VQ Data Flow

The player NEVER uses Atari memory addresses. Codebook offset tables
(`cb_offset_lo/hi`) are computed from `vector_size`:

```
VQ index stream → index byte → cb_offset[index] → codebook[offset + vo]
```

This avoids the Atari-address vs Python-offset mismatch that would occur
if using VQ_LO/VQ_HI tables from the ASM output directly.

## Running Tests

```bash
python test_pokey.py
```

## License

POKEY emulator algorithms: GPLv2+ (from ASAP by Piotr Fusik)
VQ player engine: follows project license
