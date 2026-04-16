"""tests/test_folder_watcher.py — FolderWatcher unit tests"""

import os
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.folder_watcher import (
    FolderWatcher,
    WatcherCallbacks,
    file_size_stable,
    _scan_recursive,
)
from modules.result_store import ResultStore


def test_scan_recursive_finds_jpgs(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.jpeg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    (tmp_path / "skip.png").write_bytes(b"\x00" * 100)
    (tmp_path / ".hidden.jpg").write_bytes(b"\x00" * 100)

    results = _scan_recursive(str(tmp_path))
    names = {Path(p).name for p in results}
    assert names == {"a.jpg", "b.jpeg"}


def test_file_size_stable_returns_true_for_static_file(tmp_path):
    f = tmp_path / "test.jpg"
    f.write_bytes(b"\x00" * 1000)
    assert file_size_stable(str(f), stable_duration=0.3, interval=0.1)


def test_file_size_stable_returns_false_for_missing_file(tmp_path):
    assert not file_size_stable(str(tmp_path / "nope.jpg"), stable_duration=0.3, interval=0.1)


def test_file_size_stable_returns_false_for_empty_file(tmp_path):
    f = tmp_path / "empty.jpg"
    f.write_bytes(b"")
    assert not file_size_stable(str(f), stable_duration=0.3, interval=0.1)


def test_watcher_state_transitions(tmp_path):
    (tmp_path / "test.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    watcher = FolderWatcher()
    assert watcher.state == "stopped"

    with patch("modules.folder_watcher.load_config", return_value={
        "gemini_api_key": "test-key",
        "model": "lite",
        "watch_concurrency": 1,
        "watch_interval": 60,
    }):
        watcher.start(folder=str(tmp_path))
        assert watcher.state == "watching"

        watcher.pause()
        assert watcher.state == "paused"

        watcher.start()  # resume
        assert watcher.state == "watching"

        watcher.stop()
        assert watcher.state == "stopped"


def test_watcher_start_without_api_key(tmp_path):
    watcher = FolderWatcher()
    with patch("modules.folder_watcher.load_config", return_value={
        "gemini_api_key": "",
        "watch_concurrency": 1,
        "watch_interval": 60,
    }):
        try:
            watcher.start(folder=str(tmp_path))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "API key" in str(e)


def test_watcher_start_with_invalid_folder():
    watcher = FolderWatcher()
    with patch("modules.folder_watcher.load_config", return_value={
        "gemini_api_key": "test-key",
        "watch_concurrency": 1,
        "watch_interval": 60,
    }):
        try:
            watcher.start(folder="/nonexistent/path/xyz")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not accessible" in str(e)


def test_watcher_callbacks_called(tmp_path):
    events = []

    class TestCallbacks(WatcherCallbacks):
        def on_state_change(self, state):
            events.append(("state", state))

    watcher = FolderWatcher(callbacks=TestCallbacks())
    with patch("modules.folder_watcher.load_config", return_value={
        "gemini_api_key": "test-key",
        "model": "lite",
        "watch_concurrency": 1,
        "watch_interval": 60,
    }):
        watcher.start(folder=str(tmp_path))
        watcher.pause()
        watcher.stop()

    assert ("state", "watching") in events
    assert ("state", "paused") in events
    assert ("state", "stopped") in events


def test_watcher_set_concurrency():
    watcher = FolderWatcher()
    watcher.set_concurrency(5)
    assert watcher._concurrency == 5
    watcher.set_concurrency(0)
    assert watcher._concurrency == 1
    watcher.set_concurrency(99)
    assert watcher._concurrency == 10


def test_dedup_skips_completed_in_db(tmp_path):
    """Photos completed in local DB should be skipped."""
    photo = tmp_path / "done.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    store = ResultStore(tmp_path / "test.db")
    store.save_result(str(photo), {"title": "test"})

    watcher = FolderWatcher()
    watcher._folder = str(tmp_path)
    watcher._store = store

    watcher._scan_and_enqueue()
    assert watcher.queue_size == 0
    store.close()


def test_dedup_skips_iptc_tagged(tmp_path):
    """Photos with HappyVisionProcessed IPTC tag should be skipped."""
    photo = tmp_path / "tagged.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    store = ResultStore(tmp_path / "test.db")
    watcher = FolderWatcher()
    watcher._folder = str(tmp_path)
    watcher._store = store

    with patch("modules.folder_watcher.has_happy_vision_tag", return_value=True):
        with patch("modules.folder_watcher.file_size_stable", return_value=True):
            watcher._scan_and_enqueue()

    assert watcher.queue_size == 0
    store.close()


def test_dedup_enqueues_new_photo(tmp_path):
    """New photos without DB record or IPTC tag should be enqueued."""
    photo = tmp_path / "new.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    store = ResultStore(tmp_path / "test.db")
    watcher = FolderWatcher()
    watcher._folder = str(tmp_path)
    watcher._store = store

    with patch("modules.folder_watcher.has_happy_vision_tag", return_value=False):
        with patch("modules.folder_watcher.file_size_stable", return_value=True):
            watcher._scan_and_enqueue()

    assert watcher.queue_size == 1
    store.close()


def test_failed_photos_are_retried(tmp_path):
    """Photos marked as failed in DB should be re-enqueued."""
    photo = tmp_path / "failed.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    store = ResultStore(tmp_path / "test.db")
    store.mark_failed(str(photo), "API error")

    watcher = FolderWatcher()
    watcher._folder = str(tmp_path)
    watcher._store = store

    with patch("modules.folder_watcher.file_size_stable", return_value=True):
        watcher._scan_and_enqueue()

    assert watcher.queue_size == 1
    store.close()
