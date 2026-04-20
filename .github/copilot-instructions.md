# Copilot 指南 — Happy_Vision

目的：為進入此倉庫的 Copilot / 自動化 agent 提供專案特定的指令、架構要點與慣例，便於快速取得上下文並做出正確建議或變更。

1) 常用建置 / 測試 / Lint 指令

- 安裝（Python 與 frontend）：
  - ./setup.sh    # 建立 .venv，安裝 Python 套件
  - 或：make install

- 開發模式（同時啟動後端與前端）：
  - make dev     # 會啟動 Flask (8081) 與 Vite (5176)
  - 或手動：python3 web_ui.py & cd frontend && npm run dev

- 前端建置：
  - make build   # cd frontend && npm run build

- Lint（Python，使用 ruff）：
  - make lint    # ruff check modules api tests web_ui.py cli.py
  - 檢查單一檔案：ruff check modules/gemini_vision.py

- 測試（pytest）：
  - make test    # 執行整個測試套件（pytest -q）
  - 執行單一測試檔：pytest -q tests/test_metadata_writer.py
  - 執行單一測試函式：pytest tests/test_metadata_writer.py::test_write_metadata -q
  - 依關鍵字跑測試：pytest -k "metadata"

- 打包 / App：
  - make app     # 透過 build_app.py 建置 macOS .app

- 常用 make target：make verify（lint + tests）、make help

2) 高階架構（重點流程）

- 產品定位：macOS 原生桌面工具（pywebview）＋Flask 後端＋Vue 3 前端。
- 核心資料流程：
  1. 由 CLI 或 Web UI（cli.py / web_ui.py）觸發 pipeline
  2. pipeline 呼叫 modules/gemini_vision.py / gemini_batch.py（Google Gemini）分析影像
  3. 結果由 modules/metadata_writer.py 寫入 IPTC/XMP（exiftool），並存入 modules/result_store.py（SQLite）
  4. 背景 daemon（batch_monitor / watch）負責輪詢 Gemini 批次作業，更新狀態與重試策略
  5. 前端（frontend/）透過 API blueprints（api/）呈現監控、失敗重試、報表等功能

- 外部依賴與儲存：
  - SQLite DB（預設在 ~/.happy-vision/results.db）
  - exiftool（二進位）必須在系統上安裝
  - Google Gemini（google-genai 套件）作為視覺 AI 引擎

- 打包：make app / build_app.py → dist/HappyVision.app（目前僅 macOS）

3) 專案慣例與注意事項

- 測試：pytest 管理單元與整合測試，tests/ 下有大量案例（含 phash、result_store、metadata_writer 等）。
- Lint：使用 ruff；Makefile 是日常入口。
- 虛擬環境：setup.sh 會建立 .venv；開發者/CI 假設使用 Python 3.10+
- 前端：位於 frontend/，使用 Vite；dev server 為 :5176，後端 dev 為 :8081
- 外部二進位：exiftool 需安裝（setup.sh 在 macOS 上會透過 brew 安裝）
- 非同步管線：背景 daemon 會標示 LIVE / RETRY / STUCK，閱讀 modules/pipeline.py、modules/gemini_batch.py、modules/batch_monitor.py、modules/result_store.py 能快速理解狀態轉換
- 秘密與設定：secret_store.py 與 config.py 管理本地設定；不要在程式碼內硬編 API keys。可參考 CLAUDE.md 的維運備註

4) Copilot / 自動化 agent 首選檢查位置

- web_ui.py（桌面 app / dev server 進入點）
- cli.py（CLI 流程）
- modules/gemini_vision.py, modules/gemini_batch.py（外部 API）
- modules/metadata_writer.py, modules/result_store.py（寫入與儲存）
- modules/pipeline.py, modules/batch_monitor.py（作業流程與重試邏輯）
- frontend/ 與 frontend/package.json（若修改前端需檢查）
- Makefile、setup.sh（常用命令）

5) 已新增的 CI / Canary（重要）

- CI (ruff + pytest)：.github/workflows/ci.yml
  - 觸發：pull_request、push 到 main
  - 內容：setup python、安裝 requirements、使用 pip cache、執行 ruff、執行 pytest，並上傳 report

- Playwright Canary：.github/workflows/playwright-canary.yml
  - 觸發：push、pull_request、每日排程（03:00 UTC）
  - 內容：安裝 Node + Playwright 瀏覽器、build 前端、啟動 Flask 後端並等待就緒、執行 E2E 測試、上傳 HTML 報告

6) 與其他 AI assistant / agents 的整合

- AGENTS.md（repo root）已建立，請 agent 開發者將其視為 agent 註冊表：描述名稱、負責人、觸發條件、需要的 GH Secrets/權限與聯絡方式
- 自動 agent 在運作時，應依 AGENTS.md 與 workflows 路徑尋找觸發點（例如 .github/workflows/playwright-canary.yml）
- 為避免外部 API 花費或測試漂移，涉及 Gemini/Google 的測試請盡量使用 mock/fixture 或錄製的測試資料（見 AGENTS.md 下方建議）

7) 快速排錯建議（給 Copilot 或自動 agent）

- 要建議本地命令，引用 Makefile 目標（make dev / make test / make lint）或直接列出命令
- 若變更牽涉 exiftool，先檢查系統是否有安裝（setup.sh 有檢查步驟）
- 若建議變更會觸發 CI，請同時更新 .github/workflows 及 AGENTS.md（以便其他 agent 知道觸發條件）

---

備註：此檔案由 README.md、CLAUDE.md、Makefile 與專案程式碼匯總而成；如有流程或包裝方式改變（例如擴展至 Windows），請同步更新本檔與 AGENTS.md。

已記錄的工作流程：
- .github/workflows/ci.yml（PR 與 push 的 ruff + pytest）
- .github/workflows/playwright-canary.yml（每日 + push 的 Playwright canary）

若需要，我可以：
- 把本檔加入 README 的 quick-start badge 與 CI 狀態
- 把 CLAUDE.md 的維運重點合併進本檔（需你同意）

請問要我把上述兩項（加入 README badge / 合併 CLAUDE.md 要點）一起做嗎？
