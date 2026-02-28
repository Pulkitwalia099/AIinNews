import os
import json
import re
import time
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


def fetch_luma_events():
    """Fetch AI/Startup/VC events from Luma Boston discover page."""

    BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # --- Step 1: Fetch lu.ma/boston and extract event URLs ---
    print("Fetching Luma Boston events...")
    try:
        req = urllib.request.Request("https://lu.ma/boston", headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Luma page fetch failed: {e}")
        return []

    # Extract event URLs from the HTML
    # Luma event links look like: /event/evt-XXXXX or /e/XXXXX or just /slug-name
    event_urls = set()

    # Look for embedded JSON data (Next.js __NEXT_DATA__ or inline scripts)
    next_data_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if next_data_match:
        try:
            next_data = json.loads(next_data_match.group(1))
            # Walk the JSON looking for event URLs or api_ids
            data_str = json.dumps(next_data)
            # Find lu.ma event URLs in the data
            for match in re.findall(r'"url"\s*:\s*"(https://lu\.ma/[^"]+)"', data_str):
                if "/boston" not in match and "/signin" not in match:
                    event_urls.add(match)
            # Find event slugs/paths
            for match in re.findall(r'"event_url"\s*:\s*"([^"]+)"', data_str):
                if match.startswith("http"):
                    event_urls.add(match)
                else:
                    event_urls.add(f"https://lu.ma/{match}")
        except json.JSONDecodeError:
            pass

    # Also scan for links in the raw HTML
    for match in re.findall(r'href="(https://lu\.ma/[^"]+)"', html):
        if "/boston" not in match and "/signin" not in match and "/settings" not in match:
            event_urls.add(match)
    for match in re.findall(r'href="(/[a-zA-Z0-9][\w-]*[^"]*)"', html):
        if not match.startswith(("/signin", "/settings", "/home", "/explore", "/_next")):
            event_urls.add(f"https://lu.ma{match}")

    print(f"  Found {len(event_urls)} potential event URLs on Luma Boston.")

    if not event_urls:
        print("  No event URLs found. Luma page may require JS rendering.")
        return []

    # --- Step 2: Fetch each event page for JSON-LD structured data ---
    events_raw = []
    for url in list(event_urls)[:40]:
        try:
            req = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                event_html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue

        # Look for JSON-LD (most reliable — Luma includes this for SEO)
        for ld_match in re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            event_html, re.DOTALL
        ):
            try:
                ld = json.loads(ld_match)
                if isinstance(ld, list):
                    ld = ld[0]
                if ld.get("@type") == "Event" or "startDate" in ld:
                    events_raw.append({
                        "title": ld.get("name", ""),
                        "url": url,
                        "location": _extract_ld_location(ld),
                        "start_time": ld.get("startDate", ""),
                        "description": (ld.get("description") or "")[:400],
                    })
                    break
            except json.JSONDecodeError:
                continue

        # Fallback: extract from meta tags
        if not any(e["url"] == url for e in events_raw):
            title = _extract_meta(event_html, "og:title") or _extract_meta(event_html, "twitter:title")
            desc = _extract_meta(event_html, "og:description") or _extract_meta(event_html, "twitter:description")
            if title:
                events_raw.append({
                    "title": title,
                    "url": url,
                    "location": "Boston, MA",
                    "start_time": None,
                    "description": (desc or "")[:400],
                })

        time.sleep(0.5)  # Be respectful with rate limiting

    print(f"  Extracted details for {len(events_raw)} events from Luma.")

    if not events_raw:
        return []

    # --- Step 3: Use Claude to filter for AI/Startup/VC events ---
    return _filter_events_with_claude(events_raw)


def _extract_ld_location(ld):
    """Extract location string from JSON-LD data."""
    loc = ld.get("location", {})
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        name = loc.get("name", "")
        addr = loc.get("address", {})
        if isinstance(addr, str):
            return f"{name}, {addr}" if name else addr
        if isinstance(addr, dict):
            city = addr.get("addressLocality", "")
            state = addr.get("addressRegion", "")
            parts = [name, city, state]
            return ", ".join(p for p in parts if p) or "Boston, MA"
    return "Boston, MA"


def _extract_meta(html, prop):
    """Extract content from a meta tag."""
    match = re.search(
        rf'<meta[^>]*(?:property|name)="{re.escape(prop)}"[^>]*content="([^"]*)"',
        html
    )
    if not match:
        match = re.search(
            rf'<meta[^>]*content="([^"]*)"[^>]*(?:property|name)="{re.escape(prop)}"',
            html
        )
    return match.group(1) if match else None


def _filter_events_with_claude(events_raw):
    """Use Claude to filter events for AI, Startup, and VC relevance."""
    try:
        import anthropic
    except ImportError:
        print("  anthropic package not installed, skipping Claude filtering.")
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  No ANTHROPIC_API_KEY set, returning all Luma events unfiltered.")
        return [
            {**e, "source": "Luma"}
            for e in events_raw
        ]

    client = anthropic.Anthropic()
    events_json = json.dumps([
        {"title": e["title"], "description": e["description"], "url": e["url"]}
        for e in events_raw
    ], indent=2)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    "You are filtering events for a Boston AI/tech newsletter for founders.\n\n"
                    "From the events below, return ONLY the ones related to:\n"
                    "- Artificial Intelligence, Machine Learning, LLMs, GenAI\n"
                    "- Startups, entrepreneurship, venture building\n"
                    "- Venture Capital, fundraising, investor events\n"
                    "- Tech industry networking relevant to founders\n\n"
                    "Exclude: pure social gatherings, food/drink, fitness, arts, "
                    "music, sports, or events with no clear tech/startup angle.\n\n"
                    "Return a JSON array of the URLs that pass the filter. "
                    "Return ONLY valid JSON, no other text.\n"
                    'Example: ["https://lu.ma/abc", "https://lu.ma/xyz"]\n\n'
                    f"Events:\n{events_json}"
                ),
            }],
        )
    except Exception as e:
        print(f"  Claude filtering failed: {e}")
        return [{**e, "source": "Luma"} for e in events_raw]

    # Parse Claude's response to get filtered URLs
    try:
        text = response.content[0].text.strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        filtered_urls = set(json.loads(text))
    except (json.JSONDecodeError, IndexError):
        print("  Could not parse Claude's filter response, returning all events.")
        return [{**e, "source": "Luma"} for e in events_raw]

    filtered = [
        {**e, "source": "Luma"}
        for e in events_raw
        if e["url"] in filtered_urls
    ]

    print(f"  Claude filtered to {len(filtered)} AI/Startup/VC events from {len(events_raw)} total.")
    return filtered


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
    all_events += fetch_luma_events()

    save_events(all_events)
    print(f"\nTotal: {len(all_events)} events fetched.")
