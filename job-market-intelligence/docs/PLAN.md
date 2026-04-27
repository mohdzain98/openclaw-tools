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
Parse & deduplicate against SQLite (seen jobs DB)
        ↓
Score & rank jobs (match score, company tier, freshness)
        ↓
Generate HTML dashboards
  → latest.html  (jobs found in this run)
  → all.html     (all jobs ever found, filterable)
        ↓
Deploy dashboards → /path/to/job_scout/dashboard/
        ↓
OpenClaw sends WhatsApp notification with summary + links
```

---

## Files to Create

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

- `https://domain.example/apply-jobs/latest.html` — jobs from latest run
- `https://domain.example/apply-jobs/all.html` — all jobs, filterable table

---

## job_scout.py — Responsibilities

1. Load config from `.env`
2. Connect to SQLite (`jobs.db`) — table: `jobs(id, title, company, location, url, source, tags, score, date_found, applied)`
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
- Cards or table: Title | Company | Location | Tags | Apply button
- Tags as colored chips: Remote, Gen AI, DS, Startup, etc.
- "Apply" button opens job URL in new tab

### all.html
- Full searchable table (JS filter in-page, no backend needed)
- Columns: Date Found | Title | Company | Location | Tags | Status | Apply
- Status column: "New" / "Applied" (updated manually or via script flag)
- Sort by: Date Found, Score
- Filter by: tags, company, location

---

## SQLite Schema

```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,   -- sha256(title+company)
    title       TEXT,
    company     TEXT,
    location    TEXT,
    apply_url   TEXT,
    source      TEXT,               -- linkedin / naukri / glassdoor / company
    tags        TEXT,               -- JSON array
    score       INTEGER,            -- 0-100, relevance score
    date_found  TEXT,               -- ISO date
    applied     INTEGER DEFAULT 0   -- 0 = not applied, 1 = applied
);
```

---

## Environment Variables (.env)

```bash
# Claude CLI
CLAUDE_BIN=/path/to/bin/claude

# WhatsApp
WHATSAPP_NUM=+910000000000
OPENCLAW_WHATSAPP_ENABLED=true

# Dashboard
DASHBOARD_URL=https://domain.example/apply-jobs
JOBS_DASHBOARD_DIR=/path/to/job_scout/dashboard

# Database
JOBS_DATA_DIR=/path/to/job_scout/data
JOBS_DB_PATH=/path/to/job_scout/data/jobs.db

# Search config
JOB_ROLES=Data Scientist,Gen AI Engineer,ML Engineer,LLM Engineer,AI Researcher
JOB_SEARCH_DAYS=2
```

---

## Cron Schedule

Every other night at 12:00 AM IST = 6:30 PM UTC on even days:

```cron
30 18 */2 * * /usr/bin/python3 /path/to/job_scout/job_scout.py >> /var/log/job_scout.log 2>&1
```

---

## WhatsApp Notification Format

```
🧠 Job Scout — 27 Apr 2026

🆕 12 new jobs found!

Top picks:
  1. Senior Gen AI Engineer @ Google — Remote
  2. ML Engineer (LLMs) @ Sarvam AI — Bangalore
  3. Data Scientist @ Meesho — Bangalore

📊 Dashboard:
latest → https://domain.example/apply-jobs/latest.html
all    → https://domain.example/apply-jobs/all.html
```

---

## nginx Config Addition

Add to the existing openclaw nginx server block:

```nginx
location /apply-jobs/ {
    alias /path/to/job_scout/dashboard/;
    index latest.html;
    try_files $uri $uri/ /latest.html;
    add_header Cache-Control "no-cache";
}
```

---

## On-Demand Usage via WhatsApp

Once SKILL.md is registered with OpenClaw:

| Message                            | What happens                     |
| ---------------------------------- | -------------------------------- |
| `Find me new jobs`                 | Runs job_scout.py, returns links |
| `Show me Gen AI jobs in Bangalore` | Filtered scout run               |
| `Any remote Data Science jobs?`    | Remote-only filtered run         |

---

## Implementation Order

1. [ ] `SKILL.md` — OpenClaw skill definition
2. [ ] `.env.example` — env template
3. [ ] `job_scout.py` — main script (Claude search → SQLite → HTML → WhatsApp)
4. [ ] `docs/SETUP.md` — full setup guide (nginx, cron, env vars, dependencies)
5. [ ] Test locally, then deploy to server

---

*Built with OpenClaw + Claude API + Python · Auto-runs every 2 nights at 12 AM IST*
