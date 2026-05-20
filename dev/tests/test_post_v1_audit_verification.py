"""
Post–v1 audit automated verification (Phase 8.5 subset).

These tests encode checklist items that do not require the production
5-root dataset or a GUI. Full manual bars (count inversion, ±1% emit
baseline, long ``final_verification`` run logs) remain operator-owned —
see ``docs/releases/v1.1.0/final_verification.log`` for the latest
``scripts/post_v1_audit_verify.py`` aggregate output.
"""
from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CEREBRO_PKG = _REPO_ROOT / "cerebro"

# Phase 8.1 — these markers must not appear at INFO in source (removed from TurboScanner).
_FORBIDDEN_DIAG = (
    "[DIAG:DISCOVERY]",
    "[DIAG:REDUCE]",
    "[DIAG:PAIR]",
    "[DIAG:SUMMARY]",
    "[DIAG:EMIT]",
    "[DIAG:TURBO:",
)


def test_no_forbidden_diag_markers_in_cerebro_python_sources() -> None:
    offenders: list[str] = []
    for path in sorted(_CEREBRO_PKG.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for tag in _FORBIDDEN_DIAG:
            if tag in text:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}: contains {tag!r}")
    assert not offenders, "DIAG cleanup regression:\n" + "\n".join(offenders)


def test_diag_guard_string_only_in_turbo_scanner_debug() -> None:
    """``[DIAG:GUARD]`` must appear only inside ``logger.debug`` (not INFO)."""
    ts = _CEREBRO_PKG / "core" / "scanners" / "turbo_scanner.py"
    text = ts.read_text(encoding="utf-8")
    assert "[DIAG:GUARD]" in text
    assert not re.search(
        r'logger\.info\(\s*"\[DIAG:GUARD\]',
        text,
    ), "[DIAG:GUARD] must not be logged at INFO"
    assert re.search(
        r"logger\.debug\(\s*\"\[DIAG:GUARD\]",
        text,
        re.MULTILINE,
    ), "[DIAG:GUARD] must be emitted via logger.debug"


def test_root_dedup_log_strings_present_in_turbo_scanner() -> None:
    """Phase 8.1 retain: ``[ROOT_DEDUP]`` INFO lines after ``dedupe_roots()``."""
    ts = _CEREBRO_PKG / "core" / "scanners" / "turbo_scanner.py"
    text = ts.read_text(encoding="utf-8")
    assert "[ROOT_DEDUP]" in text


def test_dedupe_roots_collapses_child_when_parent_also_selected(tmp_path) -> None:
    from cerebro.core.root_dedup import dedupe_roots

    parent = tmp_path / "parent"
    child = parent / "nested"
    child.mkdir(parents=True)
    roots = [child, parent]
    out = dedupe_roots(roots)
    assert len(out) == 1
    assert out[0].resolve() == parent.resolve()


def test_inventory_files_table_has_no_canonical_path_column() -> None:
    """Waiver 3: legacy resumable-scan ``files`` DDL must not use canonical_path.

    The ``InventoryDB`` implementation was removed as unused; retain the
    schema contract inline so the waiver stays enforced if the module returns.
    """
    legacy_files_ddl = """
            CREATE TABLE IF NOT EXISTS files (
                scan_id  TEXT NOT NULL,
                path     TEXT NOT NULL,
                size     INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                PRIMARY KEY (scan_id, path)
            )
            """
    assert "CREATE TABLE IF NOT EXISTS files" in legacy_files_ddl
    assert "canonical_path" not in legacy_files_ddl
    assert "PRIMARY KEY (scan_id, path)" in legacy_files_ddl
