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
for pkg in ['scipy', 'numpy', 'sounddevice']:
    try:
        bins = collect_dynamic_libs(pkg)
        extra_binaries.extend(bins)
        print(f"[SPEC] collect_dynamic_libs('{pkg}'): {len(bins)} binary files")
    except Exception as e:
        print(f"[SPEC] collect_dynamic_libs('{pkg}') failed: {e}")

# Also try _sounddevice_data which some pip installs use to bundle PortAudio
try:
    bins = collect_dynamic_libs('_sounddevice_data')
    extra_binaries.extend(bins)
    print(f"[SPEC] collect_dynamic_libs('_sounddevice_data'): {len(bins)} binary files")
    for src, dst in bins:
        print(f"[SPEC]   -> {src}")
except Exception as e:
    print(f"[SPEC] _sounddevice_data not available: {e}")

# -------------------------------------------------------------------------
# PORTAUDIO DIAGNOSTICS & BUNDLING
# -------------------------------------------------------------------------
# sounddevice loads PortAudio via ctypes at runtime. On Windows the DLL is
# typically bundled with the pip package, but on Linux/macOS it's a system
# library that PyInstaller does NOT auto-detect. Without it the app crashes
# with "OSError: PortAudio library not found" on machines where libportaudio
# is not installed.
print(f"[SPEC] =========== PortAudio diagnostics ===========")
print(f"[SPEC] Build platform: {system} ({platform.machine()})")

# Diagnostic: How does sounddevice find PortAudio on THIS system?
try:
    import sounddevice as _sd
    _pa_lib = getattr(_sd, '_lib', None)
    if _pa_lib is not None:
        print(f"[SPEC] sounddevice._lib = {_pa_lib}")
        _ffi = getattr(_sd, '_ffi', None)
        if _ffi:
            print(f"[SPEC] sounddevice._ffi = {_ffi}")
    else:
        print(f"[SPEC] sounddevice._lib is None (unusual)")
    print(f"[SPEC] sounddevice.__file__ = {_sd.__file__}")
    _sd_dir = os.path.dirname(_sd.__file__)
    print(f"[SPEC] sounddevice directory contents:")
    for f in sorted(os.listdir(_sd_dir)):
        fpath = os.path.join(_sd_dir, f)
        if os.path.isfile(fpath):
            fsize = os.path.getsize(fpath)
            print(f"[SPEC]   {f} ({fsize:,} bytes)")
        else:
            print(f"[SPEC]   {f}/")
except Exception as e:
    print(f"[SPEC] sounddevice diagnostic import failed: {e}")

# Diagnostic: Check _sounddevice_data package (pip-bundled PortAudio)
try:
    import _sounddevice_data
    _sdd_dir = os.path.dirname(_sounddevice_data.__file__)
    print(f"[SPEC] _sounddevice_data found at: {_sdd_dir}")
    print(f"[SPEC] _sounddevice_data contents:")
    for root, dirs, files in os.walk(_sdd_dir):
        for f in sorted(files):
            fpath = os.path.join(root, f)
            relpath = os.path.relpath(fpath, _sdd_dir)
            fsize = os.path.getsize(fpath)
            print(f"[SPEC]   {relpath} ({fsize:,} bytes)")
except ImportError:
    print(f"[SPEC] _sounddevice_data package NOT installed (no pip-bundled PortAudio)")
except Exception as e:
    print(f"[SPEC] _sounddevice_data error: {e}")

# Now actually find and bundle PortAudio
import subprocess as _sp
import glob as _glob

_pa_binaries = []  # Collect PortAudio-specific binaries here

if system in ('Linux', 'Darwin'):
    # Method 1: Check if sounddevice ships its own PortAudio (via _sounddevice_data)
    try:
        import _sounddevice_data
        _sdd_dir = os.path.dirname(_sounddevice_data.__file__)
        for root, dirs, files in os.walk(_sdd_dir):
            for f in files:
                if 'portaudio' in f.lower() or f.endswith('.so') or f.endswith('.dylib'):
                    fpath = os.path.join(root, f)
                    _pa_binaries.append((fpath, '.'))
                    print(f"[SPEC] PA Method 1 (_sounddevice_data): {fpath}")
    except ImportError:
        pass

    # Method 2: ldconfig (Linux only)
    if system == 'Linux' and not _pa_binaries:
        try:
            result = _sp.run(['ldconfig', '-p'], capture_output=True, text=True)
            print(f"[SPEC] ldconfig returned {len(result.stdout.splitlines())} entries")
            for line in result.stdout.split('\n'):
                if 'libportaudio' in line:
                    print(f"[SPEC]   ldconfig match: {line.strip()}")
                    if '=>' in line:
                        pa_path = line.split('=>')[-1].strip()
                        if os.path.isfile(pa_path):
                            _pa_binaries.append((pa_path, '.'))
                            print(f"[SPEC] PA Method 2 (ldconfig): {pa_path}")
                        else:
                            print(f"[SPEC]   WARNING: path does not exist: {pa_path}")
        except Exception as e:
            print(f"[SPEC] ldconfig search failed: {e}")

    # Method 3: Common library paths (broadest fallback)
    if not _pa_binaries:
        search_patterns = (
            ['/usr/lib/x86_64-linux-gnu/libportaudio*',
             '/usr/lib64/libportaudio*',
             '/usr/lib/libportaudio*',
             '/usr/local/lib/libportaudio*',
             '/usr/local/lib64/libportaudio*']
            if system == 'Linux' else
            ['/usr/local/lib/libportaudio*',
             '/opt/homebrew/lib/libportaudio*',
             '/usr/lib/libportaudio*']
        )
        for pattern in search_patterns:
            matches = sorted(_glob.glob(pattern))
            if matches:
                print(f"[SPEC] PA Method 3 glob '{pattern}': {matches}")
            for path in matches:
                if os.path.isfile(path):
                    _pa_binaries.append((path, '.'))
                    print(f"[SPEC] PA Method 3 (glob): {path}")

    # Method 4: Use ctypes to find what sounddevice actually loaded
    if not _pa_binaries:
        try:
            import ctypes.util
            pa_name = ctypes.util.find_library('portaudio')
            print(f"[SPEC] ctypes.util.find_library('portaudio') = {pa_name}")
            if pa_name:
                result = _sp.run(['ldconfig', '-p'], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if pa_name in line and '=>' in line:
                        pa_path = line.split('=>')[-1].strip()
                        if os.path.isfile(pa_path):
                            _pa_binaries.append((pa_path, '.'))
                            print(f"[SPEC] PA Method 4 (ctypes): {pa_path}")
        except Exception as e:
            print(f"[SPEC] ctypes search failed: {e}")

    # Deduplicate and add to extra_binaries
    if _pa_binaries:
        seen = set()
        for src, dst in _pa_binaries:
            bname = os.path.basename(src)
            if bname not in seen:
                seen.add(bname)
                extra_binaries.append((src, dst))
                print(f"[SPEC] >>> WILL BUNDLE: {bname} <- {src}")
    else:
        print(f"[SPEC] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"[SPEC] WARNING: libportaudio NOT FOUND by any method!")
        print(f"[SPEC] Audio will NOT work on target machines.")
        print(f"[SPEC] Install:")
        print(f"[SPEC]   Fedora:        sudo dnf install portaudio-devel")
        print(f"[SPEC]   Debian/Ubuntu:  sudo apt install libportaudio2")
        print(f"[SPEC]   macOS:          brew install portaudio")
        print(f"[SPEC] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

elif system == 'Windows':
    print(f"[SPEC] Windows: PortAudio should be bundled by sounddevice pip package")

# Final summary of ALL binaries being bundled that relate to audio
print(f"[SPEC] =========== Audio-related binaries in bundle ===========")
for src, dst in extra_binaries:
    bname = os.path.basename(src).lower()
    if any(k in bname for k in ('portaudio', 'sounddevice', '_sounddevice', 'pa_', 'audio')):
        print(f"[SPEC]   {os.path.basename(src)} <- {src}")
print(f"[SPEC] =========================================================")

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
