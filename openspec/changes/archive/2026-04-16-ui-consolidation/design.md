## Context

Happy Vision 目前有 5 個前端頁面（匯入/監控/進度/結果/設定），隨著 Watch Folder 成為主要使用模式，頁面結構需要從「功能分頁」轉為「場景分頁」。攝影師 95% 的時間只需確認監控狀態和瀏覽結果，不需要手動觸發批次分析。

現有前端資產：
- `ImportView.vue`：資料夾瀏覽器 + 觸發批次分析
- `WatchView.vue`：Watch 控制 + 狀態 + 最近處理列表
- `ProgressView.vue`：批次進度條 + 暫停/取消
- `ResultsView.vue`：照片 grid + 詳情 modal + 匯出
- `SettingsView.vue`：API Key + 模型 + 並行數量 + 跳過已處理
- `stores/analysis.js`：批次分析 SSE 狀態管理
- `stores/settings.js`：設定讀寫

## Goals / Non-Goals

**Goals:**
- 2 tab 結構（監控 | 設定），消除頁面冗餘
- 監控頁作為首頁，一頁完成所有日常操作（看狀態、看結果、手動加入資料夾、匯出）
- 統一結果列表（不分 Watch 或手動來源）
- 手動加入資料夾丟進 Watch queue，不開獨立 pipeline

**Non-Goals:**
- 不重寫後端 pipeline 或 Watch 核心邏輯（已完成且穩定）
- 不做分頁/虛擬捲動（現階段照片量不大）
- 不做 onboarding 引導流程（使用者是內部團隊，可口頭教學）
- 不改 API 結構（除新增 enqueue endpoint）

## Decisions

### 1. 2 tab vs. 3 tab

**選擇：2 tab（監控 | 設定）**

替代方案：3 tab 加一個「瀏覽」頁獨立顯示所有結果。

理由：攝影師不需要獨立的結果瀏覽器——他們在監控頁的結果列表已經可以看到每張照片的分析結果。獨立結果頁只在照片量非常大時才有價值，現階段不需要。匯出功能直接放在監控頁即可。

### 2. 手動加入資料夾的實作方式

**選擇：透過 Watch queue 統一處理**

替代方案：保留獨立的 `run_pipeline` 批次分析 + 獨立進度。

理由：照片分析不急，是為未來做準備。不需要「立即跑完」的批次模式。手動加入的資料夾掃描一次後丟進 Watch 的 queue，用同一套 worker 和並行設定處理。好處：不會搶資源、結果統一、程式碼更簡單。

### 3. 結果列表 vs. 照片 Grid

**選擇：先用列表（WatchView 的模式），點擊展開詳情 modal**

替代方案：直接用 ResultsView 的照片 grid。

理由：列表更適合「確認進度」的使用場景——看得到時間順序、成功/失敗狀態、處理速度。Grid 適合「瀏覽照片」但在 800x600 窗口裡一屏只能顯示 4-6 張，資訊密度不夠。列表一屏可以顯示 10-15 筆。未來如果需要照片 grid 瀏覽模式，可以在列表上方加一個切換按鈕。

### 4. 並行數量統一

**選擇：單一設定，範圍 1-10，放在設定頁**

理由：WatchView 和 SettingsView 各有一個並行滑桿造成困惑。手動加入的資料夾走同一個 queue，不需要獨立的並行設定。統一為 1 個，在設定頁管理。

### 5. watchStore 架構

**選擇：Pinia store + App 層級 SSE**

```
stores/watch.js
├── state: status, folder, queueSize, processing, completedToday, failedToday
├── recentItems: 最近處理列表
├── SSE: 在 App.vue onMounted 時 connectSSE()
├── actions: fetchStatus(), fetchRecent(), startWatch(), pauseWatch(), stopWatch()
└── enqueueFolder(path): POST /api/watch/enqueue
```

SSE 在 App 層級連線，因為不管在哪個 tab 都需要即時狀態。recentItems 用於監控頁的結果列表。

### 6. 監控頁版面配置

```
┌─ 狀態區 ─────────────────────────────────────┐
│  狀態燈號 + 路徑 + 統計數字 + 控制按鈕         │
│  + 加入資料夾分析（展開式資料夾瀏覽器）         │
└──────────────────────────────────────────────┘
┌─ 結果區 ─────────────────────────────────────┐
│  結果列表（點擊展開詳情 modal）                 │
│  匯出按鈕                                     │
└──────────────────────────────────────────────┘
```

狀態區固定在上方，不滾動（sticky）。結果區佔剩餘空間，可滾動。

## Risks / Trade-offs

**[失去照片 Grid 瀏覽]** → 現有 ResultsView 的照片 grid 在重構後被移除。Mitigation: 結果列表的詳情 modal 保留完整的照片分析資訊。未來可加「grid 模式」切換。

**[批次分析 pipeline 變成 dead code]** → `run_pipeline`、`analysisStore`、analysis API 不再被前端使用。Mitigation: 後端 API 保留不刪，CLI (`cli.py`) 仍然可用。前端只刪 view 和 store，不動後端。

**[小窗口塞不下]** → 800x600 窗口中，狀態區 + 資料夾瀏覽器展開時可能擠壓結果列表。Mitigation: 資料夾瀏覽器預設折疊，只顯示一行「+ 加入資料夾分析」按鈕。
