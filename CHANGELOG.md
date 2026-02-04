# POKEY VQ Tracker - Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

---

## [Beta 2] - 2025-02

### Bug Fixes

- **Song editor undo not recorded**: Editing pattern assignments or speed
  values in the song editor via keyboard did not create an undo snapshot.
  Changes were silently permanent. (`keyboard.py`: added `save_undo("Edit song")`
  before `_apply_song_pattern_value` commits)
- **Autosave lost VQ settings**: The `vq_enhance` and `vq_optimize_speed`
  fields were not included in the `EditorState` written by autosave, causing
  these settings to reset to defaults when restoring from an autosave.
  (`ui_globals.py`: added both fields to the autosave `EditorState` constructor)

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
`ui_build.py`, `audio_engine.py`, `file_io.py`.
Unchanged: all ASM sources, `build.py`, `data_model.py`, `state.py`,
`constants.py`, `runtime.py`, `ui_refresh.py`, `ui_theme.py`, `ui_browser.py`,
`ui_dialogs.py`, `analyze.py`, `vq_convert.py`, `build_release.py`.

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

- Song editor keyboard edits did not record undo snapshots
- Autosave did not persist `vq_enhance` and `vq_optimize_speed` settings
- Bare `except:` clauses throughout the codebase silently swallowed errors
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
