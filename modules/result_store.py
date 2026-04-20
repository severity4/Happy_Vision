"""modules/result_store.py — SQLite result storage with checkpoint/resume"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir

log = logging.getLogger(__name__)


def _assert_not_polluting_real_home(db_path: Path) -> None:
    """Trip wire: under pytest, refuse to touch the developer's real
    ~/.happy-vision/ DB. Background threads from watcher tests used to
    outlive the monkeypatch that redirected HAPPY_VISION_HOME, then wrote
    pytest tmp_path rows into the real DB — silently corrupting the user's
    local results.

    We detect pytest via `sys.modules["pytest"]` (not PYTEST_CURRENT_TEST,
    which is cleared between test items so leaked threads writing in the
    gap window escape). Production never imports pytest, so runtime cost
    is a single dict lookup."""
    import sys
    if "pytest" not in sys.modules:
        return
    try:
        real_home = Path.home().expanduser().resolve()
        target = db_path.expanduser().resolve()
    except (OSError, RuntimeError):
        return  # Can't resolve? Don't block — better than a false-positive.
    forbidden = real_home / ".happy-vision"
    if forbidden == target.parent or forbidden in target.parents:
        raise RuntimeError(
            f"ResultStore refusing to open real-home DB during pytest: {target}. "
            "Either a test didn't set HAPPY_VISION_HOME, OR a background "
            "thread outlived its fixture's monkeypatch (check api/watch.py "
            "watcher teardown). This guard exists because of the 2026-04 incident "
            "where 134 pytest-tmp rows polluted the developer's real DB."
        )


class ResultStore:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_config_dir() / "results.db"
        _assert_not_polluting_real_home(Path(db_path))
        self._lock = threading.Lock()
        self.db_path = self._resolve_db_path(Path(db_path))
        try:
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_db()
        except sqlite3.Error as e:
            # Primary location failed. Close whatever connection we opened
            # before falling back — else we leak an fd + risk partial state.
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001 — close must not mask the original failure
                pass
            # Durable fallback inside the user's home so data survives reboot.
            # /tmp would silently discard results — never use that here.
            fallback_dir = Path.home() / ".happy-vision-fallback"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = fallback_dir / Path(db_path).name
            log.error(
                "Primary DB path unusable (%s). Falling back to %s. "
                "Analysis results will save there instead — inspect the cause.",
                e, self.db_path,
            )
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_db()

    def _resolve_db_path(self, path: Path) -> Path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            test_conn = sqlite3.connect(str(path))
            test_conn.close()
            return path
        except (sqlite3.Error, OSError) as e:
            # Same durable fallback as __init__ — never /tmp. OSError
            # covers the rare case where `path.parent` exists and is a
            # file (mkdir raises FileExistsError, not sqlite3.Error).
            fallback_dir = Path.home() / ".happy-vision-fallback"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            log.warning(
                "Cannot write DB at %s (%s). Falling back to %s",
                path, e, fallback_dir,
            )
            return fallback_dir / path.name

    def _init_db(self):
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                file_path TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'completed',
                result_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_status ON results(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_updated_at ON results(updated_at DESC)")
        # Additive migrations — silently skip columns that already exist.
        for col, coltype in [
            ("input_tokens", "INTEGER"),
            ("output_tokens", "INTEGER"),
            ("total_tokens", "INTEGER"),
            ("cost_usd", "REAL"),
            ("model", "TEXT"),
            # v0.6.0: near-duplicate detection. phash is the perceptual hash
            # of the photo content (16-char hex); duplicate_of points to the
            # file_path of the master photo when this row was saved as a
            # near-duplicate without a fresh Gemini call.
            ("phash", "TEXT"),
            ("duplicate_of", "TEXT"),
            # v0.12.0: first 16 bits of phash as int. Lets find_similar do
            # a prefix-bucket lookup instead of a LIMIT 5000 recent scan,
            # which capped dedup recall at 15万-photo scale. See
            # modules/phash.prefix16 for the trade-off.
            ("phash_prefix", "INTEGER"),
        ]:
            try:
                self.conn.execute(f"ALTER TABLE results ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_phash ON results(phash)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_phash_prefix ON results(phash_prefix)")

        # v0.9.0: Gemini Batch API job tracking. One row per submitted batch
        # job, one row per (job, request_key) in batch_items so we can map
        # output lines back to local paths after the app restarts.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                folder TEXT NOT NULL,
                model TEXT NOT NULL,
                photo_count INTEGER NOT NULL,
                completed_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                input_file_id TEXT,
                output_file_id TEXT,
                payload_bytes INTEGER NOT NULL DEFAULT 0,
                write_metadata INTEGER NOT NULL DEFAULT 0,
                image_max_size INTEGER NOT NULL DEFAULT 3072,
                display_name TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_jobs(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_jobs_updated_at ON batch_jobs(updated_at DESC)")
        # v0.11.0: observability columns. Added via ALTER so old DBs upgrade
        # transparently. `consecutive_poll_failures` enables zombie detection
        # (SRE audit HIGH): if a job's API calls keep failing — e.g. user
        # rotated the key mid-flight — we mark it JOB_STATE_FAILED after
        # MAX_POLL_FAILURES ticks instead of polling it forever.
        for col, coltype in [
            ("last_polled_at", "TEXT"),
            ("last_poll_error", "TEXT"),
            ("consecutive_poll_failures", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                self.conn.execute(f"ALTER TABLE batch_jobs ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_items (
                job_id TEXT NOT NULL,
                request_key TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (job_id, request_key)
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_items_job_id ON batch_items(job_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_items_file_path ON batch_items(file_path)")
        self.conn.commit()

    def save_result(
        self,
        file_path: str,
        result: dict,
        usage: dict | None = None,
        cost_usd: float | None = None,
        phash: str | None = None,
        duplicate_of: str | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        usage = usage or {}
        # Compute 16-bit prefix for the bucket index. Cheap (4-char parse).
        from modules.phash import prefix16
        phash_prefix = prefix16(phash) if phash else None
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO results
                   (file_path, status, result_json, input_tokens, output_tokens,
                    total_tokens, cost_usd, model, phash, phash_prefix,
                    duplicate_of, created_at, updated_at)
                   VALUES (?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_path,
                    json.dumps(result, ensure_ascii=False),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    usage.get("total_tokens"),
                    cost_usd,
                    usage.get("model"),
                    phash,
                    phash_prefix,
                    duplicate_of,
                    now,
                    now,
                ),
            )
            self.conn.commit()

    def find_similar(self, target_phash: str, threshold: int = 5,
                     limit: int = 5000) -> dict | None:
        """Find the closest completed result by pHash Hamming distance.

        Returns {file_path, phash, result (dict), distance} for the best
        match within `threshold` bits, resolved to the underlying master row
        (so dup chains don't compound). Returns None if nothing is close.

        v0.12.0 scale change: the v0.6.x implementation did
        `ORDER BY updated_at DESC LIMIT 5000` which meant any dedup candidate
        older than the last 5000 rows was invisible — fine at 10k photos,
        broken at 150k. This version uses the `phash_prefix` bucket index
        plus its single-bit-flip neighbours, which handles the common case
        at 150k scale. Falls back to the recent-rows scan for legacy rows
        without a prefix populated.

        Performance: the candidate scan selects only (file_path, phash) —
        the result_json column can be 1-3 KB per row and fetching it for
        every candidate amplifies I/O by ~100x on big DBs. We only load
        the master's JSON after we've picked a match.
        """
        from modules.phash import find_closest, prefix16, prefix_neighbours
        candidates: list[tuple[str, str]] = []
        target_prefix = prefix16(target_phash)
        if target_prefix is not None:
            buckets = prefix_neighbours(target_prefix, max_flips=1)
            placeholders = ",".join("?" * len(buckets))
            bucket_rows = self.conn.execute(
                f"""SELECT file_path, phash
                    FROM results
                    WHERE status = 'completed'
                      AND phash IS NOT NULL
                      AND phash_prefix IN ({placeholders})
                    LIMIT ?""",
                (*buckets, limit),
            ).fetchall()
            candidates = [(r["file_path"], r["phash"]) for r in bucket_rows]

        # Fallback: if bucket query returned nothing (e.g. legacy rows lack
        # phash_prefix because they were saved before v0.12.0), widen to
        # the historical recent-rows scan so we don't regress on old data.
        if not candidates:
            rows = self.conn.execute(
                """SELECT file_path, phash
                   FROM results
                   WHERE status = 'completed' AND phash IS NOT NULL
                     AND phash_prefix IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            candidates = [(r["file_path"], r["phash"]) for r in rows]

        match = find_closest(target_phash, candidates, threshold)
        if match is None:
            return None
        match_path, _match_hash, distance = match

        # Resolve to the underlying master. match_path itself might be a
        # duplicate row; follow duplicate_of until we hit a row with no
        # duplicate_of set. Cap hops defensively (chain should be depth 1).
        master_path = match_path
        row = None
        for _ in range(4):
            row = self.conn.execute(
                """SELECT file_path, phash, result_json, duplicate_of
                   FROM results WHERE file_path = ? AND status = 'completed'""",
                (master_path,),
            ).fetchone()
            if row is None:
                return None
            if not row["duplicate_of"]:
                break  # found the master
            master_path = row["duplicate_of"]
        else:
            # Chain too deep (4+ hops) — don't trust it, bail to a fresh
            # Gemini call rather than compound the corruption.
            log.warning(
                "dedup chain for %s > 4 hops deep — skipping dedup",
                target_phash,
            )
            return None

        return {
            "file_path": row["file_path"],
            "phash": row["phash"],
            "result": json.loads(row["result_json"]) if row["result_json"] else {},
            "distance": distance,
        }

    def get_result(self, file_path: str) -> dict | None:
        row = self.conn.execute(
            "SELECT result_json FROM results WHERE file_path = ? AND status = 'completed'",
            (file_path,),
        ).fetchone()
        if row and row["result_json"]:
            return json.loads(row["result_json"])
        return None

    def get_result_with_usage(self, file_path: str) -> dict | None:
        """Same as get_result but augments the dict with `_usage` + `_dedup`.

        `_usage` = {input_tokens, output_tokens, total_tokens, cost_usd, model}
          — absent for rows saved before the tokens migration (pre-v0.5.0).
        `_dedup` = {phash, duplicate_of}
          — present when either field is set. duplicate_of points to the
          master row's file_path when this photo was saved as a near-dup.
        """
        row = self.conn.execute(
            """SELECT result_json, input_tokens, output_tokens, total_tokens,
                      cost_usd, model, phash, duplicate_of
               FROM results WHERE file_path = ? AND status = 'completed'""",
            (file_path,),
        ).fetchone()
        if not row or not row["result_json"]:
            return None
        data = json.loads(row["result_json"])
        if row["total_tokens"] is not None or row["cost_usd"] is not None:
            data["_usage"] = {
                "input_tokens": row["input_tokens"] or 0,
                "output_tokens": row["output_tokens"] or 0,
                "total_tokens": row["total_tokens"] or 0,
                "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else 0.0,
                "model": row["model"] or "",
            }
        if row["phash"] or row["duplicate_of"]:
            data["_dedup"] = {
                "phash": row["phash"] or "",
                "duplicate_of": row["duplicate_of"] or "",
            }
        return data

    def is_processed(self, file_path: str) -> bool:
        row = self.conn.execute(
            "SELECT status FROM results WHERE file_path = ? AND status = 'completed'",
            (file_path,),
        ).fetchone()
        return row is not None

    def get_failed_results(self, folder: str | None = None, limit: int = 1000) -> list[dict]:
        """Return rows whose analysis failed. Used by the Monitor 'retry failed'
        UI to let the user re-enqueue without hunting through the DB.

        If `folder` is provided, only failures under that root are returned
        (matched against both raw and symlink-resolved prefix, same trick as
        `get_results_for_folder`)."""
        if folder:
            raw = str(Path(folder))
            resolved = str(Path(folder).resolve())
            rows = self.conn.execute(
                """SELECT file_path, error_message, updated_at
                   FROM results
                   WHERE status = 'failed'
                     AND (file_path LIKE ? OR file_path LIKE ?)
                   ORDER BY updated_at DESC LIMIT ?""",
                (raw + "%", resolved + "%", limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT file_path, error_message, updated_at
                   FROM results WHERE status = 'failed'
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_failed(self, file_paths: list[str]) -> int:
        """Remove `status='failed'` rows so they get re-processed on next run.
        Returns the number of rows affected. Used before re-enqueuing a
        retry so `skip_existing` logic re-picks them up."""
        if not file_paths:
            return 0
        placeholders = ",".join("?" * len(file_paths))
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                f"DELETE FROM results WHERE status = 'failed' AND file_path IN ({placeholders})",
                tuple(file_paths),
            )
            self.conn.commit()
            return cur.rowcount

    def mark_failed(self, file_path: str, error_message: str) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO results
                   (file_path, status, error_message, created_at, updated_at)
                   VALUES (?, 'failed', ?, ?, ?)""",
                (file_path, error_message, now, now),
            )
            self.conn.commit()

    def get_status(self, file_path: str) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM results WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return row["status"] if row else None

    def get_all_results(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT file_path, result_json FROM results WHERE status = 'completed'"
        ).fetchall()
        results = []
        for row in rows:
            data = json.loads(row["result_json"])
            data["file_path"] = row["file_path"]
            results.append(data)
        return results

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get the most recently updated results."""
        rows = self.conn.execute(
            "SELECT file_path, status, error_message, updated_at FROM results "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_today_stats(self) -> dict:
        """Get today's completed/failed counts, USD cost, and dedup savings."""
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'completed' AND updated_at LIKE ? THEN 1 ELSE 0 END) as completed, "
            "SUM(CASE WHEN status = 'failed' AND updated_at LIKE ? THEN 1 ELSE 0 END) as failed, "
            "COALESCE(SUM(CASE WHEN status = 'completed' AND updated_at LIKE ? THEN cost_usd ELSE 0 END), 0) as cost, "
            "SUM(CASE WHEN status = 'completed' AND updated_at LIKE ? AND duplicate_of IS NOT NULL THEN 1 ELSE 0 END) as dedup_saved "
            "FROM results",
            (today + "%", today + "%", today + "%", today + "%"),
        ).fetchone()
        return {
            "completed_today": row["completed"] or 0,
            "failed_today": row["failed"] or 0,
            "cost_usd_today": float(row["cost"] or 0.0),
            "dedup_saved_today": row["dedup_saved"] or 0,
        }

    def get_summary(self) -> dict:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM results GROUP BY status"
        ).fetchall()
        summary = {"completed": 0, "failed": 0, "total": 0}
        for row in rows:
            summary[row["status"]] = row["cnt"]
            summary["total"] += row["cnt"]
        return summary

    def update_result(self, file_path: str, updates: dict) -> None:
        existing = self.get_result(file_path)
        if existing is None:
            return
        existing.update(updates)
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE results SET result_json = ?, updated_at = ? WHERE file_path = ?",
                (json.dumps(existing, ensure_ascii=False), now, file_path),
            )
            self.conn.commit()

    def get_results_for_folder(self, folder: str) -> list[dict]:
        """Get completed results for photos within a specific folder.

        Matches both the caller-supplied folder and its symlink-resolved form,
        because save_result writes whatever path scan_photos yielded (often
        unresolved, e.g. /tmp/... on macOS) while a caller later may hand in
        the resolved form (/private/tmp/...). Union over both prefixes."""
        raw = str(Path(folder))
        resolved = str(Path(folder).resolve())
        rows = self.conn.execute(
            """SELECT file_path, result_json, input_tokens, output_tokens,
                      total_tokens, cost_usd, model, updated_at
               FROM results
               WHERE status = 'completed' AND (file_path LIKE ? OR file_path LIKE ?)""",
            (raw + "%", resolved + "%"),
        ).fetchall()
        results = []
        for row in rows:
            data = json.loads(row["result_json"])
            data["file_path"] = row["file_path"]
            data["updated_at"] = row["updated_at"]
            if row["total_tokens"] is not None or row["cost_usd"] is not None:
                data["_usage"] = {
                    "input_tokens": row["input_tokens"] or 0,
                    "output_tokens": row["output_tokens"] or 0,
                    "total_tokens": row["total_tokens"] or 0,
                    "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else 0.0,
                    "model": row["model"] or "",
                }
            results.append(data)
        return results

    # ---------------- Batch jobs (v0.9.0) ----------------
    def create_batch_job(
        self,
        job_id: str,
        folder: str,
        model: str,
        items: list[tuple[str, str]],
        input_file_id: str,
        payload_bytes: int,
        display_name: str = "",
        write_metadata: bool = False,
        image_max_size: int = 3072,
        initial_status: str = "JOB_STATE_PENDING",
    ) -> None:
        """Persist a newly-submitted batch job + its (key, file_path) items."""
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT INTO batch_jobs
                   (job_id, status, folder, model, photo_count, completed_count,
                    failed_count, input_file_id, payload_bytes, write_metadata,
                    image_max_size, display_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id, initial_status, folder, model, len(items),
                    input_file_id, payload_bytes, 1 if write_metadata else 0,
                    image_max_size, display_name, now, now,
                ),
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO batch_items (job_id, request_key, file_path, status) "
                "VALUES (?, ?, ?, 'pending')",
                [(job_id, k, p) for k, p in items],
            )
            self.conn.commit()

    def update_batch_job_status(
        self,
        job_id: str,
        status: str,
        output_file_id: str | None = None,
        error_message: str | None = None,
        completed_count: int | None = None,
        failed_count: int | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        ended = status in {
            "JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
            "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED",
            "JOB_STATE_PARTIALLY_SUCCEEDED",
        }
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT status, completed_count, failed_count FROM batch_jobs WHERE job_id = ?",
                (job_id,),
            )
            existing = cur.fetchone()
            if existing is None:
                return
            new_completed = completed_count if completed_count is not None else existing["completed_count"]
            new_failed = failed_count if failed_count is not None else existing["failed_count"]
            cur.execute(
                """UPDATE batch_jobs SET status = ?, updated_at = ?,
                          output_file_id = COALESCE(?, output_file_id),
                          error_message = COALESCE(?, error_message),
                          completed_count = ?, failed_count = ?,
                          completed_at = CASE WHEN ? AND completed_at IS NULL THEN ? ELSE completed_at END
                   WHERE job_id = ?""",
                (
                    status, now, output_file_id, error_message,
                    new_completed, new_failed,
                    1 if ended else 0, now if ended else None,
                    job_id,
                ),
            )
            self.conn.commit()

    def record_poll_attempt(
        self,
        job_id: str,
        error: str | None = None,
    ) -> int:
        """Update `last_polled_at` + increment/reset `consecutive_poll_failures`
        atomically. Returns the NEW failure count after this attempt.

        Used by the batch monitor for zombie detection (SRE HIGH). A job's
        poll loop may work fine for the first hour then start returning
        PERMISSION_DENIED when the user rotates the API key — without
        this counter the row would sit forever.
        """
        now = datetime.now().isoformat()
        with self._lock:
            cur = self.conn.cursor()
            if error is None:
                cur.execute(
                    """UPDATE batch_jobs SET last_polled_at = ?,
                              last_poll_error = NULL,
                              consecutive_poll_failures = 0,
                              updated_at = ?
                       WHERE job_id = ?""",
                    (now, now, job_id),
                )
                self.conn.commit()
                return 0
            cur.execute(
                """UPDATE batch_jobs SET last_polled_at = ?,
                          last_poll_error = ?,
                          consecutive_poll_failures = consecutive_poll_failures + 1,
                          updated_at = ?
                   WHERE job_id = ?""",
                (now, error[:500], now, job_id),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT consecutive_poll_failures FROM batch_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            return int(row["consecutive_poll_failures"]) if row else 0

    def update_batch_job_counts(
        self,
        job_id: str,
        completed_count: int,
        failed_count: int,
    ) -> None:
        """Update per-item counters WITHOUT touching status or completed_at.

        `update_batch_job_status` always writes the status column; calling it
        to report counts races with a just-written terminal state (e.g. the
        poll loop wrote SUCCEEDED, then the materialise step ran counts with
        a stale `status` argument and regressed the row back to PENDING).
        Keep counter updates isolated from state transitions."""
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """UPDATE batch_jobs
                   SET completed_count = ?, failed_count = ?, updated_at = ?
                   WHERE job_id = ?""",
                (completed_count, failed_count, now, job_id),
            )
            self.conn.commit()

    def get_batch_job(self, job_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM batch_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_batch_jobs(self, active_only: bool = False, limit: int = 100) -> list[dict]:
        """List batch jobs, newest first. `active_only` excludes ended states."""
        ended = (
            "JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
            "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED",
            "JOB_STATE_PARTIALLY_SUCCEEDED",
        )
        if active_only:
            placeholders = ",".join("?" * len(ended))
            query = (
                f"SELECT * FROM batch_jobs WHERE status NOT IN ({placeholders}) "
                "ORDER BY updated_at DESC LIMIT ?"
            )
            params = (*ended, limit)
        else:
            query = "SELECT * FROM batch_jobs ORDER BY updated_at DESC LIMIT ?"
            params = (limit,)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_batch_items(self, job_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT request_key, file_path, status FROM batch_items WHERE job_id = ?",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_batch_item(self, job_id: str, request_key: str, status: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE batch_items SET status = ? WHERE job_id = ? AND request_key = ?",
                (status, job_id, request_key),
            )
            self.conn.commit()

    def delete_batch_job(self, job_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM batch_items WHERE job_id = ?", (job_id,))
            self.conn.execute("DELETE FROM batch_jobs WHERE job_id = ?", (job_id,))
            self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
