import os
import sys
import json
import re
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


def fetch_ticketmaster():
    api_key = os.environ.get("TICKETMASTER_API_KEY", "")
    if not api_key:
        print("No TICKETMASTER_API_KEY set, skipping Ticketmaster.")
        return []

    params = urllib.parse.urlencode({
        "apikey": api_key,
        "city": "Boston",
        "stateCode": "MA",
        "keyword": "AI artificial intelligence machine learning startup",
        "sort": "date,asc",
        "size": 20,
    })
    url = f"https://app.ticketmaster.com/discovery/v2/events.json?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AIinNews/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Ticketmaster fetch failed: {e}")
        return []

    embedded = data.get("_embedded", {})
    raw_events = embedded.get("events", [])

    events = []
    for e in raw_events:
        venues = e.get("_embedded", {}).get("venues", [{}])
        venue = venues[0] if venues else {}
        city = venue.get("city", {}).get("name", "Boston")
        venue_name = venue.get("name", "")
        location = f"{venue_name}, {city}" if venue_name else city

        start = e.get("dates", {}).get("start", {})
        start_time = start.get("dateTime")  # ISO 8601 UTC

        events.append({
            "title": e["name"],
            "url": e.get("url", ""),
            "source": "Ticketmaster",
            "location": location,
            "start_time": start_time,
            "description": e.get("info", "")[:400],
        })

    print(f"Fetched {len(events)} events from Ticketmaster.")
    return events


def fetch_tnt_events():
    """Scrape upcoming startup events from TNT's MIT & Harvard calendar (tnt.so/calendar)."""
    TNT_URL = "https://tnt.so/calendar"
    req = urllib.request.Request(TNT_URL, headers={"User-Agent": "AIinNews/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"TNT calendar fetch failed: {e}")
        return []

    # Extract JSON-LD structured data from <script type="application/ld+json"> tags
    ld_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )

    now = datetime.now(timezone.utc).date()
    events = []

    for block in ld_blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue

        # JSON-LD can be a single object or a list; normalise to list
        items = data if isinstance(data, list) else [data]

        # Handle CollectionPage → mainEntity → itemListElement nesting
        for item in list(items):
            main_entity = item.get("mainEntity", {})
            if main_entity.get("@type") == "ItemList":
                items.extend(main_entity.get("itemListElement", []))
            if item.get("@type") in ("ItemList", "CollectionPage"):
                items.extend(item.get("itemListElement", []))

        for item in items:
            if item.get("@type") != "Event":
                continue

            name = item.get("name", "").strip()
            start_date_str = item.get("startDate", "")
            if not name or not start_date_str:
                continue

            # Parse date (could be YYYY-MM-DD or full ISO datetime)
            try:
                start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00")).date()
            except Exception:
                try:
                    start_date = datetime.strptime(start_date_str[:10], "%Y-%m-%d").date()
                except Exception:
                    continue

            # Skip past events
            if start_date < now:
                continue

            # Build location string from nested Place object
            loc = item.get("location", {})
            if isinstance(loc, dict):
                place_name = loc.get("name", "")
                address = loc.get("address", "")
                if isinstance(address, dict):
                    address = address.get("addressLocality", "")
                location = f"{place_name}, {address}" if place_name and address else place_name or address or "Boston, MA"
            else:
                location = str(loc) if loc else "Boston, MA"

            # Build a unique URL using the event name as a fragment
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            event_url = f"{TNT_URL}#{slug}"

            events.append({
                "title": name,
                "url": event_url,
                "source": "TNT",
                "location": location,
                "start_time": f"{start_date_str}T12:00:00Z" if "T" not in start_date_str else start_date_str,
                "description": "",
            })

    print(f"Fetched {len(events)} upcoming events from TNT calendar (scraped).")
    return events


def fetch_luma_boston():
    """Fetch upcoming Boston events from Luma's discover API, filtered for AI/VC/startup/tech."""
    LUMA_DISCOVER_URL = (
        "https://api.lu.ma/discover/get-paginated-events"
        "?discover_place_api_id=discplace-VWeZ1zUvnawYHMj"
        "&pagination_limit=50"
    )

    # Keywords that signal an AI / VC / startup / tech event
    KEYWORDS = re.compile(
        r"\b("
        r"ai|artificial.intelligence|machine.learning|deep.learning|llm|gpt|genai|generative.ai"
        r"|startup|startups|founder|founders|entrepreneurship|demo.day|pitch"
        r"|venture.capital|vc|angel.invest|seed.fund|series.[a-d]"
        r"|tech|technology|software|saas|devops|cloud|data.science|robotics|biotech"
        r"|hackathon|hack.night|build.night|dev|developer|engineering|cto|product"
        r")\b",
        re.IGNORECASE,
    )

    req = urllib.request.Request(LUMA_DISCOVER_URL, headers={"User-Agent": "AIinNews/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Luma Boston fetch failed: {e}")
        return []

    entries = data.get("entries", [])
    now = datetime.now(timezone.utc)
    events = []

    for entry in entries:
        ev = entry.get("event", {})
        name = ev.get("name", "")
        slug = ev.get("url", "")
        start_at = ev.get("start_at")

        # Build a text blob to match keywords against (name + calendar name + host names)
        calendar_name = (entry.get("calendar", {}) or {}).get("name", "")
        host_names = " ".join(
            (h.get("name") or "" for h in (entry.get("hosts") or [])),
        )
        search_text = f"{name} {calendar_name} {host_names}"

        if not KEYWORDS.search(search_text):
            continue

        # Skip past events
        start_time = None
        if start_at:
            try:
                start_time = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
                if start_time < now:
                    continue
            except Exception:
                pass

        # Location
        geo = ev.get("geo_address_info") or {}
        location = geo.get("full_address") or geo.get("city_state") or "Boston, MA"

        if name and slug:
            events.append({
                "title": name,
                "url": f"https://luma.com/{slug}",
                "source": "Luma",
                "location": location,
                "start_time": start_time.isoformat() if start_time else None,
                "description": "",
            })

    print(f"Fetched {len(events)} AI/VC/startup/tech events from Luma Boston (out of {len(entries)} total).")
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
    all_events += fetch_tnt_events()
    all_events += fetch_ticketmaster()
    all_events += fetch_luma_boston()

    save_events(all_events)
    print(f"\nTotal: {len(all_events)} events fetched.")

    if len(all_events) == 0:
        print("ERROR: No events fetched from any source. Exiting with failure.")
        sys.exit(1)
