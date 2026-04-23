"""
Optional first-run dependency bootstrap for **source / venv** launches.

PyInstaller (and similar) bundles a private interpreter — ``pip install``
cannot extend that layout meaningfully, so when ``sys.frozen`` is true this
module returns immediately and the spec must ship all wheels.

Environment:
    CEREBRO_SKIP_AUTO_DEPS=1  — disable network install (fail fast if imports missing).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

# (import root as used by find_spec, pip distribution name)
# Keep aligned with requirements.txt.
_REQUIRED: Tuple[Tuple[str, str], ...] = (
    ("yaml", "PyYAML"),
    ("psutil", "psutil"),
    ("PIL", "Pillow"),
    ("send2trash", "send2trash"),
    ("customtkinter", "customtkinter"),
    ("imagehash", "imagehash"),
    ("numpy", "numpy"),
)


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _repo_root() -> Path:
    """Directory that contains ``requirements.txt`` when running from a git checkout."""
    return Path(__file__).resolve().parents[1]


def _requirements_path() -> Path | None:
    p = _repo_root() / "requirements.txt"
    return p if p.is_file() else None


def _missing_pip_names() -> List[str]:
    missing: List[str] = []
    for import_root, pip_name in _REQUIRED:
        if importlib.util.find_spec(import_root) is None:
            missing.append(pip_name)
    return missing


def _pip_install(pip_names: Sequence[str], requirements: Path | None) -> int:
    cmd: List[str] = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
    ]
    if requirements is not None:
        cmd += ["-r", str(requirements)]
    else:
        cmd += list(pip_names)
    print(
        "[CEREBRO] Installing dependencies:\n  "
        + " ".join(cmd)
        + "\n(This only runs when running from source, not the frozen .exe.)\n",
        file=sys.stderr,
    )
    # Inherit stdout/stderr so the user sees pip progress.
    return subprocess.call(cmd)


def _warn_optional_drag_drop() -> None:
    if importlib.util.find_spec("tkinterdnd2") is None:
        print(
            "[CEREBRO] Optional: install tkinterdnd2 for drag-and-drop folders "
            "(pip install tkinterdnd2).",
            file=sys.stderr,
        )


def ensure_runtime_dependencies() -> None:
    """Install missing PyPI packages when running from source, then restart the process.

    No-op when ``sys.frozen`` (PyInstaller) or when ``CEREBRO_SKIP_AUTO_DEPS`` is set.
    """
    if _is_frozen():
        return
    if os.environ.get("CEREBRO_SKIP_AUTO_DEPS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        missing = _missing_pip_names()
        if missing:
            print(
                "[CEREBRO] Missing packages but auto-install is disabled: "
                + ", ".join(missing)
                + "\nInstall with: pip install -r requirements.txt",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return

    missing = _missing_pip_names()
    if not missing:
        _warn_optional_drag_drop()
        return

    print(
        "[CEREBRO] Missing Python packages: "
        + ", ".join(missing)
        + "\nAttempting automatic install…",
        file=sys.stderr,
    )
    req = _requirements_path()
    if req is not None:
        code = _pip_install((), req)
    else:
        code = _pip_install(missing, None)

    if code != 0:
        print(
            "[CEREBRO] Automatic install failed (exit code %s). "
            "Install manually:\n  %s -m pip install -r requirements.txt"
            % (code, sys.executable),
            file=sys.stderr,
        )
        raise SystemExit(1)

    # New process so importlib metadata and sys.path pick up the new wheels.
    print("[CEREBRO] Dependencies installed — restarting…", file=sys.stderr)
    try:
        proc = subprocess.run([sys.executable, *sys.argv])
    except OSError as exc:
        print(
            "[CEREBRO] Could not restart automatically (%s). "
            "Please start CEREBRO again." % exc,
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise SystemExit(proc.returncode)
