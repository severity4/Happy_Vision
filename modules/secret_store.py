"""modules/secret_store.py — macOS Keychain wrapper for API keys.

Stores the Gemini API key in the user's Keychain via the `keyring` package.
On macOS this uses the login keychain with process-level access control,
protecting the key from backup exfiltration (Time Machine, iCloud Desktop)
and file-system readers with Full Disk Access.
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


def get_key() -> str:
    """Return the stored Gemini API key, or empty string if not set,
    unreachable, or Keychain access timed out."""
    try:
        value = _call_with_timeout(
            lambda: _keyring.get_password(_SERVICE, _USERNAME),
            default="",
        )
    except keyring.errors.KeyringError as e:
        log.warning("Keychain access failed: %s", e)
        return ""
    return value or ""


def set_key(key: str) -> None:
    """Store (or clear, if empty) the Gemini API key in Keychain."""
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


def clear_key() -> None:
    """Remove the stored key. Idempotent."""
    try:
        _keyring.delete_password(_SERVICE, _USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass  # already absent
    except keyring.errors.KeyringError as e:
        log.warning("Keychain clear failed: %s", e)
