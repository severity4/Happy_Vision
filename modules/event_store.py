"""modules/event_store.py — Structured telemetry/event storage"""

import json
import sqlite3
import threading
import tempfile
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir, load_config


class EventStore:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_config_dir() / "events.db"
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

    def _init_db(self) -> None:
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                machine_name TEXT,
                tester_name TEXT,
                app_version TEXT,
                folder TEXT,
                file_path TEXT,
                details_json TEXT
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)"
        )
        self.conn.commit()

    def add_event(
        self,
        event_type: str,
        *,
        folder: str | None = None,
        file_path: str | None = None,
        details: dict | None = None,
    ) -> None:
        config = load_config()
        now = datetime.now().isoformat()
        with self._lock:
            self.conn.execute(
                """INSERT INTO events
                   (created_at, event_type, machine_name, tester_name,
                    app_version, folder, file_path, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now,
                    event_type,
                    config.get("machine_name", ""),
                    config.get("tester_name", ""),
                    config.get("app_version", ""),
                    folder or "",
                    file_path or "",
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            self.conn.commit()

    def get_recent(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["details"] = json.loads(event.pop("details_json") or "{}")
            events.append(event)
        return events

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
