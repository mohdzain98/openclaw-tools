# Axis Spending Setup

This guide sets up the `axis-spending` OpenClaw tool on the server.

It covers:
- Himalaya email access
- server folder structure
- `.env` configuration
- nginx static dashboard serving
- cron scheduling
- what `axis_tracker.py` actually does

## Overview

The tracker is a stored-history workflow, not a live-only weekly script.

High-level flow:

```text
axis_tracker.py
  -> reads .env
  -> fetches Axis Bank alert emails with Himalaya
  -> parses debit / credit transactions
  -> categorizes using regex rules
  -> stores unique rows in SQLite
  -> regenerates dashboards from stored DB data
  -> optionally sends WhatsApp summary
```

Generated outputs:
- `latest.html`
- `current-month.html`
- `all-time.html`
- `month-YYYY-MM.html`
- `archive.html`

## Server Layout

Expected server path:

```text
/home/zain/zainclaw/axis_spending/
  axis_tracker.py
  SKILL.md
  .env
  data/
    transactions.db
  dashboard/
    latest.html
    current-month.html
    all-time.html
    archive.html
    month-YYYY-MM.html
```

## `axis_tracker.py` Overview

Main responsibilities of [axis_tracker.py](./axis_tracker.py):

1. Load configuration from `.env`
2. Connect to SQLite and ensure the `transactions` table exists
3. Fetch transaction emails from `alerts@axis.bank.in` using Himalaya
4. Parse:
   - date
   - debit/credit type
   - amount
   - transaction info
   - account suffix
5. Extract a `target` using `pick_payee()`
6. Categorize using notebook-style regex `CATEGORY_RULES`
7. Deduplicate and insert rows into SQLite
8. Build dashboard pages from stored history
9. Send WhatsApp summary if enabled and configured

Important behavior:
- no OpenAI or Gemini calls
- DB is the source of truth for dashboards
- the script backfills missing current-month data when needed
- `latest.html` is controlled separately by `AXIS_LATEST_DASHBOARD_DAYS`

## Step 1: Install Himalaya

Install Himalaya on the server and verify it works:

```bash
himalaya --version
```

If it is not installed, install it first using your preferred method or from the
official release archive.

## Step 2: Configure Himalaya

Create:

```bash
mkdir -p ~/.config/himalaya
nano ~/.config/himalaya/config.toml
```

Example config:

```toml
[accounts.axis-inbox]
email = "you@example.com"
display-name = "Zain"
default = true

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@example.com"
backend.auth.type = "password"
backend.auth.raw = "gmail_app_password_here"
```

Test it:

```bash
himalaya envelope list
```

You should be able to see mailbox envelopes, including Axis alert emails.

## Step 3: Deploy Files

Make sure these files exist on the server:

```bash
/home/zain/zainclaw/axis_spending/axis_tracker.py
/home/zain/zainclaw/axis_spending/SKILL.md
```

Create data and dashboard folders:

```bash
mkdir -p /home/zain/zainclaw/axis_spending/data
mkdir -p /home/zain/zainclaw/axis_spending/dashboard
```

## Step 4: Create `.env`

Create:

```bash
nano /home/zain/zainclaw/axis_spending/.env
```

Recommended contents:

```env
WHATSAPP_NUM=+917310672019
DASHBOARD_URL=https://claw.mohdzain.com/spending
AXIS_SENDER=alerts@axis.bank.in
AXIS_DATA_DIR=/home/zain/zainclaw/axis_spending/data
AXIS_DASHBOARD_DIR=/home/zain/zainclaw/axis_spending/dashboard
AXIS_DB_PATH=/home/zain/zainclaw/axis_spending/data/transactions.db
OPENCLAW_WHATSAPP_ENABLED=true
AXIS_DEFAULT_FETCH_DAYS=7
AXIS_LATEST_DASHBOARD_DAYS=7
```

Notes:
- `.env` is local to this tool and should not be committed
- `AXIS_DEFAULT_FETCH_DAYS` controls sync/backfill window when no CLI arg is passed
- `AXIS_LATEST_DASHBOARD_DAYS` controls what `latest.html` shows

## Step 5: nginx Configuration

If OpenClaw is already proxied on `claw.mohdzain.com`, add a static location for
the dashboards before the catch-all `/` proxy block.

Example:

```nginx
server {
    server_name claw.mohdzain.com;

    location /spending/ {
        alias /home/zain/zainclaw/axis_spending/dashboard/;
        index latest.html;
        try_files $uri $uri/ /latest.html;
        add_header Cache-Control "no-cache";
    }

    location / {
        proxy_pass http://127.0.0.1:18789;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Dashboard URLs:
- `https://claw.mohdzain.com/spending/latest.html`
- `https://claw.mohdzain.com/spending/current-month.html`
- `https://claw.mohdzain.com/spending/all-time.html`
- `https://claw.mohdzain.com/spending/archive.html`

## Step 6: Test Manually

Run:

```bash
python3 /home/zain/zainclaw/axis_spending/axis_tracker.py
```

Or with an explicit sync window:

```bash
python3 /home/zain/zainclaw/axis_spending/axis_tracker.py 14
```

What happens:
- the script checks DB coverage
- fetches only missing/new mail needed for sync
- updates SQLite
- regenerates dashboards
- optionally sends WhatsApp summary

Useful first-run note:
- if the DB only has recent rows, the script may backfill from the 1st of the current month so `current-month.html` is complete

## Step 7: Cron Job

To run every Monday `12:00 AM IST`, use:

```cron
30 18 * * 0 /usr/bin/python3 /home/zain/zainclaw/axis_spending/axis_tracker.py 7 >> /var/log/axis_tracker.log 2>&1
```

Why:
- `12:00 AM IST Monday` = `6:30 PM UTC Sunday`
- cron is safer with full Python path

Edit crontab:

```bash
crontab -e
```

Verify:

```bash
crontab -l
```

## Step 8: OpenClaw Skill

[SKILL.md](./SKILL.md) is the OpenClaw-facing skill definition.

It describes:
- when the skill should be used
- how to run the tracker
- expected outputs
- server paths and dashboard URLs

## Troubleshooting

### WhatsApp number missing

Make sure:
- `/home/zain/zainclaw/axis_spending/.env` exists
- `WHATSAPP_NUM=...` is present

### `openclaw` command not found

Either:
- install OpenClaw on the server
- add it to `PATH`
- or set `OPENCLAW_WHATSAPP_ENABLED=false` until messaging is available

### `latest.html` and `current-month.html` look the same

This happens when:
- DB only contains current-month data
- or `latest` window overlaps almost the entire current month

The current script already backfills current-month coverage when missing.

### Inspect SQLite data

Quick month summary:

```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('/home/zain/zainclaw/axis_spending/data/transactions.db')
for row in conn.execute("select substr(tx_date,1,7) as month, count(*) from transactions group by 1 order by 1 desc"):
    print(row)
conn.close()
PY
```

## Deployment

This repo includes a GitHub Actions deploy workflow for `axis-spending`.

It copies the tool files to:

```text
/home/zain/zainclaw/axis_spending
```

Required GitHub secrets:
- `HOST`
- `USERNAME`
- `SSH_PRIVATE_KEY`
