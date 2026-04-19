"""tests/test_gemini_batch.py — unit tests for the Gemini Batch client.

Network calls to genai.Client are mocked; we only validate the JSONL we
build, how we drive the SDK, and how we parse output lines."""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from modules import gemini_batch


# ---------------- helpers ----------------

def _write_jpeg(path: Path, color=(128, 64, 200), size=(64, 48)) -> None:
    img = Image.new("RGB", size, color)
    img.save(path, format="JPEG", quality=85)


@pytest.fixture
def three_photos(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"p{i}.jpg"
        _write_jpeg(p, color=(i * 40, 100, 200 - i * 30))
        paths.append(str(p))
    return paths


# ---------------- build_jsonl_for_chunk ----------------

def test_build_jsonl_creates_one_line_per_photo(three_photos, tmp_path):
    out = tmp_path / "batch.jsonl"
    jsonl_path, key_map, payload_bytes = gemini_batch.build_jsonl_for_chunk(
        three_photos, model="lite", max_size=1024, out_path=out,
    )
    assert jsonl_path == out
    assert len(key_map) == 3
    assert [k for k, _ in key_map] == ["p00000", "p00001", "p00002"]
    assert payload_bytes > 0
    lines = out.read_text().splitlines()
    assert len(lines) == 3


def test_build_jsonl_uses_snake_case_fields(three_photos, tmp_path):
    """Gemini REST expects snake_case. A camelCase regression would silently
    fail all requests."""
    out = tmp_path / "batch.jsonl"
    gemini_batch.build_jsonl_for_chunk(three_photos[:1], out_path=out)
    obj = json.loads(out.read_text().splitlines()[0])
    assert "key" in obj and "request" in obj
    req = obj["request"]
    assert "contents" in req
    assert "generation_config" in req  # not generationConfig
    # response schema lives under generation_config
    assert "response_schema" in req["generation_config"]
    # Inline image part uses inline_data, not inlineData
    parts = req["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg"
    # base64 data is a non-empty string
    assert len(parts[0]["inline_data"]["data"]) > 100
    assert isinstance(parts[1]["text"], str)


def test_build_jsonl_rejects_empty_list():
    with pytest.raises(ValueError, match="must not be empty"):
        gemini_batch.build_jsonl_for_chunk([])


def test_build_jsonl_rejects_oversized_chunk(three_photos):
    too_many = three_photos * (gemini_batch.MAX_PHOTOS_PER_BATCH // 3 + 1)
    with pytest.raises(ValueError, match="exceeds MAX_PHOTOS_PER_BATCH"):
        gemini_batch.build_jsonl_for_chunk(too_many)


def test_build_jsonl_skips_unreadable_photo(three_photos, tmp_path, caplog):
    bad = str(tmp_path / "missing.jpg")
    photos = [three_photos[0], bad, three_photos[1]]
    out = tmp_path / "batch.jsonl"
    _, key_map, _ = gemini_batch.build_jsonl_for_chunk(photos, out_path=out)
    # The missing file is skipped; key order preserved by original index.
    assert len(key_map) == 2
    paths = [p for _, p in key_map]
    assert three_photos[0] in paths and three_photos[1] in paths


# ---------------- chunk_photos ----------------

def test_chunk_photos_splits_evenly():
    photos = [f"p{i}" for i in range(7)]
    chunks = gemini_batch.chunk_photos(photos, chunk_size=3)
    assert len(chunks) == 3
    assert chunks[0] == ["p0", "p1", "p2"]
    assert chunks[-1] == ["p6"]


def test_chunk_photos_single_chunk_when_small():
    chunks = gemini_batch.chunk_photos(["a", "b"], chunk_size=5)
    assert chunks == [["a", "b"]]


# ---------------- submit_batch (mocked SDK) ----------------

def _make_fake_client(uploaded_name="files/abc123", job_name="batches/xyz", upload_raises=None, create_raises=None):
    fake = MagicMock()
    uploaded = MagicMock()
    uploaded.name = uploaded_name
    uploaded.size_bytes = 12345
    if upload_raises is not None:
        fake.files.upload.side_effect = upload_raises
    else:
        fake.files.upload.return_value = uploaded
    job = MagicMock()
    job.name = job_name
    job.state = MagicMock()
    job.state.name = "JOB_STATE_PENDING"
    if create_raises is not None:
        fake.batches.create.side_effect = create_raises
    else:
        fake.batches.create.return_value = job
    return fake


def test_submit_batch_happy_path(tmp_path, three_photos):
    out = tmp_path / "batch.jsonl"
    gemini_batch.build_jsonl_for_chunk(three_photos, out_path=out)
    fake = _make_fake_client()
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        res = gemini_batch.submit_batch(out, api_key="k", model="lite")
    assert res.job_id == "batches/xyz"
    assert res.input_file_id == "files/abc123"
    # Should have called upload exactly once with mime_type "jsonl"
    assert fake.files.upload.call_count == 1
    call_kwargs = fake.files.upload.call_args.kwargs
    assert call_kwargs["config"].mime_type == "jsonl"
    # Then batches.create with the uploaded file name as src
    assert fake.batches.create.call_count == 1
    create_kwargs = fake.batches.create.call_args.kwargs
    assert create_kwargs["src"] == "files/abc123"


def test_submit_batch_retries_mime_on_key_error(tmp_path, three_photos):
    """SDK issue #1590: first upload raises KeyError, second with text/plain
    must succeed. Our client should fall through without surfacing."""
    out = tmp_path / "batch.jsonl"
    gemini_batch.build_jsonl_for_chunk(three_photos, out_path=out)
    uploaded = MagicMock()
    uploaded.name = "files/ok"
    uploaded.size_bytes = 999
    fake = MagicMock()
    fake.files.upload.side_effect = [KeyError("file"), uploaded]
    job = MagicMock()
    job.name = "batches/ok"
    job.state.name = "JOB_STATE_PENDING"
    fake.batches.create.return_value = job
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        res = gemini_batch.submit_batch(out, api_key="k")
    assert res.job_id == "batches/ok"
    assert fake.files.upload.call_count == 2
    first_mime = fake.files.upload.call_args_list[0].kwargs["config"].mime_type
    second_mime = fake.files.upload.call_args_list[1].kwargs["config"].mime_type
    assert first_mime == "jsonl"
    assert second_mime == "text/plain"


def test_submit_batch_tier_error_raises_friendly(tmp_path, three_photos):
    out = tmp_path / "batch.jsonl"
    gemini_batch.build_jsonl_for_chunk(three_photos, out_path=out)
    fake = _make_fake_client(
        create_raises=Exception("PERMISSION_DENIED: batch requires billing tier 1"),
    )
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        with pytest.raises(gemini_batch.TierRequiredError):
            gemini_batch.submit_batch(out, api_key="k")


# ---------------- get_job_state ----------------

def test_get_job_state_reports_output_file_when_present():
    fake = MagicMock()
    job = MagicMock()
    job.state.name = "JOB_STATE_SUCCEEDED"
    job.dest = MagicMock()
    job.dest.file_name = "files/output-9"
    job.error = None
    fake.batches.get.return_value = job
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        info = gemini_batch.get_job_state("batches/x", api_key="k")
    assert info["state"] == "JOB_STATE_SUCCEEDED"
    assert info["output_file"] == "files/output-9"
    assert info["error"] is None


# ---------------- fetch_results ----------------

def test_fetch_results_parses_success_and_error_lines():
    good_line = json.dumps({
        "key": "p00000",
        "response": {
            "candidates": [{
                "content": {"parts": [{"text": json.dumps({
                    "title": "t", "description": "d", "keywords": ["a"],
                    "category": "ceremony", "scene_type": "indoor",
                    "mood": "formal", "people_count": 2,
                })}]}
            }],
            "usage_metadata": {"prompt_token_count": 100, "candidates_token_count": 20, "total_token_count": 120},
        },
    })
    bad_line = json.dumps({
        "key": "p00001",
        "error": {"code": 3, "message": "INVALID_ARGUMENT"},
    })
    payload = (good_line + "\n" + bad_line + "\n").encode("utf-8")

    fake = MagicMock()
    job = MagicMock()
    job.dest = MagicMock()
    job.dest.file_name = "files/out"
    job.state.name = "JOB_STATE_SUCCEEDED"
    fake.batches.get.return_value = job
    fake.files.download.return_value = payload
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        results = list(gemini_batch.fetch_results("batches/x", api_key="k", model="lite"))
    assert len(results) == 2
    assert results[0].key == "p00000"
    assert results[0].result is not None
    assert results[0].result["title"] == "t"
    assert results[0].usage["input_tokens"] == 100
    assert results[0].usage["output_tokens"] == 20
    assert results[0].error is None
    assert results[1].key == "p00001"
    assert results[1].result is None
    assert "INVALID_ARGUMENT" in results[1].error


def test_fetch_results_raises_when_no_output_file():
    fake = MagicMock()
    job = MagicMock()
    job.dest = None
    job.state.name = "JOB_STATE_RUNNING"
    fake.batches.get.return_value = job
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        with pytest.raises(RuntimeError, match="no output file"):
            list(gemini_batch.fetch_results("batches/x", api_key="k"))


# ---------------- cancel_job ----------------

def test_cancel_job_returns_true_on_success():
    fake = MagicMock()
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        assert gemini_batch.cancel_job("batches/x", api_key="k") is True
    fake.batches.cancel.assert_called_once_with(name="batches/x")


def test_cancel_job_returns_false_on_api_error():
    fake = MagicMock()
    fake.batches.cancel.side_effect = Exception("already cancelled")
    with patch.object(gemini_batch.genai, "Client", return_value=fake):
        assert gemini_batch.cancel_job("batches/x", api_key="k") is False


# ---------------- estimate_completion_at ----------------

def test_estimate_completion_at_adds_24h():
    eta = gemini_batch.estimate_completion_at("2026-04-19T12:00:00", slo_hours=24)
    assert eta.startswith("2026-04-20T12:00:00")
