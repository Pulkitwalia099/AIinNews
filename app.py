import json
import os
import psycopg2
from datetime import date
import urllib.parse
from flask import Flask, render_template, request, redirect, jsonify

app = Flask(__name__)


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
        # Show only first 30 and last 20 chars for safety
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
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta http-equiv="refresh" content="3;url=https://aiinnews.space">
</head><body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px;color:#37352f;">
<p style="font-size:2rem;">{emoji}</p>
<p style="font-size:1rem;">Thanks for your feedback — it helps improve the newsletter.</p>
<p style="font-size:0.8rem;color:#9b9a97;">Redirecting you back...</p>
</body></html>"""


@app.route("/resend-webhook", methods=["POST"])
def resend_webhook():
    import hmac, hashlib, time as _time

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

        # Extract newsletter date from subject line e.g. "AI in News — 2026-02-28"
        subject = data.get("subject", "")
        newsletter_date = None
        if subject:
            import re
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


if __name__ == "__main__":
    app.run(debug=True)
