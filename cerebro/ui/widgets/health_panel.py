# path: cerebro/ui/widgets/health_panel.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel


@dataclass(slots=True)
class HealthSnapshot:
    runtime_mode: str = "UI"
    pipeline_bound: bool = False
    session_bound: bool = False
    scanning: bool = False


class HealthPanel(QFrame):
    def __init__(self, parent=None, health: Optional[HealthSnapshot] = None):
        super().__init__(parent)

        self.setObjectName("HealthPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self._lbl_title = QLabel("System Health")
        self._lbl_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._lbl_title)

        self._lbl_mode = QLabel()
        self._lbl_pipeline = QLabel()
        self._lbl_session = QLabel()
        self._lbl_scan = QLabel()

        layout.addWidget(self._lbl_mode)
        layout.addWidget(self._lbl_pipeline)
        layout.addWidget(self._lbl_session)
        layout.addWidget(self._lbl_scan)

        self.update_health(health or HealthSnapshot())

    def update_health(self, health: HealthSnapshot) -> None:
        self._lbl_mode.setText(f"Mode: {health.runtime_mode}")
        self._lbl_pipeline.setText(f"Pipeline: {'OK' if health.pipeline_bound else '—'}")
        self._lbl_session.setText(f"Session: {'OK' if health.session_bound else '—'}")
        self._lbl_scan.setText(f"Scanning: {'YES' if health.scanning else 'NO'}")

    # Aliases used by MainWindow (compat)
    def set_snapshot(self, health: HealthSnapshot) -> None:
        self.update_health(health)

    def update_snapshot(self, health: HealthSnapshot) -> None:
        self.update_health(health)

    def set_health(self, health: HealthSnapshot) -> None:
        self.update_health(health)
