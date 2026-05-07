"""
Verify that module loggers (logging.getLogger(__name__)) emit records
to the cerebro file handler.

The key invariant: logging.getLogger("cerebro.services.config") is a child
of logging.getLogger("cerebro"), so its records propagate to the cerebro
root handlers — including the rotating file handler — without any per-module
handler configuration.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest

from cerebro.services.logger import cleanup_handlers


def _get_logger_module():
    # cerebro/services/__init__.py re-exports `logger` (Logger instance) as an
    # attribute named `logger`, which shadows the submodule when using plain
    # `import cerebro.services.logger`. importlib.import_module goes through
    # sys.modules directly and always returns the module object.
    return importlib.import_module("cerebro.services.logger")


@pytest.fixture(autouse=True)
def isolated_logger(tmp_path: Path):
    """Reset and reconfigure the cerebro logger for each test."""
    cleanup_handlers()
    mod = _get_logger_module()
    original = mod._safe_logs_dir  # type: ignore[attr-defined]

    def _tmp_logs_dir() -> Path:
        d = tmp_path / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    mod._safe_logs_dir = _tmp_logs_dir  # type: ignore[attr-defined]
    mod._configure_root(level=logging.DEBUG, log_to_file=True)  # type: ignore[attr-defined]
    yield tmp_path
    cleanup_handlers()
    mod._safe_logs_dir = original  # type: ignore[attr-defined]


def _read_log(tmp_path: Path) -> str:
    log_file = tmp_path / "logs" / "cerebro.log"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


def test_root_logger_writes_to_file(tmp_path: Path) -> None:
    """logging.getLogger('cerebro') records reach the file handler."""
    from cerebro.services.logger import flush_all_handlers
    log = logging.getLogger("cerebro")
    log.warning("root-logger-sentinel-abc123")
    flush_all_handlers()
    assert "root-logger-sentinel-abc123" in _read_log(tmp_path)


def test_deep_module_logger_propagates_to_file(tmp_path: Path) -> None:
    """logging.getLogger('cerebro.services.config') propagates to file handler."""
    from cerebro.services.logger import flush_all_handlers
    log = logging.getLogger("cerebro.services.config")
    log.warning("deep-module-sentinel-xyz789")
    flush_all_handlers()
    content = _read_log(tmp_path)
    assert "deep-module-sentinel-xyz789" in content, (
        "Record from cerebro.services.config did not reach the file handler. "
        "Logger hierarchy is broken."
    )


def test_unrelated_logger_does_not_appear(tmp_path: Path) -> None:
    """A logger outside the cerebro hierarchy does not appear in cerebro's file."""
    from cerebro.services.logger import flush_all_handlers
    log = logging.getLogger("someother.module")
    log.warning("outsider-sentinel-never-appears")
    flush_all_handlers()
    assert "outsider-sentinel-never-appears" not in _read_log(tmp_path)


def test_json_formatter_emits_valid_json(tmp_path: Path, monkeypatch) -> None:
    """When CEREBRO_LOG_JSON=1, every log line is valid JSON."""
    mod = _get_logger_module()
    cleanup_handlers()
    monkeypatch.setattr(mod, "LOG_JSON", True)
    monkeypatch.setattr(mod, "_configured", False)

    def _tmp_logs_dir() -> Path:
        d = tmp_path / "logs_json"
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(mod, "_safe_logs_dir", _tmp_logs_dir)
    mod._configure_root(level=logging.DEBUG, log_to_file=True)  # type: ignore[attr-defined]

    import json
    log = logging.getLogger("cerebro.test.json_fmt")
    log.info("json-format-check")
    mod.flush_all_handlers()  # type: ignore[attr-defined]

    log_file = tmp_path / "logs_json" / "cerebro.log"
    lines = [l.strip() for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines, "No log lines written"
    for line in lines:
        parsed = json.loads(line)
        assert "level" in parsed
        assert "msg" in parsed
