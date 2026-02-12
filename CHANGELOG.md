# POKEY VQ Tracker - Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

---

## [Beta 3] - 2025-02

### Major Features

- **4-channel polyphonic playback**: Expanded from 3 to 4 independent sample
  channels. All four POKEY audio registers (AUDC1–AUDC4) are now used, giving
  the full hardware polyphony. The 6502 IRQ handler, process_row commit logic,
  and tracker_api all handle 4 channels with complete VQ/RAW mode support.

- **Mixed VQ + RAW sample encoding**: Instruments can now individually use either
  VQ (Vector Quantization) or RAW (uncompressed 4-bit PCM) encoding. VQ gives
  better compression (8:1 with vec_size=8) using a shared 256-entry codebook.
  RAW uses more memory but costs fewer CPU cycles per sample — no codebook
  lookup needed. The player selects the correct handler per channel at note
  trigger time via self-modifying code, with zero overhead during playback.

- **OPTIMIZE button**: Analyzes all instruments and the song arrangement to
  recommend VQ or RAW mode for each instrument. The optimizer simulates
  playback row-by-row to find the worst-case CPU load, then switches short
  or CPU-heavy instruments to RAW when memory allows. After optimization,
  V (VQ) and R (RAW) indicators appear next to each instrument showing the
  recommendation. Toggling an instrument's checkbox preserves these indicators.

- **Amiga MOD import**: Import 4-channel ProTracker .MOD files with automatic
  conversion of patterns, instruments, song arrangement, and speed settings.
  MOD samples are resampled to the POKEY rate and their `base_note` is set to
  C-3 (matching MOD tuning conventions). After import, the optimizer runs
  automatically to assign RAW/VQ modes.

- **Configurable memory limit**: The sample data memory budget is adjustable
  (default 35 KB). The OPTIMIZE button and BUILD process respect this limit
  when deciding how to fit instruments into the Atari's 64 KB RAM.

- **Coupled note entry mode**: New setting (on by default) that controls whether
  entering a note on an occupied cell overwrites the instrument and volume
  (FastTracker 2 style) or preserves them (Renoise-style edit mask). Toggle
  in Settings panel.

- **Clone instrument**: Deep-copies the selected instrument (audio data, effects
  chain, settings) to a new slot at the end of the instrument list.

### Bug Fixes

- **MOD instruments played 2 octaves too high on Atari**: The ASM pitch table
  ignored `base_note`. MOD samples are pitched for C-3 playback, but the
  exporter mapped C-3 to pitch index 24 = 4.0x instead of 1.0x. Fixed by
  extending the pitch table from 36 to 60 entries (5 octaves including 0.25x
  and 0.5x sub-octaves) and applying a base_note correction during export:
  `export_note = gui_note + 24 - (base_note - 1)`.

- **VQ preview cheating vs RAW**: The VQ preview played codebook vectors at
  float32 precision (~24-bit quality) instead of quantizing through the real
  16-level POKEY voltage table. This made VQ sound dramatically better than RAW
  in preview, but the difference does not exist on real hardware. Both VQ and
  RAW previews now go through honest 16-level POKEY quantization.

- **RAW preview used wrong interpolation**: RAW preview used sinc interpolation
  (scipy.signal.resample) creating ringing artifacts. Now uses zero-order hold
  (np.repeat at 1.77 MHz → resample to 48 kHz), matching real POKEY hardware
  sample-and-hold behavior and identical to the VQ preview method.

- **IRQ skip labels fell through into RAW handlers**: Every `chN_skip` label
  in tracker_irq_speed.asm pointed to the same address as `chN_raw_boundary`
  (only comments between, no instructions). On every non-boundary tick, execution
  fell through from skip into the RAW boundary handler. Fixed by placing all RAW
  handlers after the `rti` instruction, reachable only via SMC JMP targets.

- **Branch out of range after removing size optimization**: Removing
  OPTIMIZE_SPEED conditionals made commit blocks exceed the 6502's ±127 byte
  relative branch limit. Fixed by inverting `beq @commit_done_N` to
  `bne @do_commit_N / jmp @commit_done_N`.

- **Atari data size display excluded RAW samples**: The size shown after
  conversion only counted VQ_BLOB + VQ_INDICES. RAW_SAMPLES bytes were never
  added. All-RAW projects showed "2 B". Fixed.

- **Keyboard notes played while typing in Limit field**: The memory limit
  input field did not suppress keyboard note entry, causing notes to trigger
  while typing numbers. Fixed by adding the field to the input-active check list.

- **Optimize indicators disappeared on checkbox toggle**: Clicking a VQ/RAW
  checkbox cleared the optimize result, hiding the V/R recommendation
  indicators. The indicators now persist through checkbox toggles (only cleared
  by operations that change the instrument list or settings).

### Improvements

- **Noise shaping for RAW samples**: 1st-order error-feedback noise shaping
  pushes quantization noise from audible low frequencies to less-audible high
  frequencies. At 15 kHz POKEY rate, noise in the 0–2 kHz band drops by ~18x.
  Auto-enabled when POKEY rate ≥ 6 kHz.

- **2-cycle/channel IRQ optimization**: Data bytes now store raw 0–15 volumes
  instead of pre-baked `$10|vol`. Removes the `AND #$0F` instruction from the
  IRQ hot path, saving 8 cycles per IRQ tick across 4 channels.

- **Removed size-optimized player from tracker**: The tracker now always uses
  the speed-optimized IRQ handler. The size-optimized variant (nibble-packed,
  no RAW support) remains available in the standalone vq_converter.

- **Auto-optimize on MOD import**: After importing a MOD file, the RAW/VQ
  optimizer runs automatically so instruments start with sensible mode
  assignments.

- **Simplified menus**: Removed "Import vq_converter..." and "Export .ASM..."
  menu items. The tracker workflow is now: compose → convert → build (.xex).

### Documentation

- Updated User Guide: 4-channel playback, VQ vs RAW encoding explained,
  OPTIMIZE workflow, MOD import guide, memory limit configuration.

---

## [Beta 2] - 2025-02

### Bug Fixes

- **Windows: WinError 32 when loading .pvq files**: Loading projects failed with
  "The process cannot access the file because it is being used by another process".
  Root cause: ZIP archives use forward slashes (`samples/00.wav`) but Windows uses
  backslashes. When checking if source and destination paths were the same,
  string comparison failed due to mixed separators, causing `shutil.copy2()` to
  attempt copying a file onto itself. Fixed with `os.path.normpath()` before
  path comparison. (`file_io.py`)
- **Linux/macOS: FFmpeg not found for MP3 import**: The `_setup_ffmpeg_for_pydub()`
  function only set up the bundled FFmpeg path on Windows. Now works on all
  platforms, enabling MP3/OGG/FLAC import from both source and PyInstaller builds.
  (`main.py`)
- **Misleading VQ conversion size**: The size shown after conversion (~30KB) didn't match
  the actual .xex size (~7KB). The encoder's estimated size didn't account for nibble
  packing. Fixed by having `MADSExporter.export()` return the actual byte count after
  export, which `builder.py` now stores in `conversion_info.json`. (`vq_converter/`:
  `mads_exporter.py`, `builder.py`; tracker: `vq_convert.py`, `ui_callbacks.py`,
  `ui_refresh.py`)
- **Song editor undo not recorded**: Editing pattern assignments or speed
  values in the song editor via keyboard did not create an undo snapshot.
  Changes were silently permanent. (`keyboard.py`: added `save_undo("Edit song")`
  before `_apply_song_pattern_value` commits)
- **Autosave lost VQ settings**: The `vq_enhance` and `vq_optimize_speed`
  fields were not included in the `EditorState` written by autosave, causing
  these settings to reset to defaults when restoring from an autosave.
  (`ui_globals.py`: added both fields to the autosave `EditorState` constructor)

### Project File Format

- **Simplified and portable .pvq format**: Complete redesign of sample storage:
  - Samples stored as numbered files: `samples/000.wav`, `samples/001.wav`, etc.
  - No paths stored in JSON — sample existence determined by file presence
  - Removed `sample_path`, `original_sample_path`, `sample_file` from serialization
  - Instrument `name`, `base_note`, `sample_rate` are the only persisted fields
  - `sample_path` is now runtime-only, reconstructed on load
  - Changed numbering from `02d` to `03d` to support all 128 instruments
- **Cross-platform compatibility**: Project files now fully portable between
  Windows, macOS, and Linux without path separator issues

### Architecture

- **Operations module refactored into `ops/` package**: The monolithic
  `operations.py` (1181 lines) has been replaced by ten focused modules under
  `ops/`, grouped by domain: `base`, `file_ops`, `editing`, `navigation`,
  `playback`, `instrument_ops`, `pattern_ops`, `songline_ops`, `input_settings`.
  The `operations.py` wrapper has been removed; all call sites now
  `import ops` directly.
- **Typed UI callback interface**: Replaced ~15 mutable module-level callback
  variables with `UICallbacks`, a typed dataclass in the new
  `ui_callbacks_interface.py`. All callbacks have safe no-op defaults, so the
  operations layer works even before the UI is wired up. Callback wiring in
  `main.py` now constructs a single `UICallbacks` instance and passes it via
  `set_ui_callbacks()`.

### Code Quality

- **Bare `except:` clauses eliminated**: All bare `except:` and `except: pass`
  patterns replaced with specific exception types and diagnostic logging:
  - `file_io.py`: `OSError` for lock/unlock, `Exception` for fallback paths,
    `scipy`/`wave` read failures now logged at debug/warning level
  - `audio_engine.py`: stream close, callback errors now logged with context
  - `ui_globals.py`: parse errors narrowed to `ValueError`/`TypeError`,
    autosave cleanup errors logged
- **Magic numbers replaced with constants**: Hardcoded `6` (speed) and `64`
  (pattern length) in `audio_engine.py` replaced with `DEFAULT_SPEED` and
  `DEFAULT_LENGTH` from `constants.py`.
- **Removed unused code**:
  - `original_sample_path` field from `Instrument` dataclass
  - `is_converted` parameter from `load_sample()` function
  - `_safe_filename()` function (no longer needed with numbered samples)
  - Backward compatibility code for old project formats

### Testing

- **New test suite**: 86 unit tests across five modules, runnable via
  `run_tests.sh` / `run_tests.bat`:
  - `test_data_model.py` (37 tests): Song, Pattern, Row, Instrument
    creation, serialization round-trip, edge cases
  - `test_file_io.py` (19 tests): Safe filename generation, project
    save/load, format version handling, lock management
  - `test_state.py` (19 tests): UndoManager push/pop/redo, Clipboard,
    Selection, EditorState persistence
  - `test_export.py` (6 tests): Binary and ASM export validation,
    event encoding, note mapping
  - `test_ui_callbacks_interface.py` (5 tests): UICallbacks defaults,
    field assignment, mutation isolation

### File Changes Summary

New files: `ops/` (10 modules), `ui_callbacks_interface.py`, `tests/` (5 test
modules + runner scripts).
Removed: `operations.py`.
Modified: `keyboard.py`, `main.py`, `ui_globals.py`, `ui_callbacks.py`,
`ui_build.py`, `audio_engine.py`, `file_io.py`, `data_model.py`, `vq_convert.py`,
`ui_refresh.py`.
Unchanged: all ASM sources, `build.py`, `state.py`, `constants.py`, `runtime.py`,
`ui_theme.py`, `ui_browser.py`, `ui_dialogs.py`, `analyze.py`, `build_release.py`.

---

## [Beta 1] - 2025-02

### Initial Release

First public beta of POKEY VQ Tracker — an experimental sample-based music
tracker for Atari XL/XE computers using Vector Quantization audio compression.

### Core Features

- 3-channel polyphonic sample playback on stock 64K Atari XL/XE
- 3 octaves (36 semitones) with 8.8 fixed-point pitch calculation
- VQ compression with adjustable sample rate (3333–15834 Hz) and vector
  size (2, 4, 8, 16)
- Pattern-based sequencer with songline arrangement
- Real-time preview playback in the tracker
- One-click export to Atari executable (.xex) via integrated MADS assembler
- Multi-format sample import (WAV, MP3, OGG, FLAC, AIFF, M4A)
- Speed and size optimization modes for the 6502 IRQ handler
- Optional per-note volume control, display blanking, keyboard control

### Editor

- Piano and tracker keyboard modes for note entry
- Pattern copy/paste/transpose
- Undo/redo
- Hex/decimal display toggle
- Row highlighting and follow mode

### Project Management

- Self-contained `.pvq` project format (ZIP-based with embedded samples)
- Auto-save, recent files list, editor state preservation

### Build System

- Cross-platform builds (Windows, macOS, Linux) via PyInstaller
- Bundled MADS assembler binaries

### Analysis

- CPU cycle budget analysis with per-row cost estimation and configuration
  recommendations

### Known Issues (fixed in Beta 2)

- Windows: Loading .pvq files failed with WinError 32 due to path separator mismatch
- Linux/macOS: FFmpeg not found for MP3/OGG/FLAC import in bundled builds
- Project files not portable across platforms (absolute paths stored)
- VQ conversion showed misleading size (included preview WAVs, not just Atari data)
- Song editor keyboard edits did not record undo snapshots
- Autosave did not persist `vq_enhance` and `vq_optimize_speed` settings
- Bare `except:` clauses throughout the codebase silently swallowed errors
- Sample filenames limited to 99 instruments (used `02d` format)
- No unit tests

### Known Limitations

- Analysis provides estimates, not cycle-accurate emulation
- No effect commands (portamento, vibrato, etc.)
- Single codebook shared across all samples
- Base RAM only (no extended memory support)
- PAL timing is the primary focus; NTSC is less tested

---

## Future Plans

See `UserGuide.md` "Future Roadmap" section for planned features including
cycle-accurate emulation, extended memory support, multi-codebook compression,
effect commands, and more.

---

## Credits

- MADS Assembler by Tomasz Biela (Tebe)
- Altirra Emulator by Avery Lee
- DearPyGui by Jonathan Hoffstadt
- The Atari 8-bit community

---

*Thank you for trying POKEY VQ Tracker! Feedback and bug reports welcome.*
