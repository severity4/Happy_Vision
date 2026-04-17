## Why

修圖師在 Lightroom 修圖後匯出照片到共享資料夾（透過 LucidLink 同步），目前需要手動開啟 Happy Vision、選擇資料夾、按開始分析。這打斷了他們的修圖工作流程。需要一個 Watch Folder 功能，讓 App 自動監控指定資料夾，偵測新照片並在背景完成分析與 metadata 寫入，修圖師完全不需要離開 Lightroom。

## What Changes

- 新增 Watch Service：以 polling 方式定期掃描指定資料夾（含子資料夾），偵測未處理的照片並自動送入分析 pipeline
- 以 IPTC/XMP metadata 作為跨電腦去重的 source of truth（多台 Mac 透過 LucidLink 共享資料夾時，不會重複分析）
- 新增檔案就緒檢查：檔案大小穩定性驗證，確保 Lightroom 匯出完成後才開始分析
- 新增 Watch 狀態控制 API：開始 / 暫停 / 停止，支援 SSE 即時狀態推送
- config.json 新增 watch 相關設定（watch_folder、watch_enabled、watch_concurrency），App 重啟自動恢復監控
- 前端新增 Watch Folder 頁面：資料夾選擇、並發 slider（附白話說明）、狀態顯示、處理歷史

## Capabilities

### New Capabilities
- `folder-watcher`: 資料夾輪詢偵測引擎——定時掃描、檔案就緒檢查、IPTC 去重判斷、佇列管理
- `watch-api`: Watch 狀態控制的 REST API + SSE 即時推送（開始/暫停/停止/狀態查詢）
- `watch-ui`: 前端 Watch Folder 頁面——資料夾選擇、並發控制、狀態面板、處理歷史列表

### Modified Capabilities
（無既有 spec 需要修改，pipeline 和 metadata_writer 透過現有 API 呼叫即可）

## Impact

- **後端新增模組**：`modules/folder_watcher.py`（Watch Service 核心）
- **新增 API blueprint**：`api/watch.py`（控制 + SSE）
- **修改 config.py**：`DEFAULT_CONFIG` 新增 watch 相關預設值
- **修改 web_ui.py**：註冊新 blueprint、App 啟動時自動恢復 watch
- **前端新增頁面**：Watch Folder 視圖 + 路由
- **修改 result_store.py**：`is_processed()` 需考慮 failed 狀態的重試邏輯
- **依賴**：無新增外部依賴（純 Python 標準庫 polling，不用 watchdog）
