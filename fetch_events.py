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
    all_events += fetch_tnt_events()
    all_events += fetch_eventbrite()
    all_events += fetch_mit_events()

    save_events(all_events)
    print(f"\nTotal: {len(all_events)} events fetched.")
