# OpenClaw Weekly Spending Tracker — Complete Setup Guide

> Automatically fetches Axis Bank transaction emails, categorizes spending, generates an HTML dashboard, and sends a weekly WhatsApp summary via OpenClaw.

---

## Architecture Overview

```
Every Sunday 12 AM IST (cron)
        ↓
cron job runs -> Python script (axis_tracker.py)
        ↓
Himalaya fetches Axis Bank emails via IMAP
        ↓
Parse transactions from email subject lines
        ↓
Categorize: Keyword rules based classifier
        ↓
Generate HTML dashboard → /home/zain/zainclaw/axis_spending/dashboard/
        ↓
OpenClaw sends WhatsApp summary with dashboard link
```

---

## Step 1: Enable Gmail IMAP & Generate App Password

### 1.1 Enable IMAP
1. Go to **Gmail → Settings → See all settings → Forwarding and POP/IMAP**
2. IMAP is enabled by default — no action needed if you see the IMAP settings section

### 1.2 Generate App Password
1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. You need **2-Step Verification** enabled first — go to [myaccount.google.com/security](https://myaccount.google.com/security) to enable it
3. In the **App name** field type `himalaya`
4. Click **Create**
5. Copy the 16-character password shown (no spaces) — Google won't show it again

---

## Step 2: Install Himalaya on the Server

SSH into your prod server and run:

```bash
# Check latest version
curl -s https://api.github.com/repos/pimalaya/himalaya/releases/latest | grep "tag_name"
# Output: "tag_name": "v1.2.0"

# Download that version
curl -L "https://github.com/pimalaya/himalaya/releases/download/v1.2.0/himalaya-x86_64-unknown-linux-musl.tar.gz" -o himalaya.tar.gz
tar xzf himalaya.tar.gz
sudo mv himalaya /usr/local/bin/
himalaya --version
# Output: himalaya v1.2.0
```

---

## Step 3: Configure Himalaya

```bash
mkdir -p ~/.config/himalaya
nano ~/.config/himalaya/config.toml
```

Paste this config (replace with your actual Gmail and app password):

```toml
[accounts.axis-inbox]
email = "youremail@gmail.com"
display-name = "Zain"
default = true

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "youremail@gmail.com"
backend.auth.type = "password"
backend.auth.raw = "abcdefghijklmnop"
```

Save with `Ctrl+O` → Enter → `Ctrl+X`

### Test Himalaya
```bash
himalaya envelope list
```

You should see your inbox emails listed. Axis Bank emails from `alerts@axis.bank.in` should appear with subjects like `INR 30.00 was debited from your A/c no. XX1258`.

### Read a test email
```bash
himalaya message read <EMAIL_ID>
```

Axis Bank email body format:
```
Amount Debited: INR 30.00
Account Number: XX1258
Date & Time: 14-04-26, 19:35:58 IST
Transaction Info: UPI/P2M/737295712717/BANGALORE METRO
```

---

## Step 4: Set Up Project Files

### 4.1 Create directory on server
```bash
mkdir -p /home/zain/zainclaw/axis_spending
```

### 4.2 Create the tracker script
Place `axis_tracker.py` in `/home/zain/zainclaw/axis_spending/`

### 4.3 Create SKILL.md
Place `SKILL.md` in `/home/zain/zainclaw/axis_spending/`

SKILL.md frontmatter:
```yaml
---
name: axis-spending
description: "Fetches Axis Bank transaction emails via Himalaya, categorizes spending using keyword rules + OpenAI/Gemini fallback, generates a weekly HTML dashboard, and sends a WhatsApp summary."
homepage: https://github.com/mohdzain/axis-spending
metadata: {"clawdbot":{"emoji":"💸","requires":{"bins":["himalaya","python3"]}}}
---
```

---

## Step 5: Install Python Dependencies

```bash
pip install requests openpyxl --break-system-packages
```

---

## Step 6: Set Environment Variables
create .env
```bash
nano /home/zain/zainclaw/axis_spending/.env
```

```bash
WHATSAPP_NUM=+910000000000
DASHBOARD_URL=https://claw.mohdzain.com/spending
AXIS_SENDER=alerts@axis.bank.in
AXIS_DATA_DIR=/home/zain/zainclaw/axis_spending/data
AXIS_DASHBOARD_DIR=/home/zain/zainclaw/axis_spending/dashboard
AXIS_DB_PATH=/home/zain/zainclaw/axis_spending/data/transactions.db
OPENCLAW_WHATSAPP_ENABLED=true
AXIS_DEFAULT_FETCH_DAYS=7
AXIS_LATEST_DASHBOARD_DAYS=7
```

> **Note:** Always run `source ~/.bashrc` after editing it.

---

## Step 7: Register Skill with OpenClaw

```bash
# Tell OpenClaw where your custom skills live
openclaw config set skills.load.extraDirs '["/home/zain/zainclaw/axis_spending"]'

# Restart gateway to pick up the new skill
openclaw gateway restart

# Verify skill is registered
openclaw skills list
# Should show: axis-spending
```

---

## Step 8: Configure nginx for Dashboard

Add the `/spending/` location to your existing nginx config:

```nginx
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

---

## Step 9: Test WhatsApp Sending

```bash
# Test OpenClaw WhatsApp sending directly
openclaw message send --channel whatsapp --target 917310672019 --message "test from openclaw"

# Expected output:
# ✅ Sent via gateway (whatsapp). Message ID: 3EB0059026BB58CC7EF69A
```
---

## Step 10: Test Full Script

```bash
python3 /home/zain/zainclaw/axis_spending/axis_tracker.py
```

What happens:
- the script checks DB coverage
- fetches only missing/new mail needed for sync
- updates SQLite
- regenerates dashboards
- optionally sends WhatsApp summary

Useful first-run note:
- if the DB only has recent rows, the script may backfill from the 1st of the current month so `current-month.html` is complete

Expected output:
```
🚀 Axis Spending Tracker — 08 Apr – 15 Apr 2026
==================================================
📧 Fetching Axis Bank emails from last 7 days...
✅ Found 42 transactions (3 categorized by LLM)

📊 Summary:
   Total Spent  : ₹7,916.00
   Actual Spend : ₹4,466.00
   Credited     : ₹12,500.00
   Transactions : 42

   Top Categories:
   shopping        ₹3,450.00
   food            ₹1,992.00
   other           ₹1,123.00
   medical         ₹840.00
   recharge        ₹249.00

📊 Dashboard saved: /home/zain/zainclaw/axis_spending/dashboard/week-2026-04-15.html
✅ WhatsApp message sent!

Dashboard: 
https://claw.mohdzain.com/spending/latest.html
https://claw.mohdzain.com/spending/current-month.html
https://claw.mohdzain.com/spending/all-time.html
https://claw.mohdzain.com/spending/archive.html
```

---

## Step 11: Set Up Cron Job

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

View logs after it runs:
```bash
tail -f /var/log/axis_tracker.log
```

---

## On-Demand Usage via WhatsApp

Since the skill is registered with OpenClaw, you can trigger it anytime by messaging your OpenClaw agent on WhatsApp:

| Message                                        | What happens        |
| ---------------------------------------------- | ------------------- |
| `Generate my spending report`                  | Last 7 days report  |
| `Generate my spending report for last 2 weeks` | Last 14 days report |
| `Generate my spending report for last 30 days` | Last 30 days report |
| `Show me this week's expenses`                 | Last 7 days report  |

OpenClaw reads the SKILL.md, runs the script, and replies with the WhatsApp summary + dashboard link.

---

## Categorization Logic
- Rule-based classification is used, so categorization is fast and consistent.
- Matching is done from transaction particulars and extracted merchant/target together.
- Example: `UPI/P2M/646321578806/Haleem Biryani/Paymen/AXIS BANK` maps to food because `Haleem Biryani` matches the food rules.
- If no rule matches, the transaction is assigned to other.
- Rules can be extended anytime as new merchants or repeated patterns are discovered.

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
6. Categorize using regex `CATEGORY_RULES`
7. Deduplicate and insert rows into SQLite
8. Build dashboard pages from stored history
9. Send WhatsApp summary if enabled and configured

---

## File Structure

```
/home/zain/zainclaw/
└── axis_spending/
    ├── axis_tracker.py      # Main script
    ├── SKILL.md             # OpenClaw skill definition
    └── dashboard/           # Generated HTML dashboards
        ├── latest.html      # Always the most recent report
        └── current-month.html 
        └── all-time.html
```

---

*Built with OpenClaw + Himalaya + Python · Auto-runs every Sunday 12 AM IST*