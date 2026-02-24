# POKEY VQ Tracker - Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Beta 6] - 2026-02

### POKEY Emulation
- **Built-in POKEY emulator**: Pure-Python port of ASAP's `pokey.fu` (Piotr Fusik).
- **VQ/RAW player engine**: Reimplements the tracker's 6502 IRQ handler (`tracker_irq_speed.asm`) in Python.
- **All playback through POKEY**: Every audio path — song play (F5/F6/F7), pattern play, note preview, row preview, sample editor preview, WAV export — goes through the POKEY emulator. No WAV pitch-shifting anywhere.
- **Pre-conversion preview**: Before VQ conversion, instruments are converted on-the-fly to RAW POKEY format (resample to target rate → quantize to 4-bit POKEY levels → AUDC register writes). You hear the actual 4-bit quantization and sample rate limitations from the first note you place.
- **Post-conversion playback**: After VQ conversion, uses the actual compressed VQ data — identical register writes to the .xex on real hardware.
- **Sample editor preview**: Renders through POKEY in RAW mode at the configured target rate, so you hear the hardware-accurate version of your sample while editing.
- **POKEY WAV export**: File → Export WAV renders through the POKEY emulator, producing output that matches Atari hardware sample-for-sample.
- **VU meter decay**: Classic tracker linear fall (always dropping, no hold). Vibrating bounce on consecutive notes.

---

## [Beta 6] - 2026-02

### Cycle-Accurate POKEY Emulation

- **Built-in POKEY emulator**: Pure-Python port of ASAP's `pokey.fu` (Piotr Fusik). Band-limited sinc interpolation, DAC compression from measured AMI chip characteristics, IIR high-pass filter, poly4/5/9/17 polynomial counters — the full pipeline. 75–108× real-time performance (0.2ms per 20ms frame), zero C extensions needed.
- **VQ/RAW player engine**: Reimplements the tracker's 6502 IRQ handler (`tracker_irq_speed.asm`) in Python. Bit-exact 8.8 fixed-point pitch accumulation, VQ codebook lookup, RAW page-crossing, volume scaling table, per-channel end-of-stream detection. Seven critical bugs found and fixed during line-by-line audit against the assembly source.
- **All playback through POKEY**: Every audio path — song play (F5/F6/F7), pattern play, note preview, row preview, sample editor preview, WAV export — goes through the POKEY emulator. No WAV pitch-shifting anywhere. What you hear is what the Atari produces.
- **Pre-conversion preview**: Before VQ conversion, instruments are converted on-the-fly to RAW POKEY format (resample to target rate → quantize to 4-bit POKEY levels → AUDC register writes). You hear the actual 4-bit quantization and sample rate limitations from the first note you place.
- **Post-conversion playback**: After VQ conversion, uses the actual compressed VQ data — identical register writes to the .xex on real hardware.
- **Sample editor preview**: Renders through POKEY in RAW mode at the configured target rate, so you hear the hardware-accurate version of your sample while editing.
- **POKEY WAV export**: File → Export WAV renders through the POKEY emulator, producing output that matches Atari hardware sample-for-sample.
- **173 emulator tests**: 125-assertion core suite covering POKEY registers, polynomial tables, sinc interpolation, DAC compression, channel timing, pure tone generation, STIMER/SKCTL, plus 48-assertion deep validation suite testing DC rejection, frame boundary continuity, codebook byte readout, and end-of-stream behavior. Plus 62-assertion 4-channel verification suite testing multi-channel mixing, channel independence, note-off isolation, pitch rates, per-channel volume, and AudioEngine integration. Plus 248-assertion integration test suite verifying every data path from tracker → SongData → VQPlayer → POKEY registers → PCM: AUDF computation, codebook offsets, volume scaling, pitch accumulation (6502-exact fixed-point), sequencer row/songline/speed/wrap logic, VQ and RAW byte readout, end-of-stream, note-off, retrigger, channel muting, DAC compression, DC rejection, NTSC/PAL timing, and AudioEngine WAV→RAW conversion. Plus 39-assertion integration test suite verifying register-level VQ/RAW writes, sequencer correctness, and full AudioEngine paths.
- **Removed WAV preview generation**: The converter no longer generates per-instrument preview WAV files to `.tmp`. The "Use converted" checkbox has been removed. All preview is now handled by the POKEY emulator directly — faster conversion, less disk I/O, and no sample swapping.
- **Cached POKEY sinc tables**: Sinc interpolation lookup tables (1024×32 entries) are computed once on first use and shared across all VQPlayer instances. Eliminates 32ms overhead on every play/preview action.
- **Lock-free rendering**: Note preview, row preview, sample editor preview, and play-start all perform the heavy POKEY rendering outside the audio lock. Lock hold time reduced from 70–104ms to <1ms, eliminating audio pops/glitches when pressing keys or starting playback.
- **Fixed out-of-range songline**: Playing from an invalid songline position no longer triggers ghost notes from stale pattern data.
- **Fixed sample editor cursor**: Preview position calculation now uses the correct sample rate (44100 Hz output, not 3958 Hz POKEY rate), so the waveform cursor tracks accurately during playback.
- **Fixed FFT ring buffer overflow**: Audio callback now handles buffer sizes larger than the 2048-sample FFT window without crashing.
- **Fixed post-conversion RAW instrument silence**: Three bugs in the VQ→Player data bridge caused RAW-mode instruments to produce silence after conversion: (1) case-sensitive mode comparison (`"RAW"` vs `'raw'`), (2) loader looked for per-instrument `RAW_SAMPLE_N.asm` files but builder creates a single `RAW_SAMPLES.asm` with labeled sections, (3) fallback used empty VQ indices instead of a silence byte. Now correctly parses `RAW_SAMPLES.asm` labels and handles mixed VQ/RAW songs.
- **VQ data validation with fallback**: All playback paths (song, note preview, row preview, WAV export) now validate loaded VQ data after conversion. If instruments are missing, codebook is empty, or instrument count doesn't match the song, automatically falls back to live RAW preview instead of playing silence.
- **Invalidate stale VQ during re-conversion**: Starting a new conversion now immediately invalidates the previous VQ data, so playback during conversion falls back to live RAW instead of reading from a deleted output directory.
- **Fixed play-from-row**: Starting playback from a non-zero row (e.g. pressing play at row 5) now correctly fast-forwards the per-channel event positions. Previously it would fire events from row 0, causing wrong notes and desynchronized patterns.
- **39-assertion integration test suite**: End-to-end tests covering VQ/RAW register writes, 4-channel isolation, sequencer row/songline/pattern-wrap, start-from-row, pitch accuracy, volume control, channel muting, NTSC/PAL frame lengths, and AudioEngine integration.

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
