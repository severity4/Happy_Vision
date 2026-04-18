# Changelog

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
