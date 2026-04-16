# watch-store Specification

## Purpose
TBD - created by archiving change ui-consolidation. Update Purpose after archive.
## Requirements
### Requirement: Global watch state store
A Pinia store (`stores/watch.js`) SHALL manage watch state globally, accessible from any page.

#### Scenario: Store provides reactive watch state
- **WHEN** any component accesses the watch store
- **THEN** it can read current status, folder, queueSize, processing count, completedToday, failedToday, and recentItems

### Requirement: App-level SSE connection
The watch store SHALL establish an SSE connection to `/api/watch/events` when the app mounts, regardless of which page is active.

#### Scenario: App starts
- **WHEN** App.vue mounts
- **THEN** the watch store connects to the SSE endpoint and begins updating state in real-time

#### Scenario: SSE receives watch_progress event
- **WHEN** a `watch_progress` SSE event arrives
- **THEN** the store updates queueSize, completedToday, and prepends the processed file to recentItems

#### Scenario: SSE receives watch_state event
- **WHEN** a `watch_state` SSE event arrives
- **THEN** the store updates the status field

#### Scenario: SSE connection drops
- **WHEN** the SSE connection is lost
- **THEN** the store attempts to reconnect after a brief delay

### Requirement: Watch control actions
The store SHALL provide actions for controlling the watcher: startWatch, pauseWatch, resumeWatch, stopWatch, and enqueueFolder.

#### Scenario: enqueueFolder is called
- **WHEN** `enqueueFolder(path)` is called
- **THEN** it sends `POST /api/watch/enqueue` with the folder path and refreshes recentItems after completion

