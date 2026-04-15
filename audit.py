#!/usr/bin/env python3
"""
audit.py — Mechanical verification of the senior-engineer critique.

Run from the repo root:
    python tools/audit.py

Exit code:
    0  — all criteria pass
    1  — at least one criterion fails

This script intentionally has zero dependencies beyond the stdlib so it can
run in CI without `pip install` overhead. It checks ten things:

    1. No duplicated scanner directories
    2. No engine/ vs engines/ split
    3. No duplicated _format_bytes definitions
    4. Bare-except count under threshold
    5. print() count in production code under threshold
    6. Private CTk API access count under threshold
    7. logger import in every UI module
    8. Test files exist for the orchestrator and turbo engine
    9. CI config present
   10. ruff / mypy config present

For each FAIL, the script prints the offending file:line so you can act on it.
This is the artifact you point Cursor / yourself at and say
"do not declare this fixed until ./tools/audit.py exits 0".
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, List, Tuple

# Force UTF-8 stdout on Windows so the script never crashes on its own output.
# Without this, a stray non-ASCII character produces UnicodeEncodeError under
# the default cp1252 codepage in PowerShell / cmd.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, OSError):
    # Older Pythons or non-tty streams: best-effort, ignore.
    pass

# Locate the repo root. Works whether this script lives at:
#   <repo>/audit.py             (parents[0] is repo)
#   <repo>/tools/audit.py       (parents[1] is repo)
#   <repo>/scripts/audit.py     (parents[1] is repo)
# We pick the closest ancestor that contains a 'cerebro/' directory.
def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "cerebro").is_dir():
            return candidate
    # Fallback to old behaviour
    return here.parents[1] if len(here.parents) > 1 else here.parent


REPO_ROOT = _find_repo_root()
SRC = REPO_ROOT / "cerebro"

# Files we never lint/count: vendored, generated, tests
EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules", "tests", "sanity"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def py_files(root: Path) -> List[Path]:
    out = []
    for p in root.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def ui_files(root: Path) -> List[Path]:
    return [p for p in py_files(root) if "v2/ui" in p.as_posix()]


class Result:
    """Container for one audit step's outcome."""

    def __init__(self, name: str, criterion: str):
        self.name = name
        self.criterion = criterion
        self.passed = True
        self.detail: List[str] = []

    def fail(self, msg: str) -> None:
        self.passed = False
        self.detail.append(msg)

    def __str__(self) -> str:
        marker = "PASS" if self.passed else "FAIL"
        head = f"[{marker}] {self.name}: {self.criterion}"
        if self.passed:
            return head
        return head + "\n        " + "\n        ".join(self.detail[:10]) + (
            f"\n        ... and {len(self.detail) - 10} more"
            if len(self.detail) > 10 else ""
        )


# ---------------------------------------------------------------------------
# Audit checks
# ---------------------------------------------------------------------------

def check_duplicate_scanners() -> Result:
    r = Result("01-no-duplicate-scanners",
               "scanner code lives in exactly one location")
    locations = []
    for cand in ("cerebro/scanners", "cerebro/core/scanners",
                 "cerebro/experimental/scanners"):
        p = REPO_ROOT / cand
        if p.is_dir() and any(p.glob("*.py")):
            locations.append(cand)
    if len(locations) > 1:
        r.fail(f"scanner code in {len(locations)} dirs: {', '.join(locations)}")
    return r


def check_engine_singular_vs_plural() -> Result:
    r = Result("02-no-engine-engines-split",
               "only one of cerebro/engine/ or cerebro/engines/ exists")
    has_singular = (REPO_ROOT / "cerebro/engine").is_dir()
    has_plural   = (REPO_ROOT / "cerebro/engines").is_dir()
    if has_singular and has_plural:
        r.fail("both cerebro/engine/ and cerebro/engines/ exist; pick one")
    return r


def check_duplicate_format_bytes() -> Result:
    r = Result("03-no-duplicated-helpers",
               "_format_bytes / format_bytes defined in exactly one module")
    pattern = re.compile(r"^\s*def\s+_?format_bytes\s*\(", re.M)
    hits: List[str] = []
    for f in py_files(SRC):
        text = f.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            hits.append(f.relative_to(REPO_ROOT).as_posix())
    if len(hits) > 1:
        r.fail(f"_format_bytes defined in {len(hits)} files:")
        for h in hits:
            r.fail(f"    {h}")
    return r


def check_bare_excepts() -> Result:
    r = Result("04-exception-handling",
               "<=30 bare/blanket excepts repo-wide (target: 0)")
    THRESHOLD = 30
    offenders: List[str] = []
    for f in py_files(SRC):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            t = node.type
            # Bare `except:` or `except Exception:` only
            if t is None or (isinstance(t, ast.Name) and t.id == "Exception"):
                offenders.append(
                    f"{f.relative_to(REPO_ROOT).as_posix()}:{node.lineno}"
                )
    if len(offenders) > THRESHOLD:
        r.fail(f"{len(offenders)} bare/blanket excepts (threshold {THRESHOLD})")
        for o in offenders[:10]:
            r.fail(f"    {o}")
    return r


def check_print_in_production() -> Result:
    r = Result("05-no-print-statements",
               "0 print() calls in cerebro/ (use logger)")
    pat = re.compile(r"^\s*print\s*\(", re.M)
    offenders: List[str] = []
    for f in py_files(SRC):
        text = f.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if pat.match(line):
                offenders.append(
                    f"{f.relative_to(REPO_ROOT).as_posix()}:{i}"
                )
    if offenders:
        r.fail(f"{len(offenders)} print() calls found:")
        for o in offenders[:10]:
            r.fail(f"    {o}")
    return r


def check_private_ctk_api() -> Result:
    r = Result("06-no-private-ctk",
               "no access to CustomTkinter private API (_apply_appearance_mode etc)")
    # These are private members of CustomTkinter widgets specifically.
    # _sync_partner used to be in this list but is actually CEREBRO's own
    # attribute on ZoomCanvas, not a CTk internal — removed to fix false
    # positives.
    BAD = (
        "_apply_appearance_mode",
        "._fg_color",
        "._text_color",
        "._bg_color",
        "._border_color",
        "._hover_color",
    )
    offenders: List[str] = []
    for f in ui_files(SRC):
        text = f.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            for token in BAD:
                if token in line:
                    offenders.append(
                        f"{f.relative_to(REPO_ROOT).as_posix()}:{i}: {token}"
                    )
                    break
    if offenders:
        r.fail(f"{len(offenders)} private-CTk accesses:")
        for o in offenders[:10]:
            r.fail(f"    {o}")
    return r


def check_logger_in_ui_modules() -> Result:
    r = Result("07-logger-everywhere",
               "every cerebro/v2/ui/*.py imports logging and creates a logger")
    offenders: List[str] = []
    for f in ui_files(SRC):
        text = f.read_text(encoding="utf-8", errors="replace")
        # Skip __init__.py and pure-data files
        if f.name == "__init__.py" or len(text) < 200:
            continue
        if "import logging" not in text:
            offenders.append(
                f"{f.relative_to(REPO_ROOT).as_posix()}: missing 'import logging'"
            )
            continue
        if "getLogger(" not in text:
            offenders.append(
                f"{f.relative_to(REPO_ROOT).as_posix()}: missing logger = logging.getLogger(__name__)"
            )
    if offenders:
        r.fail(f"{len(offenders)} UI modules without logger:")
        for o in offenders[:10]:
            r.fail(f"    {o}")
    return r


def check_critical_tests_exist() -> Result:
    r = Result("08-critical-tests",
               "test files cover orchestrator and turbo engine")
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.is_dir():
        r.fail("tests/ directory does not exist")
        return r
    test_files = list(tests_dir.rglob("test_*.py"))
    if not test_files:
        r.fail("no test_*.py files in tests/")
        return r
    # Look inside test files for imports of the things we care about
    needs = {
        "orchestrator": "cerebro.engines.orchestrator",
        "turbo engine": "cerebro.engines.turbo_file_engine",
    }
    found = {k: False for k in needs}
    for tf in test_files:
        text = tf.read_text(encoding="utf-8", errors="replace")
        for label, importpath in needs.items():
            if importpath in text:
                found[label] = True
    missing = [k for k, v in found.items() if not v]
    if missing:
        r.fail(f"no test imports cover: {', '.join(missing)}")
        r.fail(f"  (looked in {len(test_files)} test files under tests/)")
    return r


def check_ci_present() -> Result:
    r = Result("09-ci-present",
               ".github/workflows/ has at least one workflow file")
    wf_dir = REPO_ROOT / ".github" / "workflows"
    if not wf_dir.is_dir():
        r.fail(".github/workflows/ does not exist")
    elif not any(wf_dir.glob("*.yml")) and not any(wf_dir.glob("*.yaml")):
        r.fail(".github/workflows/ exists but contains no .yml file")
    return r


def check_lint_config() -> Result:
    r = Result("10-linter-config",
               "ruff and mypy configured (pyproject.toml or .ruff.toml)")
    cfgs = [
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / ".ruff.toml",
        REPO_ROOT / "ruff.toml",
    ]
    has_ruff = False
    has_mypy = False
    for c in cfgs:
        if not c.exists():
            continue
        text = c.read_text(encoding="utf-8", errors="replace").lower()
        if "ruff" in text or "[tool.ruff" in text:
            has_ruff = True
        if "mypy" in text or "[tool.mypy" in text:
            has_mypy = True
    if not has_ruff:
        r.fail("no ruff config in pyproject.toml / .ruff.toml")
    if not has_mypy:
        r.fail("no mypy config in pyproject.toml")
    return r


# ---------------------------------------------------------------------------
# Live behavioural smoke tests — these import the code and run it
# ---------------------------------------------------------------------------

def smoke_orchestrator_files_mode() -> Result:
    """The bug Cursor introduced and missed twice. Catches it forever."""
    r = Result("11-smoke-files-mode",
               "ScanOrchestrator can open the 'files' mode without crashing")
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from cerebro.engines.orchestrator import ScanOrchestrator
        o = ScanOrchestrator()
        opts = o.set_mode("files")
        if not isinstance(opts, list):
            r.fail(f"set_mode returned {type(opts).__name__}, not list")
    except Exception as e:
        r.fail(f"set_mode('files') raised {type(e).__name__}: {e}")
    return r


def smoke_turbo_engine_finds_duplicates() -> Result:
    """End-to-end: the actual claim of the product."""
    r = Result("12-smoke-end-to-end-scan",
               "TurboFileEngine finds a duplicate in a 3-file test folder")
    import tempfile, time
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from cerebro.engines.orchestrator import ScanOrchestrator
        from cerebro.engines.base_engine import ScanState

        td = Path(tempfile.mkdtemp(prefix="cerebro_audit_"))
        (td / "a.txt").write_bytes(b"identical content " * 100)
        (td / "b.txt").write_bytes(b"identical content " * 100)
        (td / "c.txt").write_bytes(b"different content here")

        o = ScanOrchestrator()
        o.set_mode("files")
        o.start_scan(
            folders=[td],
            protected=[],
            options={"min_size_bytes": 0, "hash_algorithm": "sha256"},
            progress_callback=lambda p: None,
        )

        # Wait up to 10s
        engine = o._engines["files"]
        for _ in range(100):
            time.sleep(0.1)
            try:
                if engine.state in (ScanState.COMPLETED, ScanState.ERROR,
                                    ScanState.CANCELLED):
                    break
            except AttributeError:
                # The "missing _state" bug Cursor introduced
                r.fail("engine.state raised AttributeError -- _state not initialised")
                return r

        if engine.state != ScanState.COMPLETED:
            r.fail(f"scan did not complete; final state = {engine.state}")
            return r

        groups = o.get_results()
        if len(groups) != 1:
            r.fail(f"expected 1 duplicate group, got {len(groups)}")
            return r
        if len(groups[0].files) != 2:
            r.fail(f"group has {len(groups[0].files)} files, expected 2")
    except Exception as e:
        r.fail(f"end-to-end scan raised {type(e).__name__}: {e}")
    return r


# ---------------------------------------------------------------------------
# External tool checks — run ruff/mypy if installed; warn (not fail) otherwise
# ---------------------------------------------------------------------------

def run_external(cmd: List[str]) -> Tuple[bool, str]:
    try:
        out = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
        )
        return out.returncode == 0, (out.stdout + out.stderr)[:2000]
    except FileNotFoundError:
        return False, f"{cmd[0]} not installed"


def check_ruff_clean() -> Result:
    r = Result("13-ruff-clean",
               "ruff check cerebro/ exits 0")
    ok, log = run_external(["ruff", "check", "cerebro/"])
    if not ok:
        r.fail(log.strip().split("\n")[-1] if log else "ruff failed")
    return r


def check_mypy_clean() -> Result:
    r = Result("14-mypy-clean",
               "mypy cerebro/ exits 0 (or has acceptable error budget)")
    ok, log = run_external(["mypy", "cerebro/"])
    if not ok:
        # Allow a few errors during transition; tighten as you go
        BUDGET = 50
        match = re.search(r"Found (\d+) error", log)
        if match and int(match.group(1)) <= BUDGET:
            return r  # within budget -- pass
        r.fail(log.strip().split("\n")[-1] if log else "mypy failed")
    return r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CHECKS = [
    check_duplicate_scanners,
    check_engine_singular_vs_plural,
    check_duplicate_format_bytes,
    check_bare_excepts,
    check_print_in_production,
    check_private_ctk_api,
    check_logger_in_ui_modules,
    check_critical_tests_exist,
    check_ci_present,
    check_lint_config,
    smoke_orchestrator_files_mode,
    smoke_turbo_engine_finds_duplicates,
    check_ruff_clean,
    check_mypy_clean,
]


def main() -> int:
    print("=" * 70)
    print("CEREBRO repo audit")
    print("=" * 70)
    results: List[Result] = []
    for fn in CHECKS:
        results.append(fn())
        print(results[-1])
        print()

    fails = [r for r in results if not r.passed]
    print("=" * 70)
    print(f"Result: {len(results) - len(fails)}/{len(results)} checks passed")
    print("=" * 70)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
