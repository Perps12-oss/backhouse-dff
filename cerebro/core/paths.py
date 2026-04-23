"""
Canonical CEREBRO per-user layout (cache, logs, config).

Single place for paths referenced by engines and services so the hash cache
and TurboScanner use the same directory.
"""

from __future__ import annotations

from pathlib import Path


def cerebro_user_root() -> Path:
    return Path.home() / ".cerebro"


def default_cerebro_cache_dir() -> Path:
    p = cerebro_user_root() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p
