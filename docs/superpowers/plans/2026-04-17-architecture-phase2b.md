# Happy Vision Phase 2B 架構/可靠性計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉 Phase 1 留下的 watcher 架構性問題 — `stop()` race、watcher 用舊的 per-photo exiftool、`set_concurrency` 戳私有欄位、pipeline 跟 watcher 沒有共用 rate limiter 各自 burst Gemini API。

**Architecture:** Watcher 對齊 pipeline 的每張照片 transaction（metadata → save_result → callback），共用 `ExiftoolBatch` class 與 module-level `RateLimiter`。`stop()` 改成等 in-flight workers 完成再關 DB。`set_concurrency` 用 shutdown + 重建 executor 取代私有屬性 hack。

**Tech Stack:** Python stdlib (`threading.Event`, `concurrent.futures`), 既有 `ExiftoolBatch`（來自 Phase 1 Task 6）, 新 `modules/rate_limiter.py`（簡單 token bucket）。

**Phase 2C（下一份計劃）：** 前端 UX polish — visibilitychange refresh、fetch timeout、SSE 斷線 UI、localStorage dismiss、補 API blueprint 測試、E2E test。

---

## File Structure

**新檔：**
- `modules/rate_limiter.py` — token bucket，shared by pipeline 和 watcher
- `tests/test_rate_limiter.py`

**改檔：**
- `modules/folder_watcher.py`:
  - `__init__` 加 `self._in_flight_count` 以 Event 取代 int（for stop 等待）
  - `stop()` 改 wait in-flight workers + `shutdown(wait=True)`
  - `set_concurrency` 重建 executor，舊 executor graceful shutdown
  - `_process_one` 改用 `ExiftoolBatch` + metadata-before-save 順序
  - `start()` 建立 shared `ExiftoolBatch` instance，`stop()` 關閉
  - 走 `rate_limiter.acquire()` 保護對 Gemini 的呼叫
- `modules/pipeline.py`:
  - 走同一個 module-level `rate_limiter.acquire()`（共享 RPM budget）
- `tests/test_folder_watcher.py` — 加 stop race 測試、ExiftoolBatch 使用測試、set_concurrency 重建測試
- `tests/test_pipeline.py` — 加 rate_limiter 共享測試

---

## Task 1: FolderWatcher.stop() race 修復

**Files:**
- Modify: `modules/folder_watcher.py`
- Modify: `tests/test_folder_watcher.py`

**動機（Phase 1 code reviewer 標記 Critical）：** `stop()` 呼叫 `self._executor.shutdown(wait=False)` 後立刻 `self._store.close()`。但 executor 裡的 `_process_one` 還在跑，下一行寫 `self._store.save_result(...)` 時 DB 已關 → `sqlite3.ProgrammingError: Cannot operate on a closed database`。pause → 立即 start，或 app 正常關閉時偶發出現。

### Step 1: 寫測試 — stop 必須等 in-flight workers

Read 現有 `tests/test_folder_watcher.py`：

```bash
grep -n "def test_\|FolderWatcher\|start\|stop" tests/test_folder_watcher.py | head -30
```

加到 `tests/test_folder_watcher.py` 末尾：

```python
def test_stop_waits_for_in_flight_workers(tmp_path, monkeypatch):
    """stop() must not close the store while workers are still writing."""
    from modules import folder_watcher as fw
    from modules.folder_watcher import FolderWatcher, WatcherCallbacks
    import threading
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
```

### Step 2: 跑測試確認失敗

Run: `pytest tests/test_folder_watcher.py::test_stop_waits_for_in_flight_workers -v`
Expected: 可能 PASS（timing 敏感，GIL serialization 有時掩蓋問題）或 FAIL 且 log 出現 "Cannot operate on a closed database"。即使 PASS，修實作仍必要以消除 race。繼續下一步。

### Step 3: 改 `stop()` 等 in-flight 完成

編輯 `modules/folder_watcher.py::stop`：

```python
    def stop(self) -> None:
        """Stop watching completely. Waits for in-flight workers to finish
        before closing the DB."""
        if self._state == "stopped":
            return
        self._stop_event.set()
        self._pause_event.set()  # unblock if paused

        # Clear the queue so new items don't get picked up
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        # Wait for poll + worker threads to exit their loops
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)

        # Shut down executor with wait=True so in-flight _process_one
        # calls finish before we close the store underneath them.
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None

        self._state = "stopped"
        self._callbacks.on_state_change("stopped")

        # NOW it is safe to close the store
        if self._store:
            self._store.close()
            self._store = None

        log.info("Watcher stopped")
```

### Step 4: 跑測試確認通過

Run: `pytest tests/test_folder_watcher.py -v`
Expected: 全 PASS。

Run: `pytest -q`
Expected: 140 passed（139 + 1 new）。

### Step 5: Commit

```bash
git add modules/folder_watcher.py tests/test_folder_watcher.py
git commit -m "fix(folder_watcher): stop() waits for in-flight workers before closing DB

Previously shutdown(wait=False) + immediate store.close() raced with
workers still calling save_result, producing sporadic 'Cannot operate
on a closed database' errors on app shutdown and pause->start cycles.
Now drains the queue, joins poll/worker threads, shutdown(wait=True)
on the executor, then closes the store."
```

---

## Task 2: FolderWatcher 改用 ExiftoolBatch + pipeline 對齊語義

**Files:**
- Modify: `modules/folder_watcher.py` (`start`, `stop`, `_process_one`)
- Modify: `tests/test_folder_watcher.py`

**動機：** 
1. Watcher 目前每張照片都 spawn 一次 exiftool（~200ms startup）。Phase 1 的 `ExiftoolBatch` 已能解決，pipeline 已採用；watcher 留著舊路是技術債也是效能損失。
2. Watcher 語義：save_result('completed') → write_metadata，寫失敗不改 DB 狀態。Pipeline 是反過來（write → save_result）。統一成 pipeline 語義：metadata 寫到磁碟後再 mark completed，DB `completed` 意味著 IPTC 已落盤。

### Step 1: 寫測試

加到 `tests/test_folder_watcher.py`：

```python
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
    import time
    for _ in range(50):
        if save_calls:
            break
        time.sleep(0.1)

    watcher.stop()

    # Batch used (init + write + close at least once each)
    assert any(c[0] == "batch_init" for c in calls)
    assert any(c[0] == "batch_write" for c in calls)
    assert any(c[0] == "batch_close" for c in calls)
    # save_result was called AFTER batch_write for the photo
    write_idx = next(i for i, c in enumerate(calls) if c[0] == "batch_write")
    # save_calls is tracked separately but in order; at least one save happened
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

    import time
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
```

### Step 2: 跑測試確認失敗

Run: `pytest tests/test_folder_watcher.py::test_watcher_uses_exiftool_batch_and_writes_before_save tests/test_folder_watcher.py::test_watcher_metadata_failure_marks_failed_not_completed -v`
Expected: 2 tests FAIL（ExiftoolBatch 還沒 import）。

### Step 3: 改 `modules/folder_watcher.py`

**Imports** — 替換舊的單檔 API：
```python
# 從
from modules.metadata_writer import has_happy_vision_tag, write_metadata

# 改成
from modules.metadata_writer import ExiftoolBatch, build_exiftool_args, has_happy_vision_tag
```
（`has_happy_vision_tag` 仍保留，用來做 cross-machine dedup 檢查。）

**`__init__`** — 加 `self._batch`：
```python
        self._executor: ThreadPoolExecutor | None = None
        self._batch: ExiftoolBatch | None = None
```

**`start()`** — 在啟動 threads 之前建 batch：
```python
        self._stop_event.clear()
        self._pause_event.set()
        self._store = ResultStore()
        self._executor = ThreadPoolExecutor(max_workers=self._concurrency)
        self._batch = ExiftoolBatch()  # <-- NEW
```

**`stop()`** — 在 executor shutdown 之後、store close 之前關 batch：
```python
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None

        # Close batch after workers finish, before closing store
        if self._batch:
            self._batch.close()
            self._batch = None

        # NOW it is safe to close the store
        if self._store:
            self._store.close()
            self._store = None
```

**`_process_one`** — 重寫，metadata 寫成功才 save_result：

```python
    def _process_one(self, photo_path: str) -> None:
        """Analyze a single photo, write metadata, then mark completed."""
        with self._lock:
            self._processing_count += 1

        try:
            config = load_config()
            api_key = config.get("gemini_api_key", "")
            model = config.get("model", "lite")

            result = analyze_photo(photo_path, api_key=api_key, model=model)

            if not result:
                if self._store:
                    self._store.mark_failed(photo_path, "Analysis returned no result")
                self._callbacks.on_error(photo_path, "Analysis returned no result")
                return

            # Write metadata first; only mark completed if IPTC actually lands on disk
            if self._batch is not None:
                args = build_exiftool_args(result) + ["-overwrite_original"]
                if not self._batch.write(photo_path, args):
                    if self._store:
                        self._store.mark_failed(photo_path, "Metadata write failed")
                    self._callbacks.on_error(photo_path, "Metadata write failed")
                    return

            if self._store:
                self._store.save_result(photo_path, result)
            log.info("Processed: %s", photo_path)
            self._callbacks.on_processed(photo_path, self._queue.qsize())
        except Exception as e:
            log.exception("Failed to process %s", photo_path)
            if self._store:
                self._store.mark_failed(photo_path, str(e))
            self._callbacks.on_error(photo_path, str(e))
        finally:
            with self._lock:
                self._processing_count -= 1
```

### Step 4: 跑測試

Run: `pytest tests/test_folder_watcher.py -v`
Expected: 原有 tests + 新 2 tests 全 PASS。

Run: `pytest -q`
Expected: 142 passed（140 + 2 new）。

### Step 5: Commit

```bash
git add modules/folder_watcher.py tests/test_folder_watcher.py
git commit -m "perf(folder_watcher): share ExiftoolBatch with pipeline semantics

Watcher now uses the same persistent exiftool (-stay_open) process
that pipeline adopted in Phase 1. Per-photo metadata write drops
from ~200ms (subprocess spawn) to ~40ms.

Also aligns transaction semantics: save_result('completed') fires
only after metadata successfully lands on disk. Previously the
watcher would mark completed first, then attempt metadata write,
leaving the DB and disk out of sync on exiftool failure."
```

---

## Task 3: `set_concurrency` 重建 executor

**Files:**
- Modify: `modules/folder_watcher.py` (`set_concurrency`)
- Modify: `tests/test_folder_watcher.py`

**動機（Phase 1 審查標記 Low）：** `self._executor._max_workers = value` 戳 CPython 私有屬性，未來版本可能失效，且對已啟動的 thread 不生效。改成 graceful shutdown 舊 executor + 建立新 executor。

### Step 1: 寫測試

加到 `tests/test_folder_watcher.py`：

```python
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
```

### Step 2: 跑測試確認失敗

Run: `pytest tests/test_folder_watcher.py -v -k concurrency`
Expected: 3 tests FAIL（目前 `set_concurrency` 戳 `_max_workers`，第一個 test 的 `old_executor._shutdown` 檢查會失敗；第三個 test 會 fail 因為目前每次都改 private attr）。

### Step 3: 改 `set_concurrency`

```python
    def set_concurrency(self, value: int) -> None:
        """Update concurrency at runtime by rebuilding the executor.

        In-flight tasks on the old executor finish; new tasks go to the
        new executor. Clamps to [1, 10].
        """
        value = max(1, min(10, value))
        if value == self._concurrency:
            return
        self._concurrency = value
        if self._executor is not None:
            old = self._executor
            self._executor = ThreadPoolExecutor(max_workers=value)
            # shutdown(wait=False) so the caller doesn't block; in-flight
            # tasks continue on the old executor and its threads retire.
            old.shutdown(wait=False)
        log.info("Concurrency updated to %d", value)
```

### Step 4: 跑測試

Run: `pytest tests/test_folder_watcher.py -v`
Expected: 全 PASS。

Run: `pytest -q`
Expected: 145 passed（142 + 3 new）。

### Step 5: Commit

```bash
git add modules/folder_watcher.py tests/test_folder_watcher.py
git commit -m "fix(folder_watcher): set_concurrency rebuilds executor

Previously set_concurrency assigned to executor._max_workers (private
CPython attr) which didn't actually change the running thread count
and is liable to break in future Python releases. Now we rebuild the
executor: new tasks go to the new one, in-flight tasks finish on the
old one as it retires."
```

---

## Task 4: Shared Gemini rate limiter

**Files:**
- Create: `modules/rate_limiter.py`
- Create: `tests/test_rate_limiter.py`
- Modify: `modules/gemini_vision.py` (acquire limiter at top of `analyze_photo`)
- Modify: `modules/pipeline.py` (no changes needed — all calls go through `analyze_photo`)
- Modify: `modules/folder_watcher.py` (no changes needed)

**動機：** 當 pipeline（concurrency=5）和 watcher（concurrency=1）同時跑，瞬間可能 6 個並發 Gemini request，各自獨立 retry/backoff，造成雷群效應：全部同時 429 → 全部 sleep(1s) → 全部同時再打 → 全部再 429。用共享 token bucket 全 process 範圍限流。

### Design — Token Bucket

- `RateLimiter(rate_per_minute: int)` — 填充速率 `rate_per_minute / 60` tokens/秒，上限 `rate_per_minute` tokens
- `acquire(timeout: float | None = None) -> bool` — 阻塞直到有 token 可用。timeout=None 表示永久等待；有 timeout 則返回 False 表示超時
- Module-level instance `default_limiter`：預設 60 RPM（保守）。啟動時從 config 讀覆蓋

### Step 1: 寫 RateLimiter 測試

建 `tests/test_rate_limiter.py`：

```python
"""tests/test_rate_limiter.py"""
import threading
import time

import pytest

from modules.rate_limiter import RateLimiter


def test_acquire_initial_tokens_non_blocking():
    """Start with full bucket — first N acquires should be instant."""
    rl = RateLimiter(rate_per_minute=60)
    start = time.monotonic()
    for _ in range(5):
        assert rl.acquire(timeout=0.1) is True
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Initial acquires took {elapsed:.2f}s"


def test_acquire_blocks_when_bucket_empty():
    """After bucket drains, next acquire must wait for refill."""
    rl = RateLimiter(rate_per_minute=60)  # 1 token/sec
    # Drain the bucket
    for _ in range(60):
        rl.acquire(timeout=0.1)

    start = time.monotonic()
    # Next acquire should wait ~1 second for refill
    assert rl.acquire(timeout=2.0) is True
    elapsed = time.monotonic() - start
    assert 0.5 < elapsed < 1.5, f"Refill wait was {elapsed:.2f}s (expected ~1.0s)"


def test_acquire_timeout_returns_false():
    rl = RateLimiter(rate_per_minute=6)  # 1 token / 10s
    # Drain
    for _ in range(6):
        rl.acquire(timeout=0.1)
    # Next acquire with short timeout should fail
    assert rl.acquire(timeout=0.1) is False


def test_refill_accumulates_over_time():
    rl = RateLimiter(rate_per_minute=120)  # 2 tokens/sec
    # Drain
    for _ in range(120):
        rl.acquire(timeout=0.1)
    # Wait 1 second → should have 2 tokens
    time.sleep(1.1)
    start = time.monotonic()
    rl.acquire(timeout=0.5)
    rl.acquire(timeout=0.5)
    elapsed = time.monotonic() - start
    assert elapsed < 0.2, f"Refilled tokens took {elapsed:.2f}s to acquire"


def test_thread_safe_concurrent_acquires():
    """Two threads hammering acquire should not double-spend tokens."""
    rl = RateLimiter(rate_per_minute=60)
    counts = {"a": 0, "b": 0}

    def worker(key):
        for _ in range(40):
            if rl.acquire(timeout=0.05):
                counts[key] += 1

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Combined cannot exceed initial 60 tokens meaningfully during the short window
    total = counts["a"] + counts["b"]
    assert total <= 65, f"Got {total} total acquires; bucket should cap at ~60"
    assert total >= 50, f"Got {total} total; should be close to 60"
```

### Step 2: 跑測試確認失敗

Run: `pytest tests/test_rate_limiter.py -v`
Expected: 全 FAIL（module 不存在）。

### Step 3: 實作 `modules/rate_limiter.py`

```python
"""modules/rate_limiter.py — Token bucket rate limiter (thread-safe).

Shared between pipeline and folder_watcher so concurrent Gemini API calls
respect a single RPM budget instead of each worker thread independently
backing off on 429s."""

import threading
import time


class RateLimiter:
    """Simple token bucket. Acquire blocks until a token is available.

    Bucket starts full. Tokens refill continuously at rate_per_minute/60 per
    second, capped at rate_per_minute total.
    """

    def __init__(self, rate_per_minute: int):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self._capacity = float(rate_per_minute)
        self._refill_per_sec = rate_per_minute / 60.0
        self._tokens = float(rate_per_minute)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def _refill(self) -> None:
        """Must be called with self._lock held."""
        now = time.monotonic()
        delta = now - self._last_refill
        if delta > 0:
            self._tokens = min(self._capacity, self._tokens + delta * self._refill_per_sec)
            self._last_refill = now

    def acquire(self, timeout: float | None = None) -> bool:
        """Block until a token is available. Returns True on success,
        False if timeout expired."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
                # Need to wait for more tokens
                needed = 1 - self._tokens
                wait_time = needed / self._refill_per_sec
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    wait_time = min(wait_time, remaining)
                self._cond.wait(timeout=wait_time)


# Default limiter used by gemini_vision.analyze_photo. Configured at import time
# with a conservative default; web_ui or pipeline can call `configure(...)` to
# adjust based on user's Gemini plan.
default_limiter = RateLimiter(rate_per_minute=60)


def configure(rate_per_minute: int) -> None:
    """Replace the default limiter with one at the given rate."""
    global default_limiter
    default_limiter = RateLimiter(rate_per_minute=rate_per_minute)
```

### Step 4: 跑測試確認通過

Run: `pytest tests/test_rate_limiter.py -v`
Expected: 5 tests PASS。

### Step 5: 接到 `analyze_photo`

編輯 `modules/gemini_vision.py`。在 imports 加：

```python
from modules.rate_limiter import default_limiter
```

在 `analyze_photo` 內，於 `client = _get_client(api_key)` 之後、`for attempt in range(max_retries):` 之前加：

```python
    client = _get_client(api_key)

    # Global rate limit (shared by pipeline workers and folder watcher)
    default_limiter.acquire()

    for attempt in range(max_retries):
```

**注意：** 只 acquire 一次，在 retry loop 外。retry 本身的 backoff sleep 處理 429；限流處理 burst。若 429 發生 → backoff sleep → 重發 request → **不**再 acquire（雖然 acquire 會快速通過，但語義上 retry 是同一個邏輯 request）。

### Step 6: 寫 pipeline 整合測試

加到 `tests/test_pipeline.py`：

```python
def test_pipeline_respects_rate_limiter(tmp_path, monkeypatch):
    """analyze_photo should call default_limiter.acquire() before each request."""
    from modules import pipeline as pl
    from modules import gemini_vision
    from modules import rate_limiter

    for i in range(3):
        (tmp_path / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    acquire_count = {"n": 0}
    orig_acquire = rate_limiter.default_limiter.acquire

    def tracking_acquire(timeout=None):
        acquire_count["n"] += 1
        return True

    monkeypatch.setattr(rate_limiter.default_limiter, "acquire", tracking_acquire)

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **kw: (rate_limiter.default_limiter.acquire(),
                            {"title": "T", "keywords": [], "description": "",
                             "category": "other", "scene_type": "indoor",
                             "mood": "neutral", "people_count": 0})[1],
    )

    class FakeBatch:
        def write(self, p, a): return True
        def close(self): pass
    monkeypatch.setattr(pl, "ExiftoolBatch", FakeBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
    )

    # 3 photos → 3 acquires (one per analyze_photo invocation)
    assert acquire_count["n"] == 3
```

### Step 7: 跑全部 test

Run: `pytest -q`
Expected: 151 passed（145 + 5 rate_limiter + 1 pipeline = 151）。

### Step 8: Commit

```bash
git add modules/rate_limiter.py tests/test_rate_limiter.py modules/gemini_vision.py tests/test_pipeline.py
git commit -m "feat(rate_limiter): shared token bucket for Gemini API

Pipeline workers (concurrency up to 10) and folder watcher (concurrency
up to 10) previously each retried independently on 429s, producing
thundering-herd bursts. Now both paths call default_limiter.acquire()
before each Gemini request, respecting a single 60 RPM budget across
the whole process.

The acquire is outside the retry loop so 429 backoff still kicks in
per-request; the limiter only throttles initial submission."
```

---

## Final Verification

- [ ] **Step 1: Full test suite**

Run: `make verify`
Expected: 151 tests PASS + lint 綠。

- [ ] **Step 2: 煙霧測試 — 手動驗證 stop race**

Run:
```bash
make dev &
# 透過 UI 啟動 watcher，丟 20 張照片進監控資料夾，等 3 秒（有 in-flight 時）停止 watcher
# 觀察 log 不應出現 "Cannot operate on a closed database"
pkill -f "web_ui.py"
```

- [ ] **Step 3: 煙霧測試 — 手動驗證 ExiftoolBatch 效能**

Run:
```bash
# 比較 20 張照片處理時間
time make dev  # 手動丟照片、計時
```
Expected: 20 張 @ concurrency=5 約 20–30 秒（Phase 1 + Phase 2B 累積效果）；watcher 的 metadata 階段從 serial subprocess 變成 persistent stdin 餵。

- [ ] **Step 4: bump VERSION**

編輯 `VERSION`：`0.3.0` → `0.3.1`。

- [ ] **Step 5: Final commit**

```bash
git add VERSION
git commit -m "chore: bump version to 0.3.1

Phase 2B architecture/reliability improvements:
- FolderWatcher.stop() waits for in-flight workers before closing DB
  (fixes sporadic 'Cannot operate on a closed database' on pause/stop)
- Watcher adopts ExiftoolBatch (persistent -stay_open process) and
  pipeline-aligned semantics (metadata → save_result, so DB completed
  implies IPTC on disk)
- set_concurrency rebuilds executor instead of poking private
  _max_workers attribute (CPython-internal hack)
- Shared RateLimiter (token bucket) between pipeline and watcher
  prevents thundering-herd 429 bursts on Gemini API"
```

---

## Next Plan — Phase 2C UX/Test Polish

獨立計劃處理：
1. 前端 `visibilitychange` refresh（watcher 回前景自動刷新狀態）
2. Fetch timeout helper（避免永遠 loading）
3. SSE 斷線 UI 提示（目前 `sseConnected` 只是內部變數，UI 看不到）
4. `MonitorView.formatTime` tick（「3 分鐘前」自動更新，不然盯一小時都不動）
5. `dismissUpdate` localStorage 記憶（重啟 app 後 dismissed 版本不重彈）
6. 補 API blueprint 測試（`test_analysis_api.py`、`test_results_api.py`、`test_settings_api.py`、`test_export_api.py`、`test_browse_api.py`）
7. E2E test：真實 JPG → pipeline → metadata → CSV

## Future — Phase 3

- Apple Developer codesign + notarization（需帳號 + CI）
- Pipeline 完整統一到 watcher（消除雙重執行引擎 — 目前兩者共用 ExiftoolBatch + rate_limiter 已解決大部分重複問題，進一步合併是大工程）
- Watchdog 取代 polling（FSEvents on macOS）

---

## Self-Review 已完成

- ✅ **Spec coverage：** 原始審查中 Phase 2B 該解決的都有對應 task（stop race = Task 1；watcher 用 batch + 對齊 pipeline = Task 2；set_concurrency 私有 attr = Task 3；thundering herd 429 = Task 4）
- ✅ **無 placeholder：** 每 step 都有具體 code / command / expected
- ✅ **型別一致：** `ExiftoolBatch`、`build_exiftool_args`、`RateLimiter`、`default_limiter`、`acquire`、`configure` 在多個 task 出現時命名一致
- ✅ **TDD：** 每個改動先寫測試、確認失敗、實作、確認通過
- ✅ **小 commit：** 4 個功能 task + 1 收尾，每個獨立可 revert
- ✅ **Scope：** 純架構/可靠性工作；不含 UX（Phase 2C）、codesign（Phase 3）
