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
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS tags TEXT")
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


def _extract_tnt_tags(block, title, location):
    """Extract tags from a TNT event card HTML block using badge spans and keyword matching."""
    TAG_NORMALIZE = {
        "boston ecosystem": "Boston",
        "fireside chat": "Talk", "fireside": "Talk", "panel": "Talk",
        "pitch competition": "Competition", "pitch": "Competition",
        "climate": "Climate / Energy", "energy": "Climate / Energy",
        "vc": "VC / Funding",
        "mit": "MIT", "harvard": "Harvard", "boston": "Boston",
        "competition": "Competition", "hackathon": "Hackathon",
        "conference": "Conference", "talk": "Talk", "workshop": "Workshop",
        "networking": "Networking", "demo day": "Demo Day",
        "showcase": "Demo Day", "summit": "Summit",
        "ai": "AI", "healthcare": "Healthcare",
        "climate / energy": "Climate / Energy", "startups": "Startups",
        "vc / funding": "VC / Funding",
    }

    tags = set()

    # Try to extract tag badge spans (TNT renders them as small spans with tag classes)
    badge_spans = re.findall(r'class="[^"]*bse-tag[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL | re.IGNORECASE)
    for span_text in badge_spans:
        clean = re.sub(r'<[^>]+>', '', span_text).strip().lower()
        if clean in TAG_NORMALIZE:
            tags.add(TAG_NORMALIZE[clean])

    # Also check plain text content of the card for known tag words
    card_text = re.sub(r'<[^>]+>', ' ', block).lower()
    full_text = f"{title} {location} {card_text}".lower()

    # Location tags from location field
    if "harvard" in location.lower() or "hbs" in location.lower():
        tags.add("Harvard")
    elif "mit" in location.lower():
        tags.add("MIT")
    else:
        tags.add("Boston")

    # Topic tags from title + card text
    if re.search(r"\b(ai|artificial.intelligence|machine.learning|deep.learning|llm|gpt|genai|generative.ai)\b", full_text):
        tags.add("AI")
    if re.search(r"\b(startup|founder|entrepreneurship|launch)\b", full_text):
        tags.add("Startups")
    if re.search(r"\b(venture.capital|vc\b|angel|seed.fund|series.[a-d]|funding|invest)\b", full_text):
        tags.add("VC / Funding")
    if re.search(r"\b(biotech|health|pharma|life.science|medical|genomic)\b", full_text):
        tags.add("Healthcare")
    if re.search(r"\b(climate|energy|sustainab|cleantech|green|solar|carbon)\b", full_text):
        tags.add("Climate / Energy")

    # Format tags from title + card text
    if re.search(r"\b(competition|pitch.comp|challenge|prize)\b", full_text):
        tags.add("Competition")
    if re.search(r"\b(hackathon|hack.night|build.night)\b", full_text):
        tags.add("Hackathon")
    if re.search(r"\b(conference|conf\b)\b", full_text):
        tags.add("Conference")
    if re.search(r"\b(fireside|panel|keynote|talk|speaker|lecture|seminar|discussion)\b", full_text):
        tags.add("Talk")
    if re.search(r"\b(workshop|hands.on|bootcamp|masterclass|tutorial|office.hours)\b", full_text):
        tags.add("Workshop")
    if re.search(r"\b(mixer|social|networking|meetup|happy.hour|drinks|reception|dinner)\b", full_text):
        tags.add("Networking")
    if re.search(r"\b(demo.day|showcase|expo)\b", full_text):
        tags.add("Demo Day")
    if re.search(r"\b(summit)\b", full_text):
        tags.add("Summit")

    return ",".join(sorted(tags)) if tags else ""


def fetch_tnt_events():
    """Scrape upcoming startup events from TNT's MIT & Harvard calendar (tnt.so/calendar).

    Parses <a class="bse-event-card"> HTML elements directly — this gives us real
    external event URLs and all 60+ events (vs. the JSON-LD which only has ~45 and no URLs).
    Also extracts tags from badge spans and keyword matching.
    """
    TNT_URL = "https://tnt.so/calendar"
    req = urllib.request.Request(TNT_URL, headers={"User-Agent": "AIinNews/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"TNT calendar fetch failed: {e}")
        return []

    # Each event is rendered as <a class="bse-event-card ..."> in the HTML
    card_blocks = re.findall(
        r'(<a\s[^>]*class="[^"]*bse-event-card[^"]*"[^>]*>.*?</a>)',
        html, re.DOTALL,
    )

    now = datetime.now(timezone.utc).date()
    events = []

    for block in card_blocks:
        # Real external event URL and date are attributes on the <a> tag
        href_m = re.search(r'\bhref="([^"]+)"', block)
        date_m = re.search(r'\bdata-date="([^"]+)"', block)
        if not href_m or not date_m:
            continue

        url = href_m.group(1)
        date_str = date_m.group(1)

        try:
            start_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if start_date < now:
            continue

        # Title from <h3>
        title_m = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
        if not title:
            continue

        # Description from <p>
        desc_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        description = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip() if desc_m else ""

        # Location: 2nd span inside bse-meta div (1st span = date range, 2nd = location)
        location = "Boston, MA"
        meta_m = re.search(r'class="bse-meta"[^>]*>(.*?)</div>', block, re.DOTALL)
        if meta_m:
            spans = re.findall(r'<span[^>]*>(.*?)</span>', meta_m.group(1), re.DOTALL)
            clean_spans = [re.sub(r'<[^>]+>', '', s).strip() for s in spans if s.strip()]
            clean_spans = [s for s in clean_spans if s]
            if len(clean_spans) >= 2:
                location = clean_spans[1]

        # Extract tags from badge spans + keyword matching
        tags = _extract_tnt_tags(block, title, location)

        events.append({
            "title": title,
            "url": url,
            "source": "TNT",
            "location": location,
            "start_time": f"{date_str}T12:00:00Z",
            "description": description,
            "tags": tags,
        })

    tagged = sum(1 for e in events if e.get("tags"))
    print(f"Fetched {len(events)} upcoming events from TNT calendar ({tagged} with tags).")
    return events


def fetch_luma_boston():
    """Fetch upcoming Boston events from Luma's discover API, filtered for AI/VC/startup/tech."""
    LUMA_DISCOVER_URL = (
        "https://api.lu.ma/discover/get-paginated-events"
        "?discover_place_api_id=discplace-VWeZ1zUvnawYHMj"
        "&pagination_limit=50"
    )

    # Keywords that signal an AI / VC / startup / tech / builder event
    KEYWORDS = re.compile(
        r"\b("
        r"ai|artificial.intelligence|machine.learning|deep.learning|llm|gpt|genai|generative.ai"
        r"|startup|startups|founder|founders|entrepreneurship|demo.day|pitch"
        r"|venture.capital|vc|angel.invest|seed.fund|series.[a-d]"
        r"|tech|technology|software|saas|devops|cloud|data.science|robotics|biotech"
        r"|hackathon|hack.night|build.night|dev|developer|engineering|cto|product"
        r"|hardware|embedded|xr|vr|ar|web3|blockchain|crypto|dao|decentralized"
        r"|innovation|research|science|conference|summit|expo|coding"
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

        # Build a text blob to match keywords against
        calendar_name = (entry.get("calendar", {}) or {}).get("name", "") or ""
        calendar_desc = (entry.get("calendar", {}) or {}).get("description_short", "") or ""
        host_names = " ".join(
            (h.get("name") or "" for h in (entry.get("hosts") or [])),
        )
        search_text = f"{name} {calendar_name} {calendar_desc} {host_names}"

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
            # --- Infer tags from Luma metadata ---
            luma_tags = set()

            # Topic tags from name + calendar + hosts
            luma_text = f"{name} {calendar_name} {host_names}".lower()
            if re.search(r"\b(ai|artificial.intelligence|machine.learning|deep.learning|llm|gpt|genai|generative.ai)\b", luma_text):
                luma_tags.add("AI")
            if re.search(r"\b(startup|founder|entrepreneurship|demo.day|pitch|launch)\b", luma_text):
                luma_tags.add("Startups")
            if re.search(r"\b(venture.capital|vc\b|angel|seed.fund|series.[a-d]|funding|invest)\b", luma_text):
                luma_tags.add("VC / Funding")
            if re.search(r"\b(biotech|health|bio|pharma|life.science|medical|genomic)\b", luma_text):
                luma_tags.add("Healthcare")
            if re.search(r"\b(climate|energy|sustainab|cleantech|green|solar|carbon)\b", luma_text):
                luma_tags.add("Climate / Energy")

            # Format tags
            if re.search(r"\b(competition|pitch.comp|challenge|prize)\b", luma_text):
                luma_tags.add("Competition")
            if re.search(r"\b(hackathon|hack.night|build.night)\b", luma_text):
                luma_tags.add("Hackathon")
            if re.search(r"\b(conference|conf\b)\b", luma_text):
                luma_tags.add("Conference")
            if re.search(r"\b(fireside|panel|keynote|talk|speaker|lecture|chat|seminar|discussion)\b", luma_text):
                luma_tags.add("Talk")
            if re.search(r"\b(workshop|hands.on|bootcamp|masterclass|tutorial|office.hours)\b", luma_text):
                luma_tags.add("Workshop")
            if re.search(r"\b(mixer|social|networking|meetup|happy.hour|drinks|reception|dinner)\b", luma_text):
                luma_tags.add("Networking")
            if re.search(r"\b(demo.day|showcase|expo)\b", luma_text):
                luma_tags.add("Demo Day")
            if re.search(r"\b(summit)\b", luma_text):
                luma_tags.add("Summit")

            # Location tags from address
            luma_loc = location.lower()
            if "harvard" in luma_loc or "hbs" in luma_loc:
                luma_tags.add("Harvard")
            elif "mit" in luma_loc:
                luma_tags.add("MIT")
            else:
                luma_tags.add("Boston")

            events.append({
                "title": name,
                "url": f"https://luma.com/{slug}",
                "source": "Luma",
                "location": location,
                "start_time": start_time.isoformat() if start_time else None,
                "description": "",
                "tags": ",".join(sorted(luma_tags)),
            })

    print(f"Fetched {len(events)} AI/VC/startup/tech events from Luma Boston (out of {len(entries)} total).")
    return events


def cleanup_stale_tnt_events():
    """Delete all existing TNT events so they can be replaced by freshly scraped ones."""
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM events WHERE source = 'TNT'")
    deleted = cur.rowcount
    con.commit()
    cur.close()
    con.close()
    if deleted:
        print(f"Cleared {deleted} old TNT event(s) from DB.")


def classify_event_regex(event):
    """Regex fallback classifier for events without scraped tags (e.g. Ticketmaster)."""
    text = f"{event.get('title', '')} {event.get('description', '')} {event.get('location', '')}".lower()
    tags = set()

    # Topic
    if re.search(r"\b(ai|artificial.intelligence|machine.learning|deep.learning|llm|gpt|genai|generative.ai)\b", text):
        tags.add("AI")
    if re.search(r"\b(startup|founder|entrepreneurship|demo.day|pitch|launch)\b", text):
        tags.add("Startups")
    if re.search(r"\b(venture.capital|vc\b|angel|seed.fund|series.[a-d]|funding|invest)\b", text):
        tags.add("VC / Funding")
    if re.search(r"\b(biotech|health|pharma|life.science|medical|genomic)\b", text):
        tags.add("Healthcare")
    if re.search(r"\b(climate|energy|sustainab|cleantech|green|solar|carbon)\b", text):
        tags.add("Climate / Energy")

    # Format
    if re.search(r"\b(competition|pitch.comp|challenge|prize)\b", text):
        tags.add("Competition")
    if re.search(r"\b(hackathon|hack)\b", text):
        tags.add("Hackathon")
    if re.search(r"\b(conference)\b", text):
        tags.add("Conference")
    if re.search(r"\b(fireside|panel|keynote|talk|speaker|lecture|chat|seminar)\b", text):
        tags.add("Talk")
    if re.search(r"\b(workshop|hands.on|bootcamp|masterclass|tutorial)\b", text):
        tags.add("Workshop")
    if re.search(r"\b(mixer|social|networking|meetup|happy.hour|drinks|reception)\b", text):
        tags.add("Networking")
    if re.search(r"\b(demo.day|showcase|expo)\b", text):
        tags.add("Demo Day")
    if re.search(r"\b(summit)\b", text):
        tags.add("Summit")

    # Location
    loc = event.get("location", "").lower()
    if "harvard" in loc or "hbs" in loc:
        tags.add("Harvard")
    elif "mit" in loc:
        tags.add("MIT")
    else:
        tags.add("Boston")

    return ",".join(sorted(tags)) if tags else ""


def classify_untagged_with_haiku(events):
    """Use Claude Haiku to tag events that have no tags or only a location tag.
    Sends all untagged events in a single API call for efficiency."""
    LOCATION_ONLY = {"MIT", "Harvard", "Boston"}

    untagged = []
    for i, ev in enumerate(events):
        existing = set(t.strip() for t in ev.get("tags", "").split(",") if t.strip())
        if not existing or existing.issubset(LOCATION_ONLY):
            untagged.append((i, ev))

    if not untagged:
        print("  [haiku-tagger] All events already have tags. Skipping.")
        return events

    print(f"  [haiku-tagger] {len(untagged)} event(s) need AI tagging...")

    # Build a compact prompt
    event_lines = ""
    for idx, (i, ev) in enumerate(untagged):
        existing = ev.get("tags", "")
        event_lines += f"[{idx}] {ev['title']} | {ev.get('location', '')} | existing: {existing}\n"

    valid_tags = (
        "AI, Startups, VC / Funding, Healthcare, Climate / Energy, "
        "Competition, Hackathon, Conference, Talk, Workshop, Networking, Demo Day, Summit, "
        "MIT, Harvard, Boston"
    )

    prompt = f"""Tag these events. For each event, return a JSON array of arrays.
Each inner array contains 1-4 tags from this list ONLY: {valid_tags}

Events:
{event_lines}

Return ONLY a JSON array like: [["AI","Talk","MIT"],["Startups","Competition","Harvard"],...]
No explanation. One inner array per event, same order."""

    try:
        import anthropic
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        tag_arrays = json.loads(raw)

        if len(tag_arrays) == len(untagged):
            for idx, (i, ev) in enumerate(untagged):
                existing = set(t.strip() for t in ev.get("tags", "").split(",") if t.strip())
                new_tags = set(tag_arrays[idx]) if idx < len(tag_arrays) else set()
                merged = existing | new_tags
                events[i]["tags"] = ",".join(sorted(merged))
            print(f"  [haiku-tagger] Tagged {len(untagged)} events via Haiku.")
        else:
            print(f"  [haiku-tagger] Response length mismatch ({len(tag_arrays)} vs {len(untagged)}). Skipping.")
    except Exception as e:
        print(f"  [haiku-tagger] Haiku tagging failed (non-critical): {e}")

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
                INSERT INTO events (title, url, source, location, start_time, description, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    title = EXCLUDED.title,
                    location = EXCLUDED.location,
                    start_time = EXCLUDED.start_time,
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags
            """, (
                e["title"], e["url"], e["source"],
                e["location"], e["start_time"], e["description"],
                e.get("tags", "")
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

    tnt_events = fetch_tnt_events()
    if tnt_events:
        cleanup_stale_tnt_events()  # only wipe old rows if scrape succeeded

    all_events = tnt_events[:]
    all_events += fetch_ticketmaster()
    all_events += fetch_luma_boston()

    # Apply regex fallback to any events still missing tags
    for event in all_events:
        if not event.get("tags"):
            event["tags"] = classify_event_regex(event)

    # Use Claude Haiku for any remaining untagged/undertagged events
    all_events = classify_untagged_with_haiku(all_events)

    save_events(all_events)
    print(f"\nTotal: {len(all_events)} events fetched.")

    # Log tag stats
    tagged = sum(1 for e in all_events if e.get("tags"))
    print(f"Tagged: {tagged}/{len(all_events)}")

    if len(all_events) == 0:
        print("ERROR: No events fetched from any source. Exiting with failure.")
        sys.exit(1)
