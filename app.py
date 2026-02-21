import json
import os
import sqlite3
from flask import Flask, render_template, request, redirect

app = Flask(__name__)

DB = "subscribers.db"

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                is_technical TEXT,
                goals TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()

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

@app.route("/")
def index():
    dates = get_all_dates()
    if not dates:
        return "No newsletters yet. Run generate.py first."
    newsletter = load_newsletter(dates[0])
    status = request.args.get("status")
    return render_template("index.html", newsletter=newsletter, status=status)

@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = request.form.get("email", "").strip().lower()
    is_technical = request.form.get("is_technical", "")
    goals = json.dumps(request.form.getlist("goals"))

    if not email:
        return redirect("/?status=error")

    try:
        with sqlite3.connect(DB) as con:
            con.execute(
                "INSERT INTO subscribers (email, is_technical, goals) VALUES (?, ?, ?)",
                (email, is_technical, goals)
            )
        return redirect("/?status=subscribed")
    except sqlite3.IntegrityError:
        return redirect("/?status=exists")

@app.route("/archive")
def archive():
    dates = get_all_dates()
    return render_template("archive.html", dates=dates)

@app.route("/<date>")
def issue(date):
    newsletter = load_newsletter(date)
    if not newsletter:
        return f"No newsletter found for {date}.", 404
    return render_template("index.html", newsletter=newsletter, status=None)

if __name__ == "__main__":
    app.run(debug=True)
