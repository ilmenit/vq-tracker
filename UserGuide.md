# POKEY VQ Tracker - User Guide

## What Is This?

**POKEY VQ Tracker** is an experimental music tracker for creating sample-based music on the Atari 8-bit computer (XL/XE). Unlike traditional POKEY trackers that use synthesized waveforms, this one plays actual audio samples with variable pitch control â€” enabling realistic instruments like piano, bass, drums, and strings.

### The Innovation

Playing samples on an Atari isn't new. Various players have demonstrated single-channel sample playback at reasonable quality. But playing **four independent channels simultaneously**, each with **real-time pitch control**, on a **stock 64KB Atari without extended memory** â€” that's the challenge this project tackles.

The magic behind this is **Vector Quantization (VQ)** compression. Your audio samples are compressed into a codebook of small waveform patterns. Instead of storing every sample individually, we store indices into this codebook. The Atari's 1.77 MHz 6502 CPU then streams these patterns in real-time while handling pitch shifting across four independent channels.

### The Technical Challenge

The PAL Atari 8-bit runs at approximately **1.77 MHz** (1,773,447 Hz) with about **35,568 CPU cycles per video frame** (50 Hz). NTSC machines run slightly faster at 1.79 MHz with 29,859 cycles per frame at 60 Hz. That might sound like plenty, but consider what sample playback demands â€” and that ANTIC steals cycles for screen refresh.

The CPU must output audio samples at rates of 4,000â€“8,000 Hz (or higher for better quality). At 5,278 Hz, that's over **100 IRQ interrupts per frame**. Each IRQ must:

- Output 4 audio samples to POKEY registers (one per channel)
- Advance 4 pitch accumulators using 8.8 fixed-point arithmetic
- Handle vector boundary crossings when the compressed stream advances
- Optionally apply volume scaling
- All within roughly 100-300 cycles depending on settings

When all four channels cross a vector boundary simultaneously (worst case), the IRQ handler must fetch new codebook pointers for each channel. This is where careful optimization becomes critical.


**Our key constraint:** Everything runs from the base 64KB RAM. No extended memory, no cartridge ROM, no bank switching. This keeps the player compatible with all Atari XL/XE machines but limits total sample storage to what fits alongside the player code, song data, and codebook.

---

## Installation & Requirements

### Software Requirements

**For running the standalone executable (POKEY_VQ_Tracker.exe):**
- **MADS assembler** â€” `mads.exe` in `bin\windows_x86_64\`
- **vq_converter** â€” the VQ compression tool in `vq_converter\` folder

**vq_converter options (one required for CONVERT to work):**
1. **Standalone executable** (recommended): Place `vq_converter.exe` in `vq_converter\` folder
2. **Python-based**: Requires Python 3.8+ with numpy, scipy, soundfile installed

**Optional tools:**
- **Altirra emulator** â€” for auto-launching builds
- **FFmpeg** â€” for MP3/OGG/FLAC/M4A import

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
â”œâ”€â”€ POKEY_VQ_Tracker.exe      (or main.py for development)
â”œâ”€â”€ asm/                      (ASM templates - required for BUILD)
â”œâ”€â”€ bin/
â”‚   â””â”€â”€ windows_x86_64/
â”‚       â”œâ”€â”€ mads.exe          (required for BUILD)
â”‚       â”œâ”€â”€ ffmpeg.exe        (optional - audio import)
â”‚       â””â”€â”€ ffprobe.exe       (optional - audio import)
â””â”€â”€ vq_converter/
    â”œâ”€â”€ vq_converter.exe      (option 1: standalone)
    â””â”€â”€ pokey_vq/             (option 2: Python module)
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

**File â†’ Add Sample** or **File â†’ Add Folder**

Import WAV, MP3, OGG, or FLAC files. They're automatically converted to mono WAV and stored in your project. The tracker creates working copies in the `.tmp/samples/` folder, so your originals remain untouched.

**Sample Selection Tips:**
- **Short samples work best** â€” long sustained sounds consume memory quickly
- **Punchy attacks** â€” drums, plucks, and staccato instruments compress well
- **Avoid heavy reverb** â€” reverb tails eat space and sound muddy after compression
- **Mono is fine** â€” stereo is converted to mono anyway

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
- **Songlines** define which pattern plays on each of the 4 channels
- Patterns can be reused across songlines and channels

### 4. Build & Run

Click **BUILD & RUN** to:

1. **Validate** â€” Check song data for errors (invalid notes, missing samples)
2. **Export** â€” Generate 6502 assembly source files
3. **Compile** â€” Run MADS assembler to create XEX executable
4. **Launch** â€” Open the XEX in Altirra emulator

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
| **Oct** | Current octave for keyboard entry (1-3). Also set with F1-F3. |
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

The main composition area showing four channel columns:

```
Row â”‚ CH1 [Ptn 00]  â”‚ CH2 [Ptn 01]  â”‚ CH3 [Ptn 02]  â”‚
â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
 00 â”‚ C-2  00   F   â”‚ ---  --   -   â”‚ D-3  01   8   â”‚
 01 â”‚ ---  --   -   â”‚ E-2  00   F   â”‚ ---  --   -   â”‚
 02 â”‚ D-2  --   C   â”‚ ---  --   -   â”‚ ---  --   -   â”‚
```

Each cell shows:
- **Note**: Pitch and octave (C-2, F#3, etc.) or `---` for empty
- **Ins**: Instrument number or `--` for none
- **Vol**: Volume (0-F) or `-` for default

**Navigation:**
| Key | Action |
|-----|--------|
| â†‘/â†“ | Move up/down rows |
| â†/â†’ | Move between columns (Note/Ins/Vol) |
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

**Buttons:**
| Button | Action |
|--------|--------|
| **CONVERT** | Run VQ compression on all samples |
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
â”Œâ”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”
â”‚ 2 â”‚ 3 â”‚   â”‚ 5 â”‚ 6 â”‚ 7 â”‚   â”‚ 9 â”‚ 0 â”‚   â”‚ â† Black keys
â”‚C# â”‚D# â”‚   â”‚F# â”‚G# â”‚A# â”‚   â”‚C# â”‚D# â”‚   â”‚
â”œâ”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¤
â”‚ Q â”‚ W â”‚ E â”‚ R â”‚ T â”‚ Y â”‚ U â”‚ I â”‚ O â”‚ P â”‚ â† White keys
â”‚ C â”‚ D â”‚ E â”‚ F â”‚ G â”‚ A â”‚ B â”‚ C â”‚ D â”‚ E â”‚
â””â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”˜

Lower Row (current octave):
â”Œâ”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”¬â”€â”€â”€â”
â”‚ S â”‚ D â”‚   â”‚ G â”‚ H â”‚ J â”‚   â”‚ â† Black keys
â”‚C# â”‚D# â”‚   â”‚F# â”‚G# â”‚A# â”‚   â”‚
â”œâ”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¼â”€â”€â”€â”¤
â”‚ Z â”‚ X â”‚ C â”‚ V â”‚ B â”‚ N â”‚ M â”‚ â† White keys
â”‚ C â”‚ D â”‚ E â”‚ F â”‚ G â”‚ A â”‚ B â”‚
â””â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”´â”€â”€â”€â”˜
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
---

## VQ vs RAW Sample Encoding

Each instrument can use one of two encoding modes, selectable via the checkbox next to its name in the instrument list.

### VQ (Vector Quantization) — Compressed

VQ divides each audio sample into small windows (typically 8 samples each) and replaces each window with the closest match from a shared **codebook** of 256 learned waveform patterns. On the Atari, the IRQ handler reads a 1-byte index, looks up the corresponding 8-byte codebook vector, and streams those bytes to POKEY. This gives roughly **8:1 compression** (with vec_size=8), meaning more instruments fit in the 64 KB RAM.

**Tradeoff:** The codebook lookup costs extra CPU cycles per sample. For projects with many simultaneous channels or high sample rates, this can push past the CPU budget.

### RAW (Uncompressed 4-bit PCM)

RAW stores each audio sample as a single byte (4-bit POKEY volume level, 0-15). No codebook lookup is needed — the IRQ handler reads one byte and writes it directly to POKEY. This is the fastest possible playback path.

**Tradeoff:** RAW uses 8x more memory than VQ (for vec_size=8). A 300ms kick drum at 15 kHz takes ~4.5 KB in RAW vs ~0.6 KB in VQ indices.

RAW mode also supports **noise shaping**: a technique that pushes quantization noise from audible low frequencies to less-audible high frequencies. This is automatically enabled at POKEY rates above 6 kHz, making 4-bit RAW samples sound cleaner than you'd expect.

### When to Use Each

| | VQ | RAW |
|---|---|---|
| **Memory** | Small (8:1 compression) | Large (1 byte/sample) |
| **CPU cost** | Higher (codebook lookup) | Lower (direct read) |
| **Best for** | Long pads, melodic lines | Short drums, percussive hits |

In practice, the best approach is to use the **OPTIMIZE** button, which analyzes your specific song and instruments to find the optimal mix.

---

## The OPTIMIZE Button

The **Optimize** button in the Instruments panel analyzes your project and recommends VQ or RAW mode for each instrument.

### What It Does

1. **Measures instrument sizes** — calculates how much memory each instrument needs in both VQ and RAW formats at the current sample rate and vector size.

2. **Simulates playback** — walks through every row of your song to find the worst-case moment where the most channels are active simultaneously. This determines the true peak CPU load.

3. **Finds the best mix** — tries switching instruments to RAW mode (starting with the shortest ones that save the most CPU) while staying within the memory limit. If switching an instrument to RAW eliminates CPU overruns, it recommends RAW.

4. **Shows indicators** — after optimization, **V** (VQ) or **R** (RAW) letters appear next to each instrument. Green means the current checkbox matches the recommendation. Red means you've overridden it.

### Tips

- Run Optimize after changing the sample rate, vector size, or memory limit.
- Run Optimize after adding or removing instruments.
- MOD import runs Optimize automatically.
- You can manually override any recommendation by toggling the checkbox — the V/R indicators stay visible so you can see what the optimizer suggested.

---

## Importing MOD Files

The tracker can import standard 4-channel Amiga ProTracker **.MOD** files.

### What Gets Imported

- **Instruments**: Each MOD sample becomes an instrument. The audio is saved as WAV and the instrument's `base_note` is set to C-3 (matching MOD conventions where sample period 428 = C-3).

- **Patterns**: All MOD patterns are converted to native tracker format. Notes are mapped to the 3-octave range (C-1 to B-3). Volume column values are converted from MOD's 0-64 range to the tracker's 0-15 range.

- **Song arrangement**: The MOD's pattern order becomes songlines. Speed/tempo commands in patterns are converted to per-songline speed values.

### After Import

After a successful import, the **optimizer runs automatically**, analyzing all imported instruments and setting their VQ/RAW modes based on the song's CPU requirements. You can then adjust settings and click CONVERT to proceed with building.

### Limitations

- MOD effect commands (portamento, vibrato, arpeggio, etc.) are not supported — only note, instrument, volume, and speed changes are imported.
- MOD samples with loops are not looped — they play once and stop.
- Very long MOD samples may exceed memory limits; consider using a lower sample rate or trimming in the sample editor.

---

## Memory Limit

The **Limit** field in the instruments panel sets the maximum memory budget for sample data on the Atari (default: 35 KB). This includes both VQ data (codebook + index streams) and RAW sample pages.

The OPTIMIZE button respects this limit when deciding which instruments to encode as RAW. If you increase the limit, more instruments can use RAW mode (better CPU, more memory). If you decrease it, the optimizer prefers VQ to save space.

The practical maximum depends on your song data and player code size, but 35 KB is a safe default for most projects on a stock 64 KB Atari.

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

### VQ/RAW Mode per Instrument

Each instrument can be set to VQ (compressed) or RAW (uncompressed). RAW saves CPU cycles but uses more memory. Use the **Optimize** button to find the best mix, or manually set modes via the checkboxes in the instrument list.

| Mode | IRQ Cycles/Channel | Memory per Sample | Best For |
|------|-------------------|-------------------|----------|
| **VQ** | ~30 (non-boundary) | ~1/8 of original | Long samples, melodic lines |
| **RAW** | ~24 (non-boundary) | Full size (page-aligned) | Short drums, percussion |

### Song Options Impact

| Option | Cycles Added | Recommendation |
|--------|--------------|----------------|
| Vol (Volume) | +11 per channel | Disable unless needed |
| Screen | +15% total (ANTIC DMA) | Disable for complex songs |
| Key | +35-55 total | Disable for play-once mode |

### Quick Optimization Checklist

If your song glitches:

1. â˜ Reduce **Rate** to 5278 Hz or lower
2. â˜ Increase **Vec** to 8 or 16
3. â˜ Disable **Screen** option
4. â˜ Disable **Vol** option if not using volume changes
5. â˜ Disable **Key** option
6. â˜ Try **Speed** optimize mode
7. â˜ Reduce simultaneous notes (avoid 3-channel chords on every row)

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

This folder can be safely deleted â€” it's regenerated as needed.

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

**No sound at all**
- Is Altirra audio enabled?
- Are samples loaded? (Check instrument list)
- Did CONVERT complete successfully?
- Check for errors in BUILD log

**"Use Converted" sounds bad**
- VQ compression is lossy â€” some quality loss is expected
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

This is **Beta 1** â€” an experimental first release. The foundation is working, but there's enormous potential for improvement:

### Planned Features

**Cycle-Accurate Emulation**

**Extended Memory Support**
The current player uses only base 64KB RAM. Adding support for extended memory (130XE banks, cartridge ROM) would dramatically increase available sample storage while keeping the playback engine in main RAM.

**Dynamic Sample Optimization**
Analyze which note/pitch combinations your song actually uses, then pre-render those specific pitches at conversion time. This could eliminate runtime pitch calculation entirely for many songs, dramatically reducing CPU load.

**Multi-Codebook Approach**
Instead of one global codebook for all samples, use instrument-specific codebooks. This improves compression quality for diverse sample sets (drums vs. strings vs. bass).

**Virtual Instruments**
Pre-mix multiple samples into combined "virtual instruments" at conversion time. For example, a chord could be a single mixed sample instead of three separate channels.

**Envelope Support**
Volume automation without per-note overhead â€” fade-ins, fade-outs, and attack/decay curves baked into the sample stream.

**Effect Commands**
Pitch slides, arpeggios, vibrato â€” pre-computed into the VQ stream rather than calculated at runtime.

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
- Fast playback â€” just table lookups
- Codebook can be optimized per sample set

**Trade-offs:**
- Lossy compression â€” quality depends on codebook size
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
- 4-channel polyphonic playback with pitch control
- VQ compression with adjustable parameters
- Pattern-based song editor
- One-click build and run

---

*Happy tracking! ðŸŽµ*

*Questions, bugs, or music to share? Find us on AtariAge!*
