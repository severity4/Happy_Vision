"""modules/folder_watcher.py — Watch folder service: poll, detect, queue, process"""

import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from modules.config import load_config, save_config
from modules.gemini_vision import analyze_photo
from modules.logger import setup_logger
from modules.metadata_writer import ExiftoolBatch, build_exiftool_args, has_happy_vision_tag
from modules.result_store import ResultStore

log = setup_logger("folder_watcher")

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg"}


class WatcherCallbacks:
    """Callbacks for watch progress events."""

    def on_processed(self, file_path: str, queue_size: int) -> None:
        pass

    def on_error(self, file_path: str, error: str) -> None:
        pass

    def on_state_change(self, state: str) -> None:
        pass


def file_size_stable(
    path: str, stable_duration: float = 1.0, interval: float = 0.2
) -> bool:
    """Check if a file's size is stable (not being written to).

    Returns True if the file size doesn't change for stable_duration seconds.
    """
    prev_size = -1
    deadline = time.time() + stable_duration
    while time.time() < deadline:
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        if size != prev_size:
            prev_size = size
            deadline = time.time() + stable_duration
        time.sleep(interval)
    return prev_size > 0


def _scan_recursive(folder: str) -> list[str]:
    """Recursively find all JPG files using os.scandir."""
    results = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    results.extend(_scan_recursive(entry.path))
                elif entry.is_file() and Path(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS:
                    results.append(entry.path)
    except (PermissionError, OSError) as e:
        log.warning("Cannot scan %s: %s", folder, e)
    return results


class FolderWatcher:
    """Watches a folder for new photos and processes them automatically."""

    def __init__(self, callbacks: WatcherCallbacks | None = None):
        self._callbacks = callbacks or WatcherCallbacks()
        self._state = "stopped"  # watching | paused | stopped
        self._folder: str = ""
        self._interval: float = 10.0
        self._concurrency: int = 1
        self._queue: queue.Queue = queue.Queue()
        self._poll_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused by default
        self._lock = threading.Lock()
        self._processing_count = 0
        self._store: ResultStore | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._batch: "ExiftoolBatch | None" = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def folder(self) -> str:
        return self._folder

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def processing_count(self) -> int:
        with self._lock:
            return self._processing_count

    def start(self, folder: str | None = None) -> None:
        """Start or resume watching."""
        if self._state == "watching":
            return

        if self._state == "paused":
            self._pause_event.set()
            self._state = "watching"
            self._callbacks.on_state_change("watching")
            log.info("Watcher resumed")
            return

        # Fresh start
        if folder:
            self._folder = folder
        if not self._folder or not Path(self._folder).is_dir():
            raise ValueError(f"Watch folder not accessible: {self._folder}")

        config = load_config()
        api_key = config.get("gemini_api_key", "")
        if not api_key:
            raise ValueError("Gemini API key not configured")

        self._concurrency = config.get("watch_concurrency", 1)
        self._interval = config.get("watch_interval", 10)

        self._stop_event.clear()
        self._pause_event.set()
        self._store = ResultStore()
        self._executor = ThreadPoolExecutor(max_workers=self._concurrency)
        self._batch = ExiftoolBatch()

        self._state = "watching"
        self._callbacks.on_state_change("watching")

        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._poll_thread.start()
        self._worker_thread.start()

        log.info("Watcher started: %s (concurrency=%d, interval=%ds)",
                 self._folder, self._concurrency, self._interval)

    def pause(self) -> None:
        """Pause watching — in-progress work completes, no new work starts."""
        if self._state != "watching":
            return
        self._pause_event.clear()
        self._state = "paused"
        self._callbacks.on_state_change("paused")
        log.info("Watcher paused")

    def stop(self) -> None:
        """Stop watching completely. Waits for in-flight workers to finish
        before closing the DB."""
        if self._state == "stopped":
            return
        self._stop_event.set()
        self._pause_event.set()  # unblock if paused

        # Clear the queue so new items don't get picked up
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        # Wait for poll + worker threads to exit their loops
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)

        # Shut down executor with wait=True so in-flight _process_one
        # calls finish before we close the store underneath them.
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None

        # Close batch after workers finish, before closing store
        if self._batch:
            self._batch.close()
            self._batch = None

        self._state = "stopped"
        self._callbacks.on_state_change("stopped")

        # NOW it is safe to close the store
        if self._store:
            self._store.close()
            self._store = None

        log.info("Watcher stopped")

    def set_concurrency(self, value: int) -> None:
        """Update concurrency at runtime by rebuilding the executor.

        In-flight tasks on the old executor finish; new tasks go to the
        new executor. Clamps to [1, 10].
        """
        value = max(1, min(10, value))
        if value == self._concurrency:
            return
        self._concurrency = value
        if self._executor is not None:
            old = self._executor
            self._executor = ThreadPoolExecutor(max_workers=value)
            # shutdown(wait=False) so the caller doesn't block; in-flight
            # tasks continue on the old executor and its threads retire.
            old.shutdown(wait=False)
        log.info("Concurrency updated to %d", value)

    def _poll_loop(self) -> None:
        """Periodically scan the folder for new photos."""
        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            try:
                self._scan_and_enqueue()
            except Exception:
                log.exception("Error during poll scan")

            self._stop_event.wait(timeout=self._interval)

    def _scan_and_enqueue(self) -> None:
        """Scan the current watch folder and add unprocessed photos to queue."""
        enqueued, _ = self._scan_folder_into_queue(self._folder)
        if enqueued > 0:
            log.info("Enqueued %d new photos (queue size: %d)", enqueued, self._queue.qsize())

    def enqueue_folder(self, folder: str) -> tuple[int, int]:
        """Scan a folder once and enqueue unprocessed photos. Returns (enqueued, skipped).

        Unlike `_scan_and_enqueue`, this does NOT add the folder to the polling loop;
        it is a one-shot enqueue into the existing worker queue.
        """
        if not Path(folder).is_dir():
            raise ValueError(f"Folder not accessible: {folder}")
        if self._store is None:
            self._store = ResultStore()
        return self._scan_folder_into_queue(folder)

    def _scan_folder_into_queue(self, folder: str) -> tuple[int, int]:
        """Scan the given folder and enqueue unprocessed photos. Returns (enqueued, skipped)."""
        all_photos = _scan_recursive(folder)
        enqueued = 0
        skipped = 0

        for photo_path in all_photos:
            if self._stop_event.is_set():
                break

            # Fast path: check local DB first
            status = self._store.get_status(photo_path)
            if status == "completed":
                skipped += 1
                continue

            # For unknown or failed files, check IPTC (cross-machine dedup)
            if status is None:
                try:
                    if has_happy_vision_tag(photo_path):
                        # Another machine processed it — record locally and skip
                        self._store.save_result(photo_path, {
                            "file_path": photo_path,
                            "source": "external",
                        })
                        skipped += 1
                        continue
                except Exception:
                    log.warning("Cannot read IPTC for %s, will try to process", photo_path)

            # Check file readiness
            if not file_size_stable(photo_path):
                skipped += 1
                continue

            self._queue.put(photo_path)
            enqueued += 1

        return enqueued, skipped

    def _worker_loop(self) -> None:
        """Process photos from the queue."""
        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            try:
                photo_path = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if self._stop_event.is_set():
                break

            # Submit to executor
            if self._executor:
                self._executor.submit(self._process_one, photo_path)

    def _process_one(self, photo_path: str) -> None:
        """Analyze a single photo, write metadata, then mark completed.

        Pipeline-aligned semantics: save_result('completed') fires only after
        metadata successfully lands on disk, so DB completed implies IPTC is
        written.
        """
        with self._lock:
            self._processing_count += 1

        try:
            config = load_config()
            api_key = config.get("gemini_api_key", "")
            model = config.get("model", "lite")

            result = analyze_photo(photo_path, api_key=api_key, model=model)

            if not result:
                if self._store:
                    self._store.mark_failed(photo_path, "Analysis returned no result")
                self._callbacks.on_error(photo_path, "Analysis returned no result")
                return

            # Write metadata first; only mark completed if IPTC actually lands
            if self._batch is not None:
                args = build_exiftool_args(result) + ["-overwrite_original"]
                if not self._batch.write(photo_path, args):
                    if self._store:
                        self._store.mark_failed(photo_path, "Metadata write failed")
                    self._callbacks.on_error(photo_path, "Metadata write failed")
                    return

            if self._store:
                self._store.save_result(photo_path, result)
            log.info("Processed: %s", photo_path)
            self._callbacks.on_processed(photo_path, self._queue.qsize())
        except Exception as e:
            log.exception("Failed to process %s", photo_path)
            if self._store:
                self._store.mark_failed(photo_path, str(e))
            self._callbacks.on_error(photo_path, str(e))
        finally:
            with self._lock:
                self._processing_count -= 1
