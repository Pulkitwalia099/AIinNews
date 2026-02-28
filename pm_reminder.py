"""
pm_reminder.py — Reminder script for unapproved PM plans.

Runs every Tuesday 9 AM UTC via GitHub Actions.
If any pm_reports are still pending after 3+ days, sends a reminder
email to Pulkit with the same direct approve links.
"""

import json
import os
import hmac
import hashlib
from datetime import date, timedelta
import psycopg2
import resend
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.environ["RESEND_API_KEY"]
PM_EMAIL = "pulkitwalia099@gmail.com"
PM_SECRET = os.environ.get("PM_SECRET", "")
BASE_URL = "https://aiinnews.space"


def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def make_approval_token(report_id, rec_index):
    """Same HMAC logic as app.py and weekly_review.py — must stay in sync."""
    secret = PM_SECRET or "fallback"
    msg = f"{report_id}:{rec_index}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def fetch_pending_reports():
    """Return pm_reports pending for 3+ days."""
    con = get_db()
    cur = con.cursor()
    cutoff = (date.today() - timedelta(days=3)).isoformat()
    cur.execute("""
        SELECT id, report_date, recommendations_json
        FROM pm_reports
        WHERE status = 'pending' AND report_date <= %s
        ORDER BY created_at ASC
    """, (cutoff,))
    rows = cur.fetchall()
    cur.close()
    con.close()
    return [
        {"id": r[0], "report_date": r[1], "recommendations": r[2] or []}
        for r in rows
    ]


def send_reminder_email(pending_reports):
    """Send a reminder email with approve links for all pending recommendations."""
    if not pending_reports:
        return

    # Calculate next Saturday
    today = date.today()
    days_until_saturday = (5 - today.weekday()) % 7 or 7
    next_saturday = (today + timedelta(days=days_until_saturday)).isoformat()

    # Build recommendation cards HTML
    cards_html = ""
    for report in pending_reports:
        report_id = report["id"]
        report_date = report["report_date"]
        for i, rec in enumerate(report["recommendations"]):
            token = make_approval_token(report_id, i)
            approve_url = (
                f"{BASE_URL}/pm/approve-quick"
                f"?report_id={report_id}&rec_index={i}&token={token}"
            )
            pm_url = f"{BASE_URL}/pm?secret={PM_SECRET}"

            type_colors = {
                "bug_fix":     ("#fee2e2", "#b91c1c"),
                "improvement": ("#e8f1ff", "#0050b3"),
                "new_build":   ("#eceafb", "#4240b8"),
                "cost_impact": ("#fff4e5", "#c4680a"),
                "editorial":   ("#f4f4f2", "#6b6b6b"),
            }
            rec_type = rec.get("type", "improvement")
            tb, tc = type_colors.get(rec_type, ("#f4f4f2", "#6b6b6b"))

            cards_html += f"""
    <div style="background:#fff; border-radius:10px; padding:20px 22px; margin-bottom:14px;
                border-left:4px solid #7b78e8; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <div style="margin-bottom:8px;">
        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase;
                     letter-spacing:0.06em; background:{tb}; color:{tc};
                     padding:2px 9px; border-radius:20px;">
          {rec_type.replace("_", " ")}
        </span>
        <span style="font-size:0.72rem; color:#9b9a97; margin-left:8px;">
          from {report_date}
        </span>
      </div>
      <h3 style="font-size:0.96rem; font-weight:600; margin-bottom:10px; color:#1d1d1f;">
        {i + 1}. {rec.get("title", "")}
      </h3>
      <p style="font-size:0.86rem; color:#6b6b6b; line-height:1.65; margin-bottom:14px;">
        {rec.get("why", "")}
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

    pm_archive_url = f"{BASE_URL}/pm?secret={PM_SECRET}"
    oldest_date = pending_reports[0]["report_date"]

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif; max-width:640px;
             margin:0 auto; padding:32px 16px; background:#FAFAF9; color:#37352f;">

  <!-- Header -->
  <div style="border-bottom:1px solid #ebebea; padding-bottom:14px; margin-bottom:24px;
              display:flex; justify-content:space-between; align-items:center;">
    <span style="font-size:0.8rem; font-weight:700; letter-spacing:0.12em;
                 text-transform:uppercase; color:#1d1d1f;">AI in News — Reminder</span>
    <span style="font-size:0.78rem; color:#9b9a97;">{date.today().isoformat()}</span>
  </div>

  <!-- Alert banner -->
  <div style="background:#fff4e5; border-left:4px solid #f59e0b; border-radius:0 8px 8px 0;
              padding:14px 18px; margin-bottom:24px;">
    <p style="font-size:0.88rem; font-weight:600; color:#92400e; margin-bottom:4px;">
      You have pending recommendations from {oldest_date}
    </p>
    <p style="font-size:0.84rem; color:#92400e;">
      You haven't approved any of them yet. It's been 3+ days.
    </p>
  </div>

  <!-- Instructions -->
  <div style="background:#f4f4f2; border-radius:10px; padding:16px 20px; margin-bottom:24px;
              font-size:0.84rem; line-height:1.75; color:#37352f;">
    <p style="font-weight:600; margin-bottom:8px;">What you need to do:</p>
    <p style="margin-bottom:6px;">→ Pick ONE recommendation below and click <strong>"Approve &amp; Generate Plan"</strong></p>
    <p style="margin-bottom:6px;">→ You'll get an email with the full implementation plan</p>
    <p style="margin-bottom:6px;">→ Open Claude Code in your ai-newsletter/ folder and execute the plan</p>
    <p style="margin-bottom:0; color:#6b6b6b;">
      That's it. It takes 10 seconds to approve.<br>
      If you don't approve by <strong>{next_saturday}</strong>, these will roll over to next Saturday's report.
    </p>
  </div>

  <!-- Recommendation cards -->
  <p style="font-size:0.7rem; font-weight:700; text-transform:uppercase;
             letter-spacing:0.08em; color:#9b9a97; margin-bottom:12px;">
    Pending recommendations
  </p>
  {cards_html}

  <!-- Footer -->
  <div style="margin-top:32px; padding-top:16px; border-top:1px solid #ebebea;
              font-size:0.74rem; color:#b0aeab; text-align:center; line-height:1.8;">
    This reminder runs every Tuesday.<br>
    <a href="{pm_archive_url}" style="color:#9b9a97;">View full dashboard &rarr;</a>
  </div>

</body></html>"""

    resend.Emails.send({
        "from": "AI in News <newsletter@aiinnews.space>",
        "to": [PM_EMAIL],
        "subject": f"Reminder: AI in News — {len(pending_reports)} report(s) waiting for your approval",
        "html": html,
    })
    print(f"  [email] Sent reminder to {PM_EMAIL}")


def run():
    print(f"\n=== PM Reminder Check — {date.today().isoformat()} ===\n")
    pending = fetch_pending_reports()

    if not pending:
        print("  No pending reports older than 3 days. Nothing to remind.")
        return

    print(f"  Found {len(pending)} pending report(s) — sending reminder...")
    send_reminder_email(pending)
    print("\n=== Done ===\n")


if __name__ == "__main__":
    run()
