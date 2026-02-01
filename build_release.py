#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for POKEY VQ Tracker

Creates standalone executables for Windows, macOS, and Linux using PyInstaller.

Usage:
    python build_release.py           # Build for current platform
    python build_release.py --clean   # Clean build (remove dist/ and build/)
    python build_release.py --check   # Check dependencies only

Requirements:
    pip install pyinstaller dearpygui numpy scipy sounddevice pydub

The bin/ directory must contain MADS executables for target platforms:
    bin/
    ├── linux_x86_64/mads
    ├── macos_aarch64/mads
    ├── macos_x86_64/mads
    └── windows_x86_64/mads.exe
"""

import os
import sys
import shutil
import platform
import subprocess
import argparse


def check_dependencies():
    """Check if all required packages are installed."""
    print("Checking dependencies...")
    
    required = [
        ('dearpygui', 'dearpygui'),
        ('numpy', 'numpy'),
        ('scipy', 'scipy'),
        ('sounddevice', 'sounddevice'),
        ('pydub', 'pydub'),
        ('PyInstaller', 'pyinstaller'),
    ]
    
    optional = [
        ('pokey_vq', 'pokey_vq'),  # May be in vq_converter/ instead
    ]
    
    missing = []
    for name, package in required:
        try:
            __import__(package.split('.')[0])
            print(f"  ✓ {name}")
        except ImportError:
            print(f"  ✗ {name} - MISSING")
            missing.append(name)
    
    for name, package in optional:
        try:
            __import__(package.split('.')[0])
            print(f"  ✓ {name} (optional)")
        except ImportError:
            print(f"  ○ {name} (optional, not found - will use vq_converter/ if available)")
    
    if missing:
        print(f"\nMissing required packages: {', '.join(missing)}")
        print("Install with: pip install " + ' '.join(missing))
        return False
    
    return True


def check_bin_directory():
    """Check if bin directory with MADS exists."""
    print("\nChecking MADS binaries...")
    
    system = platform.system()
    machine = platform.machine().lower()
    
    if system == "Linux":
        plat_dir = "linux_x86_64"
        binary = "mads"
    elif system == "Darwin":
        plat_dir = "macos_aarch64" if "arm" in machine or "aarch" in machine else "macos_x86_64"
        binary = "mads"
    elif system == "Windows":
        plat_dir = "windows_x86_64"
        binary = "mads.exe"
    else:
        print(f"  ✗ Unsupported platform: {system}")
        return False
    
    mads_path = os.path.join("bin", plat_dir, binary)
    
    if os.path.exists(mads_path):
        print(f"  ✓ Found: {mads_path}")
        return True
    else:
        print(f"  ✗ Not found: {mads_path}")
        print(f"\nPlease create bin/{plat_dir}/ and add {binary}")
        return False


def check_asm_directory():
    """Check if asm directory exists."""
    print("\nChecking ASM templates...")
    
    if os.path.isdir("asm"):
        count = len([f for f in os.listdir("asm") if f.endswith('.asm') or f.endswith('.inc')])
        print(f"  ✓ Found asm/ directory with {count} files")
        return True
    else:
        print("  ✗ asm/ directory not found")
        return False


def clean_build():
    """Remove build artifacts."""
    print("Cleaning build directories...")
    
    dirs_to_clean = ['build', 'dist', '__pycache__']
    files_to_clean = ['*.pyc', '*.pyo']
    
    for d in dirs_to_clean:
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"  Removed: {d}/")
    
    # Clean __pycache__ in subdirectories
    for root, dirs, files in os.walk('.'):
        for d in dirs:
            if d == '__pycache__':
                path = os.path.join(root, d)
                shutil.rmtree(path)
                print(f"  Removed: {path}")


def build():
    """Run PyInstaller build."""
    print("\n" + "=" * 60)
    print("Building POKEY VQ Tracker")
    print("=" * 60)
    
    system = platform.system()
    print(f"\nPlatform: {system} ({platform.machine()})")
    print(f"Python: {sys.version}")
    
    # Check spec file exists
    if not os.path.exists("tracker.spec"):
        print("\nERROR: tracker.spec not found")
        return False
    
    # Run PyInstaller
    print("\nRunning PyInstaller...")
    cmd = [sys.executable, "-m", "PyInstaller", "tracker.spec", "--noconfirm"]
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("BUILD SUCCESSFUL!")
        print("=" * 60)
        
        # Find the output
        if system == "Windows":
            exe_path = os.path.join("dist", "POKEY_VQ_Tracker.exe")
        else:
            exe_path = os.path.join("dist", "POKEY_VQ_Tracker")
        
        if os.path.exists(exe_path):
            size = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\nOutput: {exe_path}")
            print(f"Size: {size:.1f} MB")
        
        print("\nTo run: " + exe_path)
        return True
    else:
        print("\nERROR: Build failed")
        return False


def main():
    parser = argparse.ArgumentParser(description="Build POKEY VQ Tracker")
    parser.add_argument("--clean", action="store_true", help="Clean build directories")
    parser.add_argument("--check", action="store_true", help="Check dependencies only")
    args = parser.parse_args()
    
    # Change to script directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or '.')
    
    if args.clean:
        clean_build()
        if not args.check:
            print("\nCleaned. Run without --clean to build.")
            return
    
    # Check dependencies
    deps_ok = check_dependencies()
    bin_ok = check_bin_directory()
    asm_ok = check_asm_directory()
    
    if args.check:
        print("\n" + "=" * 60)
        if deps_ok and bin_ok and asm_ok:
            print("All checks passed! Ready to build.")
        else:
            print("Some checks failed. Please fix issues above.")
        return
    
    if not (deps_ok and bin_ok and asm_ok):
        print("\nCannot build due to missing dependencies.")
        print("Run with --check for details.")
        sys.exit(1)
    
    # Build
    if build():
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
