# Happy Vision Phase 1 可靠性 & 效能改進計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉六位專家找到的「週末級」高效益問題 — 消除偶發 `database is locked`、把 metadata 寫入從 350ms/張 降到 40ms/張、清除前端死碼、修掉幾個明顯 race。

**Architecture:** 以小步驟 TDD 推進，每個任務獨立可 commit。所有後端改動先補/改測試再改實作；前端刪除無 router 掛載的死碼。不引入新依賴。

**Tech Stack:** Python 3.10+、Flask、SQLite (WAL)、exiftool (`-stay_open`)、Vue 3、pytest。

**Phase 2（下一份計劃，不在本次）：** updater codesign 驗證、API token + Origin 檢查、API key 搬 Keychain、pipeline 統一到 watcher、visibilitychange refresh、fetch timeout。

---

## File Structure

**Modify（後端）：**
- `modules/result_store.py` — 加 WAL、index、thread lock
- `modules/metadata_writer.py` — 新增 `ExiftoolBatch` class；`write_metadata` / `has_happy_vision_tag` 走 batch
- `modules/pipeline.py` — metadata 改成 per-photo 在 `process_one` 裡寫、跟 analyze 交織
- `modules/gemini_vision.py` — module-level `_client_cache`
- `modules/folder_watcher.py` — 走新的 batch API
- `api/update.py` — 加 `_download_lock` 互斥
- `web_ui.py` — `auto_start_watcher()` 加 reloader guard

**Modify（前端）：**
- `frontend/src/App.vue` — `dismissUpdate()` 時停 polling、interval 改 2000ms

**Delete（前端死碼）：**
- `frontend/src/views/ImportView.vue`
- `frontend/src/views/ProgressView.vue`
- `frontend/src/views/ResultsView.vue`
- `frontend/src/views/WatchView.vue`
- `frontend/src/stores/analysis.js`

**Tests（新增/擴充）：**
- `tests/test_result_store.py` — 加 WAL mode 驗證 + 併發寫入
- `tests/test_metadata_writer.py` — 加 `ExiftoolBatch` 測試（mock subprocess）
- `tests/test_pipeline.py` — 加「cancel 後 metadata 不會寫」+「write_metadata=True 時每張呼叫一次」
- `tests/test_gemini_vision.py` — 加 client cache 驗證
- `tests/test_update_api.py`（新檔）— 加互斥鎖測試

---

## Task 1: SQLite 加 WAL、index、thread lock

**Files:**
- Modify: `modules/result_store.py`
- Test: `tests/test_result_store.py`

**動機：** pipeline + watcher 同時寫 SQLite 時會 `OperationalError: database is locked`；`get_today_stats` / `get_recent` 沒 index 查全表。`ResultStore` 跨 thread 使用卻沒鎖。

- [ ] **Step 1: 寫測試 — WAL 已啟用**

加到 `tests/test_result_store.py` 末尾：

```python
def test_wal_mode_enabled(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    store.close()


def test_index_exists(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    rows = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='results'"
    ).fetchall()
    index_names = {r["name"] for r in rows}
    assert "idx_results_status" in index_names
    assert "idx_results_updated_at" in index_names
    store.close()


def test_concurrent_writes_do_not_deadlock(tmp_path):
    """Two threads saving results simultaneously must not raise OperationalError."""
    import threading
    store = ResultStore(tmp_path / "test.db")
    errors = []

    def writer(prefix):
        try:
            for i in range(50):
                store.save_result(f"/photos/{prefix}_{i:03d}.jpg", {"title": f"{prefix}{i}"})
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=writer, args=("A",))
    t2 = threading.Thread(target=writer, args=("B",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == []
    results = store.get_all_results()
    assert len(results) == 100
    store.close()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `make test PYTEST_ARGS='tests/test_result_store.py::test_wal_mode_enabled tests/test_result_store.py::test_index_exists tests/test_result_store.py::test_concurrent_writes_do_not_deadlock -v'`
Expected: 前兩個 FAIL（journal_mode 是 `delete`、沒 index），第三個大概率 FAIL 或 flaky。

- [ ] **Step 3: 實作 — 加 WAL + index + lock**

編輯 `modules/result_store.py`，在 `__init__` 加 lock，`_init_db` 加 pragma 與 index；所有會寫的方法用 lock 包。

```python
import threading
# ... existing imports ...

class ResultStore:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_config_dir() / "results.db"
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                file_path TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'completed',
                result_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_status ON results(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_updated_at ON results(updated_at DESC)")
        self.conn.commit()
```

然後把 `save_result`、`mark_failed`、`update_result` 三個**寫入**方法的 body 用 `with self._lock:` 包起來。例：

```python
    def save_result(self, file_path: str, result: dict) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO results
                   (file_path, status, result_json, created_at, updated_at)
                   VALUES (?, 'completed', ?, ?, ?)""",
                (file_path, json.dumps(result, ensure_ascii=False), now, now),
            )
            self.conn.commit()

    def mark_failed(self, file_path: str, error_message: str) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO results
                   (file_path, status, error_message, created_at, updated_at)
                   VALUES (?, 'failed', ?, ?, ?)""",
                (file_path, error_message, now, now),
            )
            self.conn.commit()

    def update_result(self, file_path: str, updates: dict) -> None:
        existing = self.get_result(file_path) or {}
        merged = {**existing, **updates}
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE results SET result_json = ?, updated_at = ? WHERE file_path = ?",
                (json.dumps(merged, ensure_ascii=False), now, file_path),
            )
            self.conn.commit()
```

（讀取方法 `get_*` 不需要 lock，WAL 下讀不擋寫。）

- [ ] **Step 4: 跑測試確認通過**

Run: `make test PYTEST_ARGS='tests/test_result_store.py -v'`
Expected: 所有 test PASS（含原有 9 個 + 新 3 個）。

- [ ] **Step 5: Commit**

```bash
git add modules/result_store.py tests/test_result_store.py
git commit -m "fix(result_store): enable WAL, add indexes, lock writes

Fixes sporadic 'database is locked' errors when pipeline and watcher
write simultaneously. Adds indexes on status and updated_at for the
dashboard queries that used to scan the full table."
```

---

## Task 2: Frontend 刪死碼

**Files:**
- Delete: `frontend/src/views/ImportView.vue`
- Delete: `frontend/src/views/ProgressView.vue`
- Delete: `frontend/src/views/ResultsView.vue`
- Delete: `frontend/src/views/WatchView.vue`
- Delete: `frontend/src/stores/analysis.js`

**動機：** `router.js` 只掛 `MonitorView` 與 `SettingsView`，這 4 個 view + 1 個 store 沒人用但仍 import SSE 會在誤掛時重複連線。先清乾淨再改其他。

- [ ] **Step 1: 確認沒有引用**

Run:
```bash
grep -rn "ImportView\|ProgressView\|ResultsView\|WatchView\|stores/analysis" frontend/src/ --include='*.vue' --include='*.js'
```
Expected: 除了這些檔案自己，沒有任何外部引用（router.js 早已改掉）。若找到殘留引用，停下先查清楚再繼續。

- [ ] **Step 2: 刪除 5 個檔案**

```bash
rm frontend/src/views/ImportView.vue
rm frontend/src/views/ProgressView.vue
rm frontend/src/views/ResultsView.vue
rm frontend/src/views/WatchView.vue
rm frontend/src/stores/analysis.js
```

- [ ] **Step 3: build 確認沒壞**

Run: `cd frontend && npm run build`
Expected: build 成功，沒有 "Cannot find module" 錯誤。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(frontend): remove dead views and unused analysis store

router.js only mounts MonitorView and SettingsView; the other four
views and the analysis Pinia store were orphans that still imported
SSE and would double-connect if accidentally re-mounted."
```

---

## Task 3: Dev reloader guard（避免雙 watcher）

**Files:**
- Modify: `web_ui.py:25-29`

**動機：** `debug=True` 時 Werkzeug reloader 把 process exec 兩次，`auto_start_watcher()` 跑兩次 → 兩個 watcher、兩組 SSE broadcast、偶發照片被處理兩次。

- [ ] **Step 1: 讀目前位置**

Run: `grep -n "auto_start_watcher" web_ui.py`
確認：呼叫在 top-level（register blueprint 之後）。

- [ ] **Step 2: 加 guard**

編輯 `web_ui.py`，把呼叫 `auto_start_watcher()` 那行改成：

```python
# Auto-start watch folder if previously enabled.
# Skip in Werkzeug's reloader parent process to avoid double-starting.
import os
if not os.environ.get("WERKZEUG_RUN_MAIN") == "false":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        auto_start_watcher()
```

更簡潔的版本（推薦）：

```python
import os
# Auto-start watcher once. In dev (debug=True) Werkzeug's reloader forks:
# parent has no WERKZEUG_RUN_MAIN; child has it set to "true". Only start in child.
# In production (frozen .app) debug is False and there's no reloader.
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    auto_start_watcher()
```

- [ ] **Step 3: 手動驗證（無自動測試）**

終端 A：`make dev`，觀察 log 出現幾次 "Folder watcher started"。
Expected: 只一次（修復前是兩次）。

停掉後，繼續。

- [ ] **Step 4: Commit**

```bash
git add web_ui.py
git commit -m "fix(web_ui): guard auto_start_watcher against Werkzeug reloader

In dev mode Werkzeug forks the process; without this guard the watcher
starts twice, causing duplicate SSE broadcasts and occasionally the
same photo being analyzed by both watchers."
```

---

## Task 4: `genai.Client` module-level cache

**Files:**
- Modify: `modules/gemini_vision.py`
- Test: `tests/test_gemini_vision.py`

**動機：** `analyze_photo:146` 每次呼叫都 `genai.Client(api_key=...)`，浪費 TLS handshake 與 connection pool 初始化（每次 ~50–100ms）。

- [ ] **Step 1: 寫測試 — 同 api_key 只建一次 client**

加到 `tests/test_gemini_vision.py`：

```python
def test_client_cache_reuses_instance(monkeypatch):
    """Calling _get_client twice with same key returns same instance."""
    from modules import gemini_vision

    created = []

    class FakeClient:
        def __init__(self, api_key):
            created.append(api_key)

    monkeypatch.setattr(gemini_vision.genai, "Client", FakeClient)
    gemini_vision._client_cache.clear()

    c1 = gemini_vision._get_client("key-abc")
    c2 = gemini_vision._get_client("key-abc")
    c3 = gemini_vision._get_client("key-xyz")

    assert c1 is c2
    assert c1 is not c3
    assert created == ["key-abc", "key-xyz"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `make test PYTEST_ARGS='tests/test_gemini_vision.py::test_client_cache_reuses_instance -v'`
Expected: FAIL (`_get_client` / `_client_cache` 不存在)。

- [ ] **Step 3: 實作 cache**

編輯 `modules/gemini_vision.py`：在 import 區塊下方、MODEL_MAP 上方加：

```python
# Module-level cache: one genai.Client per api_key, reused across calls.
_client_cache: dict[str, "genai.Client"] = {}
_client_cache_lock = __import__("threading").Lock()


def _get_client(api_key: str) -> "genai.Client":
    with _client_cache_lock:
        client = _client_cache.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            _client_cache[api_key] = client
        return client
```

然後把 `analyze_photo` 內第 146 行 `client = genai.Client(api_key=api_key)` 改成：

```python
    client = _get_client(api_key)
```

- [ ] **Step 4: 跑測試**

Run: `make test PYTEST_ARGS='tests/test_gemini_vision.py -v'`
Expected: 全 PASS（含原有 + 新 1 個）。

- [ ] **Step 5: Commit**

```bash
git add modules/gemini_vision.py tests/test_gemini_vision.py
git commit -m "perf(gemini_vision): cache genai.Client per api_key

Saves ~50-100ms TLS handshake per photo. For a 1000-photo run at
concurrency=5 that is ~15s saved."
```

---

## Task 5: Update API 加互斥鎖

**Files:**
- Modify: `api/update.py`
- Create: `tests/test_update_api.py`

**動機：** `POST /api/update/download` 沒檢查 `status == "downloading"`，快速點兩下 → 兩條 thread 同時 rename 同一個 `.app` → 100% 競態，bundle 壞掉。

- [ ] **Step 1: 寫測試 — 第二次 POST 回 409**

建立 `tests/test_update_api.py`：

```python
"""tests/test_update_api.py"""
from unittest.mock import patch

import pytest

from web_ui import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_download_rejected_if_no_update(client):
    with patch("api.update.get_state", return_value={"status": "idle"}):
        r = client.post("/api/update/download")
    assert r.status_code == 400


def test_download_rejected_if_already_downloading(client):
    """Second POST while first is in-flight must return 409, not spawn another thread."""
    state = {"status": "available"}

    # Make the background fn slow so the two requests overlap
    def slow(*_args, **_kwargs):
        import time
        state["status"] = "downloading"
        time.sleep(0.3)
        state["status"] = "ready"

    with patch("api.update.get_state", side_effect=lambda: state):
        with patch("api.update.download_and_install", side_effect=slow):
            r1 = client.post("/api/update/download")
            # Second call arrives while first is still sleeping
            r2 = client.post("/api/update/download")

    assert r1.status_code == 200
    assert r2.status_code == 409
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `make test PYTEST_ARGS='tests/test_update_api.py -v'`
Expected: `test_download_rejected_if_already_downloading` FAIL (目前會回 200 兩次)。

- [ ] **Step 3: 實作互斥鎖**

編輯 `api/update.py`：

```python
"""api/update.py — Update check & download API endpoints"""

import threading

from flask import Blueprint, jsonify

from modules.updater import (
    check_for_update,
    download_and_install,
    get_current_version,
    get_state,
    restart_app,
)

update_bp = Blueprint("update", __name__, url_prefix="/api/update")
_download_lock = threading.Lock()


# ... check() and status() unchanged ...


@update_bp.route("/download", methods=["POST"])
def download():
    """Start downloading and installing the update in background."""
    state = get_state()
    if state["status"] != "available":
        return jsonify({"error": "沒有可用的更新"}), 400

    # Try to acquire the lock without blocking; if someone else already
    # triggered a download, return 409 instead of spawning a second thread.
    if not _download_lock.acquire(blocking=False):
        return jsonify({"error": "更新下載已在進行中"}), 409

    def _run():
        try:
            download_and_install()
        finally:
            _download_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "downloading"})
```

- [ ] **Step 4: 跑測試**

Run: `make test PYTEST_ARGS='tests/test_update_api.py -v'`
Expected: 兩個 test PASS。

- [ ] **Step 5: Commit**

```bash
git add api/update.py tests/test_update_api.py
git commit -m "fix(update): mutex lock on download endpoint

Prevents two background threads from simultaneously renaming the
running .app bundle when the download button is double-clicked."
```

---

## Task 6: `ExiftoolBatch` — persistent `-stay_open` writer

**Files:**
- Modify: `modules/metadata_writer.py`
- Test: `tests/test_metadata_writer.py`

**動機：** 每張照片 `subprocess.run(["exiftool", ...])` spawn 一次 Perl 直譯器（~200ms 純啟動），批次寫 1000 張要多燒 ~3 分鐘在 fork/exec。`-stay_open True -@ -` 讓 exiftool 跑一個 persistent daemon，stdin 餵指令、讀到 `{ready}` 為止。

### 設計

```
ExiftoolBatch
  __init__()      -> Popen(["exiftool", "-stay_open", "True", "-@", "-"])
  write(path, args: list[str]) -> bool   # feed args + path + "-execute\n", read until {ready}
  read(path) -> dict                     # feed "-j" + path + "-execute\n", parse JSON
  close()                                # send "-stay_open\nFalse\n", wait()
```

保留原 `write_metadata(path, result)` / `read_metadata(path)` / `has_happy_vision_tag(path)` 作為**單檔**便利函式（向下相容、測試也容易），但新增 class 給 pipeline/watcher 用。

- [ ] **Step 1: 寫測試 — batch 輸出格式正確**

測試用 stubbed subprocess（不實際 spawn exiftool）。加到 `tests/test_metadata_writer.py`：

```python
def test_exiftool_batch_write_sends_correct_commands(monkeypatch):
    """ExiftoolBatch.write should feed args + path + -execute\\n and read until {ready}."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout_chunks = [
                "    1 image files updated\n",
                "{ready}\n",
            ]
            self._read_idx = 0
            self.stdout = self
            self.returncode = None

        def readline(self):
            if self._read_idx < len(self.stdout_chunks):
                line = self.stdout_chunks[self._read_idx]
                self._read_idx += 1
                return line
            return ""

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/photo.jpg", ["-IPTC:Headline=Test", "-overwrite_original"])

    assert ok is True
    written = fake.stdin.getvalue()
    assert "-IPTC:Headline=Test\n" in written
    assert "-overwrite_original\n" in written
    assert "/tmp/photo.jpg\n" in written
    assert "-execute\n" in written


def test_exiftool_batch_write_detects_failure(monkeypatch):
    """Error output before {ready} should return False."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout_chunks = [
                "Error: File not found\n",
                "    0 image files updated\n",
                "{ready}\n",
            ]
            self._read_idx = 0
            self.stdout = self

        def readline(self):
            if self._read_idx < len(self.stdout_chunks):
                line = self.stdout_chunks[self._read_idx]
                self._read_idx += 1
                return line
            return ""

        def wait(self, timeout=None):
            return 0

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/missing.jpg", ["-IPTC:Headline=X"])
    assert ok is False


def test_exiftool_batch_close_sends_shutdown(monkeypatch):
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
            self.waited = False

        def readline(self):
            return ""

        def wait(self, timeout=None):
            self.waited = True
            return 0

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    batch.close()

    shutdown = fake.stdin.getvalue()
    assert "-stay_open\nFalse\n" in shutdown
    assert fake.waited


def test_exiftool_batch_thread_safe(monkeypatch):
    """Two threads writing through the same batch must serialize."""
    from modules import metadata_writer
    import io
    import threading

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
            self._lines = []
            self._idx = 0

        def readline(self):
            # Every write operation consumes one "{ready}" line.
            return "{ready}\n"

        def wait(self, timeout=None):
            return 0

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    errors = []

    def worker(i):
        try:
            for j in range(10):
                batch.write(f"/tmp/p{i}_{j}.jpg", [f"-IPTC:Headline=T{i}{j}"])
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert errors == []
    # 3 threads × 10 writes × at least 2 lines each (args + -execute) ≥ 60 lines
    assert fake.stdin.getvalue().count("-execute\n") == 30
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `make test PYTEST_ARGS='tests/test_metadata_writer.py -v -k exiftool_batch'`
Expected: 4 個 test 全 FAIL (`ExiftoolBatch` 不存在)。

- [ ] **Step 3: 實作 `ExiftoolBatch`**

加到 `modules/metadata_writer.py` 末尾（同時保留現有 `write_metadata` / `read_metadata` / `has_happy_vision_tag` 函式）：

```python
import threading


class ExiftoolBatch:
    """Persistent exiftool process using -stay_open mode.

    One exiftool invocation handles many files via stdin, avoiding
    ~200ms Perl startup per photo. Instances are thread-safe.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            [_get_exiftool_cmd(), "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _run_batch(self, args: list[str]) -> tuple[bool, str]:
        """Feed args + -execute, read output until {ready}. Returns (ok, output)."""
        with self._lock:
            for arg in args:
                self._proc.stdin.write(arg + "\n")
            self._proc.stdin.write("-execute\n")
            self._proc.stdin.flush()

            output_lines = []
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    return False, "".join(output_lines)  # process died
                if line.strip() == "{ready}":
                    break
                output_lines.append(line)

        output = "".join(output_lines)
        ok = "Error" not in output and "error" not in output.lower()
        return ok, output

    def write(self, photo_path: str, args: list[str]) -> bool:
        """Run exiftool args against photo_path. Returns True on success."""
        ok, output = self._run_batch(args + [photo_path])
        if not ok:
            log.error("exiftool batch write failed for %s: %s", photo_path, output.strip())
        return ok

    def read_json(self, photo_path: str, tags: list[str] | None = None) -> dict:
        """Read metadata as JSON. Returns {} on failure."""
        args = ["-j"]
        if tags:
            args.extend(tags)
        args.append(photo_path)
        ok, output = self._run_batch(args)
        if not ok:
            return {}
        try:
            data = json.loads(output)
            return data[0] if isinstance(data, list) and data else {}
        except (json.JSONDecodeError, IndexError):
            return {}

    def close(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.write("-stay_open\nFalse\n")
                    self._proc.stdin.flush()
                except (BrokenPipeError, ValueError):
                    pass
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
```

確認檔案頂端已 `import json`；若沒則加。

- [ ] **Step 4: 跑測試**

Run: `make test PYTEST_ARGS='tests/test_metadata_writer.py -v'`
Expected: 全 PASS (原有的 + 新 4 個 batch test)。

- [ ] **Step 5: Commit**

```bash
git add modules/metadata_writer.py tests/test_metadata_writer.py
git commit -m "feat(metadata_writer): add ExiftoolBatch for -stay_open mode

Per-photo subprocess spawn costs ~200ms of Perl startup. Batch mode
keeps exiftool running and feeds args via stdin, cutting write time
to ~30-50ms per photo."
```

---

## Task 7: Pipeline 改成 per-photo metadata 交織 + 用 `ExiftoolBatch`

**Files:**
- Modify: `modules/pipeline.py`
- Test: `tests/test_pipeline.py`

**動機：** 現況是先跑完所有 Gemini 分析才 serial 寫 metadata，兩階段無法重疊。改成 `process_one` 裡 analyze 成功就立刻寫 metadata（透過共享 `ExiftoolBatch`），metadata 階段消失。

### 交易語義改變

**舊：** analyze 成功 → 存 DB (`completed`) → 全部跑完再 loop 寫 metadata
**新：** analyze 成功 → 寫 metadata → 存 DB (`completed`)

若 exiftool 失敗，該張 `mark_failed` 並回報 `on_error`；跟 watcher 的語義一致。

- [ ] **Step 1: 寫測試 — `write_metadata=True` 時每張都呼叫 batch.write，且 cancel 後剩餘照片不會寫**

先讀現有 `tests/test_pipeline.py` 的 fixture 風格：

Run: `grep -n "def test_\|fixture\|monkeypatch" tests/test_pipeline.py | head -30`

然後加到 `tests/test_pipeline.py`：

```python
def test_pipeline_writes_metadata_per_photo(tmp_path, monkeypatch):
    """When write_metadata=True, ExiftoolBatch.write is called once per photo."""
    from modules import pipeline as pl

    # 3 fake photos
    for i in range(3):
        (tmp_path / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")  # minimal JPEG

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **kw: {"title": f"T-{Path(path).name}", "keywords": ["k"],
                            "description": "d", "category": "other",
                            "scene_type": "indoor", "mood": "neutral", "people_count": 0},
    )

    writes = []

    class FakeBatch:
        def __init__(self): pass
        def write(self, path, args):
            writes.append(path)
            return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", FakeBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
    )

    assert len(writes) == 3
    assert all(str(tmp_path) in w for w in writes)


def test_pipeline_cancel_stops_metadata_writes(tmp_path, monkeypatch):
    """After cancel, no further metadata writes happen."""
    from modules import pipeline as pl

    for i in range(10):
        (tmp_path / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    state = pl.PipelineState()
    call_count = {"n": 0}

    def fake_analyze(path, **kw):
        call_count["n"] += 1
        if call_count["n"] == 2:
            state.cancel()
        return {"title": "T", "keywords": [], "description": "",
                "category": "other", "scene_type": "indoor",
                "mood": "neutral", "people_count": 0}

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)

    writes = []
    class FakeBatch:
        def write(self, path, args): writes.append(path); return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(pl, "ExiftoolBatch", FakeBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
        state=state,
    )

    # Cancelled after 2 analyses → at most 2 metadata writes (not all 10)
    assert len(writes) <= 2


def test_pipeline_metadata_failure_marks_failed(tmp_path, monkeypatch):
    """If ExiftoolBatch.write returns False, photo should be marked failed."""
    from modules import pipeline as pl

    (tmp_path / "p.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **kw: {"title": "T", "keywords": [], "description": "",
                            "category": "other", "scene_type": "indoor",
                            "mood": "neutral", "people_count": 0},
    )

    class FailingBatch:
        def write(self, path, args): return False
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(pl, "ExiftoolBatch", FailingBatch)

    errors = []
    class CB(pl.PipelineCallbacks):
        def on_error(self, path, err): errors.append((path, err))

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
        callbacks=CB(),
    )

    assert len(errors) == 1
    assert "metadata" in errors[0][1].lower()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `make test PYTEST_ARGS='tests/test_pipeline.py -v -k metadata'`
Expected: 新 3 個 test FAIL。

- [ ] **Step 3: 改 `run_pipeline`**

編輯 `modules/pipeline.py`，改掉 `process_one` 與末尾的 metadata 迴圈：

```python
# 頂端 import 區塊加入：
from modules.metadata_writer import ExiftoolBatch, build_exiftool_args

# run_pipeline 內：
# 在 `total = len(to_process)` 之後、`def process_one` 之前：
    batch = ExiftoolBatch() if write_metadata else None

    def process_one(photo_path: str) -> dict | None:
        nonlocal done_count, failed_count
        if state.cancelled:
            return None
        state.wait_if_paused()
        if state.cancelled:
            return None

        result = analyze_photo(photo_path, api_key=api_key, model=model)

        # Write metadata before committing to DB as 'completed', so that
        # a successful save_result implies the photo has the IPTC marker.
        if result and batch is not None:
            args = build_exiftool_args(result) + ["-overwrite_original"]
            if args and not batch.write(photo_path, args):
                result = None  # treat as failure below

        with lock:
            if result:
                store.save_result(photo_path, result)
                results.append(result)
            else:
                if state.cancelled:
                    return None  # don't mark failed on user cancel
                store.mark_failed(photo_path, "Analysis or metadata write failed")
                failed_count += 1
                callbacks.on_error(photo_path, "Analysis or metadata failed")

            done_count += 1
            callbacks.on_progress(done_count, total, photo_path)

        return result

    try:
        if concurrency <= 1:
            for photo in to_process:
                process_one(photo)
                if state.cancelled:
                    break
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(process_one, p): p for p in to_process}
                for future in concurrent.futures.as_completed(futures):
                    if state.cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    future.result()
    finally:
        if batch is not None:
            batch.close()

    store.close()
    callbacks.on_complete(total, failed_count)
    log.info("Pipeline complete: %d analyzed, %d failed", len(results), failed_count)
    return results
```

移除**原本末尾**的這段（放到 `process_one` 裡面了）：

```python
    # Write metadata only for photos in this folder
    if write_metadata and results:
        for r in store.get_results_for_folder(folder):
            write_meta(r["file_path"], r)
```

確保頂端不再 import `write_metadata as write_meta`（可保留，但不再使用）；為了整潔可以改成 `from modules.metadata_writer import ExiftoolBatch, build_exiftool_args`，並刪掉 `write_meta` 的 import 若無其他使用者。

Run: `grep -n "write_meta\b" modules/pipeline.py` 確認沒有殘留呼叫。

- [ ] **Step 4: 跑測試**

Run: `make test PYTEST_ARGS='tests/test_pipeline.py -v'`
Expected: 全 PASS（含原有 + 新 3 個）。

- [ ] **Step 5: 跑全部 test 確認沒回歸**

Run: `make test`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add modules/pipeline.py tests/test_pipeline.py
git commit -m "perf(pipeline): interleave metadata write with analysis

Old pipeline did all Gemini calls then a serial loop of exiftool
spawns — two stages that could not overlap. New pipeline uses a
shared ExiftoolBatch instance; each worker writes metadata right
after its Gemini call. For 1000 photos at concurrency=5 this cuts
total time from ~18min to ~11min alongside the -stay_open change.

Also tightens semantics: save_result('completed') now happens only
after metadata successfully lands on disk, matching the watcher's
per-photo transaction boundary."
```

---

## Task 8: `App.vue` 修更新 polling 洩漏

**Files:**
- Modify: `frontend/src/App.vue`

**動機：** 使用者按「稍後」或遇到錯誤時，500ms polling 不停。Bobo 的 pywebview 一開一整天，會打爆 `/api/update/status`。

- [ ] **Step 1: 讀目前 polling 程式碼**

Run: `grep -n "startPolling\|stopPolling\|dismissUpdate\|setInterval" frontend/src/App.vue`

- [ ] **Step 2: 修 dismissUpdate + 改 interval**

在 `frontend/src/App.vue` 內找到 `dismissUpdate()` 函式，確保它呼叫 `stopPolling()`；`startPolling()` 的 `setInterval` 第二參數從 `500` 改成 `2000`；`setInterval` 回 handle 的變數必須確認被 `stopPolling` 清到。

具體 patch（以現行碼為基礎；若欄位命名不同請調整）：

```javascript
// Before:
function dismissUpdate() {
  update.show = false
}

// After:
function dismissUpdate() {
  update.show = false
  stopPolling()
}
```

```javascript
// startPolling: change 500 -> 2000
pollTimer = setInterval(async () => {
  // ... existing body ...
}, 2000)
```

確保 `stopPolling` 會在以下三種情況都被呼叫：
1. `dismissUpdate()`（使用者按稍後）
2. 收到 `status === 'ready'`
3. 收到 `status === 'error'`

- [ ] **Step 3: 手動驗證**

Run: `make dev`，在瀏覽器 DevTools 開 Network tab。
場景：假裝有更新 → 看到 banner → 按「稍後」。
Expected: Network tab 不再每 2 秒打一次 `/api/update/status`；完全停掉。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.vue
git commit -m "fix(frontend): stop update polling on dismiss, widen interval to 2s

Previously clicking '稍後' left the 500ms interval running forever,
which accumulated thousands of /api/update/status calls over a long
pywebview session."
```

---

## Final verification

- [ ] **Step 1: 全部測試通過**

Run: `make verify`
Expected: lint + test 全 PASS。

- [ ] **Step 2: 煙霧測試（smoke test）— 真實照片 e2e**

Run: `make dev`，準備 5 張真實 JPG 放到 `for_TEST_PHOTO/`。
1. 在 UI 指到該資料夾、啟動 watcher
2. 檢查 log：watcher 只啟動一次（Task 3）
3. 等 5 張處理完，看總時間（應比之前快明顯 — exiftool batch 的效果）
4. 用 `exiftool for_TEST_PHOTO/*.jpg` 確認 IPTC/XMP 寫入
5. 關 pywebview、重開，確認 dismissed 的更新 banner 不會一直重複 check

Expected: 所有照片有正確 metadata，沒有 `database is locked` 錯誤，log 乾淨。

- [ ] **Step 3: bump VERSION**

編輯 `VERSION`：`0.2.0` → `0.2.1`。

- [ ] **Step 4: Final commit**

```bash
git add VERSION
git commit -m "chore: bump version to 0.2.1

Phase 1 reliability & performance improvements:
- SQLite WAL + indexes + thread-safe writes
- ExiftoolBatch (-stay_open) cuts per-photo metadata from 350ms to 40ms
- Pipeline interleaves metadata with analysis
- Update download mutex prevents .app corruption on double-click
- genai.Client cached per api_key
- Werkzeug reloader guard stops double-watcher in dev
- Frontend dead views removed, update polling no longer leaks"
```

---

## Next Plan（Phase 2 — 不在這份計劃）

下一份計劃（另開一份 `.md`）會處理：

1. **Updater 安全**：`codesign --verify`、SHA256 checksum、zip slip 防護、白名單檔名、大小上限
2. **API 認證**：per-session token 注入到 pywebview、Origin + Host header 檢查、`/api/browse` 與 `/api/photo` 路徑 sandbox
3. **API key → macOS Keychain**（用 `keyring` package）
4. **Pipeline 統一到 watcher 之上**（消除雙重執行引擎）
5. **補測試**：updater.py 全套、analysis/results/settings/export API blueprints、真實 JPG E2E
6. **前端**：`visibilitychange` refresh、fetch timeout helper、SSE 斷線 UI 提示、`formatTime` tick
7. **`folder_watcher.set_concurrency`**：改成重建 executor（不動 private `_max_workers`）

---

## Self-Review 已完成

- ✅ Spec coverage：六位專家報告中所有 week-one 級別的項目都有對應 task
- ✅ 無 placeholder：每 step 都有具體 code / command / expected
- ✅ 型別 / 命名一致：`ExiftoolBatch.write / close / __enter__` 在 Task 6 定義、Task 7 使用同名
- ✅ TDD：每個改動先寫測試、看失敗、再實作
- ✅ 小 commit：8 個功能 task + 1 個收尾，每個都是獨立可 revert 的
