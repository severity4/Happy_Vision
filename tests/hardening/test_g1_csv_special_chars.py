"""tests/hardening/test_g1_csv_special_chars.py

Hardening G1: CSV 報告裡特殊字元（逗號、引號、換行、emoji、tab）正確跳脫，
Excel / Numbers 開不會爛格。

實際情境：Gemini 產生的 description 常常有逗號（「A ceremony, hosted by...」）。
title/description 會偶爾包引號（引述 slogan）。OCR 拆出來的 banner 文字可能
含換行。keywords 裡本來就是列表但 join 成字串後若單個 keyword 有逗號會破壞
下游工具的二次 split。這裡把 CSV round-trip（寫入 → 讀回）鎖死。
"""

from __future__ import annotations

import csv
from pathlib import Path

from modules.report_generator import generate_csv, generate_json


def _minimal(**overrides) -> dict:
    base = {
        "file_path": "/tmp/p.jpg",
        "title": "t",
        "description": "d",
        "keywords": [],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }
    base.update(overrides)
    return base


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_csv_round_trips_comma_in_description(tmp_path):
    results = [_minimal(
        title="Gala dinner",
        description="A formal ceremony, hosted by Taipei Chamber, featured panel",
    )]
    out = tmp_path / "r.csv"
    generate_csv(results, out)

    rows = _read_csv(out)
    assert len(rows) == 1
    # Original commas must be preserved after read-back; no field split.
    assert rows[0]["description"] == (
        "A formal ceremony, hosted by Taipei Chamber, featured panel"
    )


def test_csv_round_trips_double_quotes(tmp_path):
    results = [_minimal(
        title='Speaker said "Innovate or die"',
        description='The banner read "Welcome Taipei 2026"',
    )]
    out = tmp_path / "r.csv"
    generate_csv(results, out)

    rows = _read_csv(out)
    assert rows[0]["title"] == 'Speaker said "Innovate or die"'
    assert rows[0]["description"] == 'The banner read "Welcome Taipei 2026"'


def test_csv_round_trips_newlines_and_tabs(tmp_path):
    results = [_minimal(
        description="Line 1\nLine 2\nLine 3",
        ocr_text=["Banner line 1\nBanner line 2", "Slide\tTitle"],
    )]
    out = tmp_path / "r.csv"
    generate_csv(results, out)

    rows = _read_csv(out)
    assert rows[0]["description"] == "Line 1\nLine 2\nLine 3"
    # ocr_text is a list that gets joined with ", " — the newlines inside
    # each item must survive the join.
    assert "Banner line 1\nBanner line 2" in rows[0]["ocr_text"]


def test_csv_round_trips_emoji_and_cjk(tmp_path):
    results = [_minimal(
        title="慶祝活動 🎉",
        description="一場盛大的慶祝活動 🎊✨",
        keywords=["慶祝", "🎉 派對", "event 2026"],
        identified_people=["張大明"],
        ocr_text=["映奧創意 🌟"],
    )]
    out = tmp_path / "r.csv"
    generate_csv(results, out)

    # UTF-8 round-trip — read raw bytes to rule out any escape shenanigans
    # that DictReader might hide.
    raw = out.read_bytes().decode("utf-8")
    assert "慶祝活動 🎉" in raw
    assert "🎊" in raw
    assert "張大明" in raw
    assert "映奧創意 🌟" in raw

    rows = _read_csv(out)
    assert rows[0]["title"] == "慶祝活動 🎉"
    assert "慶祝" in rows[0]["keywords"]


def test_csv_keyword_with_embedded_comma_stays_a_single_cell(tmp_path):
    """The existing implementation joins list fields with ', '. If one
    keyword itself contains a comma, downstream re-splitting will break.
    We can't fix the join strategy without backward-incompat breakage, but
    we CAN assert the behavior is stable and the CSV cell is intact
    (properly quoted so Excel sees one column, not many)."""
    results = [_minimal(
        keywords=["rock, paper, scissors", "normal"],
    )]
    out = tmp_path / "r.csv"
    generate_csv(results, out)

    rows = _read_csv(out)
    # One logical CSV cell despite embedded commas.
    assert rows[0]["keywords"] == "rock, paper, scissors, normal"


def test_csv_empty_results_writes_header_only(tmp_path):
    """G4 adjacent — empty result set must not crash and must still be a
    valid CSV (just the header row). Excel / pandas expect at least a
    header to identify columns."""
    out = tmp_path / "empty.csv"
    generate_csv([], out)

    raw = out.read_text(encoding="utf-8")
    # First non-empty line must be the header.
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 1
    for field in ("file_path", "title", "description", "keywords"):
        assert field in lines[0]


def test_json_report_preserves_unicode_and_structure(tmp_path):
    """G2 adjacent — JSON must use ensure_ascii=False so humans can actually
    read the output without \\uXXXX noise. Also structure (lists stay lists)
    must survive, unlike the CSV join-with-comma flattening."""
    results = [_minimal(
        title="阿伯演講 🎤",
        keywords=["演講", "event, 2026", "main stage"],
        people_count=42,
    )]
    out = tmp_path / "r.json"
    generate_json(results, out)

    raw = out.read_text(encoding="utf-8")
    # Literal CJK + emoji, not escaped.
    assert "阿伯演講 🎤" in raw

    import json
    parsed = json.loads(raw)
    assert parsed[0]["keywords"] == ["演講", "event, 2026", "main stage"]
    assert parsed[0]["people_count"] == 42
