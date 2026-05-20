#!/usr/bin/env python3
"""
review_ui_layer_bisect.py — apply one review-UI layer from the bad worktree
onto the current tree to bisect review-page regressions one file at a time.

Subcommands
-----------
  list                     enumerate layers with their indices
  apply <idx>              restore layer[idx] to good-sha baseline, then
                           overwrite with the bad-worktree version
  restore <idx>            restore layer[idx] to the good-sha version
  restore --all            restore every layer to the good-sha version

Flags
-----
  --good <sha>             known-good commit (e.g. 95ff3aeb)
  --bad-worktree           auto-detect the bad worktree (any non-main,
                           non-good worktree in this repo)
  --smoke                  run compile smoke after apply/restore; exit 0 on
                           PASS, 1 on FAIL
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_REVIEW_FLOW_PKG = "cerebro/v2/ui/flet_app/pages/review_flow"
_SMOKE_TARGETS = [_REVIEW_FLOW_PKG]


# ── git helpers ───────────────────────────────────────────────────────────────

def _run(args: list[str], *, cwd: Path = REPO_ROOT, check: bool = True) -> str:
    return subprocess.run(
        args, capture_output=True, text=True, cwd=cwd, check=check,
    ).stdout.strip()


def _sha_exists_in_good(good_sha: str, repo_path: str) -> bool:
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{good_sha}:{repo_path}"],
        cwd=REPO_ROOT,
    )
    return r.returncode == 0


def _restore_file_to_good(good_sha: str, repo_path: str) -> None:
    dest = REPO_ROOT / repo_path
    if _sha_exists_in_good(good_sha, repo_path):
        content = subprocess.run(
            ["git", "show", f"{good_sha}:{repo_path}"],
            capture_output=True, cwd=REPO_ROOT, check=True,
        ).stdout
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    else:
        if dest.exists():
            dest.unlink()


# ── worktree helpers ──────────────────────────────────────────────────────────

def _worktree_list() -> list[tuple[Path, str]]:
    raw = _run(["git", "worktree", "list", "--porcelain"])
    result: list[tuple[Path, str]] = []
    for block in raw.split("\n\n"):
        data: dict[str, str] = {}
        for line in block.strip().splitlines():
            if " " in line:
                k, v = line.split(" ", 1)
                data[k] = v
        if "worktree" in data and "HEAD" in data:
            result.append((Path(data["worktree"]), data["HEAD"]))
    return result


def _find_bad_worktree(good_sha: str) -> tuple[Path, str]:
    wts = _worktree_list()
    current = REPO_ROOT.resolve()
    candidates: list[tuple[Path, str]] = []
    for path, sha in wts:
        if path.resolve() == current:
            continue
        if sha.startswith(good_sha[:8]) or good_sha.startswith(sha[:8]):
            continue
        candidates.append((path, sha))
    if not candidates:
        sys.exit(
            "error: no bad worktree found — every non-main worktree is at "
            f"the good sha ({good_sha[:8]})."
        )
    if len(candidates) > 1:
        paths = ", ".join(str(p) for p, _ in candidates)
        sys.exit(f"error: multiple bad worktrees found: {paths}")
    return candidates[0]


# ── layer computation ─────────────────────────────────────────────────────────

def _compute_layers(good_sha: str, bad_sha: str) -> list[str]:
    raw = _run([
        "git", "diff", "--name-only", good_sha, bad_sha,
        "--", _REVIEW_FLOW_PKG,
    ])
    if not raw:
        return []
    return sorted(raw.splitlines())


# ── smoke test ────────────────────────────────────────────────────────────────

def _run_smoke() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "-q"] + _SMOKE_TARGETS,
        cwd=REPO_ROOT,
    )
    if r.returncode == 0:
        print("SMOKE PASS")
        return True
    print(f"SMOKE FAIL (exit {r.returncode})")
    return False


# ── subcommands ───────────────────────────────────────────────────────────────

def cmd_list(good_sha: str, bad_wt: Path, bad_sha: str) -> None:
    layers = _compute_layers(good_sha, bad_sha)
    if not layers:
        print(f"No differences between good ({good_sha[:8]}) and bad ({bad_sha[:8]}).")
        return
    print(f"Layers  good={good_sha[:8]}  bad={bad_sha[:8]}  ({bad_wt.name})\n")
    for i, path in enumerate(layers):
        in_good = _sha_exists_in_good(good_sha, path)
        in_bad = (bad_wt / path).exists()
        if in_good and in_bad:
            tag = "CHANGED"
        elif in_good:
            tag = "ADDED-IN-GOOD"
        else:
            tag = "ADDED-IN-BAD"
        print(f"  [{i:2d}] {path}  ({tag})")


def cmd_apply(idx: int, good_sha: str, bad_wt: Path, bad_sha: str, smoke: bool) -> None:
    layers = _compute_layers(good_sha, bad_sha)
    if idx >= len(layers):
        sys.exit(f"error: index {idx} out of range (0–{len(layers) - 1})")

    repo_path = layers[idx]
    in_good = _sha_exists_in_good(good_sha, repo_path)
    bad_src = bad_wt / repo_path
    in_bad = bad_src.exists()

    print(f"[{idx}] {repo_path}")
    print(f"  → restoring good baseline ({good_sha[:8]}) …")
    _restore_file_to_good(good_sha, repo_path)

    dest = REPO_ROOT / repo_path
    if in_bad:
        print(f"  → applying bad version from {bad_wt.name} …")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bad_src.read_bytes())
    elif in_good:
        print("  → file absent in bad worktree; good baseline deleted")
    else:
        print("  → file absent in both — nothing to do")

    if smoke:
        print()
        ok = _run_smoke()
        sys.exit(0 if ok else 1)


def cmd_restore(
    idx: int | None,
    restore_all: bool,
    good_sha: str,
    bad_sha: str,
    smoke: bool,
) -> None:
    layers = _compute_layers(good_sha, bad_sha)
    targets = layers if restore_all else [layers[idx]]
    for repo_path in targets:
        print(f"  restoring {repo_path} → {good_sha[:8]} …")
        _restore_file_to_good(good_sha, repo_path)
    if smoke:
        print()
        ok = _run_smoke()
        sys.exit(0 if ok else 1)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bisect review-UI regressions one file-layer at a time.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--good", required=True, metavar="SHA")
    common.add_argument("--bad-worktree", action="store_true")
    common.add_argument("--smoke", action="store_true")

    sub.add_parser("list", parents=[common])

    p_apply = sub.add_parser("apply", parents=[common])
    p_apply.add_argument("idx", type=int, metavar="IDX")

    p_restore = sub.add_parser("restore", parents=[common])
    rg = p_restore.add_mutually_exclusive_group(required=True)
    rg.add_argument("idx", type=int, nargs="?", metavar="IDX")
    rg.add_argument("--all", dest="restore_all", action="store_true")

    args = parser.parse_args()
    if not args.bad_worktree:
        parser.error("--bad-worktree is required")

    bad_wt, bad_sha = _find_bad_worktree(args.good)

    if args.cmd == "list":
        cmd_list(args.good, bad_wt, bad_sha)
    elif args.cmd == "apply":
        cmd_apply(args.idx, args.good, bad_wt, bad_sha, args.smoke)
    elif args.cmd == "restore":
        idx = None if args.restore_all else args.idx
        if not args.restore_all and idx is None:
            parser.error("restore requires IDX or --all")
        cmd_restore(idx, args.restore_all, args.good, bad_sha, args.smoke)


if __name__ == "__main__":
    main()
