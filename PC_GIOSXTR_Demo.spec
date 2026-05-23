# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None
numpy_core_hiddenimports = collect_submodules("numpy._core")
winrt_hiddenimports = collect_submodules("winrt")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("1024.png", ".")],
    hiddenimports=[
        "qasync",
        "bleak",
        "bleak.backends.winrt",
        "bleak.backends.winrt.scanner",
        "bleak.backends.winrt.client",
        "pyqtgraph",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "asyncio",
        *numpy_core_hiddenimports,
        *winrt_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PC_GIOSXTR_Demo_V1.0.0",
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
    icon="app_icon.ico",
    version="version_info.txt",
)
