from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from cerebro.core.models import DuplicateGroup, FileMetadata




@dataclass(frozen=True)
class TrashAction:
    moved: List[Tuple[str, str]]  # (src, dst)


class TrashManager:
    """
    Core safety layer for duplicate cleanup.
    Responsible ONLY for safe file relocation and undo.
    """

    def __init__(self, trash_dir_name: str = ".cerebro_trash"):
        self.trash_dir_name = trash_dir_name

    def move_duplicates(
        self,
        groups: List[DuplicateGroup],
        scan_root: Path
    ) -> TrashAction:
        trash_root = scan_root / self.trash_dir_name
        trash_root.mkdir(parents=True, exist_ok=True)

        moved: List[Tuple[str, str]] = []

        for group in groups:
            group.ensure_one_survivor()

            for item in group.items:
                if item.keep:
                    continue

                src = Path(item.path)
                if not src.exists():
                    continue

                rel = self._safe_relpath(src, scan_root)
                dst = trash_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst = self._dedupe_path(dst)

                src.replace(dst)
                moved.append((str(src), str(dst)))

        return TrashAction(moved=moved)

    def undo(self, action: TrashAction) -> bool:
        if not action.moved:
            return False

        ok = True
        for src, dst in reversed(action.moved):
            dst_p = Path(dst)
            src_p = Path(src)
            try:
                if dst_p.exists():
                    src_p.parent.mkdir(parents=True, exist_ok=True)
                    dst_p.replace(src_p)
            except Exception:
                ok = False

        return ok

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _safe_relpath(self, path: Path, scan_root: Path) -> Path:
        try:
            return path.relative_to(scan_root)
        except Exception:
            safe = str(path).replace(":", "").lstrip("\\/")
            return Path("_external") / safe

    def _dedupe_path(self, path: Path) -> Path:
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent

        for i in range(1, 10_000):
            candidate = parent / f"{stem}__{i}{suffix}"
            if not candidate.exists():
                return candidate

        raise RuntimeError("Could not dedupe trash path")
