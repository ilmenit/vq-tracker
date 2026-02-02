# POKEY VQ Tracker - User Guide

## What Is This?

**POKEY VQ Tracker** is an experimental music tracker for creating sample-based music on the Atari 8-bit computer (XL/XE). Unlike traditional POKEY trackers that use synthesized waveforms, this one plays actual audio samples with variable pitch control — enabling realistic instruments like piano, bass, drums, and strings.

### The Innovation

Playing samples on an Atari isn't new. Various players have demonstrated single-channel sample playback at reasonable quality. But playing **three independent channels simultaneously**, each with **real-time pitch control**, on a **stock 64KB Atari without extended memory** — that's the challenge this project tackles.

The magic behind this is **Vector Quantization (VQ)** compression. Your audio samples are compressed into a codebook of small waveform patterns. Instead of storing every sample individually, we store indices into this codebook. The Atari's 1.77 MHz 6502 CPU then streams these patterns in real-time while handling pitch shifting across three independent channels.

### The Technical Challenge

The PAL Atari 8-bit runs at approximately **1.77 MHz** (1,773,447 Hz) with about **35,568 CPU cycles per video frame** (50 Hz). NTSC machines run slightly faster at 1.79 MHz with 29,859 cycles per frame at 60 Hz. That might sound like plenty, but consider what sample playback demands — and that ANTIC steals cycles for screen refresh.

The CPU must output audio samples at rates of 4,000–8,000 Hz (or higher for better quality). At 5,278 Hz, that's over **100 IRQ interrupts per frame**. Each IRQ must:

- Output 3 audio samples to POKEY registers (one per channel)
- Advance 3 pitch accumulators using 8.8 fixed-point arithmetic
- Handle vector boundary crossings when the compressed stream advances
- Optionally apply volume scaling
- All within roughly 100-300 cycles depending on settings

When all three channels cross a vector boundary simultaneously (worst case), the IRQ handler must fetch new codebook pointers for each channel. This is where careful optimization becomes critical.

Additionally, when the display is enabled, ANTIC steals approximately 9-15% of CPU cycles for memory refresh, display list fetching, and screen data access. The analyzer accounts for this when estimating timing margins.

**Our key constraint:** Everything runs from the base 64KB RAM. No extended memory, no cartridge ROM, no bank switching. This keeps the player compatible with all Atari XL/XE machines but limits total sample storage to what fits alongside the player code, song data, and codebook.

---

## Installation & Requirements

### Software Requirements

**For running the standalone executable (POKEY_VQ_Tracker.exe):**
- **MADS assembler** — `mads.exe` in `bin\windows_x86_64\`
- **vq_converter** — the VQ compression tool in `vq_converter\` folder

**vq_converter options (one required for CONVERT to work):**
1. **Standalone executable** (recommended): Place `vq_converter.exe` in `vq_converter\` folder
2. **Python-based**: Requires Python 3.8+ with numpy, scipy, soundfile installed

**Optional tools:**
- **Altirra emulator** — for auto-launching builds
- **FFmpeg** — for MP3/OGG/FLAC/M4A import

**For development (running from source):**
- **Python 3.8+** with the following packages:
  - DearPyGui (GUI framework)
  - NumPy (audio processing)
  - SciPy (WAV file handling)
  - pydub (audio format conversion)

### Audio Format Support

| Format | Requirement |
|--------|-------------|
| WAV | Always supported (built-in) |
| MP3, OGG, FLAC, M4A | Requires FFmpeg |

**Windows users:** Place `ffmpeg.exe` and `ffprobe.exe` in the `bin\windows_x86_64\` folder. Download from: https://www.gyan.dev/ffmpeg/builds/

**Linux/macOS users:** Install ffmpeg via your package manager (`apt install ffmpeg`, `brew install ffmpeg`).

### Folder Structure

```
tracker_folder/
├── POKEY_VQ_Tracker.exe      (or main.py for development)
├── asm/                      (ASM templates - required for BUILD)
├── bin/
│   └── windows_x86_64/
│       ├── mads.exe          (required for BUILD)
│       ├── ffmpeg.exe        (optional - audio import)
│       └── ffprobe.exe       (optional - audio import)
└── vq_converter/
    ├── vq_converter.exe      (option 1: standalone)
    └── pokey_vq/             (option 2: Python module)
```

### Setup

1. Extract the tracker to a folder
2. Place `mads.exe` in `bin\windows_x86_64\`
3. Set up vq_converter (exe or Python with dependencies)
4. (Optional) Add FFmpeg for MP3/OGG/FLAC import
5. (Optional) Configure Altirra path for auto-launch
6. Run: `POKEY_VQ_Tracker.exe` (or `python main.py`)

---

## Quick Start Workflow

### 1. Add Samples

**File → Add Sample** or **File → Add Folder**

Import WAV, MP3, OGG, or FLAC files. They're automatically converted to mono WAV and stored in your project. The tracker creates working copies in the `.tmp/samples/` folder, so your originals remain untouched.

**Sample Selection Tips:**
- **Short samples work best** — long sustained sounds consume memory quickly
- **Punchy attacks** — drums, plucks, and staccato instruments compress well
- **Avoid heavy reverb** — reverb tails eat space and sound muddy after compression
- **Mono is fine** — stereo is converted to mono anyway

*Samples are embedded in your project file (.pvq), so the originals can be moved or deleted after import.*

### 2. Convert

Click **CONVERT** in the Build section.

This runs the VQ compression algorithm, transforming your samples into Atari-compatible format. The conversion window shows:

- Progress for each sample being processed
- Compression ratio achieved
- Final data size (codebook + indices)
- Any warnings about quality or size

After conversion, toggle **"Use Converted"** to preview how your samples will sound on the Atari. This plays the VQ-compressed versions through your computer's audio, giving you an accurate preview before building.

### 3. Compose

The pattern editor works like a classic tracker:

- **Piano keyboard layout** (Z-M for lower octave, Q-P for upper) enters notes
- **F1, F2, F3** select octave 1, 2, or 3
- **Arrow keys** navigate the grid
- **Tab** moves between channels
- **Space** toggles play/stop

**Song Structure:**
- **Patterns** contain sequences of notes for a single channel
- **Songlines** define which pattern plays on each of the 3 channels
- Patterns can be reused across songlines and channels

### 4. Analyze

Click **ANALYZE** to estimate CPU usage.

The analyzer calculates cycle budgets based on your current settings:
- Available cycles per IRQ at your sample rate
- Typical case (no boundary crossings)
- Worst case (all 3 channels cross boundaries simultaneously)
- Safety margin percentage

**Understanding the Results:**
- **Green/Safe**: Plenty of headroom, should work reliably
- **Yellow/Tight**: May work but could have occasional glitches
- **Red/Over**: Will definitely glitch — reduce settings

*Important: The analyzer provides estimates based on theoretical cycle counts. Actual behavior may vary slightly. Future versions will include cycle-accurate emulation for precise verification.*

### 5. Build & Run

Click **BUILD & RUN** to:

1. **Validate** — Check song data for errors (invalid notes, missing samples)
2. **Export** — Generate 6502 assembly source files
3. **Compile** — Run MADS assembler to create XEX executable
4. **Launch** — Open the XEX in Altirra emulator

If everything works, you'll hear your music playing on the (emulated) Atari!

**If BUILD succeeds but audio glitches in Altirra**, your settings are too demanding for the CPU. See the optimization section below.

---

## The User Interface

### Menu Bar

**File Menu**
| Item | Shortcut | Description |
|------|----------|-------------|
| New | Ctrl+N | Create empty project |
| Open | Ctrl+O | Load .pvq project file |
| Save | Ctrl+S | Save current project |
| Save As | Ctrl+Shift+S | Save to new filename |
| Add Sample | | Import individual audio file |
| Add Folder | | Import all samples from folder |
| Recent Files | | Quick access to recent projects |
| Exit | Alt+F4 | Close the application |

**Edit Menu**
| Item | Shortcut | Description |
|------|----------|-------------|
| Undo | Ctrl+Z | Undo last action |
| Redo | Ctrl+Y | Redo undone action |
| Cut | Ctrl+X | Cut selection |
| Copy | Ctrl+C | Copy selection |
| Paste | Ctrl+V | Paste at cursor |
| Delete | Del | Clear selection |
| Select All | Ctrl+A | Select entire pattern |

**Song Menu**
| Item | Description |
|------|-------------|
| Add Songline | Append new songline at end |
| Insert Songline | Insert at current position |
| Delete Songline | Remove current songline |
| Clone Songline | Duplicate current songline |

**Pattern Menu**
| Item | Description |
|------|-------------|
| New Pattern | Create empty pattern |
| Clone Pattern | Duplicate current pattern |
| Delete Pattern | Remove pattern (if unused) |
| Transpose +1/-1 | Shift notes by semitone |
| Transpose +12/-12 | Shift notes by octave |

**Help Menu**
| Item | Description |
|------|-------------|
| Keyboard Shortcuts | Show key reference |
| About | Version and credits |

---

### Main Window Sections

#### Song Info (Top Left)

| Field | Description |
|-------|-------------|
| **Title** | Song name (shown in player, saved in project) |
| **Author** | Composer name |
| **Speed** | VBLANK ticks per row (1-255). Lower = faster. Default: 6 |

**CPU Options** (checkboxes):
| Option | Default | Effect |
|--------|---------|--------|
| **Vol** | Off | Enable per-note volume control. Adds ~11 cycles per channel but allows dynamic expression. |
| **Screen** | Off | Show playback display (SONG/ROW/SPD) during playback. Costs ~15% CPU due to ANTIC DMA. When off, screen blanks during playback for maximum CPU. |
| **Key** | Off | Enable keyboard control during playback (SPACE to stop, R to restart). When off, runs in play-once mode with minimal overhead. |

*For maximum CPU headroom, keep all three options disabled.*

#### Instruments Panel (Top Center)

Lists all loaded instruments with:
- **Index number** (00-7F)
- **Name** (editable)
- **Selection highlight** showing current instrument

**Buttons:**
| Button | Action |
|--------|--------|
| **+** | Add empty instrument slot |
| **-** | Remove selected instrument |
| **Rename** | Change instrument name |

Click an instrument to select it for note entry. Double-click to rename.

#### Editor Settings (Top Right)

| Setting | Description |
|---------|-------------|
| **Oct** | Current octave for keyboard entry (1-4). Also set with F1-F4. |
| **Step** | Cursor advance after note entry (0-16). 0 = no advance. |
| **Vol** | Default volume for new notes (0-F in hex, 0-15 in decimal) |

**Display Options:**
| Option | Description |
|--------|-------------|
| **HEX** | Toggle hexadecimal display for numbers |
| **Follow** | Cursor follows playback position |

#### Song Editor (Left Panel)

Shows the song structure as a list of songlines:
```
Ln  C1  C2  C3
00  00  01  02
01  00  01  03
02  04  05  02
```

- **Ln**: Songline number
- **C1/C2/C3**: Pattern assigned to each channel

Click a songline to edit its patterns. Use arrow keys to navigate. Press Enter or double-click pattern numbers to change assignments.

#### Pattern Editor (Center/Bottom)

The main composition area showing three channel columns:

```
Row │ CH1 [Ptn 00]  │ CH2 [Ptn 01]  │ CH3 [Ptn 02]  │
────┼───────────────┼───────────────┼───────────────┤
 00 │ C-2  00   F   │ ---  --   -   │ D-3  01   8   │
 01 │ ---  --   -   │ E-2  00   F   │ ---  --   -   │
 02 │ D-2  --   C   │ ---  --   -   │ ---  --   -   │
```

Each cell shows:
- **Note**: Pitch and octave (C-2, F#3, etc.) or `---` for empty
- **Ins**: Instrument number or `--` for none
- **Vol**: Volume (0-F) or `-` for default

**Navigation:**
| Key | Action |
|-----|--------|
| ↑/↓ | Move up/down rows |
| ←/→ | Move between columns (Note/Ins/Vol) |
| Tab | Next channel |
| Shift+Tab | Previous channel |
| Page Up/Down | Jump 16 rows |
| Home/End | First/last row |

**Editing:**
| Key | Action |
|-----|--------|
| Z-M | Enter notes (lower octave) |
| Q-P | Enter notes (upper octave) |
| S,D,G,H,J | Enter sharps/flats |
| 0-9, A-F | Enter values (instrument/volume columns) |
| Delete | Clear current cell |
| Backspace | Clear and move up |
| . (period) | Note OFF (silence the channel) |

#### Build Section (Bottom Right)

**VQ Conversion Settings:**
| Setting | Range | Description |
|---------|-------|-------------|
| **Rate** | 1000-20000 | POKEY sample rate in Hz. Higher = better quality, more CPU. |
| **Vec** | 2-16 | Vector size for VQ compression. Smaller = sharper attacks, more CPU. |
| **Smooth** | 0-100 | Anti-aliasing amount. Higher = smoother but softer transients. |
| **Enhance** | 0-100 | High-frequency boost to compensate for compression. |

**Optimize Mode:**
| Mode | Description |
|------|-------------|
| **Speed** | Larger IRQ code, faster execution (~63 cycles typical) |
| **Size** | Smaller IRQ code, slower execution (~83 cycles typical) |

**Buttons:**
| Button | Action |
|--------|--------|
| **CONVERT** | Run VQ compression on all samples |
| **ANALYZE** | Estimate CPU usage with current settings |
| **BUILD & RUN** | Compile and launch in Altirra |

**Checkbox:**
| Option | Description |
|--------|-------------|
| **Use Converted** | Preview VQ-compressed audio instead of originals |

#### Status Bar (Bottom)

Shows:
- Current operation status
- Error messages
- Playback state
- File modified indicator (*)

---

## Keyboard Reference

### Note Entry (Piano Layout)

```
Upper Row (current octave + 1):
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│ 2 │ 3 │   │ 5 │ 6 │ 7 │   │ 9 │ 0 │   │ ← Black keys
│C# │D# │   │F# │G# │A# │   │C# │D# │   │
├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
│ Q │ W │ E │ R │ T │ Y │ U │ I │ O │ P │ ← White keys
│ C │ D │ E │ F │ G │ A │ B │ C │ D │ E │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

Lower Row (current octave):
┌───┬───┬───┬───┬───┬───┬───┐
│ S │ D │   │ G │ H │ J │   │ ← Black keys
│C# │D# │   │F# │G# │A# │   │
├───┼───┼───┼───┼───┼───┼───┤
│ Z │ X │ C │ V │ B │ N │ M │ ← White keys
│ C │ D │ E │ F │ G │ A │ B │
└───┴───┴───┴───┴───┴───┴───┘
```

### Playback Controls

| Key | Action |
|-----|--------|
| Space | Play/Stop from cursor position |
| F5 | Play current pattern from start |
| F6 | Play entire song from start |
| F7 | Play song from current songline/row |
| F8 | Stop playback |
| Enter | Preview current row (single step) |

### Octave & Instrument

| Key | Action |
|-----|--------|
| F1 | Set octave 1 |
| F2 | Set octave 2 |
| F3 | Set octave 3 |
| F4 | Set octave 4 |
| * | Octave up |
| / | Octave down |
| [ | Previous instrument |
| ] | Next instrument |

### Selection

| Key | Action |
|-----|--------|
| Shift + Arrows | Extend selection |
| Ctrl + A | Select all in pattern |
| Ctrl + C | Copy selection |
| Ctrl + X | Cut selection |
| Ctrl + V | Paste at cursor |

---

## CPU Optimization Guide

The Atari has limited CPU time. Here's how to tune your project for reliable playback.

### Sample Rate (Rate)

The sample rate determines audio quality and CPU load:

| Rate | Quality | CPU Load | Notes |
|------|---------|----------|-------|
| 7917 Hz | Very Good | High | For 1-2 channels or simple songs |
| **5278 Hz** | Good | **Moderate** | **Recommended default** |
| 3945 Hz | Acceptable | Low | Safe for complex songs |
| 2636 Hz | Lo-fi | Very Low | Chiptune aesthetic |

*Rule of thumb: Start with 5278 Hz. Only increase if you have headroom.*

### Vector Size (Vec)

Vector size affects attack sharpness and boundary crossing frequency:

| Size | Quality | CPU Load | Best For |
|------|---------|----------|----------|
| 2 | Sharpest attacks | Highest | Drums, percussion |
| 4 | Very good | High | General use (if CPU allows) |
| **8** | Good balance | **Moderate** | **Recommended default** |
| 16 | Softer attacks | Low | Pads, sustained sounds |

Smaller vectors preserve transients but cause more frequent boundary crossings where the CPU must fetch new codebook entries.

### Optimize Mode

| Mode | IRQ Code | Typical Cycles | Worst Case | Use When |
|------|----------|----------------|------------|----------|
| **Speed** | ~200 bytes | 63 cycles | 125 cycles | Default choice |
| Size | ~150 bytes | 83 cycles | 145 cycles | RAM is tight |

Speed mode unrolls loops for faster execution. Size mode uses loops to save RAM.

### Song Options Impact

| Option | Cycles Added | Recommendation |
|--------|--------------|----------------|
| Vol (Volume) | +11 per channel | Disable unless needed |
| Screen | +15% total (ANTIC DMA) | Disable for complex songs |
| Key | +35-55 total | Disable for play-once mode |

### Quick Optimization Checklist

If your song glitches:

1. ☐ Reduce **Rate** to 5278 Hz or lower
2. ☐ Increase **Vec** to 8 or 16
3. ☐ Disable **Screen** option
4. ☐ Disable **Vol** option if not using volume changes
5. ☐ Disable **Key** option
6. ☐ Try **Speed** optimize mode
7. ☐ Reduce simultaneous notes (avoid 3-channel chords on every row)

---

## Understanding the Atari Output

### Display During Playback

If **Screen** is enabled, the Atari shows:

```
SONG:00 ROW:00 SPD:06
```

- **SONG**: Current songline in hex (00-FF)
- **ROW**: Current row within patterns (00-3F typically)
- **SPD**: Speed setting (ticks per row)

If **Screen** is disabled, the display blanks during playback (black screen). This is normal and saves ~15% CPU.

### Background Colors

| Color | Meaning |
|-------|---------|
| Black | Stopped / Idle |
| Green | Playing |
| Red flash | Error condition |

### Controls on Atari

If **Key** is enabled:
- **SPACE**: Stop playback
- **R**: Restart from beginning

If **Key** is disabled, the song plays once and stops. No keyboard input is processed during playback.

---

## Project Files

### File Types

| Extension | Description |
|-----------|-------------|
| `.pvq` | Complete project archive (song + samples) |
| `.xex` | Compiled Atari executable |

### Project Structure

The `.pvq` file is a ZIP archive containing:
```
project.json      - Song data, patterns, songlines
metadata.json     - Version info, timestamps
samples/          - Embedded WAV files
  00_Piano.wav
  01_Bass.wav
  ...
```

### Working Directory

The tracker uses a `.tmp/` folder for working files:
```
.tmp/
  samples/        - Working copies of imported samples
  vq_output/      - VQ conversion results
  build/          - Compiled ASM and XEX files
  autosave/       - Automatic backups
```

This folder can be safely deleted — it's regenerated as needed.

### Autosave

Projects are automatically saved every 30 seconds (if modified) to:
```
.tmp/autosave/autosave_SongTitle_YYYYMMDD_HHMMSS.pvq
```

The 20 most recent autosaves are kept.

---

## Troubleshooting

### Audio Problems

**Glitches, pops, or dropouts**
- Reduce **Rate** (try 5278 Hz or lower)
- Increase **Vec** (try 8 or 16)
- Disable **Screen** option
- Disable **Vol** if not needed
- Check ANALYZE results — are you over budget?

**No sound at all**
- Is Altirra audio enabled?
- Are samples loaded? (Check instrument list)
- Did CONVERT complete successfully?
- Check for errors in BUILD log

**"Use Converted" sounds bad**
- VQ compression is lossy — some quality loss is expected
- Try lower **Smooth** values for punchier sound
- Short, simple samples compress better than complex ones
- Very quiet passages may become silent

### Build Problems

**MADS not found**
- Install MADS assembler
- Add to system PATH, or place in tracker folder

**Altirra doesn't launch**
- Check Altirra path in settings
- Ensure .xex file was created (check `.tmp/build/`)

**Assembly errors**
- Check BUILD log for specific line numbers
- Usually indicates a data validation issue
- Report persistent errors as bugs

### Conversion Problems

**Conversion takes very long**
- Large samples take longer
- Try reducing sample length before import
- VQ compression is CPU-intensive

**Output files too large**
- Reduce number of instruments
- Use shorter samples
- Increase **Vec** size (fewer vectors = smaller indices)

---

## Future Possibilities

This is **Beta 1** — an experimental first release. The foundation is working, but there's enormous potential for improvement:

### Planned Features

**Cycle-Accurate Emulation**
Currently, ANALYZE provides estimates. A future version will include actual 6502 emulation in the tracker itself, showing exact cycle counts per frame and highlighting problem areas in real-time as you compose.

**Extended Memory Support**
The current player uses only base 64KB RAM. Adding support for extended memory (130XE banks, cartridge ROM) would dramatically increase available sample storage while keeping the playback engine in main RAM.

**Dynamic Sample Optimization**
Analyze which note/pitch combinations your song actually uses, then pre-render those specific pitches at conversion time. This could eliminate runtime pitch calculation entirely for many songs, dramatically reducing CPU load.

**Multi-Codebook Approach**
Instead of one global codebook for all samples, use instrument-specific codebooks. This improves compression quality for diverse sample sets (drums vs. strings vs. bass).

**Virtual Instruments**
Pre-mix multiple samples into combined "virtual instruments" at conversion time. For example, a chord could be a single mixed sample instead of three separate channels.

**Envelope Support**
Volume automation without per-note overhead — fade-ins, fade-outs, and attack/decay curves baked into the sample stream.

**Effect Commands**
Pitch slides, arpeggios, vibrato — pre-computed into the VQ stream rather than calculated at runtime.

### Platform Expansion

- **NTSC timing** support (60 Hz instead of PAL 50 Hz)
- **Stereo POKEY** output for dual-POKEY machines
- **Integration** with other Atari sound engines

---

## Technical Notes

### Why Vector Quantization?

Traditional sample playback stores raw sample values (4-bit for POKEY). VQ instead stores indices into a codebook of pre-computed vectors.

**Advantages:**
- Better compression than raw samples
- Fast playback — just table lookups
- Codebook can be optimized per sample set

**Trade-offs:**
- Lossy compression — quality depends on codebook size
- Boundary crossings add CPU overhead
- Fixed vector sizes may not suit all material

### POKEY Audio Registers

The player uses POKEY in "volume-only" mode:
- **AUDC1-3**: Volume registers (bits 0-3 = volume, bit 4 = mode)
- **AUDF1-3**: Set to constant values (frequency divisors for IRQ timing)
- **AUDCTL**: Audio control (clock selection)

Each IRQ writes new volume values to simulate waveforms.

### Memory Layout

Typical memory map for a compiled song:
```
$2000-$2FFF  Player code, tables, display list
$3000-$4FFF  VQ codebook (vector data)
$5000-$7FFF  Sample indices (VQ streams)
$8000-$BFFF  (Available for more data if needed)
$C000-$FFFF  OS ROM / hardware
```

---

## Credits & Acknowledgments

**POKEY VQ Tracker** builds on decades of Atari audio experimentation:

- The Atari community's extensive work on sample playback
- MADS assembler by Tomasz Biela
- Altirra emulator by Avery Lee
- DearPyGui framework
- NumPy/SciPy for audio processing

---

## Version History

**Beta 1** (Current)
- Initial public release
- 3-channel polyphonic playback with pitch control
- VQ compression with adjustable parameters
- Pattern-based song editor
- CPU budget analyzer
- One-click build and run

---

*Happy tracking! 🎵*

*Questions, bugs, or music to share? Find us on AtariAge!*
