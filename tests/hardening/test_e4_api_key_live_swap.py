"""tests/hardening/test_e4_api_key_live_swap.py

Hardening E4: API key 設定後立即可用，不需重啟 app。

真實情境：
- 同事第一次開 Happy Vision，看到 Settings 頁提示「尚未設定 API key」
- 到 Google AI Studio 生一把 key，貼回 Settings 存檔
- **期望**：下一次分析照片立即使用新 key，不需要重開 app
- **恐怖版本**：舊版本可能有 cache 沒失效、或 folder_watcher 已經用 ""
  初始化過，需要 restart 才生效 — 這在 dogfood 現場會被當成 bug 被吵

合約：
1. `secret_store.set_key(new_key)` 立刻更新 in-process cache
2. `load_config()` 之後馬上回 new_key（不經 Keychain round-trip）
3. folder_watcher 每張照片都 re-read config → 不 cache 舊 key
4. `gemini_vision._get_client` cache 能同時持有舊 / 新 key 的 client；
   切 key 時新 client 用新 key 的 credential（避免 401 假陽性）
5. UI 透過 PUT /api/settings 送新 key 後，GET 立刻看到 `gemini_api_key_set=True`
"""

from __future__ import annotations

from modules import config as cfg
from modules import gemini_vision
from modules import secret_store
from web_ui import app as _app


# ---------- secret_store: set → get 無 restart ----------

def test_set_key_reflected_in_get_immediately():
    """Core contract: set then get returns the new value without any
    explicit cache invalidation."""
    secret_store.set_key("abc-first")
    assert secret_store.get_key() == "abc-first"

    secret_store.set_key("xyz-second")
    assert secret_store.get_key() == "xyz-second", (
        "set_key must update cache atomically — old value visible after set "
        "means a restart would be required to pick up the new key"
    )


def test_load_config_sees_updated_key_after_set():
    """End-to-end: user hits PUT /api/settings → save_config → set_key.
    A subsequent load_config from the SAME process (e.g., folder_watcher's
    per-photo config read) must return the new key."""
    secret_store.set_key("k-v1")
    assert cfg.load_config().get("gemini_api_key") == "k-v1"

    secret_store.set_key("k-v2")
    cfg2 = cfg.load_config()
    assert cfg2.get("gemini_api_key") == "k-v2", (
        "load_config still sees old key — folder_watcher would keep "
        "calling Gemini with the stale credential"
    )


def test_clear_key_reflected_immediately():
    """User deletes key from Settings (unlikely, but should work)."""
    secret_store.set_key("to-be-cleared")
    assert secret_store.get_key() == "to-be-cleared"

    secret_store.clear_key()
    assert secret_store.get_key() == ""
    # load_config should also reflect empty key
    assert cfg.load_config().get("gemini_api_key", "") == ""


# ---------- gemini_vision client cache: per-key isolation ----------

def test_get_client_returns_distinct_clients_per_key(monkeypatch):
    """Regression guard: if `_get_client` wrongly cached across keys, a
    request with the new key would reuse the OLD key's client — and every
    call would fail 401 even after user fixed their key."""
    # Clear client cache so this test is deterministic.
    with gemini_vision._client_cache_lock:
        gemini_vision._client_cache.clear()

    observed_keys = []

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            observed_keys.append(api_key)

    monkeypatch.setattr(gemini_vision.genai, "Client", _FakeClient)

    c1 = gemini_vision._get_client("key-alpha")
    c2 = gemini_vision._get_client("key-beta")

    assert c1 is not c2, "new key must produce a new client instance"
    assert c1.api_key == "key-alpha"
    assert c2.api_key == "key-beta"

    # Second call with the same key hits the cache (no extra Client construct).
    c1_again = gemini_vision._get_client("key-alpha")
    assert c1_again is c1
    assert observed_keys.count("key-alpha") == 1


def test_get_client_empty_key_isolated_from_real_key(monkeypatch):
    """Before user sets their key, analyze_photo is called with "". That
    empty-key client MUST NOT be served when the user later provides a
    real key — else all subsequent analyses would 401 with the old empty
    credential."""
    with gemini_vision._client_cache_lock:
        gemini_vision._client_cache.clear()

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(gemini_vision.genai, "Client", _FakeClient)

    empty_c = gemini_vision._get_client("")
    real_c = gemini_vision._get_client("user-real-key")

    assert empty_c is not real_c
    assert empty_c.api_key == ""
    assert real_c.api_key == "user-real-key"


# ---------- API: PUT /api/settings reflects new key immediately ----------

def test_put_settings_new_key_visible_in_next_get():
    """Simulates the exact UI flow: user types key into Settings page, the
    frontend PUTs it, then re-GETs the settings to redraw. The GET must
    show gemini_api_key_set=True without the user hitting refresh."""
    _app.config["TESTING"] = True
    client = _app.test_client()

    # Initially no key.
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.get_json().get("gemini_api_key_set") is False

    # User saves a fresh key.
    resp = client.put("/api/settings", json={"gemini_api_key": "fresh-new-key"})
    assert resp.status_code == 200

    # Immediate re-GET: must reflect set=True, no app restart needed.
    resp = client.get("/api/settings")
    data = resp.get_json()
    assert data.get("gemini_api_key_set") is True, (
        "UI would show 'key not set' banner even though user just saved — "
        "E4 contract broken"
    )
    # Key value itself MUST NOT be echoed (security — see api/settings.py).
    assert data.get("gemini_api_key") == ""


def test_put_settings_masked_placeholder_does_not_clobber_key():
    """Regression guard (from api/settings.py comments): frontend sometimes
    sends the settings object it got from GET — which masks the key as
    "" or a "..." placeholder. That must NOT clear the stored real key."""
    _app.config["TESTING"] = True
    client = _app.test_client()

    # User first sets a real key.
    client.put("/api/settings", json={"gemini_api_key": "real-user-key"})
    assert secret_store.get_key() == "real-user-key"

    # Frontend round-trips: re-PUT with masked / empty key (e.g., user
    # edited an unrelated field and the form re-sent all values).
    client.put("/api/settings", json={"gemini_api_key": "..."})
    assert secret_store.get_key() == "real-user-key", (
        "masked placeholder clobbered the real key — user loses their key "
        "just by saving some other setting"
    )

    client.put("/api/settings", json={"gemini_api_key": ""})
    assert secret_store.get_key() == "real-user-key", (
        "empty-string PUT wiped the real key"
    )


# ---------- folder_watcher-style re-read: no stale key after swap ----------

def test_folder_watcher_reread_sees_new_key():
    """folder_watcher reads config at the start of every `_process_photo`.
    Simulate: watcher starts with key-A cached, user swaps to key-B,
    next per-photo config read sees key-B."""
    secret_store.set_key("key-A")
    # first config read (like watcher did on startup)
    assert cfg.load_config()["gemini_api_key"] == "key-A"

    # User saves new key via UI flow
    secret_store.set_key("key-B")

    # Watcher's next per-photo read
    assert cfg.load_config()["gemini_api_key"] == "key-B", (
        "folder_watcher would keep calling Gemini with key-A — that's a "
        "real dogfood bug: user fixes key, watcher keeps 401-ing silently"
    )
