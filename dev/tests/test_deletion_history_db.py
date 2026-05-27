from cerebro.v2.core.deletion_history_db import HistoryManager


def test_deletion_history_round_trip(tmp_path):
    db_file = tmp_path / "deletion_history.db"
    mgr = HistoryManager(str(db_file))
    assert mgr.log_deletion("C:/tmp/a.jpg", 1234, "photos")
    assert mgr.log_deletion("C:/tmp/b.jpg", 5678, "photos")

    rows = mgr.get_recent_history(limit=10)
    assert len(rows) == 2
    assert rows[0][1] in {"a.jpg", "b.jpg"}
    assert any(r[2].endswith("a.jpg") for r in rows)


def test_deletion_history_search_and_clear(tmp_path):
    db_file = tmp_path / "deletion_history.db"
    mgr = HistoryManager(str(db_file))
    mgr.log_deletion("/tmp/music.mp3", 1, "music")
    mgr.log_deletion("/tmp/image.png", 1, "photos")

    found = mgr.search_history("music")
    assert len(found) == 1
    assert found[0][1] == "music.mp3"

    assert mgr.clear_history()
    assert mgr.get_recent_history(limit=10) == []
