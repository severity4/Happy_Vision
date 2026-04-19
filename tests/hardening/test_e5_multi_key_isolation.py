"""tests/hardening/test_e5_multi_key_isolation.py

Hardening E5: 多個 API key 切換（例如免費 / 付費帳號）正確隔離。

真實情境：
- 映奧有個人 free-tier key 跑小批次 QA，也有公司 paid-tier key 跑正式批次
- 切 key 後，下一次 analyze_photo 必須用新 key 的 credential，舊 key 的
  cached client 不可被誤用（否則付費 key 的 request 會被 rate-limit 到
  free-tier）

E4 已覆蓋 set → get 的即時性。E5 再往深測：
- `_get_client` cache 同時持有多把 key 的 client，每把都獨立
- 切 key 不會跨污染（cache 不誤 match）
- 只要兩次呼叫用不同 key，兩個 Client 實例獨立

Happy Vision 目前只在 Keychain / secret_store 裡存「當前使用的」那一把
key，並不支援同時常駐多把。使用者切 key 的流程是：Settings 改掉舊的，
secret_store 覆蓋，next load_config 就看到新的。這題 lock 的是
`_get_client` 的多 key cache 行為，保證切換乾淨。
"""

from __future__ import annotations

import threading

from modules import gemini_vision


def _reset_client_cache():
    with gemini_vision._client_cache_lock:
        gemini_vision._client_cache.clear()


def test_different_keys_yield_different_clients(monkeypatch):
    """Two keys → two distinct Client instances. cache hit on same key
    returns the same instance."""
    _reset_client_cache()

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(gemini_vision.genai, "Client", _FakeClient)

    free = gemini_vision._get_client("free-tier-key")
    paid = gemini_vision._get_client("paid-tier-key")
    free_again = gemini_vision._get_client("free-tier-key")

    assert free is not paid
    assert free is free_again
    assert free.api_key == "free-tier-key"
    assert paid.api_key == "paid-tier-key"


def test_key_cache_survives_concurrent_access(monkeypatch):
    """If multiple worker threads first-time the same key, cache must
    only construct ONE Client (not N). Regression guard for the lock."""
    _reset_client_cache()

    constructions = []

    class _FakeClient:
        def __init__(self, api_key):
            constructions.append(api_key)
            self.api_key = api_key

    monkeypatch.setattr(gemini_vision.genai, "Client", _FakeClient)

    clients: list = []
    lock = threading.Lock()

    def worker():
        c = gemini_vision._get_client("shared-key")
        with lock:
            clients.append(c)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 8 got the same instance
    assert len(clients) == 8
    assert all(c is clients[0] for c in clients)
    # Only ONE Client was constructed despite 8 parallel _get_client calls
    assert constructions.count("shared-key") == 1


def test_switching_keys_does_not_pollute_cache(monkeypatch):
    """Simulate the user swap flow: free key's client, then paid key's
    client. Subsequent lookups of either key must return the ORIGINAL
    client for that key — not the most-recently-constructed one."""
    _reset_client_cache()

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(gemini_vision.genai, "Client", _FakeClient)

    c_free_1 = gemini_vision._get_client("free")
    c_paid = gemini_vision._get_client("paid")
    c_free_2 = gemini_vision._get_client("free")

    assert c_free_1 is c_free_2, (
        "free-tier client got evicted when paid-tier key was requested — "
        "cache isn't keyed on api_key correctly"
    )
    # Paid client unaffected
    assert c_paid.api_key == "paid"


def test_empty_string_key_and_real_key_are_isolated(monkeypatch):
    """Before user sets their key (empty string flows through),
    analyze_photo constructs an empty-keyed client and caches it. Once
    user sets a real key, the real-keyed client must NOT be the empty one."""
    _reset_client_cache()

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(gemini_vision.genai, "Client", _FakeClient)

    empty = gemini_vision._get_client("")
    real = gemini_vision._get_client("AIza-real-key")

    assert empty.api_key == ""
    assert real.api_key == "AIza-real-key"
    assert empty is not real


def test_cache_handles_many_key_rotations(monkeypatch):
    """Belt-and-braces: rotating through 20 distinct keys produces 20
    distinct cached clients — no silent eviction surprises."""
    _reset_client_cache()

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(gemini_vision.genai, "Client", _FakeClient)

    seen = {}
    for i in range(20):
        key = f"key-{i:02d}"
        c = gemini_vision._get_client(key)
        seen[key] = c

    # Fetch each again: still the same instance
    for key, original in seen.items():
        assert gemini_vision._get_client(key) is original, (
            f"cache evicted {key!r} — client identity lost across rotation"
        )
