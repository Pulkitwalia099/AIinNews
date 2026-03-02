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

## Feedback Loops

There are two separate feedback loops — one that improves curation daily, and one that autonomously improves the product weekly.

### Loop 1 — Daily Curation Feedback

Reader votes (👍/👎) feed back into tomorrow's article selection.

```
┌──────────────────────────────────────────────────────────────┐
│                   DAILY CURATION LOOP                        │
│                                                              │
│   Reader clicks 👍 / 👎 on an article                        │
│       │                                                      │
│       ▼                                                      │
│   Stored in article_feedback table                           │
│       │                                                      │
│       ▼                                                      │
│   Next day's pipeline reads last 14 days of votes            │
│       │                                                      │
│       ▼                                                      │
│   Claude Haiku selection prompt enriched with:               │
│       • Which topics/articles scored highest                 │
│       • What readers didn't find useful                      │
│       │                                                      │
│       ▼                                                      │
│   Better article selection tomorrow                          │
└──────────────────────────────────────────────────────────────┘
```

---

### Loop 2 — Weekly Self-Improvement Loop

Every week, reader product feedback (bug reports, feature requests, questions) flows through a fully autonomous loop — from raw feedback all the way to a shipped improvement and a 7-day impact check. A human approves at one point, everything else is AI-driven.

```
┌─────────────────────────────────────────────────────────────────────┐
│              WEEKLY SELF-IMPROVEMENT LOOP                           │
│                                                                     │
│  COLLECT                                                            │
│  ─────────────────────────────────────────────────────────────────  │
│  Readers submit product feedback on the site                        │
│  (Bug / Feature / Feedback / Question)                              │
│      │                                                              │
│      ▼                                                              │
│  Stored in product_feedback table                                   │
│      │                                                              │
│                                                                     │
│  ANALYSE  (every Tuesday)                                           │
│  ─────────────────────────────────────────────────────────────────  │
│      ▼                                                              │
│  AI PM (Claude Sonnet) reads:                                       │
│      • All recent product feedback                                  │
│      • Last 7 days of article votes + email engagement              │
│      Writes a structured report with 3 prioritised                  │
│      recommendations (what to build, why, estimated impact)         │
│      │                                                              │
│      ▼                                                              │
│  Report saved + reminder email sent to admin                        │
│      │                                                              │
│                                                                     │
│  APPROVE  (human in the loop)                                       │
│  ─────────────────────────────────────────────────────────────────  │
│      ▼                                                              │
│  Admin reads report on PM dashboard                                 │
│  Picks one recommendation, adds optional refinement notes           │
│  Clicks "Approve & Generate Plan"                                   │
│      │                                                              │
│                                                                     │
│  BUILD                                                              │
│  ─────────────────────────────────────────────────────────────────  │
│      ▼                                                              │
│  AI Engineer/Architect (Claude Sonnet) generates a                  │
│  step-by-step implementation plan and emails it to admin            │
│      │                                                              │
│      ▼                                                              │
│  Admin builds the feature / fix                                     │
│  Clicks "Mark as Shipped" on the PM dashboard                       │
│      │                                                              │
│                                                                     │
│  CLOSE THE LOOP                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│      ▼                                                              │
│  For every feedback giver who left an email:                        │
│  Claude Sonnet writes a personalised thank-you email                │
│      • Quotes their original feedback                               │
│      • Explains what was built because of it                        │
│      • Sent via Resend                                              │
│      │                                                              │
│                                                                     │
│  MEASURE  (7 days after shipping)                                   │
│  ─────────────────────────────────────────────────────────────────  │
│      ▼                                                              │
│  AI PM reads engagement data from the week after the ship           │
│  Writes an impact report:                                           │
│      • Did ratings improve?                                         │
│      • Did engagement change?                                       │
│      • Was the original hypothesis correct?                         │
│  Report emailed to admin                                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

The result: every piece of reader feedback has a traceable path from submission → analysis → decision → build → thank-you → measured outcome. No feedback disappears into a void.

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
