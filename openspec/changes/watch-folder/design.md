## Context

Happy Vision 目前的工作流程是「手動選擇資料夾 → 按開始 → 等待完成」。修圖師使用 Lightroom 修圖後，透過 LucidLink 將成品照片同步到共享雲端資料夾。多位攝影師可能同時從不同 Mac 輸出到同一個 LucidLink 掛載的資料夾結構中。

現有基礎設施：
- `pipeline.py`：已有 `scan_photos`（遞迴掃描）、`skip_existing`、`PipelineState`（pause/cancel）
- `metadata_writer.py`：已有 `has_happy_vision_tag()` 可判斷照片是否已被 Happy Vision 處理過
- `result_store.py`：SQLite 本機結果儲存，有 `is_processed()` 和 `mark_failed()`
- `config.py`：JSON config 讀寫
- `api/analysis.py`：SSE 即時推送機制
- 前端：Vue 3 + 四個 View（Import/Progress/Results/Settings）

## Goals / Non-Goals

**Goals:**
- 修圖師設定一次監控資料夾後，App 自動在背景偵測與處理新照片
- 透過 IPTC/XMP tag 跨電腦去重，多台 Mac 不會重複分析同一張照片
- 提供直覺的控制介面（開始/暫停/停止）和即時狀態回饋
- App 重啟後自動恢復先前的監控設定
- 使用者可自行調整並發數量，並看到白話說明理解影響

**Non-Goals:**
- 不做系統級 daemon / launchd 服務（App 要開著才監控）
- 不做 watchdog filesystem event（LucidLink 掛載不可靠），用 polling
- 不做多資料夾同時監控（一個根目錄，遞迴掃子資料夾即可）
- 不做處理完搬移檔案（照片留在原地，metadata 寫回照片本身）

## Decisions

### 1. Polling vs. Watchdog

**選擇：Polling（定時 os.scandir）**

替代方案：Python `watchdog` 套件使用 OS 原生 FSEvents/inotify。

理由：LucidLink 掛載的 volume 上，其他電腦寫入的檔案不一定觸發本機 FSEvents。Polling 不依賴 OS 事件，掃到就處理，在任何 virtual filesystem 上都可靠。掃描間隔預設 10 秒，對修圖師完全無感。無新增外部依賴。

### 2. 跨電腦去重策略

**選擇：讀取 IPTC/XMP metadata（`has_happy_vision_tag()`）**

替代方案：
- 共用 SQLite DB 放在 LucidLink → SQLite 不支援多機同時寫入
- 用 `.done` sidecar 檔案標記 → 增加檔案雜亂，違反「資料夾保持乾淨」原則

理由：Happy Vision 分析後會寫入 `Instructions: HappyVisionProcessed` tag 到照片 IPTC。`has_happy_vision_tag()` 已經存在。照片本身就是 source of truth，LucidLink 同步 metadata 後其他電腦即可辨識。Race condition 窗口極短（兩台同時開始分析同一張），最差情況只是多花一次 API call，不會損壞資料。

### 3. 檔案就緒檢查

**選擇：檔案大小穩定性檢查（1 秒內大小不變 → 就緒）**

替代方案：
- `open(path, 'rb+')` file lock → macOS 不鎖定寫入中的檔案，不可靠
- 固定延遲等待 → 無法適應不同檔案大小

理由：Lightroom 批次匯出時檔案一建立就存在於磁碟，但內容還在寫入。每 200ms 檢查檔案大小，連續 1 秒不變即視為完成。這是 DaVinci Resolve、ShotGrid 等媒體工具的業界標準做法。

### 4. Watch Service 架構

**選擇：獨立的 `FolderWatcher` class，內含 polling 迴圈 thread + 處理佇列 thread**

```
FolderWatcher
├── _poll_thread     每 N 秒掃描資料夾，找出新檔案
│   ├── os.scandir recursive
│   ├── has_happy_vision_tag() 過濾
│   └── file_size_stable() 檢查
├── _process_queue   Queue[str] 等待處理的檔案路徑
├── _worker_thread   從 queue 取出，呼叫 analyze_photo + write_metadata
│   └── concurrency 由 ThreadPoolExecutor 控制
├── start() / pause() / stop()
└── state: watching | paused | stopped
```

不在 `pipeline.py` 的 `run_pipeline` 上面疊加 watch 邏輯，而是讓 `FolderWatcher` 直接呼叫 `analyze_photo` 和 `write_metadata`，避免 batch 模式和 watch 模式的控制流互相干擾。但復用 `scan_photos` 的掃描邏輯和 `ResultStore` 的結果儲存。

### 5. 並發控制 UI

**選擇：Slider（1–10）+ 即時白話說明**

不用預設檔位（省力/平衡/全速）。使用者自行拉 slider，下方即時顯示估計的網路用量和效能影響說明。讓使用者有判斷能力但不幫他們做決定。

### 6. Config 持久化

在現有 `config.json` 新增：
```json
{
  "watch_folder": "/Volumes/LucidLink/修圖完成",
  "watch_enabled": true,
  "watch_concurrency": 1,
  "watch_interval": 10
}
```

App 啟動時讀取 config，若 `watch_enabled == true` 且 `watch_folder` 存在，自動啟動 watcher。

## Risks / Trade-offs

**[LucidLink 延遲]** → LucidLink 同步 metadata 可能有數秒延遲，造成短暫的 race condition 重複分析。Mitigation: 本機 DB 也做記錄，僅在首次掃描時 fallback 到 IPTC 檢查；且 `has_happy_vision_tag` 的 exiftool 讀取可能對 LucidLink 上的檔案較慢。實際影響小（多一次 API call），不值得為此增加複雜的分散式鎖。

**[大量檔案掃描效能]** → 資料夾中累積數萬張照片時，每次 polling 的 `os.scandir` + `has_happy_vision_tag`（exiftool）會變慢。Mitigation: 先用本機 DB 過濾已知檔案，只對 DB 中無記錄的檔案才呼叫 exiftool 檢查 IPTC。掃描邏輯：DB 有記錄 → 跳過；DB 無記錄 → 檢查 IPTC → 有 tag 跳過，無 tag 加入佇列。

**[App 未正常關閉]** → 不需要特別處理。重啟時自動補掃，DB + IPTC 雙重判斷確保冪等。分析到一半的照片（DB 無記錄、IPTC 無 tag）會被重新分析。

**[Gemini API 錯誤/限流]** → 失敗的照片記錄在本機 DB 為 `failed` 狀態，下次掃描會重試。可考慮 exponential backoff 但第一版不做，polling 間隔本身就提供了自然的重試間隔。
