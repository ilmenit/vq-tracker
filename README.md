# Atari Sample Tracker v3.0

A cross-platform music tracker for composing sample-based music targeting Atari XL/XE 8-bit computers.

## Features

- **3-channel polyphonic playback** using VQ-compressed samples
- **3 octaves** (C-1 to B-3) with pitch control
- **Pattern-based sequencing** with variable-length event encoding
- **Real-time audio preview** matching Atari output
- **Export to Atari executable** (.xex) via MADS assembler

## Requirements

- Python 3.8+
- DearPyGui (`pip install dearpygui`)
- NumPy (`pip install numpy`)
- SoundDevice (`pip install sounddevice`)
- MADS assembler (for building Atari executables)
- VQ Converter (for sample compression)

## Quick Start

1. Run the tracker: `python main.py`
2. Load WAV samples as instruments
3. Compose music using piano keyboard (Z-M, Q-P keys)
4. Convert samples: Song → VQ Convert
5. Build executable: Song → Build XEX

## Keyboard Controls

### Note Entry (Pattern Editor)
- **Z-M row**: C-B (base octave)
- **S,D,G,H,J**: Sharp notes (C#,D#,F#,G#,A#)
- **Q-P row**: C-E (octave+1)
- **2,3,5,6,7,9,0**: Sharp notes (octave+1)

### Navigation
- **Arrow keys**: Move cursor
- **Tab/Shift+Tab**: Switch channels
- **Page Up/Down**: Jump 16 rows
- **Home/End**: First/last row

### Playback
- **Space**: Play/Stop
- **Enter**: Preview current row

## Pitch System

The tracker uses 8.8 fixed-point pitch multipliers:

| Note | Pitch Index | Multiplier |
|------|-------------|------------|
| C-1  | 0           | 1.0x       |
| C-2  | 12          | 2.0x       |
| C-3  | 24          | 4.0x       |

Samples should be recorded/prepared for playback at C-1 (1.0x speed).

## File Formats

- **.pvq**: Project file (gzip-compressed JSON)
- **.xex**: Atari executable

## Project Structure

```
tracker_v3/
├── main.py           # Application entry point
├── data_model.py     # Song, Pattern, Instrument classes
├── audio_engine.py   # Real-time audio playback
├── build.py          # XEX build system
├── constants.py      # Configuration constants
├── asm/              # 6502 assembly sources
│   ├── song_player.asm
│   ├── tracker/      # IRQ handler and API
│   ├── pitch/        # Pitch tables
│   └── common/       # Shared includes
└── EXPORT_FORMAT.md  # Binary format documentation
```

## License

MIT License
