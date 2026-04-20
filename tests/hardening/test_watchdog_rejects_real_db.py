"""tests/hardening/test_watchdog_rejects_real_db.py

Guards against the 2026-04 pytest-pollution incident: watcher daemon
threads outlived their fixture's HAPPY_VISION_HOME monkeypatch and wrote
134 pytest tmp_path rows into the real ~/.happy-vision/results.db.

`ResultStore.__init__` now trips a `RuntimeError` if pytest is imported
AND the target DB lives under the real home's `.happy-vision/`. This
test confirms the wire actually trips."""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.result_store import ResultStore


def test_resultstore_rejects_real_home_path_under_pytest(tmp_path):
    """Any attempt to open a DB under the real ~/.happy-vision/ during
    pytest must raise — even if the path was constructed deliberately."""
    forbidden = Path.home() / ".happy-vision" / "results.db"
    with pytest.raises(RuntimeError, match="real-home DB"):
        ResultStore(forbidden)


def test_resultstore_rejects_real_home_subdir_path_under_pytest(tmp_path):
    """Nested paths under ~/.happy-vision/ (e.g. fallback subdirs) also
    blocked — the guard checks parents, not just immediate parent."""
    forbidden = Path.home() / ".happy-vision" / "sub" / "results.db"
    with pytest.raises(RuntimeError, match="real-home DB"):
        ResultStore(forbidden)


def test_resultstore_accepts_tmp_path(tmp_path):
    """Sanity: the guard doesn't false-positive on normal test paths."""
    store = ResultStore(tmp_path / "results.db")
    store.close()


def test_resultstore_accepts_fallback_dir(tmp_path, monkeypatch):
    """~/.happy-vision-fallback/ is separate and should be allowed, else
    the existing fallback-path logic would also trip this guard."""
    fb = Path.home() / ".happy-vision-fallback" / "results.db"
    # We can't actually write to the real home during tests, so just make
    # sure the guard doesn't immediately raise before sqlite gets a chance.
    # If the guard were too broad this would raise RuntimeError("real-home");
    # if it's correctly scoped it raises sqlite/OSError or succeeds.
    try:
        ResultStore(fb).close()
    except RuntimeError as e:
        assert "real-home DB" not in str(e), (
            "guard over-triggered on fallback dir"
        )
    except (OSError, Exception):
        pass  # permissions/other — not what we're testing here
