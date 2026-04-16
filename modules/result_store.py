"""modules/result_store.py — SQLite result storage with checkpoint/resume"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


class ResultStore:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_config_dir() / "results.db"
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

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
        self.conn.commit()

    def save_result(self, file_path: str, result: dict) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO results
                   (file_path, status, result_json, created_at, updated_at)
                   VALUES (?, 'completed', ?, ?, ?)""",
                (file_path, json.dumps(result, ensure_ascii=False), now, now),
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
        """Get today's completed and failed counts."""
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'completed' AND updated_at LIKE ? THEN 1 ELSE 0 END) as completed, "
            "SUM(CASE WHEN status = 'failed' AND updated_at LIKE ? THEN 1 ELSE 0 END) as failed "
            "FROM results",
            (today + "%", today + "%"),
        ).fetchone()
        return {
            "completed_today": row["completed"] or 0,
            "failed_today": row["failed"] or 0,
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
        """Get completed results for photos within a specific folder."""
        folder_prefix = str(Path(folder).resolve())
        rows = self.conn.execute(
            "SELECT file_path, result_json FROM results WHERE status = 'completed' AND file_path LIKE ?",
            (folder_prefix + "%",),
        ).fetchall()
        results = []
        for row in rows:
            data = json.loads(row["result_json"])
            data["file_path"] = row["file_path"]
            results.append(data)
        return results

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
