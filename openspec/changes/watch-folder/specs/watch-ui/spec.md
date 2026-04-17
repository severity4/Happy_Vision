## ADDED Requirements

### Requirement: Watch Folder page
The system SHALL provide a dedicated Watch Folder page accessible from the main navigation, showing the current watch state, controls, and activity.

#### Scenario: User navigates to Watch Folder page
- **WHEN** the user clicks the Watch Folder navigation item
- **THEN** the page displays the current watch state, configured folder path, and control buttons

### Requirement: Folder selection
The system SHALL allow users to select a watch folder using the existing folder browser UI (not manual path input).

#### Scenario: User selects a watch folder
- **WHEN** the user clicks the folder selector and picks a directory
- **THEN** the selected path is displayed and persisted to config

### Requirement: Watch controls
The system SHALL provide start, pause, and stop controls that reflect the current watcher state.

#### Scenario: Watcher is stopped
- **WHEN** the watcher is in `stopped` state
- **THEN** only the「開始監控」button is enabled

#### Scenario: Watcher is watching
- **WHEN** the watcher is in `watching` state
- **THEN** 「暫停」and「停止」buttons are enabled, a green indicator shows active status

#### Scenario: Watcher is paused
- **WHEN** the watcher is in `paused` state
- **THEN** 「繼續」and「停止」buttons are enabled, a yellow indicator shows paused status

### Requirement: Concurrency slider with plain-language description
The system SHALL provide a slider (range 1–10) for adjusting concurrent processing, with a real-time plain-language description below it explaining the impact.

#### Scenario: User adjusts concurrency to 1
- **WHEN** the slider is set to 1
- **THEN** the description reads something like「同時分析 1 張照片，不影響其他工作」

#### Scenario: User adjusts concurrency to higher value
- **WHEN** the slider is set to a value above 5
- **THEN** the description includes a note about network bandwidth impact on LucidLink sync

#### Scenario: Slider change takes effect immediately
- **WHEN** the user moves the slider while the watcher is running
- **THEN** the new concurrency is sent to the API and applied without restarting the watcher

### Requirement: Live status display
The system SHALL show real-time statistics updated via SSE: queue size, currently processing count, and today's completed/failed counts.

#### Scenario: Photos being processed
- **WHEN** the watcher is actively processing photos
- **THEN** the UI shows queue count, processing count, and a progress indicator

#### Scenario: Idle with no pending photos
- **WHEN** the watcher is watching but the queue is empty
- **THEN** the UI shows「監控中，等待新照片...」

### Requirement: Recent activity list
The system SHALL display a scrollable list of recently processed photos showing file path (relative to watch folder), status (success/failed), and timestamp.

#### Scenario: Photo processed successfully
- **WHEN** a photo is analyzed successfully
- **THEN** it appears at the top of the activity list with a success indicator

#### Scenario: Photo failed
- **WHEN** a photo analysis fails
- **THEN** it appears at the top of the activity list with an error indicator and a「重試」button

### Requirement: Error state display
The system SHALL clearly communicate error states to the user.

#### Scenario: Watch folder not accessible
- **WHEN** the configured watch folder is not accessible (LucidLink not mounted)
- **THEN** the UI shows a warning message explaining the folder cannot be reached

#### Scenario: Gemini API key not configured
- **WHEN** the user tries to start watching without a configured API key
- **THEN** the UI shows an error directing them to Settings
