"""tests/test_folder_watcher_dedup.py — v0.6.0 watcher pre-analyze dedup"""

import time
from unittest.mock import MagicMock

import pytest
from PIL import Image

from modules import folder_watcher as fw
from modules.folder_watcher import FolderWatcher, WatcherCallbacks
from modules.result_store import ResultStore


_ANALYSIS_STUB = {
    "title": "T", "keywords": [], "description": "",
    "category": "other", "scene_type": "indoor",
    "mood": "neutral", "people_count": 0,
}
_USAGE_STUB = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
               "model": "gemini-2.5-flash-lite"}


def _make_jpg(path, color=(128, 128, 128), noise_seed=None):
    """Create a JPEG. When noise_seed is set, each (x,y) pixel gets a unique
    shift so two images with the same seed are byte-identical, and two with
    different seeds have very different brightness patterns (distinct dhash)."""
    img = Image.new("RGB", (300, 300), color=color)
    if noise_seed is not None:
        import random
        rng = random.Random(noise_seed)
        pixels = img.load()
        for x in range(300):
            for y in range(300):
                shift = rng.randint(-80, 80)
                c = tuple(max(0, min(255, v + shift)) for v in color)
                pixels[x, y] = c
    img.save(str(path), "JPEG", quality=90)


def _common_mocks(monkeypatch, tmp_path, analyze_calls, phash_threshold=5):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))
    monkeypatch.setattr(
        fw, "analyze_photo",
        lambda path, **kw: (analyze_calls.append(path) or (_ANALYSIS_STUB, _USAGE_STUB)),
    )
    monkeypatch.setattr(fw, "has_happy_vision_tag", lambda p: False)
    monkeypatch.setattr(fw, "file_size_stable", lambda p, **kw: True)
    monkeypatch.setattr(
        fw, "load_config",
        lambda: {
            "gemini_api_key": "k",
            "watch_concurrency": 1,
            "watch_interval": 1,
            "model": "lite",
            "image_max_size": 3072,
            "phash_threshold": phash_threshold,
        },
    )


def test_second_similar_photo_is_deduped(tmp_path, monkeypatch):
    """Processing a near-duplicate after the master should skip analyze_photo."""
    photo_a = tmp_path / "a.jpg"
    photo_b = tmp_path / "b.jpg"
    _make_jpg(photo_a, noise_seed=42)
    _make_jpg(photo_b, noise_seed=42)  # identical seed -> identical pHash

    analyze_calls = []
    _common_mocks(monkeypatch, tmp_path, analyze_calls, phash_threshold=5)

    # Fake exiftool batch that always succeeds
    monkeypatch.setattr(fw, "ExiftoolBatch",
                        lambda: type("B", (), {"write": lambda s, p, a: True,
                                               "close": lambda s: None})())

    watcher = FolderWatcher(WatcherCallbacks())
    watcher._folder = str(tmp_path)
    watcher._store = ResultStore(tmp_path / "test.db")
    watcher._batch = type("B", (), {"write": lambda s, p, a: True,
                                    "close": lambda s: None})()

    watcher._process_one(str(photo_a))
    watcher._process_one(str(photo_b))

    assert len(analyze_calls) == 1, (
        f"Expected dedup to skip second analyze, got {len(analyze_calls)} calls"
    )

    # B should be saved with duplicate_of pointing to A
    row_b = watcher._store.conn.execute(
        "SELECT phash, duplicate_of FROM results WHERE file_path = ?",
        (str(photo_b),),
    ).fetchone()
    assert row_b is not None
    assert row_b["phash"] is not None
    assert row_b["duplicate_of"] == str(photo_a)
    watcher._store.close()


def test_distinct_photos_both_analyzed(tmp_path, monkeypatch):
    photo_a = tmp_path / "a.jpg"
    photo_b = tmp_path / "b.jpg"
    _make_jpg(photo_a, color=(220, 40, 40), noise_seed=1)
    _make_jpg(photo_b, color=(40, 40, 220), noise_seed=2)

    analyze_calls = []
    _common_mocks(monkeypatch, tmp_path, analyze_calls, phash_threshold=5)
    monkeypatch.setattr(fw, "ExiftoolBatch",
                        lambda: type("B", (), {"write": lambda s, p, a: True,
                                               "close": lambda s: None})())

    watcher = FolderWatcher(WatcherCallbacks())
    watcher._folder = str(tmp_path)
    watcher._store = ResultStore(tmp_path / "test.db")
    watcher._batch = type("B", (), {"write": lambda s, p, a: True,
                                    "close": lambda s: None})()

    watcher._process_one(str(photo_a))
    watcher._process_one(str(photo_b))

    assert len(analyze_calls) == 2, "Distinct photos should both hit Gemini"
    # Neither should be saved as a duplicate
    rows = watcher._store.conn.execute(
        "SELECT file_path, duplicate_of FROM results WHERE status = 'completed'"
    ).fetchall()
    for r in rows:
        assert r["duplicate_of"] is None
    watcher._store.close()


def test_threshold_zero_disables_dedup(tmp_path, monkeypatch):
    """phash_threshold=0 must never dedup even when photos are identical."""
    photo_a = tmp_path / "a.jpg"
    photo_b = tmp_path / "b.jpg"
    _make_jpg(photo_a, noise_seed=99)
    _make_jpg(photo_b, noise_seed=99)  # identical

    analyze_calls = []
    _common_mocks(monkeypatch, tmp_path, analyze_calls, phash_threshold=0)
    monkeypatch.setattr(fw, "ExiftoolBatch",
                        lambda: type("B", (), {"write": lambda s, p, a: True,
                                               "close": lambda s: None})())

    watcher = FolderWatcher(WatcherCallbacks())
    watcher._folder = str(tmp_path)
    watcher._store = ResultStore(tmp_path / "test.db")
    watcher._batch = type("B", (), {"write": lambda s, p, a: True,
                                    "close": lambda s: None})()

    watcher._process_one(str(photo_a))
    watcher._process_one(str(photo_b))

    assert len(analyze_calls) == 2, "threshold=0 must not dedup"
    watcher._store.close()


def test_dedup_saves_phash_on_master(tmp_path, monkeypatch):
    """When a photo IS analyzed (not a dup), its phash should be stored for
    future dedup lookups."""
    photo = tmp_path / "a.jpg"
    _make_jpg(photo, noise_seed=7)

    analyze_calls = []
    _common_mocks(monkeypatch, tmp_path, analyze_calls, phash_threshold=5)
    monkeypatch.setattr(fw, "ExiftoolBatch",
                        lambda: type("B", (), {"write": lambda s, p, a: True,
                                               "close": lambda s: None})())

    watcher = FolderWatcher(WatcherCallbacks())
    watcher._folder = str(tmp_path)
    watcher._store = ResultStore(tmp_path / "test.db")
    watcher._batch = type("B", (), {"write": lambda s, p, a: True,
                                    "close": lambda s: None})()
    watcher._process_one(str(photo))

    row = watcher._store.conn.execute(
        "SELECT phash, duplicate_of FROM results WHERE file_path = ?",
        (str(photo),),
    ).fetchone()
    assert row["phash"] is not None
    assert row["duplicate_of"] is None
    watcher._store.close()
