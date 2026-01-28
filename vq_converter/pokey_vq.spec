# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['pokey_vq/gui.py'],
    pathex=[],
    binaries=[],
    datas=[('players', 'players'), ('bin', 'bin'), ('/home/ilm/.local/lib/python3.14/site-packages/customtkinter', 'customtkinter')],
    hiddenimports=['PIL._tkinter_finder', 'pokey_vq.encoders.vq', 'pokey_vq.encoders.raw', 'scipy.signal', 'scipy.io.wavfile', 'numpy', 'soundfile'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['librosa', 'numba', 'llvmlite', 'matplotlib', 'pandas', 'scikit-learn', 'sklearn', 'ipython', 'pytest', 'docutils'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pokey_vq',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
