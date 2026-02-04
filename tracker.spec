# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for POKEY VQ Tracker

Build:
  pyinstaller tracker.spec --clean

How bundling works:
  - All Python code (tracker + pokey_vq) is FROZEN as compiled bytecode
  - Non-Python data (ASM players, fonts) is bundled at paths matching
    what builder.py expects when sys.frozen is True
  - asm/ and bin/ are NOT bundled (distributed alongside the executable)

Requirements:
  pip install pyinstaller dearpygui numpy scipy sounddevice pydub soundfile
"""

import os
import sys
import platform

try:
    spec_dir = SPECPATH
except NameError:
    spec_dir = os.getcwd()

sys.path.insert(0, spec_dir)
from version import VERSION, VERSION_DISPLAY, APP_NAME

# Platform settings
system = platform.system()
exe_name = 'POKEY_VQ_Tracker.exe' if system == 'Windows' else 'POKEY_VQ_Tracker'

# =========================================================================
# PATH SETUP
# =========================================================================
# Add vq_converter to BOTH sys.path (for spec-time collect_submodules)
# and pathex (for PyInstaller analysis-time module discovery).
vq_path = os.path.join(spec_dir, 'vq_converter')
pathex = []
if os.path.isdir(vq_path):
    sys.path.insert(0, vq_path)   # spec-time: so collect_submodules can import pokey_vq
    pathex.append(vq_path)         # analysis-time: so PyInstaller finds pokey_vq
    print(f"[SPEC] pathex += {vq_path}")
else:
    print(f"[SPEC] WARNING: vq_converter not found at {vq_path}")

# =========================================================================
# DATA FILES (non-Python resources needed at runtime)
# =========================================================================
# builder.py when frozen sets: pkg_root = sys._MEIPASS
# Then looks for: pkg_root/players/ and pkg_root/bin/
# So we bundle players/ at the MEIPASS root level.
datas = []

players_path = os.path.join(vq_path, 'players')
if os.path.isdir(players_path):
    datas.append((players_path, 'players'))
    print(f"[SPEC] Bundling players/ -> _MEIPASS/players/")

assets_path = os.path.join(vq_path, 'pokey_vq', 'assets')
if os.path.isdir(assets_path):
    datas.append((assets_path, os.path.join('pokey_vq', 'assets')))
    print(f"[SPEC] Bundling assets/ -> _MEIPASS/pokey_vq/assets/")

# =========================================================================
# BINARY COLLECTION (THE KEY FIX)
# =========================================================================
# CRITICAL: collect_dynamic_libs walks the package directory and collects
# ALL compiled C extensions (.pyd on Windows, .so on Linux/Mac).
#
# Without this, PyInstaller may MISS compiled extensions like
# scipy.sparse.csgraph._shortest_path even when their module names
# are in hiddenimports. hiddenimports handles Python bytecode discovery,
# but the actual .pyd/.so binary files need explicit collection.
#
# This was the root cause of "No module named 'scipy.sparse.csgraph._shortest_path'"
# - the module name was known but the .pyd file wasn't in the bundle.
from PyInstaller.utils.hooks import collect_dynamic_libs

extra_binaries = []
for pkg in ['scipy', 'numpy']:
    try:
        bins = collect_dynamic_libs(pkg)
        extra_binaries.extend(bins)
        print(f"[SPEC] collect_dynamic_libs('{pkg}'): {len(bins)} binary files")
    except Exception as e:
        print(f"[SPEC] collect_dynamic_libs('{pkg}') failed: {e}")

# =========================================================================
# HIDDEN IMPORTS
# =========================================================================
from PyInstaller.utils.hooks import collect_submodules

collected = []
for pkg in ['pokey_vq', 'scipy', 'numpy']:
    try:
        mods = collect_submodules(pkg)
        collected.extend(mods)
        print(f"[SPEC] collect_submodules('{pkg}'): {len(mods)} modules")
    except Exception as e:
        print(f"[SPEC] collect_submodules('{pkg}') failed: {e}")

# Filter out test modules - they bloat the build massively
# (scipy.*.tests.* alone is 500+ modules) and are never needed at runtime.
# The previous build was analyzing 500+ test modules for ~50 minutes.
before_count = len(collected)
collected = [m for m in collected
             if '.tests.' not in m           # scipy.signal.tests.test_foo
             and not m.endswith('.tests')     # scipy.signal.tests
             and '.test_' not in m           # rare inline test modules
             and '._test' not in m           # scipy.ndimage._ctest etc
             and '.conftest' not in m        # pytest conftest modules
             and '_precompute' not in m]     # scipy.special._precompute (build-time only)
print(f"[SPEC] Filtered {before_count - len(collected)} test/precompute modules, {len(collected)} remaining")

hiddenimports = collected + [
    # --- pokey_vq (explicit, in case collect_submodules misses any) ---
    'pokey_vq', 'pokey_vq.cli.builder', 'pokey_vq.cli.helpers',
    'pokey_vq.cli.main', 'pokey_vq.core.codebook',
    'pokey_vq.core.encoder_base', 'pokey_vq.core.experiment',
    'pokey_vq.core.pokey_table', 'pokey_vq.encoders.raw',
    'pokey_vq.encoders.vq', 'pokey_vq.utils.mads_exporter',
    'pokey_vq.utils.quality', 'pokey_vq.utils.gen_full_pokey_table',
    
    # --- scipy submodules explicitly needed by pokey_vq ---
    'scipy.io.wavfile', 'scipy.signal', 'scipy.signal.windows',
    'scipy.spatial.distance', 'scipy.sparse.csgraph',
    
    # --- Audio/GUI ---
    'sounddevice', 'soundfile', 'pydub',
    'dearpygui', 'dearpygui.dearpygui',
    
    # --- Stdlib that may be lazy-loaded ---
    'queue', 'threading', 'json', 'zipfile', 'wave', 'tempfile',
    'logging', 'dataclasses', 'io', 'contextlib', 'argparse',
    'time', 'shutil', 'platform', 'struct', 'array',
]

hiddenimports = list(set(hiddenimports))
print(f"[SPEC] Total hiddenimports: {len(hiddenimports)}")

excludes = [
    'tkinter', 'matplotlib', 'PIL', 'cv2',
]

# =========================================================================
# ANALYSIS
# =========================================================================
a = Analysis(
    ['main.py'],
    pathex=pathex,
    binaries=extra_binaries,   # <-- collected .pyd/.so files for scipy/numpy
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,   # Don't optimize - can break imports
)

# Remove unnecessary binaries (but be careful not to remove scipy/numpy extensions)
# NOTE: Previous version had '_test' and 'test_' patterns which is risky - removed.
exclude_bin_patterns = ['tcl', 'tk', 'tkinter', 'matplotlib']
a.binaries = [(n, p, k) for n, p, k in a.binaries
              if not any(pat in n.lower() for pat in exclude_bin_patterns)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

if system == 'Darwin':
    app = BUNDLE(
        exe,
        name=f'{APP_NAME}.app',
        icon=None,
        bundle_identifier='com.pokeyvq.tracker',
        info_plist={
            'CFBundleShortVersionString': VERSION_DISPLAY,
            'CFBundleVersion': VERSION,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.13.0',
        },
    )
