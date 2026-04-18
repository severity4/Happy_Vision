"""modules/result_store.py — SQLite result storage with checkpoint/resume"""

import json
import sqlite3
import threading
import tempfile
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


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
        except sqlite3.Error:
            fallback_dir = Path(tempfile.gettempdir()) / "happy-vision"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = fallback_dir / Path(db_path).name
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_db()

    def _resolve_db_path(self, path: Path) -> Path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            test_conn = sqlite3.connect(str(path))
            test_conn.close()
            return path
        except sqlite3.Error:
            fallback_dir = Path(tempfile.gettempdir()) / "happy-vision"
            fallback_dir.mkdir(parents=True, exist_ok=True)
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
        ]:
            try:
                self.conn.execute(f"ALTER TABLE results ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    def save_result(
        self,
        file_path: str,
        result: dict,
        usage: dict | None = None,
        cost_usd: float | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        usage = usage or {}
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO results
                   (file_path, status, result_json, input_tokens, output_tokens,
                    total_tokens, cost_usd, model, created_at, updated_at)
                   VALUES (?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_path,
                    json.dumps(result, ensure_ascii=False),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    usage.get("total_tokens"),
                    cost_usd,
                    usage.get("model"),
                    now,
                    now,
                ),
            )
            self.conn.commit()

    def get_result(self, file_path: str) -> dict | None:
        row = self.conn.execute(
            "SELECT result_json FROM results WHERE file_path = ? AND status = 'completed'",
            (file_path,),
        ).fetchone()
        if row and row["result_json"]:
            return json.loads(row["result_json"])
        return None

    def get_result_with_usage(self, file_path: str) -> dict | None:
        """Same as get_result but augments the dict with a `_usage` sub-object.

        `_usage` = {input_tokens, output_tokens, total_tokens, cost_usd, model}
        Absent for rows saved before the tokens migration (pre-v0.5.0).
        """
        row = self.conn.execute(
            """SELECT result_json, input_tokens, output_tokens, total_tokens,
                      cost_usd, model
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
        """Get today's completed/failed counts and total USD cost."""
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'completed' AND updated_at LIKE ? THEN 1 ELSE 0 END) as completed, "
            "SUM(CASE WHEN status = 'failed' AND updated_at LIKE ? THEN 1 ELSE 0 END) as failed, "
            "COALESCE(SUM(CASE WHEN status = 'completed' AND updated_at LIKE ? THEN cost_usd ELSE 0 END), 0) as cost "
            "FROM results",
            (today + "%", today + "%", today + "%"),
        ).fetchone()
        return {
            "completed_today": row["completed"] or 0,
            "failed_today": row["failed"] or 0,
            "cost_usd_today": float(row["cost"] or 0.0),
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
