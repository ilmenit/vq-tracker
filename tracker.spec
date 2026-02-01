# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for POKEY VQ Tracker

Build commands:
  Windows:  pyinstaller tracker.spec
  macOS:    pyinstaller tracker.spec  
  Linux:    pyinstaller tracker.spec

The resulting executable will be in dist/ directory.

Requirements before building:
  1. Install PyInstaller: pip install pyinstaller
  2. Install all dependencies: pip install dearpygui numpy scipy sounddevice pydub
  3. Install pokey_vq: pip install pokey_vq (or install from source)
  4. Ensure bin/ folder contains MADS for target platform(s)

Directory structure expected:
  tracker_v3/
  ├── main.py
  ├── asm/           <- Assembly templates (included as data)
  ├── bin/           <- MADS executables (included as data)
  │   ├── linux_x86_64/mads
  │   ├── macos_aarch64/mads
  │   ├── macos_x86_64/mads
  │   └── windows_x86_64/mads.exe
  └── vq_converter/  <- Optional, if not using pip-installed pokey_vq
      └── pokey_vq/
"""

import os
import sys
import platform

# SPECPATH is provided by PyInstaller - it's the directory containing the spec file
# Note: __file__ is NOT defined in spec files, use SPECPATH instead
try:
    spec_dir = SPECPATH
except NameError:
    # Fallback for running outside PyInstaller (shouldn't happen normally)
    spec_dir = os.getcwd()

# Import version info
sys.path.insert(0, spec_dir)
from version import VERSION, VERSION_DISPLAY, APP_NAME

# Determine platform-specific settings
system = platform.system()
if system == 'Windows':
    exe_name = 'POKEY_VQ_Tracker.exe'
    icon_file = None  # Add icon path if available: 'resources/icon.ico'
    console = True    # Keep console visible for debug output
elif system == 'Darwin':
    exe_name = 'POKEY_VQ_Tracker'
    icon_file = None  # Add icon path if available: 'resources/icon.icns'
    console = True    # Keep console visible for debug output
else:
    exe_name = 'POKEY_VQ_Tracker'
    icon_file = None
    console = True    # Keep console visible for debug output

# Collect data files
datas = []

# Include ASM templates
asm_path = os.path.join(spec_dir, 'asm')
if os.path.isdir(asm_path):
    datas.append((asm_path, 'asm'))

# Include bin directory with MADS executables
bin_path = os.path.join(spec_dir, 'bin')
if os.path.isdir(bin_path):
    datas.append((bin_path, 'bin'))

# Include local vq_converter if present (for portable builds)
vq_path = os.path.join(spec_dir, 'vq_converter')
if os.path.isdir(vq_path):
    datas.append((vq_path, 'vq_converter'))

# Include default config file if present
config_path = os.path.join(spec_dir, 'tracker_config.json')
if os.path.isfile(config_path):
    datas.append((config_path, '.'))

# Hidden imports for modules that PyInstaller might miss
hiddenimports = [
    'numpy',
    'scipy',
    'scipy.io',
    'scipy.io.wavfile',
    'scipy.signal',
    'sounddevice',
    'pydub',
    'dearpygui',
    'dearpygui.dearpygui',
    # pokey_vq modules (if installed as package)
    'pokey_vq',
    'pokey_vq.cli',
    'pokey_vq.encoder',
    'pokey_vq.decoder',
    'pokey_vq.codebook',
    # Standard library modules that might be lazy-loaded
    'queue',
    'threading',
    'json',
    'zipfile',
    'wave',
    'tempfile',
    'logging',
    'dataclasses',
]

# Exclude unnecessary modules to reduce size
excludes = [
    'tkinter',
    'matplotlib',
    'PIL',
    'cv2',
    'test',
    'unittest',
    'doctest',
    'pdb',
    'pydoc',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,  # Basic optimization
)

# Filter out unnecessary data files to reduce size
def filter_binaries(binaries):
    """Remove unnecessary binaries."""
    exclude_patterns = [
        'tcl', 'tk', 'tkinter',
        'matplotlib',
        '_test', 'test_',
    ]
    filtered = []
    for name, path, kind in binaries:
        if not any(pat in name.lower() for pat in exclude_patterns):
            filtered.append((name, path, kind))
    return filtered

a.binaries = filter_binaries(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # Set to True for smaller size (removes debug symbols)
    upx=True,     # Use UPX compression if available
    upx_exclude=[],
    runtime_tmpdir=None,
    console=console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

# For macOS, optionally create an app bundle
if system == 'Darwin':
    app = BUNDLE(
        exe,
        name=f'{APP_NAME}.app',
        icon=icon_file,
        bundle_identifier='com.pokeyvq.tracker',
        info_plist={
            'CFBundleShortVersionString': VERSION_DISPLAY,
            'CFBundleVersion': VERSION,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.13.0',
        },
    )
