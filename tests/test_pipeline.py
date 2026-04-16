"""tests/test_pipeline.py"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.pipeline import scan_photos, run_pipeline, PipelineCallbacks


def test_scan_photos_finds_jpgs(tmp_path):
    (tmp_path / "photo1.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "photo2.JPG").write_bytes(b"\xff\xd8")
    (tmp_path / "photo3.jpeg").write_bytes(b"\xff\xd8")
    (tmp_path / "photo4.png").write_bytes(b"\x89PNG")
    (tmp_path / "readme.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "photo5.jpg").write_bytes(b"\xff\xd8")

    photos = scan_photos(str(tmp_path))
    extensions = {Path(p).suffix.lower() for p in photos}
    assert extensions <= {".jpg", ".jpeg"}
    assert len(photos) == 4  # photo1, photo2, photo3, sub/photo5


def test_scan_photos_empty_folder(tmp_path):
    photos = scan_photos(str(tmp_path))
    assert photos == []


def test_pipeline_callbacks_called(tmp_path):
    (tmp_path / "photo1.jpg").write_bytes(b"\xff\xd8")

    mock_result = {
        "title": "Test",
        "description": "Test photo",
        "keywords": ["test"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }

    callbacks = PipelineCallbacks()
    progress_calls = []
    callbacks.on_progress = lambda done, total, path: progress_calls.append((done, total, path))

    with patch("modules.pipeline.analyze_photo", return_value=mock_result):
        results = run_pipeline(
            folder=str(tmp_path),
            api_key="fake-key",
            model="lite",
            concurrency=1,
            skip_existing=False,
            db_path=tmp_path / "test.db",
            callbacks=callbacks,
        )

    assert len(results) == 1
    assert len(progress_calls) == 1
    assert progress_calls[0][0] == 1  # done
    assert progress_calls[0][1] == 1  # total


def test_pipeline_skips_processed(tmp_path):
    (tmp_path / "photo1.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "photo2.jpg").write_bytes(b"\xff\xd8")

    mock_result = {"title": "Test", "keywords": []}

    from modules.result_store import ResultStore
    store = ResultStore(tmp_path / "test.db")
    store.save_result(str(tmp_path / "photo1.jpg"), mock_result)
    store.close()

    analyze_calls = []

    def mock_analyze(path, **kwargs):
        analyze_calls.append(path)
        return mock_result

    with patch("modules.pipeline.analyze_photo", side_effect=mock_analyze):
        run_pipeline(
            folder=str(tmp_path),
            api_key="fake-key",
            model="lite",
            concurrency=1,
            skip_existing=True,
            db_path=tmp_path / "test.db",
        )

    assert len(analyze_calls) == 1
    assert "photo2.jpg" in analyze_calls[0]


def test_pipeline_writes_metadata_per_photo(tmp_path, monkeypatch):
    """When write_metadata=True, ExiftoolBatch.write is called once per photo."""
    from modules import pipeline as pl

    # 3 fake photos
    for i in range(3):
        (tmp_path / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")  # minimal JPEG

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **kw: {"title": f"T-{Path(path).name}", "keywords": ["k"],
                            "description": "d", "category": "other",
                            "scene_type": "indoor", "mood": "neutral", "people_count": 0},
    )

    writes = []

    class FakeBatch:
        def __init__(self): pass
        def write(self, path, args):
            writes.append(path)
            return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", FakeBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
    )

    assert len(writes) == 3
    assert all(str(tmp_path) in w for w in writes)


def test_pipeline_cancel_stops_metadata_writes(tmp_path, monkeypatch):
    """After cancel, no further metadata writes happen."""
    from modules import pipeline as pl

    for i in range(10):
        (tmp_path / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    state = pl.PipelineState()
    call_count = {"n": 0}

    def fake_analyze(path, **kw):
        call_count["n"] += 1
        if call_count["n"] == 2:
            state.cancel()
        return {"title": "T", "keywords": [], "description": "",
                "category": "other", "scene_type": "indoor",
                "mood": "neutral", "people_count": 0}

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)

    writes = []
    class FakeBatch:
        def write(self, path, args): writes.append(path); return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(pl, "ExiftoolBatch", FakeBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
        state=state,
    )

    # Cancelled after 2 analyses → at most 2 metadata writes (not all 10)
    assert len(writes) <= 2


def test_pipeline_metadata_failure_marks_failed(tmp_path, monkeypatch):
    """If ExiftoolBatch.write returns False, photo should be marked failed."""
    from modules import pipeline as pl

    (tmp_path / "p.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **kw: {"title": "T", "keywords": [], "description": "",
                            "category": "other", "scene_type": "indoor",
                            "mood": "neutral", "people_count": 0},
    )

    class FailingBatch:
        def write(self, path, args): return False
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(pl, "ExiftoolBatch", FailingBatch)

    errors = []
    class CB(pl.PipelineCallbacks):
        def on_error(self, path, err): errors.append((path, err))

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
        callbacks=CB(),
    )

    assert len(errors) == 1
    assert "metadata" in errors[0][1].lower()


def test_pipeline_does_not_create_batch_when_metadata_disabled(tmp_path, monkeypatch):
    """When write_metadata=False, ExiftoolBatch must never be instantiated."""
    from modules import pipeline as pl

    (tmp_path / "p.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **kw: {"title": "T", "keywords": [], "description": "",
                            "category": "other", "scene_type": "indoor",
                            "mood": "neutral", "people_count": 0},
    )

    instantiated = {"n": 0}

    class SpyBatch:
        def __init__(self):
            instantiated["n"] += 1
        def write(self, *a, **kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", SpyBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    assert instantiated["n"] == 0
