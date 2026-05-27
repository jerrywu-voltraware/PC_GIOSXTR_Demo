# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_all


block_cipher = None
numpy_core_hiddenimports = collect_submodules("numpy._core")
winrt_hiddenimports = collect_submodules("winrt")
bleak_hiddenimports = collect_submodules("bleak")

# winrt 3.x splits its WinRT bindings across many sibling distributions
# (winrt-Windows.Devices.Bluetooth, winrt-Windows.Devices.Bluetooth.Advertisement, ...).
# collect_submodules("winrt") alone may miss some of them depending on how the
# namespace package is laid out, so we pull every winrt-* distribution in
# explicitly with collect_all to gather submodules, datas, and binaries.
extra_winrt_datas = []
extra_winrt_binaries = []
for _winrt_pkg in (
    "winrt.runtime",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.storage.streams",
    "winrt.windows.devices.enumeration",
    "winrt.windows.devices.radios",
    "winrt.windows.devices.bluetooth",
    "winrt.windows.devices.bluetooth.advertisement",
    "winrt.windows.devices.bluetooth.genericattributeprofile",
):
    try:
        _datas, _binaries, _hidden = collect_all(_winrt_pkg)
    except Exception:
        continue
    extra_winrt_datas += _datas
    extra_winrt_binaries += _binaries
    winrt_hiddenimports += _hidden

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=extra_winrt_binaries,
    datas=[("1024.png", "."), ("assets", "assets"), *extra_winrt_datas],
    hiddenimports=[
        "qasync",
        "bleak",
        "bleak.backends.winrt",
        "bleak.backends.winrt.scanner",
        "bleak.backends.winrt.client",
        "bleak.backends.winrt.util",
        "bleak.args.winrt",
        "pyqtgraph",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "asyncio",
        "winrt.windows.devices.bluetooth",
        "winrt.windows.devices.bluetooth.advertisement",
        "winrt.windows.devices.bluetooth.genericattributeprofile",
        "winrt.windows.devices.enumeration",
        "winrt.windows.devices.radios",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.storage.streams",
        *numpy_core_hiddenimports,
        *winrt_hiddenimports,
        *bleak_hiddenimports,
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
    name="PC_GIOSXTR_Demo_V1.0.15",
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
