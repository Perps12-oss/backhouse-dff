from __future__ import annotations

import random
import time
from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup


def generate_mock_groups(count: int = 1000, *, seed: int = 42) -> list[DuplicateGroup]:
  rng = random.Random(seed)
  groups: list[DuplicateGroup] = []
  exts = [".jpg", ".png", ".pdf", ".mp3", ".mp4", ".docx", ".zip"]
  base = Path("/mock/Photos/2024")
  now = time.time()
  for gid in range(1, count + 1):
    ext = rng.choice(exts)
    dup_count = rng.randint(2, 5)
    files: list[DuplicateFile] = []
    size = rng.randint(50_000, 8_000_000)
    for idx in range(dup_count):
      path = base / f"folder_{gid % 40}" / f"vacation_{gid:04d}_{idx}{ext}"
      files.append(
        DuplicateFile(
          path=path,
          size=size + rng.randint(-500, 500),
          modified=now - rng.randint(0, 86400 * 400),
          extension=ext.lstrip("."),
          similarity=rng.uniform(0.85, 1.0),
          metadata={"mock": True},
        )
      )
    groups.append(
      DuplicateGroup(
        group_id=gid,
        files=files,
        similarity_type="exact" if files[0].similarity >= 0.99 else "visual",
      )
    )
  return groups


def mock_overview_metrics(groups: list[DuplicateGroup]) -> dict[str, int | float]:
  file_count = sum(len(g.files) for g in groups)
  reclaimable = sum(int(getattr(g, "reclaimable", 0) or 0) for g in groups)
  return {
    "set_count": len(groups),
    "file_count": file_count,
    "reclaimable_bytes": reclaimable,
    "scan_seconds": 14 * 60 + 32,
    "files_scanned": 45231,
  }
