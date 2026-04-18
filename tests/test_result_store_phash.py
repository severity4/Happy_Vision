"""tests/test_result_store_phash.py — v0.6.0 pHash migration + find_similar"""

import pytest

from modules.result_store import ResultStore


RESULT_SAMPLE = {
    "title": "T",
    "description": "",
    "keywords": [],
    "category": "other",
    "scene_type": "indoor",
    "mood": "neutral",
    "people_count": 0,
}


def test_phash_columns_added_by_migration(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    cols = {row[1] for row in store.conn.execute("PRAGMA table_info(results)").fetchall()}
    assert "phash" in cols
    assert "duplicate_of" in cols
    store.close()


def test_phash_index_created(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    indices = [
        row[0] for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='results'"
        ).fetchall()
    ]
    assert "idx_results_phash" in indices
    store.close()


def test_save_result_persists_phash_and_duplicate_of(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result(
        "/photos/A.jpg", RESULT_SAMPLE,
        phash="8000000000000000",
    )
    store.save_result(
        "/photos/B.jpg", RESULT_SAMPLE,
        phash="8000000000000001",
        duplicate_of="/photos/A.jpg",
    )
    row_a = store.conn.execute(
        "SELECT phash, duplicate_of FROM results WHERE file_path = ?",
        ("/photos/A.jpg",),
    ).fetchone()
    row_b = store.conn.execute(
        "SELECT phash, duplicate_of FROM results WHERE file_path = ?",
        ("/photos/B.jpg",),
    ).fetchone()
    assert row_a["phash"] == "8000000000000000"
    assert row_a["duplicate_of"] is None
    assert row_b["phash"] == "8000000000000001"
    assert row_b["duplicate_of"] == "/photos/A.jpg"
    store.close()


def test_find_similar_returns_closest_within_threshold(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    # A is exact match to the query; B is 2 bits away; C is 63 bits away.
    # Threshold 5 pulls in A and B but A is strictly closer.
    store.save_result("/photos/A.jpg", RESULT_SAMPLE, phash="8000000000000001")
    store.save_result("/photos/B.jpg", RESULT_SAMPLE, phash="8000000000000007")
    store.save_result("/photos/C.jpg", RESULT_SAMPLE, phash="ffffffffffffffff")
    match = store.find_similar("8000000000000001", threshold=5)
    assert match is not None
    assert match["file_path"] == "/photos/A.jpg"
    assert match["distance"] == 0
    store.close()


def test_find_similar_returns_none_when_all_beyond_threshold(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/A.jpg", RESULT_SAMPLE, phash="ffffffffffffffff")
    assert store.find_similar("0000000000000000", threshold=5) is None
    store.close()


def test_find_similar_ignores_rows_without_phash(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/legacy.jpg", RESULT_SAMPLE)  # no phash
    assert store.find_similar("8000000000000000", threshold=5) is None
    store.close()


def test_find_similar_follows_duplicate_of_to_master(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    # A is the master; B was saved as a duplicate of A. A new query that
    # matches B should resolve back to A so we don't chain dup-of-dup.
    store.save_result("/photos/A.jpg", RESULT_SAMPLE, phash="8000000000000000")
    store.save_result(
        "/photos/B.jpg", {**RESULT_SAMPLE, "title": "B"},
        phash="8000000000000003", duplicate_of="/photos/A.jpg",
    )
    # Query something very close to B; should resolve to A
    match = store.find_similar("8000000000000003", threshold=5)
    assert match is not None
    assert match["file_path"] == "/photos/A.jpg"
    store.close()


def test_get_result_with_usage_surfaces_dedup(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result(
        "/photos/B.jpg", RESULT_SAMPLE,
        phash="8000000000000001", duplicate_of="/photos/A.jpg",
    )
    out = store.get_result_with_usage("/photos/B.jpg")
    assert out is not None
    assert "_dedup" in out
    assert out["_dedup"]["phash"] == "8000000000000001"
    assert out["_dedup"]["duplicate_of"] == "/photos/A.jpg"
    store.close()


def test_get_today_stats_counts_duplicates(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/A.jpg", RESULT_SAMPLE, phash="8000000000000000")
    store.save_result("/photos/B.jpg", RESULT_SAMPLE,
                      phash="8000000000000001", duplicate_of="/photos/A.jpg")
    store.save_result("/photos/C.jpg", RESULT_SAMPLE,
                      phash="8000000000000002", duplicate_of="/photos/A.jpg")
    stats = store.get_today_stats()
    assert stats["completed_today"] == 3
    assert stats["dedup_saved_today"] == 2  # B and C are dupes
    store.close()
