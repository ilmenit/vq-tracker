# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for POKEY VQ Tracker

Build commands:
  Windows:  pyinstaller tracker.spec --clean
  macOS:    pyinstaller tracker.spec --clean
  Linux:    pyinstaller tracker.spec --clean

The resulting executable will be in dist/ directory.

Requirements before building:
  1. Install PyInstaller: pip install pyinstaller
  2. Install dependencies: pip install dearpygui numpy scipy sounddevice pydub soundfile
  3. Place vq_converter folder alongside this spec file
  4. Place bin/ folder with MADS for target platform(s)

Directory structure expected:
  tracker_v3/
  ├── main.py
  ├── asm/           <- Assembly templates (alongside exe, not bundled)
  ├── bin/           <- MADS executables (alongside exe, not bundled)
  │   └── windows_x86_64/mads.exe
  └── vq_converter/  <- VQ conversion (bundled as Python package)
      └── pokey_vq/
"""

import os
import sys
import platform

# SPECPATH is provided by PyInstaller - it's the directory containing the spec file
try:
    spec_dir = SPECPATH
except NameError:
    spec_dir = os.getcwd()

# Import version info
sys.path.insert(0, spec_dir)
from version import VERSION, VERSION_DISPLAY, APP_NAME

# Determine platform-specific settings
system = platform.system()
if system == 'Windows':
    exe_name = 'POKEY_VQ_Tracker.exe'
    icon_file = None
    console = True
elif system == 'Darwin':
    exe_name = 'POKEY_VQ_Tracker'
    icon_file = None
    console = True
else:
    exe_name = 'POKEY_VQ_Tracker'
    icon_file = None
    console = True

# Collect data files
datas = []

# Bundle vq_converter as a Python package (so it can be imported directly)
vq_path = os.path.join(spec_dir, 'vq_converter')
if os.path.isdir(vq_path):
    # Add as data so the package structure is preserved
    datas.append((vq_path, 'vq_converter'))
    print(f"Bundling vq_converter from: {vq_path}")

# NOTE: asm/ and bin/ are NOT bundled - they should be distributed alongside the executable
# This allows users to modify ASM files and keeps the bundle smaller

# Hidden imports for modules that PyInstaller might miss
hiddenimports = [
    # Core tracker dependencies
    'numpy',
    'scipy',
    'scipy.io',
    'scipy.io.wavfile',
    'scipy.signal',
    'sounddevice',
    'soundfile',  # Required by pokey_vq
    'pydub',
    'dearpygui',
    'dearpygui.dearpygui',
    
    # pokey_vq submodules (bundled via vq_converter folder)
    'pokey_vq',
    'pokey_vq.cli',
    'pokey_vq.cli.builder',
    'pokey_vq.cli.helpers',
    'pokey_vq.cli.main',
    'pokey_vq.encoders',
    'pokey_vq.encoders.vq',
    'pokey_vq.encoders.raw',
    'pokey_vq.utils',
    'pokey_vq.utils.quality',
    'pokey_vq.utils.mads_exporter',
    'pokey_vq.core',
    'pokey_vq.core.pokey_table',
    'pokey_vq.core.encoder_base',
    'pokey_vq.core.experiment',
    'pokey_vq.core.codebook',
    
    # Standard library modules that might be lazy-loaded
    'queue',
    'threading',
    'json',
    'zipfile',
    'wave',
    'tempfile',
    'logging',
    'dataclasses',
    'io',
    'contextlib',
    'argparse',
    'time',
    'shutil',
    'platform',
]

# Exclude unnecessary modules to reduce size
# NOTE: Do NOT exclude 'unittest' - pokey_vq import chain requires it
excludes = [
    'tkinter',
    'matplotlib',
    'PIL',
    'cv2',
    'test',
    # 'unittest',  # Required by pokey_vq/numpy/scipy import chain
    'doctest',
    'pdb',
    'pydoc',
]

# Add vq_converter to analysis paths so it can be found
pathex = []
if os.path.isdir(vq_path):
    pathex.append(vq_path)

a = Analysis(
    ['main.py'],
    pathex=pathex,
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
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
    strip=False,
    upx=True,
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
