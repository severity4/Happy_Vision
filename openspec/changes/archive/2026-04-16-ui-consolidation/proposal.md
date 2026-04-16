## Why

Watch Folder 功能上線後，App 的 5 tab 結構（匯入/監控/進度/結果/設定）出現嚴重冗餘：匯入和監控做同樣的事（分析照片），進度只服務批次不服務監控，結果頁不區分來源。攝影師每天開 App 落在「匯入」頁，但 95% 的時間只需要確認「監控在跑嗎？跑了多少？」。需要從使用者角度重整頁面架構，統一為「一個處理佇列，兩種方式餵照片」的概念。

## What Changes

- **刪除 4 個頁面**：ImportView（匯入）、WatchView（監控）、ProgressView（進度）、ResultsView（結果）
- **新建 MonitorView**（監控，首頁）：合併狀態顯示 + 手動加入資料夾 + 結果列表 + 匯出，一頁完成所有日常操作
- **改造 SettingsView**：新增監控資料夾選擇區、並行數量統一為 1 個（1-10），移除 WatchView 的獨立滑桿
- **導航從 5 tab 縮為 2 tab**：監控 | 設定
- **新增 watchStore**（Pinia）：將 WatchView 的 local state 提升為全域 store，SSE 連線在 App 層級管理
- **新增後端 API `POST /api/watch/enqueue`**：手動加入資料夾，掃描後丟進 Watch queue（不開新 pipeline）
- **結果列表點擊展開詳情**：復用 ResultsView 的 modal 設計，在監控頁內展開，不跳頁

## Capabilities

### New Capabilities
- `monitor-page`: 統一監控首頁——狀態面板、手動加入資料夾、結果列表（含展開詳情 modal）、匯出功能
- `watch-store`: Pinia 全域 store 管理 Watch 狀態，SSE 連線從 App 層級驅動
- `enqueue-api`: 手動加入資料夾的後端 API，掃描後丟進現有 Watch queue

### Modified Capabilities
（無既有 spec 需修改）

## Impact

- **前端刪除**：`ImportView.vue`、`WatchView.vue`、`ProgressView.vue`、`ResultsView.vue`、`stores/analysis.js`
- **前端新增**：`MonitorView.vue`、`stores/watch.js`
- **前端修改**：`App.vue`（nav 2 tab）、`router.js`（2 routes）、`SettingsView.vue`（新增監控資料夾設定）
- **後端新增**：`POST /api/watch/enqueue` endpoint in `api/watch.py`
- **後端修改**：`modules/folder_watcher.py`（新增 `enqueue_folder` 方法）
- **依賴**：無新增外部依賴
