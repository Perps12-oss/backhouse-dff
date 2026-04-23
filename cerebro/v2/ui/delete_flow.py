"""
delete_flow — the shared 4-step delete ceremony used by both Results and
Review pages.

Originally lived as a private method on ``ResultsPage``. Extracted here
during the Phase-6 course-correction (Results → Review split) so Review's
Smart-Select path can reuse the exact same ceremony without cross-importing
ResultsPage internals.

Public API:
    run_delete_ceremony(
        parent,           # any Tk widget on the page invoking the flow
        items,            # List[DeleteItem] — path string + byte size
        scan_mode,        # "files" | "photos" | "videos" | "music" — for
                          # the media-noun labels in the dialogs
        on_remove_paths,  # Callable[[Set[str]], None] — page prunes its
                          # own state for the successfully deleted paths
        on_navigate_home, # Callable[[], None] or None — Step-5 celebration
        on_rescan,        # Callable[[], None] or None — Step-4 "Rescan"
        source_tag,       # free-form source label for DeletionEngine
                          # metadata / deletion-history DB
    ) -> DeleteCeremonyResult

The function blocks on a nested event loop while the progress dialog runs
(same nested event-loop pattern as the original single-window delete flow). It's safe to call from a Tk
event handler. It must NOT be called from a worker thread.

What this does NOT do:
  - mutate the page's internal row lists or group lists (that's the
    caller's job via ``on_remove_paths``)
  - fire <<CheckChanged>> — ditto
  - handle the empty-input case — caller should early-return before
    reaching here

See also:
  - cerebro.v2.ui.delete_ceremony_widgets — modal classes and helpers
    (lazy-imported when ``run_delete_ceremony`` runs).
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox
from typing import Callable, List, Optional, Set

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeleteItem:
    """One file slated for deletion.

    ``path_str`` is kept as a raw string (not a ``Path``) because it also
    serves as the identity key the caller uses for its internal row list —
    calling ``Path.resolve()`` on Windows can shift slash style or drive
    letter case and then the prune step drops the wrong row.
    """
    path_str: str
    size:     int


@dataclass
class DeleteCeremonyResult:
    """Return value of ``run_delete_ceremony``. Populated regardless of
    which branch the user took (cancel / rescan / celebrate / partial
    failure) so the caller can decide its own follow-up."""
    cancelled:         bool           = False
    cancelled_at_step: Optional[int]  = None   # 1 or 2 if cancelled
    success_count:     int            = 0
    recovered_bytes:   int            = 0
    deleted_paths:     List[str]      = field(default_factory=list)
    failed:            List[tuple]    = field(default_factory=list)
    chose_rescan:      bool           = False


def run_delete_ceremony(
    parent:           tk.Widget,
    items:            List[DeleteItem],
    scan_mode:        str,
    on_remove_paths:  Callable[[Set[str]], None],
    on_navigate_home: Optional[Callable[[], None]] = None,
    on_rescan:        Optional[Callable[[], None]] = None,
    source_tag:       str = "delete_flow",
) -> DeleteCeremonyResult:
    """Run the 4-step ceremony and return what happened.

    Flow (unchanged from the original Results-page delete implementation):
        Step 1 — "Are you sure?"                  Cancel / Confirm
        Step 2 — breakdown + Recycle Bin notice   Cancel / Allow
        Step 3 — progress dialog + worker thread  (non-cancellable)
        Step 4 — summary                          Rescan / OK
        Step 5 — celebration overlay → on_navigate_home()

    After step 3 succeeds (i.e. any file deleted), the floating Undo
    toast is shown bottom-right of the parent's toplevel.
    """
    result = DeleteCeremonyResult()

    if not items:
        return result

    try:
        from cerebro.v2.ui.delete_ceremony_widgets import (
            _DeleteDialog, _DeleteProgressDialog, _DeleteSummaryDialog,
            _DeleteCelebration, _UndoToast,
            _delete_media_label, _delete_breakdown,
        )
        from cerebro.v2.core.deletion_history_db import log_deletion_event
    except ImportError:
        _log.exception("Delete ceremony unavailable — delete_ceremony_widgets import failed")
        return result

    try:
        from cerebro.utils.formatting import format_bytes
    except ImportError:
        format_bytes = None    # type: ignore[assignment]

    count = len(items)
    noun  = _delete_media_label(scan_mode)

    # -- Step 1 -------------------------------------------------------
    d1 = _DeleteDialog(
        parent,
        title="Delete Confirmation",
        icon="⚠",
        headline=f"Delete {count} {noun}?",
        body=(
            f"You're about to delete {count} {noun}. This action will move "
            "the files to your system's Recycle Bin.\n\n"
            "Once you move them, you can restore from the Recycle Bin if "
            "you change your mind."
        ),
        btn_cancel="Cancel",
        btn_confirm="Confirm",
        confirm_dangerous=True,
    )
    if not d1.result:
        result.cancelled = True
        result.cancelled_at_step = 1
        return result

    # -- Step 2 -------------------------------------------------------
    # Build the breakdown strings the legacy flow uses.
    # `_delete_breakdown` needs a row-like object; the tuples here cover
    # the fields it reads (extension / size).
    breakdown_rows = [
        {
            "extension": Path(it.path_str).suffix.lower(),
            "size":      it.size,
            "path":      it.path_str,
        }
        for it in items
    ]
    breakdown = _delete_breakdown(breakdown_rows, noun)
    reclaimable = sum(it.size for it in items)
    reclaimable_str = (
        format_bytes(reclaimable, decimals=1) if format_bytes
        else f"{reclaimable} bytes"
    )

    d2 = _DeleteDialog(
        parent,
        title="Move to Recycle Bin",
        icon="♻",
        headline="Moving to Recycle Bin",
        body=(
            f"{breakdown} will be moved to the Recycle Bin.\n\n"
            f"Estimated space freed: {reclaimable_str}"
        ),
        btn_cancel="Cancel",
        btn_confirm="Allow",
        confirm_dangerous=False,
    )
    if not d2.result:
        result.cancelled = True
        result.cancelled_at_step = 2
        return result

    # -- Step 3 -------------------------------------------------------
    prog = _DeleteProgressDialog(parent, total=count)

    def _worker() -> None:
        try:
            from cerebro.core.deletion import (
                DeletionEngine, DeletionPolicy, DeletionRequest,
            )
        except ImportError:
            DeletionEngine  = None   # type: ignore[assignment]
            DeletionPolicy  = None   # type: ignore[assignment]
            DeletionRequest = None   # type: ignore[assignment]

        engine  = DeletionEngine() if DeletionEngine else None
        request = (
            DeletionRequest(
                policy=DeletionPolicy.TRASH,
                metadata={"source": source_tag, "mode": "trash"},
            )
            if (DeletionRequest and DeletionPolicy) else None
        )
        try:
            import send2trash
        except ImportError:
            send2trash = None    # type: ignore[assignment]

        for i, it in enumerate(items):
            row_key = it.path_str
            size    = int(it.size or 0)
            try:
                fp = Path(row_key).resolve()
            except (OSError, ValueError):
                fp = Path(row_key)

            def _mark_ok() -> None:
                result.success_count      += 1
                result.recovered_bytes    += size
                result.deleted_paths.append(row_key)
                try:
                    log_deletion_event(str(fp), size, scan_mode)
                except (OSError, ValueError, RuntimeError):
                    _log.exception("log_deletion_event failed for %s", fp)

            try:
                if engine and request:
                    res = engine.delete_one(fp, request)
                    if getattr(res, "success", False):
                        _mark_ok()
                    else:
                        result.failed.append(
                            (str(fp),
                             getattr(res, "error", None) or "Unknown error")
                        )
                elif send2trash is not None:
                    send2trash.send2trash(str(fp))
                    _mark_ok()
                else:
                    result.failed.append(
                        (str(fp), "deletion backend unavailable")
                    )
            except (OSError, ValueError, RuntimeError, AttributeError,
                    TypeError, KeyError, ImportError) as exc:
                result.failed.append((str(fp), str(exc)))

            parent.after(0, lambda done=i + 1: prog.set_progress(done))

        parent.after(0, prog.close)

    threading.Thread(target=_worker, daemon=True,
                     name=f"delete-ceremony-{source_tag}").start()
    prog.wait()   # nested event loop — exits when worker calls prog.close()

    # -- Post-worker: prune caller state + Undo toast ----------------
    if result.deleted_paths:
        try:
            on_remove_paths(set(result.deleted_paths))
        except Exception:   # pylint: disable=broad-except
            _log.exception("on_remove_paths callback raised")

        try:
            size_str = (format_bytes(result.recovered_bytes, decimals=1)
                        if format_bytes else f"{result.recovered_bytes} bytes")
            _UndoToast(
                parent.winfo_toplevel(),
                count=len(result.deleted_paths),
                size_str=size_str,
                deleted_paths=list(result.deleted_paths),
            )
        except Exception:   # pylint: disable=broad-except
            _log.debug("Undo toast unavailable — skipping", exc_info=True)

    # -- Partial failure → warning, skip summary/celebration ---------
    if result.failed:
        head = "\n".join(
            f"  • {Path(f).name}: {e}" for f, e in result.failed[:5]
        )
        more = (
            f"\n  … and {len(result.failed) - 5} more"
            if len(result.failed) > 5 else ""
        )
        messagebox.showwarning(
            "Deletion Partial",
            f"Deleted {result.success_count} of {count} {noun}.\n\n"
            f"Failed:\n{head}{more}",
            parent=parent,
        )
        return result

    # -- Step 4 — summary --------------------------------------------
    d4 = _DeleteSummaryDialog(
        parent, noun=noun,
        count=result.success_count,
        recovered=result.recovered_bytes,
    )

    if d4.result == "rescan":
        result.chose_rescan = True
        if on_rescan:
            try:
                on_rescan()
            except Exception:   # pylint: disable=broad-except
                _log.exception("on_rescan callback raised")
        return result

    # -- Step 5 — celebration overlay --------------------------------
    def _done() -> None:
        if on_navigate_home:
            try:
                on_navigate_home()
            except Exception:   # pylint: disable=broad-except
                _log.exception("on_navigate_home callback raised")

    _DeleteCelebration(parent, noun=noun, on_done=_done)
    return result
