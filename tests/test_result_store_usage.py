"""tests/test_result_store_usage.py — v0.5.0 tokens/cost migration + persistence"""

import sqlite3

from modules.result_store import ResultStore


RESULT_SAMPLE = {
    "title": "Keynote",
    "description": "A speaker addresses the audience.",
    "keywords": ["speaker"],
    "category": "ceremony",
    "scene_type": "indoor",
    "mood": "formal",
    "people_count": 50,
}

USAGE_SAMPLE = {
    "input_tokens": 3800,
    "output_tokens": 420,
    "total_tokens": 4220,
    "model": "gemini-2.5-flash-lite",
}


def test_migration_adds_usage_columns(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    cols = {row[1] for row in store.conn.execute("PRAGMA table_info(results)").fetchall()}
    for expected in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "model"):
        assert expected in cols, f"missing column {expected}"
    store.close()


def test_migration_idempotent_on_reopen(tmp_path):
    p = tmp_path / "test.db"
    store1 = ResultStore(p)
    store1.close()
    # Reopen — ALTER TABLE should silently no-op instead of raising
    store2 = ResultStore(p)
    cols = {row[1] for row in store2.conn.execute("PRAGMA table_info(results)").fetchall()}
    assert "input_tokens" in cols
    store2.close()


def test_save_with_usage_persists_cost_columns(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/A.jpg", RESULT_SAMPLE, usage=USAGE_SAMPLE, cost_usd=0.000548)
    row = store.conn.execute(
        "SELECT input_tokens, output_tokens, total_tokens, cost_usd, model "
        "FROM results WHERE file_path = ?",
        ("/photos/A.jpg",),
    ).fetchone()
    assert row["input_tokens"] == 3800
    assert row["output_tokens"] == 420
    assert row["total_tokens"] == 4220
    assert abs(row["cost_usd"] - 0.000548) < 1e-9
    assert row["model"] == "gemini-2.5-flash-lite"
    store.close()


def test_save_without_usage_accepts_none(tmp_path):
    # Back-compat: callers that don't pass usage should still work (e.g., the
    # external-IPTC shortcut in folder_watcher.py)
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/B.jpg", RESULT_SAMPLE)
    row = store.conn.execute(
        "SELECT input_tokens, cost_usd FROM results WHERE file_path = ?",
        ("/photos/B.jpg",),
    ).fetchone()
    assert row["input_tokens"] is None
    assert row["cost_usd"] is None
    store.close()


def test_get_result_with_usage_returns_usage_dict(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/A.jpg", RESULT_SAMPLE, usage=USAGE_SAMPLE, cost_usd=0.000548)
    out = store.get_result_with_usage("/photos/A.jpg")
    assert out is not None
    assert out["title"] == "Keynote"
    assert "_usage" in out
    assert out["_usage"]["input_tokens"] == 3800
    assert out["_usage"]["cost_usd"] == 0.000548
    assert out["_usage"]["model"] == "gemini-2.5-flash-lite"
    store.close()


def test_get_result_with_usage_omits_usage_for_legacy_rows(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/legacy.jpg", RESULT_SAMPLE)  # no usage
    out = store.get_result_with_usage("/photos/legacy.jpg")
    assert out is not None
    assert "_usage" not in out, "legacy rows without tokens should omit _usage"
    store.close()


def test_get_today_stats_includes_cost(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/A.jpg", RESULT_SAMPLE, usage=USAGE_SAMPLE, cost_usd=0.001)
    store.save_result("/photos/B.jpg", RESULT_SAMPLE, usage=USAGE_SAMPLE, cost_usd=0.002)
    stats = store.get_today_stats()
    assert stats["completed_today"] == 2
    assert abs(stats["cost_usd_today"] - 0.003) < 1e-9
    store.close()


def test_get_today_stats_with_no_cost_data(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/legacy.jpg", RESULT_SAMPLE)
    stats = store.get_today_stats()
    assert stats["completed_today"] == 1
    assert stats["cost_usd_today"] == 0.0  # SUM over NULL = 0 via COALESCE
    store.close()


def test_results_for_folder_includes_usage(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/wedding/A.jpg", RESULT_SAMPLE, usage=USAGE_SAMPLE, cost_usd=0.001)
    results = store.get_results_for_folder("/photos/wedding")
    assert len(results) == 1
    assert results[0]["_usage"]["input_tokens"] == 3800
    assert results[0]["updated_at"]  # also surfaced for PDF sort
    store.close()
