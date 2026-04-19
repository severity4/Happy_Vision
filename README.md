# Happy Vision

**映奧創意 (INOUT Creative) 內部工具。** 用 Google Gemini 分析 wedding / event 照片,把 title、description、keywords、category、people count、OCR 文字等寫進 IPTC/XMP metadata,Lightroom / Bridge 裡就能搜尋。

macOS 原生視窗 (pywebview),不開瀏覽器。

## Features (v0.12.1)

- **Gemini Batch API 模式** — 24h 內完成、費用 50%、async。適合 1000+ 張 backlog。
- **Lightroom rating 預篩** — 只分析 ≥ N 星的照片,跳過廢片省錢。
- **pHash 近重複偵測** — 連拍自動去重,一組只送 1 張。DB 15 萬張 scale 用 16-bit prefix bucket 快速查找。
- **成本預覽 + 確認** — 送批次前先看「將花 $X / 省 $Y / 預計 24h 內完成」,手滑不會扛 $84。
- **可觀測監控** — 背景 daemon 每 60s polls Gemini,`LIVE` / `RETRY` / `STUCK` 徽章即時顯示;`/api/batch/health` endpoint 暴露狀態。
- **殭屍 job 自動判決** — 連續 20 次 poll 失敗(API key rotated 之類)自動轉 FAILED,不佔 active list。
- **失敗照片重試 UI** — Monitor FAIL card 可點,modal 列出錯誤,一鍵清除失敗標記下次重跑。
- **Terminal Dense UI** — htop 風暗色儀表板,JetBrains Mono + Inter + 紫色 accent。
- **PDF / CSV / JSON 報告** — 支援繁中 (Noto Sans TC)。

## Quick Start

```bash
# Install (first time)
./setup.sh
make install

# Dev mode (Flask :8081 + Vite :5176)
make dev

# Build macOS .app
make app
```

第一次開 app 會跳 onboarding wizard 引導:貼 Gemini API key → 選 watch folder → 開始。

## Architecture

Flask backend (`web_ui.py`) + Vue 3 frontend + SQLite (`~/.happy-vision/results.db`) + pywebview macOS wrapper + Gemini API + exiftool。

細節看 [CLAUDE.md](CLAUDE.md)(給 maintainer)或 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)(給 INOUT 使用者)。

## Build 出的 .app

- `make app` → `dist/HappyVision.app`(94 MB,onedir + self-signed)
- `ditto -c -k --sequesterRsrc --keepParent HappyVision.app HappyVision-v{VER}.zip` 產出 release zip(47 MB)
- Self-signed codesign 讓 Keychain 跨版本不再重複要密碼(v0.7.2+)

## Windows 支援?

目前只 macOS。**有實際 Windows 使用者出現再做**,技術上 85% stack 已跨平台(Flask/Vue/SQLite/keyring/pywebview/google-genai)。延後決策細節 見 `.claude/projects/-Users-bobo-m3-Developer-Happy-Vision/memory/project_windows_deferred.md`。

## Releases

[GitHub Releases](https://github.com/severity4/Happy_Vision/releases) · 同步備份到 Google Drive `60_技術系統/HappyVision/`。

## License

Internal use, no license yet.
