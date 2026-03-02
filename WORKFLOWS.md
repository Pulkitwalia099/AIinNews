# AI in News — Workflows

> **What is this?** A living reference for every automated and manual workflow in the AI in News newsletter system. Keep this updated when you add new features.

---

## Overview

The system has four main workflows:

| Workflow | Frequency | Trigger | Output |
|---|---|---|---|
| Daily Newsletter | Every day | GitHub Actions (cron) | Email sent to all subscribers |
| Weekly PM Review | Weekly (Tue) | GitHub Actions (cron) | PM dashboard populated |
| PM Approval → Plan | On demand | Pulkit clicks on PM dashboard | Implementation plan emailed |
| Ship & Thank | On demand | Pulkit marks plan as shipped | Acknowledgment emails to feedback givers |

---

## 1. Daily Newsletter Workflow

**What it does:** Every morning, the system automatically fetches AI news, selects the best stories, summarises them with Claude, and emails subscribers.

**GitHub Actions file:** `.github/workflows/daily-newsletter.yml`

**Runs:** Daily (cron schedule)

### Steps

```
GitHub Actions fires
    ↓
run_daily.py          — checks if today's newsletter already exists (prevents duplicate sends)
    ↓
fetch.py              — pulls articles from RSS feeds + Hacker News API
fetch_github.py       — pulls trending AI repos from GitHub
fetch_events.py       — pulls AI events
    ↓
process.py            — uses Claude Haiku to:
                         • classify articles into Foundation / Infrastructure / Application layers
                         • score each article for signal quality
                         • inject feedback context (last 14 days of reader votes)
                         • select the top stories
                         • write summaries + Builder's Lens for each
                         • add signal tags + maturity tag
    ↓
generate.py           — assembles final newsletter JSON
                         saves to newsletters/YYYY-MM-DD.json
    ↓
email_sender.py       — builds HTML email (one per subscriber)
                         sends via Resend API (rate-limited to 2/sec)
                         each email has personalised 👍/👎 links per article
```

### Key files

- `run_daily.py` — entry point (idempotency guard)
- `process.py` — all the Claude prompting logic
- `email_sender.py` — HTML builder + Resend sender
- `newsletters/` — archive of every newsletter as JSON

### Things to know

- Never run `generate.py` or `email_sender.py` directly in production — always go through `run_daily.py` to avoid sending duplicate emails.
- Always test with `send_newsletter(newsletter, test_recipient="pulkitwalia099@gmail.com")` — never with the subscriber list.
- Articles are grouped into three layers: **Foundation** (models/research), **Infrastructure** (tools/infra), **Application** (products/use cases).

---

## 2. Weekly PM Review Workflow

**What it does:** Every Tuesday, the system analyses the past week — article performance, reader feedback, product feedback — and uses Claude Sonnet to write a PM report with 3 prioritised recommendations for what to build next.

**GitHub Actions file:** `.github/workflows/weekly-review.yml`

**Runs:** Weekly (Tuesday)

### Steps

```
GitHub Actions fires
    ↓
weekly_review.py
    ↓
  1. Fetch last 7 days of article_feedback (thumbs up/down votes)
  2. Fetch last 7 days of email_events (opens, clicks)
  3. Fetch product_feedback (bug reports, feature requests) — unacknowledged, last 30 days
        ↓
  4. Build a PM prompt with all this data
        ↓
  5. Claude Sonnet writes:
       • Full markdown report (what worked, what didn't, key signals)
       • 3 recommendations (each with: title, why, what_to_build,
         impact_estimate, type, priority, effort, feedback_ids)
        ↓
  6. Save to pm_reports table in Supabase
        ↓
  7. Send PM reminder email to Pulkit with link to dashboard
```

**GitHub Actions file:** `.github/workflows/pm-reminder.yml`

The reminder email is sent separately by `pm_reminder.py` — it reads the latest pending report from the DB and emails Pulkit a link to the PM dashboard.

### Key files

- `weekly_review.py` — all the data fetching + Claude prompting
- `pm_reminder.py` — sends the "your PM report is ready" email
- `app.py` → `GET /pm/<report_id>?secret=...` — PM dashboard route

### Things to know

- The report is only viewable via the secret link (protected by `PM_SECRET` env var).
- `feedback_ids` in each recommendation links back to specific `product_feedback` rows — this is what powers the acknowledgment emails later.

---

## 3. PM Approval → Implementation Plan Workflow

**What it does:** Pulkit reads the weekly PM report, picks one recommendation, optionally adds refinement notes, and approves it. Claude Sonnet then generates a detailed implementation plan and emails it.

**Trigger:** Manual — Pulkit clicks "Approve & Generate Plan →" on the PM dashboard.

### Steps

```
Pulkit opens PM dashboard (emailed link)
    ↓
Reads report + 3 recommendations
    ↓
Optionally adds refinement notes ("focus only on web", "skip email part"...)
    ↓
Clicks "Approve & Generate Plan →"
    ↓
POST /pm/approve
    ↓
  1. Validate PM_SECRET
  2. Look up the chosen recommendation from pm_reports.recommendations_json
  3. Build architect prompt (recommendation + refinement notes)
  4. Claude Sonnet writes a step-by-step implementation plan (markdown)
  5. INSERT into pm_plans table (status = 'pending')
  6. Link product_feedback rows to this plan (feedback_ids → plan_id)
  7. Email Pulkit the full plan (markdown rendered in HTML)
    ↓
PM dashboard now shows the plan under "Implementation Plans"
```

### Key files

- `app.py` → `POST /pm/approve` route
- `app.py` → `_do_approve()` helper

### Things to know

- Only one recommendation can be approved per report.
- Once a report is approved, all the "Approve" buttons on the dashboard are replaced with a "✓ Plan generated" badge.
- The plan is stored in `pm_plans` and stays as `pending` until Pulkit ships it.

---

## 4. Ship & Acknowledge Workflow

**What it does:** Once Pulkit has actually built the thing, they mark the plan as "shipped" on the PM dashboard. The system then finds any readers who submitted feedback that inspired this plan (and provided their email), and sends them a personal thank-you email explaining what was built.

**Trigger:** Manual — Pulkit clicks "Mark as Shipped ✓" on the PM dashboard.

### Steps

```
Pulkit opens PM dashboard
    ↓
Finds the pending plan card
    ↓
(Optional) writes a note about what changed
    ↓
Clicks "Mark as Shipped ✓"
    ↓
POST /pm/ship
    ↓
  1. Validate PM_SECRET
  2. Mark pm_plans.status = 'shipped', save shipped_note
  3. Fetch the original recommendation (title, why, what_to_build)
  4. Find product_feedback rows where plan_id = this plan AND
     subscriber_email IS NOT NULL AND acknowledged_at IS NULL
  5. For each feedback giver:
       a. Use Claude Sonnet to draft a personalised email:
            - Quotes their original feedback
            - Explains what was built and why
            - Thanks them warmly
       b. Send via Resend
       c. Mark acknowledged_at = NOW() in product_feedback
  6. Redirect back to PM dashboard
```

### Key files

- `app.py` → `POST /pm/ship` route
- `app.py` → `send_acknowledgment_email()` helper
- `email_sender.py` → Resend client setup

### Things to know

- The acknowledgment email is written by Claude Sonnet each time — it references the person's actual feedback and the specific thing that shipped.
- If no feedback givers have emails, the plan still marks as shipped — no emails are sent.
- `acknowledged_at` ensures we never email the same person twice for the same feedback.
- Static fallback: if Claude API fails, a generic (but still correct) email is sent instead.

---

## 5. Reader Feedback Workflows

These run continuously (not on a schedule) — triggered by reader actions.

### 5a. Article Rating (👍 / 👎)

```
Reader clicks 👍 or 👎 link in email
    ↓
GET /feedback?date=&url=&rating=up|down&email=
    ↓
Upsert into article_feedback table
(unique per article_url + subscriber_email — re-vote just updates)
    ↓
Emoji thank-you page → redirect back after 3s
```

- Web article ratings (from the site, not email) are anonymous — `subscriber_email = NULL`.
- This data feeds into the daily newsletter's Claude prompts after 3+ ratings exist.

### 5b. Product Feedback Form

```
Reader clicks Bug / Feature / Feedback / Question pill on site
    ↓
GET /feedback/product?type=bug (pre-fills the type)
    ↓
Reader fills out form (comment + optional email)
    ↓
POST /feedback/product
    ↓
INSERT into product_feedback table
    ↓
Thank-you page shown
```

- Feedback with an email can receive acknowledgment later (Workflow 4).
- All unacknowledged recent feedback is surfaced to Claude in the weekly PM review (Workflow 2).

### 5c. Email Open / Click Events

```
Resend fires webhook on email.opened or email.clicked
    ↓
POST /resend-webhook
    ↓
Svix signature verified (RESEND_WEBHOOK_SECRET)
    ↓
INSERT into email_events table
```

- This data feeds into the weekly PM review.
- Webhook must be configured manually in the Resend dashboard (URL: `https://aiinnews.space/resend-webhook`).

---

## Database Tables (Supabase)

| Table | Purpose |
|---|---|
| `subscribers` | Email list — who gets the newsletter |
| `article_feedback` | Thumbs up/down per article per subscriber |
| `email_events` | Open + click events from Resend webhook |
| `product_feedback` | Bug reports, feature requests, general feedback from the site |
| `pm_reports` | Weekly PM reports (markdown + recommendations JSON) |
| `pm_plans` | Implementation plans generated from approved recommendations |

---

## Environment Variables

| Variable | Used in | What it is |
|---|---|---|
| `RESEND_API_KEY` | `email_sender.py`, `app.py` | Resend API key for sending emails |
| `ANTHROPIC_API_KEY` | `process.py`, `weekly_review.py`, `app.py` | Claude API key |
| `DATABASE_URL` | `app.py`, `email_sender.py`, `weekly_review.py` | Supabase PostgreSQL connection string |
| `PM_SECRET` | `app.py` | Secret to protect PM dashboard and approve/ship routes |
| `DEBUG_SECRET` | `app.py` | Secret to access `/debug-db` endpoint |
| `RESEND_WEBHOOK_SECRET` | `app.py` | Svix signing secret for Resend webhook verification |

All env vars live in `.env` locally (gitignored) and as Vercel env vars in production.

---

## Deployment

- **Hosting:** Vercel (serverless Flask via `Procfile` + `vercel.json`)
- **Database:** Supabase (PostgreSQL)
- **Email:** Resend
- **Automation:** GitHub Actions (4 workflows above)
- **Domain:** `aiinnews.space` (registered on Vercel, DNS configured)
- **Force deploy:** `vercel --prod --yes` from project root

---

## Common Operations

**Test a newsletter send (without hitting subscribers):**
```python
send_newsletter(newsletter, test_recipient="pulkitwalia099@gmail.com")
```

**Check DB tables:**
```
GET https://aiinnews.space/debug-db?secret=debugsecret
```

**View PM dashboard:**
Check your weekly reminder email for the secret link, or construct:
```
https://aiinnews.space/pm/<report_id>?secret=<PM_SECRET>
```
