# openclaw-tools

Collection of small tools and automations built around OpenClaw workflows.

This repository is organized as a multi-tool workspace where each tool lives in
its own folder with its own script, skill definition, and supporting docs.

## Included Tools

### `axis-spending`

Email-driven spending tracker for Axis Bank alerts.

- Fetches transaction emails via Himalaya (IMAP)
- Classifies transactions with regex rules
- Stores data in SQLite with deduplication
- Generates weekly and monthly dashboards from stored history
- Sends a WhatsApp summary via OpenClaw

Main files:
- [axis-spending/axis_tracker.py](./axis-spending/axis_tracker.py)
- [axis-spending/SKILL.md](./axis-spending/SKILL.md)
- [axis-spending/docs/SETUP.md](./axis-spending/docs/SETUP.md)

---

### `job-market-intelligence`

Every-other-night job scout for Data Science and Gen AI roles across Indian cities.

- Uses Claude CLI with WebSearch to find new job postings on LinkedIn, Naukri, Glassdoor, and Indeed
- Scores each job by role relevance and location weight (Bengaluru 0.4 · Delhi NCR 0.25 · Hyderabad 0.2 · Mumbai 0.15)
- Deduplicates against SQLite history across runs
- Generates two dashboards: `latest.html` (this run) and `all.html` (full history, filterable)
- "Mark Applied" tracking stored in browser localStorage — no backend needed
- Sends a WhatsApp summary with top picks via OpenClaw

Main files:
- [job-market-intelligence/job_scout.py](./job-market-intelligence/job_scout.py)
- [job-market-intelligence/prompt.txt](./job-market-intelligence/prompt.txt)
- [job-market-intelligence/SKILL.md](./job-market-intelligence/SKILL.md)
- [job-market-intelligence/docs/SETUP.md](./job-market-intelligence/docs/SETUP.md)

## Repository Structure

```text
openclaw-tools/
  axis-spending/
    axis_tracker.py
    SKILL.md
    .env.example
    docs/
      SETUP.md
  job-market-intelligence/
    job_scout.py
    prompt.txt
    SKILL.md
    .env.example
    plan.md
    docs/
      SETUP.md
  .github/
    workflows/
      deploy-axis-spending.yml
      deploy-job-scout.yml
```

## Notes

- This repo is shared publicly as a template/reference.
- Real deployment values should come from `.env` and GitHub/server secrets.
- Any server paths, domains, or contact numbers shown here are placeholders unless explicitly configured by the user.
