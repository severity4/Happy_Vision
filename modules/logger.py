"""modules/logger.py — Logging setup for Happy Vision"""

import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


_REDACT = "REDACTED"

_PATTERNS: list[tuple[re.Pattern, str | None]] = [
    # Google API key (AIza + 35 alphanumerics / _ / -)
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), None),
    # Google OAuth access tokens (ya29.xxxx)
    (re.compile(r"ya29\.[A-Za-z0-9._\-]+"), None),
    # Bearer / Token headers
    (re.compile(r"(?i)(Bearer|Token)\s+[A-Za-z0-9._\-]+"), r"\1 " + _REDACT),
    # api_key=xxx / access_token=xxx / key=xxx (query strings, JSON-ish)
    (re.compile(r"(?i)(api[_\-]?key|access[_\-]?token|key)=([A-Za-z0-9._\-]+)"),
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
