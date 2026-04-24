"""CEREBRO command-line interface.

Usage:
    cerebro                        # launch GUI (default)
    cerebro gui                    # launch GUI explicitly
    cerebro scan <folder> ...      # scan folders, print results
    cerebro scan <folder> --delete # scan and delete duplicates (keep one)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None or args.command == "gui":
        return _cmd_gui()

    if args.command == "scan":
        return _cmd_scan(args)

    parser.print_help()
    return 1


# ---------------------------------------------------------------------------
# GUI subcommand
# ---------------------------------------------------------------------------

def _cmd_gui() -> int:
    from cerebro.runtime_deps import ensure_runtime_dependencies
    ensure_runtime_dependencies()
    from cerebro.v2.ui.flet_app.main import run_flet_app
    run_flet_app()
    return 0


# ---------------------------------------------------------------------------
# Scan subcommand
# ---------------------------------------------------------------------------

def _cmd_scan(args: argparse.Namespace) -> int:
    import time
    from cerebro.engines.orchestrator import ScanOrchestrator
    from cerebro.engines.base_engine import ScanState

    folders = [Path(f).expanduser().resolve() for f in args.folders]
    missing = [f for f in folders if not f.exists()]
    if missing:
        for m in missing:
            print(f"error: folder not found: {m}", file=sys.stderr)
        return 1

    orchestrator = ScanOrchestrator()
    try:
        orchestrator.set_mode(args.mode)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    opts: dict = {}
    if args.min_size:
        opts["min_size_bytes"] = args.min_size

    done_event = __import__("threading").Event()

    def _on_progress(p) -> None:
        if p.state in (ScanState.COMPLETED, ScanState.ERROR, ScanState.CANCELLED):
            done_event.set()
        elif p.state == ScanState.SCANNING and not args.quiet:
            pct = (
                f"{p.files_scanned}/{p.files_total}"
                if p.files_total
                else f"{p.files_scanned} files"
            )
            print(f"\r  scanning… {pct}", end="", flush=True)

    orchestrator.start_scan(
        folders=folders,
        protected=[],
        options=opts,
        progress_callback=_on_progress,
    )

    t0 = time.monotonic()
    while not done_event.wait(timeout=0.25):
        if time.monotonic() - t0 > 3600:
            print("\nerror: scan timeout", file=sys.stderr)
            return 1

    if not args.quiet:
        print()  # newline after progress

    groups = orchestrator.get_results()
    if not groups:
        print("No duplicates found.")
        return 0

    # Apply min-size filter at group level
    if args.min_size:
        groups = [g for g in groups if g.reclaimable >= args.min_size]

    if args.output == "json":
        _output_json(groups)
    elif args.output == "csv":
        _output_csv(groups)
    else:
        _output_table(groups)

    total_bytes = sum(g.reclaimable for g in groups)
    _fmt = _fmt_size(total_bytes)
    print(f"\n{len(groups)} duplicate groups · {_fmt} reclaimable")

    if args.delete:
        return _delete_duplicates(groups, args)

    return 0


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _output_table(groups) -> None:
    for g in groups:
        keeper = max(g.files, key=lambda f: int(getattr(f, "size", 0) or 0))
        print(f"\nGroup #{g.group_id}  ({len(g.files)} files, "
              f"{_fmt_size(int(g.reclaimable))} reclaimable)")
        for f in g.files:
            tag = " [keep]" if f is keeper else ""
            print(f"  {f.path}{tag}")


def _output_json(groups) -> None:
    data = [
        {
            "group_id": g.group_id,
            "reclaimable": g.reclaimable,
            "files": [
                {"path": str(f.path), "size": f.size, "modified": f.modified}
                for f in g.files
            ],
        }
        for g in groups
    ]
    print(json.dumps(data, indent=2))


def _output_csv(groups) -> None:
    import csv
    writer = csv.writer(sys.stdout)
    writer.writerow(["group_id", "path", "size", "modified"])
    for g in groups:
        for f in g.files:
            writer.writerow([g.group_id, str(f.path), f.size, f.modified])


# ---------------------------------------------------------------------------
# Delete path
# ---------------------------------------------------------------------------

def _delete_duplicates(groups, args: argparse.Namespace) -> int:
    keep_rule = args.keep
    deleted = 0
    freed = 0

    for g in groups:
        files = list(g.files)
        if len(files) < 2:
            continue

        if keep_rule == "oldest":
            keeper = min(files, key=lambda f: getattr(f, "modified", 0) or 0)
        elif keep_rule == "newest":
            keeper = max(files, key=lambda f: getattr(f, "modified", 0) or 0)
        elif keep_rule == "smallest":
            keeper = min(files, key=lambda f: int(getattr(f, "size", 0) or 0))
        else:  # largest (default)
            keeper = max(files, key=lambda f: int(getattr(f, "size", 0) or 0))

        for f in files:
            if f is keeper:
                continue
            p = Path(f.path)
            size = int(getattr(f, "size", 0) or 0)
            if args.dry_run:
                if not args.quiet:
                    print(f"  [dry-run] would delete: {p}")
                deleted += 1
                freed += size
                continue
            try:
                import send2trash
                send2trash.send2trash(str(p))
            except ImportError:
                p.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  warning: could not delete {p}: {exc}", file=sys.stderr)
                continue
            deleted += 1
            freed += size
            if not args.quiet:
                print(f"  deleted: {p}")

    verb = "would delete" if args.dry_run else "deleted"
    print(f"\n{verb} {deleted} files, freed {_fmt_size(freed)}")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cerebro",
        description="CEREBRO — fast duplicate file finder",
    )
    sub = parser.add_subparsers(dest="command")

    # gui
    sub.add_parser("gui", help="Launch the GUI (default when no command given)")

    # scan
    sp = sub.add_parser("scan", help="Scan folders for duplicates")
    sp.add_argument("folders", nargs="+", metavar="FOLDER",
                    help="Folders to scan")
    sp.add_argument("--mode", default="files",
                    choices=["files", "photos", "music", "videos",
                             "empty_folders", "large_files", "burst"],
                    help="Scan engine (default: files)")
    sp.add_argument("--output", default="table",
                    choices=["table", "json", "csv"],
                    help="Output format (default: table)")
    sp.add_argument("--min-size", type=int, default=0, metavar="BYTES",
                    help="Ignore files smaller than this (bytes)")
    sp.add_argument("--delete", action="store_true",
                    help="Delete duplicates after scanning (keeps one copy)")
    sp.add_argument("--keep",
                    choices=["largest", "smallest", "oldest", "newest"],
                    default="largest",
                    help="Which copy to keep when --delete is used (default: largest)")
    sp.add_argument("--dry-run", action="store_true",
                    help="Preview deletions without changing any files")
    sp.add_argument("--quiet", action="store_true",
                    help="Suppress progress output")

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
