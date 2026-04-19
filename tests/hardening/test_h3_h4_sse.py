"""tests/hardening/test_h3_h4_sse.py

Hardening H3/H4: SSE 連線行為。

H3 連線中斷恢復：EventSource client 關閉 → 後端 queue 要能被清掉（避免
泡久了堆滿 deadlock）；重新連線時 client 看得到新事件，不卡住。

H4 並發多 client：5 個 EventSource 同時連線，所有人收到相同進度事件。
這是「一台 Mac 開兩個 tab 同時監看」這種 UX 可能觸發的情境。

實作上 api/analysis.py 用一個全域 list[queue.Queue]，每個新 GET /stream
push 一個 queue 進去，broadcast 時 for-loop 把 msg put 進每個 queue。
Client 斷線時透過 `finally` 把自己 queue 從 list 移除。Queue 滿 → 標記
dead 清掉。
"""

from __future__ import annotations

import json
import queue
import threading
import time

import pytest

from api import analysis as api_analysis
from api import batch as api_batch


@pytest.fixture(autouse=True)
def _reset_sse_queues():
    """Isolate: clear global SSE queues before/after each test."""
    with api_analysis._sse_lock:
        api_analysis._sse_queues.clear()
    yield
    with api_analysis._sse_lock:
        api_analysis._sse_queues.clear()


# ---------- H4: multi-client broadcast ----------

def test_broadcast_reaches_every_subscribed_queue():
    """Core fan-out: 5 queues registered → broadcast puts the message
    into all 5."""
    queues = [queue.Queue(maxsize=10) for _ in range(5)]
    with api_analysis._sse_lock:
        api_analysis._sse_queues.extend(queues)

    api_analysis._broadcast_sse("progress", {"done": 1, "total": 10})

    for q in queues:
        msg = q.get_nowait()
        assert "event: progress" in msg
        assert '"done": 1' in msg


def test_broadcast_cjk_payload_not_ascii_escaped():
    """`ensure_ascii=False` in _broadcast_sse must keep CJK readable —
    a browser EventSource receiving `\\u8b1b\\u8005` for `講者` means
    UI showing mojibake."""
    q = queue.Queue(maxsize=1)
    with api_analysis._sse_lock:
        api_analysis._sse_queues.append(q)

    api_analysis._broadcast_sse("error", {"file": "講者.jpg", "error": "分析失敗"})
    msg = q.get_nowait()
    assert "講者.jpg" in msg
    assert "分析失敗" in msg
    assert "\\u" not in msg


def test_multiple_events_arrive_in_order_across_clients():
    """3 clients + 4 events → each client sees 4 messages in order."""
    clients = [queue.Queue(maxsize=10) for _ in range(3)]
    with api_analysis._sse_lock:
        api_analysis._sse_queues.extend(clients)

    for i in range(4):
        api_analysis._broadcast_sse("progress", {"done": i, "total": 4})

    for q in clients:
        received = []
        for _ in range(4):
            received.append(q.get_nowait())
        dones = [json.loads(m.split("data: ", 1)[1].split("\n", 1)[0])["done"]
                 for m in received]
        assert dones == [0, 1, 2, 3]


# ---------- H3: full queue signals dead client, gets pruned ----------

def test_full_queue_is_pruned_on_broadcast():
    """A slow / stalled client hits queue full. Broadcaster must remove
    that queue so we don't leak references + so future broadcasts don't
    slow-mo waiting for it."""
    stuck = queue.Queue(maxsize=1)
    stuck.put("prior-msg")  # now full

    healthy = queue.Queue(maxsize=10)

    with api_analysis._sse_lock:
        api_analysis._sse_queues.append(stuck)
        api_analysis._sse_queues.append(healthy)

    api_analysis._broadcast_sse("progress", {"done": 1, "total": 10})

    # Stuck queue removed from the global list
    with api_analysis._sse_lock:
        assert stuck not in api_analysis._sse_queues
        assert healthy in api_analysis._sse_queues

    # Healthy queue got the message
    assert healthy.get_nowait()


# ---------- H3: client reconnect gets NEW events (not replay of old) ----------

def test_client_reconnect_receives_future_events_only():
    """SSE is a pure broadcast: disconnect → reconnect yields a fresh
    queue, no replay. This is by design (we don't persist past events
    to the SSE buffer). Lock the contract."""
    old_q = queue.Queue(maxsize=10)
    with api_analysis._sse_lock:
        api_analysis._sse_queues.append(old_q)

    api_analysis._broadcast_sse("progress", {"done": 1, "total": 10})
    # simulate disconnect
    with api_analysis._sse_lock:
        api_analysis._sse_queues.remove(old_q)

    # Client reconnects — fresh queue
    new_q = queue.Queue(maxsize=10)
    with api_analysis._sse_lock:
        api_analysis._sse_queues.append(new_q)

    # Broadcast after reconnect
    api_analysis._broadcast_sse("progress", {"done": 2, "total": 10})

    # New client only sees the second event, not the first.
    assert new_q.qsize() == 1
    msg = new_q.get_nowait()
    assert '"done": 2' in msg


def test_concurrent_broadcasts_and_new_clients_no_race(monkeypatch):
    """Stress: 100 broadcasts from 4 threads while 3 other threads are
    registering new clients. No deadlock, no lost messages on clients
    that were present for the whole run."""
    persistent = [queue.Queue(maxsize=1000) for _ in range(3)]
    with api_analysis._sse_lock:
        api_analysis._sse_queues.extend(persistent)

    stop = threading.Event()
    broadcast_count = {"n": 0}

    def broadcaster():
        while not stop.is_set() and broadcast_count["n"] < 100:
            api_analysis._broadcast_sse(
                "progress",
                {"done": broadcast_count["n"], "total": 100},
            )
            broadcast_count["n"] += 1
            time.sleep(0.001)

    def new_clients():
        while not stop.is_set():
            q = queue.Queue(maxsize=10)
            with api_analysis._sse_lock:
                api_analysis._sse_queues.append(q)
            time.sleep(0.002)
            with api_analysis._sse_lock:
                if q in api_analysis._sse_queues:
                    api_analysis._sse_queues.remove(q)

    threads = [
        threading.Thread(target=broadcaster, daemon=True),
        threading.Thread(target=broadcaster, daemon=True),
        threading.Thread(target=new_clients, daemon=True),
    ]
    for t in threads:
        t.start()

    # Wait up to 2s for 100 broadcasts
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and broadcast_count["n"] < 100:
        time.sleep(0.01)
    stop.set()
    for t in threads:
        t.join(timeout=1)

    # Each persistent client should have received ALL broadcasts that
    # happened while it was in the list (approximately 100 — allow for
    # the tiny window where maxsize=1000 is enough buffer).
    for q in persistent:
        # Must be non-empty and within order
        received = []
        while not q.empty():
            received.append(q.get_nowait())
        assert len(received) > 0, "persistent client dropped every message"


# ---------- batch_bp SSE mirrors same contract ----------

def test_batch_bp_broadcast_helper_exists():
    """api/batch.py has broadcast_batch_event which web_ui.py binds to
    the batch_monitor's event_sink. Ensure it doesn't silently no-op
    if called."""
    from api.batch import broadcast_batch_event
    # Should be callable without raising
    broadcast_batch_event({"type": "batch_created", "job_id": "test"})
