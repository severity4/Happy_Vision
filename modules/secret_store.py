"""modules/secret_store.py — macOS Keychain wrapper for API keys.

Stores the Gemini API key in the user's Keychain via the `keyring` package.
On macOS this uses the login keychain with process-level access control,
protecting the key from backup exfiltration (Time Machine, iCloud Desktop)
and file-system readers with Full Disk Access.
"""

import keyring
import logging

log = logging.getLogger(__name__)

_keyring = keyring
_SERVICE = "happy-vision"
_USERNAME = "gemini_api_key"


def get_key() -> str:
    """Return the stored Gemini API key, or empty string if not set or unreachable."""
    try:
        value = _keyring.get_password(_SERVICE, _USERNAME)
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
        _keyring.set_password(_SERVICE, _USERNAME, key)
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
