# Job Market Intelligence — Setup Guide

> OpenClaw-compatible job scout that uses Claude CLI (WebSearch tool) to find Data Science
> and Gen AI jobs every other night, then builds a dashboard and sends WhatsApp alerts.

---

## Architecture Overview

```
Every other night 12:00 AM IST (cron — every 2 days)
        ↓
cron runs → job_scout.py
        ↓
Reads prompt.txt (with [DATE], [CUTOFF], [ROLES], [LOCATIONS] placeholders filled in)
        ↓
Claude CLI runs with WebSearch tool — searches LinkedIn, Naukri, Glassdoor, Indeed
Returns structured JSON of job postings
        ↓
Score each job (role relevance + location weight)
        ↓
Deduplicate against SQLite (jobs.db)
        ↓
Generate dashboards → /path/to/job_scout/dashboard/
  latest.html — this run only
  all.html    — full history, filterable by location/tag, Apply buttons
        ↓
OpenClaw sends WhatsApp summary with top picks + links
```

---

## Step 1: Create Project Directory on Server

```bash
mkdir -p /path/to/job_scout/data
mkdir -p /path/to/job_scout/dashboard
```

---

## Step 2: Copy Project Files

```bash
# From your local machine
scp job_scout.py   server:/path/to/job_scout/
scp prompt.txt     server:/path/to/job_scout/
scp SKILL.md       server:/path/to/job_scout/
scp .env.example   server:/path/to/job_scout/.env
```

Then on the server, edit the `.env` with real values:

```bash
nano /path/to/job_scout/.env
```

---

## Step 3: Verify Python and Claude CLI

No extra pip packages needed — only the standard library.

```bash
python3 --version        # 3.8+ required
which claude             # confirm Claude CLI is installed
claude --version
```

If the `claude` binary is not at `/path/to/.local/bin/claude`, set `CLAUDE_BIN` in `.env` to the correct path.

---

## Step 4: Configure .env

```bash
nano /path/to/job_scout/.env
```

Fill in:

```bash
CLAUDE_BIN=/path/to/bin/claude
WHATSAPP_NUM=+910000000000
OPENCLAW_WHATSAPP_ENABLED=true
DASHBOARD_URL=https:/domain.example/apply-jobs
JOBS_DASHBOARD_DIR=/path/to/job_scout/dashboard
JOBS_DATA_DIR=/path/to/job_scout/data
JOBS_DB_PATH=/path/to/job_scout/data/jobs.db
JOB_ROLES=Data Scientist,Gen AI Engineer,ML Engineer,LLM Engineer,AI Researcher
JOB_SEARCH_DAYS=2
# Optional — defaults to prompt.txt next to job_scout.py
# JOBS_PROMPT_FILE=/path/to/job_scout/prompt.txt
```

---

## Step 5: Test the Script

```bash
cd /path/to/job_scout
python3 job_scout.py
```

Expected output:
```
🚀 Job Scout — 27 Apr 2026
==================================================
🤖 Running Claude CLI with WebSearch...
✅ Claude completed (3241 chars)
   Claude found: 28 candidate jobs
   After local dedup: 25 jobs
   New (not in DB):   25 jobs
💾 Inserted 25 jobs into /path/to/job_scout/data/jobs.db

📊 Generating dashboards...
📊 Dashboard saved: .../dashboard/latest.html → https://domain.example/apply-jobs/latest.html
📊 Dashboard saved: .../dashboard/all.html    → https://domain.example/apply-jobs/all.html

📈 Summary:
   New jobs found : 25
   Top picks (≥75): 8
   [88] Gen AI Engineer @ Sarvam AI — Bengaluru
   [85] LLM Engineer @ Krutrim — Bengaluru
   [82] Senior ML Engineer @ Meesho — Bengaluru

🔗 Dashboards:
   latest → https://domain.example/apply-jobs/latest.html
   all    → https://domain.example/apply-jobs/all.html
✅ WhatsApp message sent!

✅ Done!
```

---

## Step 6: Configure nginx for Dashboard

Add a static location block to your existing openclaw nginx server config:

```bash
sudo nano /etc/nginx/sites-available/domain.example
```

Add **before** the catch-all `/` proxy block:

```nginx
location /apply-jobs/ {
    alias /path/to/job_scout/dashboard/;
    index latest.html;
    try_files $uri $uri/ /latest.html;
    add_header Cache-Control "no-cache";
}
```

Reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Verify:

```bash
curl -I https://domain.example/apply-jobs/latest.html
# Should return: HTTP/2 200
```

---

## Step 7: Register Skill with OpenClaw

```bash
# Add job_scout directory to OpenClaw's extra skill dirs
openclaw config set skills.load.extraDirs '["/path/to/axis_spending", "/path/to/job_scout"]'

# Restart gateway
openclaw gateway restart

# Confirm skill shows up
openclaw skills list
# Should show: job-market-intelligence
```

---

## Step 8: Test WhatsApp Notification

```bash
openclaw message send --channel whatsapp --target +910000000000 --message "test from job scout"
```

---

## Step 9: Set Up Cron Job

Every other night at 12:00 AM IST = 6:30 PM UTC every 2 days:

```bash
crontab -e
```

Add:

```cron
30 18 */2 * * /usr/bin/python3 /path/to/job_scout/job_scout.py >> /var/log/job_scout.log 2>&1
```

Verify:

```bash
crontab -l
```

View logs after first run:

```bash
tail -f /var/log/job_scout.log
```

---

## On-Demand Usage via WhatsApp

Once the skill is registered, message your OpenClaw agent on WhatsApp:

| Message                                | What happens                           |
| -------------------------------------- | -------------------------------------- |
| `Find me new jobs`                     | Runs job_scout.py, sends back links    |
| `Show me Gen AI jobs`                  | Runs scout, focuses on Gen AI roles    |
| `Any remote Data Science jobs?`        | Runs scout, returns remote-tagged jobs |
| `What companies are hiring right now?` | Runs scout, summarizes companies       |

---

## Dashboard Features

### latest.html
- Shows only jobs found in the most recent run
- Sorted by relevance score (0–100)
- Score ≥ 75 = top pick (shown in green)
- Direct "Apply →" button per job linking to apply URL
- Stats: new jobs count, top picks count, top location

### all.html
- Complete history of all jobs ever found
- Live search box filters by title or company
- Location dropdown filter
- Tag dropdown filter (Gen AI, LLM, Remote, etc.)
- "Mark Applied" button per row — stores status in browser `localStorage` (no backend needed)
- Applied jobs shown at 50% opacity

---

## Scoring Logic

| Factor                     | Points Added    |
| -------------------------- | --------------- |
| Gen AI / LLM in job title  | +20             |
| Gen AI / LLM in tags only  | +12             |
| ML / Data Science in title | +10             |
| Bengaluru location         | +12 (0.40 × 30) |
| Delhi / NCR location       | +7  (0.25 × 30) |
| Remote tag/location        | +5              |
| Hyderabad location         | +6  (0.20 × 30) |
| Mumbai location            | +4  (0.15 × 30) |
| Base score                 | 50              |

Score is capped at 100. Top picks threshold: ≥ 75.

---

## File Structure

```
/path/to/
└── job_scout/
    ├── job_scout.py      # Main script
    ├── prompt.txt        # Claude search prompt (edit to tune searches)
    ├── SKILL.md          # OpenClaw skill definition
    ├── .env              # Environment variables (not committed)
    ├── data/
    │   └── jobs.db       # SQLite — all jobs ever found
    └── dashboard/
        ├── latest.html   # Latest run jobs
        └── all.html      # Full history, filterable
```

---

*Built with OpenClaw + Claude CLI (WebSearch) + Python · Auto-runs every 2 nights at 12 AM IST*
