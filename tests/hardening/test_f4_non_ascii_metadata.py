"""tests/hardening/test_f4_non_ascii_metadata.py

Hardening F4: 寫入 non-ASCII 關鍵字（中文、日文、特殊字元）編碼正確。

真實情境：映奧大量中文活動名 + 人名寫進 Keywords。IPTC 在歷史上只支 Latin-1
（1980s 設計），新規範走 UTF-8（需要寫入 CodedCharacterSet=UTF8）。如果
exiftool 的 charset 沒設對，中文會變亂碼或問號。

合約：
- 寫 IPTC:Keywords 含中文 / 日文 / 韓文 → 讀回一致，不亂碼
- XMP:Subject（UTF-8 native）同樣 round-trip 正確
- IPTC:Caption-Abstract 長中文字串正確寫入
- 特殊符號（「」『』—·）不被 mangle
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from modules import metadata_writer as mw


def _write_jpg(path: Path) -> None:
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


@pytest.fixture
def exiftool_required():
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed")


def _read_back(photo: Path, tag: str) -> object:
    proc = subprocess.run(
        ["exiftool", "-j", f"-{tag}", str(photo)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)[0]
    # Strip the tag prefix (e.g. IPTC:Keywords → Keywords)
    return data.get(tag.split(":", 1)[1])


def test_cjk_keywords_round_trip(exiftool_required, tmp_path):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": "d",
        "keywords": ["講者", "活動", "婚禮", "致詞"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })
    assert ok

    keywords = _read_back(photo, "IPTC:Keywords")
    if isinstance(keywords, str):
        keywords = [keywords]
    for expected in ("講者", "活動", "婚禮", "致詞"):
        assert expected in keywords, (
            f"CJK keyword {expected!r} missing from round-trip: {keywords!r}"
        )


def test_japanese_and_korean_keywords_round_trip(exiftool_required, tmp_path):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    ok = mw.write_metadata(str(photo), {
        "title": "混合語言", "description": "multilingual",
        "keywords": ["セレモニー", "スピーチ", "축하", "결혼식"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })
    assert ok

    keywords = _read_back(photo, "IPTC:Keywords")
    if isinstance(keywords, str):
        keywords = [keywords]
    for expected in ("セレモニー", "スピーチ", "축하", "결혼식"):
        assert expected in keywords


def test_xmp_subject_carries_unicode_correctly(exiftool_required, tmp_path):
    """XMP is UTF-8 native — Lightroom round-trips unicode here."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": "d",
        "keywords": ["專業攝影", "映奧創意"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })
    assert ok

    subject = _read_back(photo, "XMP:Subject")
    if isinstance(subject, str):
        subject = [subject]
    assert "專業攝影" in subject
    assert "映奧創意" in subject


def test_long_cjk_caption_preserved(exiftool_required, tmp_path):
    """A 200-char Traditional Chinese description survives."""
    long_desc = "一位身穿西裝的年長男性站在講台上對著麥克風演講，背景投影幕打著「映奧創意 2026 年度大會」，台下坐滿與會者，整體氛圍莊重而正式。" * 2

    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    ok = mw.write_metadata(str(photo), {
        "title": "年度大會致詞",
        "description": long_desc,
        "keywords": [],
        "category": "other", "scene_type": "indoor",
        "mood": "formal", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })
    assert ok

    caption = _read_back(photo, "IPTC:Caption-Abstract")
    # IPTC Caption-Abstract has a 2000-char limit; our input is well under.
    # Must not come back mangled or truncated mid-multibyte.
    assert caption is not None
    assert "映奧創意" in caption
    assert "年度大會" in caption


def test_special_punctuation_round_trip(exiftool_required, tmp_path):
    """Fullwidth brackets 「」『』 / en-dash — / middle dot · / ellipsis …
    all common in CJK event naming conventions."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    title = "2026「 映奧 · 年度大會」—— 致詞片段…"
    keywords = ["『特邀講者』", "中場·休息", "上午10：30—12：00"]

    ok = mw.write_metadata(str(photo), {
        "title": title, "description": "d",
        "keywords": keywords, "category": "other",
        "scene_type": "indoor", "mood": "formal",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    })
    assert ok

    headline = _read_back(photo, "IPTC:Headline")
    assert headline == title

    kw_readback = _read_back(photo, "IPTC:Keywords")
    if isinstance(kw_readback, str):
        kw_readback = [kw_readback]
    for kw in keywords:
        assert kw in kw_readback, f"punctuation mangled for {kw!r}: {kw_readback!r}"
