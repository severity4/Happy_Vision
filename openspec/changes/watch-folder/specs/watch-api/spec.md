## ADDED Requirements

### Requirement: Watch control endpoints
The system SHALL provide REST API endpoints under `/api/watch/` to control the folder watcher.

#### Scenario: Start watching
- **WHEN** `POST /api/watch/start` is called with `{ "folder": "/path" }` (optional, uses config if omitted)
- **THEN** the watcher starts, config is updated with the folder path and `watch_enabled: true`, and response returns `{ "status": "watching", "folder": "..." }`

#### Scenario: Start while already watching
- **WHEN** `POST /api/watch/start` is called while the watcher is in `watching` state
- **THEN** response returns `409` with `{ "error": "Already watching" }`

#### Scenario: Pause watching
- **WHEN** `POST /api/watch/pause` is called while in `watching` state
- **THEN** the watcher pauses and response returns `{ "status": "paused" }`

#### Scenario: Resume watching
- **WHEN** `POST /api/watch/resume` is called while in `paused` state
- **THEN** the watcher resumes and response returns `{ "status": "watching" }`

#### Scenario: Stop watching
- **WHEN** `POST /api/watch/stop` is called
- **THEN** the watcher stops, config is updated with `watch_enabled: false`, and response returns `{ "status": "stopped" }`

### Requirement: Watch status endpoint
The system SHALL provide a status endpoint that returns the current watcher state and statistics.

#### Scenario: Query watch status
- **WHEN** `GET /api/watch/status` is called
- **THEN** response returns `{ "status": "watching|paused|stopped", "folder": "...", "queue_size": N, "processing": N, "completed_today": N, "failed_today": N }`

### Requirement: Update concurrency at runtime
The system SHALL allow updating the concurrency setting without restarting the watcher.

#### Scenario: Update concurrency
- **WHEN** `POST /api/watch/concurrency` is called with `{ "concurrency": 5 }`
- **THEN** the watcher updates its concurrency, config is persisted, and response confirms the new value

### Requirement: SSE event stream for watch progress
The system SHALL provide an SSE endpoint at `GET /api/watch/events` that streams real-time watch events.

#### Scenario: Photo processed
- **WHEN** a photo is successfully analyzed
- **THEN** an SSE event `watch_progress` is sent with `{ "file": "...", "queue_size": N, "completed_today": N }`

#### Scenario: Photo failed
- **WHEN** a photo analysis fails
- **THEN** an SSE event `watch_error` is sent with `{ "file": "...", "error": "...", "failed_today": N }`

#### Scenario: Watcher state changed
- **WHEN** the watcher state changes (start/pause/stop)
- **THEN** an SSE event `watch_state` is sent with `{ "status": "watching|paused|stopped" }`

### Requirement: Recent activity endpoint
The system SHALL provide an endpoint to query recently processed photos.

#### Scenario: Query recent activity
- **WHEN** `GET /api/watch/recent?limit=20` is called
- **THEN** response returns the most recent processed/failed photos with file path, status, and timestamp
