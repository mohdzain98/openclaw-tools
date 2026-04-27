# Job Market Intelligence Agent — Plan

> Every-other-night job scout: Claude searches for Data Science & Gen AI roles,
> builds an HTML dashboard, and sends a WhatsApp notification.

---

## Architecture

```
Every other night at 12:00 AM IST (cron — every 2nd day)
        ↓
cron triggers → job_scout.py
        ↓
Reads prompt.txt → fills [DATE], [CUTOFF], [ROLES], [LOCATIONS] placeholders
        ↓
Claude CLI (subprocess) with --allowedTools WebSearch
  — searches LinkedIn, Naukri, Glassdoor, Indeed, company career pages
  — returns structured JSON array of job postings
        ↓
Parse & deduplicate against SQLite (jobs.db)
        ↓
Score & rank jobs (role relevance + location weight)
        ↓
Generate HTML dashboards
  → latest.html  (jobs found in this run)
  → all.html     (all jobs ever found, filterable)
        ↓
Deploy dashboards → /home/zain/zainclaw/job_scout/dashboard/
        ↓
OpenClaw sends WhatsApp notification with summary + links
```

---

## Files

```
job-market-intelligence/
├── plan.md                  ← this file
├── SKILL.md                 ← OpenClaw skill definition
├── job_scout.py             ← main script
├── prompt.txt               ← Claude search prompt (edit to tune searches)
├── docs/
│   └── SETUP.md             ← full setup guide
└── .env.example             ← environment variable template
```

---

## Dashboard URLs

- `https://claw.mohdzain.com/apply-jobs/latest.html` — jobs from latest run
- `https://claw.mohdzain.com/apply-jobs/all.html` — all jobs, filterable table

---

## job_scout.py — Responsibilities

1. Load config from `.env`
2. Connect to SQLite (`jobs.db`) — table: `jobs(id, title, company, location, apply_url, source, tags, score, date_found, applied)`
3. Read `prompt.txt`, replace `[DATE]`, `[CUTOFF]`, `[ROLES]`, `[LOCATIONS]` placeholders
4. Run Claude CLI via subprocess with `--allowedTools WebSearch`
   - Claude searches and returns a raw JSON array of job postings
5. Deduplicate by sha256(title+company) hash against `jobs.db`
6. Score each job (role relevance + location weight)
7. Insert new jobs into SQLite
8. Generate `latest.html` — new jobs from this run only
9. Regenerate `all.html` — full table with search/filter, "Apply" buttons, localStorage applied-tracking
10. Write dashboards to `JOBS_DASHBOARD_DIR`
11. Send WhatsApp summary via `openclaw message send`

---

## Claude Search Strategy

Claude CLI is invoked via subprocess with `--allowedTools WebSearch`. The prompt lives in `prompt.txt` and uses four placeholders filled at runtime:
- `[DATE]` — today's date
- `[CUTOFF]` — search cutoff (today − JOB_SEARCH_DAYS)
- `[ROLES]` — comma-separated list from `JOB_ROLES` env var
- `[LOCATIONS]` — Bengaluru, Delhi NCR, Hyderabad, Mumbai, Remote

Claude searches LinkedIn, Naukri, Glassdoor, Indeed, and career pages, deduplicates by title+company, and returns a raw JSON array. Edit `prompt.txt` directly to tune search behaviour without touching the script.

---

## HTML Dashboard Design

### latest.html
- Header: "Jobs found — {date of run}"
- Count badge: "X new jobs"
- Table: Score | Title / Company | Location | Tags | Source | Apply button
- Tags as colored chips: Remote, Gen AI, DS, Startup, etc.
- "Apply →" button opens job URL in new tab

### all.html
- Live search box (filters by title or company)
- Location and tag dropdowns
- "Mark Applied" button per row — persists in browser `localStorage` (no backend needed)
- Applied jobs shown at 50% opacity
- Sorted by score DESC

---

## SQLite Schema

```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,   -- sha256(title+company)[:16]
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT NOT NULL,
    apply_url   TEXT NOT NULL,
    source      TEXT NOT NULL,      -- linkedin / naukri / glassdoor / company
    tags        TEXT NOT NULL,      -- JSON array
    score       INTEGER NOT NULL,   -- 0-100, relevance score
    date_found  TEXT NOT NULL,      -- YYYY-MM-DD
    applied     INTEGER NOT NULL DEFAULT 0
);
```

---

## Scoring Logic

| Factor                          | Points Added       |
| ------------------------------- | ------------------ |
| Gen AI / LLM in job title       | +20                |
| Gen AI / LLM in tags only       | +12                |
| ML / Data Science in title      | +10                |
| Bengaluru location              | +12 (0.40 × 30)    |
| Delhi / NCR location            | +7  (0.25 × 30)    |
| Remote tag/location             | +5                 |
| Hyderabad location              | +6  (0.20 × 30)    |
| Mumbai location                 | +4  (0.15 × 30)    |
| Base score                      | 50                 |

Score capped at 100. Top picks threshold: ≥ 75.

---

## Environment Variables (.env)

```bash
# Claude CLI
CLAUDE_BIN=/home/zain/.local/bin/claude

# WhatsApp
WHATSAPP_NUM=+910000000000
OPENCLAW_WHATSAPP_ENABLED=true

# Dashboard
DASHBOARD_URL=https://claw.mohdzain.com/apply-jobs
JOBS_DASHBOARD_DIR=/home/zain/zainclaw/job_scout/dashboard

# Database
JOBS_DATA_DIR=/home/zain/zainclaw/job_scout/data
JOBS_DB_PATH=/home/zain/zainclaw/job_scout/data/jobs.db

# Search config
JOB_ROLES=Data Scientist,Gen AI Engineer,ML Engineer,LLM Engineer,AI Researcher
JOB_SEARCH_DAYS=2
```

---

## Cron Schedule

Every other night at 12:00 AM IST = 6:30 PM UTC on even days:

```cron
30 18 */2 * * /usr/bin/python3 /home/zain/zainclaw/job_scout/job_scout.py >> /var/log/job_scout.log 2>&1
```

---

## WhatsApp Notification Format

```
🧠 Job Scout — 27 Apr 2026

🆕 12 new jobs found!

🌟 Top picks:
  1. Gen AI Engineer @ Sarvam AI — Bengaluru
  2. LLM Engineer @ Krutrim — Bengaluru
  3. ML Engineer @ Meesho — Bengaluru

📊 Dashboards:
latest → https://claw.mohdzain.com/apply-jobs/latest.html
all    → https://claw.mohdzain.com/apply-jobs/all.html
```

---

## nginx Config Addition

Add to the existing openclaw nginx server block:

```nginx
location /apply-jobs/ {
    alias /home/zain/zainclaw/job_scout/dashboard/;
    index latest.html;
    try_files $uri $uri/ /latest.html;
    add_header Cache-Control "no-cache";
}
```

---

## On-Demand Usage via WhatsApp

Once SKILL.md is registered with OpenClaw:

| Message                              | What happens                     |
| ------------------------------------ | -------------------------------- |
| `Find me new jobs`                   | Runs job_scout.py, returns links |
| `Show me Gen AI jobs in Bangalore`   | Filtered scout run               |
| `Any remote Data Science jobs?`      | Remote-only filtered run         |

---

## Implementation Status

- [x] `SKILL.md` — OpenClaw skill definition
- [x] `.env.example` — env template
- [x] `prompt.txt` — Claude search prompt with placeholders
- [x] `job_scout.py` — main script (Claude CLI → SQLite → HTML → WhatsApp)
- [x] `docs/SETUP.md` — full setup guide (nginx, cron, env vars)
- [ ] Deploy to server and run first test

---

*Built with OpenClaw + Claude CLI (WebSearch) + Python · Auto-runs every 2 nights at 12 AM IST*
