import os
import json
import resend
from datetime import date

with open("config.json") as f:
    config = json.load(f)

resend.api_key = os.environ["RESEND_API_KEY"]

SECTIONS = [
    ("Foundation Layer",     "#4240b8", "#f0effe"),
    ("Infrastructure Layer", "#156038", "#edfaf1"),
    ("Application Layer",    "#0050b3", "#e8f1ff"),
]

def build_html(newsletter):
    date_str = newsletter["date"]
    articles = newsletter["articles"]

    sections_map = {}
    for article in articles:
        s = article.get("section", "Other")
        sections_map.setdefault(s, []).append(article)

    articles_html = ""
    for section_name, color, bg in SECTIONS:
        if section_name not in sections_map:
            continue

        articles_html += f"""
        <div style="margin: 36px 0 16px;">
            <span style="display:inline-block; font-size:0.7rem; font-weight:700;
                         letter-spacing:0.08em; text-transform:uppercase;
                         color:{color}; background:{bg};
                         padding:4px 12px; border-radius:20px;">{section_name}</span>
        </div>
        """

        for a in sections_map[section_name]:
            hn_score = a.get("hn_score", 0)
            hype_html = ""
            if hn_score and hn_score >= 10:
                hype_html = f'<span style="display:inline-block; font-size:0.7rem; font-weight:500; color:#c4680a; background:#fff4e5; padding:1px 7px; border-radius:10px; margin-left:6px;">🔥 {hn_score}</span>'

            tags_html = "".join(
                f'<span style="display:inline-block; background:#e8f1ff; color:#0060d1; '
                f'font-size:0.7rem; font-weight:500; padding:2px 9px; border-radius:20px; margin-right:4px;">'
                f'{tag}</span>'
                for tag in a.get("signal_tags", [])
            )
            maturity = a.get("maturity_tag", "")
            if maturity:
                tags_html += (
                    f'<span style="display:inline-block; background:#f4f4f2; color:#6b6b6b; '
                    f'font-size:0.7rem; font-weight:500; padding:2px 9px; border-radius:20px;">{maturity}</span>'
                )

            founders_lens = a.get("founders_lens")
            lens_html = ""
            if founders_lens:
                lens_html = f"""
                <div style="background:#f0fdf4; border-left:3px solid #34C759; border-radius:0 6px 6px 0;
                            padding:10px 14px; font-size:0.86rem; color:#1a4731; line-height:1.6; margin-top:10px;">
                    <span style="display:block; font-size:0.65rem; font-weight:700; letter-spacing:0.1em;
                                 text-transform:uppercase; color:#1a7f4e; margin-bottom:4px;">Founder's Lens</span>
                    {founders_lens}
                </div>"""

            articles_html += f"""
            <div style="background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,0.06);
                        padding:20px 22px; margin-bottom:12px;">
                <h2 style="margin:0 0 5px; font-size:1rem; font-weight:600; line-height:1.4;">
                    <a href="{a['url']}" style="color:#1d1d1f; text-decoration:none;">{a['title']}</a>
                </h2>
                <div style="font-size:0.76rem; color:#9b9a97; margin-bottom:10px;">
                    {a.get('source', '')}{hype_html}
                </div>
                <div style="margin-bottom:12px;">{tags_html}</div>
                <p style="margin:0 0 0; font-size:0.9rem; color:#37352f; line-height:1.65;">
                    {a.get('summary', '')}
                </p>
                {lens_html}
            </div>
            """

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Arial,sans-serif;
             max-width:640px; margin:0 auto; padding:32px 16px; background:#FAFAF9; color:#37352f;">

    <div style="background:#fff; border-radius:0; border-bottom:1px solid #ebebea;
                padding:16px 0; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between;">
        <span style="font-size:0.82rem; font-weight:700; letter-spacing:0.12em;
                     text-transform:uppercase; color:#1d1d1f;">AI in News</span>
        <span style="font-size:0.78rem; color:#9b9a97; letter-spacing:0.04em;
                     text-transform:uppercase;">{date_str}</span>
    </div>

    {articles_html}

    <div style="margin-top:40px; padding-top:16px; border-top:1px solid #ebebea;
                font-size:0.75rem; color:#b0aeab; text-align:center;">
        Curated daily for founders · Powered by Claude
    </div>
</body>
</html>"""


def send_newsletter(newsletter):
    html = build_html(newsletter)
    date_str = newsletter["date"]
    recipient = config["recipient_email"]

    params: resend.Emails.SendParams = {
        "from": "AI in News <onboarding@resend.dev>",
        "to": [recipient],
        "subject": f"AI in News — {date_str}",
        "html": html,
    }

    response = resend.Emails.send(params)
    print(f"Email sent to {recipient} (id: {response['id']})")


if __name__ == "__main__":
    today = date.today().isoformat()
    filename = f"newsletters/{today}.json"
    with open(filename) as f:
        newsletter = json.load(f)
    send_newsletter(newsletter)
