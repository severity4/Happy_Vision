"""tests/hardening/test_d6_sqlite_corruption.py

Hardening D6: results.db 損壞 → ResultStore 偵測到並 fallback 到
`~/.happy-vision-fallback/`，不直接 crash。

真實場景：
- 硬碟掉 WAL 寫入、突然斷電、外接碟拔掉 → SQLite file 被截斷或寫入一半
- 同事試圖「修」成 txt 開來看，存檔時編輯器污染 header
- 其他 app 誤把 file 當另一個格式 import

合約：ResultStore 構造時如果 `sqlite3.connect + PRAGMA/CREATE` 失敗，走
fallback 路徑；fallback 後 save_result / is_processed 等 API 正常運作。
"""

from __future__ import annotations

from pathlib import Path

from modules.result_store import ResultStore


def _write_corrupt_db(path: Path) -> None:
    """Write bytes that LOOK like a SQLite file (correct magic) but whose
    pages are corrupted. sqlite3.connect() won't raise on open; the error
    surfaces on the first PRAGMA / CREATE TABLE attempt inside _init_db."""
    # Valid SQLite header magic ("SQLite format 3\x00") but garbage after.
    header = b"SQLite format 3\x00"
    garbage = b"\x00\xFF" * 512  # clearly not valid page layout
    path.write_bytes(header + garbage)


def _write_non_sqlite_file(path: Path) -> None:
    """Not even close to a SQLite file — plain text."""
    path.write_text("not a database at all, just notes")


def test_corrupt_db_falls_back_cleanly(tmp_path, monkeypatch):
    """When the primary DB path is corrupt, ResultStore should complete
    construction via the fallback path and be usable for save/read."""
    # Redirect fallback location to the test tmp (so we don't pollute
    # the developer's real ~/.happy-vision-fallback).
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: fake_home))

    corrupt = tmp_path / "corrupt.db"
    _write_corrupt_db(corrupt)

    store = ResultStore(corrupt)
    try:
        # Should be usable. save_result must succeed.
        store.save_result(
            "/tmp/p.jpg",
            {
                "title": "t",
                "description": "d",
                "keywords": [],
                "category": "other",
                "scene_type": "indoor",
                "mood": "neutral",
                "people_count": 0,
            },
        )
        assert store.is_processed("/tmp/p.jpg") is True
    finally:
        store.close()

    # The store's db_path should have moved to the fallback dir, NOT the
    # original corrupt location.
    fallback_dir = fake_home / ".happy-vision-fallback"
    assert fallback_dir.exists()
    assert store.db_path.parent == fallback_dir


def test_non_sqlite_file_falls_back_cleanly(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: fake_home))

    garbage = tmp_path / "garbage.db"
    _write_non_sqlite_file(garbage)

    store = ResultStore(garbage)
    try:
        # Fallback DB is usable.
        store.save_result(
            "/tmp/p.jpg",
            {
                "title": "t",
                "description": "d",
                "keywords": [],
                "category": "other",
                "scene_type": "indoor",
                "mood": "neutral",
                "people_count": 0,
            },
        )
        assert store.is_processed("/tmp/p.jpg") is True
    finally:
        store.close()

    # Original corrupt file untouched — user can still rescue / inspect.
    assert garbage.exists()


def test_fallback_preserves_name_not_just_generic_file(tmp_path, monkeypatch):
    """Fallback file should keep the original basename so multiple runs
    with distinct db names don't collide in the fallback dir."""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: fake_home))

    corrupt = tmp_path / "project-x-results.db"
    _write_corrupt_db(corrupt)

    store = ResultStore(corrupt)
    try:
        assert store.db_path.name == "project-x-results.db"
    finally:
        store.close()


def test_parent_dir_not_writable_also_falls_back(tmp_path, monkeypatch):
    """_resolve_db_path handles a parent that can't be written. We
    simulate by passing a DB path whose parent is a file (so mkdir
    fails) — stdlib raises FileExistsError / OSError that maps to
    SQLite error internally."""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: fake_home))

    # Create a regular file where the DB's parent dir would have to be.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    target = blocker / "results.db"  # parent is a file, mkdir will fail

    store = ResultStore(target)
    try:
        # Fallback should be in the test-fake home.
        assert store.db_path.parent == fake_home / ".happy-vision-fallback"
        # And usable.
        store.save_result(
            "/tmp/p.jpg",
            {
                "title": "t", "description": "d", "keywords": [],
                "category": "other", "scene_type": "indoor",
                "mood": "neutral", "people_count": 0,
            },
        )
    finally:
        store.close()


def test_readable_db_not_affected_by_fallback_logic(tmp_path, monkeypatch):
    """Regression guard: valid DB path must NOT be spuriously moved to
    the fallback dir just because the fallback logic exists."""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: fake_home))

    target = tmp_path / "happy.db"

    store = ResultStore(target)
    try:
        assert store.db_path == target
        # Fallback dir should NOT be created for a happy-path init.
        assert not (fake_home / ".happy-vision-fallback").exists()
    finally:
        store.close()
