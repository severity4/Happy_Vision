# Happy Vision — Design Spec

## Overview

映奧創意 (INOUT Creative) 內部工具。修圖師把修好的 JPG 放到資料夾，Happy Vision 用 Gemini API 批次分析照片，產生英文描述、關鍵字、分類等 metadata，寫回照片 IPTC/XMP 欄位，並匯出報告。

獨立應用程式，不綁定 Lightroom。目標是把 AI 分析和 metadata 標記的工作從 Lightroom 拉出來，降低攝影師在 Lightroom 裡的工作量。

## Tech Stack

- **Backend:** Python 3.10+ / Flask
- **Frontend:** Vue 3 + Vite
- **AI:** Google Gemini API (2.0 Flash Lite default, 2.5 Flash optional)
- **Image Analysis:** OpenCV
- **Metadata:** exiftool (IPTC/XMP)
- **CLI:** click
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
- **未來：** Docker container（Windows 支援）

## Analysis Pipeline

每張 JPG 照片依序經過：

### 1. Quality Check (OpenCV, local)

- 模糊偵測（Laplacian variance）
- 曝光評估（histogram analysis）
- 基本構圖評估
- 標記問題照片，不自動刪除

### 2. AI Content Analysis (Gemini API)

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
  "ocr_text": ["INOUT Creative", "Annual Summit 2026"],
  "quality_notes": "Well exposed, sharp focus on subject"
}
```

**AI Model:**
- Default: Gemini 2.0 Flash Lite (cheaper, faster, sufficient for most photos)
- Optional: Gemini 2.5 Flash (better visual understanding for complex scenes)
- Configurable per session

**Public Figure Identification:**
- Prompt explicitly requests identification of public figures (celebrities, executives, politicians, etc.)
- Results in `identified_people` array, also written to keywords
- If Gemini refuses due to safety policy, field returns empty array, other results unaffected
- Risk: Gemini may inconsistently refuse identification. If testing reveals high refusal rate, consider backup service.

### 3. OCR

Handled by Gemini Vision within the same API call. Extracted text stored in `ocr_text` field.

### 4. Auto-Classification

Based on AI results + EXIF timestamps:
- Group by scene type
- Group by time period
- Group by event segment

### 5. Face Grouping

**Not included in v1.** Gemini handles public figure identification. Dedicated face clustering (dlib/face_recognition) deferred to future version if needed.

## Concurrency

- Gemini API: `asyncio` + `aiohttp`, configurable concurrency limit (default 5)
- OpenCV analysis: `ThreadPoolExecutor`
- Progress tracking: tqdm (CLI) / real-time progress bar (Web UI)

## Metadata Write-back

Using `exiftool` to write standard IPTC/XMP fields:

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

## Report Export

| Format | Use Case |
|--------|----------|
| CSV | Universal, open in Excel, deliver to clients |
| JSON | Programmatic integration, archive system import |
| HTML | Visual report with thumbnails, viewable in browser |

## Web UI (Vue 3, port 5176)

### Screens:

1. **Import** — Drag-and-drop folder or select path, show photo thumbnails and count
2. **Settings** — Model selection (Lite/Flash), concurrency, people identification toggle, write mode (overwrite all / skip existing)
3. **Progress** — Real-time progress bar, completed/total count, estimated time remaining, pause/cancel
4. **Results** — Photo grid, click to view AI-generated description/keywords/category, manual edit before write-back
5. **Export** — Select format (CSV/JSON/HTML) and download

## CLI

```bash
# Basic usage
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
| `--skip-existing` | Skip photos that already have metadata | Off |

## Project Structure

```
Happy_Vision/
├── api/                   # Flask blueprints
├── modules/
│   ├── gemini_vision.py   # Gemini API calls
│   ├── quality_check.py   # OpenCV quality analysis
│   ├── metadata_writer.py # exiftool write-back
│   └── report_generator.py
├── frontend/              # Vue 3
├── cli.py                 # CLI entry point
├── web_ui.py              # Flask entry point
├── Makefile
├── setup.sh
├── build_app.py           # macOS .app packaging
├── Dockerfile             # Future Windows support
├── requirements.txt
└── CLAUDE.md
```

## External Dependencies

| Dependency | Purpose | Installation |
|------------|---------|-------------|
| Gemini API Key | AI analysis | User enters in settings, stored in `~/.happy-vision/config.json` |
| exiftool | Metadata write-back | Bundled in .app, or `brew install exiftool` |
| OpenCV | Quality check | pip dependency |

## API Key Management

First launch guides user to enter Gemini API Key. Stored in `~/.happy-vision/config.json`, never committed to git.

## Out of Scope (v1)

- Face clustering/grouping with dlib (deferred)
- Custom person library (upload reference photos to identify non-public figures)
- RAW file support (CR3, ARW, NEF)
- Video analysis (use inout-footage-analyzer for that)
- Windows native build (Docker available as workaround)
