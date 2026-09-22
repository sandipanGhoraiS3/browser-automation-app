---
name: daily_report
display_name: Daily Report
description: Collect today's report from your chosen dashboard and save a local CSV and screenshot.
version: '1.0'
category: reporting
requires_browser: true
requires_files: true
---

## Preconditions
- Ask for the dashboard URL and report fields unless supplied in the conversation.
- The user must sign in directly in the browser if authentication is needed.
- Ask which date and timezone to use if today's date is ambiguous.

## Steps
1. Open the user-provided dashboard in the current tab and inspect it.
2. Find today's report using visible labels and current page state.
3. Collect the requested fields and record counts, without inventing missing data.
4. If the site offers a report download, activate its Download control and inspect completed downloads.
5. Create a reports folder inside the user's PC Downloads folder.
6. Save the detected download, or generate a properly quoted CSV from the observed records, using a date-based filename. Choose a unique filename if it already exists.
7. Save a full-page screenshot next to the report using file_save_screenshot.

## Output
Return the relative saved file paths, record count, date range, and a concise findings summary. Clearly identify unavailable records.

## Browser Rules
Use fresh snapshots and semantic page labels. Reuse the current tab. Keep the browser open. Request confirmation for important form submissions and account changes.

## Recovery
If authentication expires, ask the user to sign in. If data or a download is unavailable, inspect the current state and explain the missing prerequisite. Do not fabricate a report or overwrite files.
