# cerebro/ui/pages/history_page.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QFileDialog, QMessageBox, QProgressBar,
)

from cerebro.ui.components.modern import (
    HistoryCard,
    PageHeader,
    PageScaffold,
    StatCard,
)
from cerebro.ui.components.modern._tokens import token as theme_token
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.state_bus import get_state_bus


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


class ExportWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, file_path: str, fmt: str, limit: int = 10000, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._file_path = file_path
        self._fmt = fmt
        self._limit = limit

    def run(self) -> None:
        try:
            from cerebro.history.store import HistoryStore
            store = HistoryStore()
            path = Path(self._file_path)
            def prog(current: int, total: int) -> None:
                self.progress.emit(current, total)
            if self._fmt == "json":
                store.export_to_json(path, limit=self._limit, progress_cb=prog)
            else:
                store.export_to_csv(path, limit=self._limit, progress_cb=prog)
            self.finished.emit(self._file_path)
        except Exception as e:
            self.error.emit(str(e))


class VerifyWorker(QThread):
    finished = Signal(str)

    def __init__(self, record: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._record = record

    def run(self) -> None:
        details = self._record.get("details") or []
        missing = 0
        kept_ok = 0
        for d in details:
            path = d.get("path") or d.get("kept_path")
            if path and Path(path).exists():
                kept_ok += 1
            elif path:
                missing += 1
        msg = f"Paths checked: {len(details)}; still present: {kept_ok}; missing: {missing}"
        self.finished.emit(msg)


class HistoryPage(BaseStation):
    station_id = "history"
    station_title = "History"

    open_in_review_requested = Signal(dict)
    resume_scan_requested = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._bus = get_state_bus()
        self._items: List[Dict[str, Any]] = []
        self._export_worker: Optional[ExportWorker] = None
        self._verify_worker: Optional[VerifyWorker] = None
        self._drag_highlight = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=False)
        root.addWidget(self._scaffold)

        last_ts = ""
        self._header = PageHeader("History", last_ts or "Deletion audits. Export to JSON/CSV or verify paths.")
        self._scaffold.set_header(self._header)

        self._stat_deleted = StatCard("Total Deleted", "0", icon=None)
        self._stat_bytes = StatCard("Bytes Reclaimed", "0 B", icon=None)
        self._stat_rate = StatCard("Success Rate", "—", icon=None)
        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)
        stat_row.addWidget(self._stat_deleted)
        stat_row.addWidget(self._stat_bytes)
        stat_row.addWidget(self._stat_rate)

        toolbar_wrap = QWidget()
        tb_layout = QHBoxLayout(toolbar_wrap)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.setToolTip("Reload deletion history from store. Shows timeline of past cleanups.")
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.clicked.connect(self.refresh)
        self._export_btn = QPushButton("Export…")
        self._export_btn.setToolTip("Export history to JSON or CSV for backup or analysis.")
        self._export_btn.setCursor(Qt.PointingHandCursor)
        self._export_btn.clicked.connect(self._start_export)
        tb_layout.addWidget(self._refresh_btn)
        tb_layout.addWidget(self._export_btn)
        tb_layout.addStretch(1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)
        content_layout.addLayout(stat_row)
        content_layout.addWidget(toolbar_wrap)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        content_layout.addWidget(self._progress_bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("background: transparent;")
        self._cards_widget = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setAlignment(Qt.AlignTop)
        self._cards_layout.setSpacing(8)
        self._scroll.setWidget(self._cards_widget)
        content_layout.addWidget(self._scroll, 1)

        self._empty_label = QLabel("No deletion history yet.\nRun a scan and perform a cleanup to see audits here.")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {theme_token('muted')}; font-size: 14px; padding: 40px;")
        content_layout.addWidget(self._empty_label, 1)
        self._empty_label.setVisible(True)
        self._scroll.setVisible(False)

        self._scaffold.set_content(content)
        self.refresh()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drag_highlight = True
            self.setStyleSheet(f"border: 2px solid {theme_token('accent')}; border-radius: 12px;")

    def dropEvent(self, event: QDropEvent) -> None:
        self._drag_highlight = False
        self.setStyleSheet("")
        if event.mimeData() and event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self._bus.resume_scan_requested.emit({"root": path})
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drag_highlight = False
        self.setStyleSheet("")

    def ingest_scan_result(self, result: Dict[str, Any]) -> None:
        # Called by MainWindow best-effort
        item = {
            "when": result.get("timestamp") or "",
            "root": result.get("scan_root") or result.get("root") or "",
            "groups": len(result.get("groups") or []),
            "files": int(result.get("file_count", 0) or 0),
            "status": "completed",
            "payload": dict(result or {}),
            "terminated": bool(result.get("terminated", False) or result.get("cancelled", False)),
        }
        self._items.insert(0, item)
        self._render()

    def refresh(self) -> None:
        """Load real deletion history from HistoryStore (record_deletion)."""
        try:
            from cerebro.history.store import HistoryStore  # type: ignore
            store = HistoryStore()
            records = store.get_deletion_history(limit=200)
            self._items = []
            for r in records:
                when_str = datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d %H:%M") if r.timestamp else ""
                self._items.append({
                    "when": when_str,
                    "root": str(r.scan_id)[:32],
                    "groups": r.groups,
                    "files": r.deleted,
                    "failed": getattr(r, "failed", 0),
                    "bytes_reclaimed": getattr(r, "bytes_reclaimed", 0),
                    "mode": getattr(r, "mode", "trash"),
                    "status": f"{r.deleted} deleted, {r.failed} failed",
                    "payload": r.to_dict(),
                    "terminated": False,
                    "is_audit": True,
                })
        except Exception:
            self._items = []
        self._render()

    def _render(self) -> None:
        total_deleted = sum(item.get("files", 0) or 0 for item in self._items)
        total_bytes = sum(item.get("bytes_reclaimed", 0) or 0 for item in self._items)
        total_failed = sum(item.get("failed", 0) or 0 for item in self._items)
        denom = total_deleted + total_failed
        success_pct = f"{(100 * total_deleted / denom):.0f}%" if denom else "—"

        self._stat_deleted.set_value(str(total_deleted))
        self._stat_bytes.set_value(_fmt_bytes(total_bytes))
        self._stat_rate.set_value(success_pct)

        if self._items:
            self._header.set_subtitle(f"Last: {self._items[0].get('when', '')}" if self._items else "No audits yet.")
        self._empty_label.setVisible(not self._items)
        self._scroll.setVisible(bool(self._items))

        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        for item in self._items:
            ts = str(item.get("when", ""))[:22]
            mode = str(item.get("mode", "trash"))
            deleted = int(item.get("files", 0) or 0)
            failed = int(item.get("failed", 0) or 0)
            bytes_str = _fmt_bytes(int(item.get("bytes_reclaimed", 0) or 0))
            resumable = bool(item.get("terminated", False)) and not item.get("is_audit")
            card = HistoryCard(ts, mode, deleted, failed, bytes_str, resumable=resumable)
            payload = item.get("payload")

            def _open_bind(p):
                def _():
                    self._open(p)
                return _

            def _export_bind(p):
                def _():
                    self._export_one(p)
                return _

            def _resume_bind(p):
                def _():
                    self._resume(p)
                return _

            card.open_clicked.connect(_open_bind(payload))
            card.export_clicked.connect(_export_bind(payload))
            card.resume_clicked.connect(_resume_bind(payload))
            self._cards_layout.addWidget(card)

    def _open(self, payload: Dict[str, Any]) -> None:
        self._bus.notify("Opening", "Sending summary to Review…", 1400)
        # global bus route: review page will accept load_scan_result
        self._bus.scan_completed.emit(dict(payload or {}))

    def _resume(self, payload: Dict[str, Any]) -> None:
        self._bus.notify("Resume requested", "Opening Scan with last configuration…", 1800)
        self._bus.resume_scan_requested.emit(dict(payload or {}))

    def _start_export(self) -> None:
        path, selected = QFileDialog.getSaveFileName(
            self, "Export deletion history", "", "JSON (*.json);;CSV (*.csv);;All (*)"
        )
        if not path:
            return
        fmt = "json" if path.endswith(".json") or (selected and "JSON" in selected) else "csv"
        self._export_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)
        self._export_worker = ExportWorker(path, fmt, parent=self)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_progress(self, current: int, total: int) -> None:
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)

    def _on_export_finished(self, path: str) -> None:
        self._progress_bar.setVisible(False)
        self._export_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._export_worker = None
        self._bus.notify("Export done", f"Saved to {path}", 2500)

    def _on_export_error(self, err: str) -> None:
        self._progress_bar.setVisible(False)
        self._export_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._export_worker = None
        QMessageBox.warning(self, "Export failed", err)

    def _export_one(self, payload: Dict[str, Any]) -> None:
        """Export single record to user-chosen file (quick, no worker)."""
        if not payload:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export record", "", "JSON (*.json);;All (*)")
        if not path:
            return
        try:
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            self._bus.notify("Exported", path, 2000)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def _verify_one(self, payload: Dict[str, Any]) -> None:
        """Run verify worker for one record (path existence)."""
        if not payload:
            return
        if self._verify_worker and self._verify_worker.isRunning():
            return
        self._verify_worker = VerifyWorker(payload, parent=self)
        self._verify_worker.finished.connect(self._on_verify_finished)
        self._verify_worker.start()

    def _on_verify_finished(self, msg: str) -> None:
        self._verify_worker = None
        self._bus.notify("Verify", msg, 4000)

    def reset(self) -> None:
        """Clear internal state; disconnect running workers so no ghost signals."""
        if self._export_worker is not None:
            try:
                self._export_worker.progress.disconnect()
                self._export_worker.finished.disconnect()
                self._export_worker.error.disconnect()
            except Exception:
                pass
            self._export_worker = None
        if self._verify_worker is not None:
            try:
                self._verify_worker.finished.disconnect()
            except Exception:
                pass
            self._verify_worker = None
        self._progress_bar.setVisible(False)
        self._export_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._items = []
        self._render()

    def reset_for_new_scan(self) -> None:
        """No scan-specific state; history shows deletion audits."""
        pass
