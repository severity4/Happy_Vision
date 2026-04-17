# Happy Vision P0 可靠性加固計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉 ultrareview 找到的 P0 critical 問題，讓 v0.3.4 在長時間運作、使用者檔名怪異、API/exiftool 失聯時不會「靜悄悄地」卡住或洩漏敏感資訊。

**Architecture:** 純後端 TDD 小步改動。不動架構、不動前端、不動 API schema、不動 DB schema。每個 task 獨立 commit，任何一個中斷都不破壞現有功能。

**Tech Stack:** Python 3.10+、pytest、現有 `modules/` 模組。不引入新依賴。

**範圍外（留待 Phase 2）：** SSE heartbeat、SQLite integrity check、路徑 traversal 加固、前端 backoff、日誌 rotation、端到端 regression test、常數外部化、依賴鎖版。

---

## File Structure

**Modify：**
- `modules/gemini_vision.py` — `analyze_photo` 的 rate limiter 加 timeout；retry 涵蓋更多錯誤碼；`generate_content` 加 HTTP timeout
- `modules/metadata_writer.py` — `ExiftoolBatch` 拒絕含換行/NUL 的 path；`_run_batch` 的 readline 加 select-based timeout 與 auto-restart
- `modules/logger.py` — 加 `SensitiveDataFilter` 掛到所有 handler

**Test（擴充既有檔）：**
- `tests/test_gemini_vision.py` — timeout / 新 retry 碼覆蓋
- `tests/test_metadata_writer.py` — path injection 拒絕、readline timeout 恢復

**Test（新增檔）：**
- `tests/test_logger.py` — SensitiveDataFilter 脫敏

---

## Task 1: Gemini rate limiter 加入 timeout 防止永久阻塞

**Files:**
- Modify: `modules/gemini_vision.py:150-208`
- Test: `tests/test_gemini_vision.py`

**動機：** 目前 `default_limiter.acquire()` 無 timeout（`gemini_vision.py:165`）。若有 bug 讓 token 永遠補不回來、或 rate_per_minute 被設成極小值，整個 worker thread 會永久阻塞，使用者按 cancel 也無法穿透（cancel 只 set pause event，rate limiter 不受影響）。

### Step 1: 寫測試（先失敗）

加到 `tests/test_gemini_vision.py` 末尾：

- [ ] **Step 1: 新增 timeout 測試**

```python
def test_analyze_photo_respects_rate_limiter_timeout(tmp_path, monkeypatch):
    """若 rate_limiter.acquire 回 False (timeout), analyze_photo 必須放棄, 不能卡在 API 呼叫上."""
    from modules import gemini_vision
    from modules import rate_limiter

    img_path = tmp_path / "test.jpg"
    _create_test_jpg(img_path)

    monkeypatch.setattr(rate_limiter.default_limiter, "acquire",
                        lambda timeout=None: False)

    # 就算 client 還在, 也絕不該呼叫到 generate_content
    call_count = {"n": 0}

    def fail_if_called(*a, **kw):
        call_count["n"] += 1
        raise AssertionError("generate_content should not be reached when rate-limited out")

    with patch("modules.gemini_vision.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.side_effect = fail_if_called

        result = gemini_vision.analyze_photo(str(img_path), api_key="fake", model="lite")

    assert result is None
    assert call_count["n"] == 0
```

- [ ] **Step 2: 跑測試，確認失敗**

Run: `pytest tests/test_gemini_vision.py::test_analyze_photo_respects_rate_limiter_timeout -v`

Expected: FAIL（目前 `acquire()` 無 timeout 且無回傳值檢查，`generate_content` 會被呼叫）

- [ ] **Step 3: 改實作**

修改 `modules/gemini_vision.py:165` 前後：

```python
    client = _get_client(api_key)

    # Global rate limit (shared by pipeline workers and folder watcher)
    # 60s cap lets cancel/shutdown propagate instead of blocking forever.
    if not default_limiter.acquire(timeout=60):
        log.warning("Rate limiter timeout for %s — giving up", photo_path)
        return None

    for attempt in range(max_retries):
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_gemini_vision.py::test_analyze_photo_respects_rate_limiter_timeout -v`

Expected: PASS

- [ ] **Step 5: commit**

```bash
git add modules/gemini_vision.py tests/test_gemini_vision.py
git commit -m "fix(gemini): bound rate-limiter wait with 60s timeout

Prevents worker threads hanging forever if the token bucket is
misconfigured or cancel happens while waiting for a token."
```

---

## Task 2: Gemini retry 涵蓋 DEADLINE_EXCEEDED / RESOURCE_EXHAUSTED / UNAVAILABLE

**Files:**
- Modify: `modules/gemini_vision.py:196-205`
- Test: `tests/test_gemini_vision.py`

**動機：** 現行只比對字串 `"429"`/`"500"`/`"503"` 是否出現在 error message（`gemini_vision.py:198`）。google-genai SDK 實際丟出的 gRPC 錯誤訊息常是：`DEADLINE_EXCEEDED`（請求超時）、`RESOURCE_EXHAUSTED`（quota 用光）、`UNAVAILABLE`（服務暫時掛掉）、`INTERNAL`。這些都應該 retry，不該第一次失敗就 `return None`。

### Step 1: 寫測試

- [ ] **Step 1: 新增 retry 涵蓋測試**

加到 `tests/test_gemini_vision.py`：

```python
def test_analyze_photo_retries_on_deadline_exceeded(tmp_path, monkeypatch):
    """DEADLINE_EXCEEDED / RESOURCE_EXHAUSTED / UNAVAILABLE 都要 retry, 不能第一發就放棄."""
    from modules import gemini_vision
    from modules import rate_limiter

    img_path = tmp_path / "test.jpg"
    _create_test_jpg(img_path)

    # 放 rate limiter 通
    monkeypatch.setattr(rate_limiter.default_limiter, "acquire",
                        lambda timeout=None: True)
    # 把 time.sleep 變 no-op 讓測試秒跑
    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    good_response = MagicMock()
    good_response.text = json.dumps({"title": "ok", "description": "", "keywords": [],
                                     "category": "other", "scene_type": "indoor",
                                     "mood": "neutral", "people_count": 0})

    call_sequence = [
        Exception("DEADLINE_EXCEEDED: request timed out"),
        Exception("RESOURCE_EXHAUSTED: quota"),
        good_response,
    ]

    with patch("modules.gemini_vision.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.side_effect = call_sequence

        result = gemini_vision.analyze_photo(str(img_path), api_key="fake",
                                             model="lite", max_retries=3)

    assert result is not None
    assert result["title"] == "ok"


def test_analyze_photo_does_not_retry_on_permanent_error(tmp_path, monkeypatch):
    """INVALID_ARGUMENT / PERMISSION_DENIED 不該 retry."""
    from modules import gemini_vision
    from modules import rate_limiter

    img_path = tmp_path / "test.jpg"
    _create_test_jpg(img_path)

    monkeypatch.setattr(rate_limiter.default_limiter, "acquire",
                        lambda timeout=None: True)
    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    call_count = {"n": 0}

    def raise_permanent(*a, **kw):
        call_count["n"] += 1
        raise Exception("INVALID_ARGUMENT: bad model name")

    with patch("modules.gemini_vision.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.side_effect = raise_permanent

        result = gemini_vision.analyze_photo(str(img_path), api_key="fake",
                                             model="lite", max_retries=3)

    assert result is None
    assert call_count["n"] == 1  # 只試一次, 沒 retry
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_gemini_vision.py -k "retries_on_deadline or permanent_error" -v`

Expected: 兩個 test FAIL（DEADLINE_EXCEEDED 不在現有字串白名單，第一次拋就 return None）

- [ ] **Step 3: 改實作**

把 `modules/gemini_vision.py:196-205` 的 `except Exception` 段換成：

```python
        except Exception as e:
            error_str = str(e)
            retryable_markers = (
                "429", "500", "502", "503", "504",
                "DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED",
                "UNAVAILABLE", "INTERNAL",
            )
            if any(m in error_str for m in retryable_markers):
                wait = 2 ** attempt
                log.warning("Retryable API error for %s (attempt %d/%d), retry in %ds: %s",
                            photo_path, attempt + 1, max_retries, wait, error_str)
                time.sleep(wait)
                continue
            log.error("API error for %s: %s", photo_path, error_str)
            return None
```

- [ ] **Step 4: 跑全部 gemini 測試**

Run: `pytest tests/test_gemini_vision.py -v`

Expected: 全部 PASS（含既有測試）

- [ ] **Step 5: commit**

```bash
git add modules/gemini_vision.py tests/test_gemini_vision.py
git commit -m "fix(gemini): retry on DEADLINE_EXCEEDED, RESOURCE_EXHAUSTED, UNAVAILABLE

Previously only HTTP numeric codes triggered retries; gRPC-style
errors from google-genai (DEADLINE_EXCEEDED etc.) fell through and
caused a single-shot failure on transient issues."
```

---

## Task 3: ExiftoolBatch 拒絕含換行/NUL 的 photo path

**Files:**
- Modify: `modules/metadata_writer.py:159-164`（`write()` 和 `read_json()` 前加 guard）
- Test: `tests/test_metadata_writer.py`

**動機：** exiftool 的 `-stay_open True -@ -` 模式以 `\n` 分隔 arg。使用者照片夾中若有檔名含 `\n`（極罕見但可發生於 macOS，因為 HFS+/APFS 允許），會破壞 batch 協定，之後所有寫入都會錯亂。NUL byte 同樣會被 exiftool 視為結束。現行 `write(photo_path, ...)` 直接把 path 當 arg 餵 stdin，沒檢查。

### Step 1: 寫測試

- [ ] **Step 1: 新增 path 安全檢查測試**

加到 `tests/test_metadata_writer.py` 末尾：

```python
def test_exiftool_batch_rejects_path_with_newline(monkeypatch):
    """含換行的 path 會破壞 -@ - 協定, 必須拒絕而不是送進去."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
        def readline(self): return "{ready}\n"
        def wait(self, timeout=None): return 0
        def poll(self): return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/bad\nname.jpg", ["-IPTC:Headline=X"])

    assert ok is False
    # 絕不能把壞 path 送進 stdin
    assert "bad\nname.jpg" not in fake.stdin.getvalue()


def test_exiftool_batch_rejects_path_with_nul(monkeypatch):
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
        def readline(self): return "{ready}\n"
        def wait(self, timeout=None): return 0
        def poll(self): return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/nul\x00name.jpg", ["-IPTC:Headline=X"])
    assert ok is False


def test_exiftool_batch_rejects_arg_with_newline(monkeypatch):
    """Args 本身含 \\n 也會破壞協定 (譬如 caption 含換行被直接塞)."""
    from modules import metadata_writer
    import io

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = self
        def readline(self): return "{ready}\n"
        def wait(self, timeout=None): return 0
        def poll(self): return None

    fake = FakeProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: fake)

    batch = metadata_writer.ExiftoolBatch()
    ok = batch.write("/tmp/ok.jpg", ["-IPTC:Caption-Abstract=line1\nline2"])
    assert ok is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_metadata_writer.py -k "rejects" -v`

Expected: 三個 test FAIL（目前沒 guard，write 會回 True）

- [ ] **Step 3: 改實作**

在 `modules/metadata_writer.py` 的 `ExiftoolBatch` class 裡，把 `_run_batch` 最前面加 guard：

```python
    _UNSAFE_CHARS = ("\n", "\r", "\x00")

    def _run_batch(self, args: list[str]) -> tuple[bool, str]:
        """Feed args + -execute, read output until {ready}. Returns (ok, output)."""
        for arg in args:
            if any(c in arg for c in self._UNSAFE_CHARS):
                log.error("Rejecting exiftool arg with unsafe chars: %r", arg)
                return False, "unsafe arg"
        with self._lock:
            try:
                for arg in args:
                    self._proc.stdin.write(arg + "\n")
                self._proc.stdin.write("-execute\n")
                self._proc.stdin.flush()
            ...
```

- [ ] **Step 4: 跑全 metadata 測試**

Run: `pytest tests/test_metadata_writer.py -v`

Expected: 全部 PASS

- [ ] **Step 5: commit**

```bash
git add modules/metadata_writer.py tests/test_metadata_writer.py
git commit -m "fix(metadata_writer): reject newline/NUL in exiftool batch args

The -stay_open -@ - protocol uses newline as arg separator, so a
filename or caption containing \\n silently corrupts the session
and affects every subsequent write. Guard at the entry point."
```

---

## Task 4: ExiftoolBatch readline 加 timeout 防止無限卡住

**Files:**
- Modify: `modules/metadata_writer.py:132-157`（`_run_batch` 的 readline loop）
- Test: `tests/test_metadata_writer.py`

**動機：** 目前 `self._proc.stdout.readline()`（`metadata_writer.py:145`）若 exiftool hang 住（檔案 lock、ICC profile 損壞、磁碟 I/O 卡死）會永久阻塞。我們持有 `self._lock`，所以其他 thread 也全卡。必須有 timeout + auto-kill + 標記需重啟。

**設計：** 用 `select.select(fd, timeout=...)` 包 readline。累積 30 秒沒動靜就：殺 process、清狀態、回 `(False, "timeout")`。下一次 `_run_batch` 呼叫時，`_proc.poll()` 已非 None，現有的 `BrokenPipeError` 路徑（line 140-141）會自然攔截 — 但我們要在那之前就嘗試重啟一次，才不會所有後續照片都失敗。

**設計細節：** `_readline_with_timeout` 若 stdout 沒 `fileno()`（既有測試 FakeProc 就是這樣）就 fallback 到普通 readline，保持既有測試不變。

### Step 1: 寫測試

- [ ] **Step 1: 在 `tests/test_metadata_writer.py` 末尾新增 timeout 測試**

```python
def test_exiftool_batch_timeout_when_readline_hangs(monkeypatch):
    """readline 無資料時, _run_batch 在 timeout 後必須放棄並 kill, 不能卡死."""
    from modules import metadata_writer
    import io
    import os
    import time

    class HangingProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self._killed = False
            # A pipe that never gets written to — select() will time out.
            self._r, self._w = os.pipe()

            outer = self

            class _StdoutLike:
                def fileno(self_inner):
                    return outer._r
                def readline(self_inner):
                    return ""  # should never be reached

            self.stdout = _StdoutLike()

        def kill(self):
            if not self._killed:
                self._killed = True
                os.close(self._r)
                os.close(self._w)

        def wait(self, timeout=None):
            return -9

        def poll(self):
            return -9 if self._killed else None

    hanging = HangingProc()
    monkeypatch.setattr(metadata_writer.subprocess, "Popen", lambda *a, **kw: hanging)
    monkeypatch.setattr(metadata_writer, "EXIFTOOL_READ_TIMEOUT_SEC", 0.2)

    batch = metadata_writer.ExiftoolBatch()
    start = time.monotonic()
    ok = batch.write("/tmp/p.jpg", ["-IPTC:Headline=X"])
    elapsed = time.monotonic() - start

    assert ok is False
    assert elapsed < 2.0, f"should have timed out fast, got {elapsed:.2f}s"
    assert hanging._killed is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_metadata_writer.py::test_exiftool_batch_timeout_when_readline_hangs -v --timeout=10`

Expected: FAIL — `EXIFTOOL_READ_TIMEOUT_SEC` 不存在（AttributeError on monkeypatch）

- [ ] **Step 3: 改實作**

在 `modules/metadata_writer.py` 最上方既有 import 區加：

```python
import io
import select
```

在 `log = setup_logger(...)` 下方加模組常數：

```python
# Max seconds to wait for one line from exiftool before killing the process.
EXIFTOOL_READ_TIMEOUT_SEC = 30.0
```

在 `ExiftoolBatch` class 的 `_run_batch` method **之前**新增 helper method：

```python
    def _readline_with_timeout(self, timeout: float) -> str | None:
        """Read one line. Returns None if no data within timeout. Returns ''
        on EOF / dead process. Falls back to blocking readline when the
        stdout doesn't expose a real fd (e.g. fake streams in tests)."""
        stdout = self._proc.stdout
        try:
            fd = stdout.fileno()
        except (AttributeError, ValueError, io.UnsupportedOperation):
            return stdout.readline()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        return stdout.readline()
```

把 `_run_batch` 中既有的 readline 迴圈（`while True: line = self._proc.stdout.readline()`）換成：

```python
            output_lines = []
            while True:
                line = self._readline_with_timeout(EXIFTOOL_READ_TIMEOUT_SEC)
                if line is None:
                    log.error("exiftool unresponsive after %.1fs, killing",
                              EXIFTOOL_READ_TIMEOUT_SEC)
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                    return False, "exiftool read timeout"
                if not line:
                    return False, "".join(output_lines)  # process died
                if line.strip() == "{ready}":
                    break
                output_lines.append(line)
```

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_metadata_writer.py -v --timeout=15`

Expected: 全部 PASS。既有 FakeProc 測試（沒 `fileno`）走 fallback 路徑，行為與改動前一致。新 HangingProc 測試因為 `select()` 永不 ready，觸發 timeout 分支回 `False`。

- [ ] **Step 5: commit**

```bash
git add modules/metadata_writer.py tests/test_metadata_writer.py
git commit -m "fix(metadata_writer): bound exiftool readline with 30s select timeout

If exiftool hangs (file lock, corrupt ICC profile, disk I/O stall)
the batch lock was held forever, freezing every worker. Now we
select() with timeout and kill the process on stall."
```

---

## Task 5: Logger 加脫敏 filter，清掉 API key / Bearer token

**Files:**
- Modify: `modules/logger.py`
- Create: `tests/test_logger.py`

**動機：** `gemini_vision.py:200,204` 會把 `error_str` 寫進 log，而 google-genai 的錯誤訊息偶爾包含 request URL 或原始 payload。若使用者 API key 或 access token 以 `key=AIza...` / `Bearer ...` 形式出現在任何 log record 的 msg/args，就被寫進 `~/.happy-vision/logs/YYYY-MM-DD.log` 成為明文。這個資料夾可能被同步到 Time Machine、iCloud Desktop、傳給客服。

### Step 1: 寫測試（創新檔）

- [ ] **Step 1: 建立 tests/test_logger.py**

Create `tests/test_logger.py`:

```python
"""tests/test_logger.py — SensitiveDataFilter strips keys from log records."""

import logging

from modules.logger import SensitiveDataFilter


def _apply(msg: str, *args) -> str:
    rec = logging.LogRecord(
        name="t", level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=args, exc_info=None,
    )
    SensitiveDataFilter().filter(rec)
    return rec.getMessage()


def test_scrubs_gemini_api_key():
    out = _apply("error from key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    assert "AIza" not in out
    assert "REDACTED" in out


def test_scrubs_bearer_token():
    out = _apply("Authorization: Bearer ya29.abcdef.GhIjKlMn_opqrstUVwxyz")
    assert "ya29" not in out
    assert "REDACTED" in out


def test_scrubs_api_key_query_param():
    out = _apply("GET https://example.com?api_key=sk-1234567890abcdef&foo=bar")
    assert "sk-1234567890abcdef" not in out
    assert "foo=bar" in out  # non-sensitive stays


def test_scrubs_api_key_in_args():
    """Arguments passed as %s substitution must also be scrubbed."""
    out = _apply("api failed: %s", "key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 bad request")
    assert "AIza" not in out


def test_does_not_touch_safe_text():
    out = _apply("Analyzed photo.jpg: speaker on stage")
    assert out == "Analyzed photo.jpg: speaker on stage"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_logger.py -v`

Expected: FAIL — `SensitiveDataFilter` 還不存在

- [ ] **Step 3: 改實作**

把 `modules/logger.py` 整檔換成：

```python
"""modules/logger.py — Logging setup for Happy Vision"""

import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


_REDACT = "REDACTED"

_PATTERNS = [
    # Google API key style (AIza + 35 chars)
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    # Bearer tokens (Authorization header or raw)
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    # ?api_key=xxx / &api_key=xxx / key=xxx query params
    re.compile(r"(?i)\b(api[_\-]?key|access[_\-]?token|key)=([A-Za-z0-9._\-]+)"),
    # Google OAuth access tokens (ya29.xxxx)
    re.compile(r"ya29\.[A-Za-z0-9._\-]+"),
]


def _scrub(text: str) -> str:
    for pat in _PATTERNS:
        if pat.groups == 2:
            text = pat.sub(lambda m: f"{m.group(1)}={_REDACT}", text)
        else:
            text = pat.sub(_REDACT, text)
    return text


class SensitiveDataFilter(logging.Filter):
    """Scrubs API keys / bearer tokens from log records before they hit handlers.

    Operates on both ``msg`` (after %-formatting) and raw string ``args``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    _scrub(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (_scrub(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        return True


def setup_logger(name: str = "happy_vision") -> logging.Logger:
    """Set up a logger that writes to ~/.happy-vision/logs/ and stdout."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    sensitive_filter = SensitiveDataFilter()

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    console.addFilter(sensitive_filter)
    logger.addHandler(console)

    # File handler
    try:
        log_dir = get_config_dir() / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{datetime.now():%Y-%m-%d}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError:
        fallback_dir = Path(tempfile.gettempdir()) / "happy-vision-logs"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        log_file = fallback_dir / f"{datetime.now():%Y-%m-%d}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    file_handler.addFilter(sensitive_filter)
    logger.addHandler(file_handler)

    return logger
```

- [ ] **Step 4: 跑整個測試集**

Run: `pytest tests/test_logger.py -v`

Expected: 全部 PASS

Run: `pytest tests/ -q`

Expected: 全 suite PASS（filter 不動 record 結構，不該打壞任何既有測試）

- [ ] **Step 5: commit**

```bash
git add modules/logger.py tests/test_logger.py
git commit -m "feat(logger): scrub API keys and bearer tokens from log records

Prevents Gemini API keys (AIza...), Google OAuth tokens (ya29...),
and api_key query params from landing in ~/.happy-vision/logs/*.log
when an upstream error message echoes the request URL or payload."
```

---

## Task 6: Bump VERSION + CHANGELOG

**Files:**
- Modify: `VERSION`
- Create or modify: `CHANGELOG.md`（若不存在，先檢查）

- [ ] **Step 1: 確認目前版本**

Run: `cat VERSION`

- [ ] **Step 2: 查看是否有 CHANGELOG.md**

Run: `ls CHANGELOG.md 2>/dev/null || echo "missing"`

- [ ] **Step 3: 把 VERSION 從 `0.3.3` 改成 `0.3.4`**

Edit `VERSION`: `0.3.3` → `0.3.4`

- [ ] **Step 4: 在 CHANGELOG.md（若有）頂端、或新建，加 v0.3.4 區段**

```markdown
## v0.3.4 — 2026-04-17

### Reliability
- Gemini analyze: rate-limiter wait now capped at 60s (previously could block forever).
- Gemini analyze: retry on `DEADLINE_EXCEEDED`, `RESOURCE_EXHAUSTED`, `UNAVAILABLE`, `INTERNAL` (previously only HTTP numeric codes).
- exiftool batch: readline now has a 30s timeout + kill-on-stall to prevent freezing worker pool if exiftool hangs.
- exiftool batch: reject args containing `\n`, `\r`, or NUL — these silently corrupt the `-@ -` stdin protocol.

### Security
- Logger: scrub Google API keys (`AIza...`), OAuth tokens (`ya29...`), `Bearer` tokens, and `api_key=` query params from all log records before writing to disk.
```

- [ ] **Step 5: commit**

```bash
git add VERSION CHANGELOG.md
git commit -m "chore: bump version to 0.3.4"
```

---

## Final verification

- [ ] **Step 1: 跑全測試 + lint**

Run: `make verify`

Expected: ruff PASS, pytest 全 PASS。

- [ ] **Step 2: 手動煙測**

Run: `python3 web_ui.py` 開啟 UI，選一個含 5-10 張真實照片的資料夾，選「寫入 metadata」、model=lite，按開始。觀察：
  - 完成率 100%
  - 日誌檔 `~/.happy-vision/logs/2026-04-17.log` 裡面沒有任何 `AIza` 字串（tail + grep 確認）

- [ ] **Step 3: 若一切 OK，準備 release**

這份計劃只完成 code + test。正式發 v0.3.4 由使用者下一個指令 `部署 v0.3.4` 觸發既有 release flow。
