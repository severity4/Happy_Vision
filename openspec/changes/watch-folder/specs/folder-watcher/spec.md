## ADDED Requirements

### Requirement: Polling-based folder scanning
The system SHALL periodically scan the configured watch folder (including all subdirectories) for JPG/JPEG files using `os.scandir` recursive traversal. The default polling interval SHALL be 10 seconds and MUST be configurable.

#### Scenario: New photos detected during polling
- **WHEN** a polling cycle runs and finds JPG files not in the local DB and without `HappyVisionProcessed` IPTC tag
- **THEN** those files are added to the processing queue

#### Scenario: Already processed photos skipped (local DB)
- **WHEN** a polling cycle finds a JPG file that exists in the local ResultStore as `completed`
- **THEN** the file is skipped without calling exiftool

#### Scenario: Already processed photos skipped (IPTC cross-machine)
- **WHEN** a polling cycle finds a JPG file not in the local DB but with `HappyVisionProcessed` IPTC tag
- **THEN** the file is skipped (another machine already processed it)

#### Scenario: Failed photos retried
- **WHEN** a polling cycle finds a JPG file recorded as `failed` in the local DB
- **THEN** the file is re-queued for analysis

### Requirement: File readiness check
The system SHALL verify that a detected file is fully written before queueing it for analysis. A file is considered ready WHEN its size remains unchanged for at least 1 second, checked at 200ms intervals.

#### Scenario: File still being written by Lightroom
- **WHEN** a new JPG file is detected and its size changes within the 1-second stability window
- **THEN** the stability timer resets and the file is not queued until stable

#### Scenario: File fully written
- **WHEN** a new JPG file's size remains constant for 1 second
- **THEN** the file is added to the processing queue

#### Scenario: Zero-byte or disappeared file
- **WHEN** a detected file has zero bytes or no longer exists during the stability check
- **THEN** the file is discarded from the current check (will be re-evaluated next poll)

### Requirement: Automatic photo analysis and metadata write-back
The system SHALL automatically analyze queued photos via Gemini API and write IPTC/XMP metadata back to the photo file. This MUST use the existing `analyze_photo` and `write_metadata` functions.

#### Scenario: Successful analysis
- **WHEN** a queued photo is analyzed successfully
- **THEN** the result is saved to local ResultStore, IPTC/XMP metadata is written to the photo, and an SSE event is broadcast

#### Scenario: Analysis failure
- **WHEN** Gemini API returns an error for a photo
- **THEN** the photo is marked as `failed` in ResultStore, an SSE error event is broadcast, and the photo will be retried on next polling cycle

### Requirement: Concurrency control
The system SHALL process photos using a ThreadPoolExecutor with a configurable number of workers (1–10). The concurrency value MUST be adjustable at runtime without restarting the watcher.

#### Scenario: User changes concurrency while watching
- **WHEN** the user adjusts the concurrency slider while the watcher is running
- **THEN** the new concurrency value takes effect for subsequently queued photos

### Requirement: Watch state management
The FolderWatcher SHALL support three states: `watching`, `paused`, and `stopped`.

#### Scenario: Start watching
- **WHEN** start is invoked with a valid folder path
- **THEN** the state transitions to `watching` and polling begins

#### Scenario: Pause watching
- **WHEN** pause is invoked while in `watching` state
- **THEN** polling stops and in-progress analysis completes, but no new photos are dequeued

#### Scenario: Resume from pause
- **WHEN** start is invoked while in `paused` state
- **THEN** polling resumes and queued photos continue processing

#### Scenario: Stop watching
- **WHEN** stop is invoked
- **THEN** polling stops, the processing queue is cleared, and in-progress analysis completes

### Requirement: Config persistence and auto-restore
The system SHALL persist watch settings (`watch_folder`, `watch_enabled`, `watch_concurrency`, `watch_interval`) in `config.json`. On App startup, if `watch_enabled` is `true` and the watch folder path is accessible, the watcher SHALL start automatically.

#### Scenario: App restarts with watch enabled
- **WHEN** the App starts and config has `watch_enabled: true` with a valid `watch_folder`
- **THEN** the watcher starts automatically and processes any unprocessed photos in the folder

#### Scenario: App restarts with inaccessible folder
- **WHEN** the App starts and config has `watch_enabled: true` but the folder path is not accessible (e.g., LucidLink not mounted)
- **THEN** the watcher does NOT start, and an error state is shown in the UI

#### Scenario: App restarts after crash
- **WHEN** the App restarts after an abnormal shutdown
- **THEN** the watcher resumes normally; photos partially analyzed (no DB record, no IPTC tag) are re-analyzed
