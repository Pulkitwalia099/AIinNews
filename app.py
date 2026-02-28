import json
import os
import psycopg2
from flask import Flask, render_template, request, redirect

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


@app.route("/<date>")
def issue(date):
    newsletter = load_newsletter(date)
    if not newsletter:
        return f"No newsletter found for {date}.", 404
    return render_template("index.html", newsletter=newsletter, status=None, upcoming_events=[])


if __name__ == "__main__":
    app.run(debug=True)
