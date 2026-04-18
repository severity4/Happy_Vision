"""modules/logger.py — Logging setup for Happy Vision"""

import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


_REDACT = "REDACTED"

_PATTERNS: list[tuple[re.Pattern, str | None]] = [
    # Google API key — AIza followed by ≥20 allowed chars. Real keys are 39
    # chars total (AIza + 35), but we accept 24+ to catch truncated/malformed
    # logs that would otherwise leak a tail. A standalone "AIza" literal is
    # safe; we only redact when followed by meaningful entropy.
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), None),
    # Google OAuth / refresh tokens (ya29.x..., 1//x...)
    (re.compile(r"ya29\.[A-Za-z0-9._\-]+"), None),
    (re.compile(r"1//[0-9A-Za-z_\-]{20,}"), None),
    # Anthropic-style keys (future-proof — sk-ant-, sk-*)
    (re.compile(r"sk(-ant)?-[A-Za-z0-9_\-]{20,}"), None),
    # Authorization header (any scheme: Bearer, Basic, Token, Digest, ...)
    (re.compile(r"(?i)(Authorization|X-Goog-Api-Key|X-Api-Key)\s*:\s*\S+"),
     r"\1: " + _REDACT),
    (re.compile(r"(?i)(Bearer|Basic|Token|Digest)\s+[A-Za-z0-9._\-=+/]+"),
     r"\1 " + _REDACT),
    # api_key=xxx / access_token=xxx / key=xxx / token=xxx in query strings,
    # JSON, YAML, form bodies. Case-insensitive; word-boundary to avoid
    # catching "invokeKey=" type false positives.
    (re.compile(r"(?i)\b(api[_\-]?key|access[_\-]?token|secret[_\-]?key|token|key)\s*[:=]\s*['\"]?([A-Za-z0-9._\-]+)"),
     r"\1=" + _REDACT),
]


def _scrub(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl if repl is not None else _REDACT, text)
    return text


class SensitiveDataFilter(logging.Filter):
    """Scrubs API keys / bearer tokens from log records before they hit handlers.

    Operates on both ``msg`` (after %-formatting) and raw string ``args``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    _scrub(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (_scrub(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        # Exception tracebacks — the formatted exc_text — can also contain
        # secrets if an exception's repr includes the key. Scrub there too.
        if record.exc_text:
            record.exc_text = _scrub(record.exc_text)
        return True


def setup_logger(name: str = "happy_vision") -> logging.Logger:
    """Set up a logger that writes to ~/.happy-vision/logs/ and stdout."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    sensitive_filter = SensitiveDataFilter()

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    console.addFilter(sensitive_filter)
    logger.addHandler(console)

    # File handler
    try:
        log_dir = get_config_dir() / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{datetime.now():%Y-%m-%d}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError:
        fallback_dir = Path(tempfile.gettempdir()) / "happy-vision-logs"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        log_file = fallback_dir / f"{datetime.now():%Y-%m-%d}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    file_handler.addFilter(sensitive_filter)
    logger.addHandler(file_handler)

    return logger
