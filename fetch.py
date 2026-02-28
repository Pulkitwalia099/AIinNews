import json
import feedparser
from datetime import datetime, timedelta

# Load config file
with open("config.json") as f:
    config = json.load(f)

CUTOFF = datetime.utcnow() - timedelta(days=7)


def fetch_articles():
    all_articles = []
    log = {"fetched": 0, "skipped": 0, "failed": 0, "sources": []}
    tier_counts = {}

    for feed in config["feeds"]:
        try:
            parsed = feedparser.parse(feed["url"], agent="Mozilla/5.0 (compatible; AIinNews/1.0)")
            limit = feed.get("limit", 10)
            tier = feed.get("tier", "other")
            articles_from_feed = []

            for entry in parsed.entries[:limit]:
                # 7-day freshness filter
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6])
                    if pub_dt < CUTOFF:
                        log["skipped"] += 1
                        continue

                articles_from_feed.append({
                    "title": entry.get("title", "No title"),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", ""),
                    "source": feed["name"],
                    "tier": tier
                })

            all_articles.extend(articles_from_feed)
            log["fetched"] += len(articles_from_feed)
            tier_counts[tier] = tier_counts.get(tier, 0) + len(articles_from_feed)
            log["sources"].append(f"  {feed['name']} ({len(articles_from_feed)} articles)")

        except Exception as e:
            log["failed"] += 1
            log["sources"].append(f"  {feed['name']} (failed: {e})")

    # Print run log
    print("\n--- Fetch Summary ---")
    for line in log["sources"]:
        print(line)
    print(f"\nBy tier: {', '.join(f'{t}: {c}' for t, c in sorted(tier_counts.items()))}")
    print(f"Total: {log['fetched']} fetched, {log['skipped']} skipped (>7 days old), {log['failed']} sources failed")
    print("---------------------\n")

    return all_articles


if __name__ == "__main__":
    articles = fetch_articles()
    if articles:
        print(f"First article: {articles[0]['title']}")
    else:
        print("No articles fetched.")
