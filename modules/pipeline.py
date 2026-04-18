"""modules/pipeline.py — Orchestrator: scan folder, run analysis, coordinate modules"""

import concurrent.futures
import threading
import time
from pathlib import Path

from modules.event_store import EventStore
from modules.gemini_vision import analyze_photo
from modules.metadata_writer import ExiftoolBatch, build_exiftool_args
from modules.pricing import calc_cost_usd
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
    batch = ExiftoolBatch() if write_metadata else None
    events = EventStore()
    events.add_event(
        "analysis_run_started",
        folder=folder,
        details={
            "total": total,
            "model": model,
            "concurrency": concurrency,
            "skip_existing": skip_existing,
            "write_metadata": write_metadata,
        },
    )

    def process_one(photo_path: str) -> dict | None:
        nonlocal done_count, failed_count
        if state.cancelled:
            return None
        state.wait_if_paused()
        if state.cancelled:
            return None

        analysis_started = time.perf_counter()
        result, usage = analyze_photo(photo_path, api_key=api_key, model=model)
        analyze_ms = round((time.perf_counter() - analysis_started) * 1000)

        cost_usd = None
        if usage:
            cost_usd = calc_cost_usd(
                usage.get("model", ""),
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            )

        # Write metadata before saving as 'completed' so that a successful
        # save_result guarantees the photo has the IPTC marker on disk.
        metadata_ms = None
        if result and batch is not None:
            metadata_started = time.perf_counter()
            args = build_exiftool_args(result) + ["-overwrite_original"]
            if not batch.write(photo_path, args):
                result = None  # treat metadata failure as a full failure
            metadata_ms = round((time.perf_counter() - metadata_started) * 1000)

        with lock:
            if result:
                store.save_result(photo_path, result, usage=usage, cost_usd=cost_usd)
                results.append(result)
                events.add_event(
                    "analysis_photo_completed",
                    folder=folder,
                    file_path=photo_path,
                    details={
                        "analyze_ms": analyze_ms,
                        "metadata_write_ms": metadata_ms,
                        "write_metadata": batch is not None,
                    },
                )
            else:
                if state.cancelled:
                    return None  # user cancelled; don't mark failed
                store.mark_failed(photo_path, "Analysis or metadata write failed")
                failed_count += 1
                callbacks.on_error(photo_path, "Analysis or metadata failed")
                events.add_event(
                    "analysis_photo_failed",
                    folder=folder,
                    file_path=photo_path,
                    details={
                        "analyze_ms": analyze_ms,
                        "metadata_write_ms": metadata_ms,
                        "error_stage": "metadata_write" if batch is not None else "analysis",
                    },
                )

            done_count += 1
            callbacks.on_progress(done_count, total, photo_path)

        return result

    try:
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
    finally:
        if batch is not None:
            batch.close()
        events.add_event(
            "analysis_run_finished",
            folder=folder,
            details={
                "total": total,
                "completed": len(results),
                "failed": failed_count,
                "cancelled": state.cancelled,
            },
        )
        events.close()

    store.close()
    callbacks.on_complete(total, failed_count)
    log.info("Pipeline complete: %d analyzed, %d failed", len(results), failed_count)
    return results
