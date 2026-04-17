"""modules/logger.py — Logging setup for Happy Vision"""

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


def setup_logger(name: str = "happy_vision") -> logging.Logger:
    """Set up a logger that writes to ~/.happy-vision/logs/ and stdout."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
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
    logger.addHandler(file_handler)

    return logger
