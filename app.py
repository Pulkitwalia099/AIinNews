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
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS tags TEXT")
    # Backfill tags for existing events that have NULL tags
    cur.execute("SELECT id, title, location, description FROM events WHERE tags IS NULL OR tags = ''")
    backfill_rows = cur.fetchall()
    if backfill_rows:
        from fetch_events import classify_event_regex
        for row in backfill_rows:
            event = {"title": row[1] or "", "location": row[2] or "", "description": row[3] or "", "source": ""}
            tags = classify_event_regex(event)
            cur.execute("UPDATE events SET tags = %s WHERE id = %s", (tags, row[0]))
        print(f"Backfilled tags for {len(backfill_rows)} existing events.")
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
    cur.execute("ALTER TABLE article_feedback ADD COLUMN IF NOT EXISTS liked_aspects TEXT")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_feedback (
            id SERIAL PRIMARY KEY,
            feedback_type TEXT NOT NULL,
            comment TEXT,
            subscriber_email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
    cur.execute("ALTER TABLE pm_plans ADD COLUMN IF NOT EXISTS rec_index INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE pm_plans ADD COLUMN IF NOT EXISTS shipped_note TEXT")
    cur.execute("ALTER TABLE product_feedback ADD COLUMN IF NOT EXISTS plan_id INTEGER")
    cur.execute("ALTER TABLE product_feedback ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMP")
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
                SELECT title, url, source, location, start_time, description, tags
                FROM events
                WHERE start_time > NOW()
                ORDER BY start_time ASC
                LIMIT %s
            """, (limit,))
        else:
            cur.execute("""
                SELECT title, url, source, location, start_time, description, tags
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
                "location": r[3], "start_time": r[4], "description": r[5],
                "tags": r[6] or ""
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

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return redirect("/?status=error")

    con = None
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO subscribers (email, is_technical, goals) VALUES (%s, %s, %s)",
            (email, is_technical, goals)
        )
        con.commit()
        cur.close()
        return redirect("/?status=subscribed")
    except psycopg2.IntegrityError:
        return redirect("/?status=exists")
    except Exception as e:
        print(f"[subscribe] DB error: {e}")
        return redirect("/?status=error")
    finally:
        if con:
            con.close()


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

    con = None
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
    except Exception as e:
        print(f"[feedback] DB error: {e}")
    finally:
        if con:
            con.close()

    safe_url = html_lib.escape(article_url)
    safe_email = html_lib.escape(subscriber_email)

    _shared_css = """
    *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
    body { font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:400px;
           margin:48px auto; padding:0 24px; color:#37352f; background:#FAFAF9; }
    .emoji { font-size:1.8rem; margin-bottom:6px; text-align:center; }
    h2 { font-size:0.98rem; font-weight:600; margin-bottom:4px; text-align:center; }
    .sub { font-size:0.82rem; color:#6b6b6b; margin-bottom:18px; text-align:center; }
    textarea { width:100%; padding:9px 12px; font-size:0.83rem; font-family:inherit;
               border:1px solid #ddd; border-radius:8px; resize:none; height:56px;
               margin-bottom:11px; color:#37352f; }
    textarea:focus { outline:none; border-color:#7b78e8; }
    .btn-send { background:#1d1d1f; color:#fff; border:none; padding:10px 0;
                border-radius:8px; font-size:0.85rem; font-weight:600;
                cursor:pointer; font-family:inherit; width:100%; }
    .btn-send:hover { background:#3a3a3c; }
    .skip { display:block; margin-top:9px; font-size:0.74rem; color:#b0aeab;
            text-decoration:none; text-align:center; }
    .skip:hover { color:#6b6b6b; }"""

    if rating == "up":
        return f"""<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Thanks!</title>
  <style>{_shared_css}
    .chips {{ display:flex; flex-wrap:wrap; gap:7px; margin-bottom:14px; }}
    .chip {{ background:#fff; border:1px solid #e0e0e0; border-radius:20px;
             padding:7px 13px; font-size:0.81rem; color:#37352f; cursor:pointer;
             font-family:inherit; transition:all 0.12s; }}
    .chip:hover {{ border-color:#7b78e8; background:#f0effe; }}
    .chip.active {{ background:#eceafb; border-color:#7b78e8; color:#4240b8; font-weight:500; }}
  </style>
</head><body>
  <div class="emoji">&#128077;</div>
  <h2>Glad it was useful!</h2>
  <p class="sub">What resonated? <span style="color:#b0aeab;font-size:0.78rem;">(optional, pick any)</span></p>
  <form action="/feedback/comment" method="POST">
    <input type="hidden" name="article_url" value="{safe_url}">
    <input type="hidden" name="subscriber_email" value="{safe_email}">
    <input type="hidden" name="liked_aspects" id="liked-input" value="">
    <div class="chips">
      <button type="button" class="chip" data-v="relevant">Relevant to my work</button>
      <button type="button" class="chip" data-v="new">Learned something new</button>
      <button type="button" class="chip" data-v="mix">Good mix of topics</button>
      <button type="button" class="chip" data-v="writing">Well written</button>
    </div>
    <textarea name="comment" placeholder="Anything else... (optional)"></textarea>
    <button class="btn-send" type="submit">Send &#8594;</button>
  </form>
  <a class="skip" href="https://aiinnews.space">No thanks &#8594;</a>
  <script>
    document.querySelectorAll('.chip').forEach(function(c) {{
      c.addEventListener('click', function() {{
        c.classList.toggle('active');
        var vals = [];
        document.querySelectorAll('.chip.active').forEach(function(a) {{ vals.push(a.dataset.v); }});
        document.getElementById('liked-input').value = vals.join(',');
      }});
    }});
  </script>
</body></html>"""

    else:
        return f"""<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Thanks!</title>
  <style>{_shared_css}
    .chips {{ display:flex; flex-wrap:wrap; gap:7px; margin-bottom:14px; }}
    .chip {{ background:#fff; border:1px solid #e0e0e0; border-radius:20px;
             padding:7px 13px; font-size:0.81rem; color:#37352f; cursor:pointer;
             font-family:inherit; transition:all 0.12s; }}
    .chip:hover {{ border-color:#d96a3a; background:#fff5f0; }}
    .chip.active {{ background:#fff0eb; border-color:#d96a3a; color:#b84a1e; font-weight:500; }}
  </style>
</head><body>
  <div class="emoji">&#128078;</div>
  <h2>Thanks for letting us know.</h2>
  <p class="sub">What went wrong? <span style="color:#b0aeab;font-size:0.78rem;">(optional, pick any)</span></p>
  <form action="/feedback/comment" method="POST">
    <input type="hidden" name="article_url" value="{safe_url}">
    <input type="hidden" name="subscriber_email" value="{safe_email}">
    <input type="hidden" name="feedback_category" id="category-input" value="">
    <div class="chips">
      <button type="button" class="chip" data-v="not_relevant">Not relevant to my work</button>
      <button type="button" class="chip" data-v="too_basic">Already knew this</button>
      <button type="button" class="chip" data-v="too_advanced">Hard to follow</button>
      <button type="button" class="chip" data-v="inaccurate">Something seemed off</button>
    </div>
    <textarea name="comment" placeholder="Tell us more... (optional)"></textarea>
    <button class="btn-send" type="submit">Send &#8594;</button>
  </form>
  <a class="skip" href="https://aiinnews.space">No thanks &#8594;</a>
  <script>
    document.querySelectorAll('.chip').forEach(function(c) {{
      c.addEventListener('click', function() {{
        c.classList.toggle('active');
        var vals = [];
        document.querySelectorAll('.chip.active').forEach(function(a) {{ vals.push(a.dataset.v); }});
        document.getElementById('category-input').value = vals.join(',');
      }});
    }});
  </script>
</body></html>"""


@app.route("/feedback/comment", methods=["POST"])
def feedback_comment():
    article_url = request.form.get("article_url", "").strip()
    subscriber_email = request.form.get("subscriber_email", "").strip()
    comment = request.form.get("comment", "").strip()
    feedback_category = request.form.get("feedback_category", "").strip()
    liked_aspects = request.form.get("liked_aspects", "").strip()

    if article_url:
        con = None
        try:
            con = get_db()
            cur = con.cursor()
            cur.execute("""
                UPDATE article_feedback
                SET comment = %s, feedback_category = %s, liked_aspects = %s
                WHERE article_url = %s
                  AND (subscriber_email = %s OR (subscriber_email IS NULL AND %s = ''))
            """, (
                comment[:1000] if comment else None,
                feedback_category if feedback_category else None,
                liked_aspects[:500] if liked_aspects else None,
                article_url,
                subscriber_email,
                subscriber_email
            ))
            con.commit()
            cur.close()
        except Exception as e:
            print(f"[feedback_comment] DB error: {e}")
        finally:
            if con:
                con.close()

    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Thanks!</title><style>
  body { font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:320px;
         margin:80px auto; padding:0 24px; text-align:center; color:#37352f; background:#FAFAF9; }
  .emoji { font-size:2rem; margin-bottom:10px; }
  p { font-size:0.86rem; color:#6b6b6b; margin-bottom:16px; line-height:1.6; }
  a { font-size:0.78rem; color:#b0aeab; text-decoration:none; }
  a:hover { color:#37352f; }
</style></head><body>
  <div class="emoji">&#127881;</div>
  <p>Thanks! Your feedback helps make AI in News better.</p>
  <a href="https://aiinnews.space">Back to the newsletter &rarr;</a>
</body></html>"""


@app.route("/feedback/product", methods=["GET", "POST"])
def feedback_product():
    if request.method == "POST":
        feedback_type = request.form.get("feedback_type", "general").strip()
        comment = request.form.get("comment", "").strip()
        subscriber_email = request.form.get("subscriber_email", "").strip()

        if feedback_type not in ("bug", "feature", "general", "question"):
            feedback_type = "general"

        con = None
        try:
            con = get_db()
            cur = con.cursor()
            cur.execute("""
                INSERT INTO product_feedback (feedback_type, comment, subscriber_email)
                VALUES (%s, %s, %s)
            """, (feedback_type, comment[:2000] if comment else None, subscriber_email or None))
            con.commit()
            cur.close()
        except Exception as e:
            print(f"[feedback_product] DB error: {e}")
        finally:
            if con:
                con.close()

        return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Thanks!</title><style>
  body { font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:400px;
         margin:60px auto; padding:0 24px; text-align:center; color:#37352f; background:#FAFAF9; }
  .emoji { font-size:2rem; margin-bottom:10px; }
  h2 { font-size:0.98rem; font-weight:600; margin-bottom:8px; }
  p { font-size:0.84rem; color:#6b6b6b; margin-bottom:16px; line-height:1.6; }
  a { font-size:0.78rem; color:#b0aeab; text-decoration:none; }
  a:hover { color:#37352f; }
</style></head><body>
  <div class="emoji">&#127881;</div>
  <h2>Thanks for the feedback!</h2>
  <p>We read every submission. This helps make AI in News better for you.</p>
  <a href="https://aiinnews.space">&larr; Back to the newsletter</a>
</body></html>"""

    # GET — show form
    feedback_type = request.args.get("type", "general")
    subscriber_email = request.args.get("email", "")
    safe_email = html_lib.escape(subscriber_email)

    type_labels = {
        "bug":      "&#128027; Bug report",
        "feature":  "&#10024; Feature request",
        "general":  "&#128172; General feedback",
        "question": "&#10067; Question",
    }
    if feedback_type not in type_labels:
        feedback_type = "general"

    options_html = ""
    for val, label in type_labels.items():
        selected = " selected" if val == feedback_type else ""
        options_html += f'<option value="{val}"{selected}>{label}</option>'

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Share feedback &#8212; AI in News</title>
  <style>
    *, *::before, *::after {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:440px;
            margin:48px auto; padding:0 24px; color:#37352f; background:#FAFAF9; }}
    .brand {{ font-size:0.7rem; font-weight:700; letter-spacing:0.12em; text-transform:uppercase;
              color:#9b9a97; margin-bottom:28px; }}
    h1 {{ font-size:1.05rem; font-weight:600; margin-bottom:5px; }}
    .sub {{ font-size:0.83rem; color:#6b6b6b; margin-bottom:22px; }}
    label {{ display:block; font-size:0.78rem; font-weight:500; color:#6b6b6b;
             margin-bottom:5px; text-transform:uppercase; letter-spacing:0.06em; }}
    select, textarea, input[type=email] {{ width:100%; padding:10px 13px; font-size:0.85rem; font-family:inherit;
                        border:1px solid #ddd; border-radius:8px; color:#37352f;
                        background:#fff; margin-bottom:16px; }}
    select:focus, textarea:focus, input[type=email]:focus {{ outline:none; border-color:#7b78e8; }}
    textarea {{ resize:vertical; min-height:100px; }}
    input[type=email]::placeholder {{ color:#b0aeab; }}
    .btn-send {{ background:#1d1d1f; color:#fff; border:none; padding:11px 0;
                 border-radius:8px; font-size:0.88rem; font-weight:600;
                 cursor:pointer; font-family:inherit; width:100%; margin-bottom:10px; }}
    .btn-send:hover {{ background:#3a3a3c; }}
    .cancel {{ display:block; font-size:0.76rem; color:#b0aeab; text-decoration:none; text-align:center; }}
    .cancel:hover {{ color:#37352f; }}
  </style>
</head><body>
  <p class="brand">AI in News</p>
  <h1>Share feedback</h1>
  <p class="sub">Got something to report, suggest, or ask? We read everything.</p>
  <form method="POST" action="/feedback/product">
    <label>Type</label>
    <select name="feedback_type">{options_html}</select>
    <label>Tell us more <span style="color:#b0aeab;font-size:0.75em;text-transform:none;">(optional)</span></label>
    <textarea name="comment" placeholder="Describe the bug, feature idea, or question&#8230;"></textarea>
    <label>Your email <span style="color:#b0aeab;font-size:0.75em;text-transform:none;">(optional — we'll let you know when we act on it)</span></label>
    <input type="email" name="subscriber_email" value="{safe_email}" placeholder="you@example.com">
    <button class="btn-send" type="submit">Send feedback</button>
  </form>
  <a class="cancel" href="https://aiinnews.space">&larr; Cancel</a>
</body></html>"""


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
            con = None
            try:
                con = get_db()
                cur = con.cursor()
                cur.execute("""
                    INSERT INTO email_events (event_type, email_id, subscriber_email, clicked_url, newsletter_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (event_type, email_id, subscriber_email, clicked_url, newsletter_date))
                con.commit()
                cur.close()
            except Exception as e:
                print(f"[resend-webhook] DB insert error: {e}")
            finally:
                if con:
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
    # Validate date format to prevent path traversal and XSS
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return "Not found.", 404
    newsletter = load_newsletter(date)
    if not newsletter:
        return f"No newsletter found for {html_lib.escape(date)}.", 404
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
- article_feedback(id, newsletter_date, article_url, rating, subscriber_email, comment, feedback_category, liked_aspects, created_at)
- email_events(id, event_type, email_id, subscriber_email, clicked_url, newsletter_date, created_at)
- events(id, title, url, source, location, start_time, description, created_at)
- pm_reports(id, report_date, report_md, recommendations_json JSONB, status, created_at)
- pm_plans(id, report_id, plan_date, plan_md, status, rec_index, shipped_note, created_at)
- product_feedback(id, feedback_type, comment, subscriber_email, plan_id, acknowledged_at, created_at)
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
      <strong>After shipping, mark it done</strong> so the AI PM measures impact next Saturday
      and notifies any users whose feedback inspired this change:
    </p>
    <div style="background:#fff; border:1px solid #c8e6c9; border-radius:6px; padding:10px 16px;">
      <a href="https://aiinnews.space/pm?secret={html_lib.escape(os.environ.get('PM_SECRET', ''))}"
         style="font-size:0.88rem; color:#156038; font-weight:600; text-decoration:none;">
        → Open PM Dashboard and click "Mark as Shipped"
      </a>
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


def send_acknowledgment_email(to_email, feedback_type, comment, shipped_note, rec=None):
    """Thank a feedback giver whose suggestion has been shipped.

    If rec (the recommendation dict) is provided, uses Claude Sonnet to draft a
    personalised email body that names their exact feedback, what was built, and why.
    Falls back to a static template if the API call fails.
    """
    type_labels = {
        "bug": "bug report", "feature": "feature request",
        "general": "feedback", "question": "question",
    }
    type_label = type_labels.get(feedback_type, "feedback")

    # --- Try Claude-generated body ---
    body_html = None
    if rec:
        try:
            comment_str = f'"{comment[:300]}"' if comment else "(no written comment — submitted as a {type_label})"
            shipped_str = shipped_note or "(no specific note from the team)"
            prompt = f"""You are writing a short, warm thank-you email for a newsletter called "AI in News" — a daily AI briefing for builders and founders.

A user submitted product feedback. We built a solution inspired by it and have just shipped it.

USER'S FEEDBACK:
- Type: {type_label}
- Their comment: {comment_str}

WHAT WE BUILT:
- Feature/fix: {rec.get('title', '')}
- Why we built it: {rec.get('why', '')}
- What was implemented: {rec.get('what_to_build', '')}
- What changed (team note): {shipped_str}

Write 3–4 short paragraphs for the email body:
1. Open by directly referencing their specific feedback — use their actual words if they wrote a comment, otherwise reference the feedback type. Make it clear we actually read what they wrote.
2. Explain concisely what was built and why we built it — connect their feedback to our decision so it feels earned, not generic corporate boilerplate.
3. A genuine, short thank-you — they helped make AI in News better for builders like them.
4. One warm closing line inviting them to share more if they have ideas.

Rules:
- No subject line, no greeting ("Hi", "Dear [name]"), no sign-off ("Best," etc.)
- No filler openers like "I hope this email finds you well"
- Tone: warm and direct, like a message from a small team that genuinely cares — not a corporation
- Under 160 words total
- Plain text only — no HTML tags, no markdown"""

            message = get_claude().messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = message.content[0].text.strip()
            paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            body_html = "".join(
                f'<p style="font-size:0.88rem; line-height:1.75; margin:0 0 14px; color:#37352f;">'
                f'{html_lib.escape(p)}</p>'
                for p in paragraphs
            )
            print(f"[ack_email] Claude draft generated ({len(raw_text)} chars)")
        except Exception as e:
            print(f"[ack_email] Claude generation failed, using static fallback: {e}")
            body_html = None

    # --- Static fallback ---
    if not body_html:
        quoted = (
            f'<blockquote style="border-left:3px solid #e0e0e0; padding:4px 12px; margin:12px 0; '
            f'color:#6b6b6b; font-style:italic; font-size:0.88rem;">'
            f'{html_lib.escape(comment[:300])}</blockquote>'
            if comment else
            f'<p style="color:#6b6b6b; font-style:italic; font-size:0.86rem;">({type_label})</p>'
        )
        what_changed = (
            f'<p style="font-size:0.88rem; line-height:1.7; margin-top:6px;">'
            f'Here\'s what changed: {html_lib.escape(shipped_note)}</p>'
            if shipped_note else
            '<p style="font-size:0.88rem; line-height:1.7; margin-top:6px;">'
            'This improvement is now live in AI in News.</p>'
        )
        body_html = f"""  <p style="font-size:0.88rem; color:#6b6b6b; line-height:1.65; margin-bottom:4px;">
    You submitted a {type_label} for AI in News:
  </p>
  {quoted}
  <p style="font-size:0.88rem; line-height:1.7; margin-top:16px;">
    Our AI PM flagged it, a plan was made, and we shipped it.
  </p>
  {what_changed}
  <p style="font-size:0.88rem; line-height:1.7; margin-top:18px; color:#37352f;">
    Thank you — suggestions like yours are how AI in News gets better for builders.
  </p>"""

    try:
        resend_lib.api_key = os.environ["RESEND_API_KEY"]
        resend_lib.Emails.send({
            "from": "AI in News <newsletter@aiinnews.space>",
            "to": [to_email],
            "subject": "Your feedback shaped AI in News \u2728",
            "html": f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:540px;
             margin:0 auto; padding:32px 16px; background:#FAFAF9; color:#37352f;">
  <p style="font-size:0.7rem; font-weight:700; text-transform:uppercase;
             letter-spacing:0.12em; color:#9b9a97; margin-bottom:20px;">AI in News</p>
  <p style="font-size:1rem; font-weight:600; color:#1d1d1f; margin-bottom:16px;">
    Your feedback shaped something real.
  </p>
  {body_html}
  <div style="margin-top:24px; padding-top:16px; border-top:1px solid #ebebea;
              font-size:0.75rem; color:#b0aeab;">
    <a href="https://aiinnews.space/feedback/product"
       style="color:#b0aeab; text-decoration:none;">Share more feedback &rarr;</a>
    &nbsp;&nbsp;&middot;&nbsp;&nbsp;
    <a href="https://aiinnews.space"
       style="color:#b0aeab; text-decoration:none;">Back to the newsletter &rarr;</a>
  </div>
</body></html>""",
        })
        print(f"[ack_email] Sent to {to_email}")
    except Exception as e:
        print(f"[ack_email] Failed to {to_email}: {e}")


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
        cur.execute("""
            SELECT p.id, p.plan_date, p.status, p.shipped_note,
                   r.recommendations_json, p.rec_index
            FROM pm_plans p
            JOIN pm_reports r ON r.id = p.report_id
            ORDER BY p.created_at DESC LIMIT 10
        """)
        plan_rows = cur.fetchall()
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
    plans = []
    for r in plan_rows:
        pid, plan_date, status, shipped_note, recs_json, rec_idx = r
        title = f"Plan #{pid}"
        if recs_json and rec_idx is not None and rec_idx < len(recs_json):
            title = recs_json[rec_idx].get("title", title)
        plans.append({
            "id": pid,
            "plan_date": plan_date,
            "status": status,
            "shipped_note": shipped_note or "",
            "title": title,
        })
    return render_template("pm.html", report=report, plans=plans, secret=secret)


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
            INSERT INTO pm_plans (report_id, plan_date, plan_md, status, rec_index)
            VALUES (%s, %s, %s, 'pending', %s) RETURNING id
        """, (report_id, plan_date, plan_md, rec_index))
        plan_id = cur.fetchone()[0]
        cur.execute("UPDATE pm_reports SET status = 'approved' WHERE id = %s", (report_id,))
        # Link any product_feedback rows this recommendation attributed to the plan
        feedback_ids = []
        for x in selected_rec.get("feedback_ids", []):
            try:
                feedback_ids.append(int(x))
            except (TypeError, ValueError):
                pass
        if feedback_ids:
            cur.execute("""
                UPDATE product_feedback SET plan_id = %s
                WHERE id = ANY(%s) AND plan_id IS NULL
            """, (plan_id, feedback_ids))
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


@app.route("/pm/ship", methods=["POST"])
def pm_ship():
    """Mark a plan as shipped and send acknowledgment emails to feedback givers."""
    secret = request.form.get("secret", "")
    pm_secret = os.environ.get("PM_SECRET", "")
    if not pm_secret or secret != pm_secret:
        return "Forbidden", 403

    try:
        plan_id = int(request.form.get("plan_id", ""))
    except ValueError:
        return "Invalid plan_id.", 400

    shipped_note = request.form.get("shipped_note", "").strip()

    # 1. Mark plan as shipped
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            UPDATE pm_plans SET status = 'shipped', shipped_note = %s WHERE id = %s
        """, (shipped_note or None, plan_id))
        con.commit()
        cur.close()
        con.close()
    except Exception as e:
        return f"DB error: {e}", 500

    # 2. Fetch the recommendation data for personalised email drafting
    rec = None
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            SELECT r.recommendations_json, p.rec_index
            FROM pm_plans p
            JOIN pm_reports r ON r.id = p.report_id
            WHERE p.id = %s
        """, (plan_id,))
        plan_row = cur.fetchone()
        cur.close()
        con.close()
        if plan_row and plan_row[0] and plan_row[1] is not None:
            recs, idx = plan_row[0], plan_row[1]
            if idx < len(recs):
                rec = recs[idx]
    except Exception as e:
        print(f"[ship] DB error fetching rec: {e}")

    # 3. Find linked feedback rows that have emails and haven't been acknowledged yet
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            SELECT id, feedback_type, comment, subscriber_email
            FROM product_feedback
            WHERE plan_id = %s AND subscriber_email IS NOT NULL AND acknowledged_at IS NULL
        """, (plan_id,))
        rows = cur.fetchall()
        cur.close()
        con.close()
    except Exception as e:
        print(f"[ship] DB error fetching feedback: {e}")
        rows = []

    # 4. Send emails and mark acknowledged
    sent = 0
    for fb_id, feedback_type, comment, email in rows:
        send_acknowledgment_email(email, feedback_type, comment, shipped_note, rec=rec)
        try:
            con = get_db()
            cur = con.cursor()
            cur.execute("UPDATE product_feedback SET acknowledged_at = NOW() WHERE id = %s", (fb_id,))
            con.commit()
            cur.close()
            con.close()
        except Exception as e:
            print(f"[ship] DB error marking acknowledged for id={fb_id}: {e}")
        sent += 1

    back_link = f"/pm?secret={html_lib.escape(secret)}"
    msg = html_lib.escape(
        "✅ Plan marked as shipped." +
        (f" Acknowledgment email sent to {sent} feedback giver(s)." if sent
         else " No emails to send (no linked feedback with email addresses).")
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
  body {{ font-family:-apple-system,sans-serif; max-width:480px; margin:60px auto;
          padding:0 24px; color:#37352f; background:#FAFAF9; }}
  .success {{ background:#f0fdf4; border-left:3px solid #34C759; border-radius:0 8px 8px 0;
              padding:14px 18px; margin-bottom:20px; font-size:0.88rem; line-height:1.7; }}
  a {{ color:#1d1d1f; font-size:0.85rem; }}
</style></head><body>
  <div class="success">{msg}</div>
  <a href="{back_link}">&larr; Back to PM Dashboard</a>
</body></html>"""


if __name__ == "__main__":
    app.run(debug=True)
