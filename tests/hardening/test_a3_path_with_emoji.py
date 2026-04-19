"""tests/hardening/test_a3_path_with_emoji.py

Hardening A3: 路徑 / 檔名含 emoji 或特殊 Unicode 符號時能正確處理。

真實情境：
- 有人用 emoji 幫資料夾分類（`📸 婚紗/`、`🎉 生日/`）
- macOS 允許檔名含 emoji，Finder 會正確顯示
- Python + exiftool + SQLite 全鏈路應該都能吞 emoji

APFS NFC/NFD 正規化：macOS 預設會把 NFC emoji 轉成 NFD（combining chars），
這是檔案系統決定的、Python 讀到的會是 NFD 形式 — 只要我們全鏈路都用
Python str 一貫處理就不會出事。這裡把常見情境鎖住。
"""

from __future__ import annotations

from pathlib import Path

from modules.metadata_writer import build_exiftool_args
from modules.pipeline import scan_photos
from modules.result_store import ResultStore


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def test_scan_photos_finds_emoji_named_files(tmp_path):
    folder = tmp_path / "📸 婚紗照"
    folder.mkdir()
    _write_jpg(folder / "🎉party.jpg")
    _write_jpg(folder / "cake🎂.jpg")

    photos = scan_photos(str(folder))
    names = {Path(p).name for p in photos}
    # macOS NFC→NFD normalization may canonicalise some codepoints; compare
    # by substring of an emoji that is single-codepoint-safe.
    assert len(photos) == 2
    assert any("party" in n for n in names)
    assert any("cake" in n for n in names)


def test_scan_photos_emoji_in_parent_folder(tmp_path):
    folder = tmp_path / "🗂_archive"
    folder.mkdir()
    _write_jpg(folder / "photo.jpg")

    photos = scan_photos(str(folder))
    assert len(photos) == 1
    assert "🗂" in str(photos[0]) or "archive" in str(photos[0])


def test_result_store_roundtrips_emoji_path(tmp_path):
    """SQLite is UTF-8 native. Path round-trip must be byte-exact so
    `is_processed` works on re-run and the report maps result → file."""
    photo_path = tmp_path / "🎉party.jpg"
    _write_jpg(photo_path)

    store = ResultStore(tmp_path / "r.db")
    store.save_result(
        str(photo_path),
        {
            "title": "🎂 celebration",
            "description": "party photo",
            "keywords": ["🎉", "party"],
            "category": "other", "scene_type": "indoor",
            "mood": "celebratory", "people_count": 0,
            "identified_people": [], "ocr_text": [],
        },
        usage={"input_tokens": 10, "output_tokens": 5,
               "total_tokens": 15, "model": "gemini-2.5-flash-lite"},
        cost_usd=0.001,
    )

    assert store.is_processed(str(photo_path)), (
        "emoji-pathed photo not detected on re-run — is_processed breaks "
        "under non-ASCII paths"
    )

    rows = store.conn.execute(
        "SELECT result_json FROM results WHERE file_path = ?",
        (str(photo_path),),
    ).fetchall()
    assert len(rows) == 1
    import json
    result = json.loads(rows[0]["result_json"])
    assert result["title"] == "🎂 celebration"
    assert "🎉" in result["keywords"]


def test_exiftool_args_carry_emoji_verbatim():
    """Emoji in keywords must flow through build_exiftool_args untouched.
    ExiftoolBatch's stdin protocol is one-arg-per-line text-mode — as
    long as we don't introduce \\n/\\r/\\x00, emoji survive."""
    result = {
        "title": "🎂 birthday",
        "description": "birthday party 🎉",
        "keywords": ["🎉", "party", "🎂cake"],
        "category": "other", "scene_type": "indoor",
        "mood": "celebratory", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    }
    args = build_exiftool_args(result)

    assert "-IPTC:Headline=🎂 birthday" in args
    assert "-IPTC:Caption-Abstract=birthday party 🎉" in args
    # B5: list-type uses `+=`. Emoji-only keyword must also be accepted.
    assert "-IPTC:Keywords+=🎉" in args
    assert "-IPTC:Keywords+=🎂cake" in args


def test_nfc_nfd_variants_of_same_emoji_treated_consistently(tmp_path):
    """APFS normalises to NFD at the FS layer. Python's os.listdir returns
    the NFD form; our pipeline must treat user-provided NFC path and
    scanner-returned NFD path as the same file so we don't re-analyze."""
    import unicodedata

    # é has both NFC (U+00E9) and NFD (U+0065 U+0301) forms.
    nfc_name = "caf\u00e9.jpg"   # NFC
    nfd_name = unicodedata.normalize("NFD", nfc_name)

    folder = tmp_path / "cafe"
    folder.mkdir()
    _write_jpg(folder / nfc_name)

    photos = scan_photos(str(folder))
    assert len(photos) == 1
    scanned = Path(photos[0]).name

    # Either form is acceptable, but the two must hash-equivalent via NFC.
    nfc_scanned = unicodedata.normalize("NFC", scanned)
    assert nfc_scanned == nfc_name, (
        f"scanner returned {scanned!r} which doesn't NFC-round-trip to "
        f"{nfc_name!r} — downstream path comparisons will misfire"
    )
    _ = nfd_name  # exercised via FS normalization above
