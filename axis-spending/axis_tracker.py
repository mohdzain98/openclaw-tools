#!/usr/bin/env python3
"""
Axis Bank Spending Tracker
- Fetches recent Axis Bank emails via Himalaya
- Categorizes using notebook-style regex rules
- Stores transactions in SQLite with deduplication
- Generates weekly and monthly dashboards from stored history
- Sends WhatsApp summary for the latest report
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def load_env_file(env_path):
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


BASE_DIR = Path(__file__).resolve().parent
load_env_file(BASE_DIR / ".env")

SENDER = os.environ.get("AXIS_SENDER", "alerts@axis.bank.in")
DASHBOARD_URL = os.environ.get(
    "DASHBOARD_URL", "https://claw.mohdzain.com/spending"
).rstrip("/")
DATA_DIR = Path(os.environ.get("AXIS_DATA_DIR", str(BASE_DIR / "data")))
DASHBOARD_DIR = Path(os.environ.get("AXIS_DASHBOARD_DIR", str(BASE_DIR / "dashboard")))
DB_PATH = Path(os.environ.get("AXIS_DB_PATH", str(DATA_DIR / "transactions.db")))
WHATSAPP_NUM = os.environ.get("WHATSAPP_NUM", "")
WHATSAPP_ENABLED = os.environ.get("OPENCLAW_WHATSAPP_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEFAULT_FETCH_DAYS = int(os.environ.get("AXIS_DEFAULT_FETCH_DAYS", "7"))

CATEGORY_RULES = {
    "emi": [r"\bemi\b", r"\bcred\b", r"cred club", r"loan"],
    "rent": [
        r"\brent\b",
        r"\bpg\b",
        r"7 hills pg",
        r"co-liv",
        r"visal ahmad",
        r"mahadevapura",
        r"iti ancillary",
    ],
    "food": [
        r"blinkit",
        r"fast foods?",
        r"anand bakers",
        r"sweets?",
        r"hungry",
        r"zomato",
        r"swiggy",
        r"optimum nutrition",
        r"haleem",
        r"biryani",
        r"alkhujema",
        r"yawar",
        r"\bdosa\b",
        r"al yamin",
        r"deepika shetty",
        r"udupi",
        r"abutaher",
        r"salim ali",
        r"brahmalingeswara",
        r"karama frazer town",
        r"adeppagari ravi",
        r"slice",
        r"thatha tea",
        r"sreenu chowdhary",
        r"aligarh house",
        r"sunitha",
        r"purushottam yadav",
        r"irappa basappa",
        r"shalimaar",
        r"shambo food tech",
        r"swaad aahar",
        r"madurai bun parotta",
        r"shubharani",
        r"dilwar hussain",
        r"nayab alam",
        r"naim ahmed",
        r"pizza",
        r"kabab",
        r"aleem pasha",
        r"wow momo",
        r"moola singh",
        r"yedla karthik",
        r"hammad",
        r"sultan",
        r"tiffans",
    ],
    "transport": [
        r"\bbmtc\b",
        r"\bcab\b",
        r"\bmetro\b",
        r"\bauto\b",
        r"ka\d{2}[a-z]{1,2}\d{4}",
        r"itpl",
    ],
    "credit": [
        r"refund",
        r"salary",
        r"astar data llp",
        r"\bcredit\b",
        r"\bimps cr\b",
        r"\bneft cr\b",
        r"\bupi cr\b",
    ],
    "recharge": [
        r"airtel payments bank",
        r"jio recharge",
        r"vodafone",
        r"idea",
        r"recharge",
        r"airtel",
    ],
    "airticket": [
        r"air india",
        r"indigo",
        r"makemytrip",
        r"aviation",
        r"air tra",
        r"interglobe",
        r"ixigo",
    ],
    "grocery": [
        r"super market",
        r"peekay home needs",
        r"amazon pay groceries",
        r"groceries",
        r"provision store",
    ],
    "medical": [
        r"apollo pharmacy",
        r"medicose",
        r"pathology",
        r"hospital",
        r"pharmacy",
        r"clinic",
        r"lab",
        r"gufran",
        r"mass pharma",
        r"ganesh medical",
    ],
    "shopping": [
        r"flipkart",
        r"amazon india",
        r"trends",
        r"bharatpe merchant",
        r"centro",
        r"e commerce",
        r"furnis",
        r"denim collection",
        r"decathlon",
        r"vaish boot house",
        r"shaik amjad",
        r"smartoo",
        r"mohsin mustaq",
        r"mustak",
        r"syed shahajaha",
        r"syed ibrahim",
    ],
    "maintainence": [
        r"cable",
        r"services",
        r"computers",
        r"maintenance",
        r"repair",
        r"lovely chaudhary",
    ],
    "friends": [r"mohd adil", r"faheem javed"],
    "home": [r"raziur rehman", r"rashma parveen", r"madiha rehman", r"mohtasim"],
    "juice_below_vsai": [r"mohammad mishab"],
    "hair": [r"salon", r"zion mens salon"],
    "vydehi": [r"vydehi", r"dalvkot"],
    "snapchat": [r"google india digital", r"google asia pacific"],
    "bank": [r"card charges", r"gst annual", r"bank charges", r"debit card charges"],
    "self": [r"mohd zain", r"self", r"domain", r"monthly", r"monthl"],
    "ais": [r"openai ll", r"openai"],
    "interest": [r"Int\.Pd", r"Int\.Pd:", r"SB:.*Int\.Pd"],
    "subscriptions": [r"mandatee", r"mandate", r"e mandate"],
    "gym_and_health": [r"fitness", r"gym", r"m s fitness"],
    "kayakalp": [r"kayaka"],
}

IGNORE_TOKENS = {
    "upi",
    "p2a",
    "p2m",
    "pay",
    "payment",
    "payments",
    "paymen",
    "bank",
    "yes bank limited ybs",
    "state bank of india",
    "canara bank",
    "emi",
    "credit",
    "debit",
    "ifsc",
    "neft",
    "imps",
    "rtgs",
    "transfer",
}


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            source_id TEXT PRIMARY KEY,
            tx_date TEXT NOT NULL,
            date_str TEXT NOT NULL,
            time_str TEXT NOT NULL,
            tx_type TEXT NOT NULL,
            amount REAL NOT NULL,
            merchant TEXT NOT NULL,
            target TEXT NOT NULL,
            particulars TEXT NOT NULL,
            category TEXT NOT NULL,
            account TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_transactions_tx_date ON transactions (tx_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions (category)"
    )
    conn.commit()


def pick_payee(text):
    if not isinstance(text, str):
        return ""
    text = text.replace("\r", " ").replace("\n", "/")
    if ":" in text:
        text = text.split(":", 1)[1]
    parts = [part.strip() for part in re.split(r"/+", text) if part.strip()]
    for part in parts:
        part_low = re.sub(r"[^a-z0-9 ]", "", part.lower()).strip()
        if not part_low or part_low.isdigit():
            continue
        if any(token in part_low for token in IGNORE_TOKENS):
            continue
        return part
    for part in reversed(parts):
        if len(re.sub(r"\W", "", part)) >= 2:
            return part
    return ""


def categorize_by_rules(merchant, particulars):
    text = f"{merchant} {particulars}".lower()
    for category, patterns in CATEGORY_RULES.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return category
    return "other"


def build_source_id(env_id, tx_date, amount, tx_type, particulars, account):
    if env_id:
        return f"msg:{env_id}"
    raw = f"{tx_date.isoformat()}|{amount}|{tx_type}|{particulars}|{account}"
    return "hash:" + hashlib.sha256(raw.encode()).hexdigest()


def get_fetch_plan(conn, days):
    now = datetime.now()
    requested_start = now - timedelta(days=days)

    stats = conn.execute(
        """
        SELECT
            MIN(CASE WHEN tx_date >= ? THEN tx_date END) AS min_in_window,
            MAX(CASE WHEN tx_date >= ? THEN tx_date END) AS max_in_window,
            MAX(tx_date) AS latest_overall
        FROM transactions
        """,
        (requested_start.isoformat(), requested_start.isoformat()),
    ).fetchone()

    min_in_window = (
        datetime.fromisoformat(stats["min_in_window"])
        if stats["min_in_window"]
        else None
    )
    latest_overall = (
        datetime.fromisoformat(stats["latest_overall"])
        if stats["latest_overall"]
        else None
    )

    if min_in_window is None:
        fetch_cutoff = requested_start
        reason = "no_db_rows_for_requested_window"
    elif min_in_window > requested_start + timedelta(minutes=1):
        fetch_cutoff = requested_start
        reason = "backfill_requested_window_start"
    elif latest_overall is not None:
        # Small overlap keeps the sync safe if the last run stopped mid-way.
        fetch_cutoff = latest_overall - timedelta(days=1)
        reason = "only_fetch_newer_than_latest_db_row"
    else:
        fetch_cutoff = requested_start
        reason = "fallback_requested_window"

    if fetch_cutoff < requested_start:
        fetch_cutoff = requested_start

    return {
        "requested_start": requested_start,
        "fetch_cutoff": fetch_cutoff,
        "reason": reason,
    }


def describe_fetch_plan(plan):
    requested_start = plan["requested_start"].strftime("%d %b %Y %H:%M")
    fetch_cutoff = plan["fetch_cutoff"].strftime("%d %b %Y %H:%M")
    reason = plan["reason"]

    if reason == "no_db_rows_for_requested_window":
        return (
            f"ℹ️  DB has no rows for the requested window. "
            f"Backfilling from {fetch_cutoff}."
        )
    if reason == "backfill_requested_window_start":
        return (
            f"ℹ️  DB only partially covers the requested window starting {requested_start}. "
            f"Backfilling from {fetch_cutoff}."
        )
    if reason == "only_fetch_newer_than_latest_db_row":
        return (
            f"ℹ️  DB already covers the requested window. "
            f"Only checking for newer mail from {fetch_cutoff} onward."
        )
    return f"ℹ️  Fetch plan: requesting data from {fetch_cutoff}."


def get_existing_source_ids(conn, source_ids):
    if not source_ids:
        return set()
    placeholders = ",".join("?" for _ in source_ids)
    rows = conn.execute(
        f"SELECT source_id FROM transactions WHERE source_id IN ({placeholders})",
        list(source_ids),
    ).fetchall()
    return {row["source_id"] for row in rows}


def fetch_recent_transactions(conn, days=7):
    plan = get_fetch_plan(conn, days)
    print(describe_fetch_plan(plan))
    print(
        f"📧 Fetching Axis Bank emails from {plan['fetch_cutoff'].strftime('%d %b %Y %H:%M')} "
        f"because {plan['reason']}..."
    )
    result = subprocess.run(
        ["himalaya", "--output", "json", "envelope", "list", "--page-size", "500"],
        capture_output=True,
        text=True,
    )
    try:
        envelopes = json.loads(result.stdout)
    except Exception:
        print("❌ Failed to parse himalaya output")
        return []

    transactions = []
    candidate_envs = []

    for env in envelopes:
        from_addr = env.get("from", {}).get("addr", "")
        if SENDER not in from_addr.lower():
            continue

        subject = env.get("subject", "")
        match = re.search(
            r"INR\s*([\d,]+\.?\d*)\s*was\s*(debited|credited)",
            subject,
            re.IGNORECASE,
        )
        if not match:
            continue

        amount = float(match.group(1).replace(",", ""))
        tx_type = "Debit" if "debited" in match.group(2).lower() else "Credit"

        raw_date = env.get("date", "")
        try:
            tx_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except Exception:
            tx_date = datetime.now()

        if tx_date < plan["fetch_cutoff"]:
            continue

        env_id = env.get("id")
        source_id = f"msg:{env_id}" if env_id else None
        candidate_envs.append((env, tx_date, amount, tx_type, source_id))

    existing_ids = get_existing_source_ids(
        conn, [source_id for _, _, _, _, source_id in candidate_envs if source_id]
    )

    for env, tx_date, amount, tx_type, source_id in candidate_envs:
        if source_id and source_id in existing_ids:
            continue

        subject = env.get("subject", "")
        acc_match = re.search(r"XX(\d+)", subject)
        account = f"XX{acc_match.group(1)}" if acc_match else "Unknown"

        body_result = subprocess.run(
            ["himalaya", "message", "read", str(env["id"])],
            capture_output=True,
            text=True,
        )
        body = body_result.stdout
        info_match = re.search(r"Transaction Info:\s*\n\s*(.*)", body)
        particulars = info_match.group(1).strip() if info_match else subject

        merchant = pick_payee(particulars) or particulars[:40]
        category = categorize_by_rules(merchant, particulars)
        source_id = build_source_id(env.get("id"), tx_date, amount, tx_type, particulars, account)

        transactions.append(
            {
                "source_id": source_id,
                "date": tx_date,
                "date_str": tx_date.strftime("%d %b %Y"),
                "time": tx_date.strftime("%H:%M"),
                "type": tx_type,
                "amount": amount,
                "merchant": merchant,
                "target": merchant,
                "particulars": particulars,
                "category": category,
                "account": account,
            }
        )

    print(
        f"✅ Found {len(candidate_envs)} candidate envelopes, "
        f"{len(existing_ids)} already in DB, {len(transactions)} new transactions"
    )
    return sorted(transactions, key=lambda tx: tx["date"], reverse=True)


def store_transactions(conn, transactions):
    inserted = 0
    for tx in transactions:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO transactions (
                source_id, tx_date, date_str, time_str, tx_type, amount,
                merchant, target, particulars, category, account, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx["source_id"],
                tx["date"].isoformat(),
                tx["date_str"],
                tx["time"],
                tx["type"],
                tx["amount"],
                tx["merchant"],
                tx["target"],
                tx["particulars"],
                tx["category"],
                tx["account"],
                datetime.now().isoformat(),
            ),
        )
        inserted += int(cur.rowcount == 1)
    conn.commit()
    return inserted


def rows_to_transactions(rows):
    transactions = []
    for row in rows:
        tx_date = datetime.fromisoformat(row["tx_date"])
        transactions.append(
            {
                "source_id": row["source_id"],
                "date": tx_date,
                "date_str": row["date_str"],
                "time": row["time_str"],
                "type": row["tx_type"],
                "amount": row["amount"],
                "merchant": row["merchant"],
                "target": row["target"],
                "particulars": row["particulars"],
                "category": row["category"],
                "account": row["account"],
            }
        )
    return transactions


def load_transactions_between(conn, start_dt=None, end_dt=None):
    query = "SELECT * FROM transactions"
    clauses = []
    params = []
    if start_dt is not None:
        clauses.append("tx_date >= ?")
        params.append(start_dt.isoformat())
    if end_dt is not None:
        clauses.append("tx_date < ?")
        params.append(end_dt.isoformat())
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY tx_date DESC"
    rows = conn.execute(query, params).fetchall()
    return rows_to_transactions(rows)


def load_all_transactions(conn):
    return load_transactions_between(conn)


def list_month_keys(conn):
    rows = conn.execute(
        """
        SELECT DISTINCT substr(tx_date, 1, 7) AS month_key
        FROM transactions
        ORDER BY month_key DESC
        """
    ).fetchall()
    return [row["month_key"] for row in rows]


def month_bounds(month_key):
    start_dt = datetime.strptime(month_key + "-01", "%Y-%m-%d")
    if start_dt.month == 12:
        end_dt = datetime(start_dt.year + 1, 1, 1)
    else:
        end_dt = datetime(start_dt.year, start_dt.month + 1, 1)
    return start_dt, end_dt


def build_nav_links(month_keys):
    links = [
        {"label": "Latest", "href": f"{DASHBOARD_URL}/latest.html"},
        {"label": "Current Month", "href": f"{DASHBOARD_URL}/current-month.html"},
        {"label": "All Time", "href": f"{DASHBOARD_URL}/all-time.html"},
        {"label": "Archive", "href": f"{DASHBOARD_URL}/archive.html"},
    ]
    for month_key in month_keys[:6]:
        links.append(
            {"label": month_key, "href": f"{DASHBOARD_URL}/month-{month_key}.html"}
        )
    return links


def compute_summary(transactions):
    debits = [tx for tx in transactions if tx["type"] == "Debit"]
    credits = [tx for tx in transactions if tx["type"] == "Credit"]

    category_map = defaultdict(
        lambda: {"debit": 0.0, "credit": 0.0, "net": 0.0, "count": 0}
    )
    for tx in transactions:
        row = category_map[tx["category"]]
        if tx["type"] == "Debit":
            row["debit"] += tx["amount"]
        else:
            row["credit"] += tx["amount"]
        row["count"] += 1
        row["net"] = row["credit"] - row["debit"]

    category_rows = []
    for category, values in category_map.items():
        category_rows.append(
            {
                "category": category,
                "debit": values["debit"],
                "credit": values["credit"],
                "net": values["net"],
                "count": values["count"],
            }
        )
    category_rows.sort(key=lambda row: (row["debit"] + row["credit"]), reverse=True)

    target_rows_by_category = {}
    for category in sorted({tx["category"] for tx in transactions}):
        grouped = defaultdict(lambda: {"debit": 0.0, "credit": 0.0, "count": 0})
        for tx in transactions:
            if tx["category"] != category:
                continue
            target = tx.get("target") or tx.get("merchant") or "Unknown"
            row = grouped[target]
            if tx["type"] == "Debit":
                row["debit"] += tx["amount"]
            else:
                row["credit"] += tx["amount"]
            row["count"] += 1

        target_rows = []
        for target, values in grouped.items():
            target_rows.append(
                {
                    "target": target,
                    "debit": values["debit"],
                    "credit": values["credit"],
                    "net": values["credit"] - values["debit"],
                    "count": values["count"],
                }
            )
        target_rows.sort(key=lambda row: (row["debit"] + row["credit"]), reverse=True)
        target_rows_by_category[category] = target_rows

    return {
        "total_spent": sum(tx["amount"] for tx in debits),
        "total_credited": sum(tx["amount"] for tx in credits),
        "tx_count": len(transactions),
        "debit_count": len(debits),
        "credit_count": len(credits),
        "category_rows": category_rows,
        "target_rows_by_category": target_rows_by_category,
        "transactions": transactions,
    }


def generate_dashboard(summary, period_label, page_title, nav_links):
    category_rows = summary["category_rows"]
    target_rows_by_category = summary["target_rows_by_category"]
    transactions = summary["transactions"]
    default_category = (
        max(category_rows, key=lambda row: row["debit"])["category"]
        if category_rows
        else ""
    )

    cat_colors = {
        "food": "#F97316",
        "transport": "#06B6D4",
        "rent": "#3B82F6",
        "emi": "#EAB308",
        "credit": "#22C55E",
        "recharge": "#EC4899",
        "airticket": "#8B5CF6",
        "grocery": "#10B981",
        "medical": "#F59E0B",
        "shopping": "#14B8A6",
        "maintainence": "#FB7185",
        "friends": "#F43F5E",
        "home": "#60A5FA",
        "hair": "#A78BFA",
        "snapchat": "#FACC15",
        "bank": "#94A3B8",
        "self": "#93C5FD",
        "interest": "#16A34A",
        "subscriptions": "#F9A8D4",
        "gym_and_health": "#86EFAC",
        "ais": "#C4B5FD",
        "kayakalp": "#7DD3FC",
        "vydehi": "#FDE68A",
        "juice_below_vsai": "#FDBA74",
        "other": "#CBD5E1",
    }

    nav_html = ""
    for link in nav_links:
        nav_html += f'<a class="nav-link" href="{link["href"]}">{link["label"]}</a>'

    category_table_html = ""
    for row in category_rows:
        color = cat_colors.get(row["category"], "#94A3B8")
        net_class = "amt-credit" if row["net"] >= 0 else "amt-debit"
        category_table_html += f"""
        <tr>
          <td><span class="tag" style="background:{color}20;color:{color};border:1px solid {color}40">{row['category']}</span></td>
          <td class="td-amt amt-debit">₹{row['debit']:,.0f}</td>
          <td class="td-amt amt-credit">₹{row['credit']:,.0f}</td>
          <td class="td-amt {net_class}">₹{row['net']:,.0f}</td>
          <td class="td-amt">{row['count']}</td>
        </tr>"""

    category_options_html = ""
    for row in category_rows:
        selected = " selected" if row["category"] == default_category else ""
        category_options_html += (
            f'<option value="{row["category"]}"{selected}>{row["category"]}</option>'
        )

    grouped_tables_html = ""
    for row in category_rows:
        category = row["category"]
        style = "" if category == default_category else ' style="display:none"'
        rows_html = ""
        for target_row in target_rows_by_category.get(category, []):
            net_class = "amt-credit" if target_row["net"] >= 0 else "amt-debit"
            rows_html += f"""
            <tr>
              <td>{target_row['target']}</td>
              <td class="td-amt amt-debit">₹{target_row['debit']:,.0f}</td>
              <td class="td-amt amt-credit">₹{target_row['credit']:,.0f}</td>
              <td class="td-amt {net_class}">₹{target_row['net']:,.0f}</td>
              <td class="td-amt">{target_row['count']}</td>
            </tr>"""
        if not rows_html:
            rows_html = """
            <tr>
              <td colspan="5" class="empty-state">No grouped rows for this category.</td>
            </tr>"""
        grouped_tables_html += f"""
        <div class="grouped-table" data-category="{category}"{style}>
          <table>
            <thead>
              <tr>
                <th>Target</th>
                <th style="text-align:right">Debit</th>
                <th style="text-align:right">Credit</th>
                <th style="text-align:right">Net</th>
                <th style="text-align:right">Txns</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>"""

    tx_rows_html = ""
    for tx in transactions[:60]:
        color = cat_colors.get(tx["category"], "#94A3B8")
        amt_class = "amt-debit" if tx["type"] == "Debit" else "amt-credit"
        sign = "-" if tx["type"] == "Debit" else "+"
        tx_rows_html += f"""
        <tr>
          <td class="td-date">{tx['date_str']}<span class="td-time">{tx['time']}</span></td>
          <td class="td-merchant">{tx['merchant']}</td>
          <td><span class="tag" style="background:{color}20;color:{color};border:1px solid {color}40">{tx['category']}</span></td>
          <td class="td-amt {amt_class}">{sign}₹{tx['amount']:,.0f}</td>
        </tr>"""

    net_flow = summary["total_credited"] - summary["total_spent"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0a0f;
    --surface: #13131a;
    --surface2: #1c1c26;
    --border: #2a2a38;
    --text: #e8e8f0;
    --muted: #6b6b85;
    --accent: #7c6af7;
    --accent2: #f76a8a;
    --green: #4ade80;
    --red: #f87171;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Syne', sans-serif;
    min-height: 100vh;
    padding-bottom: 48px;
  }}
  .header {{
    padding: 40px 32px 28px;
    border-bottom: 1px solid var(--border);
  }}
  .header-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 10px;
    gap: 12px;
    flex-wrap: wrap;
  }}
  .brand {{
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--accent);
    font-family: 'JetBrains Mono', monospace;
  }}
  .week-label {{
    font-size: 11px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    background: var(--surface2);
    padding: 4px 10px;
    border-radius: 4px;
    border: 1px solid var(--border);
  }}
  .nav {{
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 16px;
  }}
  .nav-link {{
    color: var(--text);
    text-decoration: none;
    font-size: 12px;
    padding: 8px 10px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
  }}
  h1 {{
    font-size: clamp(28px, 5vw, 48px);
    line-height: 1.1;
    font-weight: 800;
    margin-bottom: 6px;
  }}
  h1 span {{ color: var(--accent2); }}
  .subtitle {{
    color: var(--muted);
    font-size: 14px;
    font-family: 'JetBrains Mono', monospace;
  }}
  .container {{ max-width: 1100px; padding: 28px 32px 0; }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }}
  .stat-label {{
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 8px;
    font-family: 'JetBrains Mono', monospace;
  }}
  .stat-value {{
    font-size: 28px;
    font-weight: 700;
    line-height: 1;
  }}
  .stat-value.red {{ color: var(--red); }}
  .stat-value.green {{ color: var(--green); }}
  .stat-sub {{
    margin-top: 8px;
    font-size: 12px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
  }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 20px;
  }}
  .card-title {{
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 18px;
    font-family: 'JetBrains Mono', monospace;
  }}
  .controls {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 18px;
    flex-wrap: wrap;
  }}
  .control-label {{
    color: var(--muted);
    font-size: 12px;
    font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 2px;
  }}
  select {{
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    min-width: 220px;
    font-family: 'JetBrains Mono', monospace;
    outline: none;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead tr {{ border-bottom: 1px solid var(--border); }}
  th {{
    text-align: left;
    padding: 0 0 12px;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
  }}
  td {{
    padding: 12px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: 13px;
    vertical-align: middle;
  }}
  tr:last-child td {{ border-bottom: none; }}
  .td-date {{
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    line-height: 1.4;
  }}
  .td-time {{
    display: block;
    font-size: 11px;
    opacity: 0.6;
  }}
  .td-merchant {{
    color: var(--text);
    padding: 0 12px;
    max-width: 260px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }}
  .td-amt {{
    text-align: right;
    white-space: nowrap;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 500;
  }}
  .amt-debit {{ color: var(--red); }}
  .amt-credit {{ color: var(--green); }}
  .tag {{
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
  }}
  .empty-state {{
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    text-align: center;
    padding: 18px 0;
  }}
  .footer {{
    margin-top: 40px;
    text-align: center;
    font-size: 11px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
  }}
</style>
</head>
<body>
<div class="header">
  <div class="header-top">
    <div>
      <div class="brand">Axis · Spending</div>
      <h1>Stored <span>dashboard</span></h1>
      <div class="subtitle">{period_label} · Generated {datetime.now().strftime('%d %b %Y, %H:%M IST')}</div>
    </div>
    <div class="week-label">{summary['tx_count']} transactions</div>
  </div>
  <div class="nav">{nav_html}</div>
</div>
<div class="container">
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Total Debit</div>
      <div class="stat-value red">₹{summary['total_spent']:,.0f}</div>
      <div class="stat-sub">{summary['debit_count']} debit transactions</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total Credit</div>
      <div class="stat-value green">₹{summary['total_credited']:,.0f}</div>
      <div class="stat-sub">{summary['credit_count']} credit transactions</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Net Flow</div>
      <div class="stat-value">₹{net_flow:,.0f}</div>
      <div class="stat-sub">credit minus debit</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Categories</div>
      <div class="stat-value">{len(category_rows)}</div>
      <div class="stat-sub">categories in this view</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Category Summary</div>
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th style="text-align:right">Debit</th>
            <th style="text-align:right">Credit</th>
            <th style="text-align:right">Net</th>
            <th style="text-align:right">Txns</th>
          </tr>
        </thead>
        <tbody>{category_table_html}</tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Category Targets</div>
    <div class="controls">
      <div class="control-label">Select category to group by extracted target</div>
      <select id="category-select">{category_options_html}</select>
    </div>
    <div style="overflow-x:auto">{grouped_tables_html}</div>
  </div>

  <div class="card">
    <div class="card-title">Recent Transactions</div>
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th style="padding:0 12px">Merchant</th>
            <th>Category</th>
            <th style="text-align:right">Amount</th>
          </tr>
        </thead>
        <tbody>{tx_rows_html}</tbody>
      </table>
    </div>
  </div>
</div>
<div class="footer">axis bank spending tracker · stored history mode · {datetime.now().year}</div>
<script>
  const categorySelect = document.getElementById('category-select');
  const groupedTables = document.querySelectorAll('.grouped-table');
  function renderGroupedCategory() {{
    const selected = categorySelect.value;
    groupedTables.forEach((table) => {{
      table.style.display = table.dataset.category === selected ? 'block' : 'none';
    }});
  }}
  if (categorySelect) {{
    categorySelect.addEventListener('change', renderGroupedCategory);
    renderGroupedCategory();
  }}
</script>
</body>
</html>"""


def generate_archive_page(month_keys, nav_links):
    nav_html = ""
    for link in nav_links:
        nav_html += f'<a class="nav-link" href="{link["href"]}">{link["label"]}</a>'
    month_links_html = ""
    for month_key in month_keys:
        month_links_html += (
            f'<li><a href="{DASHBOARD_URL}/month-{month_key}.html">{month_key}</a></li>'
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Spending Archive</title>
<style>
  body {{ background:#0a0a0f; color:#e8e8f0; font-family: sans-serif; padding:40px; }}
  a {{ color:#8ab4ff; text-decoration:none; }}
  ul {{ margin-top:20px; padding-left:20px; }}
  li {{ margin-bottom:10px; }}
  .nav {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:24px; }}
  .nav a {{ background:#1c1c26; border:1px solid #2a2a38; border-radius:8px; padding:8px 10px; }}
</style>
</head>
<body>
  <h1>Spending Archive</h1>
  <div class="nav">{nav_html}</div>
  <ul>{month_links_html}</ul>
</body>
</html>"""


def save_dashboard(html, filename):
    ensure_dirs()
    path = DASHBOARD_DIR / filename
    path.write_text(html)
    print(f"📊 Dashboard saved: {path}")
    return f"{DASHBOARD_URL}/{filename}"


def send_whatsapp(summary, dashboard_url, period_label):
    if not WHATSAPP_ENABLED:
        print("ℹ️  WhatsApp sending disabled via OPENCLAW_WHATSAPP_ENABLED")
        return

    if not WHATSAPP_NUM:
        print("ℹ️  WhatsApp number missing, skipping send")
        return

    cat_lines = ""
    for row in summary["category_rows"][:5]:
        cat_lines += (
            f"  {row['category'][:12].ljust(12)} "
            f"D ₹{row['debit']:,.0f} | C ₹{row['credit']:,.0f}\n"
        )

    msg = f"""📊 *Spending Report*
_{period_label}_

💸 *Total Debit:* ₹{summary['total_spent']:,.2f}
📈 *Total Credit:* ₹{summary['total_credited']:,.2f}
🔢 *Transactions:* {summary['tx_count']}

*Category Summary:*
{cat_lines}
🔗 *Dashboard:* {dashboard_url}"""

    try:
        result = subprocess.run(
            [
                "openclaw",
                "message",
                "send",
                "--channel",
                "whatsapp",
                "--target",
                WHATSAPP_NUM,
                "--message",
                msg,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print("✅ WhatsApp message sent!")
        else:
            print(f"⚠️  WhatsApp send failed: {result.stderr}")
    except Exception as exc:
        print(f"⚠️  WhatsApp send error: {exc}")


def build_dashboards(conn, days):
    now = datetime.now()
    week_start = now - timedelta(days=days)
    week_label = f"{week_start.strftime('%d %b')} – {now.strftime('%d %b %Y')}"

    month_keys = list_month_keys(conn)
    nav_links = build_nav_links(month_keys)

    weekly_transactions = load_transactions_between(conn, start_dt=week_start)
    weekly_summary = compute_summary(weekly_transactions)
    latest_html = generate_dashboard(
        weekly_summary,
        week_label,
        f"Spending — {week_label}",
        nav_links,
    )
    latest_url = save_dashboard(latest_html, "latest.html")

    current_month_key = now.strftime("%Y-%m")
    start_dt, end_dt = month_bounds(current_month_key)
    current_month_transactions = load_transactions_between(
        conn, start_dt=start_dt, end_dt=end_dt
    )
    current_month_summary = compute_summary(current_month_transactions)
    current_month_html = generate_dashboard(
        current_month_summary,
        f"Current Month · {current_month_key}",
        f"Spending — {current_month_key}",
        nav_links,
    )
    save_dashboard(current_month_html, "current-month.html")

    all_time_transactions = load_all_transactions(conn)
    all_time_summary = compute_summary(all_time_transactions)
    all_time_html = generate_dashboard(
        all_time_summary,
        "All Time",
        "Spending — All Time",
        nav_links,
    )
    save_dashboard(all_time_html, "all-time.html")

    for month_key in month_keys:
        month_start, month_end = month_bounds(month_key)
        month_transactions = load_transactions_between(
            conn, start_dt=month_start, end_dt=month_end
        )
        month_summary = compute_summary(month_transactions)
        month_html = generate_dashboard(
            month_summary,
            f"Month View · {month_key}",
            f"Spending — {month_key}",
            nav_links,
        )
        save_dashboard(month_html, f"month-{month_key}.html")

    archive_html = generate_archive_page(month_keys, nav_links)
    save_dashboard(archive_html, "archive.html")

    return weekly_summary, latest_url, week_label


def main(days=7):
    print(f"\n🚀 Axis Spending Tracker — last {days} days fetch")
    print("=" * 50)

    conn = get_db()
    init_db(conn)

    recent_transactions = fetch_recent_transactions(conn, days=days)
    inserted = store_transactions(conn, recent_transactions)
    print(f"💾 Inserted {inserted} new transactions into {DB_PATH}")

    weekly_summary, latest_url, week_label = build_dashboards(conn, days)

    print(f"\n📊 Latest summary:")
    print(f"   Total Debit  : ₹{weekly_summary['total_spent']:,.2f}")
    print(f"   Total Credit : ₹{weekly_summary['total_credited']:,.2f}")
    print(f"   Transactions : {weekly_summary['tx_count']}")

    send_whatsapp(weekly_summary, latest_url, week_label)
    conn.close()
    print(f"\n✅ Done! Dashboard: {latest_url}")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FETCH_DAYS
    main(days=days)
