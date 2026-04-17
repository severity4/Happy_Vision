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


def test_failed_photos_are_skipped(tmp_path):
    """Photos marked as failed in DB should NOT be re-enqueued."""
    photo = tmp_path / "failed.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    store = ResultStore(tmp_path / "test.db")
    store.mark_failed(str(photo), "API error")

    watcher = FolderWatcher()
    watcher._folder = str(tmp_path)
    watcher._store = store

    with patch("modules.folder_watcher.file_size_stable", return_value=True):
        watcher._scan_and_enqueue()

    assert watcher.queue_size == 0
    store.close()


def test_stop_waits_for_in_flight_workers(tmp_path, monkeypatch):
    """stop() must not close the store while workers are still writing."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks
    import time

    # Seed 3 photos
    for i in range(3):
        (tmp_path / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    # Mock analyze_photo to simulate slow Gemini call
    enter = threading.Event()
    proceed = threading.Event()
    errors_seen = []

    def slow_analyze(path, **kw):
        enter.set()
        # Block until test releases us
        proceed.wait(timeout=5)
        return {"title": "T", "keywords": [], "description": "",
                "category": "other", "scene_type": "indoor",
                "mood": "neutral", "people_count": 0}

    monkeypatch.setattr(fw, "analyze_photo", slow_analyze)
    monkeypatch.setattr(fw, "has_happy_vision_tag", lambda p: False)
    monkeypatch.setattr(fw, "file_size_stable", lambda p, **kw: True)
    monkeypatch.setattr(fw, "load_config",
                        lambda: {"gemini_api_key": "k", "watch_concurrency": 2,
                                 "watch_interval": 1, "model": "lite"})

    class CB(WatcherCallbacks):
        def on_error(self, path, err):
            errors_seen.append((path, err))

    # Use a db in tmp_path so we don't touch the real one
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    watcher = FolderWatcher(CB())
    watcher.start(folder=str(tmp_path))

    # Enqueue synchronously
    watcher.enqueue_folder(str(tmp_path))

    # Wait until at least one worker has entered analyze_photo
    assert enter.wait(timeout=5), "Worker did not start"

    # Now stop. It must wait for the in-flight worker(s) to finish.
    stop_thread = threading.Thread(target=watcher.stop)
    stop_thread.start()

    # Let workers proceed
    time.sleep(0.1)
    proceed.set()

    stop_thread.join(timeout=10)
    assert not stop_thread.is_alive(), "stop() hung"

    # No errors from "Cannot operate on a closed database"
    for _, err in errors_seen:
        assert "closed" not in err.lower()
        assert "programmingerror" not in err.lower()


def test_watcher_uses_exiftool_batch_and_writes_before_save(tmp_path, monkeypatch):
    """_process_one must call ExiftoolBatch.write before save_result; if
    batch.write fails, save_result must not be called (mark_failed instead)."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks

    (tmp_path / "p.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    calls = []

    class SpyBatch:
        def __init__(self):
            calls.append(("batch_init",))
        def write(self, path, args):
            calls.append(("batch_write", path))
            return True
        def close(self):
            calls.append(("batch_close",))

    monkeypatch.setattr(fw, "ExiftoolBatch", SpyBatch)
    monkeypatch.setattr(
        fw, "analyze_photo",
        lambda path, **kw: {"title": "T", "keywords": [], "description": "",
                            "category": "other", "scene_type": "indoor",
                            "mood": "neutral", "people_count": 0},
    )
    monkeypatch.setattr(fw, "has_happy_vision_tag", lambda p: False)
    monkeypatch.setattr(fw, "file_size_stable", lambda p, **kw: True)
    monkeypatch.setattr(
        fw, "load_config",
        lambda: {"gemini_api_key": "k", "watch_concurrency": 1,
                 "watch_interval": 1, "model": "lite"},
    )
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    # Spy on save_result
    save_calls = []
    orig_save = fw.ResultStore.save_result
    def track_save(self, path, data):
        save_calls.append(path)
        orig_save(self, path, data)
    monkeypatch.setattr(fw.ResultStore, "save_result", track_save)

    watcher = FolderWatcher(WatcherCallbacks())
    watcher.start(folder=str(tmp_path))
    watcher.enqueue_folder(str(tmp_path))

    # Wait until processing settles
    for _ in range(50):
        if save_calls:
            break
        time.sleep(0.1)

    watcher.stop()

    # Batch used (init + write + close at least once each)
    assert any(c[0] == "batch_init" for c in calls)
    assert any(c[0] == "batch_write" for c in calls)
    assert any(c[0] == "batch_close" for c in calls)
    assert len(save_calls) == 1


def test_watcher_metadata_failure_marks_failed_not_completed(tmp_path, monkeypatch):
    """If ExiftoolBatch.write returns False, save_result must NOT be called;
    mark_failed must be called instead."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks

    (tmp_path / "p.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    class FailingBatch:
        def __init__(self): pass
        def write(self, path, args): return False
        def close(self): pass

    monkeypatch.setattr(fw, "ExiftoolBatch", FailingBatch)
    monkeypatch.setattr(
        fw, "analyze_photo",
        lambda path, **kw: {"title": "T", "keywords": [], "description": "",
                            "category": "other", "scene_type": "indoor",
                            "mood": "neutral", "people_count": 0},
    )
    monkeypatch.setattr(fw, "has_happy_vision_tag", lambda p: False)
    monkeypatch.setattr(fw, "file_size_stable", lambda p, **kw: True)
    monkeypatch.setattr(
        fw, "load_config",
        lambda: {"gemini_api_key": "k", "watch_concurrency": 1,
                 "watch_interval": 1, "model": "lite"},
    )
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    errors = []
    class CB(WatcherCallbacks):
        def on_error(self, path, err): errors.append((path, err))

    watcher = FolderWatcher(CB())
    watcher.start(folder=str(tmp_path))
    watcher.enqueue_folder(str(tmp_path))

    for _ in range(50):
        if errors:
            break
        time.sleep(0.1)

    watcher.stop()

    assert len(errors) == 1
    assert "metadata" in errors[0][1].lower()

    # Verify DB status is 'failed', not 'completed'
    from modules.result_store import ResultStore
    store = ResultStore()
    status = store.get_status(str(tmp_path / "p.jpg"))
    store.close()
    assert status == "failed"


def test_set_concurrency_rebuilds_executor(tmp_path, monkeypatch):
    """set_concurrency should replace the executor, not modify private attrs."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks

    monkeypatch.setattr(fw, "load_config",
                        lambda: {"gemini_api_key": "k", "watch_concurrency": 2,
                                 "watch_interval": 1, "model": "lite"})
    monkeypatch.setattr(fw, "has_happy_vision_tag", lambda p: False)
    monkeypatch.setattr(fw, "ExiftoolBatch", lambda: type("B", (), {
        "close": lambda self: None, "write": lambda self, p, a: True,
    })())
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    watcher = FolderWatcher(WatcherCallbacks())
    watcher.start(folder=str(tmp_path))

    old_executor = watcher._executor
    assert old_executor is not None
    assert old_executor._max_workers == 2

    watcher.set_concurrency(5)

    # Executor object must be different
    assert watcher._executor is not old_executor
    assert watcher._executor._max_workers == 5
    # Old executor should be shut down
    assert old_executor._shutdown

    watcher.stop()


def test_set_concurrency_clamps_to_bounds(tmp_path, monkeypatch):
    """set_concurrency clamps to [1, 10] per existing behavior."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks

    monkeypatch.setattr(fw, "load_config",
                        lambda: {"gemini_api_key": "k", "watch_concurrency": 2,
                                 "watch_interval": 1, "model": "lite"})
    monkeypatch.setattr(fw, "ExiftoolBatch", lambda: type("B", (), {
        "close": lambda self: None, "write": lambda self, p, a: True,
    })())
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    watcher = FolderWatcher(WatcherCallbacks())
    watcher.start(folder=str(tmp_path))

    watcher.set_concurrency(0)
    assert watcher._concurrency == 1

    watcher.set_concurrency(100)
    assert watcher._concurrency == 10

    watcher.stop()


def test_set_concurrency_idempotent_at_same_value(tmp_path, monkeypatch):
    """Calling set_concurrency with the current value should NOT rebuild."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks

    monkeypatch.setattr(fw, "load_config",
                        lambda: {"gemini_api_key": "k", "watch_concurrency": 3,
                                 "watch_interval": 1, "model": "lite"})
    monkeypatch.setattr(fw, "ExiftoolBatch", lambda: type("B", (), {
        "close": lambda self: None, "write": lambda self, p, a: True,
    })())
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    watcher = FolderWatcher(WatcherCallbacks())
    watcher.start(folder=str(tmp_path))

    old_executor = watcher._executor
    watcher.set_concurrency(3)
    assert watcher._executor is old_executor

    watcher.stop()


def test_scan_skips_failed_photos(tmp_path, monkeypatch):
    """_scan_folder_into_queue must NOT re-enqueue photos already marked failed."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks
    from modules.result_store import ResultStore

    (tmp_path / "p1.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (tmp_path / "p2.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))
    monkeypatch.setattr(fw, "has_happy_vision_tag", lambda p: False)
    monkeypatch.setattr(fw, "file_size_stable", lambda p, **kw: True)

    # Pre-seed: p1 is failed, p2 is new
    store = ResultStore()
    store.mark_failed(str(tmp_path / "p1.jpg"), "prior failure")
    store.close()

    watcher = FolderWatcher(WatcherCallbacks())
    watcher._store = ResultStore()
    enqueued, skipped = watcher._scan_folder_into_queue(str(tmp_path))
    watcher._store.close()

    assert enqueued == 1  # only p2
    assert skipped == 1  # p1 skipped because failed
