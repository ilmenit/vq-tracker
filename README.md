# Atari Sample Tracker

A cross-platform music tracker for composing sample-based music targeting Atari XL/XE 8-bit computers.

![Version](https://img.shields.io/badge/version-2.1-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![License](https://img.shields.io/badge/license-MIT-orange)

## Features

- **3-channel sample playback** with pitch control
- **Pattern-based sequencing** (RMT-style conventions)
- **WAV sample loading** (mono/stereo, any sample rate)
- **Real-time audio** with mute/solo per channel
- **Undo/Redo** support (100 levels)
- **Export to 6502 assembly** for Atari player
- **PAL/NTSC timing** modes

## Installation

```bash
# Clone or download the project
cd atari_tracker

# Install dependencies
pip install -r requirements.txt

# Run the tracker
python main.py
```

### Dependencies

| Package | Required | Description |
|---------|----------|-------------|
| dearpygui | Yes | GUI framework |
| numpy | Yes | Audio processing |
| sounddevice | Recommended | Audio playback |
| scipy | Optional | Better WAV support |

## Quick Start

1. **Load a sample**: Instrument → Load Sample... (or click "Load" button)
2. **Enter notes**: Use piano keys (Z-M = lower octave, Q-P = upper octave)
3. **Play**: Press Space or F5
4. **Save**: Ctrl+S

## Keyboard Shortcuts

### Navigation
| Key | Action |
|-----|--------|
| ↑/↓ | Move row up/down |
| ←/→ | Move column (Note/Ins/Vol) |
| Tab | Next channel |
| Shift+Tab | Previous channel |
| PgUp/PgDn | Jump 16 rows |
| Home/End | First/last row |
| Ctrl+Home | First songline |
| Ctrl+End | Last songline |

### Note Entry (Piano Layout)
```
Lower octave (base):
  S D   G H J     ← Black keys (C# D# F# G# A#)
Z X C V B N M     ← White keys (C D E F G A B)

Upper octave (+1):
  2 3   5 6 7   9 0     ← Black keys
Q W E R T Y U I O P     ← White keys
```

| Key | Action |
|-----|--------|
| * / Numpad* | Octave up |
| - / Numpad- | Octave down |
| [ / ] | Previous/next instrument |

### Editing
| Key | Action |
|-----|--------|
| 0-9, A-F | Enter hex value (Ins/Vol columns) |
| Delete | Clear cell |
| Backspace | Clear and move up |
| Insert | Insert row |
| Ctrl+Z | Undo |
| Ctrl+Y | Redo |
| Ctrl+C/X/V | Copy/Cut/Paste row |

### Playback
| Key | Action |
|-----|--------|
| Space | Play/Stop from cursor |
| F5 | Play pattern from start |
| F6 | Play song from start |
| F7 | Play from current songline |
| F8 | Stop |
| Enter | Preview current row |

### File Operations
| Key | Action |
|-----|--------|
| Ctrl+N | New project |
| Ctrl+O | Open project |
| Ctrl+S | Save project |

## Project Structure

```
atari_tracker/
├── main.py          # Entry point, UI creation
├── constants.py     # Configuration and mappings
├── data_model.py    # Song, Pattern, Row, Instrument
├── audio_engine.py  # Real-time playback
├── file_io.py       # Project/sample loading, ASM export
├── state.py         # Application state, undo manager
├── operations.py    # All editing operations
├── keyboard.py      # Keyboard input handling
├── ui_theme.py      # Theme and colors
├── ui_dialogs.py    # Dialog windows
├── requirements.txt
└── README.md
```

## File Format

Projects are saved as `.pvq` files (gzip-compressed JSON).

```json
{
  "version": 2,
  "metadata": {
    "title": "My Song",
    "author": "Composer",
    "speed": 6,
    "system": 50
  },
  "songlines": [[0, 1, 2], [0, 1, 3]],
  "patterns": [...],
  "instruments": [...]
}
```

## Hardware Constraints

Based on Atari XL/XE POKEY chip:

| Feature | Limit |
|---------|-------|
| Channels | 3 (Ch4 reserved) |
| Volume | 0-15 per channel |
| Notes | 48 (C1-B4, 4 octaves) |
| Patterns | 256 max |
| Rows per pattern | 1-256 |
| Songlines | 256 max |
| Instruments | 128 max |
| Speed | 1-255 (VBLANK ticks/row) |

### Speed Reference

| Speed | Rows/sec (PAL) | ~BPM |
|-------|----------------|------|
| 3 | 16.67 | 250 |
| 4 | 12.50 | 188 |
| 5 | 10.00 | 150 |
| **6** | **8.33** | **125** |
| 8 | 6.25 | 94 |
| 12 | 4.17 | 63 |

## Export

Export to ASM generates:
- `song_metadata.asm` - Title, speed, counts
- `song_data.asm` - Songline definitions
- `pattern_data.asm` - Pattern data with address tables
- `instrument_data.asm` - Instrument references

Sample data requires VQ encoding (separate tool).

## Troubleshooting

**No audio**: Install sounddevice (`pip install sounddevice`)

**Can't load WAV**: Install scipy for better format support

**GUI issues**: Ensure dearpygui ≥1.9.0

## License

MIT License - See LICENSE file

## Acknowledgments

- Based on RMT (Raster Music Tracker) conventions
- Inspired by Atari POKEY chip capabilities
