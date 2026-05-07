#!/usr/bin/env bash
# CEREBRO launcher for Linux / macOS.
# Windows users: use Run CEREBRO.bat instead.
set -euo pipefail
cd "$(dirname "$0")"

# Prefer python3; fall back to python.
PYTHON="${PYTHON:-$(command -v python3 2>/dev/null || command -v python)}"

if [ -z "$PYTHON" ]; then
    echo "[CEREBRO] Python not found. Install Python 3.10+ and retry." >&2
    exit 1
fi

exec "$PYTHON" main.py "$@"
