## ADDED Requirements

### Requirement: Manual folder enqueue endpoint
The system SHALL provide `POST /api/watch/enqueue` to scan a specified folder and add unprocessed photos to the watch queue.

#### Scenario: Enqueue a valid folder
- **WHEN** `POST /api/watch/enqueue` is called with `{ "folder": "/path/to/photos" }`
- **THEN** the folder is recursively scanned for JPG/JPEG files, unprocessed photos (not in DB as completed, no IPTC HappyVisionProcessed tag) are added to the watch queue, and response returns `{ "enqueued": N, "skipped": M }`

#### Scenario: Enqueue while watcher is stopped
- **WHEN** `POST /api/watch/enqueue` is called but the watcher is stopped
- **THEN** the watcher auto-starts (using existing config for API key, model, concurrency) to process the enqueued photos

#### Scenario: Enqueue with invalid folder
- **WHEN** `POST /api/watch/enqueue` is called with a non-existent folder path
- **THEN** response returns `400` with `{ "error": "Folder not accessible" }`

#### Scenario: Enqueue with no API key
- **WHEN** `POST /api/watch/enqueue` is called but no Gemini API key is configured
- **THEN** response returns `400` with `{ "error": "Gemini API key not configured" }`

### Requirement: FolderWatcher enqueue_folder method
The FolderWatcher class SHALL provide an `enqueue_folder(path)` method that scans a folder once and adds unprocessed photos to its existing queue.

#### Scenario: enqueue_folder scans and deduplicates
- **WHEN** `enqueue_folder("/path")` is called
- **THEN** the folder is scanned recursively, photos already completed in DB or with IPTC tag are skipped, file readiness is checked, and remaining photos are added to the processing queue

#### Scenario: enqueue_folder does not persist the folder for continuous monitoring
- **WHEN** `enqueue_folder("/path")` is called
- **THEN** the folder is scanned once only; it is NOT added to the watch polling loop
