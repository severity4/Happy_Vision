"""tests/test_result_store.py"""

import json
from pathlib import Path

from modules.result_store import ResultStore


def test_init_creates_db(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    assert (tmp_path / "test.db").exists()
    store.close()


def test_save_and_get_result(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    result = {
        "title": "Speaker on stage",
        "description": "A speaker addresses the audience.",
        "keywords": ["conference", "speaker"],
        "category": "ceremony",
        "subcategory": "keynote",
        "scene_type": "indoor",
        "mood": "formal",
        "people_count": 50,
        "identified_people": ["Jensen Huang"],
        "ocr_text": ["INOUT"],
    }
    store.save_result("/photos/IMG_001.jpg", result)

    loaded = store.get_result("/photos/IMG_001.jpg")
    assert loaded["title"] == "Speaker on stage"
    assert loaded["keywords"] == ["conference", "speaker"]
    assert loaded["identified_people"] == ["Jensen Huang"]
    store.close()


def test_get_result_returns_none_for_missing(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    assert store.get_result("/no/such/file.jpg") is None
    store.close()


def test_is_processed(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    assert not store.is_processed("/photos/IMG_001.jpg")
    store.save_result("/photos/IMG_001.jpg", {"title": "Test"})
    assert store.is_processed("/photos/IMG_001.jpg")
    store.close()


def test_mark_failed(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.mark_failed("/photos/IMG_002.jpg", "API timeout")
    status = store.get_status("/photos/IMG_002.jpg")
    assert status == "failed"
    assert not store.is_processed("/photos/IMG_002.jpg")
    store.close()


def test_get_all_results(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/IMG_001.jpg", {"title": "A"})
    store.save_result("/photos/IMG_002.jpg", {"title": "B"})
    store.mark_failed("/photos/IMG_003.jpg", "error")

    results = store.get_all_results()
    assert len(results) == 2
    paths = [r["file_path"] for r in results]
    assert "/photos/IMG_001.jpg" in paths
    assert "/photos/IMG_002.jpg" in paths
    store.close()


def test_get_session_summary(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/IMG_001.jpg", {"title": "A"})
    store.save_result("/photos/IMG_002.jpg", {"title": "B"})
    store.mark_failed("/photos/IMG_003.jpg", "error")

    summary = store.get_summary()
    assert summary["completed"] == 2
    assert summary["failed"] == 1
    assert summary["total"] == 3
    store.close()


def test_update_result(tmp_path):
    """User edits a field in the UI before writing metadata."""
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/IMG_001.jpg", {"title": "Old", "keywords": ["a"]})
    store.update_result("/photos/IMG_001.jpg", {"title": "New Title"})
    loaded = store.get_result("/photos/IMG_001.jpg")
    assert loaded["title"] == "New Title"
    assert loaded["keywords"] == ["a"]  # unchanged
    store.close()


def test_context_manager(tmp_path):
    with ResultStore(tmp_path / "test.db") as store:
        store.save_result("/photos/IMG_001.jpg", {"title": "Test"})
        assert store.is_processed("/photos/IMG_001.jpg")
    # Connection should be closed after exiting context
    # Reopening should still work
    with ResultStore(tmp_path / "test.db") as store:
        assert store.get_result("/photos/IMG_001.jpg")["title"] == "Test"


def test_get_results_for_folder(tmp_path):
    with ResultStore(tmp_path / "test.db") as store:
        store.save_result("/photos/event_a/IMG_001.jpg", {"title": "A1"})
        store.save_result("/photos/event_a/IMG_002.jpg", {"title": "A2"})
        store.save_result("/photos/event_b/IMG_003.jpg", {"title": "B1"})
        store.mark_failed("/photos/event_a/IMG_004.jpg", "error")

        results_a = store.get_results_for_folder("/photos/event_a")
        assert len(results_a) == 2
        titles = {r["title"] for r in results_a}
        assert titles == {"A1", "A2"}

        results_b = store.get_results_for_folder("/photos/event_b")
        assert len(results_b) == 1
        assert results_b[0]["title"] == "B1"


def test_wal_mode_enabled(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    store.close()


def test_index_exists(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    rows = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='results'"
    ).fetchall()
    index_names = {r["name"] for r in rows}
    assert "idx_results_status" in index_names
    assert "idx_results_updated_at" in index_names
    store.close()


def test_concurrent_writes_do_not_deadlock(tmp_path):
    """Two threads saving results simultaneously must not raise OperationalError."""
    import threading
    store = ResultStore(tmp_path / "test.db")
    errors = []

    def writer(prefix):
        try:
            for i in range(50):
                store.save_result(f"/photos/{prefix}_{i:03d}.jpg", {"title": f"{prefix}{i}"})
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=writer, args=("A",))
    t2 = threading.Thread(target=writer, args=("B",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == []
    results = store.get_all_results()
    assert len(results) == 100
    store.close()
