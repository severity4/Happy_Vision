## 1. Config 擴充

- [x] 1.1 在 `config.py` 的 `DEFAULT_CONFIG` 新增 `watch_folder`、`watch_enabled`、`watch_concurrency`、`watch_interval` 預設值
- [x] 1.2 新增 config 讀寫的測試驗證新欄位

## 2. FolderWatcher 核心模組

- [x] 2.1 建立 `modules/folder_watcher.py`，實作 `FolderWatcher` class 骨架（init、start、pause、resume、stop、state 屬性）
- [x] 2.2 實作 polling 迴圈：定時 `os.scandir` 遞迴掃描 JPG/JPEG，先查本機 DB 再 fallback 到 `has_happy_vision_tag()` 過濾
- [x] 2.3 實作 `file_size_stable()` 檔案就緒檢查（200ms 間隔、1 秒穩定窗口）
- [x] 2.4 實作處理佇列 + worker thread（ThreadPoolExecutor），呼叫 `analyze_photo` + `write_metadata` + `ResultStore.save_result`
- [x] 2.5 實作 concurrency 動態調整（runtime 更新 worker 數量）
- [x] 2.6 實作 callback 機制供 SSE 推送（on_processed、on_error、on_state_change）
- [x] 2.7 修改 `ResultStore.is_processed()` 使 `failed` 狀態的照片可被重試

## 3. Watch API Blueprint

- [x] 3.1 建立 `api/watch.py` blueprint，實作 `POST /api/watch/start`、`/pause`、`/resume`、`/stop`
- [x] 3.2 實作 `GET /api/watch/status` 狀態查詢端點
- [x] 3.3 實作 `POST /api/watch/concurrency` 動態調整並發
- [x] 3.4 實作 `GET /api/watch/events` SSE 事件串流
- [x] 3.5 實作 `GET /api/watch/recent` 最近處理記錄查詢
- [x] 3.6 在 `web_ui.py` 註冊 watch blueprint，App 啟動時根據 config 自動啟動 watcher

## 4. 前端 Watch Folder 頁面

- [x] 4.1 建立 `WatchView.vue` 頁面骨架，加入路由
- [x] 4.2 實作資料夾選擇區塊（復用現有 folder browser 元件）
- [x] 4.3 實作監控控制按鈕（開始/暫停/繼續/停止），根據 watcher 狀態切換顯示
- [x] 4.4 實作並發 slider（1–10）+ 即時白話說明文字
- [x] 4.5 實作即時狀態面板（佇列數/處理中/今日完成/今日失敗），接 SSE 更新
- [x] 4.6 實作最近處理列表（成功/失敗狀態、相對路徑、時間、失敗重試按鈕）
- [x] 4.7 實作錯誤狀態顯示（資料夾不可存取、API key 未設定）

## 5. 整合與測試

- [x] 5.1 FolderWatcher 單元測試：polling 偵測、檔案就緒檢查、狀態切換、去重邏輯
- [x] 5.2 Watch API 整合測試：各端點的正常與錯誤回應
- [ ] 5.3 用真實照片 E2E 測試：Lightroom 匯出模擬 → Watch 偵測 → 分析 → IPTC 寫入驗證
- [ ] 5.4 重啟恢復測試：config watch_enabled=true 時 App 啟動自動恢復監控
- [ ] 5.5 跨電腦去重測試：手動在照片寫入 HappyVisionProcessed tag，確認 watcher 跳過
