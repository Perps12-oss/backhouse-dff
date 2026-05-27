from cerebro.v2.core.scan_history_db import ScanHistoryDB


def test_scan_history_record_and_read(tmp_path):
    db_file = tmp_path / "scan_history.db"
    db = ScanHistoryDB(db_file)
    db.record_scan(
        mode="files",
        folders=["/tmp/a", "/tmp/b"],
        groups_found=3,
        files_found=9,
        bytes_reclaimable=1000,
        duration_seconds=4.2,
        timestamp=100.0,
    )
    rows = db.get_recent(limit=5)
    assert len(rows) == 1
    row = rows[0]
    assert row.mode == "files"
    assert row.folders == ["/tmp/a", "/tmp/b"]
    assert row.groups_found == 3


def test_scan_history_clear(tmp_path):
    db = ScanHistoryDB(tmp_path / "scan_history.db")
    db.record_scan("files", [], 0, 0, 0, 0.1)
    assert len(db.get_recent()) == 1
    db.clear()
    assert db.get_recent() == []
