# openclaw-tools

Collection of small tools and automations built around OpenClaw workflows.

This repository is organized as a multi-tool workspace where each tool lives in
its own folder with its own script, skill definition, and supporting docs.

## Included Tools

### `axis-spending`

Email-driven spending tracker for Axis Bank alerts.

It:
- fetches transaction emails via Himalaya
- classifies transactions with regex rules
- stores data in SQLite with deduplication
- generates dashboards from stored history
- supports category and target-level drill-down
- can send a WhatsApp summary through OpenClaw

Main files:
- [axis-spending/axis_tracker.py](./axis-spending/axis_tracker.py)
- [axis-spending/SKILL.md](./axis-spending/SKILL.md)
- [axis-spending/docs/SETUP.md](./axis-spending/docs/SETUP.md)

## Repository Structure

```text
openclaw-tools/
  axis-spending/
    axis_tracker.py
    SKILL.md
    .env.example
    docs/
      SETUP.md
      PLAN.md
  .github/
    workflows/
```

## Notes

- This repo is shared publicly as a template/reference.
- Real deployment values should come from `.env` and GitHub/server secrets.
- Any server paths, domains, or contact numbers shown here are placeholders unless explicitly configured by the user.
