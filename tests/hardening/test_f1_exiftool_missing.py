"""tests/hardening/test_f1_exiftool_missing.py

Hardening F1: 若 exiftool 不在 PATH / 打包時漏掉，app 要提早偵測 + 丟出
清楚可辨識的錯誤，而不是在 pipeline 中才炸 FileNotFoundError。

現實情境：同事拿到打包版 .app 但某種原因 PyInstaller bundle 沒裝到
exiftool（打包腳本 bug，或下載壞掉）。打開 UI 後按「分析並寫入 metadata」
時，pipeline 建 ExiftoolBatch → subprocess.Popen → FileNotFoundError →
前端看到 500 + 沒有任何指示。

本關合約：
1. 有個 `check_exiftool_available()` 能在啟動 / 設定頁提前判斷
2. `ExiftoolBatch()` construction 若 exiftool 不存在丟出 `ExiftoolMissingError`
   而非 FileNotFoundError（讓 pipeline 能辨識並給出更好錯誤）
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from modules import metadata_writer as mw


def test_check_exiftool_available_returns_false_when_missing(monkeypatch):
    """A convenient helper the UI / startup can call to decide whether to
    show 'install exiftool' in the settings panel."""
    # Force _get_exiftool_cmd to return a non-existent binary.
    monkeypatch.setattr(mw, "_get_exiftool_cmd", lambda: "/nonexistent/exiftool-xyz-123")

    assert mw.check_exiftool_available() is False


def test_check_exiftool_available_returns_true_when_real_binary_exists():
    """CI / dev machines typically have exiftool. If not, we skip — this
    test is about the positive path only."""
    import shutil
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed on this machine")

    assert mw.check_exiftool_available() is True


def test_exiftool_batch_init_raises_clear_error_when_binary_missing(monkeypatch):
    """ExiftoolBatch() must not raise a raw FileNotFoundError — it's a
    system-level message from subprocess that doesn't help the user. We
    want a typed ExiftoolMissingError with installation guidance."""
    monkeypatch.setattr(mw, "_get_exiftool_cmd", lambda: "/nonexistent/exiftool-xyz-123")

    with pytest.raises(mw.ExiftoolMissingError) as exc_info:
        mw.ExiftoolBatch()

    # Message should be user-actionable. We're not strict on wording but
    # it must mention exiftool + an install hint.
    msg = str(exc_info.value).lower()
    assert "exiftool" in msg
    assert "install" in msg or "brew" in msg


def test_exiftool_missing_error_is_catchable_as_distinct_exception(monkeypatch):
    """Pipeline / API layer want to distinguish 'exiftool missing' from
    'exiftool crashed mid-write'. The typed exception enables that."""
    monkeypatch.setattr(mw, "_get_exiftool_cmd", lambda: "/nonexistent/exiftool-xyz-123")

    try:
        mw.ExiftoolBatch()
    except mw.ExiftoolMissingError:
        caught = True
    except FileNotFoundError:
        pytest.fail("ExiftoolBatch leaked raw FileNotFoundError — caller "
                    "cannot distinguish from an unrelated missing file")
    else:
        pytest.fail("ExiftoolBatch did not raise despite missing binary")

    assert caught


def test_pipeline_surfaces_clear_error_when_write_metadata_but_no_exiftool(
    tmp_path, monkeypatch,
):
    """Full pipeline: write_metadata=True but exiftool is missing. The
    run must NOT silently mark every photo failed — instead the whole
    run aborts with a clear signal the UI can show."""
    from PIL import Image
    Image.new("RGB", (64, 64)).save(str(tmp_path / "p.jpg"), format="JPEG")

    monkeypatch.setattr(mw, "_get_exiftool_cmd", lambda: "/nonexistent/exiftool-xyz-123")

    from modules import pipeline as pl

    with pytest.raises(mw.ExiftoolMissingError):
        pl.run_pipeline(
            folder=str(tmp_path),
            api_key="test",
            concurrency=1,
            write_metadata=True,
            db_path=tmp_path / "r.db",
        )
