"""
Engine dependency registry + probe for the Phase-7 diagnostics overhaul.

Single source of truth for "which scan engines exist, what do they need,
and what's their current state?" — used by both
:class:`DiagnosticsPage` (rich status rows) and :class:`ScanPage`
(pre-scan warning banner).

The v1 diagnostics page caught ``ImportError`` in a single ``try/except``
and rendered the same opaque ``"import error: ModuleNotFoundError"``
string for every failure, regardless of whether:

* the engine module itself is not yet implemented in-tree (no file),
* the engine module exists but a third-party *pip* dependency is
  missing (e.g. ``mutagen`` for Music), or
* the engine module imports fine but a *runtime* resource is missing
  (e.g. the ``ffmpeg`` binary for Video).

This module models those three distinct situations as first-class
states, so the UI can show actionable guidance ("install ``pyacoustid``"
vs "planned for a future release" vs "ffmpeg not on PATH") instead of
a single generic error.

No UI imports here — this module is pure data + probe logic so it can
be unit-tested headless and re-used by any future surface (CLI ``doctor``
command, telemetry exporter, etc.).
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------

class EngineState(str, Enum):
    """Canonical state for a scan engine."""

    AVAILABLE       = "available"        # engine module + deps + runtime all OK
    NOT_IMPLEMENTED = "not_implemented"  # planned engine — no module in-tree yet
    MISSING_DEPS    = "missing_deps"     # pip package(s) missing
    DEGRADED        = "degraded"         # imports fine but an optional runtime resource is missing
    RUNTIME_ERROR   = "runtime_error"    # module imports and class instantiates, but raised on probe


# ---------------------------------------------------------------------------
# Registry entries
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineInfo:
    """Static metadata for an engine entry.

    Attributes
    ----------
    key:
        Stable lowercase identifier. Matches ``ScanOrchestrator`` mode keys
        for real engines; diagnostic-only entries (audio, documents) use
        free-form identifiers that do *not* appear in ``_SCAN_MODES``.
    display_name:
        Plain-language name shown to the user.
    module_path:
        Dotted Python path. May point at a module that does not yet exist
        in-tree — that is explicitly the ``NOT_IMPLEMENTED`` case.
    class_name:
        Name of the engine class inside ``module_path``.
    planned:
        True if the engine is reserved for a future release and the
        module is expected *not* to exist today. This lets the probe
        distinguish "planned, not a bug" from "should exist but broke".
    pip_hint:
        Copyable pip command shown to the user when deps are missing.
        ``None`` when the engine has no external pip dependencies.
    runtime_check:
        Optional callable ``() -> (bool, detail_str)`` executed after the
        engine instance is constructed. Returning ``(False, "...")``
        demotes the state from ``AVAILABLE`` to ``DEGRADED``.
    """

    key: str
    display_name: str
    module_path: str
    class_name: str
    planned: bool = False
    pip_hint: Optional[str] = None
    runtime_check: Optional[Callable[[object], "tuple[bool, str]"]] = field(
        default=None, compare=False,
    )


# ---------------------------------------------------------------------------
# Runtime checks
# ---------------------------------------------------------------------------

def _video_ffmpeg_check(engine: object) -> "tuple[bool, str]":
    """Video engine carries an ``_ffmpeg`` attribute populated at __init__ time."""
    ffmpeg = getattr(engine, "_ffmpeg", None)
    if ffmpeg:
        return True, "ffmpeg on PATH"
    return False, "ffmpeg not found on PATH"


def _music_mutagen_check(engine: object) -> "tuple[bool, str]":
    """Music engine reads tags via mutagen; the import is deferred to scan time."""
    del engine
    try:
        importlib.import_module("mutagen")
        return True, "mutagen available"
    except ImportError:
        return False, "mutagen not installed (tag-based deduplication disabled)"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ENGINE_DEPS: "dict[str, EngineInfo]" = {
    "files": EngineInfo(
        key="files",
        display_name="Files (TurboFile)",
        module_path="cerebro.engines.turbo_file_engine",
        class_name="TurboFileEngine",
    ),
    "photos": EngineInfo(
        key="photos",
        display_name="Images (perceptual)",
        module_path="cerebro.engines.image_dedup_engine",
        class_name="ImageDedupEngine",
        pip_hint="pip install Pillow imagehash",
    ),
    "videos": EngineInfo(
        key="videos",
        display_name="Videos (frame hash)",
        module_path="cerebro.engines.video_dedup_engine",
        class_name="VideoDedupEngine",
        pip_hint="winget install Gyan.FFmpeg  (or: choco install ffmpeg)",
        runtime_check=_video_ffmpeg_check,
    ),
    "music": EngineInfo(
        key="music",
        display_name="Music (tags + hash)",
        module_path="cerebro.engines.music_dedup_engine",
        class_name="MusicDedupEngine",
        pip_hint="pip install mutagen",
        runtime_check=_music_mutagen_check,
    ),
    "empty_folders": EngineInfo(
        key="empty_folders",
        display_name="Empty folders",
        module_path="cerebro.engines.empty_folder_engine",
        class_name="EmptyFolderEngine",
    ),
    "large_files": EngineInfo(
        key="large_files",
        display_name="Large files",
        module_path="cerebro.engines.large_file_engine",
        class_name="LargeFileEngine",
    ),
    # Planned — no module file in-tree yet. Listed so the diagnostics page
    # is honest about which engines the roadmap mentions, without falsely
    # implying they are "broken". When these modules land they can be
    # flipped to ``planned=False`` with the correct pip_hint.
    "audio": EngineInfo(
        key="audio",
        display_name="Audio (fingerprint)",
        module_path="cerebro.engines.audio_dedup_engine",
        class_name="AudioDedupEngine",
        planned=True,
    ),
    "documents": EngineInfo(
        key="documents",
        display_name="Documents (content)",
        module_path="cerebro.engines.document_dedup_engine",
        class_name="DocumentDedupEngine",
        planned=True,
    ),
}


# ---------------------------------------------------------------------------
# Probe result
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    """Structured probe outcome. Mirrors :class:`EngineInfo` by ``key``."""

    key: str
    state: EngineState
    detail: str
    pip_hint: Optional[str] = None
    exception_class: Optional[str] = None
    exception_message: Optional[str] = None
    module_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.state is EngineState.AVAILABLE

    @property
    def is_actionable(self) -> bool:
        """True if the user can do something (install / retry) to fix it."""
        return self.state in (
            EngineState.MISSING_DEPS,
            EngineState.DEGRADED,
            EngineState.RUNTIME_ERROR,
        )


# ---------------------------------------------------------------------------
# Probe logic
# ---------------------------------------------------------------------------

def _module_missing_is_planned(info: EngineInfo, missing_name: Optional[str]) -> bool:
    """Decide whether a ``ModuleNotFoundError`` represents the engine's own
    module being absent (planned) or a transitive dep being absent (missing_deps).

    ``missing_name`` is ``ModuleNotFoundError.name`` — the fully-qualified
    module that couldn't be found. We consider the engine's own module
    absent when ``missing_name`` equals ``info.module_path`` (or a parent
    package thereof).
    """
    if not missing_name:
        return info.planned
    if missing_name == info.module_path:
        return True
    # Parent package absent (e.g. cerebro.engines.audio_dedup_engine has
    # no cerebro.engines.audio package yet): treat as planned too.
    return info.module_path.startswith(missing_name + ".")


def probe_engine(info: EngineInfo) -> ProbeResult:
    """Resolve an :class:`EngineInfo` into a concrete :class:`ProbeResult`."""
    # Step 1 — import module.
    try:
        mod = importlib.import_module(info.module_path)
    except ModuleNotFoundError as exc:
        if _module_missing_is_planned(info, getattr(exc, "name", None)):
            return ProbeResult(
                key=info.key,
                state=EngineState.NOT_IMPLEMENTED,
                detail="not yet implemented (planned for a future release)",
                module_path=info.module_path,
                exception_class=exc.__class__.__name__,
                exception_message=str(exc),
            )
        return ProbeResult(
            key=info.key,
            state=EngineState.MISSING_DEPS,
            detail=f"missing dependency: {getattr(exc, 'name', None) or str(exc)}",
            pip_hint=info.pip_hint,
            module_path=info.module_path,
            exception_class=exc.__class__.__name__,
            exception_message=str(exc),
        )
    except ImportError as exc:
        return ProbeResult(
            key=info.key,
            state=EngineState.MISSING_DEPS,
            detail=f"import error: {exc}",
            pip_hint=info.pip_hint,
            module_path=info.module_path,
            exception_class=exc.__class__.__name__,
            exception_message=str(exc),
        )
    except Exception as exc:
        _log.exception("Engine %s raised during import", info.key)
        return ProbeResult(
            key=info.key,
            state=EngineState.RUNTIME_ERROR,
            detail=f"import raised {exc.__class__.__name__}: {exc}",
            module_path=info.module_path,
            exception_class=exc.__class__.__name__,
            exception_message=str(exc),
        )

    # Step 2 — resolve class.
    cls = getattr(mod, info.class_name, None)
    if cls is None:
        return ProbeResult(
            key=info.key,
            state=EngineState.RUNTIME_ERROR,
            detail=f"class {info.class_name!r} not found in {info.module_path}",
            module_path=info.module_path,
            exception_class="AttributeError",
            exception_message=f"module {info.module_path!r} has no attribute {info.class_name!r}",
        )

    # Step 3 — instantiate.
    try:
        engine = cls()
    except Exception as exc:
        _log.exception("Engine %s raised during construction", info.key)
        return ProbeResult(
            key=info.key,
            state=EngineState.RUNTIME_ERROR,
            detail=f"construction raised {exc.__class__.__name__}: {exc}",
            module_path=info.module_path,
            exception_class=exc.__class__.__name__,
            exception_message=str(exc),
        )

    # Step 4 — optional runtime check (ffmpeg, mutagen, ...).
    if info.runtime_check is not None:
        try:
            ok, detail = info.runtime_check(engine)
        except Exception as exc:
            _log.exception("Engine %s runtime_check raised", info.key)
            return ProbeResult(
                key=info.key,
                state=EngineState.RUNTIME_ERROR,
                detail=f"runtime check raised {exc.__class__.__name__}: {exc}",
                module_path=info.module_path,
                exception_class=exc.__class__.__name__,
                exception_message=str(exc),
            )
        if not ok:
            return ProbeResult(
                key=info.key,
                state=EngineState.DEGRADED,
                detail=detail,
                pip_hint=info.pip_hint,
                module_path=info.module_path,
            )
        # Runtime check passed — fold its detail into the AVAILABLE message.
        return ProbeResult(
            key=info.key,
            state=EngineState.AVAILABLE,
            detail=f"available · {detail}",
            module_path=info.module_path,
        )

    return ProbeResult(
        key=info.key,
        state=EngineState.AVAILABLE,
        detail="available",
        module_path=info.module_path,
    )


def probe_all() -> List[ProbeResult]:
    """Probe every registered engine. Order matches registry insertion."""
    return [probe_engine(info) for info in ENGINE_DEPS.values()]


def probe_mode(mode_key: str) -> Optional[ProbeResult]:
    """Probe the engine bound to a scan-mode key. Returns ``None`` if unknown."""
    info = ENGINE_DEPS.get(mode_key)
    if info is None:
        return None
    return probe_engine(info)


# ---------------------------------------------------------------------------
# Cache invalidation helper (for "Retry" button)
# ---------------------------------------------------------------------------

def invalidate_module_cache(module_path: str) -> None:
    """Drop cached import state for a module and its submodules.

    Used by the Diagnostics "Retry" button so the user sees fresh results
    after running ``pip install <dep>`` in another terminal without having
    to restart the app. We can't re-try the full import if Python cached
    a failed import as ``None`` in ``sys.modules``, so wipe selectively.
    """
    import sys

    to_drop = [name for name in sys.modules if name == module_path or name.startswith(module_path + ".")]
    for name in to_drop:
        sys.modules.pop(name, None)
    # Reset importlib's finder caches so freshly-installed packages are discovered.
    importlib.invalidate_caches()


__all__ = [
    "EngineState",
    "EngineInfo",
    "ProbeResult",
    "ENGINE_DEPS",
    "probe_engine",
    "probe_all",
    "probe_mode",
    "invalidate_module_cache",
]
