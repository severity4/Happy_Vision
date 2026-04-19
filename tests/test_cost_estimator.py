"""tests/test_cost_estimator.py — batch cost projection + /api/batch/estimate."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from modules.cost_estimator import (
    HEURISTIC_INPUT_TOKENS,
    HEURISTIC_OUTPUT_TOKENS,
    estimate_batch_cost,
)
from modules.result_store import ResultStore


def _write_jpeg(path: Path, size=(100, 80)) -> None:
    Image.new("RGB", size, (50, 100, 150)).save(path, format="JPEG")


@pytest.fixture
def folder(tmp_path):
    for i in range(10):
        _write_jpeg(tmp_path / f"p{i}.jpg")
    return str(tmp_path)


@pytest.fixture
def store(tmp_path):
    s = ResultStore(tmp_path / "r.db")
    yield s
    s.close()


# ---------------- heuristic path ----------------

def test_estimate_heuristic_when_no_history(folder, store):
    est = estimate_batch_cost(folder, model="lite", image_max_size=1024, store=store)
    assert est.source == "heuristic"
    assert est.sample_size == 0
    assert est.avg_input_tokens == HEURISTIC_INPUT_TOKENS[1024]
    assert est.avg_output_tokens == HEURISTIC_OUTPUT_TOKENS
    assert est.photo_count == 10


def test_estimate_batch_is_50_percent_of_realtime(folder, store):
    est = estimate_batch_cost(folder, model="lite", store=store)
    # Rounding tolerance: to 4 decimals they should be exactly half.
    assert round(est.batch_cost_usd, 4) == round(est.realtime_cost_usd / 2, 4)
    assert round(est.savings_usd, 4) == round(est.realtime_cost_usd / 2, 4)


def test_estimate_chunk_count_matches_photos_div_3000(folder, store):
    # Generate a simulated large photo list by fabricating paths (scan_photos
    # will skip non-existent files, so instead test chunks math directly via
    # smaller folder).
    est = estimate_batch_cost(folder, store=store)
    assert est.chunks == 1  # 10 photos < 3000


def test_estimate_skip_existing_filters_processed(folder, store):
    # Mark 3 of the 10 photos as already processed.
    photos = sorted(Path(folder).glob("*.jpg"))
    for p in photos[:3]:
        store.save_result(str(p), {"title": "x", "keywords": []})
    est = estimate_batch_cost(folder, skip_existing=True, store=store)
    assert est.photo_count == 7
    assert est.skipped_processed == 3
    assert est.scanned_count == 10


def test_estimate_empty_folder_returns_zero(tmp_path, store):
    est = estimate_batch_cost(str(tmp_path), store=store)
    assert est.photo_count == 0
    assert est.scanned_count == 0
    assert est.chunks == 0
    assert est.batch_cost_usd == 0.0


# ---------------- historical path ----------------

def test_estimate_uses_history_when_enough_rows(folder, store):
    """With ≥20 completed rows matching the model, use observed averages."""
    for i in range(25):
        store.save_result(
            f"/tmp/hist{i}.jpg",
            {"title": "x", "keywords": []},
            usage={
                "input_tokens": 800,
                "output_tokens": 250,
                "total_tokens": 1050,
                "model": "gemini-2.5-flash-lite",
            },
        )
    est = estimate_batch_cost(folder, model="lite", store=store)
    assert est.source == "history"
    assert est.sample_size >= 20
    assert est.avg_input_tokens == 800
    assert est.avg_output_tokens == 250


# ---------------- API endpoint ----------------

def test_api_estimate_requires_folder():
    import web_ui
    client = web_ui.app.test_client()
    r = client.get("/api/batch/estimate")
    assert r.status_code == 400
    assert "folder" in r.get_json()["error"]


def test_api_estimate_returns_full_payload(tmp_path):
    import web_ui
    for i in range(5):
        _write_jpeg(tmp_path / f"p{i}.jpg")
    client = web_ui.app.test_client()
    r = client.get(f"/api/batch/estimate?folder={tmp_path}&model=lite&image_max_size=1024")
    assert r.status_code == 200
    data = r.get_json()
    assert data["photo_count"] == 5
    assert data["model_name"] == "gemini-2.5-flash-lite"
    assert data["image_max_size"] == 1024
    assert data["batch_cost_usd"] > 0
    assert data["realtime_cost_usd"] > data["batch_cost_usd"]
    assert data["savings_usd"] > 0
    assert data["hours_slo"] == 24


def test_api_estimate_rejects_missing_folder():
    import web_ui
    client = web_ui.app.test_client()
    r = client.get("/api/batch/estimate?folder=/definitely/does/not/exist/anywhere")
    assert r.status_code == 400
    assert "not a directory" in r.get_json()["error"]
