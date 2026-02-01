# POKEY VQ Tracker - Beta 1

An experimental cross-platform music tracker for composing sample-based music targeting Atari XL/XE 8-bit computers.

## Features

- **3-channel polyphonic playback** using VQ-compressed samples
- **3 octaves** (C-1 to B-3) with pitch control
- **Pattern-based sequencing** with variable-length event encoding
- **Real-time audio preview** matching Atari output
- **Export to Atari executable** (.xex) via MADS assembler
- **ZIP-based project format** with embedded samples and VQ output
- **Multi-format audio import** (WAV, MP3, OGG, FLAC, M4A, etc.)
- **Timing analysis** to verify IRQ cycle budget before export
- **Optional volume control** (requires lower sample rate)

## Workflow

The recommended workflow for creating Atari music:

1. **Load Samples** - Add WAV/MP3/OGG files as instruments
2. **CONVERT** - Process samples through VQ compression
3. **Write Song** - Compose using patterns and the song editor
4. **ANALYZE** - Check IRQ timing feasibility
5. **BUILD** - Create Atari executable (.XEX)

Press **F4** in the tracker to see keyboard shortcuts including this workflow.

## Requirements

- Python 3.8+
- DearPyGui (`pip install dearpygui`)
- NumPy (`pip install numpy`)
- SoundDevice (`pip install sounddevice`)
- pydub (`pip install pydub`) - for multi-format audio (requires ffmpeg)
- MADS assembler (for building Atari executables)
- VQ Converter (for sample compression)

## Quick Start

1. Run the tracker: `python main.py`
2. Load audio samples (WAV, MP3, OGG, etc.) as instruments
3. Compose music using piano keyboard (Z-M, Q-P keys)
4. Convert samples: Song → VQ Convert
5. Build executable: Song → Build XEX

## Building Standalone Executable

To create a single executable file (no Python installation required):

### Windows
```batch
# Using Command Prompt
build.bat

# Using PowerShell
.\build.ps1

# Check dependencies only
build.bat check
.\build.ps1 -Check
```

### Linux / macOS
```bash
# Make script executable (first time only)
chmod +x build.sh

# Build
./build.sh

# Check dependencies only
./build.sh check
```

### Requirements for Building

1. **Python 3.8+** with pip
2. **PyInstaller** (installed automatically by build script)
3. **MADS assembler** in the appropriate `bin/` subdirectory:
   - Windows: `bin/windows_x86_64/mads.exe`
   - Linux: `bin/linux_x86_64/mads`
   - macOS Intel: `bin/macos_x86_64/mads`
   - macOS Apple Silicon: `bin/macos_aarch64/mads`

Download MADS from: http://mads.atari8.info/

### Output

The built executable will be in `dist/`:
- Windows: `dist/POKEY_VQ_Tracker.exe`
- Linux: `dist/POKEY_VQ_Tracker`
- macOS: `dist/POKEY VQ Tracker.app`

### Distribution Structure

To distribute the standalone executable, create a folder with:

```
my_tracker/
├── POKEY_VQ_Tracker       # The executable (or .exe on Windows)
├── asm/                   # ASM player templates (required for BUILD)
│   ├── song_player.asm
│   ├── common/
│   ├── tracker/
│   └── pitch/
├── bin/                   # MADS assembler (required for BUILD)
│   ├── linux_x86_64/mads
│   ├── macos_aarch64/mads
│   ├── macos_x86_64/mads
│   └── windows_x86_64/mads.exe
├── vq_converter/          # VQ converter (required for CONVERT)
│   └── pokey_vq/
├── README.md              # Optional documentation
└── UserGuide.md           # Optional documentation
```

The executable looks for `asm/`, `bin/`, and `vq_converter/` in the same directory.

## File Browser

The custom file browser supports:
- **Multi-select** with checkboxes
- **Audio preview** - click Play to hear samples before adding
- **Sorting** by name, size, or date
- **Folder mode** - select folders to import all audio files inside

## Project Format (.pvq)

Projects are saved as ZIP archives containing:

```
project.pvq (ZIP archive)
├── project.json      # Song data, editor state, VQ settings
├── samples/          # Embedded audio files (WAV)
│   ├── 00_piano.wav
│   └── 01_bass.wav
├── vq_output/        # VQ conversion output (if converted)
│   ├── VQ_CFG.asm
│   ├── VQ_BLOB.asm
│   └── ...
└── metadata.json     # Format version, timestamps
```

**Benefits:**
- Self-contained - share projects with all samples included
- Editor state preserved - resume exactly where you left off
- VQ output included - BUILD immediately after loading
- Multi-format support - import MP3/OGG, stored as WAV

## Keyboard Controls

### Note Entry (Pattern Editor)
- **Z-M row**: C-B (base octave)
- **S,D,G,H,J**: Sharp notes (C#,D#,F#,G#,A#)
- **Q-P row**: C-E (octave+1)
- **2,3,5,6,7,9,0**: Sharp notes (piano mode)
- **` (backtick)**: Note OFF (silence channel)
- **1**: Note OFF (tracker mode only)

### Keyboard Modes (Settings)
- **Piano mode** (default): Number keys play sharp notes
- **Tracker mode**: 1=Note OFF, 2-3=Select octave

### Octave Selection
- **F1/F2/F3**: Select octave 1/2/3 (always available)
- **\* (numpad)**: Octave up
- **- (minus)**: Octave down

### Navigation
- **Arrow keys**: Move cursor
- **Ctrl+Up/Down**: Jump by Step rows
- **Ctrl+Shift+Up/Down**: Increase/decrease Edit Step
- **Tab/Shift+Tab**: Switch channels
- **Page Up/Down**: Jump 16 rows
- **Home/End**: First/last row
- **Ctrl+Home/End**: First/last songline

### Editing
- **Delete**: Remove row (shift remaining rows up)
- **Insert**: Insert empty row (shift remaining rows down)
- **Backspace**: Clear cell and jump up by Step
- **[ / ]**: Previous/next instrument

### Playback
- **Space**: Play/Stop
- **Enter**: Preview current row
- **F4**: Show keyboard shortcuts
- **F5**: Play pattern
- **F6**: Play song from start
- **F7**: Play from current songline
- **F8**: Stop

## Pitch System

The tracker uses 8.8 fixed-point pitch multipliers:

| Note | Pitch Index | Multiplier |
|------|-------------|------------|
| C-1  | 0           | 1.0x       |
| C-2  | 12          | 2.0x       |
| C-3  | 24          | 4.0x       |

Samples should be recorded/prepared for playback at C-1 (1.0x speed).

## Timing Analysis

The **ANALYZE** button simulates Atari IRQ timing to detect potential playback issues before building. It reports:

- **Cycles per IRQ** based on sample rate
- **Per-row analysis** showing active channels and their cycle costs
- **Problem rows** that exceed the cycle budget
- **Recommendations** for fixing timing issues

### Optimization Modes

The **Optimize** setting controls CPU usage vs memory trade-off:

| Mode | Cycles/Channel | Codebook | Max Rate (3ch) |
|------|----------------|----------|----------------|
| **Speed** | ~58 | 4KB | 7917 Hz |
| **Size** | ~83 | 2KB | 5278 Hz |

**Speed mode** (default) uses full bytes with pre-baked POKEY bits, enabling faster sample rates. **Size mode** uses nibble-packed data for compact memory but limits maximum sample rate.

### Cycle Budget

The Atari CPU runs at 1.77 MHz (PAL). Each IRQ has limited cycles:

| Sample Rate | Available Cycles | Speed Mode | Size Mode |
|-------------|------------------|------------|-----------|
| 15834 Hz    | ~112             | ❌ Over    | ❌ Over   |
| 7917 Hz     | ~224             | ✅ OK      | ❌ Over   |
| 5278 Hz     | ~336             | ✅✅ Easy  | ✅ OK     |
| 3958 Hz     | ~448             | ✅✅ Easy  | ✅✅ Easy |

## Volume Control

Enable **Volume** checkbox in SONG INFO to include per-note volume in export.

**Requirements:**
- Sample rate ≤5757 Hz (adds ~10 cycles per active channel)
- Use ANALYZE to verify timing with volume enabled

When disabled, the volume column is hidden (data preserved). This saves cycles and allows higher sample rates.

## Working Directory

The tracker uses a `.tmp/` folder in the application directory:

```
.tmp/
├── tracker.lock      # Single-instance lock
├── samples/          # Imported/extracted samples
├── vq_output/        # VQ conversion results
└── build/            # Build artifacts
```

**Note:** Only one instance can run at a time to prevent conflicts.

## Project Structure

```
tracker_v3/
├── main.py           # Application entry point
├── data_model.py     # Song, Pattern, Instrument classes
├── audio_engine.py   # Real-time audio playback
├── file_io.py        # ZIP project format, audio import
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
