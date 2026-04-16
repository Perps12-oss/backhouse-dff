from pathlib import Path

from cerebro.core.preview import PreviewManager


def test_preview_file_missing_returns_false(tmp_path, monkeypatch):
    mgr = PreviewManager()
    missing = tmp_path / "nope.txt"

    called = {"run": 0, "startfile": 0}

    def _fake_run(*_a, **_kw):
        called["run"] += 1
        raise AssertionError("subprocess.run should not be called for missing path")

    def _fake_startfile(*_a, **_kw):
        called["startfile"] += 1
        raise AssertionError("os.startfile should not be called for missing path")

    import cerebro.core.preview as preview_mod

    monkeypatch.setattr(preview_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(preview_mod.os, "startfile", _fake_startfile, raising=True)

    assert mgr.preview_file(missing) is False
    assert called["run"] == 0
    assert called["startfile"] == 0


def test_preview_file_uses_safe_subprocess_on_macos(tmp_path, monkeypatch):
    mgr = PreviewManager()
    p = tmp_path / "file.txt"
    p.write_text("x", encoding="utf-8")

    import cerebro.core.preview as preview_mod

    monkeypatch.setattr(preview_mod.platform, "system", lambda: "Darwin")

    seen = {}

    def _fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return None

    monkeypatch.setattr(preview_mod.subprocess, "run", _fake_run)

    assert mgr.preview_file(p) is True
    assert seen["args"] == ["open", str(p)]
    assert seen["kwargs"].get("shell") is False


def test_preview_file_uses_os_startfile_on_windows(tmp_path, monkeypatch):
    mgr = PreviewManager()
    p = tmp_path / "file.txt"
    p.write_text("x", encoding="utf-8")

    import cerebro.core.preview as preview_mod

    monkeypatch.setattr(preview_mod.platform, "system", lambda: "Windows")

    seen = {"path": None}

    def _fake_startfile(arg):
        seen["path"] = arg
        return None

    monkeypatch.setattr(preview_mod.os, "startfile", _fake_startfile, raising=True)

    assert mgr.preview_file(p) is True
    assert seen["path"] == str(p)


def test_preview_file_uses_safe_subprocess_on_linux(tmp_path, monkeypatch):
    mgr = PreviewManager()
    p = tmp_path / "file.txt"
    p.write_text("x", encoding="utf-8")

    import cerebro.core.preview as preview_mod

    monkeypatch.setattr(preview_mod.platform, "system", lambda: "Linux")

    seen = {}

    def _fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return None

    monkeypatch.setattr(preview_mod.subprocess, "run", _fake_run)

    assert mgr.preview_file(p) is True
    assert seen["args"] == ["xdg-open", str(p)]
    assert seen["kwargs"].get("shell") is False
