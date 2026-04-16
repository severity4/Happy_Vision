"""modules/result_store.py — SQLite result storage with checkpoint/resume"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


class ResultStore:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_config_dir() / "results.db"
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
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
        self.conn.commit()

    def save_result(self, file_path: str, result: dict) -> None:
        now = datetime.now().isoformat()
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
        self.conn.execute(
            "UPDATE results SET result_json = ?, updated_at = ? WHERE file_path = ?",
            (json.dumps(existing, ensure_ascii=False), now, file_path),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
