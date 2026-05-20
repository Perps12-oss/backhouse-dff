#!/usr/bin/env python3
"""Lightweight secret pattern scan for CI (not a full gitleaks replacement)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".git", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}

PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS key prefix
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def main() -> int:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".ico", ".db", ".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in PATTERNS:
            if pat.search(text):
                hits.append(f"{path}: matched {pat.pattern}")
    if hits:
        print("Potential secrets found:")
        for h in hits[:20]:
            print(h)
        return 1
    print("No obvious secret patterns found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
