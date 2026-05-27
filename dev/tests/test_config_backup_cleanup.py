"""
test_config_backup_cleanup.py — L-4: Config backup errors are logged, not swallowed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest


def _has_config_manager():
    try:
        from cerebro.services.config import ConfigManager  # noqa: F401
        return True
    except (ImportError, AttributeError):
        return False


@pytest.mark.skipif(not _has_config_manager(), reason="ConfigManager not available")
def test_backup_corrupted_config_logs_on_error(tmp_path):
    """_backup_corrupted_config must log a warning on OSError, not silently pass."""
    import logging as _logging
    from unittest.mock import MagicMock
    from cerebro.services.config import ConfigManager
    import cerebro.services.config as _cfg_mod

    mgr = ConfigManager.__new__(ConfigManager)
    mgr.config_file = tmp_path / "config.json"
    mgr.backup_dir = tmp_path / "backups"
    mgr.backup_dir.mkdir()
    mgr.config_file.write_text("{}")

    warning_calls = []
    original_warning = _cfg_mod.logger.warning

    def _capture(*args, **kwargs):
        warning_calls.append(args)
        return original_warning(*args, **kwargs)

    with patch.object(_cfg_mod.logger, "warning", side_effect=_capture):
        with patch("shutil.copy2", side_effect=OSError("Permission denied")):
            mgr._backup_corrupted_config()

    assert any("Permission denied" in str(a) for a in warning_calls), \
        "OSError must be logged as a warning, not silently swallowed"


@pytest.mark.skipif(not _has_config_manager(), reason="ConfigManager not available")
def test_cleanup_old_backups_logs_on_unlink_error(tmp_path):
    """_cleanup_old_backups must log a warning if unlink fails."""
    from cerebro.services.config import ConfigManager
    import cerebro.services.config as _cfg_mod

    mgr = ConfigManager.__new__(ConfigManager)
    mgr.backup_dir = tmp_path / "backups"
    mgr.backup_dir.mkdir()

    for i in range(8):
        (mgr.backup_dir / f"config_backup_202601{i:02d}_000000.json").write_text("{}")

    warning_calls = []
    original_warning = _cfg_mod.logger.warning

    def _capture(*args, **kwargs):
        warning_calls.append(args)
        return original_warning(*args, **kwargs)

    with patch.object(_cfg_mod.logger, "warning", side_effect=_capture):
        with patch.object(Path, "unlink", side_effect=OSError("Read-only filesystem")):
            mgr._cleanup_old_backups()

    assert any("Read-only" in str(a) for a in warning_calls), \
        "unlink OSError must be logged as warning"
