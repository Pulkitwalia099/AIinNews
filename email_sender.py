import os
import json
import resend
from datetime import date

with open("config.json") as f:
    config = json.load(f)

resend.api_key = os.environ["RESEND_API_KEY"]

SECTIONS = ["Foundational", "Infra", "Application", "Research"]

def build_html(newsletter):
    date_str = newsletter["date"]
    articles = newsletter["articles"]

    # Group articles by section
    sections = {}
    for article in articles:
        s = article.get("section", "Other")
        sections.setdefault(s, []).append(article)

    # Build article HTML
    articles_html = ""
    for section in SECTIONS:
        if section not in sections:
            continue
        articles_html += f"""
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em;
                         text-transform: uppercase; color: #888;">{section}</span>
        </div>
        """
        for a in sections[section]:
            tags_html = "".join(
                f'<span style="display:inline-block; background:#f0f0f0; color:#444; '
                f'font-size:0.72rem; padding:2px 8px; border-radius:12px; margin-right:4px;">'
                f'{tag}</span>'
                for tag in a.get("signal_tags", [])
            )
            maturity = a.get("maturity_tag", "")
            if maturity:
                tags_html += (
                    f'<span style="display:inline-block; background:#e8f4e8; color:#2d6a2d; '
                    f'font-size:0.72rem; padding:2px 8px; border-radius:12px;">{maturity}</span>'
                )

            articles_html += f"""
            <div style="margin-bottom: 28px; padding-bottom: 28px; border-bottom: 1px solid #e8e8e8;">
                <h2 style="margin: 0 0 4px 0; font-size: 1rem; font-weight: 600;">
                    <a href="{a['url']}" style="color: #1a1a1a; text-decoration: none;">{a['title']}</a>
                </h2>
                <div style="font-size: 0.78rem; color: #888; margin-bottom: 8px;">{a.get('source', '')}</div>
                <div style="margin-bottom: 10px;">{tags_html}</div>
                <p style="margin: 0 0 10px 0; font-size: 0.9rem; color: #333; line-height: 1.6;">
                    {a.get('summary', '')}
                </p>
                <div style="background: #f9f9f9; border-left: 3px solid #1a1a1a;
                            padding: 10px 14px; font-size: 0.88rem; color: #333; line-height: 1.5;">
                    <strong>So what?</strong> {a.get('so_what', '')}
                </div>
            </div>
            """

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="font-family: Georgia, serif; max-width: 640px; margin: 0 auto;
                 padding: 32px 24px; background: #fff; color: #1a1a1a;">

        <div style="border-bottom: 2px solid #1a1a1a; padding-bottom: 16px; margin-bottom: 8px;">
            <h1 style="margin: 0; font-size: 1.4rem; letter-spacing: 0.05em;">AI IN NEWS</h1>
        </div>
        <div style="font-size: 0.8rem; color: #888; margin-bottom: 32px;">{date_str}</div>

        {articles_html}

        <div style="margin-top: 40px; padding-top: 16px; border-top: 1px solid #e0e0e0;
                    font-size: 0.75rem; color: #aaa; text-align: center;">
            AI in News · Unsubscribe
        </div>
    </body>
    </html>
    """


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
