from pathlib import Path

from cerebro.core.deletion import DeletionEngine, DeletionPolicy, DeletionRequest


def test_deletion_engine_permanent_deletes_file(tmp_path: Path):
    p = tmp_path / "to_delete.txt"
    p.write_text("x", encoding="utf-8")
    assert p.exists()

    engine = DeletionEngine()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT, metadata={"test": True})
    res = engine.delete_one(p, req)

    assert res.success is True
    assert p.exists() is False


def test_deletion_engine_trash_missing_file_reports_error(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    assert missing.exists() is False

    engine = DeletionEngine()
    req = DeletionRequest(policy=DeletionPolicy.TRASH, metadata={"test": True})
    res = engine.delete_one(missing, req)

    assert res.success is False
    assert res.error == "File does not exist"
