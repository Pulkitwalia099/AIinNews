import json
import os
import hmac
import hashlib
import html as html_lib
import re
import psycopg2
import anthropic
import resend as resend_lib
from datetime import date, timedelta
import urllib.parse
from flask import Flask, render_template, request, redirect, jsonify

app = Flask(__name__)

_claude_client = None


def get_claude():
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic()
    return _claude_client


def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_db():
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            is_technical TEXT,
            goals TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            source TEXT,
            location TEXT,
            start_time TIMESTAMPTZ,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS article_feedback (
            id SERIAL PRIMARY KEY,
            newsletter_date TEXT NOT NULL,
            article_url TEXT NOT NULL,
            rating TEXT NOT NULL,
            subscriber_email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (article_url, subscriber_email)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_events (
            id SERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            email_id TEXT,
            subscriber_email TEXT,
            clicked_url TEXT,
            newsletter_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Feedback enrichment columns
    cur.execute("ALTER TABLE article_feedback ADD COLUMN IF NOT EXISTS comment TEXT")
    cur.execute("ALTER TABLE article_feedback ADD COLUMN IF NOT EXISTS feedback_category TEXT")
    # PM tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pm_reports (
            id SERIAL PRIMARY KEY,
            report_date TEXT NOT NULL,
            report_md TEXT NOT NULL,
            recommendations_json JSONB,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pm_plans (
            id SERIAL PRIMARY KEY,
            report_id INTEGER,
            plan_date TEXT NOT NULL,
            plan_md TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.commit()
    cur.close()
    con.close()


try:
    init_db()
except Exception as e:
    print(f"init_db error: {e}")


def load_newsletter(date_str):
    path = f"newsletters/{date_str}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def get_all_dates():
    if not os.path.exists("newsletters"):
        return []
    files = sorted(os.listdir("newsletters"), reverse=True)
    return [f.replace(".json", "") for f in files if f.endswith(".json")]


def get_events(limit=None):
    try:
        con = get_db()
        cur = con.cursor()
        if limit:
            cur.execute("""
                SELECT title, url, source, location, start_time, description
                FROM events
                WHERE start_time > NOW()
                ORDER BY start_time ASC
                LIMIT %s
            """, (limit,))
        else:
            cur.execute("""
                SELECT title, url, source, location, start_time, description
                FROM events
                WHERE start_time > NOW()
                ORDER BY start_time ASC
            """)
        rows = cur.fetchall()
        cur.close()
        con.close()
        return [
            {
                "title": r[0], "url": r[1], "source": r[2],
                "location": r[3], "start_time": r[4], "description": r[5]
            }
            for r in rows
        ]
    except Exception as e:
        print(f"get_events error: {e}")
        return []


@app.route("/")
def index():
    dates = get_all_dates()
    if not dates:
        return "No newsletters yet. Run generate.py first."
    newsletter = load_newsletter(dates[0])
    status = request.args.get("status")
    upcoming_events = get_events(limit=3)
    return render_template("index.html", newsletter=newsletter, status=status, upcoming_events=upcoming_events)


@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = request.form.get("email", "").strip().lower()
    is_technical = request.form.get("is_technical", "")
    goals = json.dumps(request.form.getlist("goals"))

    if not email:
        return redirect("/?status=error")

    try:
        con = get_db()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO subscribers (email, is_technical, goals) VALUES (%s, %s, %s)",
            (email, is_technical, goals)
        )
        con.commit()
        cur.close()
        con.close()
        return redirect("/?status=subscribed")
    except psycopg2.IntegrityError:
        return redirect("/?status=exists")


@app.route("/debug-db")
def debug_db():
    debug_secret = os.environ.get("DEBUG_SECRET", "")
    if not debug_secret or request.args.get("secret") != debug_secret:
        return "Forbidden", 403
    try:
        db_url = os.environ.get("DATABASE_URL", "NOT SET")
        masked = db_url[:30] + "..." + db_url[-20:] if len(db_url) > 50 else db_url
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM events")
        count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM events WHERE start_time > NOW()")
        future_count = cur.fetchone()[0]
        cur.close()
        con.close()
        return f"DB URL: {masked}<br>Total events: {count}<br>Future events: {future_count}"
    except Exception as e:
        db_url = os.environ.get("DATABASE_URL", "NOT SET")
        masked = db_url[:30] + "..." + db_url[-20:] if len(db_url) > 50 else db_url
        return f"DB URL: {masked}<br>Error: {e}"


@app.route("/feedback")
def feedback():
    date_str = request.args.get("date", "")
    article_url = request.args.get("url", "")
    rating = request.args.get("rating", "")
    subscriber_email = request.args.get("email", "")

    if rating not in ("up", "down") or not article_url:
        return "Invalid feedback.", 400

    try:
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO article_feedback (newsletter_date, article_url, rating, subscriber_email)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (article_url, subscriber_email) DO UPDATE SET rating = EXCLUDED.rating
        """, (date_str, article_url, rating, subscriber_email or None))
        con.commit()
        cur.close()
        con.close()
    except Exception as e:
        print(f"[feedback] DB error: {e}")

    emoji = "👍" if rating == "up" else "👎"
    safe_url = html_lib.escape(article_url)
    safe_email = html_lib.escape(subscriber_email)

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Thanks!</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:460px;
            margin:56px auto; padding:0 24px; color:#37352f; background:#FAFAF9; }}
    .emoji {{ font-size:2.2rem; margin-bottom:10px; text-align:center; }}
    h2 {{ font-size:1.05rem; font-weight:600; margin-bottom:6px; text-align:center; }}
    .sub {{ font-size:0.86rem; color:#6b6b6b; margin-bottom:22px; text-align:center; line-height:1.6; }}
    .radio-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:14px; }}
    .radio-grid label {{
      display:flex; align-items:center; gap:8px;
      background:#fff; border:1px solid #e0e0e0; border-radius:8px;
      padding:10px 13px; font-size:0.86rem; cursor:pointer;
      transition:border-color 0.15s, background 0.15s;
    }}
    .radio-grid label:hover {{ border-color:#7b78e8; background:#f8f7ff; }}
    .radio-grid input[type=radio] {{ accent-color:#7b78e8; flex-shrink:0; }}
    .radio-grid label:has(input:checked) {{ border-color:#7b78e8; background:#eceafb; }}
    textarea {{
      width:100%; padding:10px 13px; font-size:0.86rem; font-family:inherit;
      border:1px solid #ddd; border-radius:8px; resize:vertical;
      min-height:68px; margin-bottom:13px; color:#37352f;
    }}
    textarea:focus {{ outline:none; border-color:#7b78e8; }}
    .btn-send {{
      background:#1d1d1f; color:#fff; border:none; padding:10px 22px;
      border-radius:8px; font-size:0.88rem; font-weight:600;
      cursor:pointer; font-family:inherit; width:100%;
      transition:background 0.15s;
    }}
    .btn-send:hover {{ background:#3a3a3c; }}
    .skip {{
      display:block; margin-top:12px; font-size:0.78rem; color:#b0aeab;
      text-decoration:none; text-align:center;
    }}
    .skip:hover {{ color:#6b6b6b; }}
  </style>
</head><body>
  <div class="emoji">{emoji}</div>
  <h2>Thanks for your feedback!</h2>
  <p class="sub">Want to add context? It takes 10 seconds<br>and helps improve the newsletter.</p>
  <form action="/feedback/comment" method="POST">
    <input type="hidden" name="article_url" value="{safe_url}">
    <input type="hidden" name="subscriber_email" value="{safe_email}">
    <div class="radio-grid">
      <label><input type="radio" name="feedback_category" value="bug"> 🐛 Bug report</label>
      <label><input type="radio" name="feedback_category" value="feature"> ✨ Feature request</label>
      <label><input type="radio" name="feedback_category" value="general"> 💬 General feedback</label>
      <label><input type="radio" name="feedback_category" value="question"> ❓ Question</label>
    </div>
    <textarea name="comment" placeholder="Optional: tell us more..."></textarea>
    <button class="btn-send" type="submit">Send feedback</button>
  </form>
  <a class="skip" href="https://aiinnews.space">No thanks, back to the newsletter →</a>
</body></html>"""


@app.route("/feedback/comment", methods=["POST"])
def feedback_comment():
    article_url = request.form.get("article_url", "").strip()
    subscriber_email = request.form.get("subscriber_email", "").strip()
    comment = request.form.get("comment", "").strip()
    feedback_category = request.form.get("feedback_category", "").strip()

    if article_url:
        try:
            con = get_db()
            cur = con.cursor()
            cur.execute("""
                UPDATE article_feedback
                SET comment = %s, feedback_category = %s
                WHERE article_url = %s
                  AND (subscriber_email = %s OR (subscriber_email IS NULL AND %s = ''))
            """, (
                comment[:1000] if comment else None,
                feedback_category if feedback_category else None,
                article_url,
                subscriber_email,
                subscriber_email
            ))
            con.commit()
            cur.close()
            con.close()
        except Exception as e:
            print(f"[feedback_comment] DB error: {e}")

    return redirect("https://aiinnews.space")


@app.route("/resend-webhook", methods=["POST"])
def resend_webhook():
    webhook_secret = os.environ.get("RESEND_WEBHOOK_SECRET", "")
    if webhook_secret:
        sig_header = request.headers.get("svix-signature", "")
        msg_id = request.headers.get("svix-id", "")
        msg_ts = request.headers.get("svix-timestamp", "")
        to_sign = f"{msg_id}.{msg_ts}.{request.get_data(as_text=True)}"
        expected = "v1," + __import__("base64").b64encode(
            hmac.new(webhook_secret.encode(), to_sign.encode(), hashlib.sha256).digest()
        ).decode()
        if not any(s == expected for s in sig_header.split(" ")):
            return "Unauthorized", 401

    try:
        payload = request.get_json(silent=True) or {}
        event_type = payload.get("type", "")
        data = payload.get("data", {})
        subscriber_email = data.get("to", [None])[0] if isinstance(data.get("to"), list) else data.get("to")
        email_id = data.get("email_id") or data.get("id")
        clicked_url = data.get("click", {}).get("link") if event_type == "email.clicked" else None

        subject = data.get("subject", "")
        newsletter_date = None
        if subject:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
            if m:
                newsletter_date = m.group(1)

        if event_type in ("email.opened", "email.clicked"):
            con = get_db()
            cur = con.cursor()
            cur.execute("""
                INSERT INTO email_events (event_type, email_id, subscriber_email, clicked_url, newsletter_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (event_type, email_id, subscriber_email, clicked_url, newsletter_date))
            con.commit()
            cur.close()
            con.close()
    except Exception as e:
        print(f"[resend-webhook] Error: {e}")

    return "", 200


@app.route("/events")
def events():
    all_events = get_events()
    return render_template("events.html", events=all_events)


@app.route("/archive")
def archive():
    dates = get_all_dates()
    summaries = []
    for d in dates:
        nl = load_newsletter(d)
        if not nl:
            continue
        articles = nl.get("articles", [])
        top = max(articles, key=lambda a: a.get("hn_score", 0), default=None)
        counts = {}
        for a in articles:
            s = a.get("section", "Other")
            counts[s] = counts.get(s, 0) + 1
        summaries.append({
            "date": d,
            "count": len(articles),
            "top_headline": top["title"] if top else "",
            "breakdown": counts
        })
    return render_template("archive.html", summaries=summaries)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Trigger newsletter generation. Protected by CRON_SECRET bearer token."""
    secret = os.environ.get("CRON_SECRET", "")
    auth = request.headers.get("Authorization", "")

    if not secret or auth != f"Bearer {secret}":
        return jsonify({"error": "Unauthorized"}), 401

    today = date.today().isoformat()
    path = f"newsletters/{today}.json"
    if os.path.exists(path):
        return jsonify({"status": "skipped", "reason": f"Newsletter for {today} already exists"})

    try:
        from generate import generate_newsletter
        generate_newsletter()
        return jsonify({"status": "ok", "date": today})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/<date>")
def issue(date):
    newsletter = load_newsletter(date)
    if not newsletter:
        return f"No newsletter found for {date}.", 404
    return render_template("index.html", newsletter=newsletter, status=None, upcoming_events=[])


# ---------------------------------------------------------------------------
# PM system — helpers
# ---------------------------------------------------------------------------

def make_approval_token(report_id, rec_index):
    """Generate a short HMAC token for email approve links."""
    secret = os.environ.get("PM_SECRET", "fallback")
    msg = f"{report_id}:{rec_index}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def verify_approval_token(report_id, rec_index, token):
    expected = make_approval_token(report_id, rec_index)
    return hmac.compare_digest(expected, token)


def build_codebase_context():
    return """CODEBASE FILE MAP:
  app.py: Flask app — routes, init_db, get_db, all subscriber/feedback/PM/webhook routes
  generate.py: Orchestrates fetch + process + email send
  process.py: HN scoring, dedup, Haiku selection, Sonnet analysis
  fetch.py: RSS feed fetching (19 sources from config.json across 5 tiers)
  fetch_github.py: GitHub trending repos fetch
  fetch_events.py: Events DB fetcher (Ticketmaster + curated startup events)
  email_sender.py: Resend HTML email builder and sender
  weekly_review.py: Weekly AI PM review script
  pm_reminder.py: Reminder script for unapproved plans
  templates/base.html: Base Jinja2 template with header/nav/full CSS
  templates/index.html: Newsletter homepage
  templates/pm.html: PM dashboard (standalone, no base.html)
  requirements.txt: anthropic, feedparser, flask, gunicorn, psycopg2-binary, python-dotenv, resend

KEY PATTERNS (follow exactly):
- DB: raw psycopg2, no ORM. get_db() = psycopg2.connect(os.environ["DATABASE_URL"])
- Always: con = get_db(), cur = con.cursor(), execute, commit, cur.close(), con.close()
- Claude: client = anthropic.Anthropic(); client.messages.create(model=..., max_tokens=..., messages=[...])
- Email: resend.api_key = os.environ["RESEND_API_KEY"]; resend.Emails.send({"from":..., "to":..., "subject":..., "html":...})
- Tables: CREATE TABLE IF NOT EXISTS in init_db() in app.py (no migration files)
- GitHub Actions: .github/workflows/, secrets via ${{ secrets.NAME }}
- No new dependencies. All env vars via os.environ.get() or os.environ[].
- load_dotenv() in standalone scripts (like generate.py, weekly_review.py)

DB SCHEMA (current):
- subscribers(id, email, is_technical, goals, created_at)
- article_feedback(id, newsletter_date, article_url, rating, subscriber_email, comment, feedback_category, created_at)
- email_events(id, event_type, email_id, subscriber_email, clicked_url, newsletter_date, created_at)
- events(id, title, url, source, location, start_time, description, created_at)
- pm_reports(id, report_date, report_md, recommendations_json JSONB, status, created_at)
- pm_plans(id, report_id, plan_date, plan_md, status, created_at)
"""


def build_architect_prompt(rec, report_date, refinement_notes=""):
    codebase = build_codebase_context()
    notes_section = (
        f"\nREFINEMENT NOTES FROM PRODUCT OWNER:\n{refinement_notes}\n"
        if refinement_notes.strip() else ""
    )
    return f"""You are an AI Software Architect generating an implementation plan for a Claude Code session to execute.

The project is "AI in News" — a daily AI newsletter built with Flask + psycopg2 + Anthropic + Resend, deployed on Vercel with GitHub Actions for automation.

{codebase}

=== APPROVED RECOMMENDATION ===

Title: {rec.get("title", "")}
Type: {rec.get("type", "")}
Priority: {rec.get("priority", "")}
Effort estimate: {rec.get("effort", "")}
Why this matters: {rec.get("why", "")}
What to build: {rec.get("what_to_build", "")}
Expected impact: {rec.get("impact_estimate", "")}
Report date: {report_date}{notes_section}

=== YOUR TASK ===

Generate a complete, self-contained implementation plan. Rules:
1. Follow existing code patterns exactly (see KEY PATTERNS above)
2. No new dependencies unless truly unavoidable — explain why if needed
3. Every step must be atomic and independently testable
4. Include exact SQL for DB changes (ALTER TABLE or CREATE TABLE IF NOT EXISTS — never migration files)
5. Include exact route names, function names, file names
6. Write actual working code blocks, not pseudocode — Claude Code will execute these directly
7. End with a concrete verification checklist

Use this exact markdown structure:

# Implementation Plan: [title]

## Overview
[2-3 sentences: what this does and why]

## Files to Modify
- `filename.py` — what changes and why

## Files to Create
- `new_file.py` — purpose
(Omit this section if no new files needed)

## Step-by-Step Implementation

### Step 1: [Name]
**File:** `filename.py`
**What:** [plain English description]

```python
# exact working code here
```

### Step 2: [Name]
[continue for all steps...]

## DB Changes
[Paste-ready SQL. Omit section if no DB changes.]

## New Environment Variables
[Name, where to add (GitHub secret + Vercel env), purpose. Omit if none.]

## Verification Checklist
- [ ] [specific, concrete thing to check]
- [ ] [another check]

Generate the full plan now. Write actual working code — no pseudocode."""


def send_plan_email(plan_id, plan_date, plan_title, plan_md):
    """Send the implementation plan email to Pulkit with full step-by-step instructions."""
    slug = re.sub(r"[^a-z0-9]+", "-", plan_title.lower()).strip("-")[:40]
    filename = f"plans/{plan_date}-{slug}.md"
    safe_title = html_lib.escape(plan_title)
    safe_plan = html_lib.escape(plan_md)
    safe_filename = html_lib.escape(filename)

    resend_lib.api_key = os.environ["RESEND_API_KEY"]
    resend_lib.Emails.send({
        "from": "AI in News <newsletter@aiinnews.space>",
        "to": ["pulkitwalia099@gmail.com"],
        "subject": f"AI in News — Implementation Plan Ready: {plan_title}",
        "html": f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:640px;
             margin:0 auto; padding:32px 16px; background:#FAFAF9; color:#37352f;">

  <div style="background:#fff; border-radius:10px; padding:20px 24px; margin-bottom:20px;
              border-left:4px solid #7b78e8; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
    <p style="font-size:0.7rem; font-weight:700; text-transform:uppercase;
               letter-spacing:0.08em; color:#7b78e8; margin-bottom:6px;">Implementation Plan Ready</p>
    <p style="font-size:1rem; font-weight:600; color:#1d1d1f; margin:0;">{safe_title}</p>
  </div>

  <div style="background:#f0fdf4; border-left:3px solid #34C759; border-radius:0 8px 8px 0;
              padding:18px 22px; margin-bottom:24px;">
    <p style="font-size:0.72rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
               color:#1a7f4e; margin-bottom:14px;">WHAT TO DO NOW — 3 steps</p>

    <p style="font-size:0.88rem; line-height:1.65; margin-bottom:12px;">
      <strong>Step 1: Save the plan to a file</strong><br>
      Copy everything in the grey box at the bottom of this email.<br>
      Create a new file in your ai-newsletter/ folder named:<br>
      <code style="background:#e8f5e9; padding:2px 7px; border-radius:4px;
                   font-size:0.82rem;">{safe_filename}</code>
    </p>

    <p style="font-size:0.88rem; line-height:1.65; margin-bottom:12px;">
      <strong>Step 2: Open a fresh Claude Code session</strong><br>
      Open VS Code in your ai-newsletter/ folder, or run
      <code style="background:#e8f5e9; padding:2px 6px; border-radius:4px;">claude</code>
      in your terminal there.<br>
      Use a <em>new</em> session — fresh context gives better results.
    </p>

    <p style="font-size:0.88rem; line-height:1.65; margin-bottom:12px;">
      <strong>Step 3: Paste this one instruction into Claude Code:</strong>
    </p>
    <div style="background:#fff; border:1px solid #c8e6c9; border-radius:6px;
                padding:10px 16px; font-family:monospace; font-size:0.88rem;
                color:#1d1d1f; margin-bottom:12px;">
      Execute the plan in {safe_filename}
    </div>
    <p style="font-size:0.86rem; color:#37352f; line-height:1.65; margin-bottom:14px;">
      Claude Code will read the plan and implement it step by step.
      You review and approve each action as it goes.
    </p>

    <p style="font-size:0.88rem; line-height:1.65; margin-bottom:8px;">
      <strong>After shipping, mark it done</strong> so the AI PM measures impact next Saturday:
    </p>
    <p style="font-size:0.82rem; color:#6b6b6b; margin-bottom:6px;">
      Go to <strong>supabase.com</strong> → your project → SQL Editor → run:
    </p>
    <div style="background:#fff; border:1px solid #c8e6c9; border-radius:6px;
                padding:10px 16px; font-family:monospace; font-size:0.85rem; color:#1d1d1f;">
      UPDATE pm_plans SET status = 'shipped' WHERE id = {plan_id};
    </div>
  </div>

  <p style="font-size:0.82rem; font-weight:700; color:#9b9a97; margin-bottom:8px;
             text-transform:uppercase; letter-spacing:0.06em;">
    THE PLAN — copy everything below:
  </p>
  <div style="background:#f4f4f2; border-radius:8px; padding:20px 22px;
              font-family:monospace; font-size:0.78rem; white-space:pre-wrap;
              line-height:1.65; color:#1d1d1f; overflow-x:auto;">{safe_plan}</div>

</body></html>""",
    })
    print(f"[plan_email] Sent: {plan_title}")


# ---------------------------------------------------------------------------
# PM routes
# ---------------------------------------------------------------------------

@app.route("/pm")
def pm_dashboard():
    secret = request.args.get("secret", "")
    pm_secret = os.environ.get("PM_SECRET", "")
    if not pm_secret or secret != pm_secret:
        return "Forbidden", 403

    try:
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            SELECT id, report_date, report_md, recommendations_json, status
            FROM pm_reports ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        con.close()
    except Exception as e:
        return f"DB error: {e}", 500

    if not row:
        return "No PM reports yet. Run weekly_review.py first.", 200

    report = {
        "id": row[0],
        "report_date": row[1],
        "report_md": row[2],
        "recommendations": row[3] if row[3] else [],
        "status": row[4],
    }
    return render_template("pm.html", report=report, secret=secret)


@app.route("/pm/approve-quick")
def pm_approve_quick():
    """Email-safe GET link. Validates HMAC token then generates plan."""
    try:
        report_id = int(request.args.get("report_id", ""))
        rec_index = int(request.args.get("rec_index", ""))
    except ValueError:
        return "Invalid parameters.", 400

    token = request.args.get("token", "")
    if not verify_approval_token(report_id, rec_index, token):
        return "Invalid or expired approval link.", 403

    return _do_approve(report_id, rec_index, refinement_notes="", secret="")


@app.route("/pm/approve", methods=["POST"])
def pm_approve():
    """Dashboard POST approve — with optional refinement notes."""
    secret = request.form.get("secret", "")
    pm_secret = os.environ.get("PM_SECRET", "")
    if not pm_secret or secret != pm_secret:
        return "Forbidden", 403

    try:
        report_id = int(request.form.get("report_id", ""))
        rec_index = int(request.form.get("rec_index", ""))
    except ValueError:
        return "Invalid parameters.", 400

    refinement_notes = request.form.get("refinement_notes", "").strip()
    return _do_approve(report_id, rec_index, refinement_notes, secret=secret)


def _do_approve(report_id, rec_index, refinement_notes="", secret=""):
    """Shared logic: fetch rec → call Claude Architect → save plan → email Pulkit."""
    # 1. Fetch recommendation from DB
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute(
            "SELECT report_date, recommendations_json FROM pm_reports WHERE id = %s",
            (report_id,)
        )
        row = cur.fetchone()
        cur.close()
        con.close()
    except Exception as e:
        return f"DB error: {e}", 500

    if not row:
        return "Report not found.", 404

    report_date, recs_json = row[0], row[1]
    if not recs_json or rec_index >= len(recs_json):
        return "Invalid recommendation index.", 400

    selected_rec = recs_json[rec_index]

    # 2. Call Claude as AI Architect (DB connection already closed)
    prompt = build_architect_prompt(selected_rec, report_date, refinement_notes)
    try:
        message = get_claude().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        plan_md = message.content[0].text.strip()
    except Exception as e:
        return f"Claude error: {e}", 500

    # 3. Save plan to DB + mark report approved
    try:
        plan_date = date.today().isoformat()
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO pm_plans (report_id, plan_date, plan_md, status)
            VALUES (%s, %s, %s, 'pending') RETURNING id
        """, (report_id, plan_date, plan_md))
        plan_id = cur.fetchone()[0]
        cur.execute("UPDATE pm_reports SET status = 'approved' WHERE id = %s", (report_id,))
        con.commit()
        cur.close()
        con.close()
    except Exception as e:
        return f"DB save error: {e}", 500

    # 4. Send plan email
    try:
        send_plan_email(plan_id, plan_date, selected_rec.get("title", "Plan"), plan_md)
    except Exception as e:
        print(f"[approve] Email send failed: {e}")

    # 5. Return confirmation page
    safe_title = html_lib.escape(selected_rec.get("title", ""))
    safe_plan = html_lib.escape(plan_md)
    back_link = f"/pm?secret={html_lib.escape(secret)}" if secret else "#"

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family:-apple-system,sans-serif; max-width:640px; margin:60px auto;
            padding:0 24px; color:#37352f; background:#FAFAF9; }}
    h2 {{ font-size:1.05rem; font-weight:600; margin-bottom:12px; }}
    .success {{ background:#f0fdf4; border-left:3px solid #34C759; border-radius:0 8px 8px 0;
                padding:14px 18px; margin-bottom:20px; font-size:0.88rem; line-height:1.7; }}
    a {{ color:#1d1d1f; font-size:0.85rem; }}
    .plan-box {{ background:#f4f4f2; border-radius:8px; padding:20px 22px;
                 font-family:monospace; font-size:0.77rem; white-space:pre-wrap;
                 line-height:1.65; overflow-x:auto; margin-top:20px; }}
  </style>
</head>
<body>
  <h2>Plan generated: {safe_title}</h2>
  <div class="success">
    ✅ The implementation plan has been emailed to you at pulkitwalia099@gmail.com.<br><br>
    Check your inbox — the email has step-by-step instructions to execute it in Claude Code.
  </div>
  <a href="{back_link}">&larr; Back to PM Dashboard</a>
  <div class="plan-box">{safe_plan}</div>
</body></html>"""


if __name__ == "__main__":
    app.run(debug=True)
