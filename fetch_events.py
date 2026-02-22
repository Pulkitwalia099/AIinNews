import os
import json
import urllib.request
import urllib.parse
import psycopg2
from datetime import datetime, timezone


def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_events_table():
    con = get_db()
    cur = con.cursor()
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
    print("Events table ready.")


def fetch_eventbrite():
    api_key = os.environ.get("EVENTBRITE_API_KEY", "")
    if not api_key:
        print("No EVENTBRITE_API_KEY set, skipping Eventbrite.")
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = urllib.parse.urlencode({
        "token": api_key,
        "q": "AI machine learning startup artificial intelligence",
        "location.address": "Boston, MA",
        "location.within": "25mi",
        "start_date.range_start": today,
        "categories": "102",  # Technology category
        "expand": "venue",
        "page_size": 20,
        "sort_by": "date",
    })
    url = f"https://www.eventbriteapi.com/v3/events/search/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AIinNews/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Eventbrite fetch failed: {e}")
        return []

    events = []
    for e in data.get("events", []):
        venue = e.get("venue") or {}
        addr = venue.get("address") or {}
        location = addr.get("localized_address_display", "Boston, MA")

        desc = ""
        if e.get("description") and e["description"].get("text"):
            desc = e["description"]["text"][:400]

        events.append({
            "title": e["name"]["text"],
            "url": e["url"],
            "source": "Eventbrite",
            "location": location,
            "start_time": e["start"]["utc"],
            "description": desc,
        })

    print(f"Fetched {len(events)} events from Eventbrite.")
    return events


def fetch_mit_events():
    """Fetch AI-related events from MIT's public event calendar."""
    url = "https://events.mit.edu/api/2/events/?days=30&tag=artificial+intelligence&pp=20"
    req = urllib.request.Request(url, headers={"User-Agent": "AIinNews/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"MIT events fetch failed: {e}")
        return []

    events = []
    for e in data.get("events", []):
        event = e.get("event", e)  # Localist wraps events
        title = event.get("title", "")
        url_str = event.get("url", "")
        location = event.get("location_name", "MIT, Cambridge")
        start_time = event.get("event_instances", [{}])[0].get("event_instance", {}).get("start", "")
        desc = event.get("description_text", "")[:400]

        if title and url_str:
            events.append({
                "title": title,
                "url": url_str,
                "source": "MIT Events",
                "location": location,
                "start_time": start_time or None,
                "description": desc,
            })

    print(f"Fetched {len(events)} events from MIT.")
    return events


def save_events(events):
    if not events:
        print("No events to save.")
        return

    con = get_db()
    cur = con.cursor()
    saved = 0
    for e in events:
        try:
            cur.execute("""
                INSERT INTO events (title, url, source, location, start_time, description)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    title = EXCLUDED.title,
                    location = EXCLUDED.location,
                    start_time = EXCLUDED.start_time,
                    description = EXCLUDED.description
            """, (
                e["title"], e["url"], e["source"],
                e["location"], e["start_time"], e["description"]
            ))
            saved += 1
        except Exception as ex:
            print(f"Error saving '{e.get('title', '')}': {ex}")

    con.commit()
    cur.close()
    con.close()
    print(f"Saved/updated {saved} events in Supabase.")


if __name__ == "__main__":
    init_events_table()

    all_events = []
    all_events += fetch_eventbrite()
    all_events += fetch_mit_events()

    save_events(all_events)
    print(f"\nTotal: {len(all_events)} events fetched.")
