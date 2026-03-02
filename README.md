# AI in News

A daily AI/tech newsletter for builders — curated by Claude, published on a public website, and delivered by email.

Live at **aiinnews.space**

---

## What It Does

Every morning at 8am EST, the pipeline:

1. Pulls articles from 19+ RSS feeds (TechCrunch, MIT Tech Review, OpenAI, Anthropic, VentureBeat, etc.)
2. Scores them using HackerNews community engagement data
3. Deduplicates near-identical stories
4. Selects the top 8–10 using Claude Haiku (fast, cheap filtering)
5. Analyzes each article with Claude Sonnet (deep editorial voice, structured output)
6. Saves the newsletter as JSON
7. Sends a styled HTML email to subscribers via Resend
8. Publishes to the public website

---

## How the Pipeline Works

```
┌─────────────────────────────────────────────────────────────┐
│                     DAILY PIPELINE                          │
│                                                             │
│   RSS Feeds (19+)                                           │
│       │                                                     │
│       ▼                                                     │
│   fetch.py ── pull articles, 7-day freshness filter         │
│       │         (~100-200 candidates)                       │
│       ▼                                                     │
│   process.py                                                │
│       ├── Score via HackerNews API                          │
│       ├── Deduplicate (>70% title similarity → merge)       │
│       ├── Pass 1: Claude Haiku selects top 8-10             │
│       └── Pass 2: Claude Sonnet writes analysis             │
│       │                                                     │
│       ▼                                                     │
│   generate.py ── save JSON + trigger email                  │
│       │                                                     │
│       ▼                                                     │
│   email_sender.py ── build HTML email, send via Resend      │
│       │                                                     │
│       ▼                                                     │
│   newsletters/YYYY-MM-DD.json  (stored artifact)            │
└─────────────────────────────────────────────────────────────┘
```

---

## Feedback Loop

Reader signals feed back into tomorrow's curation — the pipeline learns what builders care about.

```
┌──────────────────────────────────────────────────────────────┐
│                      FEEDBACK LOOP                           │
│                                                              │
│   Reader receives email                                      │
│       │                                                      │
│       ├── Clicks article → tracked in email_events table     │
│       ├── Thumbs 👍/👎   → stored in article_feedback table  │
│       └── Product feedback (bug/feature/question)            │
│               → stored in product_feedback table             │
│       │                                                      │
│       ▼                                                      │
│   Next day's pipeline reads last 14 days of feedback         │
│       │                                                      │
│       ▼                                                      │
│   Claude Haiku selection prompt is enriched with:            │
│       • Which articles readers liked / disliked              │
│       • What topics got engagement                           │
│       │                                                      │
│       ▼                                                      │
│   Better curation tomorrow                                   │
└──────────────────────────────────────────────────────────────┘
```

---

## Automation

All workflows run via GitHub Actions:

| Workflow | Schedule | What it does |
|---|---|---|
| `daily-newsletter.yml` | 8am EST daily | Runs the full pipeline |
| `daily-events.yml` | Daily | Scrapes tech event listings |
| `pm-reminder.yml` | Daily | Sends PM workflow reminders |
| `weekly-review.yml` | Saturdays 9am UTC | Generates analytics review |

The daily runner (`run_daily.py`) is **idempotent** — if today's newsletter already exists, it skips generation.

---

## Tech Stack

| Layer | Tool |
|---|---|
| AI | Claude API (Haiku for selection, Sonnet for analysis) |
| Backend | Python, Flask |
| Database | PostgreSQL (Supabase) |
| Email | Resend API |
| Hosting | Vercel (serverless) |
| Automation | GitHub Actions |
| RSS Parsing | feedparser |

---

## Project Structure

```
ai-newsletter/
├── app.py              # Flask web server
├── config.json         # RSS feeds (19 sources, organized by tier)
├── requirements.txt    # Python dependencies
│
├── fetch.py            # Pull articles from RSS feeds
├── fetch_github.py     # Fetch GitHub trending repos
├── fetch_events.py     # Fetch tech event listings
├── process.py          # Two-pass Claude pipeline (score → dedup → select → analyze)
├── generate.py         # Orchestrate pipeline: fetch → process → save → email
├── email_sender.py     # Build HTML email, send via Resend
│
├── run_daily.py        # Idempotent daily runner
├── pm_reminder.py      # PM workflow reminders
├── weekly_review.py    # Weekly analytics review
│
├── newsletters/        # Saved newsletter JSON files
├── templates/          # Flask HTML templates
│   ├── base.html       # Layout
│   ├── index.html      # Homepage
│   ├── archive.html    # Past newsletters
│   ├── events.html     # Event listings
│   └── pm.html         # PM dashboard
│
├── .github/workflows/  # GitHub Actions automation
├── vercel.json         # Vercel deployment config
└── Procfile            # Deployment entrypoint
```

---

## Setup

### 1. Install dependencies

```bash
git clone <repo-url>
cd ai-newsletter
pip install -r requirements.txt
```

### 2. Set environment variables

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your-key-here
RESEND_API_KEY=your-key-here
DATABASE_URL=postgresql://...
PM_SECRET=your-secret-here
```

### 3. Run the pipeline

```bash
# Full pipeline (fetch → process → save → email)
python generate.py

# Or use the idempotent daily runner
python run_daily.py

# Individual steps
python fetch.py       # Just fetch articles
python process.py     # Just process (needs fetched articles)
```

### 4. Run the website locally

```bash
flask run
# or
python app.py
```

---

## Article Output Format

Each article in the newsletter JSON includes:

| Field | Description |
|---|---|
| `section` | Foundation Layer, Infrastructure Layer, or Application Layer |
| `signal_tags` | Opportunity, Enabler, Disruption, Platform Shift, Cost Driver, New Market |
| `maturity_tag` | Early Research, Emerging, or Production-Ready |
| `summary` | 2–3 crisp sentences (what happened + why it matters) |
| `builders_lens` | Specific actionable takeaway for founders and builders |
| `impact_level` | `act` (do something now), `watch` (monitor), or `context` (FYI) |
| `technical_detail` | 1 sentence of specs for technical readers (or null) |

---

## Common Tasks

**Add a new RSS feed** — edit `config.json`, add an entry with `name`, `url`, `tier`, and `limit`.

**Generate today's newsletter manually** — run `python run_daily.py`.

**Check reader feedback** — query the `article_feedback` table in Supabase.

**Test email formatting** — look at `email_sender.py`'s `build_html()` function.
