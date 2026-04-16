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
