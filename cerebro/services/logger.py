# cerebro/services/logger.py
from __future__ import annotations

"""
CEREBRO Logger (Normalized)

- Single global logging configuration (no per-module handlers).
- Safe on locked folders (falls back to OS temp dir).
- Backwards compatible symbols used across the codebase:
    logger, get_logger,
    log_debug, log_info, log_warning, log_error, log_exception,
    set_scan_id, get_scan_id,
    flush_all_handlers
"""

import logging
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Optional, Generator

# Global DEBUG: when set (e.g. CEREBRO_DEBUG=1), root level is DEBUG so log_debug is emitted
DEBUG = os.environ.get("CEREBRO_DEBUG", "").strip().lower() in ("1", "true", "yes")


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
        record.scan_id = get_scan_id()
        return True


# ----------------------------
# Global configuration (once)
# ----------------------------

_configured = False
_config_lock = threading.Lock()
_current_log_file: Optional[Path] = None


def _safe_logs_dir() -> Path:
    """
    Prefer <project_root>/logs if possible.
    Fall back to OS temp if we can't create or write there.
    """
    here = Path(__file__).resolve()
    root = here.parents[2]  # <root> (.. / .. /)
    preferred = root / "logs"

    try:
        preferred.mkdir(parents=True, exist_ok=True)
        test = preferred / ".write_test"
        test.write_text("ok", encoding="utf-8")
        try:
            test.unlink()
        except Exception:
            pass
        return preferred
    except Exception:
        tmp = Path(tempfile.gettempdir()) / "cerebro_logs"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp


def _configure_root(level: int = logging.INFO, 
                    log_to_file: bool = True,
                    file_max_size: int = 10*1024*1024,  # 10MB
                    file_backup_count: int = 5) -> None:
    global _configured, _current_log_file
    
    with _config_lock:
        if _configured:
            return

        base = logging.getLogger("CEREBRO")
        base.setLevel(level)
        base.propagate = False  # prevents double printing via Python root logger

        # Defensive: if module reloads in dev, don't duplicate handlers
        for h in list(base.handlers):
            try:
                base.removeHandler(h)
                h.close()
            except Exception:
                pass

        class _Fmt(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                scan = getattr(record, "scan_id", "")
                scan_part = f" [scan:{scan}]" if scan else ""
                # Store formatted message
                original_msg = record.getMessage()
                formatted = super().format(record)
                # Insert scan info after the logger name
                return formatted.replace(
                    f"{record.name}:", 
                    f"{record.name}{scan_part}:"
                )

        formatter = _Fmt(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        # Console handler
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(level)
        sh.setFormatter(formatter)
        sh.addFilter(_ScanIdFilter())
        base.addHandler(sh)

        # File handler (best effort)
        if log_to_file:
            try:
                logs_dir = _safe_logs_dir()
                # Use rotating file handler instead of timestamp-based
                from logging.handlers import RotatingFileHandler
                log_file = logs_dir / "cerebro.log"
                _current_log_file = log_file
                
                fh = RotatingFileHandler(
                    log_file,
                    maxBytes=file_max_size,
                    backupCount=file_backup_count,
                    encoding="utf-8"
                )
                fh.setLevel(level)
                fh.setFormatter(formatter)
                fh.addFilter(_ScanIdFilter())
                base.addHandler(fh)
                
                # Also create a timestamped log for this session
                stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                session_log = logs_dir / f"cerebro_{stamp}.log"
                session_fh = logging.FileHandler(session_log, encoding="utf-8")
                session_fh.setLevel(level)
                session_fh.setFormatter(formatter)
                session_fh.addFilter(_ScanIdFilter())
                base.addHandler(session_fh)
            except Exception:
                # Console logging still works even if file logging fails.
                pass

        _configured = True


def configure(level: int = logging.INFO, 
              log_to_file: bool = True,
              file_max_size: int = 10*1024*1024,
              file_backup_count: int = 5) -> None:
    """Configure the logger with custom options."""
    global _configured
    with _config_lock:
        _configured = False
        _configure_root(level, log_to_file, file_max_size, file_backup_count)


def get_logger(name: Optional[str] = None, level: Optional[int] = None) -> logging.Logger:
    """
    Get a logger that shares the global CEREBRO handlers.
    Never add handlers in feature modules; use this instead.
    """
    _configure_root()
    base = logging.getLogger("CEREBRO")

    lg = base.getChild(name) if name else base
    if level is not None:
        # Validate it's a proper logging level
        valid_levels = {
            logging.DEBUG, logging.INFO, logging.WARNING,
            logging.ERROR, logging.CRITICAL, logging.FATAL,
            logging.NOTSET
        }
        if level in valid_levels:
            lg.setLevel(level)
        else:
            lg.setLevel(logging.INFO)

    lg.propagate = False
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
    base = logging.getLogger("CEREBRO")
    for h in base.handlers[:]:  # Create a copy to avoid iteration issues
        try:
            if hasattr(h, 'flush'):
                h.flush()
        except (AttributeError, ValueError):
            # Handler might have been closed
            continue


def get_current_log_file() -> Optional[Path]:
    """Get the path to the current rotating log file."""
    return _current_log_file


def cleanup_handlers() -> None:
    """Clean up all handlers (useful for tests or reconfiguration)."""
    global _configured
    with _config_lock:
        base = logging.getLogger("CEREBRO")
        for h in list(base.handlers):
            try:
                base.removeHandler(h)
                h.close()
            except Exception:
                pass
        _configured = False


# Initialize on module import (debug logs only when DEBUG/level allows)
_configure_root(level=logging.DEBUG if DEBUG else logging.INFO)