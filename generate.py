import json
import os
from datetime import date
from fetch import fetch_articles
from process import process_articles
from email_sender import send_newsletter

def generate_newsletter():
    print("=== AI in News — Newsletter Generator ===\n")

    # Step 1: Fetch
    articles = fetch_articles()
    if not articles:
        print("No articles fetched. Aborting.")
        return

    # Step 2: Process
    processed = process_articles(articles)
    if not processed:
        print("Processing failed. Aborting.")
        return

    # Step 3: Save
    os.makedirs("newsletters", exist_ok=True)
    today = date.today().isoformat()  # e.g. "2026-02-21"
    filename = f"newsletters/{today}.json"

    newsletter = {
        "date": today,
        "title": "AI in News",
        "articles": processed
    }

    with open(filename, "w") as f:
        json.dump(newsletter, f, indent=2)

    # Run log
    sections = {}
    for article in processed:
        s = article.get("section", "Unknown")
        sections[s] = sections.get(s, 0) + 1

    print(f"\n=== Newsletter saved to {filename} ===")
    print(f"Total articles: {len(processed)}")
    for section, count in sections.items():
        print(f"  {section}: {count}")

    # Step 4: Send email
    print("\nSending email...")
    send_newsletter(newsletter)


if __name__ == "__main__":
    generate_newsletter()
