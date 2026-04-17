"""tests/test_logger.py — SensitiveDataFilter strips keys from log records."""

import logging

from modules.logger import SensitiveDataFilter


def _apply(msg, *args):
    rec = logging.LogRecord(
        name="t", level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=args if args else None, exc_info=None,
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
    assert "foo=bar" in out


def test_scrubs_api_key_in_args():
    """Arguments passed as %s substitution must also be scrubbed."""
    out = _apply("api failed: %s",
                 "key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 bad request")
    assert "AIza" not in out


def test_does_not_touch_safe_text():
    out = _apply("Analyzed photo.jpg: speaker on stage")
    assert out == "Analyzed photo.jpg: speaker on stage"


def test_greedy_match_does_not_leak_key_tail():
    """Regex must consume entire key even if it's longer than the standard
    39 chars — defense against malformed or future key variants."""
    # 42 chars of allowed class after AIza
    overlong = "AIza" + "A" * 42
    out = _apply(f"leak? {overlong} trailing")
    assert "A" * 36 not in out, "any run of 36+ legit chars means tail leaked"
    assert "trailing" in out
