# POKEY VQ Tracker - Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
