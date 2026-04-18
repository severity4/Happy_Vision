"""tests/test_e2e.py — End-to-end pipeline: scan → analyze → metadata → CSV"""
import shutil
import pytest


def _exiftool_available() -> bool:
    """Check if exiftool is on PATH (needed for real metadata verification)."""
    return shutil.which("exiftool") is not None


@pytest.mark.skipif(not _exiftool_available(),
                    reason="exiftool not installed; skip real-metadata E2E")
def test_e2e_pipeline_scan_analyze_metadata_csv(tmp_path, monkeypatch):
    """Full path: 3 JPGs -> mock Gemini -> pipeline -> real IPTC -> CSV.

    Also verifies skip_existing behavior on re-run.
    """
    from PIL import Image
    from modules import pipeline as pl
    from modules.metadata_writer import read_metadata
    from modules.report_generator import generate_csv
    from modules.result_store import ResultStore

    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    # 1) Create 3 real JPGs (100x100 white)
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    for i in range(3):
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        img.save(photos_dir / f"p{i}.jpg", "JPEG")

    # 2) Mock Gemini — return a valid schema result per photo
    analyze_count = {"n": 0}

    def fake_analyze(path, **kw):
        analyze_count["n"] += 1
        return (
            {
                "title": f"Title {analyze_count['n']}",
                "description": "A white square.",
                "keywords": ["test", "white"],
                "category": "other",
                "subcategory": "",
                "scene_type": "studio",
                "mood": "neutral",
                "people_count": 0,
                "identified_people": [],
                "ocr_text": [],
            },
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "model": "gemini-2.5-flash-lite",
            },
        )

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)

    # 3) Run pipeline with write_metadata=True
    db = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(photos_dir),
        api_key="test-key",
        concurrency=1,
        write_metadata=True,
        db_path=db,
    )

    assert len(results) == 3
    assert analyze_count["n"] == 3

    # 4) Verify DB has 3 completed entries
    with ResultStore(db) as store:
        all_results = store.get_all_results()
        assert len(all_results) == 3
        for r in all_results:
            assert r["file_path"].endswith(".jpg")

    # 5) Verify actual IPTC/XMP written to JPGs (real exiftool)
    for i in range(3):
        meta = read_metadata(str(photos_dir / f"p{i}.jpg"))
        # build_exiftool_args sets XMP:UserComment to HappyVisionProcessed
        user_comment = meta.get("UserComment", "")
        assert "HappyVisionProcessed" in str(user_comment), \
            f"Expected HappyVisionProcessed marker in {meta!r}"

    # 6) Re-run with skip_existing=True → no new analyses
    analyze_count["n"] = 0
    pl.run_pipeline(
        folder=str(photos_dir),
        api_key="test-key",
        concurrency=1,
        skip_existing=True,
        write_metadata=True,
        db_path=db,
    )
    assert analyze_count["n"] == 0, "Re-run with skip_existing should analyze zero photos"

    # 7) CSV export
    csv_path = tmp_path / "report.csv"
    with ResultStore(db) as store:
        generate_csv(store.get_all_results(), csv_path)

    csv_text = csv_path.read_text()
    assert "Title 1" in csv_text
    assert "Title 2" in csv_text
    assert "Title 3" in csv_text
    # Header row should mention file_path or similar
    first_line = csv_text.splitlines()[0].lower()
    assert "path" in first_line or "file" in first_line or "title" in first_line
