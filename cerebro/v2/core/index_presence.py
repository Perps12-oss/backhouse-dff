"""Phase 1 — lightweight index / scan presence helpers for the dashboard.

Counts files whose modification time is newer than a prior scan timestamp,
using a bounded walk so opening Home stays responsive on huge trees.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Sequence

from cerebro.v2.core.scan_history_db import ScanHistoryEntry, get_scan_history_db


def latest_scan_entry() -> ScanHistoryEntry | None:
    rows = get_scan_history_db().get_recent(1)
    return rows[0] if rows else None


def format_relative_past(ts: float, *, now: float | None = None) -> str:
    """Short English label like "today", "yesterday", "3 days ago"."""
    ref = float(now if now is not None else time.time())
    delta = max(0.0, ref - float(ts))
    if delta < 60 * 60 * 12:
        return "today"
    if delta < 60 * 60 * 36:
        return "yesterday"
    days = int(delta // (60 * 60 * 24))
    if days <= 6:
        return "1 day ago" if days == 1 else f"{days} days ago"
    if days < 14:
        return "1 week ago"
    weeks = days // 7
    if weeks < 8:
        return "1 week ago" if weeks == 1 else f"{weeks} weeks ago"
    months = days // 30
    return "1 month ago" if months == 1 else f"{months} months ago"


def count_files_newer_than(
    roots: Sequence[str | Path],
    since_ts: float,
    *,
    budget_seconds: float = 2.0,
    max_files: int = 200_000,
) -> tuple[int, bool]:
    """Return ``(count, truncated)`` of files with ``mtime > since_ts``.

    ``truncated`` is True if the walk stopped early due to time budget or
    ``max_files``. Directories are skipped; unreadable trees are skipped.
    """
    deadline = time.monotonic() + float(budget_seconds)
    count = 0
    truncated = False
    since = float(since_ts)

    for raw in roots:
        if time.monotonic() >= deadline:
            truncated = True
            break
        root = Path(raw)
        try:
            if not root.exists():
                continue
        except OSError:
            continue

        stack: list[Path] = [root]
        while stack:
            if time.monotonic() >= deadline:
                truncated = True
                break
            if count >= max_files:
                truncated = True
                break
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for ent in it:
                        if time.monotonic() >= deadline:
                            truncated = True
                            break
                        if count >= max_files:
                            truncated = True
                            break
                        try:
                            if ent.is_dir(follow_symlinks=False):
                                stack.append(Path(ent.path))
                                continue
                            if not ent.is_file(follow_symlinks=False):
                                continue
                            st = ent.stat(follow_symlinks=False)
                            if float(st.st_mtime) > since:
                                count += 1
                        except OSError:
                            continue
            except OSError:
                continue
        if truncated:
            break

    return count, truncated
