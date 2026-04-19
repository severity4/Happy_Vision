"""tests/hardening/test_f5_long_description.py

Hardening F5: 超長描述（> IPTC 限制）自動截斷或警告。

IPTC IIM 的字元長度限制：
- Headline (2:105)           — 256 bytes
- Caption-Abstract (2:120)   — 2000 bytes
- Keywords (2:025)           — 64 bytes per item

Gemini prompt 要求 description 2-3 句英文 → 通常 200-400 chars，遠低於
2000 bytes。但 Gemini 偶爾會丟出過長的 list-style description，或者使用者
自訂 prompt 想要長描述。XMP 沒有這個限制。

合約：
- Caption-Abstract 超過 2000 bytes 時，寫入不崩（exiftool 會截斷或 warn）
- Headline 超過 256 bytes 也不崩
- Keyword 單項超過 64 bytes 也不崩
- Round-trip 讀回雖有截斷但仍是有效 UTF-8（不會切在 multibyte 中間爆）
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


def _read_back(photo: Path, tag: str):
    proc = subprocess.run(
        ["exiftool", "-j", f"-{tag}", str(photo)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)[0]
    return data.get(tag.split(":", 1)[1])


def test_long_iptc_caption_3000_bytes_does_not_crash(exiftool_required, tmp_path):
    """3000-byte description > 2000 IPTC cap. Write must still succeed
    (exiftool truncates and warns); photo must stay valid."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    long_desc = "A " * 1500  # 3000 bytes of ASCII
    assert len(long_desc) > 2000

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": long_desc,
        "keywords": [], "category": "other",
        "scene_type": "indoor", "mood": "neutral",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    })
    assert ok, "write_metadata returned False on 3000-byte caption"

    # File still readable
    assert photo.stat().st_size > 0
    with Image.open(photo) as img:
        img.verify()

    # XMP:Description has no such limit — stored in full
    xmp_desc = _read_back(photo, "XMP:Description")
    assert xmp_desc == long_desc


def test_extremely_long_description_10x_limit_still_safe(exiftool_required, tmp_path):
    """20000-byte description (10x IPTC limit). Regression guard against
    any code path that cap-checks against memory (not IPTC spec)."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    huge = "X" * 20000

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": huge,
        "keywords": [], "category": "other",
        "scene_type": "indoor", "mood": "neutral",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    })
    assert ok
    with Image.open(photo) as img:
        img.verify()


def test_long_cjk_description_truncation_is_utf8_safe(exiftool_required, tmp_path):
    """Core UTF-8 correctness: if exiftool truncates at a byte boundary,
    the result must still be valid UTF-8 (not cut mid-codepoint).

    Each Traditional Chinese char = 3 bytes in UTF-8. A long CJK desc
    over the 2000-byte limit forces the truncation path."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    # 1000 chars * 3 bytes ~= 3000 bytes → exceeds 2000-byte IPTC cap
    cjk_desc = "一位資深講者在舞台上侃侃而談，觀眾全神貫注，現場氣氛熱烈。" * 20

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": cjk_desc,
        "keywords": [], "category": "other",
        "scene_type": "indoor", "mood": "neutral",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    })
    assert ok

    # Caption-Abstract comes back as a str — truncated or not, must decode
    # cleanly (exiftool's own UTF-8 handling is expected to cut at codepoint
    # boundary; if not, the JSON parse below would already have failed).
    caption = _read_back(photo, "IPTC:Caption-Abstract")
    if caption is not None:
        assert isinstance(caption, str)
        # No replacement chars — that would indicate a cut-in-the-middle decode
        assert "\ufffd" not in caption


def test_long_headline_256_byte_limit(exiftool_required, tmp_path):
    """IPTC Headline limit is 256 bytes. Over-sized titles don't kill
    the write."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    long_title = "Very Long Event Title " * 50  # ~1150 bytes

    ok = mw.write_metadata(str(photo), {
        "title": long_title, "description": "d",
        "keywords": [], "category": "other",
        "scene_type": "indoor", "mood": "neutral",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    })
    assert ok, "write_metadata returned False on 1150-byte headline"

    # XMP:Title unconstrained — stored in full
    xmp_title = _read_back(photo, "XMP:Title")
    assert xmp_title == long_title


def test_long_keyword_over_64_byte_limit_does_not_abort_batch(
    exiftool_required, tmp_path,
):
    """IPTC Keywords limit is 64 bytes per item. A single long keyword
    must not abort a batch write that has other valid shorter keywords."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    long_kw = "x" * 200  # 200 bytes > 64 limit

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": "d",
        "keywords": ["short_ok", long_kw, "another_ok"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })
    assert ok, "overlong keyword killed the write"

    # XMP:Subject has no per-item limit — all 3 stored
    subject = _read_back(photo, "XMP:Subject")
    if isinstance(subject, str):
        subject = [subject]
    assert "short_ok" in subject
    assert "another_ok" in subject
    # long_kw may or may not be in IPTC (truncated) but XMP should have it
    assert long_kw in subject
