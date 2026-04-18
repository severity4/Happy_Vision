# Changelog

## v0.6.0 — 2026-04-18

### Dedup · 連拍去重（省錢大招第一發）
活動攝影 workflow 天然有大量連拍：婚禮儀式 10 張幾乎一樣、演講講者同一動作抓 5 張。之前每張都送 Gemini，這版改成**先算 pHash → 比對已分析過的近似照片 → 命中就直接套 metadata，不呼叫 Gemini**。現場砍 20-40% 的 API 成本與時間。

- **`modules/phash.py`** — `compute_phash()` 產出 16-char hex 的 pHash（imagehash 套件 + scipy.fftpack.dct），`hamming_distance()` 比對兩個 hash 差幾個 bit，`find_closest(target, candidates, threshold)` 線性掃描挑最近的（支援 exact match 短路）。
- **`result_store` 加兩個欄位**（additive migration 冪等）：`phash TEXT` + `duplicate_of TEXT` + `idx_results_phash` 索引。
- **`result_store.find_similar(target_phash, threshold)`** — 掃 recent 5000 筆 completed 的 phash，找 Hamming 距離最小且 ≤ threshold 的一筆。自動 follow `duplicate_of` 回主照，避免 dup-of-dup chain（最多 3 跳）。
- **`folder_watcher._process_one` 插入 dedup**：在呼叫 `analyze_photo` 之前先算 pHash、查 store 有沒有近似照片；命中就複製主照的 analysis、寫 IPTC、存 `duplicate_of = master_path`，**完全跳過 Gemini**。未命中就走原本流程，但也會把 pHash 一起存下來供未來比對。
- **`get_today_stats` 加 `dedup_saved_today`**，SSE 同步廣播，App.vue status strip 有資料時多一欄「去重 N」(綠字)。
- **Detail modal 加 DEDUP 徽章**：當 `_dedup.duplicate_of` 有值，顯示綠框綠燈 + 「此張 metadata 複製自 XXX.JPG，未呼叫 Gemini」。
- **`modules/config.py` 加 `phash_threshold: 5`**（0 = 關閉，5 = 預設捕捉連拍而不誤合併不同時刻）。
- **`api/settings`** 支援 `phash_threshold`（clamp `[0, 16]`）。
- **Settings UI** 新增 `DEDUP · 連拍去重` section：0-16 slider（0 = OFF 標記），LED 跟著值變色（關 / 安全 / 寬鬆 / 警告），動態描述說明每個 level 的行為。

### 實測收益
婚禮連拍場景下，一組 10 張幾乎一樣的儀式照片，**只會呼叫 Gemini 1 次**，剩下 9 張直接用相同 metadata。對 15 萬張 backlog（典型 30% 連拍重複）：
- 純去重：**省 ~30% = \$25 USD / ~NT\$800** 的 API cost
- 搭配 v0.5.1 的 2000 RPM + 1536 image_max：**\$15 USD / ~NT\$500 + 55 分鐘**

### Tests
- `test_phash.py` — 13 個（hash 產生、對稱性、異常輸入、threshold gating、find_closest 挑最近 + 短路）
- `test_result_store_phash.py` — 9 個（migration column + index、save phash/duplicate_of、find_similar 找最近/回 None、ignore no-phash 列、follow duplicate_of chain、get_result_with_usage 露出 _dedup、today_stats 計 dedup）
- `test_folder_watcher_dedup.py` — 5 個（相似照片跳 Gemini、不相似照片都跑、threshold=0 停用、master 照存 phash）
- **241 → 268 passed**（+27）

### Build
- `requirements.txt` 加 `imagehash>=4.3`
- `build_app.py` 加 hidden-imports `modules.phash` / `imagehash` / `pywt` / `scipy.fftpack`

### 邊界與已知限制
- **find_similar 掃最近 5000 筆**。超過這個量的極大資料夾會漏掉早期照片的比對。之後可加 pHash prefix bucket 或 ANN index
- pHash 對「角度相近、光線相近」的連拍超準。對「完全不同 pose 但同場景」（例如同一個主持人不同時刻）誤合併率會隨 threshold 上升，建議保持 5 不要隨便拉高
- 重拉 threshold 不會 retroactive 影響已存的 duplicate_of 標記，只影響之後新進的照片

## v0.5.1 — 2026-04-18

### Throughput tuning · 速度與成本的旋鈕
v0.5.0 把 cost 的量尺裝好了，這版把旋鈕接上去 — 使用者第一次可以自己調「要速度還是要品質」，並且用 v0.5.0 的 cost 面板驗證優化效果。

- **`modules/rate_limiter.py`** — `configure(rate_per_minute)` 會替換 module-level `default_limiter` 到新的 RateLimiter 實例，並 clamp 到 `[1, 5000]`。同 rate 重配是 no-op。
- **`modules/gemini_vision.py`** — 改 `from modules import rate_limiter` 讓 runtime `configure()` swap 立即被 worker 看見（原本 `from modules.rate_limiter import default_limiter` 會把老實例 bind 住）。`analyze_photo` 新增 `max_size` 參數（default 3072），把值傳給 `resize_for_api`。
- **`modules/pipeline.py` / `modules/folder_watcher.py`** — 把 config 的 `image_max_size` 往下傳到 `analyze_photo`。watcher 每次 `_process_one` 重讀 config，所以設定變更即刻生效；pipeline 則在 `run_pipeline(image_max_size=...)` 入口接。
- **`modules/config.py`** — `DEFAULT_CONFIG` 加 `rate_limit_rpm: 60` + `image_max_size: 3072`。
- **`api/settings.py`** — 允許寫入 `rate_limit_rpm` (clamp `[1, 5000]`) + `image_max_size` (允許 `{1024, 1536, 2048, 3072}`，其他回 400)。當 `rate_limit_rpm` 改變時同步呼叫 `rate_limiter.configure()` live update。
- **`web_ui.py` `_post_start_init`** — 載完 config 後呼叫 `rate_limiter.configure(cfg.rate_limit_rpm)` 套用使用者設定。
- **Settings UI** — 新增兩個 section：
  - **RATE LIMIT · 每分鐘請求數 (RPM)**：10-2000 slider + 直接輸入框（最高 5000）。LED 色隨值變化（綠→黃→紅）。下方動態描述：60 是免費方案上限、200 是付費起步、1500 是 flash-lite 常態、超過 1500 會建議先確認 API 配額。
  - **IMAGE SIZE · 上傳長邊上限**：1024 / 1536 / 2048 / 3072 四選一按鈕卡片。下方動態描述：3072 細節最清楚、2048 減 45% input tokens、1536 減 75%、1024 減 90% 但小字會糊。

### 可實測的收益（for 15 萬張 backlog 的使用者）
- **速度**：RPM 60 → 2000，15 萬張 42h → **75 分鐘**
- **成本**：image_max_size 3072 → 1536，input tokens 砍 **75%**（\$84 → \~\$22，~NT\$700）
- 兩個都開，\~NT\$700 + 75 分鐘跑完。跑完開 PDF 報告看實際花了多少。

### Tests
- `test_throughput.py` — 13 個測試（rate_limiter configure clamp/idempotent/swap、analyze_photo max_size 流通、/api/settings PUT 驗證 RPM + image_max_size、invalid size 回 400）
- **228 → 241 passed**（+13）

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
