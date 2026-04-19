"""tests/hardening/test_g2_g3_g4_g5_reports.py

Hardening G2 / G3 / G4 / G5：報告匯出邊界。

- G2 JSON Unicode：non-ASCII 不被 escape 成 \\uXXXX
- G3 PDF CJK：Traditional Chinese 不變方塊
- G4 空結果：匯出空 CSV / JSON / PDF 不 crash
- G5 匯出路徑不可寫：清楚錯誤訊息

真實情境：同事匯出 csv 丟給業務，業務一打開都是 \\u8b1b\\u8005 然後吵「你
是不是檔案壞了」；或是匯出路徑寫到沒權限的磁碟根目錄。
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from modules.report_generator import generate_csv, generate_json


_RESULTS_CJK = [
    {
        "file_path": "/tmp/p1.jpg",
        "title": "年度大會致詞",
        "description": "一位身穿西裝的男士對著麥克風演講",
        "keywords": ["致詞", "講者", "舞台"],
        "category": "ceremony",
        "subcategory": "開幕",
        "scene_type": "indoor",
        "mood": "formal",
        "people_count": 1,
        "identified_people": ["張大明"],
        "ocr_text": ["映奧創意 2026 大會"],
    },
    {
        "file_path": "/tmp/p2.jpg",
        "title": "餐會合影",
        "description": "與會者在圓桌合照，氣氛融洽",
        "keywords": ["合照", "餐會"],
        "category": "networking",
        "subcategory": "晚宴",
        "scene_type": "indoor",
        "mood": "celebratory",
        "people_count": 10,
        "identified_people": [],
        "ocr_text": [],
    },
]


# ---------- G2: JSON Unicode ----------

def test_json_report_does_not_escape_cjk(tmp_path):
    """ensure_ascii=False must be honored — readable CJK in the file,
    not `\\u8b1b\\u8005`."""
    out = tmp_path / "report.json"
    generate_json(_RESULTS_CJK, out)

    raw = out.read_text(encoding="utf-8")
    # Human-readable CJK directly in output
    assert "年度大會致詞" in raw
    assert "映奧創意" in raw
    # ASCII-escaped form must NOT appear
    assert "\\u8b1b" not in raw
    assert "\\u5e74" not in raw


def test_json_report_emoji_round_trip(tmp_path):
    """Emoji in keywords must survive JSON round-trip."""
    out = tmp_path / "r.json"
    generate_json(
        [{
            "file_path": "/tmp/x.jpg",
            "title": "🎂 birthday",
            "keywords": ["🎉", "cake"],
            "description": "", "category": "other",
            "subcategory": "", "scene_type": "indoor",
            "mood": "celebratory", "people_count": 0,
            "identified_people": [], "ocr_text": [],
        }],
        out,
    )
    raw = out.read_text(encoding="utf-8")
    assert "🎂" in raw
    assert "🎉" in raw

    # Also valid JSON
    data = json.loads(raw)
    assert data[0]["title"] == "🎂 birthday"


# ---------- G3: PDF CJK (heavy-path smoke test) ----------

def test_pdf_report_bundled_font_exists():
    """Pre-req for G3: the CJK font is actually on disk at build time.
    If this is missing, reportlab would silently fall back to Helvetica
    and CJK glyphs render as boxes."""
    from modules.pdf_report import _find_bundled_font
    font = _find_bundled_font()
    assert font is not None, "NotoSansTC-Regular.ttf not bundled — CJK will render as boxes"
    assert font.exists()


def test_pdf_report_generates_with_cjk_content(tmp_path):
    """Smoke test: generating a PDF with CJK content completes and the
    output starts with %PDF. Doesn't verify glyph fidelity (can't from
    here) but catches font-registration / encoding crashes."""
    from modules.pdf_report import generate_report

    results_with_usage = [dict(r) for r in _RESULTS_CJK]
    # generate_report expects `_usage` sub-dict per row
    for r in results_with_usage:
        r["_usage"] = {"input_tokens": 100, "output_tokens": 50,
                       "total_tokens": 150, "cost_usd": 0.01,
                       "model": "gemini-2.5-flash-lite"}
        r["updated_at"] = "2026-04-19T10:00:00"

    pdf_bytes = generate_report(results_with_usage, folder="/tmp/test")

    out = tmp_path / "r.pdf"
    out.write_bytes(pdf_bytes)

    assert len(pdf_bytes) > 1000  # non-trivial PDF
    assert pdf_bytes.startswith(b"%PDF"), "output isn't a valid PDF"
    # Font must have been registered (smoke: NotoSansTC is in the PDF stream)
    assert b"NotoSansTC" in pdf_bytes, (
        "bundled CJK font not embedded — Traditional Chinese will render "
        "as boxes in Preview / Adobe Reader"
    )


# ---------- G4: Empty results ----------

def test_empty_csv_still_produces_header(tmp_path):
    """generate_csv with [] must produce a valid CSV (header row only),
    not crash or produce 0-byte file."""
    out = tmp_path / "empty.csv"
    generate_csv([], out)

    assert out.exists()
    with open(out, encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 1  # just header
    assert "title" in rows[0]
    assert "file_path" in rows[0]


def test_empty_json_produces_empty_array(tmp_path):
    out = tmp_path / "empty.json"
    generate_json([], out)
    raw = out.read_text(encoding="utf-8")
    assert raw.strip() == "[]"


def test_empty_pdf_does_not_crash(tmp_path):
    """Edge: all photos failed → summary exists but results list empty."""
    from modules.pdf_report import generate_report
    pdf_bytes = generate_report([], folder="/tmp/empty")
    assert pdf_bytes.startswith(b"%PDF"), "empty PDF must still be valid"
    assert len(pdf_bytes) > 200  # at least a summary page


# ---------- G5: Unwritable path ----------

def test_csv_export_to_readonly_dir_raises_clear_error(tmp_path):
    """Writing into a 0o555 read-only dir should raise PermissionError
    (or OSError). Must not silently produce an empty file or segfault."""
    ro = tmp_path / "readonly"
    ro.mkdir()
    ro.chmod(0o555)

    try:
        with pytest.raises((PermissionError, OSError)):
            generate_csv(_RESULTS_CJK, ro / "report.csv")
    finally:
        ro.chmod(0o755)  # allow cleanup


def test_json_export_to_nonexistent_parent_raises_clear_error(tmp_path):
    """User types a path whose parent dir doesn't exist. Must raise
    FileNotFoundError (clear) not some post-hoc KeyError."""
    bad = tmp_path / "does_not_exist" / "report.json"
    with pytest.raises((FileNotFoundError, OSError)):
        generate_json(_RESULTS_CJK, bad)


def test_csv_export_to_path_that_is_a_directory(tmp_path):
    """User typed `/tmp/` instead of `/tmp/report.csv`. Must raise a
    clear IsADirectoryError-family error."""
    with pytest.raises((IsADirectoryError, PermissionError, OSError)):
        generate_csv(_RESULTS_CJK, tmp_path)
