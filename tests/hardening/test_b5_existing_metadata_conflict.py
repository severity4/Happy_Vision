"""tests/hardening/test_b5_existing_metadata_conflict.py

Hardening B5: 照片已有 IPTC / XMP metadata 時，寫入新分析結果不可默默洗掉
使用者手動打的 keywords。

真實情境：
- 攝影師先在 Lightroom 幫照片打好「wedding, bride」
- 匯出後跑 Happy Vision
- Gemini 回「ceremony, celebration, vows」
- 期望結果：keywords = [wedding, bride, ceremony, celebration, vows]
- **舊行為（bug）**：keywords = [ceremony, celebration, vows] ← 手動標籤消失

Root cause：`build_exiftool_args` 用 `-IPTC:Keywords=VAL` 而不是 `+=`，
exiftool 對 list-type tag 的 `=` 第一次會清掉整個列表。

合約：
- 對 list-type tag（IPTC:Keywords / XMP:Subject）用 `+=`，既有值保留
- 對 scalar tag（Title / Description / Category / Mood）用 `=`（AI 產出本
  來就是要覆蓋 AI 產出，無損失）
- 重跑相同 AI 輸出會 dup keywords，屬於已知限制（folder_watcher 已用
  `HappyVisionProcessed` 標記避免重跑，所以實務上不觸發）
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from modules import metadata_writer as mw


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


@pytest.fixture
def exiftool_required():
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed")


# ---------- unit tests on build_exiftool_args ----------

def test_build_args_uses_append_for_iptc_keywords():
    """Regression guard: IPTC:Keywords MUST be set with `+=`, not `=`. The
    list-type semantics of exiftool mean `=` wipes existing user-typed tags."""
    args = mw.build_exiftool_args({
        "title": "t", "description": "d",
        "keywords": ["ai_a", "ai_b"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })

    keyword_args = [a for a in args if a.startswith("-IPTC:Keywords")]
    assert keyword_args, "must emit at least one -IPTC:Keywords arg"
    for a in keyword_args:
        assert "+=" in a, (
            f"IPTC:Keywords uses destructive `=` (would wipe user's manual "
            f"tags). Found: {a!r}. Must be `-IPTC:Keywords+=value`."
        )


def test_build_args_uses_append_for_xmp_subject():
    """Lightroom writes user tags to XMP:Subject — same preservation
    requirement as IPTC:Keywords."""
    args = mw.build_exiftool_args({
        "keywords": ["ai_x"],
        "title": "t", "description": "d",
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })

    subject_args = [a for a in args if a.startswith("-XMP:Subject")]
    assert subject_args, "must emit at least one -XMP:Subject arg"
    for a in subject_args:
        assert "+=" in a, f"-XMP:Subject must use `+=` to merge, not replace. Found: {a!r}"


def test_build_args_still_uses_equals_for_scalar_tags():
    """Regression guard: Title / Description / Category / Mood are scalar.
    They're 100% AI output so straight replacement is correct. Don't
    accidentally `+=` them — that silently corrupts scalar tags."""
    args = mw.build_exiftool_args({
        "title": "new title", "description": "new desc",
        "keywords": [], "category": "ceremony",
        "subcategory": "wedding", "scene_type": "indoor",
        "mood": "formal", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })

    # Build scalar-tag prefixes; every one of their args must use single `=`.
    for a in args:
        if a.startswith(("-IPTC:Keywords", "-XMP:Subject")):
            continue
        # scalar tags: single `=`, no `+=`
        assert "+=" not in a, f"scalar tag must not use `+=`: {a!r}"


# ---------- integration: real exiftool writes preserve manual tags ----------

def test_write_metadata_preserves_manual_iptc_keywords(tmp_path, exiftool_required):
    """End-to-end: user wrote a manual keyword via exiftool, then Happy
    Vision writes AI keywords. Both must survive in the final file."""
    import subprocess

    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    # Simulate user (or Lightroom export) having pre-populated keywords.
    subprocess.run(
        ["exiftool", "-overwrite_original",
         "-IPTC:Keywords=wedding", "-IPTC:Keywords=bride",
         str(photo)],
        check=True, capture_output=True,
    )

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": "d",
        "keywords": ["ceremony", "celebration"],
        "category": "ceremony", "scene_type": "indoor",
        "mood": "formal", "people_count": 2,
        "identified_people": [], "ocr_text": [],
    })
    assert ok

    # Read back — all four keywords must be present.
    proc = subprocess.run(
        ["exiftool", "-j", "-IPTC:Keywords", str(photo)],
        check=True, capture_output=True, text=True,
    )
    import json
    data = json.loads(proc.stdout)
    keywords = data[0].get("Keywords", [])
    if isinstance(keywords, str):
        keywords = [keywords]

    assert "wedding" in keywords, (
        f"manual keyword 'wedding' was destroyed by AI write. Got: {keywords}"
    )
    assert "bride" in keywords, (
        f"manual keyword 'bride' was destroyed by AI write. Got: {keywords}"
    )
    assert "ceremony" in keywords
    assert "celebration" in keywords


def test_write_metadata_preserves_manual_xmp_subject(tmp_path, exiftool_required):
    """Lightroom writes to XMP:Subject (not IPTC:Keywords) — same concern."""
    import subprocess

    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    subprocess.run(
        ["exiftool", "-overwrite_original",
         "-XMP:Subject=lightroom_manual",
         str(photo)],
        check=True, capture_output=True,
    )

    ok = mw.write_metadata(str(photo), {
        "title": "t", "description": "d",
        "keywords": ["ai_kw"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })
    assert ok

    proc = subprocess.run(
        ["exiftool", "-j", "-XMP:Subject", str(photo)],
        check=True, capture_output=True, text=True,
    )
    import json
    data = json.loads(proc.stdout)
    subject = data[0].get("Subject", [])
    if isinstance(subject, str):
        subject = [subject]

    assert "lightroom_manual" in subject, (
        f"Lightroom manual tag lost. Got: {subject}"
    )
    assert "ai_kw" in subject


def test_write_metadata_overwrites_scalar_title_and_description(tmp_path, exiftool_required):
    """Regression: scalar tags (Headline, Caption-Abstract) SHOULD overwrite.
    AI output is authoritative for these — it would be wrong to append."""
    import subprocess

    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    # Pre-populate with old AI title/description.
    subprocess.run(
        ["exiftool", "-overwrite_original",
         "-IPTC:Headline=old_title",
         "-IPTC:Caption-Abstract=old_description",
         str(photo)],
        check=True, capture_output=True,
    )

    ok = mw.write_metadata(str(photo), {
        "title": "new_title", "description": "new_description",
        "keywords": [], "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    })
    assert ok

    proc = subprocess.run(
        ["exiftool", "-j", "-IPTC:Headline", "-IPTC:Caption-Abstract", str(photo)],
        check=True, capture_output=True, text=True,
    )
    import json
    data = json.loads(proc.stdout)[0]
    assert data.get("Headline") == "new_title"
    assert data.get("Caption-Abstract") == "new_description"
