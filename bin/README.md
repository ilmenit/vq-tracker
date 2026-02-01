# Binary Dependencies

This directory contains platform-specific executables required by the tracker.

## Directory Structure

```
bin/
├── linux_x86_64/
│   └── mads           # Linux x86_64 MADS assembler
├── macos_aarch64/
│   └── mads           # macOS Apple Silicon MADS assembler
├── macos_x86_64/
│   └── mads           # macOS Intel MADS assembler
└── windows_x86_64/
    ├── mads.exe       # Windows x64 MADS assembler
    ├── ffmpeg.exe     # (Optional) FFmpeg for audio format support
    └── ffprobe.exe    # (Optional) FFprobe for audio analysis
```

## Required: MADS Assembler

MADS (Mad Assembler) is a free 6502/65C02/65816 assembler by Tomasz Biela (Tebe).

**Download:** http://mads.atari8.info/

After downloading:
1. Extract the appropriate binary for your platform
2. Place it in the corresponding directory above
3. On Unix systems, ensure it's executable: `chmod +x mads`

## Optional: FFmpeg (Windows)

FFmpeg enables importing MP3, OGG, FLAC, M4A, and other audio formats.
Without FFmpeg, only WAV files can be imported.

**Download:** https://www.gyan.dev/ffmpeg/builds/
- Get the "ffmpeg-release-essentials.zip" (smaller) or "ffmpeg-release-full.zip"
- Extract `ffmpeg.exe` and `ffprobe.exe` from the `bin/` folder inside the archive
- Place them in `bin/windows_x86_64/`

The tracker automatically detects bundled FFmpeg and uses it.
Linux/macOS users typically have ffmpeg available system-wide via package managers.

## Verification

Test that MADS works:
```bash
# Linux/macOS
./bin/linux_x86_64/mads -h

# Windows
bin\windows_x86_64\mads.exe -h
```

Test FFmpeg (optional):
```cmd
bin\windows_x86_64\ffmpeg.exe -version
```

## Building Releases

When building standalone executables with PyInstaller, these binaries are bundled into the application. Only binaries for the target platform are needed when building.

For cross-platform distribution, include binaries for all platforms you want to support.
