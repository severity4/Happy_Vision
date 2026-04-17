# Happy Vision Phase 2C UX polish + 測試覆蓋計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉 UX review 剩下的真實痛點（背景回前景狀態過期、fetch 永遠卡 loading、SSE 斷線 UI 無感、更新 banner 重複彈），補齊缺覆蓋的 API blueprint 測試 + 一條真實 JPG E2E 測試，並修掉 Phase 2B 留下的 flaky 測試。

**Architecture:** 
- 前端：在既有 `main.js` 的 `window.fetch` wrapper 再包一層 `AbortController` timeout（所有 call site 零改動）。`App.vue` 加 `visibilitychange` listener。`stores/watch.js` 的 `sseConnected` 改 `ref` 並 export。`MonitorView.vue` 加個迷你 badge 顯示斷線。
- 後端測試：建 `tests/test_analysis_api.py` 和 `tests/test_export_api.py`（settings 和 results 已在 Phase 2A 測試中涵蓋）。建 `tests/test_e2e.py` 用真實 JPG 驗證完整流程；`exiftool` 不存在時 skip。
- Flaky test 修復：watcher 不要 re-enqueue 已 `failed` 的照片（這也同時消除 test timing race）。

**Tech Stack:** Vue 3 Composition API、Pinia、既有 Flask test_client、真實 exiftool（optional E2E）。

**Phase 3（未來）：** Apple Developer codesign/notarization、pipeline 完整併入 watcher、watchdog FSEvents 取代 polling。

---

## File Structure

**新檔：**
- `tests/test_analysis_api.py` — `/api/analysis/{start,pause,resume,cancel,stream}`
- `tests/test_export_api.py` — `/api/export/{csv,json}` + error paths
- `tests/test_e2e.py` — 真實 JPG → Gemini(mock) → metadata(real) → CSV → re-scan skip

**改檔：**
- `modules/folder_watcher.py::_scan_folder_into_queue` — 加入 `status == "failed"` 也 skip（同時修 flaky test）
- `frontend/src/main.js` — fetch wrapper 加 AbortController timeout (預設 30s)
- `frontend/src/App.vue` — `visibilitychange` refresh + `dismissUpdate` 寫 localStorage + `checkForUpdate` 讀 localStorage
- `frontend/src/stores/watch.js` — `sseConnected` 改 ref + export
- `frontend/src/views/MonitorView.vue` — SSE 斷線 badge + `timeTick` ref 讓 `formatTime` 自動重算

---

## Task 1: 修 flaky watcher test — skip failed photos in scan

**Files:**
- Modify: `modules/folder_watcher.py::_scan_folder_into_queue`
- Modify: `tests/test_folder_watcher.py` (加 1 個 regression test，原有 flaky test 維持綠)

**動機：** Phase 2B 的 `test_watcher_metadata_failure_marks_failed_not_completed` 約 25% fail rate。原因：第一次分析失敗、mark_failed，但 poll loop（interval=1s）在 test 的 5s 等待內再次掃描，看到 `status="failed"` 不等於 `"completed"` → 再 enqueue → 又跑一次 → `on_error` 被 callback 兩次 → test 斷言 `len(errors) == 1` 失敗。

實際 bug：watcher 重試已經失敗的照片會永遠 loop。DB 已經標記失敗的照片不該無限重試；使用者要重試應該手動（比如 reset-failed endpoint，未來）。修 watcher 順便修 test。

### Step 1: 寫測試

加到 `tests/test_folder_watcher.py`：

```python
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
```

### Step 2: 跑測試確認失敗

Run: `pytest tests/test_folder_watcher.py::test_scan_skips_failed_photos -v`
Expected: FAIL — currently `status == "failed"` 不會被 skip（第 239 行只 skip `completed`）。

### Step 3: 改 `_scan_folder_into_queue`

編輯 `modules/folder_watcher.py`，找到：

```python
            # Fast path: check local DB first
            status = self._store.get_status(photo_path)
            if status == "completed":
                skipped += 1
                continue
```

改成：

```python
            # Fast path: check local DB first. Skip both completed and failed —
            # failed photos are not auto-retried; user must clear status manually.
            status = self._store.get_status(photo_path)
            if status in ("completed", "failed"):
                skipped += 1
                continue
```

### Step 4: 跑測試

Run: `pytest tests/test_folder_watcher.py -v`
Expected: 全 PASS（原有 + 新 1）。並且原本 flaky 的 `test_watcher_metadata_failure_marks_failed_not_completed` 現在穩定。

Run: `for i in $(seq 1 10); do pytest tests/test_folder_watcher.py::test_watcher_metadata_failure_marks_failed_not_completed -q 2>&1 | tail -1; done`
Expected: 10 次全 pass。

Run: `pytest -q`
Expected: 153 passed（152 + 1）。

### Step 5: Commit

```bash
git add modules/folder_watcher.py tests/test_folder_watcher.py
git commit -m "fix(folder_watcher): don't re-enqueue failed photos

Scanning the watch folder now skips photos whose DB status is 'failed'
in addition to 'completed'. Previously a photo that failed analysis
(e.g. Gemini 500, metadata write error) would be retried on every
poll cycle, burning API quota and spamming error callbacks.

Side benefit: removes a race in test_watcher_metadata_failure_marks_
failed_not_completed where the poll loop's re-enqueue fought with the
test's assertion window, causing ~25% flake rate."
```

---

## Task 2: 前端 fetch timeout helper

**Files:**
- Modify: `frontend/src/main.js` (加 timeout 到既有 fetch wrapper)

**動機：** pywebview 內的 fetch 若後端慢到沒回（Gemini 巨慢、watcher 爆量同時）會永遠 pending，UI 卡「載入中…」。加 30 秒 timeout，timeout 後 throw AbortError，呼叫端的 try/catch 就能顯示錯誤。

### Design

既有 `main.js` 已經有 `window.fetch` monkeypatch（Phase 2A Task 1 加的，為了 X-HV-Token）。在那個 wrapper 裡加 `AbortController`，既有 call sites 零改動。

### Step 1: 改 `frontend/src/main.js`

Read 當前內容：

```bash
cat frontend/src/main.js
```

找到現有 wrapper（形如）：

```javascript
const token = document.querySelector('meta[name="hv-token"]')?.content
if (token && token !== '__HV_TOKEN__') {
  window.__HV_TOKEN__ = token
  const originalFetch = window.fetch
  window.fetch = (input, init = {}) => {
    const headers = new Headers(init.headers || {})
    headers.set('X-HV-Token', token)
    return originalFetch(input, { ...init, headers })
  }
}
```

改成加 timeout：

```javascript
const DEFAULT_FETCH_TIMEOUT_MS = 30_000

const token = document.querySelector('meta[name="hv-token"]')?.content
if (token && token !== '__HV_TOKEN__') {
  window.__HV_TOKEN__ = token
  const originalFetch = window.fetch
  window.fetch = (input, init = {}) => {
    const headers = new Headers(init.headers || {})
    headers.set('X-HV-Token', token)

    // Honor caller-supplied signal; otherwise impose default timeout.
    if (init.signal) {
      return originalFetch(input, { ...init, headers })
    }
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), DEFAULT_FETCH_TIMEOUT_MS)
    return originalFetch(input, { ...init, headers, signal: ctrl.signal })
      .finally(() => clearTimeout(timer))
  }
}
```

Key behaviors:
- If caller supplies `init.signal` (future use), respect it and don't impose timeout
- Otherwise, abort after 30s
- `clearTimeout` on completion to avoid dangling timers

### Step 2: build 確認沒壞

Run: `cd frontend && npm run build 2>&1 | tail -3`
Expected: 成功、index.html 仍含 `__HV_TOKEN__` placeholder。

### Step 3: 手動驗證（可選）

在瀏覽器 devtools：
```javascript
// Simulate slow endpoint — expect abort after 30s
const ctrl = new AbortController()
fetch('/api/watch/status').catch(e => console.log('got:', e.name))
```
若後端正常回應 <30s 應該正常；若人工延遲（stopping Flask 服務）則 30s 後 AbortError。

因為 AbortController 行為 prod 才看得清，此 task 不寫自動測試（純前端 wrapper，沒 unit test 框架）。信心來自：
- 邏輯本身 3 行，可靠
- Happy path 已由所有現有 pytest 覆蓋（test_client 仍可用）

### Step 4: Commit

```bash
git add frontend/src/main.js
git commit -m "feat(frontend): 30s default timeout on all fetch calls

The global fetch wrapper (which already injects X-HV-Token) now also
wraps requests in an AbortController with a 30-second deadline. Avoids
the UI getting stuck on an indefinite 'loading…' if the backend is
unresponsive. Caller-supplied signal is respected without injecting
an additional timeout."
```

---

## Task 3: 前端 visibilitychange refresh + SSE 斷線 badge

**Files:**
- Modify: `frontend/src/App.vue` (加 visibilitychange listener)
- Modify: `frontend/src/stores/watch.js` (`sseConnected` 改 ref + export)
- Modify: `frontend/src/views/MonitorView.vue` (加迷你 badge)

**動機：** 
1. Bobo 把 pywebview 視窗放背景 → WebKit 會 throttle 甚至斷開 SSE → 回前景時看到 queueSize/recentItems 是舊的，以為 watcher 沒在跑。
2. `sseConnected` 目前是 watch store 內的 `let`，沒 reactive、UI 無法顯示。

### Step 1: 改 `stores/watch.js`

Read 當前內容 (around line 15):
```javascript
  let eventSource = null
  let reconnectTimer = null
  let sseConnected = false
```

改成：
```javascript
  let eventSource = null
  let reconnectTimer = null
  const sseConnected = ref(false)
```

在 connectSSE 裡：
```javascript
    eventSource.onopen = () => {
      sseConnected = true
    }
```
改成：
```javascript
    eventSource.onopen = () => {
      sseConnected.value = true
    }
```

`onerror` 裡：
```javascript
    eventSource.onerror = () => {
      sseConnected = false
```
改成：
```javascript
    eventSource.onerror = () => {
      sseConnected.value = false
```

`disconnectSSE` 內：
```javascript
    sseConnected = false
```
改成：
```javascript
    sseConnected.value = false
```

最後，將 `sseConnected` 加入 store return：

找到：
```javascript
  return {
    status, folder, queueSize, processing, completedToday, failedToday, recentItems,
    init, connectSSE, disconnectSSE, fetchStatus, fetchRecent,
    startWatch, pauseWatch, resumeWatch, stopWatch, enqueueFolder,
  }
```

改成：
```javascript
  return {
    status, folder, queueSize, processing, completedToday, failedToday, recentItems,
    sseConnected,
    init, connectSSE, disconnectSSE, fetchStatus, fetchRecent,
    startWatch, pauseWatch, resumeWatch, stopWatch, enqueueFolder,
  }
```

### Step 2: 改 `App.vue` — 加 visibilitychange refresh

Read 既有 `onMounted` 和 `onUnmounted`（大約 line 184–200）：

```javascript
onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    version.value = data.version || ''
  } catch {}

  // Initialize watch store (fetch status, recent, connect SSE)
  watchStore.init()

  // Check for updates after a short delay (don't block startup)
  setTimeout(checkForUpdate, 2000)
})

onUnmounted(() => {
  stopPolling()
  watchStore.disconnectSSE()
})
```

加入 visibilitychange handler。在 `onMounted` 之後、`onUnmounted` 之前插入：

```javascript
function handleVisibilityChange() {
  if (!document.hidden) {
    watchStore.fetchStatus()
    watchStore.fetchRecent()
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
```

**注意**：Vue 可以有多個 `onMounted` 呼叫，但可讀性差。選擇：**把 addEventListener 合併到既有的 onMounted 區塊**。修改既有 `onMounted`：

```javascript
onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    version.value = data.version || ''
  } catch {}

  // Initialize watch store (fetch status, recent, connect SSE)
  watchStore.init()

  // Refresh store state when window comes back from background
  document.addEventListener('visibilitychange', handleVisibilityChange)

  // Check for updates after a short delay (don't block startup)
  setTimeout(checkForUpdate, 2000)
})

onUnmounted(() => {
  stopPolling()
  watchStore.disconnectSSE()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
```

函式 `handleVisibilityChange` 放 `<script setup>` 內、onMounted 上方。

### Step 3: 改 `MonitorView.vue` — 斷線 badge

Read：
```bash
grep -n "status\|watchStore\|queueSize\|<template>" frontend/src/views/MonitorView.vue | head -20
```

找 status panel 或頂部區塊（大約 line 42 附近顯示 sticky status）。在狀態文字旁加一個 badge。具體位置：任何顯示 `watchStore.status` 的附近。

範例（插入到狀態顯示區塊內）：

```html
<span v-if="!watchStore.sseConnected" class="inline-flex items-center gap-1 text-[10px] text-amber-500 ml-2">
  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
    <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
  </svg>
  連線中斷
</span>
```

（lightning icon 表示即時連線中斷；使用者按 F5 或等 3 秒自動重連即可。）

實作細節：讀 `MonitorView.vue` 找到 `watchStore.status` 的顯示位置，在同一 DOM parent 裡插入上述 span。如果顯示結構已經是某個元件如 `<StatusPill>`，在元件外側插入。

### Step 4: Build 驗證

Run: `cd frontend && npm run build 2>&1 | tail -3`
Expected: 成功。

### Step 5: 手動驗證（可選）

`make dev`，在瀏覽器 devtools：
1. 頁面可見時：`document.hidden === false`，store 定期刷新
2. 切到其他 tab 30 秒回來：`visibilitychange` 觸發 fetchStatus + fetchRecent
3. 停 Flask：SSE onerror 觸發，badge 應該在 3 秒內出現
4. 重啟 Flask：badge 消失

### Step 6: Commit

```bash
git add frontend/src/App.vue frontend/src/stores/watch.js frontend/src/views/MonitorView.vue
git commit -m "feat(frontend): visibility-change refresh + SSE reactive indicator

Two UX fixes for long-running sessions:

1. watchStore.sseConnected is now a ref (was a local let, invisible to
   the UI). MonitorView shows a '連線中斷' badge when the EventSource
   is broken, so the user knows their status display is stale.

2. App.vue listens for document.visibilitychange and refreshes
   watchStore.fetchStatus + fetchRecent whenever the window comes
   back to the foreground. Previously, putting the window in the
   background for an hour (WebKit throttles EventSource) would leave
   queue size and recent items out of date until the user manually
   interacted with the page."
```

---

## Task 4: Minor polish — formatTime tick + dismissUpdate localStorage

**Files:**
- Modify: `frontend/src/views/MonitorView.vue` (加 timeTick)
- Modify: `frontend/src/App.vue` (dismissUpdate / checkForUpdate 讀寫 localStorage)

**動機：** 
1. `MonitorView.formatTime` 回「3 分鐘前」但不會自動重算，使用者盯一小時還是「3 分鐘前」直到下次 fetchRecent。
2. 點「稍後」dismiss update banner，下次啟動 app 又跳出來（使用者可能沒空升級）。記住 dismissed version，同版本不再彈。

### Step 1: MonitorView — timeTick

Read: `grep -n "formatTime\|setInterval\|onMounted\|onUnmounted" frontend/src/views/MonitorView.vue`

在 `<script setup>` 內加（放在現有 imports 後）：

```javascript
import { ref, onMounted, onUnmounted } from 'vue'

// Tick every 30s so formatTime() re-runs on computed timestamps.
const timeTick = ref(0)
let tickTimer = null

onMounted(() => {
  tickTimer = setInterval(() => { timeTick.value++ }, 30_000)
})

onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
})
```

若檔案已經有 `onMounted`/`onUnmounted`，把 setInterval/clearInterval 合進既有 block，不要重複呼叫。

改 `formatTime`：讓它讀 `timeTick.value`（讓 Vue 知道這是 reactive dependency）：

```javascript
function formatTime(isoString) {
  // eslint-disable-next-line no-unused-expressions
  timeTick.value  // reactive dependency
  // ... existing diff calculation ...
}
```

**或者更簡潔**（推薦）：把 `formatTime` 改成 `computed` 返回一個 function，但這會改變 call sites。保守做法：在 formatTime 函式的第一行 read `timeTick.value`（Vue 3 reactivity 會追蹤此 read，ref 改變就重新 evaluate）。

範例（假設現有 formatTime 差值判斷邏輯）：

```javascript
function formatTime(isoString) {
  // Reactive dependency: re-run when 30s tick advances
  timeTick.value
  if (!isoString) return ''
  const then = new Date(isoString)
  const now = new Date()
  const diffSec = (now - then) / 1000
  if (diffSec < 60) return '剛剛'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分鐘前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小時前`
  return then.toLocaleString('zh-TW')
}
```

（如果現有 formatTime 邏輯不同，保留原邏輯，只在函式頂端加 `timeTick.value` 讀取。）

### Step 2: App.vue — dismiss localStorage

Read: `grep -n "dismissUpdate\|checkForUpdate\|localStorage" frontend/src/App.vue`

Change `dismissUpdate`:

```javascript
function dismissUpdate() {
  update.show = false
  stopPolling()
  // Remember which version was dismissed so we don't repeatedly bug the user
  if (update.latestVersion) {
    localStorage.setItem('hv_dismissed_update', update.latestVersion)
  }
}
```

Change `checkForUpdate` (inside the success branch where `data.status === 'available'` is set):

```javascript
async function checkForUpdate() {
  try {
    const res = await fetch('/api/update/check', { method: 'POST' })
    const data = await res.json()
    update.status = data.status
    update.latestVersion = data.latest_version || ''
    update.releaseNotes = data.release_notes || ''

    if (data.status === 'available') {
      // Skip banner if user already dismissed this exact version
      const dismissed = localStorage.getItem('hv_dismissed_update')
      if (dismissed === data.latest_version) {
        return
      }
      update.show = true
    }
  } catch {}
}
```

（具體現有 `checkForUpdate` 結構可能略不同；保留原邏輯、只在 `update.show = true` 前加 dismiss check。若目前把 `update.show = true` 直接寫成 `update.show = data.status === 'available'`，需要改寫成上面的 if block。）

### Step 3: Build 驗證

Run: `cd frontend && npm run build 2>&1 | tail -3`
Expected: 成功。

### Step 4: 手動驗證（可選）

1. 在 dev 模式觸發 update available → 點「稍後」
2. localStorage 應有 `hv_dismissed_update` = latest_version
3. 重新啟動 app：checkForUpdate 回同個 latest_version → banner 不應該出現
4. 模擬 latest_version 升級（手改 localStorage 或等真的新版）→ banner 出現

### Step 5: Commit

```bash
git add frontend/src/views/MonitorView.vue frontend/src/App.vue
git commit -m "feat(frontend): time tick + remember dismissed update version

MonitorView now keeps a 30s ticker so formatTime re-renders relative
strings ('3 分鐘前') as time passes, instead of freezing until the
next fetchRecent.

App.vue remembers the dismissed update version in localStorage; the
banner no longer re-appears for the same version after restart. Any
new release (different version) still surfaces the banner."
```

---

## Task 5: API blueprint 測試 — analysis + export

**Files:**
- Create: `tests/test_analysis_api.py`
- Create: `tests/test_export_api.py`

**動機：** `api/analysis.py` 和 `api/export.py` 零覆蓋。這兩個是使用者路徑最常觸發的 endpoints（分析按鈕 + 匯出按鈕）。`api/settings.py` 已在 Phase 2A Task 1 的 conftest 間接被觸發；`api/results.py` 已在 security sandbox tests 覆蓋；`api/watch.py` 有 `test_watch_api.py`。

### Step 1: 建 `tests/test_analysis_api.py`

```python
"""tests/test_analysis_api.py — /api/analysis/* endpoints"""
from unittest.mock import patch

import pytest

from web_ui import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_start_rejects_missing_folder(client):
    r = client.post("/api/analysis/start", json={})
    assert r.status_code == 400
    assert b"folder" in r.data.lower()


def test_start_rejects_missing_api_key(client, monkeypatch):
    """If Gemini API key not configured, /start returns 400."""
    monkeypatch.setattr("api.analysis.load_config",
                        lambda: {"gemini_api_key": "", "model": "lite"})
    r = client.post("/api/analysis/start", json={"folder": "/tmp"})
    assert r.status_code == 400
    assert b"api key" in r.data.lower() or b"API key" in r.data


def test_start_returns_409_if_already_running(client, monkeypatch):
    """Second /start while first is running returns 409."""
    import api.analysis as api_a

    class FakeThread:
        def is_alive(self): return True

    monkeypatch.setattr(api_a, "_pipeline_thread", FakeThread())
    r = client.post("/api/analysis/start", json={"folder": "/tmp"})
    assert r.status_code == 409


def test_pause_without_running_returns_404(client, monkeypatch):
    import api.analysis as api_a
    monkeypatch.setattr(api_a, "_pipeline_state", None)
    r = client.post("/api/analysis/pause")
    assert r.status_code == 404


def test_resume_without_running_returns_404(client, monkeypatch):
    import api.analysis as api_a
    monkeypatch.setattr(api_a, "_pipeline_state", None)
    r = client.post("/api/analysis/resume")
    assert r.status_code == 404


def test_cancel_without_running_returns_404(client, monkeypatch):
    import api.analysis as api_a
    monkeypatch.setattr(api_a, "_pipeline_state", None)
    r = client.post("/api/analysis/cancel")
    assert r.status_code == 404


def test_pause_calls_state_pause(client, monkeypatch):
    import api.analysis as api_a

    calls = {"pause": 0}

    class FakeState:
        def pause(self): calls["pause"] += 1
        def resume(self): pass
        def cancel(self): pass

    monkeypatch.setattr(api_a, "_pipeline_state", FakeState())
    r = client.post("/api/analysis/pause")
    assert r.status_code == 200
    assert calls["pause"] == 1


def test_sse_stream_returns_event_stream_mimetype(client):
    """SSE endpoint must advertise text/event-stream."""
    # GET with stream=True; we can just check the response immediately
    r = client.get("/api/analysis/stream", buffered=False)
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    r.close()
```

### Step 2: 跑 analysis 測試

Run: `pytest tests/test_analysis_api.py -v`
Expected: 全 PASS（8 個）。

### Step 3: 建 `tests/test_export_api.py`

```python
"""tests/test_export_api.py — /api/export/{csv,json}"""
import pytest

from web_ui import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_export_csv_404_when_empty(client, monkeypatch, tmp_path):
    """CSV export returns 404 if no results exist."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    r = client.get("/api/export/csv")
    assert r.status_code == 404


def test_export_json_404_when_empty(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    r = client.get("/api/export/json")
    assert r.status_code == 404


def test_export_unknown_format_400(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    # Seed one result so we skip the 404 path
    from modules.result_store import ResultStore
    with ResultStore() as store:
        store.save_result("/p.jpg", {"title": "T", "keywords": [],
                                      "description": "", "category": "other",
                                      "scene_type": "indoor", "mood": "neutral",
                                      "people_count": 0})
    r = client.get("/api/export/xml")
    assert r.status_code == 400


def test_export_csv_returns_attachment(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    from modules.result_store import ResultStore
    with ResultStore() as store:
        store.save_result("/p.jpg", {"title": "T", "keywords": ["a"],
                                      "description": "d", "category": "other",
                                      "scene_type": "indoor", "mood": "neutral",
                                      "people_count": 1})
    r = client.get("/api/export/csv")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    assert "happy_vision_report.csv" in r.headers.get("Content-Disposition", "")
    assert b"T" in r.data  # title appears in CSV


def test_export_json_returns_attachment(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    from modules.result_store import ResultStore
    with ResultStore() as store:
        store.save_result("/p.jpg", {"title": "JsonTitle", "keywords": [],
                                      "description": "", "category": "other",
                                      "scene_type": "indoor", "mood": "neutral",
                                      "people_count": 0})
    r = client.get("/api/export/json")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    import json as _json
    data = _json.loads(r.data)
    assert any(item.get("title") == "JsonTitle" for item in data)
```

### Step 4: 跑 export 測試

Run: `pytest tests/test_export_api.py -v`
Expected: 全 PASS（5 個）。

### Step 5: 跑全部 test

Run: `pytest -q`
Expected: 166 passed（153 + 8 analysis + 5 export = 166）。

### Step 6: Commit

```bash
git add tests/test_analysis_api.py tests/test_export_api.py
git commit -m "test(api): cover /api/analysis and /api/export blueprints

Previously both blueprints had zero automated coverage. Adds:
- 8 analysis tests: start rejects missing folder/key, 409 on double-
  start, pause/resume/cancel 404 without running pipeline, pause
  calls state.pause(), SSE stream returns event-stream mimetype.
- 5 export tests: csv/json empty -> 404, unknown format -> 400,
  csv and json happy paths return attachment with correct filename
  and contain the expected title."
```

---

## Task 6: E2E pipeline test

**Files:**
- Create: `tests/test_e2e.py`

**動機：** 沒有一條測試真的走完「掃資料夾 → Gemini(mock) → save DB → write IPTC(real) → 再掃 skip → 匯出 CSV」完整流程。單個 module unit test 都過、但整合可能出問題（例如 schema drift、CSV field mismatch）。

### Design

- 生成 3 張真實 JPG（用 PIL 或硬塞合法 bytes）
- Mock Gemini API 回固定 schema JSON
- 呼叫 `run_pipeline(write_metadata=True)` → 驗證 DB 有 3 筆 completed
- 用 `read_metadata` (真實 exiftool) 驗證 IPTC 確實寫入
- 再跑一次 `run_pipeline(skip_existing=True)` → 0 張被分析
- 呼叫 `generate_csv` → 驗證 3 筆、headers 正確
- `exiftool` 不存在時 skip（pytest.importorskip 相當）

### Step 1: 建 `tests/test_e2e.py`

```python
"""tests/test_e2e.py — End-to-end pipeline: scan → analyze → metadata → CSV"""
import shutil
import pytest


def _exiftool_available() -> bool:
    """Check if exiftool is on PATH (needed for real metadata verification)."""
    return shutil.which("exiftool") is not None


@pytest.mark.skipif(not _exiftool_available(),
                    reason="exiftool not installed; skip real-metadata E2E")
def test_e2e_pipeline_scan_analyze_metadata_csv(tmp_path, monkeypatch):
    """Full path: 3 JPGs -> mock Gemini -> pipeline -> real IPTC -> CSV.

    Also verifies skip_existing behavior on re-run.
    """
    from PIL import Image
    from modules import pipeline as pl
    from modules.metadata_writer import read_metadata
    from modules.report_generator import generate_csv
    from modules.result_store import ResultStore

    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / "hv"))

    # 1) Create 3 real JPGs (100x100 white)
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    for i in range(3):
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        img.save(photos_dir / f"p{i}.jpg", "JPEG")

    # 2) Mock Gemini — return a valid schema result per photo
    analyze_count = {"n": 0}

    def fake_analyze(path, **kw):
        analyze_count["n"] += 1
        return {
            "title": f"Title {analyze_count['n']}",
            "description": "A white square.",
            "keywords": ["test", "white"],
            "category": "other",
            "subcategory": "",
            "scene_type": "studio",
            "mood": "neutral",
            "people_count": 0,
            "identified_people": [],
            "ocr_text": [],
        }

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)

    # 3) Run pipeline with write_metadata=True
    db = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(photos_dir),
        api_key="test-key",
        concurrency=1,
        write_metadata=True,
        db_path=db,
    )

    assert len(results) == 3
    assert analyze_count["n"] == 3

    # 4) Verify DB has 3 completed entries
    with ResultStore(db) as store:
        all_results = store.get_all_results()
        assert len(all_results) == 3
        for r in all_results:
            assert r["file_path"].endswith(".jpg")

    # 5) Verify actual IPTC/XMP written to JPGs (real exiftool)
    for i in range(3):
        meta = read_metadata(str(photos_dir / f"p{i}.jpg"))
        # build_exiftool_args sets XMP-xmp:Instructions to HappyVisionProcessed
        instructions = meta.get("Instructions", "") or meta.get("XMP-xmp:Instructions", "")
        assert "HappyVisionProcessed" in str(instructions), \
            f"Expected HappyVisionProcessed marker in {meta!r}"

    # 6) Re-run with skip_existing=True → no new analyses
    analyze_count["n"] = 0
    pl.run_pipeline(
        folder=str(photos_dir),
        api_key="test-key",
        concurrency=1,
        skip_existing=True,
        write_metadata=True,
        db_path=db,
    )
    assert analyze_count["n"] == 0, "Re-run with skip_existing should analyze zero photos"

    # 7) CSV export
    csv_path = tmp_path / "report.csv"
    with ResultStore(db) as store:
        generate_csv(store.get_all_results(), csv_path)

    csv_text = csv_path.read_text()
    assert "Title 1" in csv_text
    assert "Title 2" in csv_text
    assert "Title 3" in csv_text
    # Header row should mention file_path or similar
    first_line = csv_text.splitlines()[0].lower()
    assert "path" in first_line or "file" in first_line or "title" in first_line
```

### Step 2: 跑 E2E test

Run: `pytest tests/test_e2e.py -v`
Expected: 
- 如果 `exiftool` 有裝: PASS
- 沒裝: SKIPPED with reason

`which exiftool` 確認本機有裝；Bobo 的 dev 機器預期是有（Makefile 的 `setup.sh` 提示 `brew install exiftool`）。

### Step 3: 全部 test

Run: `pytest -q`
Expected: 167 passed（166 + 1 E2E）；如果 skipped 則 166 passed + 1 skipped。

### Step 4: Commit

```bash
git add tests/test_e2e.py
git commit -m "test: add end-to-end pipeline test with real IPTC verification

Generates 3 real JPGs with PIL, mocks Gemini, runs run_pipeline with
write_metadata=True, then verifies: (1) DB has 3 completed entries,
(2) real exiftool reads the HappyVisionProcessed marker from each
JPG, (3) re-running with skip_existing=True analyzes zero photos,
(4) generate_csv produces expected titles.

Skipped if exiftool is not on PATH."
```

---

## Final Verification

- [ ] **Step 1: Full test suite**

Run: `make verify`
Expected: 166 or 167 passed (depending on exiftool availability), lint 綠。

- [ ] **Step 2: 煙霧測試 — fetch timeout**

Run:
```bash
make dev &
sleep 3
# In devtools console: fetch('/api/watch/status').then(r => r.json()).then(console.log)
# Should respond in <100ms
# Stop Flask: pkill -f web_ui.py
# In devtools console: fetch('/api/watch/status').catch(e => console.log(e.name))
# Should throw AbortError after 30s
```

- [ ] **Step 3: 煙霧測試 — visibilitychange**

Run:
```bash
make dev &
sleep 3
# Open pywebview or browser to http://127.0.0.1:8081
# Switch to another app/tab for 30s
# Switch back → network tab should show /api/watch/status + /api/watch/recent fire
```

- [ ] **Step 4: 煙霧測試 — SSE 斷線 badge**

Run:
```bash
make dev &
sleep 5
# Open app, note badge is NOT visible
# Stop Flask: pkill -f web_ui.py
# Within 3-5 seconds, badge should appear in MonitorView
# Restart make dev
# Badge should disappear after reconnect
```

- [ ] **Step 5: 煙霧測試 — dismiss update memory**

Run (with hand-crafted fake update state)：
```bash
# In dev mode, manually set update state in devtools or similar
# Dismiss → check localStorage: localStorage.getItem('hv_dismissed_update')
# Restart → banner should NOT re-appear for same version
```

- [ ] **Step 6: bump VERSION**

編輯 `VERSION`：`0.3.1` → `0.3.2`。

- [ ] **Step 7: Final commit**

```bash
git add VERSION
git commit -m "chore: bump version to 0.3.2

Phase 2C UX polish + test coverage:
- folder_watcher no longer re-enqueues failed photos (also fixes a
  25% flaky test from Phase 2B)
- Global fetch timeout (30s) on the frontend wrapper
- visibilitychange refresh keeps MonitorView current when window
  returns from background
- SSE reactive sseConnected + disconnect badge in MonitorView
- MonitorView time tick so '3 分鐘前' updates live
- dismissUpdate persists to localStorage — same version won't re-bug
- Full API test coverage for /api/analysis and /api/export (13 tests)
- E2E pipeline test with real IPTC verification (skipped without
  exiftool installed)"
```

---

## Completion

All Phase 2A + 2B + 2C done. Remaining future work captured in the Phase 3 section of each plan:
- Apple Developer codesign + notarization
- Pipeline fully unified into watcher
- Watchdog (FSEvents) instead of polling
- Dynamic rate_limiter configuration in Settings UI

---

## Self-Review 已完成

- ✅ **Spec coverage：** UX audit 的 High/Medium 都有對應 task（fetch timeout = Task 2；visibilitychange = Task 3；SSE badge = Task 3；formatTime tick + dismiss memory = Task 4）；測試覆蓋對照（analysis/export 補齊 = Task 5；E2E = Task 6）；flaky test 修好 = Task 1
- ✅ **無 placeholder：** 每 step 都有具體 code / command / expected
- ✅ **型別/命名一致：** `sseConnected`（ref）、`timeTick`（ref）、`handleVisibilityChange`、`hv_dismissed_update` (localStorage key)、`DEFAULT_FETCH_TIMEOUT_MS` 等在多處使用保持一致
- ✅ **TDD：** backend tasks 先寫測試；frontend task 因無 unit test 框架採用 build + 手動煙霧驗證並說明原因
- ✅ **小 commit：** 6 個功能 task + 1 收尾，每個獨立可 revert
- ✅ **Scope：** UX polish + test coverage；不含 architecture 重構或 codesign（留 Phase 3）
