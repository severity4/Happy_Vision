# Changelog

## v0.5.0 — 2026-04-18

### Cost visibility · 每張花費可見化
- **新增 `modules/pricing.py`** — 內建 Gemini 2.5 / 2.0 flash-lite / flash 定價表 + `calc_cost_usd(model, input, output)`。定價有效日期 2026-04-18，Google 調整時改這張表即可。
- **`gemini_vision.analyze_photo`** — 從 API response 抓 `usage_metadata`，回傳 `(result, usage)` tuple，usage 含 `input_tokens / output_tokens / total_tokens / model`。
- **`result_store` schema 擴充**（additive migration，舊 DB 自動相容）— 加 `input_tokens / output_tokens / total_tokens / cost_usd / model` 5 個欄位。`save_result` 新增可選的 `usage=` / `cost_usd=` 參數。
- **新增 `get_result_with_usage()` + `get_today_stats()` 回傳 `cost_usd_today`**。
- **Monitor 頁新增第 5 個 gauge tile：COST · 今日花費**（顯示 USD + NTD 概估）。Nav status strip 有資料時也會加一欄「花費」。
- **Detail modal 新增「USAGE · 用量與花費」區塊** — 顯示 input/output tokens + 本張 USD 成本 + 模型名稱。

### PDF 報告
- **新增 `/api/export/pdf` 端點** + action bar 的「PDF 報告」按鈕。
- **新增 `modules/pdf_report.py`**（reportlab）— 封面頁：總張數 / 總花費 USD+NTD / 總 tokens / 依模型花費明細 + 單價註記 / 主要分類 / 熱門關鍵字 top 15。明細頁：每張照片檔名 · 分類 · 氛圍 · tokens · USD · 時間，長結果自動分頁（每頁 28 列）。
- **Bundle Noto Sans TC Regular VF 字型**（SIL OFL license，11 MB）進 `assets/`。reportlab 內建 CID 字型有 CMap bug（`UniGB-UCS2-H` 對不上 `Adobe-CNS1`），改用 TTF 才穩。

### Tests
- `test_pricing.py` — 11 個測試（定價表、邊界值、未知模型 fallback）
- `test_pdf_report.py` — 6 個測試（空資料、CJK、分頁、多模型）
- `test_result_store_usage.py` — 10 個測試（migration 冪等性、usage 持久化、今日 cost 統計）
- 所有既有 `analyze_photo` mock 改跟新 tuple signature 對齊。**201 → 228 passed**。

### Build
- `build_app.py` 加 hidden-imports：`modules.pricing` / `modules.pdf_report` / `reportlab.pdfbase.cidfonts`，並把 `assets/NotoSansTC-Regular.ttf` 打包進 .app。
- `requirements.txt` 加 `reportlab>=4.0`。

### Fix · pywebview + Keychain 啟動死結
這輪 build v0.5.0 時發現的長期潛伏 bug（v0.4.0 其實也中，只是開發機已預授權沒注意到）：新版 binary 第一次啟動時，macOS Keychain 想對新的 code signature 彈「允許存取 Happy Vision API Key」的提示，但 pywebview 視窗還沒開，提示框無處可顯 → `keyring.get_password` 無限 block → 整個 app 卡在啟動。
- `modules/secret_store.py`：所有 Keychain call 包一層 2 秒 timeout，超時就回空值，之後使用者在 UI 重填 key 後續存取就正常（ACL 已 cache）。
- `web_ui.py`：把 `load_config()` 跟 `auto_start_watcher()` 從 module-import 時搬到 `_post_start_init()`，在 pywebview 視窗出來 0.8 秒後才跑，讓 Keychain 提示有地方顯。
- 實測 clean new binary 啟動時間：9 秒（Keychain 兩段 × 2 秒 timeout + pywebview 開窗）。先前直接死結。

### Why
v0.3.x 之前整套系統沒有任何 cost 觀測 — 使用者跑 API 不知道自己花多少錢。15 萬張規模的場景特別重要，不知道實際成本就沒辦法評估 ROI 或 debug 預算爆炸。這版之後：每張花費可查、今日總額即時顯示、可匯出 PDF 給客戶或內部結算。Cost 面板也是後續 throughput 優化（RPM 調整、降解析度、batch API、pHash 去重）的量尺。

## v0.4.0 — 2026-04-18

### UI · Terminal Dense 視覺大改
- 整套前端 shell + 監控 + 設定頁改走 "Terminal Dense"（專業儀表板風，深色底 + JetBrains Mono 資料字 + Inter UI 字 + 紫色 accent + LED 功能色）。
- 設計來源：透過 `/design-shotgun` 兩輪比較（A Pro Monochrome / B Studio Workbench / C Photo-first → B-1 Terminal Dense 最終勝出）確立方向，完整 mockup + token 表存於 `~/.gstack/projects/severity4-Happy_Vision/designs/global-shell-20260418/`。
- `App.vue`：nav 改成 LED + ALL CAPS 商標 + 分頁 pill + 模型/時鐘資訊；新增持久 status strip（監控資料夾路徑 + queue/完成/失敗 即時計數）。
- `MonitorView.vue`：重寫為 action bar + 4 gauge tile（QUEUE/PROC/DONE/FAIL，含 LED + meter）+ dense RECENT RESULTS 表格（mono 檔名 + 狀態 LED + 備註 + 時間）。邏輯全保留（watchStore、SSE、enqueue、browser、detail modal、exports）。
- `SettingsView.vue`：改成 dark panel + kicker 標籤 + mono 輸入 + LED 狀態指示。API key / Watch folder / Model / Concurrency / Skip existing / Tester 全部保留。
- `style.css`：token 改為 B-1 Terminal Dense 配色（bg `#08090c`、accent `#9b7bff`、LED `success/warning/error/cyan`）+ 新增 `--font-mono` + 全域 `.led` / `.led-ok/warn/accent/error` / `led-pulse` / `.kicker` utilities。
- `index.html`：加 Google Fonts (Inter + JetBrains Mono) 預載、改 `lang="zh-Hant"`、title 改為 Happy Vision。

## v0.3.4 — 2026-04-17

### Reliability
- Gemini analyze: rate-limiter wait now capped at 60s (previously could block forever).
- Gemini analyze: retry on `DEADLINE_EXCEEDED`, `RESOURCE_EXHAUSTED`, `UNAVAILABLE`, `INTERNAL` (previously only HTTP numeric codes).
- exiftool batch: reader thread + queue with 30s timeout and kill-on-stall, preventing a hung exiftool from freezing the worker pool.
- exiftool batch: reject args containing `\n`, `\r`, or NUL — these silently corrupt the `-@ -` stdin protocol.
- Result store: fix empty CSV/JSON export when the analyzed folder is under a symlinked path (e.g. `/tmp` → `/private/tmp` on macOS).

### Security
- Logger: scrub Google API keys (`AIza...`), OAuth tokens (`ya29...`), `Bearer` / `Token` headers, and `api_key=` query params from all log records before writing to disk.
- Logger: greedy match on API-key regex so trailing characters beyond the standard 39-char key are also consumed.
- Tests: in-memory Keychain fixture prevents pytest runs from writing fake keys into the developer's real macOS Keychain.

### UX
- Settings: help text under the API Key input with a clickable **Google AI Studio** link guiding first-time colleagues to create a free key.
- New `/api/system/open_external` endpoint routes such links through the system browser instead of keeping them inside the pywebview frame. Scheme-validated (http/https only).
