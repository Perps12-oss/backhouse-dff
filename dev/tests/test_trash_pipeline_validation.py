"""Trash deletes must pass pipeline path validation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from cerebro.core.pipeline import CerebroPipeline
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService, DeletionPolicy


def test_trash_uses_pipeline_plan() -> None:
    pipe = CerebroPipeline()
    svc = DeleteService(pipe)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(b"x")
        path = f.name
    try:
        with patch.object(svc, "_delete_to_managed_trash", return_value=([], [])):
            with patch.object(
                pipe,
                "build_explicit_paths_plan",
                return_value=MagicMock(operations=[MagicMock(path=Path(path))]),
            ) as plan:
                svc.delete_files([path], DeletionPolicy.TRASH)
                plan.assert_called_once()
    finally:
        Path(path).unlink(missing_ok=True)
