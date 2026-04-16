# Happy Vision — Design Spec

## Overview

映奧創意 (INOUT Creative) 內部工具。修圖師把修好的 JPG 放到資料夾，Happy Vision 用 Gemini API 批次分析照片，產生英文描述、關鍵字、分類等 metadata，寫回照片 IPTC/XMP 欄位，並匯出報告。

獨立應用程式，不綁定 Lightroom。目標是把 AI 分析和 metadata 標記的工作從 Lightroom 拉出來，降低攝影師在 Lightroom 裡的工作量。

## Tech Stack

- **Backend:** Python 3.10+ / Flask
- **Frontend:** Vue 3 + Vite
- **AI:** Google Gemini API (2.0 Flash Lite default, 2.5 Flash optional)
- **Metadata:** exiftool via pyexiftool (Python wrapper)
- **CLI:** click
- **Progress Push:** SSE (Server-Sent Events)
- **Local DB:** SQLite (分析結果暫存)
- **Packaging:** PyInstaller (macOS .app)

## Ports

| Service | Port |
|---------|------|
| Vue dev server | 5176 |
| Flask backend | 8081 |

## Target Users

映奧創意內部修圖師。修好 JPG 後批次分析，一次處理量從幾十張到上千張不等。

## Distribution

- **短期：** macOS .app（PyInstaller 打包，雙擊即用）
- **未來（有需求時）：** Docker container（Windows 支援）

> **注意：** PyInstaller 打包 Python + exiftool 是已知痛點（動態函式庫連結、外部 binary 路徑、macOS Gatekeeper 簽章）。實作時應優先做 packaging spike，確認能順利打包再繼續開發其他功能。

## Analysis Pipeline

每張 JPG 照片經過：

### 1. AI Content Analysis (Gemini API)

一次 API call，用 structured output (JSON schema) 取回所有結果：

```json
{
  "title": "Event host addressing audience on main stage",
  "description": "A speaker in a dark suit stands at a podium on a brightly lit stage, addressing a seated audience of approximately 200 people in a conference hall.",
  "keywords": ["conference", "keynote", "speaker", "stage", "audience", "corporate event"],
  "category": "ceremony",
  "subcategory": "keynote",
  "scene_type": "indoor",
  "mood": "formal",
  "people_count": 200,
  "identified_people": ["Jensen Huang"],
  "ocr_text": ["INOUT Creative", "Annual Summit 2026"]
}
```

**AI Model:**
- Default: Gemini 2.0 Flash Lite (cheaper, faster, sufficient for most photos)
- Optional: Gemini 2.5 Flash (better visual understanding for complex scenes)
- Configurable per session in settings

**Public Figure Identification:**
- Prompt explicitly requests identification of public figures (celebrities, executives, politicians, etc.)
- Results in `identified_people` array, also written to keywords
- If Gemini refuses due to safety policy, field returns empty array, other results unaffected
- **Risk:** Gemini 對台灣本地公眾人物（非國際級）辨識率可能偏低。實測後評估是否需要備案

### 2. OCR

Handled by Gemini Vision within the same API call. Extracted text stored in `ocr_text` field.

## Concurrency & Error Handling

**並行處理：**
- Gemini API: `asyncio` + `aiohttp`, configurable concurrency limit (default 5)
- Progress tracking: tqdm (CLI) / SSE real-time progress bar (Web UI)

**API Rate Limit 注意事項：**
- Gemini Flash Lite 免費方案 RPM 限制嚴格（~15 RPM），付費方案較寬裕
- concurrency 設定需配合實際 RPM 限制，避免大量 429 錯誤
- 實作時需先確認目標方案的 RPM/TPM 限制

**成本預估：**
- Flash Lite: 極低成本（免費額度內可處理大量照片）
- Flash 2.5: 約 $0.05-0.10 / 1000 張（視照片複雜度）
- 新 Google Cloud 帳號有 $300 免費額度

**錯誤重試：**
- API 429/500 時 exponential backoff 重試（最多 3 次）
- 單張照片失敗不中斷整批，標記為 failed 繼續處理

**Checkpoint / Resume：**
- 每張照片處理完立即寫入 SQLite
- 中斷後重啟，自動跳過已處理的照片繼續
- Web UI 和 CLI 都支援 resume

## Result Storage

**SQLite 暫存（`~/.happy-vision/results.db`）：**
- 每次分析的完整結果存入 SQLite
- 關閉 app 重開後，之前的分析結果仍可查看
- 支援歷史查詢、重新匯出報告

**「已處理」標記：**
- 寫入自定義 XMP 欄位 `XMP-xmp:HappyVisionProcessed = true`
- `--skip-existing` 依此欄位判斷，比檢查所有欄位更可靠

## Metadata Write-back

Using `pyexiftool` (Python wrapper for exiftool) to write standard IPTC/XMP fields:

| AI Result | IPTC/XMP Field | Notes |
|-----------|---------------|-------|
| title | `IPTC:Headline` / `XMP:Title` | Short title |
| description | `IPTC:Caption-Abstract` / `XMP:Description` | Full description |
| keywords | `IPTC:Keywords` / `XMP:Subject` | Keyword array (includes identified people) |
| category | `XMP:Category` | Scene category |
| mood | `XMP:Scene` | Mood/atmosphere |
| ocr_text | `XMP:Comment` | Extracted text |

**Safety:**
- Auto-backup original metadata before writing
- Optional "skip existing" mode — only write to empty fields, never overwrite manual entries
- **Default: 只分析不寫入。** 使用者需明確啟用 metadata 寫入（Web UI toggle / CLI `--write-metadata`）

## Report Export

| Format | Use Case |
|--------|----------|
| CSV | Universal, open in Excel, deliver to clients |
| JSON | Programmatic integration, archive system import |

> HTML 報告延至有實際需求再做。

## Web UI (Vue 3, port 5176)

### Screens:

1. **Import** — Drag-and-drop folder or select path, show photo thumbnails and count
2. **Settings** — Model selection (Lite/Flash), concurrency, people identification toggle, write mode (overwrite all / skip existing), API key management
3. **Progress** — SSE real-time progress bar, completed/total count, estimated time remaining, pause/cancel
4. **Results** — Photo grid, click to view AI-generated description/keywords/category, manual edit before write-back
5. **Export** — Select format (CSV/JSON) and download

## CLI

```bash
# Basic usage (analyze only, no metadata write)
happy-vision /path/to/photos

# Full options
happy-vision /path/to/photos \
  --model lite \
  --concurrency 10 \
  --output ./report \
  --format csv,json \
  --write-metadata \
  --skip-existing
```

| Flag | Description | Default |
|------|-------------|---------|
| `--model` | `lite` or `flash` | `lite` |
| `--concurrency` | Parallel API calls | `5` |
| `--output` | Report output path | Current directory |
| `--format` | Report format(s) | `csv` |
| `--write-metadata` | Write results to photo IPTC/XMP | Off |
| `--skip-existing` | Skip photos already processed by Happy Vision | Off |

## Project Structure

```
Happy_Vision/
├── api/                    # Flask blueprints
├── modules/
│   ├── gemini_vision.py    # Gemini API calls
│   ├── metadata_writer.py  # pyexiftool write-back
│   ├── result_store.py     # SQLite result storage
│   └── report_generator.py
├── frontend/               # Vue 3
├── cli.py                  # CLI entry point
├── web_ui.py               # Flask entry point
├── Makefile
├── setup.sh
├── build_app.py            # macOS .app packaging
├── requirements.txt
└── CLAUDE.md
```

## External Dependencies

| Dependency | Purpose | Installation |
|------------|---------|-------------|
| Gemini API Key | AI analysis | User enters in settings, stored in `~/.happy-vision/config.json` |
| exiftool | Metadata write-back | `brew install exiftool` / bundled in .app |
| pyexiftool | Python exiftool wrapper | pip dependency |

## API Key Management

First launch guides user to enter Gemini API Key. Stored in `~/.happy-vision/config.json`, never committed to git.

## Logging

- 每張照片的處理結果（成功/失敗/跳過）記入 log
- Log 檔位於 `~/.happy-vision/logs/`
- 修圖師遇到問題時可提供 log 給開發者

## Out of Scope (v1)

- Face clustering/grouping with dlib (deferred)
- Custom person library (upload reference photos to identify non-public figures)
- RAW file support (CR3, ARW, NEF)
- Video analysis (use inout-footage-analyzer for that)
- Windows native build (Docker as future workaround)
- OpenCV quality check (修圖師給的是修好的照片，品質已由人把關)
- Auto-classification by time/scene (活動分段邏輯太依賴現場，AI 難判)
- HTML report (v1 先做 CSV + JSON)
- Dockerfile (全 Mac 環境，有需求時再加)

## Implementation Priority

1. **PyInstaller packaging spike** — 最大技術風險，先驗證能打包再繼續
2. **Gemini API integration + structured output** — 核心功能
3. **SQLite result store + checkpoint/resume** — 大量照片處理必備
4. **Metadata write-back (pyexiftool)** — 核心功能
5. **CLI** — 先做 CLI 驗證整個 pipeline
6. **Web UI** — 在 CLI 驗證完後再做前端
7. **Report export (CSV/JSON)** — 最後加上
8. **macOS .app packaging** — 基於 spike 結果完善打包
