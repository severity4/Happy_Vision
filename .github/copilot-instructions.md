# Copilot instructions for Happy_Vision

Purpose: provide repository-specific commands, a concise architecture overview, and key conventions for Copilot sessions working in this repo.

1) Build, test, and lint commands

- Install (Python deps + frontend):
  - ./setup.sh  # creates .venv and installs Python deps
  - OR make install

- Dev mode (runs backend + frontend):
  - make dev  # starts Flask (8081) and Vite (5176)
  - or: python3 web_ui.py & cd frontend && npm run dev

- Run frontend build:
  - make build  # runs `cd frontend && npm run build`

- Lint (Python):
  - make lint  # ruff check modules api tests web_ui.py cli.py
  - run ruff on a single file: ruff check modules/gemini_vision.py

- Tests (pytest):
  - make test  # runs pytest -q (full suite)
  - run a single test file: pytest -q tests/test_metadata_writer.py
  - run a single test function: pytest tests/test_metadata_writer.py::test_write_metadata -q
  - run tests matching -k: pytest -k "metadata"

- Packaging / app:
  - make app  # build macOS .app via build_app.py

- Helpful Make targets: make verify (lint + tests), make help

2) High-level architecture (big picture)

- Purpose: macOS desktop tool (pywebview) + Flask backend + Vue 3 frontend. Core flow:
  1. CLI / UI triggers pipeline (cli.py or web_ui.py)
  2. pipeline orchestrates capture -> gemini_vision (Google GenAI) -> metadata_writer (exiftool) -> result_store (SQLite)
  3. Background daemon polls Gemini batch jobs and updates job state (modules/batch_monitor, watch)
  4. Frontend (frontend/) uses Vite; web_ui.py serves API blueprints under api/ for analysis, results, settings, export, etc.

- Data stores & external deps:
  - SQLite DB: ~/.happy-vision/results.db (result_store.py)
  - exiftool required for writing IPTC/XMP
  - Google Gemini via google-genai package (gemini_vision.py / gemini_batch.py)

- Packaging: build_app.py / make app produce dist/HappyVision.app (macOS only)

3) Key conventions & repo-specific patterns

- Tests: pytest used for unit and integration tests. Keep tests under tests/*. Use -q for concise output. Many tests assert behavior of pipeline components (phash, result_store, metadata_writer).

- Linting: ruff is used; Makefile centralizes targets. Use `make help` to discover supported commands.

- Virtualenv: setup.sh creates .venv and instructs to source .venv/bin/activate. CI/maintainers assume Python 3.10+.

- Frontend: standard npm/Vite app in frontend/. Frontend dev server runs on :5176 while Flask runs on :8081 in dev mode.

- External binary deps: exiftool must be installed on machine (setup.sh checks/installs via brew on macOS).

- Long-running background work: background daemon(s) poll Gemini and mark jobs LIVE/RETRY/STUCK. Expect asynchronous state transitions (modules/batch_monitor, system.py). Copilot should prefer inspecting modules/pipeline.py, gemini_batch.py, and result_store.py when reasoning about job flow.

- Secrets/config: secret_store.py and config.py hold runtime config; do not hardcode API keys in code. CLAUDE.md contains maintainer notes and operational commands — reference it for release and onboarding steps.

4) Files & commands Copilot should check first

- web_ui.py (entry for desktop app / dev server)
- cli.py (CLI flows)
- modules/gemini_vision.py, modules/gemini_batch.py (external API interactions)
- modules/metadata_writer.py, modules/result_store.py (I/O and persistence)
- frontend/ (Vue app) and frontend/package.json
- Makefile and setup.sh for standard commands

5) Other AI assistant configs

- CLAUDE.md exists and contains maintainer guidance and a short command list; incorporate key commands from it when responding. No other AI assistant config files (.cursorrules, AGENTS.md, etc.) were found at time of writing.

6) Quick troubleshooting hints for Copilot responses

- When suggesting a command to run locally, reference Makefile targets (e.g., `make dev`, `make test`) or the explicit python/npm commands found in those targets.
- When recommending edits touching metadata or exiftool usage, confirm exiftool is installed and the environment uses the repo's .venv.

---

Created from README.md, CLAUDE.md, and project files. Keep this file concise and update when major workflows change (e.g., non-macOS packaging).
