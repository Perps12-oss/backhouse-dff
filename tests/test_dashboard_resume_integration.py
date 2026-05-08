from __future__ import annotations

import json
from pathlib import Path

import flet as ft

from cerebro.v2.ui.flet_app.pages.dashboard_page import DashboardPage


class _FakeBridge:
    def __init__(self) -> None:
        self.dialog_dismissed = False
        self.snackbar_messages: list[str] = []

    def dismiss_top_dialog(self) -> None:
        self.dialog_dismissed = True

    def show_snackbar(self, message: str, info: bool = False) -> None:
        self.snackbar_messages.append(message)


def _make_resume_page(bridge: _FakeBridge) -> DashboardPage:
    page = DashboardPage.__new__(DashboardPage)
    page._bridge = bridge
    page._folders = []
    page._selected_mode = "files"
    page._scan_options = {
        "scan_archives": False,
        "min_size_bytes": 0,
        "exclude_paths": [],
        "include_subfolders": True,
    }
    page._min_size_slider = ft.Slider(value=0)
    page._min_size_label = ft.Text(value="")
    page._exclude_paths_tf = ft.TextField(value="")
    page._scan_archives_cb = ft.Checkbox(value=False)
    page._archives_warning = ft.Text(value="")
    page._archives_warning.visible = False
    page._include_subfolders_sw = ft.Switch(value=True)
    page._refresh_folder_chips = lambda: None
    page._update_modes_ui = lambda: None
    page._begin_scan_called = False
    page._begin_scan = lambda: setattr(page, "_begin_scan_called", True)
    page._clear_incomplete_scan_session_called = False
    page._clear_incomplete_scan_session = lambda: setattr(page, "_clear_incomplete_scan_session_called", True)
    return page


def test_cancel_resume_restores_multi_folder_mode_and_options(tmp_path: Path, monkeypatch) -> None:
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"
    folder_a.mkdir()
    folder_b.mkdir()

    snapshot_path = tmp_path / "incomplete_scan.json"
    monkeypatch.setattr(
        "cerebro.v2.ui.flet_app.pages.dashboard_page._INCOMPLETE_SCAN_PATH",
        snapshot_path,
    )

    page_before = DashboardPage.__new__(DashboardPage)
    page_before._folders = [folder_a, folder_b]
    page_before._selected_mode = "photos"
    page_before._scan_options = {
        "scan_archives": True,
        "min_size_bytes": 10 * 1024 * 1024,
        "exclude_paths": [str(folder_a / "skip"), str(folder_b / "cache")],
        "include_subfolders": False,
    }
    page_before._persist_incomplete_scan_session(status="cancelled")

    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
    page_after = _make_resume_page(_FakeBridge())
    page_after._resume_incomplete_scan(persisted)

    assert page_after._folders == [folder_a, folder_b]
    assert page_after._selected_mode == "photos"
    assert page_after._scan_options["scan_archives"] is True
    assert page_after._scan_options["min_size_bytes"] == 10 * 1024 * 1024
    assert page_after._scan_options["exclude_paths"] == [str(folder_a / "skip"), str(folder_b / "cache")]
    assert page_after._scan_options["include_subfolders"] is False

    assert int(page_after._min_size_slider.value) == 10
    assert page_after._exclude_paths_tf.value == f"{folder_a / 'skip'}\n{folder_b / 'cache'}"
    assert page_after._scan_archives_cb.value is True
    assert page_after._archives_warning.visible is True
    assert page_after._include_subfolders_sw.value is False
    assert page_after._begin_scan_called is True
