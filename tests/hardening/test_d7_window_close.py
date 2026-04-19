"""tests/hardening/test_d7_window_close.py

Hardening D7: 執行中關閉 pywebview 視窗 → 背景任務能安全中止或完成。

真實情境：使用者跑 500 張批次到一半，意外把 pywebview 視窗的紅 X
按下去。流程應該是：
1. pywebview.start() 返回
2. Python main 退出，觸發 `atexit` callbacks
3. Daemon threads（Flask、folder_watcher poll、batch_monitor 輪詢）隨
   process 死亡
4. ExiftoolBatch 的 `exiftool -stay_open` 子 process 被 OS 回收

測試重點：
- `atexit.register` 確實綁了 `stop_background_monitor`（v0.11.0 SRE
  audit 加的，防 daemon thread 被 SIGKILL 前還在打 Gemini batches API）
- `stop_background_monitor` 在未啟動時呼叫是 no-op
- `stop_background_monitor` 連續呼叫兩次不 crash（idempotent）
- `PipelineState.cancel` 是 thread-safe（從 main thread 跨 worker 的
  傳遞靠 atomic bool + Event）
"""

from __future__ import annotations

import atexit
import threading
import time

import pytest

from modules import batch_monitor
from modules.pipeline import PipelineState


# ---------- stop_background_monitor behavior ----------

def test_stop_background_monitor_noop_when_not_started(monkeypatch):
    """Calling stop before start: must not raise, must not spin up a
    daemon thread of its own."""
    monkeypatch.setattr(batch_monitor, "_monitor_instance", None)
    # Should return cleanly.
    batch_monitor.stop_background_monitor()
    assert batch_monitor._monitor_instance is None


def test_stop_background_monitor_is_idempotent(monkeypatch):
    """Real call path: atexit fires, then Python shutdown tries again.
    Must not double-stop the already-stopped monitor."""
    stop_calls = {"n": 0}

    class _FakeMonitor:
        def stop(self): stop_calls["n"] += 1

    monkeypatch.setattr(batch_monitor, "_monitor_instance", _FakeMonitor())

    batch_monitor.stop_background_monitor()
    batch_monitor.stop_background_monitor()  # second call

    # Only ONE stop() on the monitor (second call finds None and returns)
    assert stop_calls["n"] == 1
    assert batch_monitor._monitor_instance is None


def test_atexit_registered_for_monitor_shutdown(monkeypatch):
    """web_ui._post_start_init registers atexit handlers. Simulate the
    init path and verify stop_background_monitor is in the atexit registry."""
    registered = []

    def _tracking_register(fn, *args, **kwargs):
        registered.append(fn)
        return fn

    monkeypatch.setattr(atexit, "register", _tracking_register)

    # Minimal fake monitor start that doesn't actually thread up
    def _fake_start_bg(event_sink=None):
        class _M:
            def start(self): pass
            def stop(self): pass
        return _M()

    monkeypatch.setattr(batch_monitor, "start_background_monitor", _fake_start_bg)

    # Call the init path — this is what web_ui.py does on startup
    from web_ui import _post_start_init
    _post_start_init()

    # The atexit registrations must include stop_background_monitor
    assert batch_monitor.stop_background_monitor in registered, (
        "stop_background_monitor not registered via atexit — when user "
        "closes window the monitor thread gets SIGKILL'd mid-Gemini-request"
    )


# ---------- PipelineState.cancel thread-safety ----------

def test_pipeline_state_cancel_visible_across_threads():
    """Worker threads must see `state.cancelled = True` set from main
    thread. This is what lets `_check_auth`-style race conditions not
    matter: the cancel is a simple bool + Event, atomic by Python's GIL."""
    state = PipelineState()
    seen = []

    def worker():
        # Busy-wait up to 2s for cancel to flip
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if state.cancelled:
                seen.append(True)
                return
            time.sleep(0.01)
        seen.append(False)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()

    time.sleep(0.1)
    state.cancel()

    for t in threads:
        t.join(timeout=3)

    assert all(seen), (
        "some worker thread never observed the cancel — pipeline would "
        "keep calling Gemini after user closed the window"
    )


def test_pipeline_state_cancel_is_idempotent():
    """Cancel is called from multiple paths (user click cancel, window
    close handler, auth halt). Must be safe to re-call."""
    state = PipelineState()
    state.cancel()
    state.cancel()  # second call
    state.cancel()
    assert state.cancelled is True


def test_pipeline_state_pause_resume_before_cancel():
    """Window close during pause: cancel must wake the pause event so
    worker threads waiting on `wait_if_paused` don't hang forever."""
    state = PipelineState()
    state.pause()  # paused flag set

    # spawn a worker that would block in wait_if_paused
    woke = threading.Event()

    def worker():
        state.wait_if_paused()
        woke.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    # Worker should NOT finish while paused
    assert not woke.wait(0.2)

    # Cancel: per PipelineState.cancel docstring, this also unblocks paused
    state.cancel()
    assert woke.wait(2.0), (
        "cancel did not unblock paused worker — window close would leave "
        "worker threads stuck on the pause event forever"
    )
    t.join(timeout=2)


# ---------- ExiftoolBatch cleanup after explicit close ----------

def test_exiftool_batch_close_is_idempotent(tmp_path):
    """Double-close during shutdown (explicit close + __exit__ in context
    manager) must not raise or hang."""
    import shutil
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed")

    from modules.metadata_writer import ExiftoolBatch
    batch = ExiftoolBatch()
    batch.close()
    batch.close()  # must not raise
    # After close, further writes should also not crash (no-op or False)
    # but we don't require a specific behavior — just no exception.
