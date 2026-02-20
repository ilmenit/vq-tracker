# POKEY VQ Tracker - Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

---

## [Beta 5] - 2025-02

### Extended Memory Banking

- **Per-bank VQ codebooks**: Each 16KB bank stores its own 256-entry codebook trained via k-means on that bank's audio content. Replaces the single global codebook, dramatically improving VQ quality — each instrument gets codebook entries optimized for its own timbral content.
- **DBANK_TABLE fix**: Bank selection table was aliased on 130XE — first 4 entries all mapped to the same physical bank. Rewritten to follow the reference `detect_ext` block-grouped ordering.
- **Alias-aware bank detection**: `mem_detect.asm` rewritten to detect actual distinct banks (not aliases). A 130XE now correctly reports 4 banks, not 64.
- **PORTB bit 0 fix**: OS ROM was enabled during bank-switched playback, corrupting any sample data above $C000. All runtime PORTB values now have bit 0 cleared.
- **Song data expansion**: Charset relocated to $FC00, freeing song data region from 16KB to 29KB ($8000–$CFFF + $D800–$FBFF, split around I/O).
- **SEI micro-window optimization**: VQ bank-read reduced from 41 to 25 cycles by narrowing the interrupt-disabled window.

### Audio & Playback

- **Audio stream architecture**: Eliminated all secondary audio streams. Preview playback (sample editor, file browser) now routes through the main engine's single OutputStream, preventing silent stream death.
- **Exception-safe audio callback**: Errors output silence instead of killing the stream.
- **Stream health monitoring**: Auto-restarts dead streams every ~2 seconds.
- **WAV Export** (File → Export WAV): Offline render to 16-bit 44.1kHz mono WAV.

### Visualization

- **Real-time spectrum analyzer**: 24-band FFT frequency spectrum (60Hz–18kHz, log-spaced) computed from a 2048-sample ring buffer captured in the audio callback. dB normalization with noise gate.
- **Channel VU bars**: 4 vertical bars with per-channel palette colors, slow decay (0.97/frame).
- **Settings toggle**: Enable/disable visualization panel (Editor → Settings) to reduce CPU usage.

### Pattern Editor

- **2D block selection**: Selection spans rows × channels. Shift+arrows extend, Shift+click selects rectangle, Ctrl+A selects all.
- **Multi-channel clipboard**: Copy/cut/paste full 2D blocks. OS clipboard via pyperclip — paste into text editors, edit, paste back.
- **Shared pattern auto-clone**: Paste/cut/clear on shared patterns auto-clones to prevent edits leaking to other channels.
- **Follow mode** (F4): Cursor chases playback position.
- **Solo buttons** (S): Per-channel solo/unsolo in channel headers.
- **Selection highlight priority fix**: Selection color now always visible, even on beat-marker rows.

### Build Pipeline

- **Memory upgrade dialog**: When build fails due to insufficient memory, a modal offers to upgrade to the smallest working config and rebuild automatically. Works for all failure types (bank packing, pre-flight overflow, assembly errors).
- **Memory error screen**: User-friendly display on Atari showing memory config name, song title, and required banks (replaces cryptic "NEED: ?? BANKS").
- **All-RAW build fix**: Build no longer fails when all instruments use RAW mode. Defensive ASM guards and VQ_CFG patching handle missing VQ constants.
- **MADS macro label scoping**: Used `.def` directive to force global scope for labels created inside macros, fixing "Undeclared label" errors.

### Splash Screen

- **Reordered layout**: Song name and author (centered) on top two lines, VQ TRACKER banner on line 3, SONG/ROW/SPD status on line 4.

### UI Improvements

- **Instrument list coloring**: Instrument numbers and names colored with the active palette, matching track cell colors. Converted instruments show green background with hover/active states; non-converted show gray.
- **Keyboard shortcuts**: F5–F8 playback keys work globally. Space toggles play/stop from any panel. Modal dialogs block editor shortcuts.
- **Default sample rate**: Changed from 4524Hz to 3958Hz.

### Code Quality

- **IRQ handler macro refactor**: 852 lines → 315 lines via `CHANNEL_IRQ` macro with MADS parameter substitution.
- **Bank window exit optimization**: Replaced CMP/BCC with BPL/BMI, saving 40 bytes and 48 cycles on bank-crossing paths.
- **418 unit tests** covering banking, clipboard, selection, build pipeline, memory detection, VQ re-encoding, and UI state.

---

## [Beta 4] - 2025-02

### Features

- **MOD Import Wizard**: Full wizard with live memory budget, target machine selection, per-row volume control, pattern deduplication, and song truncation.
- **Instrument Export**: Sample Editor exports processed audio to WAV/FLAC/OGG/MP3.
- **Cell color palettes**: Pattern editor cells colored by note/instrument/volume/pattern. Four multi-color + six single-color palettes.
- **Volume-change events (V--)**: Change volume without interrupting playback. Enter via tilde key or volume column on empty rows.
- **Sustain effect**: Repeat sample loop regions 1–64 times with optional crossfade.
- **"Used Samples" optimization**: CONVERT/OPTIMIZE skip unused instruments.
- **Configurable Start Address**: Set player ORG ($0800–$3F00).
- **Extended memory banking** (128KB–1MB): Bank-switched sample storage with RAM detection, multi-segment XEX, and banking-aware optimization.

### Performance

- **Optimized RAW IRQ player**: 88% → 62% CPU usage for 4 active RAW channels.
- **Fixed 4-channel note trigger stutter**: Reduced IRQ blackout from 604 to 44 cycles.
- **Pre-baked AUDC volume bit**: Saves 8 cycles/IRQ across 4 channels.

### Bug Fixes

- Pattern break (Dxx/Bxx) truncation, OPTIMIZE ignoring effects, double-sustain on round-trip, song.speed not serialized, volume_control flag not set on import, editor preferences overwritten by project load, cross-platform DPG key compatibility.

---

## [Beta 3] - 2025-02

### Major Features

- **4-channel polyphonic playback**: All four POKEY registers (AUDC1–AUDC4).
- **Mixed VQ + RAW encoding**: Per-instrument VQ or RAW mode selection.
- **OPTIMIZE button**: Analyzes instruments and recommends VQ/RAW per instrument.
- **Amiga MOD import**: 4-channel ProTracker .MOD files with pattern/instrument/speed conversion.
- **Coupled note entry mode**: FastTracker 2 style (overwrite instrument/volume) or Renoise style (preserve).
- **Clone instrument**: Deep-copy to new slot.

### Bug Fixes

- MOD instruments 2 octaves too high (pitch table base_note fix), VQ preview cheating vs RAW, RAW preview wrong interpolation, IRQ skip fall-through, branch out of range, Atari data size display excluded RAW samples.

### Improvements

- Noise shaping for RAW samples, 2-cycle/channel IRQ optimization, auto-optimize on MOD import.

---

## [Beta 2] - 2025-02

### Bug Fixes

- Windows WinError 32 loading .pvq files (path separator mismatch).
- Linux/macOS FFmpeg not found for MP3 import in bundled builds.
- Misleading VQ conversion size display.
- Song editor undo not recorded.
- Autosave lost VQ settings.

### Improvements

- Simplified .pvq format with numbered sample files, cross-platform portable.
- Operations module refactored into `ops/` package.
- 86 unit tests.

---

## [Beta 1] - 2025-02

### Initial Release

First public beta — sample-based music tracker for Atari XL/XE using Vector Quantization audio compression.

- 3-channel polyphonic sample playback on stock 64K Atari XL/XE
- VQ compression with adjustable sample rate and vector size
- Pattern-based sequencer with songline arrangement
- Real-time preview playback
- One-click export to .xex via integrated MADS assembler
- Multi-format sample import (WAV, MP3, OGG, FLAC, AIFF, M4A)
- Speed and size optimization modes for 6502 IRQ handler
- Piano and tracker keyboard modes, undo/redo, hex/decimal display
- Self-contained .pvq project format
- CPU cycle budget analysis

---

## Credits

- MADS Assembler by Tomasz Biela (Tebe)
- Altirra Emulator by Avery Lee
- DearPyGui by Jonathan Hoffstadt
- The Atari 8-bit community

---

*Thank you for trying POKEY VQ Tracker! Feedback and bug reports welcome.*
