"""
weekly_review.py — AI PM weekly review script.

Runs every Saturday 9 AM UTC via GitHub Actions.
Queries Supabase for the past 7 days of metrics, calls Claude Sonnet as
AI PM, saves the report, and emails Pulkit with direct approve links.
"""

import json
import os
import hmac
import hashlib
import re
from datetime import date, timedelta
import psycopg2
import anthropic
import resend
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()
resend.api_key = os.environ["RESEND_API_KEY"]

PM_EMAIL = "pulkitwalia099@gmail.com"
PM_SECRET = os.environ.get("PM_SECRET", "")
BASE_URL = "https://aiinnews.space"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def make_approval_token(report_id, rec_index):
    """Same HMAC logic as app.py — must stay in sync."""
    secret = PM_SECRET or "fallback"
    msg = f"{report_id}:{rec_index}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_feedback_stats(days=7):
    """Thumbs-up/down counts, top/bottom articles, comments."""
    con = get_db()
    cur = con.cursor()
    since = (date.today() - timedelta(days=days)).isoformat()

    cur.execute("""
        SELECT rating, COUNT(*) FROM article_feedback
        WHERE created_at >= %s GROUP BY rating
    """, (since,))
    counts = {r[0]: r[1] for r in cur.fetchall()}
    up = counts.get("up", 0)
    down = counts.get("down", 0)
    total = up + down
    approval_pct = round(100 * up / total) if total else 0

    cur.execute("""
        SELECT article_url, COUNT(*) as ups, MAX(comment) as sample_comment
        FROM article_feedback
        WHERE rating = 'up' AND created_at >= %s
        GROUP BY article_url ORDER BY ups DESC LIMIT 5
    """, (since,))
    top_articles = [{"url": r[0], "ups": r[1], "comment": r[2]} for r in cur.fetchall()]

    cur.execute("""
        SELECT article_url, COUNT(*) as downs, MAX(comment) as sample_comment
        FROM article_feedback
        WHERE rating = 'down' AND created_at >= %s
        GROUP BY article_url ORDER BY downs DESC LIMIT 5
    """, (since,))
    bottom_articles = [{"url": r[0], "downs": r[1], "comment": r[2]} for r in cur.fetchall()]

    cur.execute("""
        SELECT feedback_category, COUNT(*) FROM article_feedback
        WHERE feedback_category IS NOT NULL AND created_at >= %s
        GROUP BY feedback_category ORDER BY COUNT(*) DESC
    """, (since,))
    category_counts = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("""
        SELECT comment FROM article_feedback
        WHERE comment IS NOT NULL AND comment != '' AND created_at >= %s
        ORDER BY created_at DESC LIMIT 15
    """, (since,))
    comments = [r[0] for r in cur.fetchall()]

    cur.close()
    con.close()
    return {
        "total_ratings": total, "up": up, "down": down,
        "approval_pct": approval_pct,
        "top_articles": top_articles,
        "bottom_articles": bottom_articles,
        "category_counts": category_counts,
        "comments": comments,
    }


def fetch_product_feedback_items(days=30):
    """Return recent unacknowledged product_feedback rows with IDs for PM attribution."""
    try:
        con = get_db()
        cur = con.cursor()
        since = (date.today() - timedelta(days=days)).isoformat()
        cur.execute("""
            SELECT id, feedback_type, comment, subscriber_email IS NOT NULL AS has_email,
                   EXTRACT(DAY FROM NOW() - created_at)::int AS days_ago
            FROM product_feedback
            WHERE created_at >= %s AND acknowledged_at IS NULL
            ORDER BY created_at DESC LIMIT 20
        """, (since,))
        rows = cur.fetchall()
        cur.close()
        con.close()
        return [
            {"id": r[0], "feedback_type": r[1], "comment": r[2] or "",
             "has_email": r[3], "days_ago": r[4]}
            for r in rows
        ]
    except Exception as e:
        print(f"  [product_feedback] Error: {e}")
        return []


def fetch_email_stats(days=7):
    """Open/click counts and most-clicked URLs."""
    con = get_db()
    cur = con.cursor()
    since = (date.today() - timedelta(days=days)).isoformat()

    cur.execute("""
        SELECT event_type, COUNT(*) FROM email_events
        WHERE created_at >= %s GROUP BY event_type
    """, (since,))
    rows = {r[0]: r[1] for r in cur.fetchall()}
    opens = rows.get("email.opened", 0)
    clicks = rows.get("email.clicked", 0)

    cur.execute("""
        SELECT clicked_url, COUNT(*) as cnt FROM email_events
        WHERE event_type = 'email.clicked'
          AND clicked_url IS NOT NULL
          AND created_at >= %s
        GROUP BY clicked_url ORDER BY cnt DESC LIMIT 5
    """, (since,))
    most_clicked = [{"url": r[0], "clicks": r[1]} for r in cur.fetchall()]

    cur.close()
    con.close()
    return {"opens": opens, "clicks": clicks, "most_clicked_urls": most_clicked}


def fetch_subscriber_stats(days=7):
    """Total subscribers and new this week."""
    con = get_db()
    cur = con.cursor()
    since = (date.today() - timedelta(days=days)).isoformat()

    cur.execute("SELECT COUNT(*) FROM subscribers")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM subscribers WHERE created_at >= %s", (since,))
    new_count = cur.fetchone()[0]

    cur.close()
    con.close()
    return {"total": total, "new_this_week": new_count}


def fetch_prev_week_stats():
    """Same metrics for days 8-14 ago — for week-over-week comparison."""
    con = get_db()
    cur = con.cursor()
    prev_start = (date.today() - timedelta(days=14)).isoformat()
    prev_end = (date.today() - timedelta(days=7)).isoformat()

    cur.execute("""
        SELECT rating, COUNT(*) FROM article_feedback
        WHERE created_at >= %s AND created_at < %s GROUP BY rating
    """, (prev_start, prev_end))
    counts = {r[0]: r[1] for r in cur.fetchall()}
    prev_up = counts.get("up", 0)
    prev_down = counts.get("down", 0)
    prev_total = prev_up + prev_down
    prev_approval = round(100 * prev_up / prev_total) if prev_total else 0

    cur.execute("""
        SELECT event_type, COUNT(*) FROM email_events
        WHERE created_at >= %s AND created_at < %s GROUP BY event_type
    """, (prev_start, prev_end))
    email_rows = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("""
        SELECT COUNT(*) FROM subscribers
        WHERE created_at >= %s AND created_at < %s
    """, (prev_start, prev_end))
    prev_new_subs = cur.fetchone()[0]

    cur.close()
    con.close()
    return {
        "approval_pct": prev_approval,
        "total_ratings": prev_total,
        "opens": email_rows.get("email.opened", 0),
        "clicks": email_rows.get("email.clicked", 0),
        "new_subscribers": prev_new_subs,
    }


def fetch_shipped_plans(days=7):
    """Plans marked shipped in the last N days."""
    try:
        con = get_db()
        cur = con.cursor()
        since = (date.today() - timedelta(days=days)).isoformat()
        cur.execute("""
            SELECT plan_date, plan_md FROM pm_plans
            WHERE status = 'shipped' AND created_at >= %s
            ORDER BY created_at DESC
        """, (since,))
        rows = cur.fetchall()
        cur.close()
        con.close()
        return [{"plan_date": r[0], "plan_md": r[1]} for r in rows]
    except Exception as e:
        print(f"  [shipped_plans] Error: {e}")
        return []


def fetch_carried_over():
    """PM reports that are still pending after 7+ days — carry over to this week."""
    try:
        con = get_db()
        cur = con.cursor()
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        cur.execute("""
            SELECT id, report_date, recommendations_json FROM pm_reports
            WHERE status = 'pending' AND report_date <= %s
            ORDER BY created_at ASC
        """, (cutoff,))
        rows = cur.fetchall()
        cur.close()
        con.close()
        carried = []
        for r in rows:
            if r[2]:
                for rec in r[2]:
                    carried.append({"from_report_id": r[0], "from_date": r[1], "rec": rec})
        return carried
    except Exception as e:
        print(f"  [carried_over] Error: {e}")
        return []


# ---------------------------------------------------------------------------
# AI PM prompt + call
# ---------------------------------------------------------------------------

def build_pm_prompt(stats_bundle):
    fb = stats_bundle["feedback"]
    em = stats_bundle["email"]
    su = stats_bundle["subscribers"]
    pw = stats_bundle["prev_week"]
    shipped = stats_bundle["shipped_plans"]
    report_date = stats_bundle["report_date"]
    product_fb_items = stats_bundle.get("product_feedback", [])

    # Trend helpers
    def trend(now, prev):
        if prev == 0:
            return "N/A (no previous data)"
        diff = now - prev
        pct = round(100 * diff / prev)
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        return f"{arrow} {abs(pct)}% vs last week"

    # Shipped plans context
    if shipped:
        shipped_ctx = "SHIPPED CHANGES THIS WEEK:\n"
        for p in shipped:
            shipped_ctx += f"- [{p['plan_date']}] {p['plan_md'][:400]}...\n"
    else:
        shipped_ctx = "SHIPPED CHANGES THIS WEEK: None."

    # Comments context
    comments_ctx = ""
    if fb["comments"]:
        comments_ctx = "\nREADER COMMENTS (freetext, last 7 days):\n"
        for c in fb["comments"][:10]:
            comments_ctx += f'- "{c}"\n'

    # Category breakdown
    cat_ctx = ""
    if fb["category_counts"]:
        cat_ctx = "\nFEEDBACK BY CATEGORY:\n"
        for cat, cnt in fb["category_counts"].items():
            cat_ctx += f"  {cat}: {cnt}\n"

    # Product feedback items (form submissions with IDs for attribution)
    product_fb_ctx = "\nPRODUCT FEEDBACK (form submissions, unaddressed — include relevant IDs in feedback_ids):\n"
    if product_fb_items:
        for item in product_fb_items:
            email_note = "has email" if item["has_email"] else "no email"
            comment_snippet = f'"{item["comment"][:120]}"' if item["comment"] else "(no comment)"
            product_fb_ctx += f'  [id={item["id"]}] {item["feedback_type"]} | {comment_snippet} | {email_note} | {item["days_ago"]}d ago\n'
    else:
        product_fb_ctx += "  (none in the last 30 days)\n"

    # Most clicked URLs
    clicked_ctx = ""
    if em["most_clicked_urls"]:
        clicked_ctx = "\nMOST CLICKED ARTICLE URLS:\n"
        for item in em["most_clicked_urls"]:
            clicked_ctx += f"  {item['clicks']} clicks — {item['url']}\n"

    return f"""You are the AI Product Manager for "AI in News", a daily AI newsletter for builders and technical executives.

Today's date: {report_date}

=== THIS WEEK'S METRICS (last 7 days) ===

ARTICLE FEEDBACK:
  Total ratings: {fb["total_ratings"]} (previous week: {pw["total_ratings"]})
  Thumbs up: {fb["up"]} | Thumbs down: {fb["down"]}
  Approval rate: {fb["approval_pct"]}% ({trend(fb["approval_pct"], pw["approval_pct"])})

TOP ARTICLES (most thumbs-up):
{json.dumps(fb["top_articles"], indent=2)}

BOTTOM ARTICLES (most thumbs-down):
{json.dumps(fb["bottom_articles"], indent=2)}
{cat_ctx}{comments_ctx}{product_fb_ctx}

EMAIL ENGAGEMENT:
  Opens: {em["opens"]} ({trend(em["opens"], pw["opens"])})
  Clicks: {em["clicks"]} ({trend(em["clicks"], pw["clicks"])})
{clicked_ctx}

SUBSCRIBERS:
  Total: {su["total"]} | New this week: {su["new_this_week"]} ({trend(su["new_this_week"], pw["new_subscribers"])})

{shipped_ctx}

=== YOUR TASK ===

Analyze this data as a senior product manager. Look for patterns across:
- Which RSS sources produce consistently low-rated articles (recommend adjusting config.json tier limits)
- Whether any section (Foundation/Infrastructure/Application Layer) is over/under-represented or rated
- Which signal_tags correlate with clicks and thumbs-up
- What patterns emerge from categorized freetext feedback
- Whether engagement is trending up or down and what to do about it
- Whether any shipped changes moved the metrics

Return ONLY valid JSON with this exact structure (no markdown fences, no text before or after):

{{
  "traction_summary": {{
    "subscribers_total": {su["total"]},
    "subscribers_new": {su["new_this_week"]},
    "subscribers_trend": "{trend(su["new_this_week"], pw["new_subscribers"])}",
    "approval_pct": {fb["approval_pct"]},
    "approval_trend": "{trend(fb["approval_pct"], pw["approval_pct"])}",
    "opens": {em["opens"]},
    "opens_trend": "{trend(em["opens"], pw["opens"])}",
    "clicks": {em["clicks"]},
    "clicks_trend": "{trend(em["clicks"], pw["clicks"])}"
  }},
  "impact_of_shipped": "Assessment of whether shipped changes affected metrics. 'No changes shipped this week.' if nothing was shipped.",
  "summary": "2-3 sentence executive summary. Be direct about whether things are improving or declining.",
  "top_performing": "1-2 sentences on what content performed best and why.",
  "under_performing": "1-2 sentences on what fell flat and the likely reason.",
  "source_insights": "Which sources/tiers produce consistently low-quality articles. Recommend specific config.json limit changes if warranted.",
  "section_insights": "Which newsletter sections are over/under-rated. Any recommendations on section balance.",
  "tag_insights": "Which signal_tags correlate with most clicks + thumbs-up. Any patterns.",
  "feedback_themes": "Summary of categorized freetext feedback. What are readers asking for or complaining about.",
  "recommendations": [
    {{
      "title": "Short title under 60 chars",
      "type": "bug_fix | improvement | new_build | cost_impact | editorial",
      "priority": "high | medium | low",
      "effort": "small | medium | large",
      "why": "1-2 sentences: what data signal drives this.",
      "what_to_build": "2-3 sentences: concrete enough for a developer to start.",
      "impact_estimate": "Expected measurable outcome.",
      "feedback_ids": [],
      "approval_token": ""
    }}
  ]
}}

Produce exactly 3 recommendations ordered by expected impact (highest first).
Focus on changes achievable in 1-3 days of work.
For feedback_ids: include the IDs of any PRODUCT FEEDBACK items (from the section above) that this recommendation directly addresses. Leave as empty array [] if none apply."""


def call_ai_pm(prompt):
    """Call Claude Sonnet as AI PM. Returns parsed JSON dict."""
    print("  Calling Claude Sonnet as AI PM...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()

    # Strip markdown fences if Claude adds them
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [ai_pm] JSON parse error: {e}")
        # Try to extract JSON object
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > 0:
            return json.loads(raw[start:end])
        raise


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def build_report_markdown(report_date, pm_result, stats_bundle):
    fb = stats_bundle["feedback"]
    em = stats_bundle["email"]
    su = stats_bundle["subscribers"]
    tr = pm_result.get("traction_summary", {})

    recs_md = ""
    for i, rec in enumerate(pm_result.get("recommendations", []), 1):
        recs_md += f"""
### Recommendation {i}: {rec.get("title", "")}
**Type:** {rec.get("type", "")} | **Priority:** {rec.get("priority", "")} | **Effort:** {rec.get("effort", "")}

**Why:** {rec.get("why", "")}

**What to build:** {rec.get("what_to_build", "")}

**Expected impact:** {rec.get("impact_estimate", "")}
"""

    return f"""# AI in News — Weekly PM Review
**Date:** {report_date}

## This Week at a Glance
| Metric | This Week | Trend |
|--------|-----------|-------|
| Total Subscribers | {su["total"]} | {tr.get("subscribers_trend", "—")} |
| New Subscribers | {su["new_this_week"]} | |
| Approval Rate | {fb["approval_pct"]}% | {tr.get("approval_trend", "—")} |
| Email Opens | {em["opens"]} | {tr.get("opens_trend", "—")} |
| Email Clicks | {em["clicks"]} | {tr.get("clicks_trend", "—")} |

## Executive Summary
{pm_result.get("summary", "")}

## Impact of Last Week's Changes
{pm_result.get("impact_of_shipped", "No changes shipped this week.")}

## What Worked
{pm_result.get("top_performing", "")}

## What Didn't Work
{pm_result.get("under_performing", "")}

## Source Insights
{pm_result.get("source_insights", "")}

## Section Insights
{pm_result.get("section_insights", "")}

## Signal Tag Insights
{pm_result.get("tag_insights", "")}

## Reader Feedback Themes
{pm_result.get("feedback_themes", "")}

## Recommendations
{recs_md}

---
*Generated by Claude Sonnet acting as AI PM · {report_date}*
"""


# ---------------------------------------------------------------------------
# DB save
# ---------------------------------------------------------------------------

def save_report_to_db(report_date, report_md, recommendations_json):
    """Save to pm_reports. Returns new row id."""
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO pm_reports (report_date, report_md, recommendations_json, status)
        VALUES (%s, %s, %s, 'pending') RETURNING id
    """, (report_date, report_md, json.dumps(recommendations_json)))
    report_id = cur.fetchone()[0]
    con.commit()
    cur.close()
    con.close()
    print(f"  [db] Saved pm_report id={report_id}")
    return report_id


def save_report_to_file(report_date, report_md):
    """Write reviews/YYYY-MM-DD-review.md to disk. GitHub Actions commits it."""
    os.makedirs("reviews", exist_ok=True)
    path = f"reviews/{report_date}-review.md"
    with open(path, "w") as f:
        f.write(report_md)
    print(f"  [file] Written to {path}")


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _rec_card_html(report_id, i, rec, is_carried_over=False):
    """Render one recommendation card for the email."""
    token = make_approval_token(report_id, i)
    approve_url = (
        f"{BASE_URL}/pm/approve-quick"
        f"?report_id={report_id}&rec_index={i}&token={token}"
    )
    pm_url = f"{BASE_URL}/pm?secret={PM_SECRET}"

    type_colors = {
        "bug_fix":      ("#fee2e2", "#b91c1c"),
        "improvement":  ("#e8f1ff", "#0050b3"),
        "new_build":    ("#eceafb", "#4240b8"),
        "cost_impact":  ("#fff4e5", "#c4680a"),
        "editorial":    ("#f4f4f2", "#6b6b6b"),
    }
    pri_colors = {
        "high":   ("#fee2e2", "#b91c1c"),
        "medium": ("#fff4e5", "#c4680a"),
        "low":    ("#f4f4f2", "#6b6b6b"),
    }
    eff_colors = {
        "small":  ("#e6f7ed", "#156038"),
        "medium": ("#fff4e5", "#c4680a"),
        "large":  ("#fee2e2", "#b91c1c"),
    }

    def badge(text, bg, color):
        return (
            f'<span style="display:inline-block; font-size:0.65rem; font-weight:700; '
            f'text-transform:uppercase; letter-spacing:0.06em; background:{bg}; color:{color}; '
            f'padding:2px 9px; border-radius:20px; margin-right:5px;">{text}</span>'
        )

    rec_type = rec.get("type", "improvement")
    priority = rec.get("priority", "medium")
    effort = rec.get("effort", "medium")

    tb, tc = type_colors.get(rec_type, ("#f4f4f2", "#6b6b6b"))
    pb, pc = pri_colors.get(priority, ("#f4f4f2", "#6b6b6b"))
    eb, ec = eff_colors.get(effort, ("#f4f4f2", "#6b6b6b"))

    border_color = "#c4680a" if is_carried_over else "#7b78e8"
    carried_label = (
        f'<p style="font-size:0.72rem; color:#c4680a; font-weight:600; margin-bottom:8px;">'
        f'↩ Carried over from {rec.get("from_date", "last week")}</p>'
        if is_carried_over else ""
    )

    return f"""
    <div style="background:#fff; border-radius:10px; padding:20px 22px; margin-bottom:14px;
                border-left:4px solid {border_color}; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      {carried_label}
      <div style="margin-bottom:10px;">
        {badge(rec_type.replace("_", " "), tb, tc)}
        {badge(priority + " priority", pb, pc)}
        {badge(effort + " effort", eb, ec)}
      </div>
      <h3 style="font-size:0.98rem; font-weight:600; margin-bottom:12px; color:#1d1d1f;">
        {i + 1}. {rec.get("title", "")}
      </h3>
      <p style="font-size:0.72rem; font-weight:700; text-transform:uppercase;
                 letter-spacing:0.08em; color:#9b9a97; margin-bottom:4px;">Why</p>
      <p style="font-size:0.86rem; line-height:1.65; margin-bottom:10px;">{rec.get("why", "")}</p>
      <p style="font-size:0.72rem; font-weight:700; text-transform:uppercase;
                 letter-spacing:0.08em; color:#9b9a97; margin-bottom:4px;">What to build</p>
      <p style="font-size:0.86rem; line-height:1.65; margin-bottom:10px;">{rec.get("what_to_build", "")}</p>
      <p style="font-size:0.8rem; color:#6b6b6b; font-style:italic; margin-bottom:16px;">
        Expected impact: {rec.get("impact_estimate", "")}
      </p>
      <div style="display:flex; gap:10px; flex-wrap:wrap;">
        <a href="{approve_url}"
           style="display:inline-block; background:#156038; color:#fff; text-decoration:none;
                  padding:9px 20px; border-radius:8px; font-size:0.86rem; font-weight:600;">
          Approve &amp; Generate Plan &rarr;
        </a>
        <a href="{pm_url}"
           style="display:inline-block; background:#f4f4f2; color:#37352f; text-decoration:none;
                  padding:9px 18px; border-radius:8px; font-size:0.86rem; font-weight:500;">
          Needs Refinement &rarr;
        </a>
      </div>
    </div>"""


def send_pm_email(report_id, report_date, pm_result, carried_over):
    """Send the weekly PM report email with traction dashboard + approve links."""
    tr = pm_result.get("traction_summary", {})
    recs = pm_result.get("recommendations", [])

    def metric_row(label, value, trend):
        arrow_color = "#156038" if "↑" in trend else ("#b91c1c" if "↓" in trend else "#9b9a97")
        return f"""
        <tr>
          <td style="padding:8px 0; font-size:0.86rem; color:#37352f; border-bottom:1px solid #f4f4f2;">
            {label}
          </td>
          <td style="padding:8px 0; font-size:0.88rem; font-weight:600; color:#1d1d1f;
                     text-align:right; border-bottom:1px solid #f4f4f2;">
            {value}
          </td>
          <td style="padding:8px 0; font-size:0.78rem; color:{arrow_color};
                     text-align:right; border-bottom:1px solid #f4f4f2; padding-left:12px;">
            {trend}
          </td>
        </tr>"""

    traction_rows = (
        metric_row("Subscribers (total)", tr.get("subscribers_total", "—"), tr.get("subscribers_trend", "—")) +
        metric_row("New subscribers", tr.get("subscribers_new", "—"), tr.get("subscribers_trend", "—")) +
        metric_row("Approval rate", f"{tr.get('approval_pct', '—')}%", tr.get("approval_trend", "—")) +
        metric_row("Email opens", tr.get("opens", "—"), tr.get("opens_trend", "—")) +
        metric_row("Email clicks", tr.get("clicks", "—"), tr.get("clicks_trend", "—"))
    )

    recs_html = "".join(_rec_card_html(report_id, i, rec) for i, rec in enumerate(recs))

    carried_html = ""
    if carried_over:
        carried_html = """
        <p style="font-size:0.78rem; font-weight:700; text-transform:uppercase;
                   letter-spacing:0.06em; color:#c4680a; margin:28px 0 12px;">
          ↩ Not yet approved from last week — still waiting on you:
        </p>"""
        for i, item in enumerate(carried_over):
            # reuse the rec card with carried-over styling
            rec = item["rec"]
            rec["from_date"] = item["from_date"]
            carried_html += _rec_card_html(item["from_report_id"], i, rec, is_carried_over=True)

    pm_archive_url = f"{BASE_URL}/pm?secret={PM_SECRET}"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:640px;
             margin:0 auto; padding:32px 16px; background:#FAFAF9; color:#37352f;">

  <!-- Header -->
  <div style="border-bottom:1px solid #ebebea; padding-bottom:14px; margin-bottom:24px;
              display:flex; justify-content:space-between; align-items:center;">
    <span style="font-size:0.8rem; font-weight:700; letter-spacing:0.12em;
                 text-transform:uppercase; color:#1d1d1f;">AI in News — PM Report</span>
    <span style="font-size:0.78rem; color:#9b9a97;">{report_date}</span>
  </div>

  <!-- Traction dashboard -->
  <div style="background:#fff; border-radius:10px; padding:20px 22px; margin-bottom:20px;
              box-shadow:0 1px 3px rgba(0,0,0,0.06);">
    <p style="font-size:0.7rem; font-weight:700; text-transform:uppercase;
               letter-spacing:0.08em; color:#9b9a97; margin-bottom:12px;">
      This week at a glance
    </p>
    <table style="width:100%; border-collapse:collapse;">
      {traction_rows}
    </table>
  </div>

  <!-- Impact of shipped -->
  <div style="background:#f0fdf4; border-left:3px solid #34C759; border-radius:0 8px 8px 0;
              padding:12px 16px; margin-bottom:20px; font-size:0.86rem; line-height:1.65;">
    <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase;
                  letter-spacing:0.08em; color:#1a7f4e; display:block; margin-bottom:4px;">
      Impact of last week's changes
    </span>
    {pm_result.get("impact_of_shipped", "No changes shipped this week.")}
  </div>

  <!-- Summary -->
  <div style="background:#fff; border-radius:10px; padding:20px 22px; margin-bottom:24px;
              box-shadow:0 1px 3px rgba(0,0,0,0.06);">
    <p style="font-size:0.7rem; font-weight:700; text-transform:uppercase;
               letter-spacing:0.08em; color:#9b9a97; margin-bottom:10px;">Summary</p>
    <p style="font-size:0.9rem; line-height:1.7;">{pm_result.get("summary", "")}</p>
  </div>

  <!-- How this works -->
  <div style="background:#f4f4f2; border-radius:10px; padding:16px 20px; margin-bottom:24px;
              font-size:0.82rem; line-height:1.75; color:#6b6b6b;">
    <p style="font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
               color:#9b9a97; margin-bottom:10px;">How this works — read this once</p>
    <p style="margin-bottom:8px;">
      Every Saturday you get this email. It shows how the newsletter performed
      and what the AI PM recommends building next.
    </p>
    <p style="margin-bottom:8px; color:#37352f;">
      <strong>What you need to do:</strong><br>
      → Review the 3 recommendations below<br>
      → Click <strong>"Approve &amp; Generate Plan"</strong> on the one you want to act on
         (approve one at a time)<br>
      → You'll get a second email with the full implementation plan<br>
      → Open Claude Code in your ai-newsletter folder and say:
         <em>"Execute the plan in plans/YYYY-MM-DD-name.md"</em>
    </p>
    <p style="margin-bottom:0;">
      If you want to add context before approving, click "Needs Refinement →" to open the
      dashboard and add notes first.<br>
      If you don't approve within 3 days, you'll get a reminder.<br>
      Unapproved items carry over to next week's report automatically.
    </p>
  </div>

  <!-- Recommendations -->
  <p style="font-size:0.7rem; font-weight:700; text-transform:uppercase;
             letter-spacing:0.08em; color:#9b9a97; margin-bottom:12px;">
    Recommendations — pick one to approve
  </p>
  {recs_html}

  <!-- Carried over -->
  {carried_html}

  <!-- Footer -->
  <div style="margin-top:36px; padding-top:16px; border-top:1px solid #ebebea;
              font-size:0.74rem; color:#b0aeab; text-align:center; line-height:1.8;">
    This is your private weekly AI PM report for AI in News.<br>
    It runs every Saturday and is fully automated.<br>
    <a href="{pm_archive_url}" style="color:#9b9a97;">Archive of all reports &rarr;</a>
  </div>

</body></html>"""

    resend.Emails.send({
        "from": "AI in News <newsletter@aiinnews.space>",
        "to": [PM_EMAIL],
        "subject": f"AI in News — Weekly PM Review ({report_date})",
        "html": html,
    })
    print(f"  [email] Sent PM report to {PM_EMAIL}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    report_date = date.today().isoformat()
    print(f"\n=== Weekly PM Review — {report_date} ===\n")

    # 1. Gather all stats
    print("Fetching stats from Supabase...")
    stats_bundle = {
        "report_date": report_date,
        "feedback": fetch_feedback_stats(days=7),
        "email": fetch_email_stats(days=7),
        "subscribers": fetch_subscriber_stats(days=7),
        "prev_week": fetch_prev_week_stats(),
        "shipped_plans": fetch_shipped_plans(days=7),
        "product_feedback": fetch_product_feedback_items(days=30),
    }
    fb = stats_bundle["feedback"]
    em = stats_bundle["email"]
    su = stats_bundle["subscribers"]
    print(f"  Feedback: {fb['total_ratings']} ratings ({fb['approval_pct']}% approval)")
    print(f"  Email: {em['opens']} opens, {em['clicks']} clicks")
    print(f"  Subscribers: {su['total']} total, {su['new_this_week']} new")

    # 2. Fetch carried-over items (unapproved from last week)
    carried_over = fetch_carried_over()
    if carried_over:
        print(f"  Carried over: {len(carried_over)} unapproved recommendation(s) from last week")

    # 3. Call Claude as AI PM
    prompt = build_pm_prompt(stats_bundle)
    pm_result = call_ai_pm(prompt)

    # 4. Add approval tokens to recommendations
    # (tokens are generated after saving to DB, once we have the report_id)

    # 5. Build markdown report
    report_md = build_report_markdown(report_date, pm_result, stats_bundle)

    # 6. Save to DB
    report_id = save_report_to_db(report_date, report_md, pm_result.get("recommendations", []))

    # 7. Add tokens to recs now that we have report_id
    for i, rec in enumerate(pm_result.get("recommendations", [])):
        rec["approval_token"] = make_approval_token(report_id, i)

    # 8. Save markdown file (GitHub Actions commits it)
    save_report_to_file(report_date, report_md)

    # 9. Send PM email
    send_pm_email(report_id, report_date, pm_result, carried_over)

    print("\n=== Done ===\n")


if __name__ == "__main__":
    run()
