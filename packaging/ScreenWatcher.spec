# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


SPEC_FILE = os.path.abspath(sys.argv[-1])
SPEC_DIR = os.path.abspath(os.path.dirname(SPEC_FILE))
PROJECT_ROOT = os.path.abspath(os.path.join(SPEC_DIR, ".."))
STAGING_ROOT = os.path.join(PROJECT_ROOT, "build", "staging")
DEFAULTS_ROOT = os.path.join(STAGING_ROOT, "defaults")
PLATFORM_TOOLS_ROOT = os.path.join(STAGING_ROOT, "platform-tools")


datas = []
binaries = []
hiddenimports = []


def safe_collect_data_files(module_name: str):
    try:
        return collect_data_files(module_name)
    except Exception:
        return []


def safe_collect_submodules(module_name: str):
    try:
        return collect_submodules(module_name)
    except Exception:
        return []

if os.path.isdir(DEFAULTS_ROOT):
    datas.append((DEFAULTS_ROOT, "defaults"))

if os.path.isdir(PLATFORM_TOOLS_ROOT):
    datas.append((PLATFORM_TOOLS_ROOT, "platform-tools"))

# WinRT OCR 和 Pillow 需要显式收集子模块/数据，避免打包后运行时报缺模块。
datas += safe_collect_data_files("PIL")
datas += safe_collect_data_files("winrt")
hiddenimports += collect_submodules("PIL")
hiddenimports += safe_collect_submodules("winrt")
hiddenimports += safe_collect_submodules("winrt.windows.foundation")
hiddenimports += safe_collect_submodules("winrt.windows.storage")
hiddenimports += safe_collect_submodules("winrt.windows.graphics")
hiddenimports += safe_collect_submodules("winrt.windows.media")
hiddenimports += [
    "winrt",
    "winrt.system",
    "winrt.windows",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.globalization",
    "winrt.windows.graphics",
    "winrt.windows.graphics.imaging",
    "winrt.windows.media",
    "winrt.windows.media.ocr",
    "winrt.windows.storage",
    "winrt.windows.storage.streams",
]


a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="ScreenWatcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ScreenWatcher",
)
