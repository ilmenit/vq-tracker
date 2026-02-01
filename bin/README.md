# MADS Assembler Binaries

This directory contains platform-specific MADS (Mad Assembler) executables used for building Atari XEX files.

## Directory Structure

```
bin/
├── linux_x86_64/
│   └── mads           # Linux x86_64 binary
├── macos_aarch64/
│   └── mads           # macOS Apple Silicon (M1/M2/M3) binary
├── macos_x86_64/
│   └── mads           # macOS Intel binary
└── windows_x86_64/
    └── mads.exe       # Windows x64 binary
```

## Obtaining MADS

MADS (Mad Assembler) is a free 6502/65C02/65816 assembler by Tomasz Biela (Tebe).

**Download:** http://mads.atari8.info/

After downloading:
1. Extract the appropriate binary for your platform
2. Place it in the corresponding directory above
3. On Unix systems, ensure it's executable: `chmod +x mads`

## Verification

Test that MADS works:
```bash
# Linux/macOS
./bin/linux_x86_64/mads -h

# Windows
bin\windows_x86_64\mads.exe -h
```

## Building Releases

When building standalone executables with PyInstaller, these binaries are bundled into the application. Only the binary for the target platform is needed when building.

For cross-platform distribution, include binaries for all platforms you want to support.
