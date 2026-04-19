"""modules/batch_monitor.py — Background thread polling Gemini Batch jobs.

Starts at app boot (web_ui._post_start_init) and runs forever. Every
POLL_INTERVAL_SECONDS it loads still-active batch_jobs rows from the DB,
hits Gemini for status, and on SUCCEEDED downloads + parses the output JSONL,
then writes analysis results + (optionally) IPTC metadata.

Designed so the user can quit and relaunch Happy Vision without losing jobs:
state lives in SQLite, not memory. The monitor picks up where it left off.

Event emissions go through the existing SSE broker (api/analysis.py or a
dedicated watch channel) via the `event_sink` callback — we don't import
Flask here to keep this module test-friendly.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from modules import gemini_batch
from modules.config import load_config
from modules.event_store import EventStore
from modules.logger import setup_logger
from modules.metadata_writer import ExiftoolBatch, build_exiftool_args
from modules.pricing import calc_cost_usd
from modules.result_store import ResultStore

log = setup_logger("batch_monitor")

POLL_INTERVAL_SECONDS = 60
# v0.11.0: after this many consecutive per-job poll failures, mark the job
# JOB_STATE_FAILED so it stops occupying the active list. Catches zombies
# from API key rotation or the user revoking billing mid-flight. Tuned to
# ~20 × 60s = 20 min of genuine API trouble before giving up.
MAX_POLL_FAILURES = 20
# Jitter the sleep between ticks ±20% so many app instances don't stampede
# Gemini on the same 60s boundary (SRE audit).
JITTER_FACTOR = 0.2
# Map internal status to user-facing Chinese; the frontend can override,
# but the SSE event payload keeps state.name for machine logic.
STATE_DISPLAY = {
    "JOB_STATE_PENDING": "等候中",
    "JOB_STATE_QUEUED": "排隊中",
    "JOB_STATE_RUNNING": "處理中",
    "JOB_STATE_SUCCEEDED": "已完成",
    "JOB_STATE_FAILED": "失敗",
    "JOB_STATE_CANCELLED": "已取消",
    "JOB_STATE_EXPIRED": "已過期",
    "JOB_STATE_PARTIALLY_SUCCEEDED": "部分完成",
}

EventSink = Callable[[dict], None]


class BatchMonitor:
    def __init__(self, event_sink: EventSink | None = None, db_path: Path | str | None = None):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._event_sink = event_sink
        self._db_path = db_path
        # Exponential backoff for transient API errors so we don't hammer Google
        # when their side is wobbling. Only counts ALL-jobs outages, not
        # per-job failures — those go on `batch_jobs.consecutive_poll_failures`.
        self._consecutive_errors = 0
        # Observability (v0.11.0): expose heartbeat state to /api/batch/health.
        self._lock = threading.Lock()
        self._last_tick_at: str | None = None
        self._last_tick_error: str | None = None
        self._active_job_count = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="batch-monitor", daemon=True)
        self._thread.start()
        log.info("Batch monitor started (poll=%ds)", POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _emit(self, payload: dict) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink(payload)
        except Exception:  # noqa: BLE001
            log.warning("event_sink raised", exc_info=True)

    def _run(self) -> None:
        # Warm-up delay — let the app finish its boot work before we touch the API.
        time.sleep(3)
        while not self._stop.is_set():
            tick_error: str | None = None
            try:
                self._tick()
                self._consecutive_errors = 0
            except Exception as e:  # noqa: BLE001
                self._consecutive_errors += 1
                tick_error = str(e)[:300]
                log.exception("Batch monitor tick failed (streak=%d)", self._consecutive_errors)
            with self._lock:
                self._last_tick_at = datetime.now().isoformat()
                self._last_tick_error = tick_error
            # Heartbeat emission so the UI / /api/batch/health can prove the
            # thread is alive (SRE HIGH: observability gap).
            self._emit({
                "type": "batch_heartbeat",
                "ts": self._last_tick_at,
                "active_jobs": self._active_job_count,
                "consecutive_errors": self._consecutive_errors,
                "last_error": tick_error,
            })
            base = POLL_INTERVAL_SECONDS * (2 ** min(self._consecutive_errors, 4))
            # ±JITTER_FACTOR so many clients don't land in lockstep.
            delay = base * (1 + random.uniform(-JITTER_FACTOR, JITTER_FACTOR))
            self._stop.wait(timeout=max(5.0, delay))

    def health_snapshot(self) -> dict:
        """Exposed to /api/batch/health. Safe to read from any thread."""
        with self._lock:
            return {
                "alive": self._thread is not None and self._thread.is_alive(),
                "last_tick_at": self._last_tick_at,
                "last_tick_error": self._last_tick_error,
                "active_jobs": self._active_job_count,
                "consecutive_errors": self._consecutive_errors,
            }

    def _tick(self) -> None:
        config = load_config()
        api_key = (config.get("gemini_api_key") or "").strip()
        if not api_key:
            with self._lock:
                self._active_job_count = 0
            return  # User hasn't configured a key yet; nothing to poll.
        store = ResultStore(self._db_path)
        try:
            active = store.list_batch_jobs(active_only=True, limit=50)
            with self._lock:
                self._active_job_count = len(active)
            if not active:
                return
            log.info("Polling %d active batch jobs", len(active))
            for job_row in active:
                if self._stop.is_set():
                    break
                self._poll_one(store, job_row, api_key)
        finally:
            store.close()

    def _poll_one(self, store: ResultStore, job_row: dict, api_key: str) -> None:
        job_id = job_row["job_id"]
        try:
            state_info = gemini_batch.get_job_state(job_id, api_key)
        except Exception as e:  # noqa: BLE001
            # v0.11.0: per-job failure tracking. One flaky job won't trigger
            # the whole-monitor backoff, but it WILL escalate its own
            # consecutive_poll_failures — after MAX_POLL_FAILURES ticks we
            # mark it FAILED so it stops polluting the active list.
            msg = str(e)[:300]
            log.warning("get_job_state(%s) failed: %s", job_id, msg)
            failures = store.record_poll_attempt(job_id, error=msg)
            if failures >= MAX_POLL_FAILURES:
                log.error(
                    "Batch %s exceeded %d poll failures — marking FAILED",
                    job_id, MAX_POLL_FAILURES,
                )
                store.update_batch_job_status(
                    job_id, "JOB_STATE_FAILED",
                    error_message=f"Monitor gave up after {MAX_POLL_FAILURES} poll failures: {msg}",
                )
                self._emit({
                    "type": "batch_state",
                    "job_id": job_id,
                    "state": "JOB_STATE_FAILED",
                    "state_display": STATE_DISPLAY.get("JOB_STATE_FAILED", "失敗"),
                    "error": f"poll_failures_exceeded ({MAX_POLL_FAILURES})",
                })
                # Roll pending items to failed so the UI shows them.
                for item in store.get_batch_items(job_id):
                    if item["status"] == "pending":
                        store.mark_batch_item(job_id, item["request_key"], "failed")
                        store.mark_failed(item["file_path"], "Batch: monitor gave up")
            return
        # Success — reset per-job failure counter.
        store.record_poll_attempt(job_id, error=None)
        state = state_info["state"]
        output_file = state_info["output_file"]
        err = state_info["error"]

        state_changed = state != job_row["status"]
        # Recovery path (v0.10.1): if the job is already SUCCEEDED in our DB
        # but materialisation never finished (exiftool missing, app killed
        # mid-loop, DB lock contention, etc), re-enter materialise on later
        # ticks until all items are in a terminal state. Previously the
        # `state == job_row["status"]` early-return meant such a job was
        # permanently stuck with orphaned pending items.
        is_success = state in ("JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED")
        completed_so_far = int(job_row.get("completed_count") or 0)
        failed_so_far = int(job_row.get("failed_count") or 0)
        needs_materialise = is_success and (
            completed_so_far + failed_so_far < int(job_row.get("photo_count") or 0)
        )

        if not state_changed and not needs_materialise:
            return  # steady state — nothing to do

        if state_changed:
            log.info("Batch %s: %s → %s", job_id, job_row["status"], state)
            store.update_batch_job_status(
                job_id, state,
                output_file_id=output_file,
                error_message=err,
            )
            self._emit({
                "type": "batch_state",
                "job_id": job_id,
                "state": state,
                "state_display": STATE_DISPLAY.get(state, state),
                "error": err,
            })

        if is_success:
            self._materialise_results(store, job_row, api_key)
        elif state_changed and state in ("JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"):
            # Roll item rows to a terminal state so the UI can show them.
            for item in store.get_batch_items(job_id):
                if item["status"] == "pending":
                    store.mark_batch_item(job_id, item["request_key"], "failed")
                    store.mark_failed(item["file_path"], f"Batch job {state}")

    def _materialise_results(self, store: ResultStore, job_row: dict, api_key: str) -> None:
        """Fetch output JSONL, save results, write metadata.

        Item-level idempotent (v0.10.1): items whose batch_items.status is
        already 'completed' are skipped entirely — no re-IPTC-write on
        retry. Code reviewer flagged the v0.9.x version as destructive on
        cold-boot because `save_result` uses INSERT OR REPLACE and
        `-overwrite_original` would stomp user-edited IPTC.

        Also wraps ExiftoolBatch init so a missing exiftool binary doesn't
        kill the tick — the job stays SUCCEEDED with completed<photo_count,
        so the next tick re-enters this method once exiftool is fixed."""
        job_id = job_row["job_id"]
        items = store.get_batch_items(job_id)
        by_key = {it["request_key"]: it["file_path"] for it in items}
        already_done = {it["request_key"] for it in items if it["status"] == "completed"}
        model = job_row["model"]
        write_metadata = bool(job_row.get("write_metadata"))

        events = EventStore()
        batch_writer: ExiftoolBatch | None = None
        if write_metadata:
            try:
                batch_writer = ExiftoolBatch()
            except Exception as e:  # noqa: BLE001
                log.error(
                    "ExiftoolBatch init failed for job %s: %s. Leaving "
                    "items pending — will retry on next tick.",
                    job_id, e,
                )
                events.close()
                return
        # Start counters from already-persisted state so the final
        # update_batch_job_counts call reflects total progress, not just
        # this tick's increments.
        completed = sum(1 for it in items if it["status"] == "completed")
        failed = sum(1 for it in items if it["status"] == "failed")
        try:
            for result in gemini_batch.fetch_results(job_id, api_key, model=model):
                path = by_key.get(result.key)
                if path is None:
                    log.warning("Batch %s: unknown key %s in output, skipping", job_id, result.key)
                    continue
                if result.key in already_done:
                    # v0.10.1 idempotency: don't re-write IPTC for items we
                    # already finished. Counter was initialised from DB above.
                    continue
                if result.result is None:
                    store.mark_failed(path, f"Batch: {result.error or 'unknown error'}")
                    store.mark_batch_item(job_id, result.key, "failed")
                    failed += 1
                    continue
                cost = None
                if result.usage:
                    cost = calc_cost_usd(
                        result.usage.get("model", ""),
                        result.usage.get("input_tokens", 0),
                        result.usage.get("output_tokens", 0),
                        batch=True,
                    )

                # Write IPTC metadata before save_result so a later "completed"
                # row implies the photo actually has the tags on disk.
                if batch_writer is not None:
                    args = build_exiftool_args(result.result) + ["-overwrite_original"]
                    if not batch_writer.write(path, args):
                        store.mark_failed(path, "Batch: metadata write failed")
                        store.mark_batch_item(job_id, result.key, "failed")
                        failed += 1
                        continue
                store.save_result(path, result.result, usage=result.usage, cost_usd=cost)
                store.mark_batch_item(job_id, result.key, "completed")
                completed += 1
                events.add_event(
                    "batch_photo_completed",
                    folder=job_row["folder"],
                    file_path=path,
                    details={"job_id": job_id},
                )
                self._emit({
                    "type": "batch_item",
                    "job_id": job_id,
                    "file_path": path,
                    "completed": completed,
                    "failed": failed,
                    "total": job_row["photo_count"],
                })
            # Only update counters — the terminal state was already written
            # by _poll_one before we were called. Writing status here with
            # job_row["status"] (stale) used to regress SUCCEEDED back to the
            # pre-poll state. This was caught by external review 2026-04-19.
            store.update_batch_job_counts(
                job_id,
                completed_count=completed,
                failed_count=failed,
            )
        finally:
            if batch_writer is not None:
                batch_writer.close()
            events.add_event(
                "batch_run_finished",
                folder=job_row["folder"],
                details={
                    "job_id": job_id,
                    "completed": completed,
                    "failed": failed,
                    "total": job_row["photo_count"],
                },
            )
            events.close()
        log.info("Batch %s materialised: %d completed, %d failed", job_id, completed, failed)


_monitor_instance: BatchMonitor | None = None
_monitor_lock = threading.Lock()


def start_background_monitor(event_sink: EventSink | None = None) -> BatchMonitor:
    """Idempotent — safe to call from multiple init paths."""
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = BatchMonitor(event_sink=event_sink)
            _monitor_instance.start()
        return _monitor_instance


def stop_background_monitor() -> None:
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is not None:
            _monitor_instance.stop()
            _monitor_instance = None
