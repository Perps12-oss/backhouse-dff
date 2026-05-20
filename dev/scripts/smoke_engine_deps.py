"""Headless smoke-test for Phase-7 Engine Status Diagnostics Overhaul.

Exercises:

* :mod:`cerebro.v2.core.engine_deps` — probe every registered engine and
  verify each probe produces a structured ``ProbeResult`` whose state
  matches what we know about the current repo (Files/Images/Videos/
  Music/EmptyFolders/LargeFiles should be AVAILABLE or DEGRADED
  depending on local env; Audio/Documents must be NOT_IMPLEMENTED
  because there are no module files for them in-tree).
* :mod:`cerebro.v2.core.engine_errors_db` — insert a row, read it back,
  and count it, using a temp DB path.
* :class:`DiagnosticsPage` — instantiate, force a synchronous probe
  render, verify the engine-section card contains one row per registry
  entry.
* :class:`ScanPage` — instantiate against a stub orchestrator and
  verify the warning banner stays hidden for AVAILABLE modes and
  appears (pack_forget-able) when we force a probe that isn't
  AVAILABLE.

Run from repo root:

    $env:PYTHONPATH="."
    python scripts/smoke_engine_deps.py
"""
from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from pathlib import Path


# ---------------------------------------------------------------------------
# 1) engine_deps.probe_all()
# ---------------------------------------------------------------------------

def _check_probes() -> None:
    from cerebro.v2.core.engine_deps import (
        ENGINE_DEPS, EngineState, probe_all, probe_mode,
    )

    probes = probe_all()
    assert len(probes) == len(ENGINE_DEPS), (
        f"probe_all() returned {len(probes)} results, expected "
        f"{len(ENGINE_DEPS)}"
    )
    by_key = {p.key: p for p in probes}

    # Audio + Documents have no module files in-tree — must be NOT_IMPLEMENTED.
    for planned_key in ("audio", "documents"):
        assert planned_key in by_key, f"missing probe for {planned_key}"
        assert by_key[planned_key].state is EngineState.NOT_IMPLEMENTED, (
            f"{planned_key}: expected NOT_IMPLEMENTED, got "
            f"{by_key[planned_key].state!r}"
        )
        assert not by_key[planned_key].ok

    # Files / Empty folders / Large files have zero external deps and
    # always-available in-tree modules — they must be AVAILABLE.
    for always_key in ("files", "empty_folders", "large_files"):
        p = by_key[always_key]
        assert p.state is EngineState.AVAILABLE, (
            f"{always_key}: expected AVAILABLE, got {p.state!r} "
            f"(detail={p.detail!r})"
        )

    # probe_mode for an unknown key returns None.
    assert probe_mode("does_not_exist") is None

    # Every non-AVAILABLE probe is either actionable (MISSING_DEPS /
    # DEGRADED / RUNTIME_ERROR) or NOT_IMPLEMENTED. Never a silent fail.
    for p in probes:
        if p.state is EngineState.AVAILABLE:
            continue
        assert p.state in (
            EngineState.NOT_IMPLEMENTED,
            EngineState.MISSING_DEPS,
            EngineState.DEGRADED,
            EngineState.RUNTIME_ERROR,
        )

    print(f"[OK] engine_deps.probe_all(): {len(probes)} probes")
    for p in probes:
        print(f"      {p.key:14s}  {p.state.value:16s}  {p.detail}")


# ---------------------------------------------------------------------------
# 2) engine_errors_db
# ---------------------------------------------------------------------------

def _check_errors_db() -> None:
    from cerebro.v2.core.engine_errors_db import EngineErrorsDB

    with tempfile.TemporaryDirectory() as tmp:
        db = EngineErrorsDB(Path(tmp) / "errors.db")
        try:
            assert db.count() == 0
            db.record_error(
                engine_key="audio",
                state="not_implemented",
                detail="not yet implemented",
                module_path="cerebro.engines.audio_dedup_engine",
                exception_class="ModuleNotFoundError",
                exception_message="No module named 'cerebro.engines.audio_dedup_engine'",
            )
            assert db.count() == 1
            last = db.get_last_error_for("audio")
            assert last is not None
            assert last.engine_key == "audio"
            assert last.state == "not_implemented"
            assert last.module_path == "cerebro.engines.audio_dedup_engine"
            recent = db.get_recent_errors(limit=10)
            assert len(recent) == 1
            db.clear()
            assert db.count() == 0
        finally:
            db.close()
    print("[OK] engine_errors_db: insert / read / clear")


# ---------------------------------------------------------------------------
# 3) DiagnosticsPage instantiation + engine section render
# ---------------------------------------------------------------------------

def _check_diagnostics_page() -> None:
    from cerebro.v2.core.engine_deps import ENGINE_DEPS
    from cerebro.v2.ui.diagnostics_page import DiagnosticsPage

    root = tk.Tk()
    root.geometry("1000x600")
    try:
        page = DiagnosticsPage(root)
        page.pack(fill="both", expand=True)
        root.update()
        # Force a synchronous collect + render (bypass background thread).
        page._render(
            page._collect_app_info(),
            page._collect_engine_status(),
            page._collect_db_info(),
        )
        root.update()
        engine_children = page._engine_container.winfo_children()
        assert len(engine_children) == len(ENGINE_DEPS), (
            f"DiagnosticsPage engine card has {len(engine_children)} rows, "
            f"expected {len(ENGINE_DEPS)}"
        )
        print(f"[OK] DiagnosticsPage: {len(engine_children)} engine rows rendered")
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# 4) ScanPage banner behaviour
# ---------------------------------------------------------------------------

class _StubOrchestrator:
    def __init__(self) -> None:
        self.mode = "files"

    def set_mode(self, key: str) -> None:
        self.mode = key

    def start_scan(self, **kwargs) -> None:  # noqa: D401, ARG002
        raise RuntimeError("smoke test should not start a real scan")

    def cancel(self) -> None:
        pass

    def get_results(self) -> list:
        return []


def _check_scan_page_banner() -> None:
    from cerebro.v2.core.engine_deps import EngineState, ProbeResult
    from cerebro.v2.ui.scan_page import ScanPage

    root = tk.Tk()
    root.geometry("1200x700")
    try:
        page = ScanPage(root, orchestrator=_StubOrchestrator())
        page.pack(fill="both", expand=True)
        root.update()

        # "files" mode must be AVAILABLE — banner must be unmanaged (not packed).
        assert not page._engine_banner.winfo_manager(), (
            "banner should be hidden for AVAILABLE default mode"
        )

        # Force a non-AVAILABLE probe and re-run the banner code path.
        import cerebro.v2.ui.scan_page as sp

        original_probe = sp.probe_mode
        sp.probe_mode = lambda _k: ProbeResult(
            key="files",
            state=EngineState.MISSING_DEPS,
            detail="missing dependency: pretend",
            pip_hint="pip install pretend",
            module_path="cerebro.engines.turbo_file_engine",
            exception_class="ModuleNotFoundError",
            exception_message="No module named 'pretend'",
        )
        try:
            page._refresh_engine_banner("files")
            root.update()
            assert page._engine_banner.winfo_manager(), (
                "banner should be visible for MISSING_DEPS probe"
            )
        finally:
            sp.probe_mode = original_probe

        # Flip back to AVAILABLE and ensure it hides again.
        page._refresh_engine_banner("files")
        root.update()
        assert not page._engine_banner.winfo_manager(), (
            "banner should hide again once probe returns AVAILABLE"
        )

        print("[OK] ScanPage: banner hide/show round-trip")
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    _check_probes()
    _check_errors_db()
    _check_diagnostics_page()
    _check_scan_page_banner()
    print("\nAll Phase-7 smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
