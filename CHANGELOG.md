# Changelog

## v0.3.4 — 2026-04-17

### Reliability
- Gemini analyze: rate-limiter wait now capped at 60s (previously could block forever).
- Gemini analyze: retry on `DEADLINE_EXCEEDED`, `RESOURCE_EXHAUSTED`, `UNAVAILABLE`, `INTERNAL` (previously only HTTP numeric codes).
- exiftool batch: reader thread + queue with 30s timeout and kill-on-stall, preventing a hung exiftool from freezing the worker pool.
- exiftool batch: reject args containing `\n`, `\r`, or NUL — these silently corrupt the `-@ -` stdin protocol.

### Security
- Logger: scrub Google API keys (`AIza...`), OAuth tokens (`ya29...`), `Bearer` / `Token` headers, and `api_key=` query params from all log records before writing to disk.
