# monitor-page Specification

## Purpose
TBD - created by archiving change ui-consolidation. Update Purpose after archive.
## Requirements
### Requirement: Monitor page is the app home page
The app SHALL display the MonitorView as the default page at route `/`. Navigation SHALL show exactly 2 tabs: 「監控」and「設定」.

#### Scenario: User opens the app
- **WHEN** the app loads
- **THEN** the MonitorView is displayed as the home page with the「監控」tab active

### Requirement: Watch status panel
The monitor page SHALL display a prominent status panel at the top showing the current watch state, monitored folder path, and real-time statistics.

#### Scenario: Watch is active
- **WHEN** the watcher is in `watching` state
- **THEN** a green pulsing indicator, the folder path, and four statistics (queue/processing/completed today/failed today) are displayed with pause and stop buttons

#### Scenario: Watch is paused
- **WHEN** the watcher is in `paused` state
- **THEN** a yellow indicator is shown with resume and stop buttons

#### Scenario: Watch is stopped
- **WHEN** the watcher is in `stopped` state
- **THEN** a grey indicator and a「開始監控」button are shown; statistics still display today's cumulative counts

#### Scenario: Watch folder not configured
- **WHEN** no watch folder is configured in settings
- **THEN** a message directs the user to the settings page to select a folder

#### Scenario: API key not configured
- **WHEN** no Gemini API key is configured
- **THEN** a warning message directs the user to the settings page

### Requirement: Manual folder enqueue
The monitor page SHALL provide a「+ 加入資料夾分析」button that expands an inline folder browser. Selecting a folder SHALL enqueue all unprocessed photos from that folder into the watch queue.

#### Scenario: User adds a folder manually
- **WHEN** the user clicks「+ 加入資料夾分析」, browses to a folder, and confirms
- **THEN** the folder is scanned and unprocessed photos are added to the existing watch queue; the folder browser collapses

#### Scenario: Folder browser is collapsed by default
- **WHEN** the monitor page loads
- **THEN** the folder browser is hidden, showing only the「+ 加入資料夾分析」button

### Requirement: Unified result list
The monitor page SHALL display a chronologically ordered list of all recently processed photos (from both watch and manual enqueue), with status, relative file path, and timestamp.

#### Scenario: Photo processed successfully
- **WHEN** a photo analysis completes successfully
- **THEN** it appears at the top of the result list with a green check icon, relative file path, and relative timestamp

#### Scenario: Photo analysis failed
- **WHEN** a photo analysis fails
- **THEN** it appears with a red X icon, the error reason is accessible

#### Scenario: User clicks a result item
- **WHEN** the user clicks on a result list item
- **THEN** a detail modal opens showing the photo's full analysis (title, description, keywords, category, scene, mood, people count, identified people, OCR text, file path)

#### Scenario: Result list updates in real-time
- **WHEN** new photos are processed while the user is viewing the monitor page
- **THEN** new items appear at the top of the list via SSE without manual refresh

### Requirement: Export from monitor page
The monitor page SHALL provide export buttons (CSV, JSON) for downloading all analysis results.

#### Scenario: User exports results
- **WHEN** the user clicks the CSV or JSON export button
- **THEN** a file download is triggered with all completed analysis results

### Requirement: Status panel is always visible
The status panel at the top of the monitor page SHALL remain visible (sticky) while the user scrolls through the result list.

#### Scenario: User scrolls the result list
- **WHEN** the result list is longer than the viewport
- **THEN** the status panel stays pinned at the top and the result list scrolls independently below it

