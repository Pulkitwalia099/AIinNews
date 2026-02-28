import os
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
    """Curated startup events from TNT's MIT & Harvard calendar (tnt.so/calendar)."""
    events = [
        {
            "title": "MIT $100K Entrepreneurship Competition: Accelerate",
            "url": "https://www.mit100k.org/accelerate/",
            "source": "TNT",
            "location": "MIT Wong Auditorium, Cambridge, MA",
            "start_time": "2026-03-03T23:30:00Z",
            "description": "Teams compete for $15,000+ in prizes including a $10,000 grand prize. Part of MIT's flagship $100K Entrepreneurship Competition series.",
        },
        {
            "title": "HBS New Venture Competition Finale",
            "url": "https://www.hbs.edu/newventurecompetition",
            "source": "TNT",
            "location": "Harvard Business School, Boston, MA",
            "start_time": "2026-03-05T23:00:00Z",
            "description": "Student finale of Harvard Business School's annual venture competition, sponsored by the Rock Center for Entrepreneurship and Social Enterprise Initiative.",
        },
        {
            "title": "HSIL Health AI Hackathon 2026",
            "url": "https://hsph.harvard.edu/research/health-systems-innovation-lab/work/hsil-hackathon-2026-building-high-value-health-systems-leveraging-ai/",
            "source": "TNT",
            "location": "Harvard T.H. Chan School of Public Health, Boston, MA",
            "start_time": "2026-04-10T13:00:00Z",
            "description": "7th edition global hackathon: build and pitch AI solutions for health systems. Winning teams advance to a Venture Incubation Program. Free to participate.",
        },
        {
            "title": "2026 MIT AI Conference",
            "url": "https://ilp.mit.edu/AI26",
            "source": "TNT",
            "location": "MIT Campus, Cambridge, MA",
            "start_time": "2026-04-14T13:00:00Z",
            "description": "Navigating the Digital Future: AI and Technology Strategy. Topics include future AI architectures, management, deployment, applications, and social impact.",
        },
        {
            "title": "2026 MIT Enterprise AI Forum",
            "url": "https://ilp.mit.edu/EnterpriseAI26",
            "source": "TNT",
            "location": "MIT Industry Meeting Center (E90), Cambridge, MA",
            "start_time": "2026-04-15T14:00:00Z",
            "description": "Enterprise-focused AI forum where 3 startups give 5-minute live presentations to MIT faculty and senior industry executives. 9 AM – 1 PM EST.",
        },
        {
            "title": "MIT Climate & Energy Prize Grand Finals",
            "url": "https://cep.mit.edu/grand-final",
            "source": "TNT",
            "location": "MIT, Boston, MA",
            "start_time": "2026-04-16T13:00:00Z",
            "description": "Grand Finals of the global student climate-tech startup competition. 8-10 teams compete for the $100,000 Grand Prize and other awards.",
        },
        {
            "title": "ODSC AI East 2026",
            "url": "https://odsc.ai/east/",
            "source": "TNT",
            "location": "Hynes Convention Center, Boston, MA",
            "start_time": "2026-04-28T13:00:00Z",
            "description": "Premier AI conference with 300+ hours of content, 280+ speakers. Workshops on GenAI, LLMs, ML, NLP, MLOps. Includes AI Startup Showcase track.",
        },
        {
            "title": "MIT $100K Launch Semifinals",
            "url": "https://www.mit100k.org/launch/",
            "source": "TNT",
            "location": "MIT Campus, Cambridge, MA",
            "start_time": "2026-04-29T22:00:00Z",
            "description": "Semifinal round of MIT's flagship $100K Entrepreneurship Competition. Teams present full business plans and prototypes to advance to the Finals.",
        },
        {
            "title": "ClimaTech 2026",
            "url": "https://climatech.live/",
            "source": "TNT",
            "location": "Boston Center for the Arts, Boston, MA",
            "start_time": "2026-05-04T13:00:00Z",
            "description": "Flagship conference of Boston Climate Week where business, innovation, and climate action intersect. Part of the citywide May 3-10 Climate Week.",
        },
        {
            "title": "Harvard President's Innovation Challenge Finals",
            "url": "https://innovationlabs.harvard.edu/presidents-innovation-challenge",
            "source": "TNT",
            "location": "Harvard University, Cambridge, MA",
            "start_time": "2026-05-06T20:00:00Z",
            "description": "150+ semifinalist ventures narrowed to five finalists per track, pitching for $25K and $75K prizes from the Bertarelli Foundation. Over $500K total.",
        },
        {
            "title": "MIT $100K Launch Finals",
            "url": "https://www.mit100k.org/launch/#finals",
            "source": "TNT",
            "location": "MIT Campus, Cambridge, MA",
            "start_time": "2026-05-12T22:00:00Z",
            "description": "Grand finale of MIT's $100K Entrepreneurship Competition. Eight finalist teams pitch for the $100,000 Grand Prize to a 2,000+ audience. Free admission.",
        },
        {
            "title": "Solve at MIT 2026",
            "url": "https://solve.mit.edu/events/solve-at-mit-2026",
            "source": "TNT",
            "location": "MIT Campus, Cambridge, MA",
            "start_time": "2026-05-14T13:00:00Z",
            "description": "MIT Solve's flagship annual event. 300+ leaders from tech, business, philanthropy, and government connect innovators with funding to scale real-world impact.",
        },
        {
            "title": "The Engine Blueprint Showcase",
            "url": "https://engine.xyz/blueprint-showcase-2",
            "source": "TNT",
            "location": "Cambridge, MA",
            "start_time": "2026-05-20T17:00:00Z",
            "description": "Culmination of The Engine's 8-week Blueprint accelerator for Tough Tech teams. Participants debut to the ecosystem of investors and partners.",
        },
        {
            "title": "TechCrunch Founder Summit 2026",
            "url": "https://techcrunch.com/events/techcrunch-founder-summit-2026/",
            "source": "TNT",
            "location": "Boston, MA",
            "start_time": "2026-06-09T13:00:00Z",
            "description": "1,000+ founders, investors, and decision-makers gather for interactive roundtables and breakout sessions on building and scaling companies.",
        },
    ]
    print(f"Loaded {len(events)} events from TNT calendar.")
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
