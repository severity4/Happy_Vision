"""modules/pipeline.py — Orchestrator: scan folder, run analysis, coordinate modules"""

import concurrent.futures
import threading
from pathlib import Path

from modules.gemini_vision import analyze_photo
from modules.metadata_writer import write_metadata as write_meta
from modules.result_store import ResultStore
from modules.logger import setup_logger

log = setup_logger("pipeline")

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg"}


class PipelineCallbacks:
    """Callbacks for pipeline progress updates."""

    def on_progress(self, done: int, total: int, file_path: str) -> None:
        pass

    def on_error(self, file_path: str, error: str) -> None:
        pass

    def on_complete(self, total: int, failed: int) -> None:
        pass


def scan_photos(folder: str) -> list[str]:
    """Recursively find all JPG files in folder."""
    root = Path(folder)
    if not root.is_dir():
        log.error("Not a directory: %s", folder)
        return []

    photos = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            photos.append(str(path))

    log.info("Found %d photos in %s", len(photos), folder)
    return photos


class PipelineState:
    """Thread-safe pipeline state for pause/cancel."""

    def __init__(self):
        self.cancelled = False
        self.paused = threading.Event()
        self.paused.set()  # not paused by default

    def cancel(self):
        self.cancelled = True
        self.paused.set()  # unblock if paused

    def pause(self):
        self.paused.clear()

    def resume(self):
        self.paused.set()

    def wait_if_paused(self):
        self.paused.wait()


def run_pipeline(
    folder: str,
    api_key: str,
    model: str = "lite",
    concurrency: int = 5,
    skip_existing: bool = False,
    write_metadata: bool = False,
    db_path: Path | str | None = None,
    callbacks: PipelineCallbacks | None = None,
    state: PipelineState | None = None,
) -> list[dict]:
    """Run the full analysis pipeline on a folder of photos.
    Pass a PipelineState to control pause/cancel from outside."""
    if state is None:
        state = PipelineState()

    if callbacks is None:
        callbacks = PipelineCallbacks()

    photos = scan_photos(folder)
    if not photos:
        callbacks.on_complete(0, 0)
        return []

    store = ResultStore(db_path)
    results = []
    done_count = 0
    failed_count = 0
    lock = threading.Lock()

    # Filter already processed
    if skip_existing:
        to_process = [p for p in photos if not store.is_processed(p)]
        log.info(
            "Skipping %d already processed, %d to analyze",
            len(photos) - len(to_process),
            len(to_process),
        )
    else:
        to_process = photos

    total = len(to_process)

    def process_one(photo_path: str) -> dict | None:
        nonlocal done_count, failed_count
        if state.cancelled:
            return None
        state.wait_if_paused()
        if state.cancelled:
            return None

        result = analyze_photo(photo_path, api_key=api_key, model=model)

        with lock:
            if result:
                store.save_result(photo_path, result)
                results.append(result)
            else:
                store.mark_failed(photo_path, "Analysis returned no result")
                failed_count += 1
                callbacks.on_error(photo_path, "Analysis failed")

            done_count += 1
            callbacks.on_progress(done_count, total, photo_path)

        return result

    if concurrency <= 1:
        for photo in to_process:
            process_one(photo)
            if state.cancelled:
                break
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(process_one, p): p for p in to_process}
            for future in concurrent.futures.as_completed(futures):
                if state.cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                future.result()

    # Write metadata only for photos in this folder
    if write_metadata and results:
        for r in store.get_results_for_folder(folder):
            write_meta(r["file_path"], r)

    store.close()
    callbacks.on_complete(total, failed_count)
    log.info("Pipeline complete: %d analyzed, %d failed", len(results), failed_count)
    return results
