# -*- mode: python ; coding: utf-8 -*-
"""
myolo-pcontrol 桌面控制端 —— PyInstaller 打包配置。

用法：在 pc/ 目录下执行
    pyinstaller desktop.spec

说明：
  - onefile：单文件可执行程序（myolo-pcontrol-desktop.exe）。
  - windowed：不弹黑色控制台窗口（console=False）。
    调试时可临时把下方 console=False 改为 True，以便在控制台看到打印/报错。
  - 因为 gui.py 顶层 import 了同目录的 mouse_controller 与 protocol，
    PyInstaller 会把它们一并打包；pynput 是动态后端，需显式 hiddenimports。
"""

a = Analysis(
    ["gui.py"],
    pathex=["."],  # 保证能找到同目录的 mouse_controller.py / protocol.py
    binaries=[],
    datas=[],
    hiddenimports=[
        "pynput",
        "pynput.mouse",
        "pynput.keyboard",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="myolo-pcontrol-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口；调试时改为 True
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
