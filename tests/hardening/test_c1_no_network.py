"""tests/hardening/test_c1_no_network.py

Hardening C1: 無網路 / DNS 失敗 → retry 後放棄該張，不 crash，已完成
結果保留 可 resume。

真實情境：
- 同事用 MacBook 到會場，wifi 剛連一下就斷 → socket error
- 公司 firewall 擋 googleapis.com → DNS 解析失敗
- VPN 跳掉 → 中間 route 壞掉

錯誤字串通常長這樣（依 SDK 版本不同）：
  "getaddrinfo failed"
  "Name or service not known"
  "Connection refused"
  "Max retries exceeded with url: ..."
  "Temporary failure in name resolution"

這些不應該被分類為 auth fatal（否則一斷網 whole batch halt）。理想情況是
retry，但 retry 3 次還不行就放棄該張、標 failed、batch 繼續；等同事重連
網路後 resume 就能續跑。
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from modules import gemini_vision
from modules import pipeline as pl
from modules.gemini_vision import analyze_photo


_MOCK_USAGE_META = type("UM", (), {
    "prompt_token_count": 10,
    "candidates_token_count": 5,
    "total_token_count": 15,
})()


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def _fake_response(text: str):
    class _R:
        pass
    r = _R()
    r.text = text
    r.usage_metadata = _MOCK_USAGE_META
    return r


_GOOD_JSON = (
    '{"title": "ok", "description": "d", "keywords": [], '
    '"category": "other", "scene_type": "indoor", '
    '"mood": "neutral", "people_count": 0}'
)


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


# ---- Network-error variants ----

_DNS_ERROR_STRINGS = [
    "getaddrinfo failed",
    "Name or service not known",
    "Temporary failure in name resolution",
    "Could not resolve host: generativelanguage.googleapis.com",
]

_CONNECT_ERROR_STRINGS = [
    "Connection refused",
    "Max retries exceeded with url: /v1/models/gemini-2.5-flash-lite",
    "Connection reset by peer",
    "Read timed out",
    "Network is unreachable",
]


def _make_failing_client(error_strings, succeed_on_attempt: int | None = None):
    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if succeed_on_attempt is not None and attempt["n"] >= succeed_on_attempt:
                return _fake_response(_GOOD_JSON)
            # Cycle through the error strings to simulate varied network failures.
            msg = error_strings[(attempt["n"] - 1) % len(error_strings)]
            raise ConnectionError(msg)

    class _Client:
        models = _Models()

    return _Client, attempt


def test_dns_failure_does_not_halt_batch(tmp_path, monkeypatch):
    """One photo's worth of DNS failures must not auth-halt the batch.
    Expected: return (None, None) after retries, pipeline marks failed,
    next photo proceeds."""
    for i in range(2):
        _write_jpg(tmp_path / f"p{i}.jpg")

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    call_log: list[str] = []

    class _Models:
        def generate_content(self, **_kw):
            call_log.append("x")
            # Photos 1–3 of 6 total attempts see DNS errors; the 4th call
            # (photo 2's first try) succeeds.
            if len(call_log) <= 3:
                raise ConnectionError("getaddrinfo failed")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # Photo 2 succeeded.
    assert len(results) == 1
    # Pipeline was NOT halted — we called at least 4 times.
    assert len(call_log) == 4


def test_connection_refused_is_not_classified_auth_fatal(tmp_path, monkeypatch):
    """Regression guard: none of the network error strings must match
    _AUTH_FATAL_MARKERS (API_KEY_INVALID / UNAUTHENTICATED /
    PERMISSION_DENIED / API key not valid). If they did, a single
    offline batch would halt as 'bad API key'."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    for err_str in _DNS_ERROR_STRINGS + _CONNECT_ERROR_STRINGS:
        class _Models:
            def generate_content(self, _err=err_str, **_kw):
                raise ConnectionError(_err)

        class _Client:
            models = _Models()

        monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

        # Call and confirm we get (None, None) rather than
        # InvalidAPIKeyError. The latter would indicate a misclassification.
        result, usage = analyze_photo(
            str(photo), api_key="k", model="lite", max_retries=1,
        )
        assert result is None and usage is None, (
            f"network error {err_str!r} produced result unexpectedly"
        )


def test_network_recovers_midway_batch_completes_remaining(
    tmp_path, monkeypatch,
):
    """Photo 1: DNS fail every attempt (becomes failed).
    Photo 2: network is back, first try succeeds.
    Photo 3: same, succeeds.
    Pipeline does NOT halt despite photo 1 exhausting retries with
    network errors."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i}.jpg")

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    counter = {"n": 0}
    lock = threading.Lock()

    class _Models:
        def generate_content(self, **_kw):
            with lock:
                counter["n"] += 1
                n = counter["n"]
            # First 3 attempts (photo 1 retries) fail with DNS error.
            if n <= 3:
                raise ConnectionError("getaddrinfo failed")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # Photos 2 and 3 succeeded; photo 1 was marked failed.
    assert len(results) == 2
    # Total: 3 (photo 1 retries) + 1 (photo 2) + 1 (photo 3) = 5
    assert counter["n"] == 5


def test_socket_timeout_treated_similarly(tmp_path, monkeypatch):
    """socket.timeout / TimeoutError should behave the same as other
    connect errors — retry, then fail this photo without halting batch."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    class _Models:
        def generate_content(self, **_kw):
            raise TimeoutError("Read timed out. (read timeout=60)")

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, usage = analyze_photo(
        str(photo), api_key="k", model="lite", max_retries=1,
    )
    assert result is None and usage is None


def test_offline_batch_is_fully_resumable(tmp_path, monkeypatch):
    """End-to-end: run batch fully offline → all photos fail. Then
    'reconnect' and resume → all succeed. Pinning this because a broken
    resume path here would be the worst possible dogfood outcome."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i}.jpg")

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    offline = {"state": True}

    class _Models:
        def generate_content(self, **_kw):
            if offline["state"]:
                raise ConnectionError("getaddrinfo failed")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"

    # Round 1: offline — all photos fail.
    r1 = pl.run_pipeline(
        folder=str(tmp_path), api_key="test", concurrency=1,
        write_metadata=False, db_path=db_path,
    )
    assert r1 == []

    # Reconnect.
    offline["state"] = False

    # Round 2: resume. failed rows get retried, all succeed.
    r2 = pl.run_pipeline(
        folder=str(tmp_path), api_key="test", concurrency=1,
        write_metadata=False, db_path=db_path, skip_existing=True,
    )
    assert len(r2) == 3
