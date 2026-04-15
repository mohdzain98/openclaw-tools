# openclaw-tools

Private repository for personal OpenClaw tools and automations.

This repo is used to keep small production utilities in one place instead of
spreading them across multiple repositories. Each tool lives in its own folder
with its own script(s), skill definition, and deployment workflow as needed.

## Current tools

### `axis-spending`

Axis Bank transaction tracker for OpenClaw.

It:
- fetches recent Axis Bank alert emails via Himalaya
- categorizes transactions using regex rules
- stores transactions in SQLite with deduplication
- generates spending dashboards from stored history
- supports category and target-level drill-down
- can send a WhatsApp summary with the latest dashboard link

## Repo structure

```text
openclaw-tools/
  axis-spending/
    axis_tracker.py
    SKILL.md
  .github/workflows/
```

