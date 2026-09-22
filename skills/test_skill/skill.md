---
name: test_skill
display_name: Workspace Check
description: Create a small Downloads report to verify file tools through the agent.
version: '1.0'
category: utilities
requires_browser: false
requires_files: true
---

## Preconditions
The local PC Downloads folder is available.

## Steps
1. Create a folder called checks inside PC Downloads.
2. List that folder and choose a new filename beginning with workspace-check.
3. Create a UTF-8 text file containing "Workspace check completed.".
4. Read the saved file to verify its contents.

## Output
Return the saved relative path and the verified text.

## Browser Rules
No browser interaction is required. Leave any existing browser open.

## Recovery
If a filename exists, select a new name. Explain filesystem errors and never escape the allowed Downloads folder.
