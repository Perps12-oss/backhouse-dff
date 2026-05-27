"""CEREBRO command-line interface.

Usage:
    cerebro                              # launch GUI (default)
    cerebro gui                          # launch GUI explicitly
    cerebro scan <folder> ...            # scan folders, print results
    cerebro scan <folder> --delete       # scan and delete duplicates via pipeline (trash, safe)
    cerebro scan <folder> --delete --permanent  # permanent delete (requires explicit confirmation)
    cerebro restore-trash                # restore files from fallback-trash manifest
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

    if args.command == "restore-trash":
        return _cmd_restore_trash(args)

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
    try:
        while not done_event.wait(timeout=0.25):
            if time.monotonic() - t0 > 3600:
                print("\nerror: scan timeout", file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        orchestrator.cancel()
        print("\nScan cancelled.", file=sys.stderr)
        return 130

    if not args.quiet:
        print()

    groups = orchestrator.get_results()
    if not groups:
        print("No duplicates found.")
        return 0

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
# Delete path (C-2) — routes through CerebroPipeline
# ---------------------------------------------------------------------------

def _pick_keeper(files: list, keep_rule: str):
    if keep_rule == "oldest":
        return min(files, key=lambda f: getattr(f, "modified", 0) or 0)
    if keep_rule == "newest":
        return max(files, key=lambda f: getattr(f, "modified", 0) or 0)
    if keep_rule == "smallest":
        return min(files, key=lambda f: int(getattr(f, "size", 0) or 0))
    return max(files, key=lambda f: int(getattr(f, "size", 0) or 0))  # largest


def _delete_duplicates(groups, args: argparse.Namespace) -> int:
    from cerebro.core.pipeline import CerebroPipeline
    from cerebro.core.safety.deletion_gate import DeletionGateError

    keep_rule = args.keep
    permanent = getattr(args, "permanent", False)

    if args.dry_run:
        return _dry_run_report(groups, keep_rule)

    # Build group dicts for the pipeline.
    group_dicts = []
    for g in groups:
        files = list(g.files)
        if len(files) < 2:
            continue
        keeper = _pick_keeper(files, keep_rule)
        delete_files = [str(f.path) for f in files if f is not keeper]
        if not delete_files:
            continue
        group_dicts.append({
            "group_index": int(getattr(g, "group_id", 0)),
            "keep": str(keeper.path),
            "delete": delete_files,
        })

    if not group_dicts:
        print("Nothing to delete (all groups have only one file).")
        return 0

    mode = "permanent" if permanent else "trash"

    if permanent:
        print(
            "\nWARNING: --permanent will irreversibly delete files with no undo.\n"
            "Type YES to confirm: ",
            end="",
            flush=True,
        )
        try:
            answer = input().strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "YES":
            print("Cancelled.", file=sys.stderr)
            return 1

    pipeline = CerebroPipeline()

    deletion_plan = {
        "scan_id": "cli_delete",
        "policy": {"mode": mode},
        "groups": group_dicts,
        "source": "cli",
    }

    try:
        plan = pipeline.build_delete_plan(deletion_plan)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if permanent:
        # Issue token from this pipeline instance (Decision A).
        token = pipeline.gate.issue_token(reason="cli --permanent")
        plan = plan.__class__(
            scan_id=plan.scan_id,
            mode=plan.mode,
            operations=plan.operations,
            stats=plan.stats,
            policy={**dict(plan.policy or {}), "token": token},
            source=plan.source,
        )

    total_files = plan.total_files
    deleted_count = [0]
    freed_bytes = [0]

    def _progress(current: int, total: int, name: str) -> bool:
        if not args.quiet:
            print(f"\r  deleting… {current}/{total}", end="", flush=True)
        return True

    try:
        result = pipeline.execute_delete_plan(plan, progress_cb=_progress)
    except DeletionGateError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print()

    deleted_count[0] = len(result.deleted)
    freed_bytes[0] = result.bytes_reclaimed

    for p, err in result.failed:
        print(f"  warning: could not delete {p}: {err}", file=sys.stderr)

    if not args.quiet:
        for p in result.deleted:
            print(f"  deleted: {p}")

    verb = "deleted" if not permanent else "permanently deleted"
    print(f"\n{verb} {deleted_count[0]} files, freed {_fmt_size(freed_bytes[0])}")
    return 0


def _dry_run_report(groups, keep_rule: str) -> int:
    deleted = 0
    freed = 0
    for g in groups:
        files = list(g.files)
        if len(files) < 2:
            continue
        keeper = _pick_keeper(files, keep_rule)
        for f in files:
            if f is keeper:
                continue
            print(f"  [dry-run] would delete: {f.path}")
            deleted += 1
            freed += int(getattr(f, "size", 0) or 0)
    print(f"\nwould delete {deleted} files, freed {_fmt_size(freed)}")
    return 0


# ---------------------------------------------------------------------------
# restore-trash subcommand (M-2)
# ---------------------------------------------------------------------------

def _cmd_restore_trash(args: argparse.Namespace) -> int:
    import uuid as uuid_mod

    manifest_path = Path.home() / ".cerebro" / "trash" / "manifest.jsonl"
    if not manifest_path.exists():
        print("No fallback trash manifest found.")
        return 0

    entries = []
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        print(f"error: cannot read manifest: {exc}", file=sys.stderr)
        return 1

    if not entries:
        print("Manifest is empty.")
        return 0

    # Filter by --id if provided.
    target_id = getattr(args, "id", None)
    if target_id:
        entries = [e for e in entries if e.get("id") == target_id]
        if not entries:
            print(f"No manifest entry found with id={target_id}.", file=sys.stderr)
            return 1

    # Filter by --all-since if provided.
    since_str = getattr(args, "all_since", None)
    if since_str:
        try:
            from datetime import datetime as _dt
            since_ts = _dt.fromisoformat(since_str).timestamp()
            entries = [e for e in entries if float(e.get("timestamp", 0)) >= since_ts]
        except ValueError as exc:
            print(f"error: invalid date format: {exc}", file=sys.stderr)
            return 1

    restored = 0
    failed = 0
    for entry in entries:
        original = entry.get("original_path", "")
        dest = entry.get("dest_path", "")
        if not original or not dest:
            continue
        src_p = Path(dest)
        dst_p = Path(original)
        if not src_p.exists():
            print(f"  skipped (not in trash): {original}", file=sys.stderr)
            continue
        if dst_p.exists():
            # Conflict: restore to timestamped name.
            ts = int(entry.get("timestamp", 0))
            dst_p = dst_p.parent / f"{dst_p.stem}.restored_{ts}{dst_p.suffix}"
            print(f"  conflict: restoring to {dst_p}")
        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.move(str(src_p), str(dst_p))
            print(f"  restored: {dst_p}")
            restored += 1
        except OSError as exc:
            print(f"  error restoring {original}: {exc}", file=sys.stderr)
            failed += 1

    print(f"\nrestored {restored} files, {failed} failures")
    return 0 if failed == 0 else 1


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
    sp.add_argument("folders", nargs="+", metavar="FOLDER", help="Folders to scan")
    sp.add_argument("--mode", default="files",
                    choices=["files", "photos", "music", "videos",
                             "empty_folders", "large_files", "burst"],
                    help="Scan engine (default: files)")
    sp.add_argument("--output", default="table", choices=["table", "json", "csv"],
                    help="Output format (default: table)")
    sp.add_argument("--min-size", type=int, default=0, metavar="BYTES",
                    help="Ignore files smaller than this (bytes)")
    sp.add_argument("--delete", action="store_true",
                    help="Delete duplicates after scanning via pipeline (default: trash)")
    sp.add_argument("--permanent", action="store_true",
                    help="Permanent deletion (requires interactive YES confirmation; implies --delete)")
    sp.add_argument("--keep", choices=["largest", "smallest", "oldest", "newest"],
                    default="largest",
                    help="Which copy to keep when --delete is used (default: largest)")
    sp.add_argument("--dry-run", action="store_true",
                    help="Preview deletions without changing any files")
    sp.add_argument("--quiet", action="store_true",
                    help="Suppress progress output")

    # restore-trash
    rp = sub.add_parser("restore-trash", help="Restore files from fallback-trash manifest")
    rp.add_argument("--id", metavar="UUID", default=None,
                    help="Restore only the entry with this manifest id")
    rp.add_argument("--all-since", metavar="DATE", default=None,
                    help="Restore all entries since this ISO date (e.g. 2026-05-01)")

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
