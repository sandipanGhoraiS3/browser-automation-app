---
name: dashboard_check
display_name: Dashboard Check
description: Inspect a chosen dashboard and save a concise local status report.
version: '1.0'
category: monitoring
requires_browser: true
requires_files: true
---

## Preconditions
The user provides a dashboard URL and the metrics to check, and authenticates directly in the browser if needed.

## Steps
1. Open the supplied dashboard and inspect the current page.
2. Find the requested metrics by visible labels.
3. Collect only observed values and relevant warnings.
4. Create a reports folder and save a uniquely named text summary.
5. Save a viewport screenshot alongside the summary.

## Output
Return observed metrics, warnings, and saved file paths.

## Browser Rules
Always inspect current state and use fresh references. Reuse the current tab and keep the browser open.

## Recovery
Ask for missing URL, metrics, or authentication. Describe unavailable information honestly. Never reuse stale references.
