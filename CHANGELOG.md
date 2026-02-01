# POKEY VQ Tracker - Changelog

All notable changes to this project will be documented in this file.

## [Beta 1] - 2025-02

### Initial Public Release

This is the first public beta release of POKEY VQ Tracker — an experimental sample-based music tracker for Atari XL/XE computers.

### Core Features

- **3-Channel Polyphonic Playback**: Play three independent sample-based voices simultaneously on stock 64K Atari
- **Variable Pitch Control**: 4 octaves (48 semitones) with real-time 8.8 fixed-point pitch calculation
- **VQ Compression**: Vector Quantization compression for efficient sample storage
- **Pattern-Based Sequencing**: Classic tracker-style composition with patterns and songlines
- **Real-Time Preview**: Hear your music in the tracker before exporting
- **One-Click Build**: Export to Atari executable (.xex) with integrated MADS assembler

### Audio Features

- Multi-format sample import (WAV, MP3, OGG, FLAC, AIFF, M4A)
- Adjustable sample rate (3333-15834 Hz)
- Adjustable vector size (2, 4, 8, 16)
- Speed/Size optimization modes
- Optional per-note volume control
- Optional display during playback
- Optional keyboard control during playback

### Editor Features

- Piano keyboard note entry (two-octave layout)
- Pattern copy/paste/transpose
- Undo/redo support
- Hex/decimal display toggle
- Real-time row highlighting
- Follow mode for playback

### Project Management

- Self-contained .pvq project format (ZIP-based)
- Embedded samples in project files
- Auto-save functionality
- Recent files list
- Editor state preservation

### Analysis Tools

- CPU cycle budget analysis
- Timing estimation for playback feasibility
- Per-row cycle cost calculation
- Configuration recommendations

### Build System

- Cross-platform standalone executable support
- Windows, macOS, Linux build scripts
- PyInstaller integration
- Bundled MADS assembler support

### Known Limitations

- ANALYZE provides estimates, not cycle-accurate emulation
- No effect commands (portamento, vibrato, etc.)
- Single codebook for all samples
- Base RAM only (no extended memory support)
- PAL timing primary focus (NTSC less tested)

### Technical Details

- Python 3.8+ with DearPyGui
- 6502 assembly playback engine
- Optimized IRQ handlers (Speed: ~63 cycles, Size: ~83 cycles per channel)
- Variable-length event encoding for compact song data

---

## Future Plans

See UserGuide.md "Future Roadmap" section for planned features including:
- Cycle-accurate emulation in tracker
- Extended memory support
- Multi-codebook compression
- Effect commands
- And more...

---

## Credits

- MADS Assembler by Tomasz Biela (Tebe)
- Altirra Emulator by Avery Lee
- DearPyGui by Jonathan Hoffstadt
- The Atari 8-bit community

---

*Thank you for trying POKEY VQ Tracker! Feedback and bug reports welcome.*
