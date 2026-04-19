"""tests/hardening/test_b6_phash_dedup.py

Hardening B6: 同一張照片重複執行 → phash 去重有效，不重複 call Gemini。

兩個去重路徑：
1. **folder_watcher** — 新照片進來，先算 phash → `result_store.find_similar`
   → 若有近似既存照片就 reuse 其分析結果，不打 Gemini（v0.6.0 起有）
2. **pipeline (CLI / batch)** — 依 file path 的 `is_processed` 檢查，同
   folder 重跑會跳過已處理檔。**但不做 phash 近似比對**：跨資料夾的
   視覺重複會雙重計費 — 這是已知限制，鎖住 regression。

真實威脅：同事把事件照片同時放 `Event/2026/` 和 `備份/Event/` 兩份都跑
分析，pipeline 會對同一張照片打兩次 Gemini。這個 checklist 項目不展開修，
但把行為鎖住，將來若改為自動跨資料夾 dedup 能立刻看到 test 變化。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from modules import pipeline as pl
from modules.result_store import ResultStore


_MOCK_USAGE = {
    "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result(title: str = "analyzed") -> dict:
    return {
        "title": title, "description": "d", "keywords": ["kw"],
        "category": "other", "subcategory": "",
        "scene_type": "indoor", "mood": "neutral",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    }


def _write_distinctive_jpg(path: Path, seed: int) -> None:
    """Write a JPEG with a reproducible pattern. Same seed → byte-identical
    pixels → identical dhash. Different seed → very different dhash."""
    import random
    img = Image.new("RGB", (200, 200), color=(128, 128, 128))
    rng = random.Random(seed)
    pixels = img.load()
    for x in range(200):
        for y in range(200):
            c = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
            pixels[x, y] = c
    img.save(str(path), "JPEG", quality=90)


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


# ---------- Pipeline path: is_processed skips re-run on same folder ----------

def test_pipeline_skips_already_processed_on_rerun_when_opted_in(tmp_path, monkeypatch):
    """With `skip_existing=True`, re-running on same folder must not call
    Gemini again. This is the UI toggle "SKIP EXISTING · 跳過已處理" and
    the CLI `--skip-existing` flag.

    Note: the pipeline default is `skip_existing=False` (re-analyze),
    documented by the other test below. Users opt in to dedup."""
    for i in range(4):
        _write_distinctive_jpg(tmp_path / f"p{i:02d}.jpg", seed=100 + i)

    analyze_calls = []

    def fake_analyze(path, **_kw):
        analyze_calls.append(path)
        return _mock_result(), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"

    # First run: all 4 analyzed (even without skip_existing — fresh DB).
    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="k",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
        skip_existing=True,
    )
    assert len(analyze_calls) == 4

    analyze_calls.clear()

    # Second run with skip_existing=True: 0 Gemini calls.
    results2 = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="k",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
        skip_existing=True,
    )
    assert len(analyze_calls) == 0, (
        f"re-run with skip_existing=True called Gemini {len(analyze_calls)} "
        "times — is_processed dedup is broken"
    )
    assert len(results2) == 0


def test_pipeline_default_reprocesses_without_skip_existing(tmp_path, monkeypatch):
    """Lock-in: pipeline's `skip_existing` default is False. Users who
    expect automatic dedup must set the flag — document the default so
    UX changes are visible in test."""
    _write_distinctive_jpg(tmp_path / "p.jpg", seed=1)

    analyze_calls = []

    def fake_analyze(path, **_kw):
        analyze_calls.append(path)
        return _mock_result(), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"

    pl.run_pipeline(folder=str(tmp_path), api_key="k", concurrency=1,
                    write_metadata=False, db_path=db_path)
    pl.run_pipeline(folder=str(tmp_path), api_key="k", concurrency=1,
                    write_metadata=False, db_path=db_path)

    # Default behavior: re-analyze. If this flips to 1, someone changed
    # the default — update checklist and UI guidance.
    assert len(analyze_calls) == 2, (
        f"Expected default pipeline to re-analyze (skip_existing=False). "
        f"Got {len(analyze_calls)} calls."
    )


def test_pipeline_reruns_failed_photos_on_next_invocation(tmp_path, monkeypatch):
    """Regression guard: `skip_existing` must only skip `completed` rows,
    not `failed` ones — otherwise a transient Gemini error would permanently
    prevent a photo from being retried on next CLI invocation."""
    _write_distinctive_jpg(tmp_path / "good.jpg", seed=1)
    _write_distinctive_jpg(tmp_path / "bad.jpg", seed=2)

    attempt = {"bad": 0}

    def mixed_analyze(path, **_kw):
        if "bad.jpg" in path:
            attempt["bad"] += 1
            if attempt["bad"] == 1:
                return None, None  # fail on first run
            return _mock_result("bad_now_good"), _MOCK_USAGE
        return _mock_result("good"), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", mixed_analyze)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"

    pl.run_pipeline(folder=str(tmp_path), api_key="k", concurrency=1,
                    write_metadata=False, db_path=db_path, skip_existing=True)

    # Second run with skip_existing=True: bad.jpg should be retried, good
    # skipped.
    pl.run_pipeline(folder=str(tmp_path), api_key="k", concurrency=1,
                    write_metadata=False, db_path=db_path, skip_existing=True)

    assert attempt["bad"] == 2, (
        "bad.jpg was not retried on second run — skip_existing wrongly "
        "swallowed the 'failed' status row"
    )


def test_pipeline_does_not_phash_dedup_across_different_paths(tmp_path, monkeypatch):
    """Document known limitation: pipeline uses file-path equality, not
    phash. Two copies of the SAME photo bytes at different paths → Gemini
    called twice.

    If someone later adds phash dedup to pipeline, this test will flip —
    then delete this test and the commit message surfaces the decision."""
    src = tmp_path / "original.jpg"
    _write_distinctive_jpg(src, seed=42)

    # Byte-identical copy at a different path → same phash
    dup = tmp_path / "copy.jpg"
    shutil.copy2(src, dup)

    analyze_calls = []

    def fake_analyze(path, **_kw):
        analyze_calls.append(path)
        return _mock_result(), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="k",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # Current behavior: both paths analyzed (no phash dedup in pipeline).
    # If this ever becomes 1, someone added phash dedup — re-evaluate this
    # test and update the B6 checklist note.
    assert len(analyze_calls) == 2, (
        f"Expected pipeline to call Gemini twice (known limitation). "
        f"Got {len(analyze_calls)} — did someone add phash dedup? "
        f"If yes, remove this test and update .ralph-hardening.md."
    )


# ---------- result_store.find_similar: the shared primitive ----------

def test_find_similar_hits_for_byte_identical_copy(tmp_path, monkeypatch):
    """Unit check on the core dedup primitive: a byte-identical copy must
    match an existing row with distance=0."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    src = tmp_path / "original.jpg"
    _write_distinctive_jpg(src, seed=7)

    from modules.phash import compute_phash

    phash_src = compute_phash(src)
    store = ResultStore(tmp_path / "r.db")
    store.save_result(
        str(src),
        _mock_result("master"),
        usage=_MOCK_USAGE,
        cost_usd=0.001,
        phash=phash_src,
    )

    dup = tmp_path / "copy.jpg"
    shutil.copy2(src, dup)
    phash_dup = compute_phash(dup)

    assert phash_src == phash_dup, "byte-identical copies must have identical dhash"

    match = store.find_similar(phash_dup, threshold=0)
    assert match is not None
    assert match["distance"] == 0
    assert match["result"]["title"] == "master"


def test_find_similar_ignores_failed_rows(tmp_path, monkeypatch):
    """Failed photos leave rows with status='failed' and NULL phash. They
    must not show up as dedup candidates — else future photos would reuse
    garbage 'analysis' from a failed row."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    failed_src = tmp_path / "bad.jpg"
    _write_distinctive_jpg(failed_src, seed=99)

    store = ResultStore(tmp_path / "r.db")
    store.mark_failed(str(failed_src), "simulated failure")

    from modules.phash import compute_phash
    phash = compute_phash(failed_src)

    match = store.find_similar(phash, threshold=5)
    assert match is None, (
        "find_similar leaked a failed row as a dedup candidate — "
        "would propagate garbage 'analysis' to future photos"
    )


# NOTE: folder_watcher phash dedup happy-path + threshold=0 are already
# covered in tests/test_folder_watcher_dedup.py (4 tests). Not duplicated
# here — this file focuses on pipeline-side behavior + cross-cutting
# primitive (find_similar) edge cases.
