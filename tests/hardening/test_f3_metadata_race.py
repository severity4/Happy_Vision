"""tests/hardening/test_f3_metadata_race.py

Hardening F3: 大量並發寫入同一檔案的 race condition。

真實情境：
- 不太可能兩個 worker 寫同一張，因為 pipeline 的 to_process 依 file_path
  去重 + SQLite `is_processed` 防重
- 但 folder_watcher + 手動 pipeline 同時跑同資料夾 → 有機會撞同檔
- exiftool `-overwrite_original` 底層是：寫 tmp → rename(2)。rename 是
  atomic，兩個並發 rename 最後一個 wins，不會產生半寫狀態

合約：
- 同一張照片併發寫入不會 crash 或產生 0-byte 檔
- 最後一個 write 勝出，檔案仍可讀（JPEG 結構完整）
- ExiftoolBatch 是 thread-safe（自帶 _lock），同 instance 併發呼叫 OK
"""

from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from modules import metadata_writer as mw


def _write_jpg(path: Path) -> None:
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


@pytest.fixture
def exiftool_required():
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed")


def test_exiftool_batch_lock_is_real(exiftool_required, tmp_path):
    """ExiftoolBatch has a threading.Lock. 16 parallel writes to DIFFERENT
    files must all succeed — lock serializes them but none should fail."""
    photos = []
    for i in range(16):
        p = tmp_path / f"p{i:02d}.jpg"
        _write_jpg(p)
        photos.append(p)

    batch = mw.ExiftoolBatch()
    results: list[bool] = []
    results_lock = threading.Lock()

    def write_one(p):
        ok = batch.write(str(p), [f"-IPTC:Headline=photo_{p.stem}",
                                  "-overwrite_original"])
        with results_lock:
            results.append(ok)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(write_one, photos))

    batch.close()
    assert all(results), (
        f"{results.count(False)}/16 parallel writes failed — lock contention "
        "or stdin corruption"
    )


def test_concurrent_writes_to_same_file_do_not_corrupt(exiftool_required, tmp_path):
    """Two parallel writes to the SAME file must both complete without
    leaving the JPEG unreadable. One of them wins (last rename), but the
    file is always a valid JPEG on disk."""
    photo = tmp_path / "contested.jpg"
    _write_jpg(photo)

    batch = mw.ExiftoolBatch()
    errors = []

    def write_title(title):
        try:
            ok = batch.write(str(photo), [f"-IPTC:Headline={title}",
                                          "-overwrite_original"])
            if not ok:
                errors.append(f"write {title} returned False")
        except Exception as e:
            errors.append(f"write {title} raised: {e}")

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(write_title, f"v{i}") for i in range(20)]
        for f in futures:
            f.result(timeout=30)

    batch.close()

    assert not errors, f"errors during concurrent writes: {errors}"
    # File still readable as JPEG
    assert photo.stat().st_size > 0
    with Image.open(photo) as img:
        img.verify()


def test_exiftool_batch_single_instance_used_safely_across_threads(
    exiftool_required, tmp_path,
):
    """Regression guard on the per-instance lock: the stdin protocol
    (feed args, send -execute, read until {ready}) is NOT re-entrant.
    Two threads interleaving would scramble the session. Lock must
    serialize the whole transaction atomically."""
    photos = [tmp_path / f"t{i}.jpg" for i in range(10)]
    for p in photos:
        _write_jpg(p)

    batch = mw.ExiftoolBatch()
    # Every thread interleaves reads + writes
    errors = []

    def mixed_ops(p):
        try:
            ok = batch.write(str(p), [f"-IPTC:Headline={p.stem}",
                                      "-overwrite_original"])
            if not ok:
                errors.append(f"write fail {p}")
            # read back
            data = batch.read_json(str(p), ["-IPTC:Headline"])
            if data.get("Headline") != p.stem:
                errors.append(f"read mismatch {p}: got {data!r}")
        except Exception as e:
            errors.append(f"exception {p}: {e}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(mixed_ops, photos))

    batch.close()
    assert not errors, f"interleaved read/write corrupted session: {errors}"
