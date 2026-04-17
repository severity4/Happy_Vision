# Changelog

## v0.3.4 — 2026-04-17

### Reliability
- Gemini analyze: rate-limiter wait now capped at 60s (previously could block forever).
- Gemini analyze: retry on `DEADLINE_EXCEEDED`, `RESOURCE_EXHAUSTED`, `UNAVAILABLE`, `INTERNAL` (previously only HTTP numeric codes).
- exiftool batch: reader thread + queue with 30s timeout and kill-on-stall, preventing a hung exiftool from freezing the worker pool.
- exiftool batch: reject args containing `\n`, `\r`, or NUL — these silently corrupt the `-@ -` stdin protocol.
- Result store: fix empty CSV/JSON export when the analyzed folder is under a symlinked path (e.g. `/tmp` → `/private/tmp` on macOS).

### Security
- Logger: scrub Google API keys (`AIza...`), OAuth tokens (`ya29...`), `Bearer` / `Token` headers, and `api_key=` query params from all log records before writing to disk.
- Logger: greedy match on API-key regex so trailing characters beyond the standard 39-char key are also consumed.
- Tests: in-memory Keychain fixture prevents pytest runs from writing fake keys into the developer's real macOS Keychain.

### UX
- Settings: help text under the API Key input with a clickable **Google AI Studio** link guiding first-time colleagues to create a free key.
- New `/api/system/open_external` endpoint routes such links through the system browser instead of keeping them inside the pywebview frame. Scheme-validated (http/https only).
