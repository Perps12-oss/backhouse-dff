# cerebro/services/logger.py
from __future__ import annotations

"""
CEREBRO Logger

- Single global logging configuration under the "cerebro" hierarchy.
- Module loggers (logging.getLogger(__name__)) propagate here automatically
  because __name__ resolves to e.g. "cerebro.services.config" which is a
  child of "cerebro" in Python's logging tree.
- Optional JSON output: set CEREBRO_LOG_JSON=1 for structured log lines.
- Optional debug verbosity: set CEREBRO_DEBUG=1.
- Safe on locked folders (falls back to OS temp dir).
- Backwards compatible symbols used across the codebase:
    logger, get_logger,
    log_debug, log_info, log_warning, log_error, log_exception,
    set_scan_id, get_scan_id,
    flush_all_handlers
"""

import json
import logging
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Generator

DEBUG = os.environ.get("CEREBRO_DEBUG", "").strip().lower() in ("1", "true", "yes")
LOG_JSON = os.environ.get("CEREBRO_LOG_JSON", "").strip().lower() in ("1", "true", "yes")

# Root name for the entire cerebro logging hierarchy.
# All module loggers (getLogger(__name__)) propagate here automatically.
_ROOT_NAME = "cerebro"


# ----------------------------
# Context (scan/session tagging)
# ----------------------------

_scan_id: ContextVar[str] = ContextVar("cerebro_scan_id", default="")


def set_scan_id(scan_id: str) -> None:
    """Attach a scan id to subsequent log records in the current context."""
    _scan_id.set(str(scan_id or ""))


def get_scan_id() -> str:
    return _scan_id.get()


@contextmanager
def scan_context(scan_id: str) -> Generator[None, None, None]:
    """Context manager for temporary scan ID setting."""
    token = _scan_id.set(str(scan_id or ""))
    try:
        yield
    finally:
        _scan_id.reset(token)


class _ScanIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.scan_id = get_scan_id()  # type: ignore[attr-defined]
        return True


# ----------------------------
# Formatters
# ----------------------------

class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        scan = getattr(record, "scan_id", "")
        scan_part = f" [scan:{scan}]" if scan else ""
        formatted = super().format(record)
        return formatted.replace(f"{record.name}:", f"{record.name}{scan_part}:")


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for log aggregator ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        scan = getattr(record, "scan_id", "")
        if scan:
            payload["scan_id"] = scan
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# ----------------------------
# Global configuration (once)
# ----------------------------

_configured = False
_config_lock = threading.Lock()
_current_log_file: Optional[Path] = None


class _WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that survives Windows os.rename failures on rollover.

    On Windows, concurrent file handles (second app instance, log viewer) cause
    PermissionError during os.rename. This handler catches that, reopens the
    stream so writes continue to the oversized file, and suppresses further
    rollover attempts for the session rather than spamming handleError().
    """

    _rollover_warned: bool = False
    _rollover_disabled: bool = False

    def shouldRollover(self, record: logging.LogRecord) -> int:
        if _WindowsSafeRotatingFileHandler._rollover_disabled:
            return 0
        return super().shouldRollover(record)

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except (PermissionError, OSError) as exc:
            try:
                self.stream = self._open()
            except (OSError, ValueError):
                self.stream = None  # type: ignore[assignment]

            _WindowsSafeRotatingFileHandler._rollover_disabled = True

            if not _WindowsSafeRotatingFileHandler._rollover_warned:
                _WindowsSafeRotatingFileHandler._rollover_warned = True
                try:
                    sys.stderr.write(
                        f"[cerebro.logger] rotation of {self.baseFilename} "
                        f"failed ({exc.__class__.__name__}: {exc}); "
                        f"rollover disabled for this session. "
                        f"Close other CEREBRO instances and restart to re-enable.\n"
                    )
                    sys.stderr.flush()
                except (OSError, ValueError):
                    pass

    def handleError(self, record: logging.LogRecord) -> None:
        return


def _safe_logs_dir() -> Path:
    home_preferred = Path.home() / ".cerebro" / "logs"
    try:
        home_preferred.mkdir(parents=True, exist_ok=True)
        test = home_preferred / ".write_test"
        test.write_text("ok", encoding="utf-8")
        try:
            test.unlink()
        except OSError:
            pass
        return home_preferred
    except OSError:
        pass

    here = Path(__file__).resolve()
    root = here.parents[2]
    preferred = root / "logs"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        test = preferred / ".write_test"
        test.write_text("ok", encoding="utf-8")
        try:
            test.unlink()
        except OSError:
            pass
        return preferred
    except OSError:
        tmp = Path(tempfile.gettempdir()) / "cerebro_logs"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp


def _make_formatter() -> logging.Formatter:
    if LOG_JSON:
        return _JsonFormatter()
    return _TextFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _configure_root(
    level: int = logging.INFO,
    log_to_file: bool = True,
    file_max_size: int = 10 * 1024 * 1024,
    file_backup_count: int = 5,
) -> None:
    global _configured, _current_log_file

    with _config_lock:
        if _configured:
            return

        base = logging.getLogger(_ROOT_NAME)
        base.setLevel(level)
        # Prevent double-logging through Python's root logger.
        base.propagate = False

        for h in list(base.handlers):
            try:
                base.removeHandler(h)
                h.close()
            except OSError:
                pass

        formatter = _make_formatter()

        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(level)
        sh.setFormatter(formatter)
        sh.addFilter(_ScanIdFilter())
        base.addHandler(sh)

        if log_to_file:
            try:
                logs_dir = _safe_logs_dir()
                log_file = logs_dir / "cerebro.log"
                _current_log_file = log_file

                fh = _WindowsSafeRotatingFileHandler(
                    log_file,
                    maxBytes=file_max_size,
                    backupCount=file_backup_count,
                    encoding="utf-8",
                    delay=True,
                )
                fh.setLevel(level)
                fh.setFormatter(formatter)
                fh.addFilter(_ScanIdFilter())
                base.addHandler(fh)

                stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                session_log = logs_dir / f"cerebro_{stamp}.log"
                session_fh = logging.FileHandler(session_log, encoding="utf-8")
                session_fh.setLevel(level)
                session_fh.setFormatter(formatter)
                session_fh.addFilter(_ScanIdFilter())
                base.addHandler(session_fh)
            except OSError:
                pass

        _configured = True


def configure(
    level: int = logging.INFO,
    log_to_file: bool = True,
    file_max_size: int = 10 * 1024 * 1024,
    file_backup_count: int = 5,
) -> None:
    """Configure the logger with custom options."""
    global _configured
    with _config_lock:
        _configured = False
    _configure_root(level, log_to_file, file_max_size, file_backup_count)


def get_logger(name: Optional[str] = None, level: Optional[int] = None) -> logging.Logger:
    """Return a logger that shares the global cerebro handlers.

    If *name* is given, returns a child of the root cerebro logger
    (e.g. get_logger("history.store") → "cerebro.history.store").
    Prefer logging.getLogger(__name__) in modules — those names already sit
    in the right hierarchy and propagate here automatically.
    """
    _configure_root()
    base = logging.getLogger(_ROOT_NAME)

    lg = base.getChild(name) if name else base
    if level is not None:
        valid_levels = {
            logging.DEBUG, logging.INFO, logging.WARNING,
            logging.ERROR, logging.CRITICAL, logging.FATAL, logging.NOTSET,
        }
        lg.setLevel(level if level in valid_levels else logging.INFO)

    return lg


# Backwards-compatible global logger
logger = get_logger()


# ----------------------------
# Backwards compatible helpers
# ----------------------------

def log_debug(msg: str) -> None:
    logger.debug(msg)


def log_info(msg: str) -> None:
    logger.info(msg)


def log_warning(msg: str) -> None:
    logger.warning(msg)


def log_error(msg: str) -> None:
    logger.error(msg)


def log_exception(msg: str) -> None:
    logger.exception(msg)


def log_critical(msg: str) -> None:
    logger.critical(msg)


def log_fatal(msg: str) -> None:
    logger.fatal(msg)


def flush_all_handlers() -> None:
    """Flush stream/file handlers (useful before crash exit)."""
    base = logging.getLogger(_ROOT_NAME)
    for h in base.handlers[:]:
        try:
            if hasattr(h, "flush"):
                h.flush()
        except (AttributeError, ValueError):
            continue


def get_current_log_file() -> Optional[Path]:
    """Return the path to the current rotating log file."""
    return _current_log_file


def cleanup_handlers() -> None:
    """Remove all handlers and reset configuration (tests / reconfiguration)."""
    global _configured
    with _config_lock:
        base = logging.getLogger(_ROOT_NAME)
        for h in list(base.handlers):
            try:
                base.removeHandler(h)
                h.close()
            except OSError:
                pass
        _configured = False


def get_structured_logger(name: str) -> object:
    """Return a structlog BoundLogger for new code that wants key=value context.

    Falls back to a stdlib logger if structlog is not installed.

    Usage (new code only — do not migrate existing getLogger(__name__) calls):
        _log = get_structured_logger(__name__)
        _log.info("scan_complete", files=12345, elapsed_s=4.2)
    """
    try:
        import structlog

        _configure_structlog_once()
        return structlog.get_logger(name)
    except ImportError:
        return logging.getLogger(name)


_structlog_configured = False
_structlog_lock = threading.Lock()


def _configure_structlog_once() -> None:
    global _structlog_configured
    if _structlog_configured:
        return
    with _structlog_lock:
        if _structlog_configured:
            return
        import structlog

        processors: list = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S", utc=False),
        ]
        if LOG_JSON:
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(
                logging.DEBUG if DEBUG else logging.INFO
            ),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        _structlog_configured = True


# Initialize on module import
_configure_root(level=logging.DEBUG if DEBUG else logging.INFO)
