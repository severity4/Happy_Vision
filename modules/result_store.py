"""modules/result_store.py — SQLite result storage with checkpoint/resume"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir

log = logging.getLogger(__name__)


class ResultStore:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_config_dir() / "results.db"
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
        except sqlite3.Error as e:
            # Same durable fallback as __init__ — never /tmp.
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
        ]:
            try:
                self.conn.execute(f"ALTER TABLE results ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_phash ON results(phash)")
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
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO results
                   (file_path, status, result_json, input_tokens, output_tokens,
                    total_tokens, cost_usd, model, phash, duplicate_of,
                    created_at, updated_at)
                   VALUES (?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_path,
                    json.dumps(result, ensure_ascii=False),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    usage.get("total_tokens"),
                    cost_usd,
                    usage.get("model"),
                    phash,
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

        Performance: the candidate scan selects only (file_path, phash) —
        the result_json column can be 1-3 KB per row and fetching it for
        every candidate amplifies I/O by ~100x on big DBs. We only load
        the master's JSON after we've picked a match.
        """
        from modules.phash import find_closest
        rows = self.conn.execute(
            """SELECT file_path, phash
               FROM results
               WHERE status = 'completed' AND phash IS NOT NULL
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

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
