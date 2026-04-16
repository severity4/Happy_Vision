## 1. 後端：enqueue API + FolderWatcher 擴充

- [x] 1.1 在 `modules/folder_watcher.py` 新增 `enqueue_folder(path)` 方法：掃描資料夾、去重、加入現有 queue
- [x] 1.2 在 `api/watch.py` 新增 `POST /api/watch/enqueue` endpoint（含 watcher 未啟動時自動啟動）
- [x] 1.3 enqueue API 單元測試

## 2. 前端：watchStore

- [x] 2.1 建立 `stores/watch.js` Pinia store（state、SSE 連線、control actions、enqueueFolder）
- [x] 2.2 在 `App.vue` onMounted 初始化 watchStore SSE 連線
- [x] 2.3 SSE 斷線重連邏輯

## 3. 前端：MonitorView 監控頁

- [x] 3.1 建立 `MonitorView.vue` 骨架 + 路由設定（`/` 指向 MonitorView）
- [x] 3.2 實作狀態面板：燈號、路徑、統計數字、控制按鈕（讀取 watchStore）
- [x] 3.3 狀態面板 sticky 定位（滾動時固定在上方）
- [x] 3.4 實作「+ 加入資料夾分析」：展開式資料夾瀏覽器、選擇後呼叫 enqueueFolder
- [x] 3.5 實作結果列表：從 watchStore.recentItems 渲染、成功/失敗狀態、相對路徑、時間
- [x] 3.6 實作詳情 modal：點擊結果項展開（復用 ResultsView 的 modal 設計）
- [x] 3.7 實作匯出按鈕（CSV / JSON），連結到現有 `/api/export/*`
- [x] 3.8 監控未設定 / API Key 未設定的引導狀態

## 4. 前端：設定頁改造

- [x] 4.1 在 SettingsView 新增「監控資料夾」設定區（資料夾瀏覽器 + 儲存）
- [x] 4.2 並行數量統一為 1 個（範圍 1-10，附白話說明），移除 Watch 獨立滑桿概念
- [x] 4.3 確保設定頁改動即時反映到 watchStore（如資料夾路徑變更）

## 5. 導航與路由整理

- [x] 5.1 更新 `App.vue` navLinks 為 2 tab：監控 | 設定
- [x] 5.2 更新 `router.js`：`/` → MonitorView、`/settings` → SettingsView，移除舊路由
- [x] 5.3 刪除舊頁面：`ImportView.vue`、`WatchView.vue`、`ProgressView.vue`、`ResultsView.vue`
- [x] 5.4 刪除 `stores/analysis.js`（批次分析 store，不再使用）

## 6. 驗證

- [x] 6.1 前端 build 通過
- [x] 6.2 全部後端測試通過
- [ ] 6.3 手動 E2E：開啟 App → 確認監控狀態 → 加入資料夾 → 看結果列表 → 匯出
