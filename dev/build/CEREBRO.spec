# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for CEREBRO (Flet + Flutter desktop).

Build (onedir, no console) from repo root:
  pyinstaller --noconfirm dev/build/CEREBRO.spec

Output: dist/CEREBRO/CEREBRO.exe
"""
from __future__ import annotations

from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
_repo_root = Path(SPECPATH).resolve().parent.parent

# --- Third-party assets ---
datas: list[tuple[str, str]] = []
binaries: list = []
hiddenimports: list[str] = [
    "yaml",
    "send2trash",
    "sqlite3",
    "flet",
]

for pkg in ("flet", "PIL"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:
        import sys as _sys
        _sys.stderr.write(
            f"[SPEC ERROR] collect_all({pkg!r}) failed: {exc}\n"
            f"Install the package before building: pip install {pkg}\n"
        )
        raise SystemExit(1) from exc

# Whole cerebro package (engines, v2 UI, etc.)
hiddenimports += collect_submodules("cerebro")

# Theme JSON is loaded by path — ensure tree is present under _MEIPASS/cerebro/themes
_themes = _repo_root / "cerebro" / "themes"
if _themes.is_dir():
    datas.append((str(_themes), "cerebro/themes"))

# Duplicate themes at repo root (some installs reference themes/builtin)
_root_themes = _repo_root / "themes"
if _root_themes.is_dir():
    datas.append((str(_root_themes), "themes"))

a = Analysis(
    [str(_repo_root / "main.py")],
    pathex=[str(_repo_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "unittest",
        "customtkinter",
        "tkinterdnd2",
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
    icon=str(_repo_root / "dev" / "packaging" / "app.ico")
    if (_repo_root / "dev" / "packaging" / "app.ico").is_file()
    else None,
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
