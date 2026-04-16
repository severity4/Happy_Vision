# CLAUDE.md

## Project Overview

映奧創意 (INOUT Creative) 內部工具：AI 平面照片標記系統。透過 Google Gemini API 分析 JPG 照片，產生英文描述、關鍵字、分類等 metadata，寫回 IPTC/XMP 欄位，並匯出 CSV/JSON 報告。

**語言：** Python 3.10+（後端）+ Vue 3（前端）

## Commands

```bash
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
```

## Architecture

Flask backend (`web_ui.py`) with blueprints in `api/`. Core logic in `modules/`. Vue 3 frontend in `frontend/`. CLI in `cli.py`.

**Modules:** `config.py` (settings), `gemini_vision.py` (Gemini API), `result_store.py` (SQLite), `metadata_writer.py` (exiftool), `report_generator.py` (CSV/JSON), `pipeline.py` (orchestrator), `logger.py` (logging).

**API Blueprints:** `analysis.py` (start/pause/cancel + SSE), `results.py` (query/edit), `settings.py` (config), `export.py` (download reports).
