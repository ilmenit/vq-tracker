# Atari 8-bit Sample Tracker

## Design Document v3.1

---

## 1. Project Overview

### 1.1 Vision

A cross-platform music tracker for composing sample-based music targeting Atari XL/XE 8-bit computers. The tracker runs as a native desktop application and exports data compatible with the 6502 assembly playback engine.

### 1.2 Core Principles

- **Native desktop app**: Cross-platform (Windows, macOS, Linux) via Go + Gio UI
- **Authentic playback**: Sample-based synthesis matching Atari hardware capabilities
- **Hardware targeting**: PAL Atari (1.77 MHz clock, 50 Hz) as primary target

### 1.3 Naming Convention

Terminology follows **Raster Music Tracker (RMT)** conventions where applicable, familiar to Atari musicians.

---

## 2. Glossary

| Term | Definition |
|------|------------|
| **Channel** | One of three independent audio outputs (AUDC1, AUDC2, AUDC3) |
| **Instrument** | A WAV sample that can be pitched across octaves |
| **Note** | Pitch (C, C#, D...) combined with octave (1-4) |
| **Pattern** | A sequence of note events for a single channel (up to 256 rows) |
| **Row** | One timing unit within a pattern |
| **Song** | The arrangement: list of songlines defining playback order |
| **Songline** | One row in the song, assigns one pattern to each channel |
| **Speed** | VBLANK ticks per row (lower = faster) |
| **VBLANK** | Vertical blank interrupt, occurs 50× per second (PAL) |
| **VQ** | Vector Quantization, compression technique for sample data on Atari |

---

## 3. Hardware Constraints

### 3.1 Limitations

- **3 simultaneous voices**: Channels 1-3 (Channel 4 reserved)
- **4-bit volume**: 16 levels (0-15) per channel
- **No real-time effects**: Effects must be pre-baked into samples
- **Pitch via playback rate**: Samples pitched by varying speed

### 3.2 Ranges

| Feature | Range |
|---------|-------|
| Octaves | 4 (1-4), 48 semitones total |
| Volume | 0-15 per channel |
| Instruments | 0-127 |
| Patterns | 0-255 (shared pool, any channel can use any pattern) |
| Rows per pattern | 1-256 |
| Songlines | 1-256 |

### 3.3 Pitch System

Notes span four octaves using 8.8 fixed-point pitch multipliers:

| Octave | Range | Base Multiplier |
|--------|-------|-----------------|
| 1 | C1-B1 | 1.0× (original sample rate) |
| 2 | C2-B2 | 2.0× |
| 3 | C3-B3 | 4.0× |
| 4 | C4-B4 | 8.0× |

---

## 4. Data Model

### 4.1 Structure

```
Song
├── Metadata (title, author, speed, system)
├── Songlines [each assigns 3 patterns to channels]
├── Patterns [note sequences, shared pool across all channels]
└── Instruments [sample references]
```

### 4.2 Songline

Each songline assigns one pattern index to each channel. Patterns come from a shared pool—assigning pattern 02 to multiple channels means they play identical notes.

```
Songline 0: [CH1=Ptn02, CH2=Ptn00, CH3=Ptn05]
Songline 1: [CH1=Ptn02, CH2=Ptn01, CH3=Ptn05]  ← CH1 reuses Ptn02
```

### 4.3 Pattern

A pattern is a sequence of rows. Patterns can have different lengths. When a pattern is shorter than the songline's effective length, it repeats.

**Example**: Songline plays for 64 rows total:
- Pattern on CH1 (length 16): repeats 4×
- Pattern on CH2 (length 32): repeats 2×
- Pattern on CH3 (length 64): plays once

### 4.4 Pattern Row

| Field | Range | Description |
|-------|-------|-------------|
| note | 0-48 | 0=continue/empty, 1-48=C1 through B4 |
| instrument | 0-127 | Sample index |
| volume | 0-15 | Channel volume |

### 4.5 Metadata

| Field | Default | Description |
|-------|---------|-------------|
| title | "Untitled" | Song name |
| author | "" | Composer |
| speed | 6 | VBLANK ticks per row (1-255) |
| system | 50 | 50=PAL, 60=NTSC |

---

## 5. File Format

### 5.1 Project File (.pvq)

Gzip-compressed JSON containing all song data and instrument references.

```json
{
  "version": 1,
  "metadata": {
    "title": "Example Song",
    "author": "Composer Name",
    "speed": 6,
    "system": 50
  },
  "songlines": [
    [2, 0, 5],
    [2, 1, 5],
    [3, 1, 6]
  ],
  "patterns": [
    {
      "length": 64,
      "rows": [
        {"note": 13, "instrument": 0, "volume": 15},
        {"note": 0, "instrument": 0, "volume": 15},
        {"note": 15, "instrument": 0, "volume": 12}
      ]
    }
  ],
  "instruments": [
    {"name": "Piano", "sample": "piano.wav"},
    {"name": "Bass", "sample": "bass.wav"}
  ]
}
```

### 5.2 File Operations

| Operation | Description |
|-----------|-------------|
| New | Empty song with one songline, one empty pattern per channel |
| Open | Load .pvq file |
| Save / Save As | Write .pvq file |
| Export | Generate .asm include files for Atari player |
| Clear | Reset to empty state (with confirmation) |

---

## 6. User Interface

### 6.1 Main Layout

Pattern grid at bottom (main focus area), controls and lists at top.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ File  Edit  Song  Pattern  Instrument  Help          [DEC/HEX] [PAL▾]  │
├───────────┬─────────────────────────────────────────────────────────────┤
│  SONG     │  INSTRUMENTS          Speed: [6]  Oct: [2]  Step: [1]      │
│           │                                                             │
│ Ln C1 C2 C3│ ▶00 Piano            Pattern: 02  Len: [64]               │
│ 00 02 00 05│  01 Bass             [New] [Clone] [Delete]               │
│▶01 02 01 05│  02 Strings                                               │
│ 02 03 01 06│                      CH1: [M][S]  CH2: [M][S]  CH3: [M][S]│
│ [+]        │  [+] [Load]                                                │
├────────────┴────────────────────────────────────────────────────────────┤
│                          PATTERN EDITOR                                 │
│  Row │ CH1 [Ptn 02]  │ CH2 [Ptn 01]  │ CH3 [Ptn 05]  │                 │
│      │ Note Ins Vol  │ Note Ins Vol  │ Note Ins Vol  │                 │
│──────┼───────────────┼───────────────┼───────────────┼                 │
│   00 │ C-2  01   F   │ ---  --   -   │ D-3  02   8   │                 │
│  ▶01 │ ---  --   -   │ E-2  01   F   │ ---  --   -   │                 │
│   02 │ D-2  --   C   │ ---  --   -   │ ---  --   -   │                 │
│   03 │ ---  --   -   │ ---  --   A   │ F-3  02   F   │                 │
│   04 │ E-2  01   F   │ G-2  --   F   │ ---  --   -   │                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Menu Bar

**File**: New, Open, Save, Save As, Export ASM, Exit
**Edit**: Undo, Redo, Cut, Copy, Paste, Delete, Select All
**Song**: Add Songline, Delete Songline, Clone Songline
**Pattern**: New Pattern, Clone Pattern, Delete Pattern, Transpose (+/- semitone, +/- octave)
**Instrument**: Load Sample, Remove Instrument, Rename
**Help**: Keyboard Shortcuts, About

### 6.3 Components

**Display Toggle** (top right)
- `[DEC/HEX]` button switches all numeric displays
- Affects: row numbers, pattern numbers, instrument numbers, volume
- Hex example: `0F` instead of `15`, `2A` instead of `42`

**System Selector**: `[PAL▾]` dropdown for PAL (50Hz) / NTSC (60Hz)

**Song Panel** (top left)
- Vertical list of songlines
- Columns: `Ln` (line number), `C1 C2 C3` (pattern assigned to each channel)
- `▶` marks current playback/edit position
- Click to select songline and load its patterns into editor
- `[+]` appends new songline

**Instrument Panel** (top center)
- List of loaded instruments with index and name
- `▶` marks currently selected instrument for note entry
- Click to select instrument
- `[+]` adds empty instrument slot
- `[Load]` opens file dialog for WAV import

**Status/Controls** (top right area)
- `Speed: [6]` — editable speed value
- `Oct: [2]` — current octave for keyboard entry (1-4)
- `Step: [1]` — cursor advance after note entry (0-16)
- `Pattern: 02  Len: [64]` — currently focused pattern with length control
- `[New] [Clone] [Delete]` — pattern management
- `[M] [S]` per channel — Mute and Solo toggles

**Pattern Editor** (bottom, main area)
- Three channel columns
- Pattern selector dropdown `[Ptn ##]` above each column
- Columns per channel: Note, Instrument (Ins), Volume (Vol)
- Row numbers in leftmost column
- Cursor position highlighted
- Scrolls to keep cursor vertically centered

### 6.4 Cell Display Format

| Mode | Note | Instrument | Volume |
|------|------|------------|--------|
| DEC | `C-2` | `01` | `15` |
| HEX | `C-2` | `01` | `0F` |
| Empty | `---` | `--` | `-` |

Notes always display as `C-2`, `C#2`, `D-2`, etc. (pitch notation, not hex).

### 6.5 Scrolling Behavior

The pattern grid keeps the cursor row vertically centered:

```
[empty space]       ← Visible when cursor near top of pattern
[empty space]
Row 00
Row 01  ◀ cursor
Row 02
Row 03
[empty space]       ← Visible when cursor near end of pattern
```

### 6.6 Visual Feedback

- **Playing row**: Highlight or color pulse on currently playing row
- **Current instrument**: Highlighted in instrument list
- **Modified indicator**: Window title shows `*` when unsaved changes
- **Playback vs edit cursor**: Distinct markers when playing (playback position separate from edit cursor)

---

## 7. Keyboard Controls

### 7.1 Note Entry (Piano Layout)

```
Upper row (base octave + 1):
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│ 2 │ 3 │   │ 5 │ 6 │ 7 │   │ 9 │ 0 │   │ ← Sharps
│C# │D# │   │F# │G# │A# │   │C# │D# │   │
├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
│ Q │ W │ E │ R │ T │ Y │ U │ I │ O │ P │ ← Naturals
│ C │ D │ E │ F │ G │ A │ B │ C │ D │ E │
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘

Lower row (base octave):
┌───┬───┬───┬───┬───┬───┬───┐
│ S │ D │   │ G │ H │ J │   │ ← Sharps
├───┼───┼───┼───┼───┼───┼───┤
│ Z │ X │ C │ V │ B │ N │ M │ ← Naturals
└───┴───┴───┴───┴───┴───┴───┘
```

### 7.2 Navigation

| Key | Action |
|-----|--------|
| ↑ / ↓ | Move cursor up/down |
| ← / → | Move between columns |
| Tab / Shift+Tab | Next/previous channel |
| Page Up/Down | Jump 16 rows |
| Home / End | First/last row |
| Ctrl+Home/End | First/last songline |

### 7.3 Editing

| Key | Action |
|-----|--------|
| Delete | Clear cell |
| Backspace | Clear cell and move up |
| Insert | Insert empty row |
| 0-9, A-F | Enter values (instrument/volume, hex in hex mode) |
| * / - | Octave up/down |
| [ / ] | Previous/next instrument |
| Ctrl+Z / Ctrl+Y | Undo/redo |

### 7.4 Playback

| Key | Action |
|-----|--------|
| Space | Play/stop from cursor |
| F5 | Play pattern from start |
| F6 | Play song from start |
| F7 | Play song from current songline |
| F8 | Stop |
| Enter | Play current row (preview) |

### 7.5 Selection

| Key | Action |
|-----|--------|
| Shift + Arrows | Extend selection |
| Ctrl+A | Select all in pattern |
| Ctrl+C / Ctrl+X / Ctrl+V | Copy/cut/paste |

---

## 8. Audio Engine

### 8.1 Playback

- Uses system audio (oto library for Go)
- Samples pitched via playback rate resampling
- 3 independent channel mixers with volume control
- Timing driven by goroutine ticker at VBLANK rate

### 8.2 Timing

```
Rows per second = System_Hz / Speed

PAL (50Hz), Speed 6:  50/6 = 8.33 rows/sec
NTSC (60Hz), Speed 6: 60/6 = 10 rows/sec
```

---

## 9. Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Go |
| UI Framework | Gio (gioui.org) |
| Audio | oto + resampling |
| File Format | JSON + gzip |
| Build | Single binary, cross-compiled |

---

## 10. Development Phases

### Phase 1: Core Editor

- [ ] Gio window with pattern grid
- [ ] Keyboard navigation and note entry
- [ ] Load WAV instruments
- [ ] Basic playback (single pattern)
- [ ] Save/load project files

### Phase 2: Full Tracker

- [ ] Song editor (songlines)
- [ ] Full playback engine (song mode)
- [ ] Copy/paste, undo/redo
- [ ] Transpose operations
- [ ] Mute/solo channels
- [ ] Hex/dec toggle

### Phase 3: Export & Polish

- [ ] Export to .asm format
- [ ] Keyboard customization
- [ ] Visual feedback improvements
- [ ] Performance optimization

---

## Appendix A: Note Reference

| Note | Oct 1 | Oct 2 | Oct 3 | Oct 4 |
|------|-------|-------|-------|-------|
| C | C-1 | C-2 | C-3 | C-4 |
| C# | C#1 | C#2 | C#3 | C#4 |
| D | D-1 | D-2 | D-3 | D-4 |
| D# | D#1 | D#2 | D#3 | D#4 |
| E | E-1 | E-2 | E-3 | E-4 |
| F | F-1 | F-2 | F-3 | F-4 |
| F# | F#1 | F#2 | F#3 | F#4 |
| G | G-1 | G-2 | G-3 | G-4 |
| G# | G#1 | G#2 | G#3 | G#4 |
| A | A-1 | A-2 | A-3 | A-4 |
| A# | A#1 | A#2 | A#3 | A#4 |
| B | B-1 | B-2 | B-3 | B-4 |

## Appendix B: Speed Reference

| Speed | Rows/sec (PAL) | Rows/sec (NTSC) | ~BPM |
|-------|----------------|-----------------|------|
| 3 | 16.67 | 20.00 | 250 |
| 4 | 12.50 | 15.00 | 188 |
| 5 | 10.00 | 12.00 | 150 |
| 6 | 8.33 | 10.00 | 125 |
| 8 | 6.25 | 7.50 | 94 |
| 10 | 5.00 | 6.00 | 75 |
| 12 | 4.17 | 5.00 | 63 |

*BPM assumes 4 rows per beat*
