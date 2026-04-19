# Changelog

## v0.11.0 — 2026-04-19 · Observability + zombie detection(SRE audit 剩下的 HIGH)

v0.10.1 修了 CRITICAL/HIGH 的前半:安全 + idempotency。這版收尾 SRE audit 的後半:監控的可觀測性 + 殭屍 job 處理 + 背壓改善。

### 監控健康可見(HIGH)
凌晨 3 點背景 monitor 死了,早上起來什麼都不知道 — 之前的盲點。這版把狀態攤開:
- `batch_jobs` 加 3 欄:`last_polled_at`, `last_poll_error`, `consecutive_poll_failures`
- `GET /api/batch/health`:回 `{alive, last_tick_at, last_tick_error, active_jobs, consecutive_errors}`
- Monitor 每 tick 結束發 `batch_heartbeat` SSE event(含 active_jobs 數 + streak)
- Monitor 加 `health_snapshot()` 公開 thread-safe 狀態
- BatchJobsPanel 新增狀態徽章:`LIVE` / `RETRY ×N` / `STUCK 5min` / `MONITOR OFF` — tooltip 顯示詳情。3 分鐘沒 tick 就顯示 stuck

### 殭屍 job 自動判決(HIGH)
API key rotated / billing 撤銷 / quota 耗盡 → job 每次 poll 都失敗,之前會卡在 PENDING 直到 48h expired。這版:
- `record_poll_attempt(job_id, error=None)`:atomic 增減 `consecutive_poll_failures`,記錄 `last_poll_error`(500 字截斷)
- `_poll_one` 成功就 reset counter、失敗就 +1
- 超過 `MAX_POLL_FAILURES = 20`(約 20 分鐘持續錯)自動標 `JOB_STATE_FAILED`,pending items 全數 roll 到 failed,送 SSE 通知
- 一個 flaky job 不再影響其他 jobs 的 polling(per-job attribution)

### Backoff 去齊步走(MEDIUM)
多個 app 實例在同一秒 tick → Gemini 側 request spike。加 ±20% jitter 打散。

### Graceful shutdown(LOW)
`atexit.register(stop_background_monitor)` — pywebview quit 時 monitor 有 5s 清掉 in-flight 工作,WAL 不會殘留。

### API 形狀統一 + 402→403(code review MEDIUM)
- `POST /api/batch/submit` 和 `POST /api/analysis/start`(路由到批次)現在都回 `{status: "submitted", mode: "batch", ...}`。前端只看一個欄位。
- TierRequiredError 從 402 Payment Required 改成 403 Forbidden 配 `error_code: "tier_required"` — 402 很多 proxy/client 誤解,403 標準得多。

### 測試
- `tests/test_batch_observability.py` 9 tests(counter reset、truncate、zombie 判決、single flake 不誤判、recovery、health snapshot、endpoint variations、403 tier)
- 356 passing(v0.10.1 是 347,+9 新)

## v0.10.1 — 2026-04-19 · Security + Resumability hotfix(三方 audit + 一個前端 bug)

跑 Code Reviewer + SRE + Security 三組 agent 掃 v0.9-v0.10,抓到 CRITICAL/HIGH 五個。再加使用者回報一個前端 bug。都修。

### CRITICAL · 路徑 allowlist 被繞過(Security)
`/api/batch/submit` 和 `/api/batch/estimate` 沒檢查 `_path_is_allowed`。拿到 session token 的話可以指向 `~/.ssh` 把 JPG base64 塞進 JSONL 上傳到 Google。補 `_require_allowed_folder()` helper 照抄 `/api/browse` 的 pattern,home 或 registered root 外一律 403。

### HIGH · Materialise 不 resumable(Code Reviewer + SRE)
三個問題本質是同一個:
- mid-run crash 後 SUCCEEDED job 被 `list_batch_jobs(active_only=True)` 過濾掉,剩下 pending items 永遠沒處理
- Cold boot 重跑整個 loop,`-overwrite_original` 把使用者編輯過的 IPTC 蓋掉
- `ExiftoolBatch()` init 失敗(exiftool 不在)直接拋例外 → 整個 tick 掛掉 → job 永遠卡住

修:
- `_materialise_results` 跳過 `batch_items.status == 'completed'` 的,counters 從 DB 起算不是 0
- `_poll_one` 加 `needs_materialise` recovery flag:SUCCEEDED 但 `completed + failed < photo_count` 時再進 materialise
- ExiftoolBatch init 用 try/except 包,失敗 log + return,下次 tick 再試

### MEDIUM · Cancel/Delete/Get 跨帳號污染(Security)
`/api/batch/jobs/<id>/cancel` 把任何 job_id 直接送到 Gemini。token 外洩時可以干掉同 API key 下其他專案的 job。修成先查本地 `batch_jobs`,不在就 404。DELETE 也加 404 守門。

### LOW · `int(request.args.get(...))` 可能 500(Security)
`image_max_size=abc` 會拋 ValueError。換成 settings.py 一樣的 `_coerce_int`,壞值回 default 不崩。

### 前端 bug · 跳過引導按鈕失效(使用者回報)
`localStorage.getItem()` 不是 Vue reactive,`open` computed 沒追蹤它。點跳過 → localStorage 寫了,但 computed 沒重算 → wizard 不關。改用 `dismissed = ref(localStorage.getItem(...))`,skip/finish/startAndClose 同步更新 ref。`watch(props.force)` 在 force 翻 true 時 reset ref,讓 Settings「再跑一次」還能重開。

### 測試
- `tests/test_batch_security.py` 8 tests(path allowlist 三種路徑、int coerce fallback、job ownership 404、known job 放行)
- `tests/test_batch_monitor_resumable.py` 4 tests(skip completed items、exiftool init 失敗不崩、recovery re-entry、steady state early return)
- 347 passing(v0.10.0 是 335,+12 新)

## v0.10.0 — 2026-04-19 · Batch 成本預覽 + 確認對話框

v0.9 系列讓批次能跑穩了,現在讓使用者「送出前看到費用再按下去」。再也沒有不小心扛 $84 的事情。

### 流程
- Monitor 頁「📦 送批次」按鈕(只在 `batch_mode` 是 auto/always 時出現)
- 點按鈕 → 彈窗即時估算:**照片數 / 批次費用 / 預計完成時間** 三大數字
- 下面有「省 $X vs 即時模式 $Y(Batch 折扣 50%)」綠色對比條
- 再下面 breakdown:模型、圖片長邊、平均 tokens、分 chunk 數、已過濾統計
- 底部 Tier 1 付費提醒 + 去 AI Studio 綁卡的連結
- 取消 / 確認送出 兩顆按鈕,確認後才真的 POST `/api/batch/submit`

### Backend
- `modules/cost_estimator.py`:兩段式估算
  - **歷史均值**:如果 DB 裡同一個 model 有 ≥20 張 completed rows,用它們的實際 tokens 均值(最準)
  - **啟發式回退**:沒歷史時按 image_max_size 查表(1024 / 1536 / 2048 / 3072 → 500 / 1000 / 2000 / 3500 input tokens),基於 v0.9.0 e2e 真實量測
- `api/batch.py`:`GET /api/batch/estimate?folder=...&model=...&image_max_size=...&skip_existing=...&min_rating=...` 回 `CostEstimate` JSON
- 估算時會:
  1. 掃描資料夾(重用 `scan_photos`)
  2. 套 `skip_existing` 過濾已處理
  3. 套 `min_rating` 過濾(best-effort,exiftool 不在就跳過檢查不影響送出)
  4. 計算 chunk 拆分(3000 張/job)
  5. 套 Batch 50% 折扣、算 TWD 近似

### Frontend
- `components/BatchEstimateModal.vue`:backdrop blur 彈窗,三大數字 cards + breakdown + 送出/取消
- `components/BatchJobsPanel.vue`:條件顯示(batch_mode 開 OR 有 jobs),加「📦 送批次」按鈕,空狀態也顯示提示
- Tier 1 錯誤處理:後端回 402 tier_required 時,前端 toast + 引導去 billing

### 測試
- `tests/test_cost_estimator.py` 9 tests:歷史 vs 啟發式、50% 折扣斷言、skip_existing 過濾、空資料夾、chunk 計算、API endpoint 驗證
- 335 passing(v0.9.1 是 326,+9 新)

## v0.9.1 — 2026-04-19 · Batch 硬化 hotfix（3 個真 bug，外部 review + real e2e 抓到）

v0.9.0 送出後做了 real-API e2e 測試 + 外部 reviewer 狠 audit,三個問題全修:

### Bug 1 — JSONL response_schema type 大小寫不匹配（CRITICAL,v0.9.0 根本跑不起來)

Gemini Batch API 在 JSONL 裡的 `response_schema` 拒絕 JSON Schema 小寫的 `"type": "object"`,需要 proto enum 式的大寫 `"OBJECT"/"STRING"/"ARRAY"/"INTEGER"`。realtime SDK 自動 normalise,batch 不會。v0.9.0 送出的每一張照片都會 400 INVALID_ARGUMENT。

- `modules/gemini_batch.py`: 新增 `_normalize_schema_types()` 遞歸把小寫 type 升為大寫,在 `_build_request_dict` 使用
- 驗證方式:真跑了 3 張照片 → SUCCEEDED 8 分鐘 → fetch_results 全綠,title/keywords/tokens 全對
- 2 新 tests(schema_types_normalised_to_uppercase + normalize_schema_types 單元)

### Bug 2 — BatchMonitor state regression（CORRECTNESS,成功 job 被回寫成舊狀態)

`_materialise_results` 最後用 `job_row["status"]` 寫回 counters — 但 `job_row` 是 poll 前抓的,`_poll_one` 已經把狀態更新成 SUCCEEDED。這會讓剛完成的 job 被 regress 回 PENDING/RUNNING,UI 顯示錯、重啟後恢復判斷失準。

- `modules/result_store.py`: 新 `update_batch_job_counts()` — 只動 completed_count/failed_count,絕不碰 status 或 completed_at
- `modules/batch_monitor.py`: 改用 counts-only update
- 1 新 regression test(`test_update_batch_job_counts_preserves_status`)驗證 SUCCEEDED + completed_at 不會被回寫覆蓋

### Bug 3 — Test 不夠 hermetic(settings API tests 污染 ~/.happy-vision)

原本 conftest 只隔離 Keychain,沒隔離 `HAPPY_VISION_HOME`。所以 `test_settings_api_*` 會寫到真的 `~/.happy-vision/config.json`。在 sandboxed CI 環境會失敗;在本機會靜默污染使用者設定。

- `tests/conftest.py`: 新增 autouse fixture `_isolate_happy_vision_home` 把 env var redirect 到 per-test tmp_path
- `tests/test_hermetic.py`: 3 新 tests 驗證 sandbox 生效 + 真 home config 不被污染

### 測試
326 passing(v0.9.0 是 320,+6 新)。

## v0.9.0 — 2026-04-19 · Gemini Batch API（省 50% 的非同步模式）

15 萬張照片批量回補的場景,即時模式要跑 ~17 分鐘、花 $4.5。批次模式 24h 內完成、花 $2.25。這版把批次管道接上。

### 功能
- **設定頁新增「BATCH MODE」section**:OFF / AUTO / ALWAYS 三檔
  - OFF = 現在的即時行為(預設)
  - AUTO = 一批 ≥ `batch_threshold` 張自動切批次(預設 500)
  - ALWAYS = 永遠走批次
- **⚠ Tier 1 付費提示**:批次 API 要求 Google AI Studio 綁定信用卡的付費帳號,免費額度不支援。Banner 裡直接有「去 AI Studio 設定付費 →」按鈕,走 `open_external` 打開 `https://aistudio.google.com/app/plan_information`
- **Monitor 頁新增 Batch Jobs 面板**:顯示進行中 + 剛完成的 jobs,每個 job 顯示進度條、狀態燈(PENDING/RUNNING/SUCCEEDED/FAILED/EXPIRED)、24h SLO 預計完成時間、取消按鈕
- **背景 monitor 線程**:每 60 秒 poll 一次 Gemini、完成後自動 download output JSONL、寫 IPTC metadata、存進 SQLite — 使用者可以關 App 明天再看,重開會接著跑

### 實作
- `modules/gemini_batch.py`:submit / poll / fetch / cancel 四個核心操作,JSONL 建構時 base64 內聯 3072px 以下的圖片
  - 自動 chunk(3000 張/job,<1.5GB payload,低於 Gemini 2GB 限制)
  - `mime_type` 走 `"jsonl"` → `"text/plain"` 的 fallback(SDK issue #1590 workaround)
  - `TierRequiredError` 友善包裝 PERMISSION_DENIED,前端收到 402 後顯示付費 CTA
- `modules/batch_monitor.py`:daemon thread,指數回退的 polling,SSE event_sink 注入
- `modules/result_store.py`:新增 `batch_jobs` + `batch_items` 兩張表,additive migration
- `modules/pipeline.py`:`submit_batch_run()` + `route_mode()` 決策函數
- `modules/pricing.py`:`calc_cost_usd(..., batch=True)` 應用 50% 折扣;`BATCH_DISCOUNT_MULTIPLIER` 具名常數
- `api/batch.py`:新 blueprint,`/submit`, `/jobs`, `/jobs/<id>/cancel`, `/jobs/<id>` DELETE, `/stream` SSE
- `api/analysis.py`:`/start` 根據 `batch_mode` config 自動 route 到批次提交
- `api/settings.py`:`batch_mode` enum 驗證 + `batch_threshold` clamp 1-50000

### 測試
- `tests/test_gemini_batch.py` 16 個測試(snake_case 驗證、KeyError fallback、tier error、success + error line parsing)
- `tests/test_result_store_batch.py` 6 個(persistence、active filter、delete cascade)
- `tests/test_batch_routing.py` 14 個(decision matrix + settings API validation)
- 共 320 tests passing(v0.8.1 是 284)

### 已知限制
- 目前沒實作 Vertex AI path(只支援 Gemini Developer API);Vertex 的 2GB 上限更寬鬆,之後可加
- 批次送出後 app 中途被殺進程,再開時會從 DB 繼續 poll — 但已經 download 的 output 不會重算,算是功能而非 bug
- 單一 job 可能 `JOB_STATE_PARTIALLY_SUCCEEDED`(少數照片 parse 失敗),目前 UI 當作 SUCCEEDED 處理,差別在 `failed_count` 欄位

## v0.8.1 — 2026-04-19 · Onboarding Wizard（first-run 三步引導）

UX Researcher 早先指出的 P0 是「首次開 app 落在空白監控頁，設定頁 8 個 section 不知從何下手」。之前一直沒補，這版補上。

### 行為
首次啟動時（沒 API key **且** 沒監控資料夾、且 localStorage 沒標記過「已跳過」），自動跳出覆蓋式對話框：

1. **Step 1 — API Key**：貼入 `AIzaSy...`，點「儲存並繼續」→ 寫 Keychain + 下一步
2. **Step 2 — 監控資料夾**：用 folder picker 選資料夾，顯示每層子資料夾的 JPG 數，點「選擇此資料夾」→ 寫 config + 下一步
3. **Step 3 — 準備好了**：顯示已設定摘要（API Key 已設 · 資料夾 · Flash Lite · Dedup 開啟），點「▶ 開始監控」→ 直接啟動 watcher，關閉 wizard

任何一步都可以「跳過引導」或「之後再...」關閉，`localStorage.hv_onboarding_dismissed=1` 之後不再自動開。

### 聰明跳步
如果半途 quit 再開（例如已填 API key 但沒選資料夾），重開時會自動跳到 Step 2，不會重新要你貼 key。

### 重新觸發
**設定 → 開發者工具 → ONBOARDING · 首次設定引導 → 再跑一次**。會清 localStorage flag 並強制開 wizard。

### 實作
- `components/OnboardingWizard.vue`：單一組件，內部有 3 個 step section + 本地 folder picker（重用 `/api/browse` 端點）
- `App.vue` 掛上，`onMounted` pre-load settings 讓 wizard 有 `settings.loaded` 當前提
- `provide('triggerOnboarding')` inject 到 SettingsView 的「再跑一次」按鈕

### 不 ship 的錯
- 目前不驗證 API key 是否真的有效（打 Gemini 一次驗證太貴，留到之後加）
- Step 2 folder picker 起點是預設 home；P1 的「最近監控 / 桌面 / 下載 / LucidLink」快捷還沒做

## v0.8.0 — 2026-04-19 · Lightroom Rating 預篩

### 🎯 新功能：依 Lightroom 星等過濾，不處理 reject 跟未評分

攝影師 workflow 通常是「Lightroom 選片 → 只交件 ≥3 星」。之前 Happy Vision 會 tag 整個資料夾所有 JPG（含 1-2 星 reject + 未評分廢片），這些都是浪費。v0.8.0 加 `min_rating` 設定，folder_watcher 掃描時跳過 rating 低於門檻的照片。

### 量化收益（承接 v0.6.0 / v0.5.1）
假設典型選片率 30%（15 萬張只有約 4.5 萬張 ≥3 星）：
- min_rating=3 時，folder_watcher 不會把 1-2 星 / 未評分的照片送進 queue
- **額外省 70% API 成本 + 70% 處理時間**（疊加 v0.6.0 dedup + v0.5.1 throughput）

全堆疊更新（15 萬 JPG，30% 選片率，連拍去重 5，2000 RPM，1536 max_size）：
- v0.7.2 base: 55 分鐘 / \$15 / NT\$500
- **v0.8.0 min_rating=3：** **17 分鐘 / \$4.5 / NT\$150**（省 70% 時間 + 70% 金額）

### 實作
- `modules/metadata_writer.py`：新增 `read_rating_batch(batch, photo_path) -> int`，透過 persistent exiftool 讀 XMP:Rating / EXIF:Rating。Lightroom 寫入的位置對到 XMP:xmp:Rating。
- `modules/folder_watcher.py`：掃描時每張照片先讀 rating，低於 `min_rating` 就跳過（不存 DB，使用者之後在 Lightroom 改 rating 重掃會重抓）。log 印出跳過總數。
- `modules/config.py`：`DEFAULT_CONFIG["min_rating"] = 0`（0 = 停用）。
- `api/settings.py`：clamp `[0, 5]`，非法值不會 500。
- `SettingsView.vue`：進階效能新增 `MIN RATING · Lightroom 星等預篩` slider，OFF / 1★ / 2★ / 3★ / 4★ / 5★，動態描述說明每個 level 對應的省錢效果。

### Tests
- `tests/test_rating_filter.py` — 10 個（read_rating_batch 各種輸入、空值、clamp、settings API 接受 / clamp）

### 其他 (from v0.7.x carryover that got delayed)
- `api/system.open_external` 的 host allowlist 測試對齊（`example.com` 改成 `github.com`）

### 升級注意
`min_rating` 預設 0 = 停用。現有使用者升級後行為不變。要省錢：Settings → 進階效能 → MIN RATING 拉到 3★（或你習慣的交件門檻）。

## v0.7.2 — 2026-04-19 (hotfix · Keychain 反覆要密碼)

### 🔴 使用者場景：每次開 App 都要輸入 macOS 登入密碼

User reported morning of v0.7.1: 「一直叫我輸入登入密碼」(keeps asking for login password). Root cause: PyInstaller default `codesign --sign -` (ad-hoc) produces a new binary hash on every rebuild. macOS Keychain indexes its per-app access control entries (ACLs) by the designated requirement, which for ad-hoc signed apps collapses to the binary hash. New build = new hash = no ACL match = macOS must re-prompt for the keychain password.

**Fix:** Ship every build with a **stable self-signed code-signing identity** (`Happy Vision Developer (Local)`). Keychain now matches ACL by the signing identity instead of binary hash → same identity across rebuilds → one «Always Allow» click persists across every future version.

### 如何啟用
One-time setup (在 Happy_Vision repo 目錄跑一次即可)：

```
python3 build_app.py --setup-codesign
```

這會：
1. 用 openssl 生成 self-signed cert（RSA 2048，10 年，Code Signing EKU）
2. 存到 `~/.happy-vision-codesign/`
3. Import 進 login keychain，標記為 code signing 受信任
4. 下一次 `make app` 會自動用這個身份簽 .app

**Note：** 此憑證只在本機生效；不是 Apple 公證，不能公開分發（但我們也沒公開分發，內部工具 OK）。

### Build flow
- `build_app.py` build 完 .app 後自動檢查 `Happy Vision Developer (Local)` 身份是否存在
- 存在 → `codesign --force --deep --sign "Happy Vision Developer (Local)" --identifier com.inout.HappyVision`
- 不存在 → 印出警告，fallback 到 ad-hoc（跟之前一樣會反覆要密碼）

### Security note
`com.inout.HappyVision` identifier + self-signed cert ≠ notarized app。Gatekeeper 仍會跳 "rejected"（這是我們一直的狀態），但對 Keychain ACL 而言足夠穩定。如果未來想發給外部同事，需要 `$99 Apple Developer` + notarize。

## v0.7.1 — 2026-04-19 (hotfix · v0.7.0 UX 其實沒 ship)

Evidence Collector 驗收 v0.7.0 時發現 **所有 UX 修改實際沒被打進 .app**：
- 「進階效能」/「開發者工具」collapsible 不存在於 bundle
- Save toast 不存在於 bundle
- Disabled button tooltip `title=""`

根因是 `build_app.build_frontend()` 看到 `frontend/dist/` 已存在就會 skip `npm run build`。我在 v0.7.0 時改了 Vue 原始碼但沒手動 `rm -rf frontend/dist`，所以 PyInstaller 打包的是前一天 v0.6.1 時代的 bundle。

### 🔴 Critical
- **`build_app.py` 永遠跑 `npm run build`** — 再也不 skip。另外加 sanity check 驗證 `index.html` + `assets/` 確實產出，log 印出 bundle 檔名 + KB，release audit 可驗。
- **SSE 初始 30s 誤報「連線中斷」** — `api/watch/events` 以前只有在第一個事件或 30s keepalive 才吐 bytes，導致 EventSource `onopen` 30 秒都沒 fire，UI 顯示紅色斷線 badge 半分鐘。現在 stream 開頭立即 `yield ": connected\n\n"`，`onopen` 瞬間觸發。keepalive 間隔也從 30s 調短到 15s，掉線偵測更快。

### Minor
- `/api/settings` GET 的 `app_version` 改從 `web_ui._get_version()` 讀，跟 `/api/health` 對齊（原本一個 "dev" 一個 "0.7.0"）。
- 新增 `api/system.py` host allowlist（`aistudio.google.com` / `ai.google.dev` / `console.cloud.google.com` / `github.com`）— Security M4。`open_external` 原本只檢查 scheme，現在加 host 白名單防止被當 phishing 跳板。
- Logger regex 補洞 — 加上 Authorization header / X-Goog-Api-Key / Basic auth / 1//... OAuth refresh token / sk-ant-... / 更寬的 API key 模式（≥20 chars 而非 ≥35，抓住 truncated log 的 tail）— Security L1。
- PDF 報告封面新增「**連拍去重省下 N 張 ≈ \$X**」— 讓使用者直接看到 dedup 帶來的 ROI。需要有實際 dedup 才會顯示。
- 新增 `test_secret_store_cache.py` (5 tests) — regression gate，防 v0.7.0 的 200x PUT 加速被偷偷破壞。

## v0.7.0 — 2026-04-19 (穩定性 + 效能 + UX 全面硬化)

本版整合了 5 個專業 agent（Code Reviewer, Evidence Collector, Security, UX Researcher, SRE）的深度 review findings，修掉 4 個 CRITICAL + 7 個 HIGH bug，量化改進 15 萬張 backlog 場景的效能，並處理 UX P0 polish。

### 🔴 CRITICAL fix (Code Reviewer + Evidence Collector)

- **Dedup chain resolution bug**（`modules/result_store.py`）— `find_similar` 的 for/else 語意錯誤加上 `duplicate_of` 誤指中間節點的 bug，會讓連拍去重鏈累積錯誤資料。改成正確追到真正 master + 4-hop cap + fetch-first-then-resolve 架構。
- **Settings PUT 卡 4-6 秒**（`modules/secret_store.py`）— Evidence Collector 發現 UI 按按鈕後設定不會 persist。root cause：每個 PUT 打 Keychain 2-4 次，每次最多 2s timeout，累積起來瀏覽器 abort。修法：在 process memory 加 key cache，首次載入後的 get_key 全部免費，只有 set_key 會真正碰 Keychain。**PUT 從 4-6s 降到 <5ms**。
- **SSE callback 每次事件開新 ResultStore**（`api/watch.py`）— SRE F-04。每張照片處理完都 `ResultStore() + get_today_stats() + close()`，重跑 6 個 ALTER TABLE + WAL checkpoint。15 萬張浪費 **25 分鐘純 SQLite open/close**。改用 module-level singleton。
- **DB fallback 會靜默丟資料**（`modules/result_store.py`）— 原本主路徑 sqlite 失敗 fallback 到 `/tmp/happy-vision/`，重開機資料全沒。改成 `~/.happy-vision-fallback/` + loud error log。
- **API key 被空字串 PUT 清掉**（`api/settings.py`）— 前端 re-PUT GET 回來的 settings object（其中 `gemini_api_key: ""`），會觸發 `secret_store.set_key("")` → `clear_key()` → Keychain 被清空。修法：api/settings PUT 只在值非空且非 masked 時才更新 key。

### 🟠 HIGH fix

- **pHash 忽略 EXIF 旋轉**（`modules/phash.py`）— 同一張照片旋轉 metadata 不同會產生不同 hash，誤判為非重複。加 `ImageOps.exif_transpose`。也加 `LOAD_TRUNCATED_IMAGES=True` 讓還在寫入的 JPEG 也能算。
- **ExiftoolBatch kill 後不會重啟**（`modules/metadata_writer.py`）— 一旦 kill-on-stall 觸發，後續每張照片都會因為 `self._proc` 已死而 mark_failed。抽出 `_spawn` + `_ensure_alive`，掛掉下次 `_run_batch` 自動重啟。
- **rate_limiter swap race**（`modules/rate_limiter.py`）— configure() 時舊 limiter 可能還有 waiter 卡在 token bucket 上，沒人 notify 它們。加 `close()` 方法 + `_closed` flag，swap 時 notify_all 讓舊 waiter 立刻 fail fast。
- **SSE 連線中斷 token 過期**（主要是 UI 層）— v0.6.1 白畫面修掉了但 EventSource 重連會用舊 token。這版新增 shared store 減少 open/close，間接降低失敗機率。
- **settings API 接受 garbage input**（`api/settings.py`）— concurrency=999、model="hacker-9000" 這種明顯錯誤的值以前會存進 config。改成：
  - `concurrency` / `watch_concurrency` clamp `[1, 10]`
  - `watch_interval` clamp `[1, 3600]`
  - `model` 白名單 `{lite, flash}`
  - 字串長度 cap 500
  - 型態錯誤（string concurrency 等）→ 400 而非 500
- **save_config 每次必寫 Keychain**（`modules/config.py`）— 即使只改 `phash_threshold` 也會呼叫 `secret_store.set_key`。改成先比對 cache 再決定是否真寫。
- **API key GET leak**（`api/settings.py`）— 原本回傳 `...XXXX` 最後 4 碼，對已拿到 token 的攻擊者可減少 key 熵。完全不回傳任何 key 片段，只回 `gemini_api_key_set: bool`。

### ⚡ 效能量化（for 15 萬張 backlog，Evidence Collector + SRE 實測路徑）

- **`WatchSSECallbacks` 重用 store** — 節省 **25 分鐘**純 SQLite open/close
- **`find_similar` 只查 (file_path, phash)，不拉 result_json** — 原本每次 fetch 5-15MB，現在 ~1MB，**I/O 減 10 倍**
- **`has_happy_vision_tag_batch` 用 persistent exiftool 而非每張 fork** — 15 萬張第一次掃從 ~8 小時降到 <1 分鐘（Perl 啟動 ~200ms × 150k = 8h → batch 消除）
- **secret_store memory cache** — 設定 PUT 從 4-6s 降到 <5ms（第二次以後）

### 💅 UX P0 polish (UX Researcher findings)

- **Global toast system** — `components/ToastHost.vue` + `utils/toast.js`。所有 Settings save 完成顯示綠色 toast，失敗顯示紅色 toast。原本 fire-and-forget 零回饋
- **Disabled button tooltips**（`MonitorView.vue`）— 開始監控 / 加入資料夾 disabled 時會顯示「請先到設定頁填寫 API Key / 選擇監控資料夾」
- **中文錯誤訊息 mapping**（`utils/errors.js`）— 把 `429` / `DEADLINE_EXCEEDED` / `exiftool not found` / `connection refused` / `PIL parse` 等 raw 錯誤映射到攝影師看得懂的中文。原 raw 字串保留為「技術細節」放在 modal 折疊區
- **設定頁分組**（`SettingsView.vue`）— 基本（API Key / Watch Folder / Model）永遠展開；「進階效能」（RPM / Image Size / Dedup / Concurrency / Skip Existing）跟「開發者工具」（Tester）預設折疊。降低新手認知負擔
- **API Key 不再顯示 `...XXXX` 後 4 碼** — UI 直接顯示「已啟用」

### Tests

- 既有 268 tests 全部依然綠。
- 新測試（`_isolate_keychain` 加 cache invalidate）保證 secret_store cache 不污染 tests
- ruff 無 warning

### 建議升級流程
v0.6.x → v0.7.0 是 in-place 升級，DB 自動 migration，Keychain 裡的 API key 不會動。首次打開因 Keychain ACL binding new signature 會有 2 秒延遲，之後全速。

## v0.6.1 — 2026-04-18 (hotfix)

### Fix · 新版 .app 第一次開出現白畫面
使用者回報 v0.6.0 .app 雙擊打開是白畫面。Root cause：每次新 build 的 binary 有新的 code signature，macOS Keychain 把它當新 app，`_post_start_init` 中的兩次 Keychain call 會各 block 到 2 秒 timeout（共 4 秒）才放行。在這 4 秒內 Flask 還沒 bind port 8081，而 pywebview 視窗在 t=0 就想載 `http://127.0.0.1:8081/`，連線被拒 → WebKit 顯示白畫面且不 retry。

（v0.5.0 首次 release 時也有這個問題，但後續版本在開發機上都已經 pre-authorize 過 Keychain，沒踩到。v0.6.0 一發到使用者手上就炸了。）

修法：**把 Flask binding 跟 Keychain init 解耦**：
- `web_ui.py` 的 `_run_flask` 不再 pre-init，直接 `app.run()`
- 另開一條 `_deferred_init` thread 延遲 1.5 秒後跑 `_post_start_init`（等 pywebview 視窗出來）
- 主 thread 用 `socket.create_connection` poll port 8081 直到 Flask ready（通常 < 1 秒）才開 pywebview 視窗。10 秒內都沒 ready 就 raise

這樣 pywebview 必然載得到 Flask，Keychain 提示在視窗出來後才彈，不會卡死啟動。

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
