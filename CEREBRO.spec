# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for CEREBRO (CustomTkinter + cerebro).

Build (onedir, no console):
  pyinstaller --noconfirm CEREBRO.spec

Output: dist/CEREBRO/CEREBRO.exe
"""
from __future__ import annotations

from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
spec_root = Path(SPECPATH).resolve()

# --- Third-party assets (CTk themes, fonts, etc.) ---
datas: list[tuple[str, str]] = []
binaries: list = []
hiddenimports: list[str] = [
    "PIL._tkinter_finder",
    "yaml",
    "send2trash",
    "sqlite3",
    "darkdetect",
]

for pkg in ("customtkinter", "PIL"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Optional drag-and-drop (pip install tkinterdnd2); harmless if absent at build time.
try:
    d, b, h = collect_all("tkinterdnd2")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    hiddenimports.append("tkinterdnd2")

# Whole cerebro package (engines, v2 UI, theme JSON under cerebro/themes, etc.)
hiddenimports += collect_submodules("cerebro")

# Theme JSON is loaded by path — ensure tree is present under _MEIPASS/cerebro/themes
_themes = spec_root / "cerebro" / "themes"
if _themes.is_dir():
    datas.append((str(_themes), "cerebro/themes"))

# Duplicate themes at repo root (some installs reference themes/builtin)
_root_themes = spec_root / "themes"
if _root_themes.is_dir():
    datas.append((str(_root_themes), "themes"))

a = Analysis(
    ["main.py"],
    pathex=[str(spec_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Shrink bundle — test stack not needed in shipped GUI
        "pytest",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CEREBRO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(spec_root / "packaging" / "app.ico") if (spec_root / "packaging" / "app.ico").is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CEREBRO",
)
