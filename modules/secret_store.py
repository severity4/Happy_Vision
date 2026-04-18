"""modules/secret_store.py — macOS Keychain wrapper for API keys.

Stores the Gemini API key in the user's Keychain via the `keyring` package.
On macOS this uses the login keychain with process-level access control,
protecting the key from backup exfiltration (Time Machine, iCloud Desktop)
and file-system readers with Full Disk Access.

Performance note (v0.7.0): every Keychain call on a fresh binary can block
for 2s waiting for the macOS permission prompt. Settings save paths used
to hit Keychain 2-4 times per PUT (load_config.get_key + save_config.get_key
+ set_key), adding 4-8s of needless latency per save. We now cache the key
in process memory after the first successful load and only hit Keychain
when (a) the cache is cold, or (b) set_key is explicitly called with a new
value. Cache is invalidated on set_key / clear_key.
"""

import keyring
import logging
import threading

log = logging.getLogger(__name__)

_keyring = keyring
_SERVICE = "happy-vision"
_USERNAME = "gemini_api_key"

# Hard cap on each Keychain call. macOS will pop a "allow access" prompt for a
# new binary signature; if the user isn't around (or we're pre-UI) this blocks
# Security.framework indefinitely. A short timeout lets startup continue — the
# user can re-enter the key from Settings, and subsequent calls (now with the
# window visible) will succeed and cache the ACL.
_TIMEOUT_SECONDS = 2.0

# Process-memory cache to avoid re-hitting Keychain on every config read.
# (key_value, is_loaded) — is_loaded=False means we have never successfully
# resolved Keychain yet (either cold start or all attempts timed out).
_cache_lock = threading.Lock()
_cache_value: str = ""
_cache_loaded: bool = False


def _call_with_timeout(fn, default=None):
    result = [default]
    err = [None]

    def _run():
        try:
            result[0] = fn()
        except BaseException as e:  # keychain errors + anything the backend raises
            err[0] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=_TIMEOUT_SECONDS)
    if t.is_alive():
        log.warning("Keychain call timed out after %.1fs", _TIMEOUT_SECONDS)
        return default
    if err[0] is not None:
        raise err[0]
    return result[0]


def invalidate_cache() -> None:
    """Force the next get_key() call to re-read from Keychain."""
    global _cache_value, _cache_loaded
    with _cache_lock:
        _cache_value = ""
        _cache_loaded = False


def get_key() -> str:
    """Return the stored Gemini API key.

    First successful call hits Keychain; afterwards we serve from in-process
    cache for free. On timeout we also serve "" from cache rather than
    re-hitting Keychain every time (noisy Security prompt storms) — this
    returns "" consistently until `set_key()` installs a real value."""
    global _cache_value, _cache_loaded
    with _cache_lock:
        if _cache_loaded:
            return _cache_value
    try:
        value = _call_with_timeout(
            lambda: _keyring.get_password(_SERVICE, _USERNAME),
            default="",
        )
    except keyring.errors.KeyringError as e:
        log.warning("Keychain access failed: %s", e)
        value = ""
    result = value or ""
    with _cache_lock:
        _cache_value = result
        _cache_loaded = True
    return result


def set_key(key: str) -> None:
    """Store (or clear, if empty) the Gemini API key in Keychain.

    Updates the in-process cache immediately so subsequent get_key() reads
    return the new value without re-hitting Keychain."""
    global _cache_value, _cache_loaded
    if not key:
        clear_key()
        return
    try:
        _call_with_timeout(
            lambda: _keyring.set_password(_SERVICE, _USERNAME, key),
            default=None,
        )
    except keyring.errors.KeyringError as e:
        log.error("Failed to write key to Keychain: %s", e)
        raise  # surface the error
    with _cache_lock:
        _cache_value = key
        _cache_loaded = True


def clear_key() -> None:
    """Remove the stored key. Idempotent. Also clears the in-memory cache."""
    global _cache_value, _cache_loaded
    try:
        _keyring.delete_password(_SERVICE, _USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass  # already absent
    except keyring.errors.KeyringError as e:
        log.warning("Keychain clear failed: %s", e)
    with _cache_lock:
        _cache_value = ""
        _cache_loaded = True  # we know it's empty
