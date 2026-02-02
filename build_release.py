#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for POKEY VQ Tracker

Creates standalone executables and complete distribution packages for
Windows, macOS, and Linux using PyInstaller.

Usage:
    python build_release.py           # Build executable only
    python build_release.py --dist    # Build AND create distribution folder
    python build_release.py --clean   # Clean build (remove dist/, build/, release/)
    python build_release.py --check   # Check dependencies only

The distribution folder contains everything needed to run the tracker:
    release/
    ├── POKEY_VQ_Tracker.exe   # The executable
    ├── asm/                   # ASM templates (required for BUILD)
    ├── bin/                   # MADS assembler (required for BUILD)
    ├── samples/               # Example samples to get started
    ├── README.md              # Documentation
    ├── UserGuide.md           # Detailed user guide
    └── CHANGELOG.md           # Version history

Requirements:
    pip install pyinstaller dearpygui numpy scipy sounddevice pydub soundfile
"""

import os
import sys
import shutil
import platform
import subprocess
import argparse
from datetime import datetime

# Import version info
try:
    from version import VERSION, VERSION_DISPLAY, APP_NAME
except ImportError:
    VERSION = "0.0.0"
    VERSION_DISPLAY = "Beta"
    APP_NAME = "POKEY VQ Tracker"


def check_dependencies():
    """Check if all required packages are installed."""
    print("Checking Python dependencies...")
    
    required = [
        ('dearpygui', 'dearpygui'),
        ('numpy', 'numpy'),
        ('scipy', 'scipy'),
        ('sounddevice', 'sounddevice'),
        ('soundfile', 'soundfile'),
        ('pydub', 'pydub'),
        ('PyInstaller', 'PyInstaller'),
    ]
    
    missing = []
    for name, package in required:
        try:
            __import__(package.split('.')[0])
            print(f"  ✓ {name}")
        except ImportError:
            print(f"  ✗ {name} - MISSING")
            missing.append(name)
    
    # Check for vq_converter folder
    if os.path.isdir("vq_converter/pokey_vq"):
        print(f"  ✓ vq_converter folder found")
    else:
        print(f"  ○ vq_converter folder not found (needed for CONVERT functionality)")
    
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
        print(f"\nPlease download MADS from http://mads.atari8.info/")
        print(f"and place {binary} in bin/{plat_dir}/")
        return False


def check_asm_directory():
    """Check if asm directory exists with expected structure."""
    print("\nChecking ASM templates...")
    
    if not os.path.isdir("asm"):
        print("  ✗ asm/ directory not found")
        return False
    
    # Count files recursively
    total_files = 0
    for root, dirs, files in os.walk("asm"):
        total_files += len([f for f in files if f.endswith('.asm') or f.endswith('.inc')])
    
    # Check expected subdirectories
    expected_subdirs = ["common", "tracker", "pitch"]
    found_subdirs = [d for d in expected_subdirs if os.path.isdir(os.path.join("asm", d))]
    
    print(f"  ✓ Found asm/ directory with {total_files} files")
    print(f"    Subdirectories: {', '.join(found_subdirs)}")
    
    return len(found_subdirs) >= 2  # At least common and tracker


def check_samples_directory():
    """Check if samples directory exists."""
    print("\nChecking sample files...")
    
    if os.path.isdir("samples"):
        samples = [f for f in os.listdir("samples") 
                   if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac'))]
        print(f"  ✓ Found samples/ directory with {len(samples)} audio files")
        return True, len(samples)
    else:
        print("  ○ samples/ directory not found (optional - example samples)")
        return False, 0


def clean_build():
    """Remove build artifacts."""
    print("Cleaning build directories...")
    
    dirs_to_clean = ['build', 'dist', 'release', '__pycache__']
    
    for d in dirs_to_clean:
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"  Removed: {d}/")
    
    # Clean __pycache__ in subdirectories
    for root, dirs, files in os.walk('.'):
        if '.git' in root:
            continue
        for d in list(dirs):
            if d == '__pycache__':
                path = os.path.join(root, d)
                try:
                    shutil.rmtree(path)
                    print(f"  Removed: {path}")
                except:
                    pass
    
    # Remove any old zip files
    for f in os.listdir('.'):
        if f.startswith('POKEY_VQ_Tracker_') and f.endswith('.zip'):
            os.remove(f)
            print(f"  Removed: {f}")


def build_executable():
    """Run PyInstaller build."""
    print("\n" + "=" * 60)
    print("Building POKEY VQ Tracker Executable")
    print("=" * 60)
    
    system = platform.system()
    print(f"\nPlatform: {system} ({platform.machine()})")
    print(f"Python: {sys.version.split()[0]}")
    
    # Check spec file exists
    if not os.path.exists("tracker.spec"):
        print("\nERROR: tracker.spec not found")
        return None
    
    # Run PyInstaller
    print("\nRunning PyInstaller (this may take a few minutes)...")
    cmd = [sys.executable, "-m", "PyInstaller", "tracker.spec", "--noconfirm", "--clean"]
    
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print("\nERROR: PyInstaller build failed")
        return None
    
    # Find the output
    if system == "Windows":
        exe_name = "POKEY_VQ_Tracker.exe"
    else:
        exe_name = "POKEY_VQ_Tracker"
    
    exe_path = os.path.join("dist", exe_name)
    
    if os.path.exists(exe_path):
        size = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n✓ Executable built: {exe_path}")
        print(f"  Size: {size:.1f} MB")
        return exe_path
    else:
        print(f"\nERROR: Expected output not found: {exe_path}")
        return None


def create_distribution(exe_path: str):
    """Create complete distribution folder with all required files."""
    print("\n" + "=" * 60)
    print("Creating Distribution Package")
    print("=" * 60)
    
    system = platform.system()
    
    # Create release directory
    release_dir = "release"
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)
    os.makedirs(release_dir)
    
    copied_items = []
    warnings = []
    
    # 1. Copy executable
    exe_name = os.path.basename(exe_path)
    dest_exe = os.path.join(release_dir, exe_name)
    shutil.copy2(exe_path, dest_exe)
    exe_size = os.path.getsize(dest_exe) / (1024 * 1024)
    copied_items.append(f"  ✓ {exe_name} ({exe_size:.1f} MB)")
    
    # 2. Copy asm/ folder (REQUIRED for BUILD)
    if os.path.isdir("asm"):
        shutil.copytree("asm", os.path.join(release_dir, "asm"))
        asm_count = sum(1 for r, d, f in os.walk("asm") 
                       for file in f if file.endswith(('.asm', '.inc')))
        copied_items.append(f"  ✓ asm/ ({asm_count} files)")
    else:
        warnings.append("  ⚠ asm/ folder missing - BUILD will not work!")
    
    # 3. Copy bin/ folder (REQUIRED for BUILD - contains MADS)
    if os.path.isdir("bin"):
        shutil.copytree("bin", os.path.join(release_dir, "bin"))
        # Count MADS executables
        mads_count = 0
        for root, dirs, files in os.walk("bin"):
            mads_count += len([f for f in files if f.startswith('mads')])
        copied_items.append(f"  ✓ bin/ ({mads_count} MADS executables)")
    else:
        warnings.append("  ⚠ bin/ folder missing - BUILD will not work!")
    
    # 4. Copy samples/ folder (OPTIONAL - example samples for users)
    if os.path.isdir("samples"):
        shutil.copytree("samples", os.path.join(release_dir, "samples"))
        sample_count = len([f for f in os.listdir("samples") 
                          if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac'))])
        copied_items.append(f"  ✓ samples/ ({sample_count} example samples)")
    else:
        copied_items.append("  ○ samples/ (not found, skipped)")
    
    # 5. Copy documentation files
    docs = [
        ("README.md", "Main documentation", True),
        ("UserGuide.md", "Detailed user guide", True),
        ("CHANGELOG.md", "Version history", False),
        ("EXPORT_FORMAT.md", "Technical reference (developers)", False),
    ]
    
    for doc_file, description, required in docs:
        if os.path.isfile(doc_file):
            shutil.copy2(doc_file, os.path.join(release_dir, doc_file))
            copied_items.append(f"  ✓ {doc_file}")
        elif required:
            warnings.append(f"  ⚠ {doc_file} missing")
        else:
            copied_items.append(f"  ○ {doc_file} (not found, skipped)")
    
    # Print summary
    print("\nDistribution contents:")
    for item in copied_items:
        print(item)
    
    if warnings:
        print("\nWarnings:")
        for warn in warnings:
            print(warn)
    
    # Calculate total size
    total_size = 0
    for root, dirs, files in os.walk(release_dir):
        for f in files:
            total_size += os.path.getsize(os.path.join(root, f))
    
    print(f"\nTotal size: {total_size / (1024 * 1024):.1f} MB")
    print(f"Location: {os.path.abspath(release_dir)}/")
    
    # Create ZIP archive
    version_str = VERSION_DISPLAY.replace(" ", "_").replace(".", "_")
    platform_str = system.lower()
    if system == "Darwin":
        machine = platform.machine().lower()
        platform_str = "macos_arm64" if "arm" in machine or "aarch" in machine else "macos_x64"
    elif system == "Linux":
        platform_str = "linux_x64"
    elif system == "Windows":
        platform_str = "windows_x64"
    
    zip_name = f"POKEY_VQ_Tracker_{version_str}_{platform_str}"
    print(f"\nCreating ZIP archive: {zip_name}.zip")
    shutil.make_archive(zip_name, 'zip', release_dir)
    zip_size = os.path.getsize(f"{zip_name}.zip") / (1024 * 1024)
    print(f"  Size: {zip_size:.1f} MB")
    
    return release_dir, f"{zip_name}.zip"


def print_final_instructions(release_dir: str, zip_file: str):
    """Print final instructions for the user."""
    system = platform.system()
    
    print("\n" + "=" * 60)
    print("BUILD COMPLETE!")
    print("=" * 60)
    
    print(f"""
Distribution created successfully!

Files:
  • Folder: {os.path.abspath(release_dir)}/
  • Archive: {os.path.abspath(zip_file)}

To distribute:
  1. Share the ZIP file ({zip_file}), OR
  2. Share the entire '{release_dir}/' folder

Contents included:
  • Executable (vq_converter bundled inside)
  • asm/ folder (ASM templates for BUILD)
  • bin/ folder (MADS assembler for BUILD)
  • samples/ folder (example audio to get started)
  • Documentation files

Users do NOT need Python installed - everything is self-contained!
""")
    
    if system == "Windows":
        print(f"To test: {release_dir}\\POKEY_VQ_Tracker.exe")
    else:
        print(f"To test: ./{release_dir}/POKEY_VQ_Tracker")


def main():
    parser = argparse.ArgumentParser(
        description="Build POKEY VQ Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_release.py           # Build executable only
  python build_release.py --dist    # Build + create distribution folder
  python build_release.py --clean   # Clean all build artifacts
  python build_release.py --check   # Check dependencies only
        """
    )
    parser.add_argument("--clean", action="store_true", 
                        help="Clean build directories before building")
    parser.add_argument("--check", action="store_true", 
                        help="Check dependencies only, don't build")
    parser.add_argument("--dist", action="store_true",
                        help="Create complete distribution folder after building")
    args = parser.parse_args()
    
    # Change to script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir:
        os.chdir(script_dir)
    
    print(f"\nPOKEY VQ Tracker Build Script")
    print(f"Version: {VERSION_DISPLAY}")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if args.clean:
        clean_build()
        if not (args.check or args.dist):
            print("\nCleaned. Run without --clean to build.")
            return
    
    # Check dependencies
    print("\n" + "-" * 60)
    deps_ok = check_dependencies()
    bin_ok = check_bin_directory()
    asm_ok = check_asm_directory()
    samples_ok, sample_count = check_samples_directory()
    
    if args.check:
        print("\n" + "=" * 60)
        if deps_ok and bin_ok and asm_ok:
            print("All required checks passed! Ready to build.")
            if not samples_ok:
                print("Note: samples/ folder not found (optional, for example music)")
        else:
            print("Some checks failed. Please fix issues above.")
            if not deps_ok:
                print("\nInstall missing packages with:")
                print("  pip install pyinstaller dearpygui numpy scipy sounddevice pydub soundfile")
        return
    
    if not deps_ok:
        print("\nCannot build due to missing Python dependencies.")
        print("Install with: pip install pyinstaller dearpygui numpy scipy sounddevice pydub soundfile")
        sys.exit(1)
    
    if not (bin_ok and asm_ok):
        print("\nCannot build due to missing files (asm/ or bin/).")
        print("Run with --check for details.")
        sys.exit(1)
    
    # Build executable
    exe_path = build_executable()
    if not exe_path:
        sys.exit(1)
    
    # Create distribution if requested (or by default now)
    if args.dist:
        release_dir, zip_file = create_distribution(exe_path)
        print_final_instructions(release_dir, zip_file)
    else:
        print("\n" + "=" * 60)
        print("EXECUTABLE BUILD SUCCESSFUL!")
        print("=" * 60)
        print(f"\nExecutable: {exe_path}")
        print("\nTo create a complete distribution folder with asm/, bin/, samples/:")
        print("  python build_release.py --dist")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
