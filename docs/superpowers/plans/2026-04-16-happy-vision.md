# Happy Vision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI photo tagger that batch-analyzes JPGs via Gemini API, writes IPTC/XMP metadata, and exports reports — with both CLI and Web UI.

**Architecture:** Python Flask backend with Gemini API for AI analysis, pyexiftool for metadata write-back, SQLite for result persistence and checkpoint/resume. Vue 3 frontend with SSE progress updates. CLI via click.

**Tech Stack:** Python 3.10+, Flask, Vue 3 + Vite, Google Gemini API (genai SDK), pyexiftool, SQLite, click, PyInstaller

---

## File Map

```
Happy_Vision/
├── modules/
│   ├── config.py            # Config load/save (~/.happy-vision/config.json)
│   ├── gemini_vision.py     # Gemini API: analyze single photo, structured output
│   ├── result_store.py      # SQLite: store results, checkpoint/resume
│   ├── metadata_writer.py   # pyexiftool: read/write IPTC/XMP
│   ├── report_generator.py  # CSV/JSON export
│   ├── pipeline.py          # Orchestrator: scan folder, run analysis, coordinate modules
│   └── logger.py            # Logging setup (~/.happy-vision/logs/)
├── api/
│   ├── __init__.py
│   ├── analysis.py          # Blueprint: start/pause/cancel analysis, SSE progress
│   ├── results.py           # Blueprint: query results, edit fields, write metadata
│   ├── settings.py          # Blueprint: config CRUD, API key management
│   └── export.py            # Blueprint: CSV/JSON download
├── frontend/                # Vue 3 + Vite (port 5176)
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.js
│   │   ├── router.js
│   │   ├── stores/
│   │   │   ├── analysis.js  # Pinia: analysis state, SSE connection
│   │   │   └── settings.js  # Pinia: settings state
│   │   ├── views/
│   │   │   ├── ImportView.vue
│   │   │   ├── ProgressView.vue
│   │   │   ├── ResultsView.vue
│   │   │   └── SettingsView.vue
│   │   └── components/
│   │       ├── PhotoGrid.vue
│   │       ├── PhotoDetail.vue
│   │       └── ProgressBar.vue
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── tests/
│   ├── test_config.py
│   ├── test_gemini_vision.py
│   ├── test_result_store.py
│   ├── test_metadata_writer.py
│   ├── test_report_generator.py
│   ├── test_pipeline.py
│   └── test_cli.py
├── cli.py                   # CLI entry point (click)
├── web_ui.py                # Flask entry point
├── Makefile
├── setup.sh
├── requirements.txt
├── ruff.toml
├── CLAUDE.md
└── .gitignore
```

---

### Task 0: Project Scaffolding + PyInstaller Spike

**Files:**
- Create: `requirements.txt`, `Makefile`, `setup.sh`, `ruff.toml`, `.gitignore`, `CLAUDE.md`, `web_ui.py`, `cli.py`, `modules/__init__.py`, `api/__init__.py`, `tests/__init__.py`
- Create: `spike_pyinstaller.py` (temporary spike script)

This task validates the highest-risk item first: can we package a Python app with pyexiftool into a macOS .app?

- [ ] **Step 0.1: Create .gitignore**

```gitignore
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
*.spec
.venv/
node_modules/
frontend/dist/
.env
.DS_Store
```

- [ ] **Step 0.2: Create requirements.txt**

```txt
flask>=3.1
google-genai>=1.0
pyexiftool>=0.5
click>=8.1
tqdm>=4.66
```

- [ ] **Step 0.3: Create ruff.toml**

```toml
line-length = 120
target-version = "py310"

[lint]
select = ["E", "F", "W"]
ignore = ["E501", "F401"]
```

- [ ] **Step 0.4: Create Makefile**

```makefile
.PHONY: dev build serve lint test verify help install app

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## Dev mode (Flask 8081 + Vite 5176)
	@echo "Starting Flask (8081) + Vite (5176)..."
	@python3 web_ui.py &
	@cd frontend && npm run dev

serve: ## Production mode (Flask only, serves Vue build)
	python3 web_ui.py

build: ## Build Vue frontend
	cd frontend && npm run build

lint: ## Lint Python
	ruff check modules api tests web_ui.py cli.py

test: ## Run pytest
	pytest -q

verify: ## Pre-merge verification
	ruff check modules api tests web_ui.py cli.py
	pytest -q

install: ## Install all dependencies
	pip install -r requirements.txt
	@if [ -d frontend ]; then cd frontend && npm install; fi

app: ## Build macOS .app
	python3 build_app.py
```

- [ ] **Step 0.5: Create setup.sh**

```bash
#!/bin/bash
set -e
echo "=== Happy Vision Setup ==="

# Check Python
python3 --version || { echo "Python 3.10+ required"; exit 1; }

# Check exiftool
if ! command -v exiftool &> /dev/null; then
    echo "Installing exiftool..."
    brew install exiftool
fi

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install Python deps
pip install -r requirements.txt

echo "=== Setup complete ==="
echo "Activate venv: source .venv/bin/activate"
```

- [ ] **Step 0.6: Create minimal web_ui.py**

```python
"""Happy Vision — Web UI entry point"""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)


@app.route("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=True)
```

- [ ] **Step 0.7: Create minimal cli.py**

```python
"""Happy Vision — CLI entry point"""

import click


@click.command()
@click.argument("folder", type=click.Path(exists=True))
@click.option("--model", default="lite", type=click.Choice(["lite", "flash"]))
@click.option("--concurrency", default=5, type=int)
@click.option("--output", default=".", type=click.Path())
@click.option("--format", "fmt", default="csv", type=click.Choice(["csv", "json", "csv,json"]))
@click.option("--write-metadata", is_flag=True, default=False)
@click.option("--skip-existing", is_flag=True, default=False)
def main(folder, model, concurrency, output, fmt, write_metadata, skip_existing):
    """Analyze photos in FOLDER with Gemini AI."""
    click.echo(f"Happy Vision — analyzing {folder}")
    click.echo(f"Model: {model}, Concurrency: {concurrency}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 0.8: Create empty __init__.py files**

Create `modules/__init__.py`, `api/__init__.py`, `tests/__init__.py` as empty files.

- [ ] **Step 0.9: Create CLAUDE.md**

```markdown
# CLAUDE.md

## Project Overview

映奧創意 (INOUT Creative) 內部工具：AI 平面照片標記系統。透過 Google Gemini API 分析 JPG 照片，產生英文描述、關鍵字、分類等 metadata，寫回 IPTC/XMP 欄位，並匯出 CSV/JSON 報告。

**語言：** Python 3.10+（後端）+ Vue 3（前端）

## Commands

\```bash
# Install
./setup.sh
make install

# Dev mode (Flask 8081 + Vite 5176)
make dev

# Lint
make lint

# Test
make test

# Pre-merge verify
make verify

# CLI
python3 cli.py /path/to/photos --model lite --write-metadata

# Build macOS .app
make app
\```

## Architecture

Flask backend (`web_ui.py`) with blueprints in `api/`. Core logic in `modules/`. Vue 3 frontend in `frontend/`. CLI in `cli.py`.

**Modules:** `config.py` (settings), `gemini_vision.py` (Gemini API), `result_store.py` (SQLite), `metadata_writer.py` (exiftool), `report_generator.py` (CSV/JSON), `pipeline.py` (orchestrator), `logger.py` (logging).

**API Blueprints:** `analysis.py` (start/pause/cancel + SSE), `results.py` (query/edit), `settings.py` (config), `export.py` (download reports).
```

- [ ] **Step 0.10: PyInstaller spike — create spike script**

```python
"""spike_pyinstaller.py — Verify PyInstaller can bundle Flask + pyexiftool"""

import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    print("=== PyInstaller Packaging Spike ===")

    # 1. Check exiftool is available
    try:
        result = subprocess.run(["exiftool", "-ver"], capture_output=True, text=True)
        exiftool_path = subprocess.run(["which", "exiftool"], capture_output=True, text=True).stdout.strip()
        print(f"exiftool {result.stdout.strip()} at {exiftool_path}")
    except FileNotFoundError:
        print("ERROR: exiftool not found")
        sys.exit(1)

    # 2. Try PyInstaller build
    try:
        import PyInstaller.__main__
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # 3. Build minimal app
    print("Building minimal .app with PyInstaller...")
    subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", "HappyVision",
        f"--add-binary={exiftool_path}:.",
        "--noconfirm",
        "web_ui.py",
    ], check=True)

    # 4. Verify the built app can start
    app_path = Path("dist/HappyVision/HappyVision")
    if app_path.exists():
        print(f"SUCCESS: Built app at {app_path}")
        print("Try running: ./dist/HappyVision/HappyVision")
    else:
        print("WARNING: App binary not found at expected path, check dist/ directory")


if __name__ == "__main__":
    main()
```

- [ ] **Step 0.11: Run the spike**

```bash
chmod +x setup.sh
./setup.sh
source .venv/bin/activate
pip install pyinstaller
python3 spike_pyinstaller.py
```

Expected: `dist/HappyVision/` directory created with bundled app. If this fails, investigate and resolve before continuing. Document findings in a comment in the spike script.

- [ ] **Step 0.12: Commit scaffolding**

```bash
git add .gitignore requirements.txt ruff.toml Makefile setup.sh web_ui.py cli.py modules/__init__.py api/__init__.py tests/__init__.py CLAUDE.md spike_pyinstaller.py
git commit -m "chore: project scaffolding + PyInstaller spike"
```

---

### Task 1: Config Module

**Files:**
- Create: `modules/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1.1: Write failing tests**

```python
"""tests/test_config.py"""

import json
from pathlib import Path

from modules.config import load_config, save_config, get_config_dir, DEFAULT_CONFIG


def test_default_config_has_required_keys():
    assert "gemini_api_key" in DEFAULT_CONFIG
    assert "model" in DEFAULT_CONFIG
    assert "concurrency" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["model"] == "lite"
    assert DEFAULT_CONFIG["concurrency"] == 5


def test_get_config_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config_dir = get_config_dir()
    assert config_dir.exists()
    assert config_dir.name == ".happy-vision"


def test_load_config_returns_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config = load_config()
    assert config["model"] == "lite"
    assert config["gemini_api_key"] == ""


def test_save_and_load_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config = load_config()
    config["gemini_api_key"] = "test-key-123"
    config["model"] = "flash"
    save_config(config)

    loaded = load_config()
    assert loaded["gemini_api_key"] == "test-key-123"
    assert loaded["model"] == "flash"


def test_load_config_merges_new_defaults(tmp_path, monkeypatch):
    """If config file is missing a key added in a newer version, load_config fills it in."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config_dir = tmp_path / ".happy-vision"
    config_dir.mkdir(parents=True)
    # Write a config missing the 'concurrency' key
    (config_dir / "config.json").write_text(json.dumps({"gemini_api_key": "k", "model": "lite"}))

    config = load_config()
    assert config["concurrency"] == 5  # filled from defaults
    assert config["gemini_api_key"] == "k"  # preserved from file
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'modules.config'`

- [ ] **Step 1.3: Implement config module**

```python
"""modules/config.py — Config load/save for Happy Vision"""

import json
from pathlib import Path
import os

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "model": "lite",
    "concurrency": 5,
    "write_metadata": False,
    "skip_existing": False,
}


def get_config_dir() -> Path:
    """Return (and create) the Happy Vision config directory."""
    base = os.environ.get("HAPPY_VISION_HOME", str(Path.home() / ".happy-vision"))
    config_dir = Path(base)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_config() -> dict:
    """Load config from disk, merging with defaults for any missing keys."""
    config_path = get_config_dir() / "config.json"
    config = dict(DEFAULT_CONFIG)
    if config_path.exists():
        with open(config_path) as f:
            stored = json.load(f)
        config.update(stored)
    return config


def save_config(config: dict) -> None:
    """Save config to disk."""
    config_path = get_config_dir() / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 1.5: Lint and commit**

```bash
ruff check modules/config.py tests/test_config.py
git add modules/config.py tests/test_config.py
git commit -m "feat: add config module with load/save/defaults"
```

---

### Task 2: Logger Module

**Files:**
- Create: `modules/logger.py`

- [ ] **Step 2.1: Implement logger**

```python
"""modules/logger.py — Logging setup for Happy Vision"""

import logging
from datetime import datetime
from pathlib import Path

from modules.config import get_config_dir


def setup_logger(name: str = "happy_vision") -> logging.Logger:
    """Set up a logger that writes to ~/.happy-vision/logs/ and stdout."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console)

    # File handler
    log_dir = get_config_dir() / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{datetime.now():%Y-%m-%d}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    return logger
```

- [ ] **Step 2.2: Smoke test**

```bash
python3 -c "from modules.logger import setup_logger; log = setup_logger(); log.info('Hello Happy Vision')"
```

Expected: `INFO: Hello Happy Vision` printed to console, log file created in `~/.happy-vision/logs/`.

- [ ] **Step 2.3: Commit**

```bash
ruff check modules/logger.py
git add modules/logger.py
git commit -m "feat: add logger module"
```

---

### Task 3: Result Store (SQLite)

**Files:**
- Create: `modules/result_store.py`
- Create: `tests/test_result_store.py`

- [ ] **Step 3.1: Write failing tests**

```python
"""tests/test_result_store.py"""

import json
from pathlib import Path

from modules.result_store import ResultStore


def test_init_creates_db(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    assert (tmp_path / "test.db").exists()
    store.close()


def test_save_and_get_result(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    result = {
        "title": "Speaker on stage",
        "description": "A speaker addresses the audience.",
        "keywords": ["conference", "speaker"],
        "category": "ceremony",
        "subcategory": "keynote",
        "scene_type": "indoor",
        "mood": "formal",
        "people_count": 50,
        "identified_people": ["Jensen Huang"],
        "ocr_text": ["INOUT"],
    }
    store.save_result("/photos/IMG_001.jpg", result)

    loaded = store.get_result("/photos/IMG_001.jpg")
    assert loaded["title"] == "Speaker on stage"
    assert loaded["keywords"] == ["conference", "speaker"]
    assert loaded["identified_people"] == ["Jensen Huang"]
    store.close()


def test_get_result_returns_none_for_missing(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    assert store.get_result("/no/such/file.jpg") is None
    store.close()


def test_is_processed(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    assert not store.is_processed("/photos/IMG_001.jpg")
    store.save_result("/photos/IMG_001.jpg", {"title": "Test"})
    assert store.is_processed("/photos/IMG_001.jpg")
    store.close()


def test_mark_failed(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.mark_failed("/photos/IMG_002.jpg", "API timeout")
    status = store.get_status("/photos/IMG_002.jpg")
    assert status == "failed"
    assert not store.is_processed("/photos/IMG_002.jpg")
    store.close()


def test_get_all_results(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/IMG_001.jpg", {"title": "A"})
    store.save_result("/photos/IMG_002.jpg", {"title": "B"})
    store.mark_failed("/photos/IMG_003.jpg", "error")

    results = store.get_all_results()
    assert len(results) == 2
    paths = [r["file_path"] for r in results]
    assert "/photos/IMG_001.jpg" in paths
    assert "/photos/IMG_002.jpg" in paths
    store.close()


def test_get_session_summary(tmp_path):
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/IMG_001.jpg", {"title": "A"})
    store.save_result("/photos/IMG_002.jpg", {"title": "B"})
    store.mark_failed("/photos/IMG_003.jpg", "error")

    summary = store.get_summary()
    assert summary["completed"] == 2
    assert summary["failed"] == 1
    assert summary["total"] == 3
    store.close()


def test_update_result(tmp_path):
    """User edits a field in the UI before writing metadata."""
    store = ResultStore(tmp_path / "test.db")
    store.save_result("/photos/IMG_001.jpg", {"title": "Old", "keywords": ["a"]})
    store.update_result("/photos/IMG_001.jpg", {"title": "New Title"})
    loaded = store.get_result("/photos/IMG_001.jpg")
    assert loaded["title"] == "New Title"
    assert loaded["keywords"] == ["a"]  # unchanged
    store.close()
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
pytest tests/test_result_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'modules.result_store'`

- [ ] **Step 3.3: Implement result_store**

```python
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
pytest tests/test_result_store.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 3.5: Lint and commit**

```bash
ruff check modules/result_store.py tests/test_result_store.py
git add modules/result_store.py tests/test_result_store.py
git commit -m "feat: add SQLite result store with checkpoint/resume"
```

---

### Task 4: Gemini Vision Module

**Files:**
- Create: `modules/gemini_vision.py`
- Create: `tests/test_gemini_vision.py`

- [ ] **Step 4.1: Write failing tests**

```python
"""tests/test_gemini_vision.py"""

import base64
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.gemini_vision import (
    build_prompt,
    parse_response,
    analyze_photo,
    ANALYSIS_SCHEMA,
    MODEL_MAP,
)


def test_model_map_has_lite_and_flash():
    assert "lite" in MODEL_MAP
    assert "flash" in MODEL_MAP
    assert "gemini" in MODEL_MAP["lite"]
    assert "gemini" in MODEL_MAP["flash"]


def test_analysis_schema_has_required_fields():
    required = ["title", "description", "keywords", "category", "subcategory",
                 "scene_type", "mood", "people_count", "identified_people", "ocr_text"]
    for field in required:
        assert field in ANALYSIS_SCHEMA["properties"]


def test_build_prompt_returns_string():
    prompt = build_prompt()
    assert isinstance(prompt, str)
    assert "title" in prompt
    assert "keywords" in prompt
    assert "public figure" in prompt.lower() or "identified_people" in prompt


def test_parse_response_valid_json():
    raw = json.dumps({
        "title": "Test",
        "description": "A test photo",
        "keywords": ["test"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    })
    result = parse_response(raw)
    assert result["title"] == "Test"
    assert result["keywords"] == ["test"]


def test_parse_response_handles_missing_fields():
    raw = json.dumps({"title": "Only title"})
    result = parse_response(raw)
    assert result["title"] == "Only title"
    assert result["keywords"] == []
    assert result["identified_people"] == []


def test_parse_response_handles_garbage():
    result = parse_response("not json at all")
    assert result is None


def test_analyze_photo_calls_gemini(tmp_path):
    # Create a tiny test JPG (1x1 pixel)
    img_path = tmp_path / "test.jpg"
    # Minimal valid JPEG: SOI + APP0 + SOF + SOS + EOI
    img_path.write_bytes(
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
        b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
        b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342'
        b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
        b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b'
        b'\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7\xa8\xa4'
        b'\xff\xd9'
    )

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "Test photo",
        "description": "A test",
        "keywords": ["test"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    })

    with patch("modules.gemini_vision.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.return_value = mock_response

        result = analyze_photo(str(img_path), api_key="fake-key", model="lite")

    assert result["title"] == "Test photo"
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
pytest tests/test_gemini_vision.py -v
```

Expected: `ModuleNotFoundError: No module named 'modules.gemini_vision'`

- [ ] **Step 4.3: Implement gemini_vision**

```python
"""modules/gemini_vision.py — Gemini API photo analysis"""

import base64
import json
import time
from pathlib import Path

from google import genai
from google.genai import types

from modules.logger import setup_logger

log = setup_logger("gemini_vision")

MODEL_MAP = {
    "lite": "gemini-2.0-flash-lite",
    "flash": "gemini-2.5-flash-preview-05-20",
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short English title describing the main subject/action"},
        "description": {"type": "string", "description": "Detailed English description of the photo"},
        "keywords": {"type": "array", "items": {"type": "string"}, "description": "English keywords/tags"},
        "category": {"type": "string", "description": "Main category (e.g. ceremony, reception, panel, performance, networking, portrait, venue, branding)"},
        "subcategory": {"type": "string", "description": "Subcategory within the main category"},
        "scene_type": {"type": "string", "enum": ["indoor", "outdoor", "studio"]},
        "mood": {"type": "string", "description": "Overall mood/atmosphere (e.g. formal, casual, energetic, intimate)"},
        "people_count": {"type": "integer", "description": "Approximate number of people visible"},
        "identified_people": {"type": "array", "items": {"type": "string"}, "description": "Names of recognized public figures"},
        "ocr_text": {"type": "array", "items": {"type": "string"}, "description": "Text visible in the photo (signs, banners, slides)"},
    },
    "required": ["title", "description", "keywords", "category", "scene_type", "mood", "people_count"],
}


def build_prompt() -> str:
    return """Analyze this event photo and provide structured metadata in English.

You are a professional event photographer's assistant. Describe what you see accurately and concisely.

Requirements:
- title: One concise English sentence describing the main subject/action
- description: 2-3 English sentences with specific details (setting, people, actions, lighting)
- keywords: 5-15 relevant English tags for searchability
- category: Main event category (ceremony, reception, panel, performance, networking, portrait, venue, branding)
- subcategory: More specific type within the category
- scene_type: indoor, outdoor, or studio
- mood: Overall atmosphere
- people_count: Approximate number of people visible
- identified_people: If you recognize any public figures (celebrities, business leaders, politicians), list their full names. Only include people you are confident about. If you cannot identify anyone or are unsure, return an empty array.
- ocr_text: Any readable text in the photo (signs, banners, projected slides, name tags)

Respond ONLY with valid JSON matching the required schema."""


def parse_response(raw_text: str) -> dict | None:
    """Parse Gemini response, filling in defaults for missing fields."""
    try:
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return None

    defaults = {
        "title": "",
        "description": "",
        "keywords": [],
        "category": "",
        "subcategory": "",
        "scene_type": "",
        "mood": "",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }
    for key, default in defaults.items():
        if key not in data:
            data[key] = default
    return data


def analyze_photo(
    photo_path: str,
    api_key: str,
    model: str = "lite",
    max_retries: int = 3,
) -> dict | None:
    """Analyze a single photo with Gemini API. Returns parsed result or None on failure."""
    model_name = MODEL_MAP.get(model, MODEL_MAP["lite"])
    photo_bytes = Path(photo_path).read_bytes()
    prompt = build_prompt()

    client = genai.Client(api_key=api_key)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg"),
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ANALYSIS_SCHEMA,
                ),
            )
            result = parse_response(response.text)
            if result:
                log.info("Analyzed %s: %s", Path(photo_path).name, result.get("title", ""))
                return result
            log.warning("Failed to parse response for %s", photo_path)
            return None

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "500" in error_str or "503" in error_str:
                wait = 2 ** attempt
                log.warning("API error for %s (attempt %d/%d), retrying in %ds: %s",
                            photo_path, attempt + 1, max_retries, wait, error_str)
                time.sleep(wait)
                continue
            log.error("API error for %s: %s", photo_path, error_str)
            return None

    log.error("All retries exhausted for %s", photo_path)
    return None
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
pytest tests/test_gemini_vision.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 4.5: Lint and commit**

```bash
ruff check modules/gemini_vision.py tests/test_gemini_vision.py
git add modules/gemini_vision.py tests/test_gemini_vision.py
git commit -m "feat: add Gemini Vision module with structured output and retry"
```

---

### Task 5: Metadata Writer Module

**Files:**
- Create: `modules/metadata_writer.py`
- Create: `tests/test_metadata_writer.py`

- [ ] **Step 5.1: Write failing tests**

```python
"""tests/test_metadata_writer.py"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.metadata_writer import (
    build_exiftool_args,
    write_metadata,
    read_metadata,
    has_happy_vision_tag,
)


def test_build_exiftool_args_basic():
    result = {
        "title": "Speaker on stage",
        "description": "A keynote speaker addresses the audience.",
        "keywords": ["conference", "keynote"],
        "category": "ceremony",
        "mood": "formal",
        "ocr_text": ["INOUT Creative"],
        "identified_people": ["Jensen Huang"],
    }
    args = build_exiftool_args(result)
    assert "-IPTC:Headline=Speaker on stage" in args
    assert "-IPTC:Caption-Abstract=A keynote speaker addresses the audience." in args
    assert "-IPTC:Keywords=conference" in args
    assert "-IPTC:Keywords=keynote" in args
    assert "-IPTC:Keywords=Jensen Huang" in args
    assert "-XMP:Category=ceremony" in args
    assert "-XMP:Scene=formal" in args
    assert any("INOUT Creative" in a for a in args)
    # Happy Vision processed tag
    assert any("HappyVision" in a for a in args)


def test_build_exiftool_args_empty_fields():
    result = {
        "title": "",
        "description": "",
        "keywords": [],
        "category": "",
        "mood": "",
        "ocr_text": [],
        "identified_people": [],
    }
    args = build_exiftool_args(result)
    # Should still have the HappyVision tag
    assert any("HappyVision" in a for a in args)


def test_build_exiftool_args_people_added_to_keywords():
    result = {
        "title": "CEO speech",
        "description": "CEO gives speech",
        "keywords": ["speech"],
        "category": "ceremony",
        "mood": "formal",
        "ocr_text": [],
        "identified_people": ["Jensen Huang", "Lisa Su"],
    }
    args = build_exiftool_args(result)
    keyword_args = [a for a in args if a.startswith("-IPTC:Keywords=")]
    keyword_values = [a.split("=", 1)[1] for a in keyword_args]
    assert "Jensen Huang" in keyword_values
    assert "Lisa Su" in keyword_values
    assert "speech" in keyword_values
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
pytest tests/test_metadata_writer.py -v
```

Expected: `ModuleNotFoundError: No module named 'modules.metadata_writer'`

- [ ] **Step 5.3: Implement metadata_writer**

```python
"""modules/metadata_writer.py — IPTC/XMP metadata read/write via exiftool"""

import json
import subprocess
from pathlib import Path

from modules.logger import setup_logger

log = setup_logger("metadata_writer")

HAPPY_VISION_TAG = "-XMP-xmp:Description=HappyVisionProcessed"


def build_exiftool_args(result: dict) -> list[str]:
    """Build exiftool CLI arguments from an analysis result dict."""
    args = []

    if result.get("title"):
        args.append(f"-IPTC:Headline={result['title']}")
        args.append(f"-XMP:Title={result['title']}")

    if result.get("description"):
        args.append(f"-IPTC:Caption-Abstract={result['description']}")
        args.append(f"-XMP:Description={result['description']}")

    # Keywords = AI keywords + identified people
    all_keywords = list(result.get("keywords", []))
    for person in result.get("identified_people", []):
        if person not in all_keywords:
            all_keywords.append(person)
    for kw in all_keywords:
        args.append(f"-IPTC:Keywords={kw}")
        args.append(f"-XMP:Subject={kw}")

    if result.get("category"):
        args.append(f"-XMP:Category={result['category']}")

    if result.get("mood"):
        args.append(f"-XMP:Scene={result['mood']}")

    if result.get("ocr_text"):
        ocr_combined = " | ".join(result["ocr_text"])
        args.append(f"-XMP:Comment={ocr_combined}")

    # Mark as processed by Happy Vision
    args.append("-XMP-xmp:Instructions=HappyVisionProcessed")

    return args


def write_metadata(photo_path: str, result: dict, backup: bool = True) -> bool:
    """Write analysis result as IPTC/XMP metadata into a photo file."""
    path = Path(photo_path)
    if not path.exists():
        log.error("File not found: %s", photo_path)
        return False

    args = build_exiftool_args(result)
    if not args:
        return True

    cmd = ["exiftool", "-overwrite_original"]
    if not backup:
        cmd.append("-overwrite_original")
    else:
        # exiftool creates .jpg_original backup by default when -overwrite_original is not set
        cmd = ["exiftool"]

    cmd.extend(args)
    cmd.append(str(path))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            log.error("exiftool failed for %s: %s", photo_path, proc.stderr)
            return False
        log.info("Metadata written to %s", path.name)
        return True
    except subprocess.TimeoutExpired:
        log.error("exiftool timed out for %s", photo_path)
        return False
    except FileNotFoundError:
        log.error("exiftool not found. Install with: brew install exiftool")
        return False


def read_metadata(photo_path: str) -> dict:
    """Read existing IPTC/XMP metadata from a photo."""
    try:
        proc = subprocess.run(
            ["exiftool", "-json", "-IPTC:all", "-XMP:all", str(photo_path)],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            return data[0] if data else {}
    except Exception as e:
        log.error("Failed to read metadata from %s: %s", photo_path, e)
    return {}


def has_happy_vision_tag(photo_path: str) -> bool:
    """Check if a photo has already been processed by Happy Vision."""
    metadata = read_metadata(photo_path)
    instructions = metadata.get("Instructions", "")
    return "HappyVisionProcessed" in str(instructions)
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
pytest tests/test_metadata_writer.py -v
```

Expected: All 3 tests PASS (these only test `build_exiftool_args`, not actual exiftool execution).

- [ ] **Step 5.5: Lint and commit**

```bash
ruff check modules/metadata_writer.py tests/test_metadata_writer.py
git add modules/metadata_writer.py tests/test_metadata_writer.py
git commit -m "feat: add metadata writer module (exiftool IPTC/XMP)"
```

---

### Task 6: Report Generator Module

**Files:**
- Create: `modules/report_generator.py`
- Create: `tests/test_report_generator.py`

- [ ] **Step 6.1: Write failing tests**

```python
"""tests/test_report_generator.py"""

import csv
import json
from pathlib import Path

from modules.report_generator import generate_csv, generate_json


def _sample_results():
    return [
        {
            "file_path": "/photos/IMG_001.jpg",
            "title": "Speaker on stage",
            "description": "A keynote speaker.",
            "keywords": ["conference", "keynote"],
            "category": "ceremony",
            "subcategory": "keynote",
            "scene_type": "indoor",
            "mood": "formal",
            "people_count": 50,
            "identified_people": ["Jensen Huang"],
            "ocr_text": ["INOUT"],
        },
        {
            "file_path": "/photos/IMG_002.jpg",
            "title": "Networking session",
            "description": "Attendees mingling.",
            "keywords": ["networking"],
            "category": "networking",
            "subcategory": "",
            "scene_type": "indoor",
            "mood": "casual",
            "people_count": 20,
            "identified_people": [],
            "ocr_text": [],
        },
    ]


def test_generate_csv(tmp_path):
    output = tmp_path / "report.csv"
    generate_csv(_sample_results(), output)
    assert output.exists()

    with open(output, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["title"] == "Speaker on stage"
    assert rows[0]["file_path"] == "/photos/IMG_001.jpg"
    assert "conference" in rows[0]["keywords"]


def test_generate_json(tmp_path):
    output = tmp_path / "report.json"
    generate_json(_sample_results(), output)
    assert output.exists()

    with open(output, encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 2
    assert data[0]["title"] == "Speaker on stage"
    assert data[1]["keywords"] == ["networking"]


def test_generate_csv_empty(tmp_path):
    output = tmp_path / "empty.csv"
    generate_csv([], output)
    assert output.exists()
    content = output.read_text()
    # Should have header but no data rows
    lines = content.strip().split("\n")
    assert len(lines) == 1  # header only
```

- [ ] **Step 6.2: Run tests to verify they fail**

```bash
pytest tests/test_report_generator.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 6.3: Implement report_generator**

```python
"""modules/report_generator.py — CSV/JSON report export"""

import csv
import json
from pathlib import Path

from modules.logger import setup_logger

log = setup_logger("report_generator")

CSV_FIELDS = [
    "file_path",
    "title",
    "description",
    "keywords",
    "category",
    "subcategory",
    "scene_type",
    "mood",
    "people_count",
    "identified_people",
    "ocr_text",
]


def generate_csv(results: list[dict], output_path: Path | str) -> None:
    """Generate a CSV report from analysis results."""
    output_path = Path(output_path)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            row = dict(result)
            # Convert lists to comma-separated strings for CSV
            for key in ["keywords", "identified_people", "ocr_text"]:
                if isinstance(row.get(key), list):
                    row[key] = ", ".join(row[key])
            writer.writerow(row)
    log.info("CSV report written to %s (%d photos)", output_path, len(results))


def generate_json(results: list[dict], output_path: Path | str) -> None:
    """Generate a JSON report from analysis results."""
    output_path = Path(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("JSON report written to %s (%d photos)", output_path, len(results))
```

- [ ] **Step 6.4: Run tests to verify they pass**

```bash
pytest tests/test_report_generator.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 6.5: Lint and commit**

```bash
ruff check modules/report_generator.py tests/test_report_generator.py
git add modules/report_generator.py tests/test_report_generator.py
git commit -m "feat: add CSV/JSON report generator"
```

---

### Task 7: Pipeline Orchestrator

**Files:**
- Create: `modules/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 7.1: Write failing tests**

```python
"""tests/test_pipeline.py"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.pipeline import scan_photos, run_pipeline, PipelineCallbacks


def test_scan_photos_finds_jpgs(tmp_path):
    (tmp_path / "photo1.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "photo2.JPG").write_bytes(b"\xff\xd8")
    (tmp_path / "photo3.jpeg").write_bytes(b"\xff\xd8")
    (tmp_path / "photo4.png").write_bytes(b"\x89PNG")
    (tmp_path / "readme.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "photo5.jpg").write_bytes(b"\xff\xd8")

    photos = scan_photos(str(tmp_path))
    extensions = {Path(p).suffix.lower() for p in photos}
    assert extensions <= {".jpg", ".jpeg"}
    assert len(photos) == 4  # photo1, photo2, photo3, sub/photo5


def test_scan_photos_empty_folder(tmp_path):
    photos = scan_photos(str(tmp_path))
    assert photos == []


def test_pipeline_callbacks_called(tmp_path):
    (tmp_path / "photo1.jpg").write_bytes(b"\xff\xd8")

    mock_result = {
        "title": "Test",
        "description": "Test photo",
        "keywords": ["test"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }

    callbacks = PipelineCallbacks()
    progress_calls = []
    callbacks.on_progress = lambda done, total, path: progress_calls.append((done, total, path))

    with patch("modules.pipeline.analyze_photo", return_value=mock_result):
        results = run_pipeline(
            folder=str(tmp_path),
            api_key="fake-key",
            model="lite",
            concurrency=1,
            skip_existing=False,
            db_path=tmp_path / "test.db",
            callbacks=callbacks,
        )

    assert len(results) == 1
    assert len(progress_calls) == 1
    assert progress_calls[0][0] == 1  # done
    assert progress_calls[0][1] == 1  # total


def test_pipeline_skips_processed(tmp_path):
    (tmp_path / "photo1.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "photo2.jpg").write_bytes(b"\xff\xd8")

    mock_result = {"title": "Test", "keywords": []}

    from modules.result_store import ResultStore
    store = ResultStore(tmp_path / "test.db")
    store.save_result(str(tmp_path / "photo1.jpg"), mock_result)
    store.close()

    analyze_calls = []

    def mock_analyze(path, **kwargs):
        analyze_calls.append(path)
        return mock_result

    with patch("modules.pipeline.analyze_photo", side_effect=mock_analyze):
        run_pipeline(
            folder=str(tmp_path),
            api_key="fake-key",
            model="lite",
            concurrency=1,
            skip_existing=True,
            db_path=tmp_path / "test.db",
        )

    # Only photo2 should have been analyzed
    assert len(analyze_calls) == 1
    assert "photo2.jpg" in analyze_calls[0]
```

- [ ] **Step 7.2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 7.3: Implement pipeline**

```python
"""modules/pipeline.py — Orchestrator: scan folder, run analysis, coordinate modules"""

import concurrent.futures
import threading
from pathlib import Path

from modules.config import load_config
from modules.gemini_vision import analyze_photo
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


# Global pipeline state for API control
_current_state: PipelineState | None = None


def get_pipeline_state() -> PipelineState | None:
    return _current_state


def run_pipeline(
    folder: str,
    api_key: str,
    model: str = "lite",
    concurrency: int = 5,
    skip_existing: bool = False,
    write_metadata: bool = False,
    db_path: Path | str | None = None,
    callbacks: PipelineCallbacks | None = None,
) -> list[dict]:
    """Run the full analysis pipeline on a folder of photos."""
    global _current_state
    _current_state = PipelineState()
    state = _current_state

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
        log.info("Skipping %d already processed, %d to analyze", len(photos) - len(to_process), len(to_process))
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
                future.result()  # propagate exceptions

    # Write metadata if requested
    if write_metadata and results:
        from modules.metadata_writer import write_metadata as write_meta
        for r in store.get_all_results():
            write_meta(r["file_path"], r)

    store.close()
    callbacks.on_complete(total, failed_count)
    _current_state = None
    log.info("Pipeline complete: %d analyzed, %d failed", len(results), failed_count)
    return results
```

- [ ] **Step 7.4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 7.5: Lint and commit**

```bash
ruff check modules/pipeline.py tests/test_pipeline.py
git add modules/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestrator with concurrency and checkpoint"
```

---

### Task 8: CLI Integration

**Files:**
- Modify: `cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 8.1: Write failing tests**

```python
"""tests/test_cli.py"""

from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

from cli import main


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Analyze photos" in result.output
    assert "--model" in result.output


def test_cli_no_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".hv"))
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "test.jpg").write_bytes(b"\xff\xd8")

    runner = CliRunner()
    result = runner.invoke(main, [str(tmp_path / "photos")])
    assert result.exit_code != 0
    assert "API key" in result.output or "api_key" in result.output.lower()


def test_cli_runs_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".hv"))

    # Set up config with API key
    config_dir = tmp_path / ".hv"
    config_dir.mkdir()
    import json
    (config_dir / "config.json").write_text(json.dumps({"gemini_api_key": "fake-key"}))

    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "test.jpg").write_bytes(b"\xff\xd8")

    mock_result = {"title": "Test", "keywords": ["test"]}

    with patch("modules.pipeline.analyze_photo", return_value=mock_result):
        runner = CliRunner()
        result = runner.invoke(main, [
            str(tmp_path / "photos"),
            "--output", str(tmp_path / "output"),
        ])

    assert result.exit_code == 0
    assert "1" in result.output  # should mention 1 photo analyzed
```

- [ ] **Step 8.2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -v
```

Expected: Tests fail because cli.py has placeholder implementation.

- [ ] **Step 8.3: Implement full CLI**

```python
"""Happy Vision — CLI entry point"""

import sys
from pathlib import Path

import click
from tqdm import tqdm

from modules.config import load_config, save_config
from modules.pipeline import run_pipeline, PipelineCallbacks, scan_photos
from modules.report_generator import generate_csv, generate_json
from modules.result_store import ResultStore
from modules.logger import setup_logger

log = setup_logger("cli")


class CLICallbacks(PipelineCallbacks):
    def __init__(self, progress_bar):
        self.progress_bar = progress_bar

    def on_progress(self, done, total, file_path):
        self.progress_bar.update(1)
        self.progress_bar.set_postfix_str(Path(file_path).name)

    def on_error(self, file_path, error):
        tqdm.write(f"FAIL: {Path(file_path).name} — {error}")

    def on_complete(self, total, failed):
        pass


@click.command()
@click.argument("folder", type=click.Path(exists=True))
@click.option("--model", default="lite", type=click.Choice(["lite", "flash"]),
              help="Gemini model (lite=2.0 Flash Lite, flash=2.5 Flash)")
@click.option("--concurrency", default=5, type=int, help="Parallel API calls")
@click.option("--output", default=".", type=click.Path(), help="Report output path")
@click.option("--format", "fmt", default="csv", help="Report format: csv, json, or csv,json")
@click.option("--write-metadata", is_flag=True, default=False, help="Write results to photo IPTC/XMP")
@click.option("--skip-existing", is_flag=True, default=False, help="Skip already processed photos")
@click.option("--api-key", default=None, help="Gemini API key (overrides config)")
def main(folder, model, concurrency, output, fmt, write_metadata, skip_existing, api_key):
    """Analyze photos in FOLDER with Gemini AI."""
    config = load_config()

    # Resolve API key
    key = api_key or config.get("gemini_api_key", "")
    if not key:
        click.echo("ERROR: No Gemini API key. Set it with --api-key or in ~/.happy-vision/config.json")
        sys.exit(1)

    # Scan first to get count
    photos = scan_photos(folder)
    if not photos:
        click.echo("No JPG photos found in folder.")
        return

    click.echo(f"Happy Vision — {len(photos)} photos in {folder}")
    click.echo(f"Model: {model}, Concurrency: {concurrency}")

    # Run pipeline with tqdm progress
    with tqdm(total=len(photos), unit="photo", desc="Analyzing") as pbar:
        callbacks = CLICallbacks(pbar)
        results = run_pipeline(
            folder=folder,
            api_key=key,
            model=model,
            concurrency=concurrency,
            skip_existing=skip_existing,
            write_metadata=write_metadata,
            callbacks=callbacks,
        )

    click.echo(f"\nDone: {len(results)} analyzed")

    # Export reports
    if results:
        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)

        store = ResultStore()
        all_results = store.get_all_results()
        store.close()

        formats = [f.strip() for f in fmt.split(",")]
        for f in formats:
            if f == "csv":
                csv_path = output_dir / "happy_vision_report.csv"
                generate_csv(all_results, csv_path)
                click.echo(f"CSV: {csv_path}")
            elif f == "json":
                json_path = output_dir / "happy_vision_report.json"
                generate_json(all_results, json_path)
                click.echo(f"JSON: {json_path}")

    if write_metadata:
        click.echo("Metadata written to photos.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8.4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 8.5: Lint and commit**

```bash
ruff check cli.py tests/test_cli.py
git add cli.py tests/test_cli.py
git commit -m "feat: implement CLI with tqdm progress and report export"
```

---

### Task 9: Flask API + SSE

**Files:**
- Modify: `web_ui.py`
- Create: `api/analysis.py`
- Create: `api/results.py`
- Create: `api/settings.py`
- Create: `api/export.py`
- Create: `api/__init__.py` (update)

- [ ] **Step 9.1: Create api/settings.py**

```python
"""api/settings.py — Config API"""

from flask import Blueprint, request, jsonify

from modules.config import load_config, save_config

settings_bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@settings_bp.route("", methods=["GET"])
def get_settings():
    config = load_config()
    # Never return the full API key to frontend
    safe = dict(config)
    key = safe.get("gemini_api_key", "")
    safe["gemini_api_key_set"] = bool(key)
    safe["gemini_api_key"] = f"...{key[-4:]}" if len(key) > 4 else ""
    return jsonify(safe)


@settings_bp.route("", methods=["PUT"])
def update_settings():
    data = request.get_json()
    config = load_config()
    for key in ["model", "concurrency", "write_metadata", "skip_existing"]:
        if key in data:
            config[key] = data[key]
    if "gemini_api_key" in data and not data["gemini_api_key"].startswith("..."):
        config["gemini_api_key"] = data["gemini_api_key"]
    save_config(config)
    return jsonify({"status": "ok"})
```

- [ ] **Step 9.2: Create api/analysis.py**

```python
"""api/analysis.py — Analysis start/pause/cancel + SSE progress"""

import json
import queue
import threading

from flask import Blueprint, request, jsonify, Response

from modules.config import load_config
from modules.pipeline import run_pipeline, get_pipeline_state, PipelineCallbacks
from modules.logger import setup_logger

log = setup_logger("api_analysis")

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/analysis")

# SSE subscribers
_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()

# Pipeline thread
_pipeline_thread: threading.Thread | None = None


def _broadcast_sse(event: str, data: dict):
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


class SSECallbacks(PipelineCallbacks):
    def on_progress(self, done, total, file_path):
        _broadcast_sse("progress", {"done": done, "total": total, "file": file_path})

    def on_error(self, file_path, error):
        _broadcast_sse("error", {"file": file_path, "error": error})

    def on_complete(self, total, failed):
        _broadcast_sse("complete", {"total": total, "failed": failed})


@analysis_bp.route("/start", methods=["POST"])
def start_analysis():
    global _pipeline_thread
    if _pipeline_thread and _pipeline_thread.is_alive():
        return jsonify({"error": "Analysis already running"}), 409

    data = request.get_json()
    folder = data.get("folder", "")
    if not folder:
        return jsonify({"error": "folder is required"}), 400

    config = load_config()
    api_key = config.get("gemini_api_key", "")
    if not api_key:
        return jsonify({"error": "Gemini API key not configured"}), 400

    model = data.get("model", config.get("model", "lite"))
    concurrency = data.get("concurrency", config.get("concurrency", 5))
    skip_existing = data.get("skip_existing", config.get("skip_existing", False))
    write_metadata = data.get("write_metadata", config.get("write_metadata", False))

    def run():
        run_pipeline(
            folder=folder,
            api_key=api_key,
            model=model,
            concurrency=concurrency,
            skip_existing=skip_existing,
            write_metadata=write_metadata,
            callbacks=SSECallbacks(),
        )

    _pipeline_thread = threading.Thread(target=run, daemon=True)
    _pipeline_thread.start()

    return jsonify({"status": "started"})


@analysis_bp.route("/pause", methods=["POST"])
def pause_analysis():
    state = get_pipeline_state()
    if state:
        state.pause()
        return jsonify({"status": "paused"})
    return jsonify({"error": "No analysis running"}), 404


@analysis_bp.route("/resume", methods=["POST"])
def resume_analysis():
    state = get_pipeline_state()
    if state:
        state.resume()
        return jsonify({"status": "resumed"})
    return jsonify({"error": "No analysis running"}), 404


@analysis_bp.route("/cancel", methods=["POST"])
def cancel_analysis():
    state = get_pipeline_state()
    if state:
        state.cancel()
        return jsonify({"status": "cancelled"})
    return jsonify({"error": "No analysis running"}), 404


@analysis_bp.route("/stream")
def sse_stream():
    q = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_queues.append(q)

    def generate():
        try:
            while True:
                msg = q.get(timeout=30)
                yield msg
        except queue.Empty:
            yield "event: ping\ndata: {}\n\n"
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 9.3: Create api/results.py**

```python
"""api/results.py — Query and edit analysis results"""

from flask import Blueprint, request, jsonify

from modules.result_store import ResultStore

results_bp = Blueprint("results", __name__, url_prefix="/api/results")


@results_bp.route("", methods=["GET"])
def get_results():
    store = ResultStore()
    results = store.get_all_results()
    summary = store.get_summary()
    store.close()
    return jsonify({"results": results, "summary": summary})


@results_bp.route("/<path:file_path>", methods=["PUT"])
def update_result(file_path):
    """User manually edits a field before writing metadata."""
    data = request.get_json()
    store = ResultStore()
    store.update_result(f"/{file_path}", data)
    store.close()
    return jsonify({"status": "ok"})


@results_bp.route("/write-metadata", methods=["POST"])
def write_all_metadata():
    """Write metadata to all completed photos."""
    from modules.metadata_writer import write_metadata

    store = ResultStore()
    results = store.get_all_results()
    store.close()

    success = 0
    failed = 0
    for r in results:
        if write_metadata(r["file_path"], r):
            success += 1
        else:
            failed += 1

    return jsonify({"success": success, "failed": failed})
```

- [ ] **Step 9.4: Create api/export.py**

```python
"""api/export.py — Report download"""

import tempfile
from pathlib import Path

from flask import Blueprint, send_file, request

from modules.result_store import ResultStore
from modules.report_generator import generate_csv, generate_json

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


@export_bp.route("/<fmt>")
def export_report(fmt):
    store = ResultStore()
    results = store.get_all_results()
    store.close()

    if not results:
        return {"error": "No results to export"}, 404

    tmp = Path(tempfile.mkdtemp())

    if fmt == "csv":
        path = tmp / "happy_vision_report.csv"
        generate_csv(results, path)
        return send_file(path, as_attachment=True, download_name="happy_vision_report.csv")
    elif fmt == "json":
        path = tmp / "happy_vision_report.json"
        generate_json(results, path)
        return send_file(path, as_attachment=True, download_name="happy_vision_report.json")
    else:
        return {"error": f"Unknown format: {fmt}"}, 400
```

- [ ] **Step 9.5: Update web_ui.py to register blueprints**

```python
"""Happy Vision — Web UI entry point"""

import os
import sys

from flask import Flask, send_from_directory
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)

# Register blueprints
from api.settings import settings_bp
from api.analysis import analysis_bp
from api.results import results_bp
from api.export import export_bp

app.register_blueprint(settings_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(results_bp)
app.register_blueprint(export_bp)


@app.route("/api/health")
def health():
    return {"status": "ok"}


# Serve Vue frontend in production
DIST_DIR = Path(__file__).parent / "frontend" / "dist"


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if DIST_DIR.exists():
        file_path = DIST_DIR / path
        if file_path.is_file():
            return send_from_directory(DIST_DIR, path)
        return send_from_directory(DIST_DIR, "index.html")
    return {"message": "Happy Vision API is running. Frontend not built yet."}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=True)
```

- [ ] **Step 9.6: Smoke test Flask app**

```bash
python3 -c "
from web_ui import app
client = app.test_client()
r = client.get('/api/health')
print(r.json)
assert r.json['status'] == 'ok'
print('OK: Flask app starts with all blueprints')
"
```

Expected: `{'status': 'ok'}` and `OK: Flask app starts with all blueprints`

- [ ] **Step 9.7: Lint and commit**

```bash
ruff check web_ui.py api/
git add web_ui.py api/
git commit -m "feat: add Flask API with SSE progress, results, settings, and export"
```

---

### Task 10: Vue 3 Frontend

**Files:**
- Create: entire `frontend/` directory

- [ ] **Step 10.1: Scaffold Vue project**

```bash
cd /Users/bobo_m3/Developer/Happy_Vision
npm create vite@latest frontend -- --template vue
cd frontend
npm install
npm install vue-router@4 pinia
npm install -D tailwindcss @tailwindcss/vite
```

- [ ] **Step 10.2: Configure Vite (frontend/vite.config.js)**

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5176,
    proxy: {
      '/api': 'http://localhost:8081',
    },
  },
})
```

- [ ] **Step 10.3: Create frontend/src/main.js**

```javascript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

- [ ] **Step 10.4: Add Tailwind to frontend/src/style.css**

```css
@import "tailwindcss";
```

- [ ] **Step 10.5: Create frontend/src/router.js**

```javascript
import { createRouter, createWebHistory } from 'vue-router'
import ImportView from './views/ImportView.vue'
import ProgressView from './views/ProgressView.vue'
import ResultsView from './views/ResultsView.vue'
import SettingsView from './views/SettingsView.vue'

const routes = [
  { path: '/', name: 'import', component: ImportView },
  { path: '/progress', name: 'progress', component: ProgressView },
  { path: '/results', name: 'results', component: ResultsView },
  { path: '/settings', name: 'settings', component: SettingsView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
```

- [ ] **Step 10.6: Create frontend/src/App.vue**

```vue
<template>
  <div class="min-h-screen bg-gray-50">
    <nav class="bg-white border-b border-gray-200 px-6 py-3">
      <div class="flex items-center justify-between max-w-6xl mx-auto">
        <h1 class="text-xl font-bold text-gray-900">Happy Vision</h1>
        <div class="flex gap-4">
          <router-link to="/" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'import' }">Import</router-link>
          <router-link to="/progress" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'progress' }">Progress</router-link>
          <router-link to="/results" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'results' }">Results</router-link>
          <router-link to="/settings" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'settings' }">Settings</router-link>
        </div>
      </div>
    </nav>
    <main class="max-w-6xl mx-auto px-6 py-8">
      <router-view />
    </main>
  </div>
</template>
```

- [ ] **Step 10.7: Create frontend/src/stores/analysis.js**

```javascript
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAnalysisStore = defineStore('analysis', () => {
  const isRunning = ref(false)
  const isPaused = ref(false)
  const done = ref(0)
  const total = ref(0)
  const currentFile = ref('')
  const errors = ref([])
  let eventSource = null

  function connectSSE() {
    if (eventSource) eventSource.close()
    eventSource = new EventSource('/api/analysis/stream')

    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data)
      done.value = data.done
      total.value = data.total
      currentFile.value = data.file
    })

    eventSource.addEventListener('error_event', (e) => {
      const data = JSON.parse(e.data)
      errors.value.push(data)
    })

    eventSource.addEventListener('complete', (e) => {
      const data = JSON.parse(e.data)
      isRunning.value = false
      isPaused.value = false
      total.value = data.total
    })
  }

  async function startAnalysis(folder, options = {}) {
    const res = await fetch('/api/analysis/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder, ...options }),
    })
    if (res.ok) {
      isRunning.value = true
      isPaused.value = false
      done.value = 0
      errors.value = []
      connectSSE()
    }
    return res.json()
  }

  async function pause() {
    await fetch('/api/analysis/pause', { method: 'POST' })
    isPaused.value = true
  }

  async function resume() {
    await fetch('/api/analysis/resume', { method: 'POST' })
    isPaused.value = false
  }

  async function cancel() {
    await fetch('/api/analysis/cancel', { method: 'POST' })
    isRunning.value = false
    isPaused.value = false
    if (eventSource) eventSource.close()
  }

  return { isRunning, isPaused, done, total, currentFile, errors, startAnalysis, pause, resume, cancel }
})
```

- [ ] **Step 10.8: Create frontend/src/stores/settings.js**

```javascript
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref({})
  const loaded = ref(false)

  async function fetchSettings() {
    const res = await fetch('/api/settings')
    settings.value = await res.json()
    loaded.value = true
  }

  async function updateSettings(updates) {
    await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    })
    await fetchSettings()
  }

  return { settings, loaded, fetchSettings, updateSettings }
})
```

- [ ] **Step 10.9: Create frontend/src/views/ImportView.vue**

```vue
<template>
  <div>
    <h2 class="text-2xl font-bold mb-6">Import Photos</h2>

    <div class="bg-white rounded-lg border-2 border-dashed border-gray-300 p-12 text-center"
         @dragover.prevent @drop.prevent="onDrop">
      <div class="text-gray-500 mb-4">
        <p class="text-lg">Drag & drop a folder here</p>
        <p class="text-sm mt-2">or enter the path below</p>
      </div>

      <div class="flex gap-2 max-w-xl mx-auto mt-6">
        <input v-model="folderPath" type="text" placeholder="/path/to/photos"
               class="flex-1 border border-gray-300 rounded px-3 py-2 text-sm" />
        <button @click="startAnalysis" :disabled="!folderPath || analysisStore.isRunning"
                class="bg-blue-600 text-white px-6 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          Analyze
        </button>
      </div>

      <div v-if="folderPath" class="mt-4 text-sm text-gray-600">
        <p>Model: {{ settingsStore.settings.model || 'lite' }} | Concurrency: {{ settingsStore.settings.concurrency || 5 }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAnalysisStore } from '../stores/analysis'
import { useSettingsStore } from '../stores/settings'

const router = useRouter()
const analysisStore = useAnalysisStore()
const settingsStore = useSettingsStore()
const folderPath = ref('')

onMounted(() => {
  settingsStore.fetchSettings()
})

function onDrop(e) {
  const items = e.dataTransfer?.items
  if (items?.[0]) {
    folderPath.value = e.dataTransfer.getData('text') || ''
  }
}

async function startAnalysis() {
  if (!folderPath.value) return
  const result = await analysisStore.startAnalysis(folderPath.value, {
    model: settingsStore.settings.model,
    concurrency: settingsStore.settings.concurrency,
    skip_existing: settingsStore.settings.skip_existing,
    write_metadata: settingsStore.settings.write_metadata,
  })
  if (!result.error) {
    router.push('/progress')
  }
}
</script>
```

- [ ] **Step 10.10: Create frontend/src/views/ProgressView.vue**

```vue
<template>
  <div>
    <h2 class="text-2xl font-bold mb-6">Analysis Progress</h2>

    <div v-if="!store.isRunning && store.done === 0" class="text-gray-500">
      No analysis running. <router-link to="/" class="text-blue-600">Start one</router-link>.
    </div>

    <div v-else class="bg-white rounded-lg border p-6">
      <div class="mb-4">
        <div class="flex justify-between text-sm text-gray-600 mb-1">
          <span>{{ store.done }} / {{ store.total }} photos</span>
          <span v-if="store.total">{{ Math.round(store.done / store.total * 100) }}%</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-3">
          <div class="bg-blue-600 h-3 rounded-full transition-all duration-300"
               :style="{ width: store.total ? `${store.done / store.total * 100}%` : '0%' }"></div>
        </div>
      </div>

      <p v-if="store.currentFile" class="text-sm text-gray-500 mb-4 truncate">
        Current: {{ store.currentFile }}
      </p>

      <div class="flex gap-2">
        <button v-if="store.isRunning && !store.isPaused" @click="store.pause()"
                class="bg-yellow-500 text-white px-4 py-2 rounded text-sm">Pause</button>
        <button v-if="store.isPaused" @click="store.resume()"
                class="bg-green-600 text-white px-4 py-2 rounded text-sm">Resume</button>
        <button v-if="store.isRunning" @click="store.cancel()"
                class="bg-red-600 text-white px-4 py-2 rounded text-sm">Cancel</button>
        <router-link v-if="!store.isRunning && store.done > 0" to="/results"
                     class="bg-blue-600 text-white px-4 py-2 rounded text-sm">View Results</router-link>
      </div>

      <div v-if="store.errors.length" class="mt-4">
        <h3 class="text-sm font-medium text-red-600 mb-2">Errors ({{ store.errors.length }})</h3>
        <ul class="text-xs text-red-500 max-h-40 overflow-y-auto">
          <li v-for="err in store.errors" :key="err.file">{{ err.file }}: {{ err.error }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useAnalysisStore } from '../stores/analysis'
const store = useAnalysisStore()
</script>
```

- [ ] **Step 10.11: Create frontend/src/views/ResultsView.vue**

```vue
<template>
  <div>
    <div class="flex justify-between items-center mb-6">
      <h2 class="text-2xl font-bold">Results</h2>
      <div class="flex gap-2">
        <button @click="writeMetadata" class="bg-green-600 text-white px-4 py-2 rounded text-sm">
          Write Metadata to Photos
        </button>
        <a href="/api/export/csv" class="bg-gray-600 text-white px-4 py-2 rounded text-sm">Export CSV</a>
        <a href="/api/export/json" class="bg-gray-600 text-white px-4 py-2 rounded text-sm">Export JSON</a>
      </div>
    </div>

    <div v-if="loading" class="text-gray-500">Loading results...</div>

    <div v-else-if="results.length === 0" class="text-gray-500">
      No results yet. <router-link to="/" class="text-blue-600">Run an analysis</router-link>.
    </div>

    <div v-else class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      <div v-for="r in results" :key="r.file_path"
           @click="selected = r"
           class="bg-white rounded-lg border p-3 cursor-pointer hover:border-blue-400 transition-colors"
           :class="{ 'border-blue-500': selected?.file_path === r.file_path }">
        <img :src="`/api/photo?path=${encodeURIComponent(r.file_path)}`"
             class="w-full h-32 object-cover rounded mb-2" loading="lazy"
             @error="$event.target.style.display='none'" />
        <p class="text-sm font-medium truncate">{{ r.title }}</p>
        <p class="text-xs text-gray-500 truncate">{{ r.category }}</p>
      </div>
    </div>

    <!-- Detail panel -->
    <div v-if="selected" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
         @click.self="selected = null">
      <div class="bg-white rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto m-4">
        <div class="flex justify-between items-start mb-4">
          <h3 class="text-lg font-bold">{{ selected.title }}</h3>
          <button @click="selected = null" class="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>
        <p class="text-sm text-gray-700 mb-3">{{ selected.description }}</p>
        <div class="flex flex-wrap gap-1 mb-3">
          <span v-for="kw in selected.keywords" :key="kw"
                class="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded">{{ kw }}</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-sm text-gray-600">
          <div>Category: <strong>{{ selected.category }}</strong></div>
          <div>Scene: <strong>{{ selected.scene_type }}</strong></div>
          <div>Mood: <strong>{{ selected.mood }}</strong></div>
          <div>People: <strong>{{ selected.people_count }}</strong></div>
        </div>
        <div v-if="selected.identified_people?.length" class="mt-3">
          <p class="text-sm font-medium">Identified People:</p>
          <p class="text-sm text-gray-700">{{ selected.identified_people.join(', ') }}</p>
        </div>
        <div v-if="selected.ocr_text?.length" class="mt-3">
          <p class="text-sm font-medium">OCR Text:</p>
          <p class="text-sm text-gray-700">{{ selected.ocr_text.join(' | ') }}</p>
        </div>
        <p class="text-xs text-gray-400 mt-4 truncate">{{ selected.file_path }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const results = ref([])
const loading = ref(true)
const selected = ref(null)

onMounted(async () => {
  const res = await fetch('/api/results')
  const data = await res.json()
  results.value = data.results
  loading.value = false
})

async function writeMetadata() {
  if (!confirm('Write AI-generated metadata to all photos? Original metadata will be backed up.')) return
  const res = await fetch('/api/results/write-metadata', { method: 'POST' })
  const data = await res.json()
  alert(`Done: ${data.success} written, ${data.failed} failed`)
}
</script>
```

- [ ] **Step 10.12: Create frontend/src/views/SettingsView.vue**

```vue
<template>
  <div>
    <h2 class="text-2xl font-bold mb-6">Settings</h2>

    <div v-if="!store.loaded" class="text-gray-500">Loading...</div>

    <div v-else class="bg-white rounded-lg border p-6 max-w-lg">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Gemini API Key</label>
          <div class="flex gap-2">
            <input v-model="apiKey" type="password" placeholder="Enter your Gemini API key"
                   class="flex-1 border border-gray-300 rounded px-3 py-2 text-sm" />
            <button @click="saveApiKey" class="bg-blue-600 text-white px-4 py-2 rounded text-sm">Save</button>
          </div>
          <p v-if="store.settings.gemini_api_key_set" class="text-xs text-green-600 mt-1">
            Key is set ({{ store.settings.gemini_api_key }})
          </p>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Model</label>
          <select v-model="model" @change="save({ model })"
                  class="border border-gray-300 rounded px-3 py-2 text-sm w-full">
            <option value="lite">Gemini 2.0 Flash Lite (faster, cheaper)</option>
            <option value="flash">Gemini 2.5 Flash (better quality)</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Concurrency</label>
          <input v-model.number="concurrency" type="number" min="1" max="20"
                 @change="save({ concurrency })"
                 class="border border-gray-300 rounded px-3 py-2 text-sm w-24" />
        </div>

        <div class="flex items-center gap-2">
          <input v-model="skipExisting" type="checkbox" @change="save({ skip_existing: skipExisting })"
                 class="rounded" id="skip" />
          <label for="skip" class="text-sm text-gray-700">Skip already processed photos</label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useSettingsStore } from '../stores/settings'

const store = useSettingsStore()
const apiKey = ref('')
const model = ref('lite')
const concurrency = ref(5)
const skipExisting = ref(false)

onMounted(async () => {
  await store.fetchSettings()
  model.value = store.settings.model || 'lite'
  concurrency.value = store.settings.concurrency || 5
  skipExisting.value = store.settings.skip_existing || false
})

async function saveApiKey() {
  if (apiKey.value) {
    await store.updateSettings({ gemini_api_key: apiKey.value })
    apiKey.value = ''
  }
}

async function save(updates) {
  await store.updateSettings(updates)
}
</script>
```

- [ ] **Step 10.13: Verify frontend builds**

```bash
cd /Users/bobo_m3/Developer/Happy_Vision/frontend
npm run build
```

Expected: Build succeeds, `dist/` directory created.

- [ ] **Step 10.14: Commit frontend**

```bash
cd /Users/bobo_m3/Developer/Happy_Vision
git add frontend/ -f
git commit -m "feat: add Vue 3 frontend with import, progress, results, and settings views"
```

---

### Task 11: Photo Serving API + Integration Test

**Files:**
- Modify: `web_ui.py` (add photo serving route)

- [ ] **Step 11.1: Add photo serving endpoint to web_ui.py**

Add after the health endpoint:

```python
from flask import send_file as flask_send_file

@app.route("/api/photo")
def serve_photo():
    """Serve a photo file by path (for thumbnail display in frontend)."""
    photo_path = request.args.get("path", "")
    if not photo_path or not Path(photo_path).is_file():
        return {"error": "File not found"}, 404
    return flask_send_file(photo_path, mimetype="image/jpeg")
```

Add `from flask import request` to the imports at the top if not already there.

- [ ] **Step 11.2: Integration smoke test**

```bash
cd /Users/bobo_m3/Developer/Happy_Vision
python3 -c "
from web_ui import app
client = app.test_client()

# Health check
r = client.get('/api/health')
assert r.json['status'] == 'ok', 'Health check failed'

# Settings
r = client.get('/api/settings')
assert 'model' in r.json, 'Settings failed'

# Results (empty)
r = client.get('/api/results')
assert 'results' in r.json, 'Results failed'

# Export empty
r = client.get('/api/export/csv')
assert r.status_code == 404, 'Export should 404 on empty'

print('All integration checks passed')
"
```

Expected: `All integration checks passed`

- [ ] **Step 11.3: Commit**

```bash
ruff check web_ui.py
git add web_ui.py
git commit -m "feat: add photo serving endpoint and verify integration"
```

---

### Task 12: End-to-End Manual Test

**Files:** None (testing only)

- [ ] **Step 12.1: Start dev servers**

```bash
cd /Users/bobo_m3/Developer/Happy_Vision
make dev
```

- [ ] **Step 12.2: Test CLI with real photos**

In a separate terminal:

```bash
cd /Users/bobo_m3/Developer/Happy_Vision
source .venv/bin/activate

# Set API key
python3 -c "
from modules.config import load_config, save_config
c = load_config()
c['gemini_api_key'] = 'YOUR_REAL_API_KEY'
save_config(c)
"

# Test with a small folder of JPGs
python3 cli.py /path/to/test/photos --model lite --output ./test_output --format csv,json
```

Expected: Progress bar completes, CSV and JSON reports generated in `./test_output/`.

- [ ] **Step 12.3: Test metadata write-back**

```bash
python3 cli.py /path/to/test/photos --model lite --write-metadata --skip-existing

# Verify metadata was written
exiftool -IPTC:all -XMP:all /path/to/test/photos/some_photo.jpg
```

Expected: IPTC/XMP fields populated with AI-generated content.

- [ ] **Step 12.4: Test Web UI**

Open http://localhost:5176 in browser:
1. Go to Settings, enter API key
2. Go to Import, enter a folder path, click Analyze
3. Watch progress on Progress page
4. View results on Results page, click a photo to see detail
5. Export CSV

- [ ] **Step 12.5: Commit any fixes and push**

```bash
git add -A
git commit -m "fix: adjustments from end-to-end testing"
git push origin master
```
