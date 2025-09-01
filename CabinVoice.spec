# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app_ui.py'],
    pathex=[],
    binaries=[('F:\\py386\\lib\\site-packages\\pyuipc.cp38-win32.pyd', '.')],
    datas=[('assets', 'assets'), ('sounds', 'sounds')],
    hiddenimports=['pyuipc', 'pygame', 'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='CabinVoice',
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
    icon=['assets\\airline_logo.ico'],
)
