"""tests/test_backfill_metadata.py — backfill utility"""
from pathlib import Path

from backfill_metadata import backfill


def _seed_result(store, path: str, title: str = "T"):
    store.save_result(path, {
        "title": title,
        "keywords": ["a", "b"],
        "description": "d",
        "category": "other",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
    })


def test_backfill_counts_missing_files(tmp_path, monkeypatch):
    """DB has entry but file gone → skipped_missing."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    from modules.result_store import ResultStore
    with ResultStore() as store:
        _seed_result(store, str(tmp_path / "nonexistent.jpg"))

    stats = backfill(dry_run=True)
    assert stats["total"] == 1
    assert stats["skipped_missing"] == 1
    assert stats["written"] == 0


def test_backfill_dry_run_writes_nothing(tmp_path, monkeypatch):
    """Dry-run reports what would be written but never spawns exiftool."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))

    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")

    from modules.result_store import ResultStore
    with ResultStore() as store:
        _seed_result(store, str(photo))

    # has_happy_vision_tag would spawn real exiftool on fake JPG → error.
    # Mock it to return False so the backfill loop thinks this photo needs writing.
    import backfill_metadata as bm
    monkeypatch.setattr(bm, "has_happy_vision_tag", lambda p: False)

    batch_created = {"n": 0}

    class BoomBatch:
        def __init__(self): batch_created["n"] += 1
        def write(self, *a, **kw): return True
        def close(self): pass

    monkeypatch.setattr(bm, "ExiftoolBatch", BoomBatch)

    stats = backfill(dry_run=True)
    assert stats["written"] == 1
    assert batch_created["n"] == 0  # dry-run doesn't even instantiate


def test_backfill_skips_already_tagged(tmp_path, monkeypatch):
    """If has_happy_vision_tag returns True, skip the write."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")

    from modules.result_store import ResultStore
    with ResultStore() as store:
        _seed_result(store, str(photo))

    import backfill_metadata as bm
    monkeypatch.setattr(bm, "has_happy_vision_tag", lambda p: True)

    write_calls = []

    class SpyBatch:
        def write(self, path, args):
            write_calls.append(path)
            return True
        def close(self): pass

    monkeypatch.setattr(bm, "ExiftoolBatch", SpyBatch)

    stats = backfill(dry_run=False)
    assert stats["skipped_tagged"] == 1
    assert stats["written"] == 0
    assert write_calls == []


def test_backfill_force_ignores_tag_check(tmp_path, monkeypatch):
    """--force writes even when HappyVisionProcessed marker is present."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")

    from modules.result_store import ResultStore
    with ResultStore() as store:
        _seed_result(store, str(photo))

    import backfill_metadata as bm
    # Even though the marker is present, force mode should NOT check
    monkeypatch.setattr(bm, "has_happy_vision_tag",
                        lambda p: (_ for _ in ()).throw(AssertionError("should not be called")))

    class SpyBatch:
        def write(self, path, args): return True
        def close(self): pass

    monkeypatch.setattr(bm, "ExiftoolBatch", SpyBatch)

    stats = backfill(dry_run=False, force=True)
    assert stats["written"] == 1
    assert stats["skipped_tagged"] == 0


def test_backfill_writes_via_batch(tmp_path, monkeypatch):
    """Happy path: untagged, existing file → batch.write called once per photo."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))

    for i in range(3):
        (tmp_path / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    from modules.result_store import ResultStore
    with ResultStore() as store:
        for i in range(3):
            _seed_result(store, str(tmp_path / f"p{i}.jpg"), title=f"T{i}")

    import backfill_metadata as bm
    monkeypatch.setattr(bm, "has_happy_vision_tag", lambda p: False)

    writes = []

    class SpyBatch:
        def write(self, path, args):
            writes.append((path, args))
            return True
        def close(self): pass

    monkeypatch.setattr(bm, "ExiftoolBatch", SpyBatch)

    stats = backfill(dry_run=False)
    assert stats["written"] == 3
    assert len(writes) == 3
    # Each args list must include -overwrite_original
    for _, args in writes:
        assert "-overwrite_original" in args


def test_backfill_folder_filter(tmp_path, monkeypatch):
    """--folder restricts scope to matching prefix."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))

    event_a = tmp_path / "event_a"
    event_b = tmp_path / "event_b"
    event_a.mkdir()
    event_b.mkdir()
    (event_a / "x.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (event_b / "y.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    from modules.result_store import ResultStore
    with ResultStore() as store:
        _seed_result(store, str(event_a / "x.jpg"))
        _seed_result(store, str(event_b / "y.jpg"))

    import backfill_metadata as bm
    monkeypatch.setattr(bm, "has_happy_vision_tag", lambda p: False)

    writes = []

    class SpyBatch:
        def write(self, path, args):
            writes.append(path)
            return True
        def close(self): pass

    monkeypatch.setattr(bm, "ExiftoolBatch", SpyBatch)

    stats = backfill(folder=str(event_a), dry_run=False)
    assert stats["written"] == 1
    assert Path(writes[0]).parent.name == "event_a"


def test_backfill_counts_write_failures(tmp_path, monkeypatch):
    """batch.write returning False increments failed count, not written."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")

    from modules.result_store import ResultStore
    with ResultStore() as store:
        _seed_result(store, str(photo))

    import backfill_metadata as bm
    monkeypatch.setattr(bm, "has_happy_vision_tag", lambda p: False)

    class FailingBatch:
        def write(self, path, args): return False
        def close(self): pass

    monkeypatch.setattr(bm, "ExiftoolBatch", FailingBatch)

    stats = backfill(dry_run=False)
    assert stats["failed"] == 1
    assert stats["written"] == 0
