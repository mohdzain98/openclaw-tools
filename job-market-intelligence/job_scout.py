#!/usr/bin/env python3
"""
Job Market Intelligence Agent
- Uses Claude CLI (WebSearch tool) to find new DS/Gen AI job postings
- Stores jobs in SQLite with deduplication
- Generates latest.html (this run) and all.html (full filterable history) dashboards
- Sends WhatsApp summary via OpenClaw
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
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

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
DATA_DIR = Path(os.environ.get("JOBS_DATA_DIR", str(BASE_DIR / "data")))
DASHBOARD_DIR = Path(os.environ.get("JOBS_DASHBOARD_DIR", str(BASE_DIR / "dashboard")))
DB_PATH = Path(os.environ.get("JOBS_DB_PATH", str(DATA_DIR / "jobs.db")))
WHATSAPP_NUM = os.environ.get("WHATSAPP_NUM", "")
WHATSAPP_ENABLED = os.environ.get("OPENCLAW_WHATSAPP_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/home/zain/.local/bin/claude")
PROMPT_FILE = Path(os.environ.get("JOBS_PROMPT_FILE", str(BASE_DIR / "prompt.txt")))

JOB_ROLES_RAW = os.environ.get(
    "JOB_ROLES",
    "Data Scientist,Gen AI Engineer,ML Engineer,LLM Engineer,AI Researcher",
)
JOB_ROLES = [r.strip() for r in JOB_ROLES_RAW.split(",") if r.strip()]

JOB_SEARCH_DAYS = int(os.environ.get("JOB_SEARCH_DAYS", "2"))

# Location weights — used for scoring and search queries
LOCATION_CONFIG = [
    {"name": "Bengaluru", "keywords": ["bengaluru", "bangalore"], "weight": 0.40},
    {
        "name": "Delhi NCR",
        "keywords": ["delhi", "noida", "ncr", "gurugram", "gurgaon", "faridabad"],
        "weight": 0.25,
    },
    {"name": "Hyderabad", "keywords": ["hyderabad", "secunderabad"], "weight": 0.20},
    {
        "name": "Mumbai",
        "keywords": ["mumbai", "navi mumbai", "thane", "pune"],
        "weight": 0.15,
    },
    {"name": "Remote", "keywords": ["remote"], "weight": 0.35},
]

SEARCH_LOCATIONS = [lc["name"] for lc in LOCATION_CONFIG]

TAG_COLORS = {
    "Gen AI": "#7c6af7",
    "LLM": "#a78bfa",
    "Data Science": "#06b6d4",
    "ML": "#3b82f6",
    "Remote": "#22c55e",
    "NLP": "#ec4899",
    "MLOps": "#f97316",
    "Startup": "#f59e0b",
    "MNC": "#94a3b8",
    "Senior": "#f43f5e",
    "Junior": "#4ade80",
    "Contract": "#fb923c",
    "AI/ML": "#818cf8",
}


# ── DB ────────────────────────────────────────────────────────────────────────


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
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            company     TEXT NOT NULL,
            location    TEXT NOT NULL,
            apply_url   TEXT NOT NULL,
            source      TEXT NOT NULL,
            tags        TEXT NOT NULL,
            score       INTEGER NOT NULL,
            date_found  TEXT NOT NULL,
            applied     INTEGER NOT NULL DEFAULT 0
        )
    """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_date ON jobs (date_found)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (score)")
    conn.commit()


def make_job_id(title, company):
    raw = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_existing_ids(conn, ids):
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id FROM jobs WHERE id IN ({placeholders})", list(ids)
    ).fetchall()
    return {row["id"] for row in rows}


def store_jobs(conn, jobs):
    today = datetime.now().strftime("%Y-%m-%d")
    inserted = 0
    for job in jobs:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (id, title, company, location, apply_url, source, tags, score, date_found, applied)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                job["id"],
                job["title"],
                job["company"],
                job["location"],
                job["apply_url"],
                job["source"],
                json.dumps(job["tags"]),
                job["score"],
                today,
            ),
        )
        inserted += int(cur.rowcount == 1)
    conn.commit()
    return inserted


def load_jobs(conn, since_date=None):
    query = "SELECT * FROM jobs"
    params = []
    if since_date:
        query += " WHERE date_found >= ?"
        params.append(since_date)
    query += " ORDER BY score DESC, date_found DESC"
    rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "title": row["title"],
                "company": row["company"],
                "location": row["location"],
                "apply_url": row["apply_url"],
                "source": row["source"],
                "tags": json.loads(row["tags"]),
                "score": row["score"],
                "date_found": row["date_found"],
                "applied": row["applied"],
            }
        )
    return result


# ── CLAUDE SEARCH ─────────────────────────────────────────────────────────────


def run_claude(prompt):
    print("🤖 Running Claude CLI with WebSearch...")
    result = subprocess.run(
        [
            CLAUDE_BIN,
            "--print",
            "--output-format",
            "text",
            "--allowedTools",
            "WebSearch",
            "-p",
            prompt,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print(f"❌ Claude CLI failed: {result.stderr[:300]}")
        sys.exit(1)
    output = result.stdout.strip()
    print(f"✅ Claude completed ({len(output)} chars)")
    return output


def search_jobs():
    if not PROMPT_FILE.exists():
        print(f"❌ Prompt file not found: {PROMPT_FILE}")
        sys.exit(1)

    template = PROMPT_FILE.read_text()
    prompt = (
        template.replace("[DATE]", datetime.now().strftime("%B %d, %Y"))
        .replace(
            "[CUTOFF]",
            (datetime.now() - timedelta(days=JOB_SEARCH_DAYS)).strftime("%B %d, %Y"),
        )
        .replace("[ROLES]", ", ".join(JOB_ROLES))
        .replace("[LOCATIONS]", ", ".join(SEARCH_LOCATIONS))
    )

    output = run_claude(prompt)

    # Strip markdown fences if present
    output = re.sub(r"```(?:json)?", "", output).strip()

    json_match = re.search(r"\[.*\]", output, re.DOTALL)
    if not json_match:
        print("⚠️  Claude returned no JSON array")
        return []

    try:
        jobs = json.loads(json_match.group())
        return jobs if isinstance(jobs, list) else []
    except json.JSONDecodeError as exc:
        print(f"⚠️  JSON parse error: {exc}")
        return []


# ── SCORING ───────────────────────────────────────────────────────────────────


def score_job(job):
    score = 50
    title_lower = job.get("title", "").lower()
    tags_lower = " ".join(job.get("tags", [])).lower()
    loc_lower = job.get("location", "").lower()

    # Gen AI / LLM specific bonus
    genai_kws = [
        "gen ai",
        "genai",
        "generative",
        "llm",
        "large language",
        "foundational model",
    ]
    if any(kw in title_lower for kw in genai_kws):
        score += 20
    elif any(kw in tags_lower for kw in genai_kws):
        score += 12

    # ML / DS relevance
    ml_kws = [
        "machine learning",
        " ml ",
        "data scien",
        "deep learning",
        "nlp",
        "ai engineer",
        "mlops",
    ]
    if any(kw in title_lower for kw in ml_kws):
        score += 10

    # Location weight
    for lc in LOCATION_CONFIG:
        if any(kw in loc_lower for kw in lc["keywords"]):
            score += int(lc["weight"] * 30)
            break

    # Remote bonus (additive to location)
    if "remote" in tags_lower or "remote" in loc_lower:
        score += 5

    return min(score, 100)


def process_jobs(raw_jobs):
    """Validate, score, and deduplicate extracted jobs."""
    seen = set()
    result = []
    for job in raw_jobs:
        title = (job.get("title") or "").strip()
        company = (job.get("company") or "").strip()
        if not title or not company:
            continue

        job_id = make_job_id(title, company)
        if job_id in seen:
            continue
        seen.add(job_id)

        result.append(
            {
                "id": job_id,
                "title": title,
                "company": company,
                "location": (job.get("location") or "India").strip(),
                "apply_url": (job.get("apply_url") or "").strip(),
                "source": (job.get("source") or "other").strip().lower(),
                "tags": job.get("tags") or [],
                "score": score_job(job),
            }
        )

    result.sort(key=lambda j: j["score"], reverse=True)
    return result


# ── HTML GENERATION ───────────────────────────────────────────────────────────

_CSS = """
:root {
  --bg: #0a0a0f; --surface: #13131a; --surface2: #1c1c26;
  --border: #2a2a38; --text: #e8e8f0; --muted: #6b6b85;
  --accent: #7c6af7; --accent2: #f76a8a; --green: #4ade80; --red: #f87171;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Syne', sans-serif; min-height: 100vh; padding-bottom: 48px; }
.header { padding: 40px 32px 28px; border-bottom: 1px solid var(--border); }
.header-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; gap: 12px; flex-wrap: wrap; }
.brand { font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: var(--accent); font-family: 'JetBrains Mono', monospace; }
.badge { font-size: 11px; color: var(--muted); font-family: 'JetBrains Mono', monospace; background: var(--surface2); padding: 4px 10px; border-radius: 4px; border: 1px solid var(--border); }
.nav { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
.nav-link { color: var(--text); text-decoration: none; font-size: 12px; padding: 8px 10px; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; font-family: 'JetBrains Mono', monospace; }
.nav-link:hover { border-color: var(--accent); color: var(--accent); }
h1 { font-size: clamp(28px, 5vw, 48px); line-height: 1.1; font-weight: 800; margin-bottom: 6px; }
h1 span { color: var(--accent2); }
.subtitle { color: var(--muted); font-size: 14px; font-family: 'JetBrains Mono', monospace; }
.container { max-width: 1100px; padding: 28px 32px 0; }
.filters { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }
.filters input, .filters select { background: var(--surface2); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; font-family: 'JetBrains Mono', monospace; font-size: 13px; outline: none; }
.filters input { flex: 1; min-width: 200px; }
.filters input:focus, .filters select:focus { border-color: var(--accent); }
table { width: 100%; border-collapse: collapse; }
thead tr { border-bottom: 1px solid var(--border); }
th { text-align: left; padding: 0 12px 12px; font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
th:first-child { padding-left: 0; }
td { padding: 14px 12px; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 13px; vertical-align: middle; }
td:first-child { padding-left: 0; }
tr:last-child td { border-bottom: none; }
tr.hidden { display: none; }
.td-score { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; }
.score-high { color: var(--green); }
.score-mid  { color: #f59e0b; }
.score-low  { color: var(--muted); }
.td-title { font-weight: 600; max-width: 280px; }
.td-company { color: var(--muted); font-size: 12px; font-family: 'JetBrains Mono', monospace; }
.td-loc { font-size: 12px; color: var(--muted); font-family: 'JetBrains Mono', monospace; white-space: nowrap; }
.tags { display: flex; gap: 5px; flex-wrap: wrap; }
.tag { font-size: 10px; padding: 2px 7px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; white-space: nowrap; }
.btn-apply { display: inline-block; padding: 6px 14px; background: var(--accent); color: #fff; border-radius: 6px; text-decoration: none; font-size: 12px; font-family: 'JetBrains Mono', monospace; white-space: nowrap; }
.btn-apply:hover { opacity: 0.85; }
.btn-apply.no-url { background: var(--surface2); color: var(--muted); border: 1px solid var(--border); cursor: default; pointer-events: none; }
.btn-applied { display: inline-block; padding: 6px 14px; background: transparent; color: var(--green); border: 1px solid var(--green); border-radius: 6px; font-size: 12px; font-family: 'JetBrains Mono', monospace; cursor: pointer; white-space: nowrap; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 20px; }
.card-title { font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: var(--muted); margin-bottom: 18px; font-family: 'JetBrains Mono', monospace; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
.stat-label { font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; font-family: 'JetBrains Mono', monospace; }
.stat-value { font-size: 28px; font-weight: 700; line-height: 1; }
.stat-sub { margin-top: 6px; font-size: 12px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
.empty-state { text-align: center; padding: 40px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
.footer { margin-top: 40px; text-align: center; font-size: 11px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
@media (max-width: 640px) {
  .header { padding: 24px 16px 16px; }
  .container { padding: 16px 16px 0; }
  th { font-size: 9px; padding: 0 8px 10px; }
  td { padding: 12px 8px; font-size: 12px; }
}
"""

_FONTS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">"""


def _tag_html(tags):
    parts = []
    for tag in tags:
        color = TAG_COLORS.get(tag, "#6b6b85")
        parts.append(
            f'<span class="tag" style="background:{color}20;color:{color};border:1px solid {color}40">'
            f"{tag}</span>"
        )
    return '<div class="tags">' + "".join(parts) + "</div>"


def _score_class(score):
    if score >= 75:
        return "score-high"
    if score >= 60:
        return "score-mid"
    return "score-low"


def _apply_btn(job):
    url = job.get("apply_url", "")
    if url:
        return f'<a class="btn-apply" href="{url}" target="_blank" rel="noopener">Apply →</a>'
    return '<span class="btn-apply no-url">No URL</span>'


def _job_row_html(job, include_date=False, include_applied_btn=False):
    score_cls = _score_class(job["score"])
    date_col = f'<td class="td-loc">{job["date_found"]}</td>' if include_date else ""
    applied_btn = ""
    if include_applied_btn:
        applied_btn = (
            f'<td><button class="btn-applied" onclick="toggleApplied(this, \'{job["id"]}\')" '
            f'id="btn-{job["id"]}">Mark Applied</button></td>'
        )
    return (
        f"<tr data-id=\"{job['id']}\" data-loc=\"{job['location'].lower()}\" "
        f"data-tags=\"{' '.join(job['tags']).lower()}\" "
        f"data-title=\"{job['title'].lower()}\" data-company=\"{job['company'].lower()}\">"
        f'<td class="td-score {score_cls}">{job["score"]}</td>'
        f'<td><div class="td-title">{job["title"]}</div>'
        f'<div class="td-company">{job["company"]}</div></td>'
        f'<td class="td-loc">{job["location"]}</td>'
        f'<td>{_tag_html(job["tags"])}</td>'
        f'<td class="td-loc">{job["source"]}</td>'
        f"{date_col}"
        f"<td>{_apply_btn(job)}</td>"
        f"{applied_btn}"
        "</tr>"
    )


def generate_latest_html(jobs, run_date):
    nav_html = (
        f'<a class="nav-link" href="{DASHBOARD_URL}/latest.html">Latest Run</a>'
        f'<a class="nav-link" href="{DASHBOARD_URL}/all.html">All Jobs</a>'
    )
    top_picks = [j for j in jobs if j["score"] >= 75]
    loc_counts = {}
    for j in jobs:
        loc_counts[j["location"]] = loc_counts.get(j["location"], 0) + 1
    top_loc = max(loc_counts, key=loc_counts.get) if loc_counts else "—"

    rows_html = "".join(_job_row_html(j) for j in jobs)
    if not rows_html:
        rows_html = '<tr><td colspan="6" class="empty-state">No new jobs found in this run.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Scout — Latest Run {run_date}</title>
{_FONTS}
<style>{_CSS}</style>
</head>
<body>
<div class="header">
  <div class="header-top">
    <div>
      <div class="brand">OpenClaw · Job Scout</div>
      <h1>Latest <span>jobs</span></h1>
      <div class="subtitle">Run {run_date} · Generated {datetime.now().strftime('%d %b %Y, %H:%M IST')}</div>
    </div>
    <div class="badge">{len(jobs)} new jobs</div>
  </div>
  <div class="nav">{nav_html}</div>
</div>
<div class="container">
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">New Jobs</div>
      <div class="stat-value">{len(jobs)}</div>
      <div class="stat-sub">found this run</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Top Picks</div>
      <div class="stat-value" style="color:var(--green)">{len(top_picks)}</div>
      <div class="stat-sub">score ≥ 75</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Top Location</div>
      <div class="stat-value" style="font-size:20px">{top_loc}</div>
      <div class="stat-sub">{loc_counts.get(top_loc, 0)} jobs</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Roles Searched</div>
      <div class="stat-value">{len(JOB_ROLES)}</div>
      <div class="stat-sub">across {len(SEARCH_LOCATIONS)} locations</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Jobs Found — Sorted by Relevance Score</div>
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>Score</th><th>Role / Company</th><th>Location</th>
            <th>Tags</th><th>Source</th><th>Apply</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>
</div>
<div class="footer">openclaw job scout · {run_date} · <a href="{DASHBOARD_URL}/all.html" style="color:var(--accent)">view all jobs →</a></div>
</body>
</html>"""


def generate_all_html(jobs):
    nav_html = (
        f'<a class="nav-link" href="{DASHBOARD_URL}/latest.html">Latest Run</a>'
        f'<a class="nav-link" href="{DASHBOARD_URL}/all.html">All Jobs</a>'
    )

    # Collect unique locations and tags for filters
    all_locs = sorted({j["location"] for j in jobs})
    all_tags = sorted({tag for j in jobs for tag in j["tags"]})

    loc_options = '<option value="">All Locations</option>' + "".join(
        f'<option value="{l.lower()}">{l}</option>' for l in all_locs
    )
    tag_options = '<option value="">All Tags</option>' + "".join(
        f'<option value="{t.lower()}">{t}</option>' for t in all_tags
    )

    rows_html = "".join(
        _job_row_html(j, include_date=True, include_applied_btn=True) for j in jobs
    )
    if not rows_html:
        rows_html = (
            '<tr><td colspan="8" class="empty-state">No jobs in database yet.</td></tr>'
        )

    applied_js = """
function toggleApplied(btn, id) {
  const applied = JSON.parse(localStorage.getItem('applied_jobs') || '{}');
  if (applied[id]) {
    delete applied[id];
    btn.textContent = 'Mark Applied';
    btn.style.color = '';
    btn.style.borderColor = '';
    btn.closest('tr').style.opacity = '1';
  } else {
    applied[id] = true;
    btn.textContent = '✓ Applied';
    btn.style.color = 'var(--green)';
    btn.style.borderColor = 'var(--green)';
    btn.closest('tr').style.opacity = '0.5';
  }
  localStorage.setItem('applied_jobs', JSON.stringify(applied));
}
function restoreApplied() {
  const applied = JSON.parse(localStorage.getItem('applied_jobs') || '{}');
  for (const id in applied) {
    const btn = document.getElementById('btn-' + id);
    if (btn) {
      btn.textContent = '✓ Applied';
      btn.style.color = 'var(--green)';
      btn.style.borderColor = 'var(--green)';
      btn.closest('tr').style.opacity = '0.5';
    }
  }
}
function filterJobs() {
  const q     = document.getElementById('search').value.toLowerCase();
  const loc   = document.getElementById('loc-filter').value.toLowerCase();
  const tag   = document.getElementById('tag-filter').value.toLowerCase();
  document.querySelectorAll('tbody tr').forEach(row => {
    const title   = row.dataset.title   || '';
    const company = row.dataset.company || '';
    const rowLoc  = row.dataset.loc     || '';
    const rowTags = row.dataset.tags    || '';
    const matchQ   = !q   || title.includes(q) || company.includes(q);
    const matchLoc = !loc || rowLoc.includes(loc);
    const matchTag = !tag || rowTags.includes(tag);
    row.classList.toggle('hidden', !(matchQ && matchLoc && matchTag));
  });
}
window.addEventListener('DOMContentLoaded', restoreApplied);
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Scout — All Jobs</title>
{_FONTS}
<style>{_CSS}</style>
</head>
<body>
<div class="header">
  <div class="header-top">
    <div>
      <div class="brand">OpenClaw · Job Scout</div>
      <h1>All <span>jobs</span></h1>
      <div class="subtitle">{len(jobs)} total · Updated {datetime.now().strftime('%d %b %Y, %H:%M IST')}</div>
    </div>
    <div class="badge">{len(jobs)} jobs</div>
  </div>
  <div class="nav">{nav_html}</div>
</div>
<div class="container">
  <div class="filters">
    <input  id="search"     type="text"   placeholder="Search title or company..." oninput="filterJobs()">
    <select id="loc-filter" onchange="filterJobs()">{loc_options}</select>
    <select id="tag-filter" onchange="filterJobs()">{tag_options}</select>
  </div>

  <div class="card">
    <div class="card-title">All Jobs (Applied status saved locally)</div>
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>Score</th><th>Role / Company</th><th>Location</th>
            <th>Tags</th><th>Source</th><th>Found</th><th>Apply</th><th>Status</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>
</div>
<div class="footer">openclaw job scout · applied status stored in browser localStorage · {datetime.now().year}</div>
<script>{applied_js}</script>
</body>
</html>"""


# ── DASHBOARD SAVE ────────────────────────────────────────────────────────────


def save_dashboard(html, filename):
    ensure_dirs()
    path = DASHBOARD_DIR / filename
    path.write_text(html, encoding="utf-8")
    url = f"{DASHBOARD_URL}/{filename}"
    print(f"📊 Dashboard saved: {path} → {url}")
    return url


# ── WHATSAPP ──────────────────────────────────────────────────────────────────


def send_whatsapp(new_jobs, run_date):
    if not WHATSAPP_ENABLED:
        print("ℹ️  WhatsApp disabled via OPENCLAW_WHATSAPP_ENABLED")
        return
    if not WHATSAPP_NUM:
        print("ℹ️  WHATSAPP_NUM not set, skipping")
        return

    top_picks = [j for j in new_jobs if j["score"] >= 75][:3]
    top_lines = ""
    for i, j in enumerate(top_picks, 1):
        top_lines += f"  {i}. {j['title']} @ {j['company']} — {j['location']}\n"
    if not top_lines:
        top_lines = "  (no top picks this run)\n"

    msg = (
        f"🧠 *Job Scout* — {run_date}\n\n"
        f"🆕 *{len(new_jobs)} new jobs* found!\n\n"
        f"🌟 *Top picks:*\n{top_lines}\n"
        f"📊 *Dashboards:*\n"
        f"latest → {DASHBOARD_URL}/latest.html\n"
        f"all    → {DASHBOARD_URL}/all.html"
    )

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


# ── MAIN ──────────────────────────────────────────────────────────────────────


def main():
    run_date = datetime.now().strftime("%d %b %Y")
    print(f"\n🚀 Job Scout — {run_date}")
    print("=" * 50)

    conn = get_db()
    init_db(conn)

    # 1. Search + extract via Claude CLI
    raw_jobs = search_jobs()
    print(f"   Claude found: {len(raw_jobs)} candidate jobs")

    # 3. Process (validate + score + local dedup)
    processed = process_jobs(raw_jobs)
    print(f"   After local dedup: {len(processed)} jobs")

    # 4. DB dedup — filter already-seen jobs
    all_ids = [j["id"] for j in processed]
    seen_ids = get_existing_ids(conn, all_ids)
    new_jobs = [j for j in processed if j["id"] not in seen_ids]
    print(f"   New (not in DB):   {len(new_jobs)} jobs")

    # 5. Store
    inserted = store_jobs(conn, new_jobs)
    print(f"💾 Inserted {inserted} jobs into {DB_PATH}")

    # 6. Dashboards
    print("\n📊 Generating dashboards...")
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_jobs = load_jobs(conn)
    latest_url = save_dashboard(generate_latest_html(new_jobs, run_date), "latest.html")
    save_dashboard(generate_all_html(all_jobs), "all.html")

    # 7. Summary
    top_picks = [j for j in new_jobs if j["score"] >= 75]
    print(f"\n📈 Summary:")
    print(f"   New jobs found : {len(new_jobs)}")
    print(f"   Top picks (≥75): {len(top_picks)}")
    if top_picks:
        for j in top_picks[:5]:
            print(f"   [{j['score']}] {j['title']} @ {j['company']} — {j['location']}")
    print(f"\n🔗 Dashboards:")
    print(f"   latest → {DASHBOARD_URL}/latest.html")
    print(f"   all    → {DASHBOARD_URL}/all.html")

    # 8. WhatsApp
    send_whatsapp(new_jobs, run_date)

    conn.close()
    print(f"\n✅ Done!")


if __name__ == "__main__":
    main()
