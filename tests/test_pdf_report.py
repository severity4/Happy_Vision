"""tests/test_pdf_report.py"""

from modules.pdf_report import generate_report


def _sample_result(i: int, model: str = "gemini-2.5-flash-lite") -> dict:
    return {
        "file_path": f"/photos/IMG_{i:04d}.jpg",
        "title": f"Photo {i}",
        "description": "測試用照片說明。",
        "keywords": ["婚禮", "人像", "自然光"],
        "category": "ceremony",
        "subcategory": "keynote",
        "scene_type": "indoor",
        "mood": "formal",
        "people_count": 10,
        "identified_people": [],
        "ocr_text": [],
        "updated_at": "2026-04-18T10:41:22",
        "_usage": {
            "input_tokens": 3800 + i,
            "output_tokens": 410 + i,
            "total_tokens": 4210 + 2 * i,
            "cost_usd": 0.000544 + i * 1e-6,
            "model": model,
        },
    }


def test_generate_report_returns_pdf_bytes():
    results = [_sample_result(i) for i in range(3)]
    pdf = generate_report(results, folder="/photos")
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000
    assert pdf.startswith(b"%PDF-"), "Output is not a PDF (wrong magic number)"


def test_generate_report_handles_empty_results():
    # Empty is a valid case — should still render summary page (0 photos)
    pdf = generate_report([])
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 500


def test_generate_report_handles_missing_usage():
    # Old rows predating v0.5.0 migration have no _usage
    results = [{
        "file_path": "/photos/legacy.jpg",
        "title": "Legacy",
        "description": "Old row.",
        "keywords": [],
        "category": "other",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "updated_at": "2026-04-01T00:00:00",
    }]
    pdf = generate_report(results)
    assert pdf.startswith(b"%PDF-")


def test_generate_report_pagination_for_large_result_set():
    # 120 rows should span multiple detail pages (chunk_size=28)
    results = [_sample_result(i) for i in range(120)]
    pdf = generate_report(results)
    # File should be meaningfully bigger than a 3-row report
    small_pdf = generate_report([_sample_result(0)])
    assert len(pdf) > len(small_pdf)


def test_generate_report_mixed_models():
    results = [
        _sample_result(0, model="gemini-2.5-flash-lite"),
        _sample_result(1, model="gemini-2.5-flash"),
        _sample_result(2, model="gemini-2.5-flash-lite"),
    ]
    pdf = generate_report(results)
    assert pdf.startswith(b"%PDF-")


def test_generate_report_handles_cjk():
    # Traditional Chinese in description/keywords must render without crash
    results = [{
        "file_path": "/photos/中文.jpg",
        "title": "新娘與伴娘",
        "description": "在教堂走道末端等待，自然光從彩色玻璃灑下。",
        "keywords": ["婚禮", "人像", "暖光", "教堂"],
        "category": "ceremony",
        "scene_type": "indoor",
        "mood": "intimate",
        "people_count": 3,
        "updated_at": "2026-04-18T10:41:22",
        "_usage": {
            "input_tokens": 4000,
            "output_tokens": 420,
            "total_tokens": 4420,
            "cost_usd": 0.000568,
            "model": "gemini-2.5-flash-lite",
        },
    }]
    pdf = generate_report(results)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000
