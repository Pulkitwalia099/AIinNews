import json
import urllib.request
import urllib.parse
import anthropic
from fetch import fetch_articles

client = anthropic.Anthropic()

STOPWORDS = {"the","a","an","is","in","of","for","to","and","on","with","how","why","new","ai","its","by"}

def keywords(title):
    return {w for w in title.lower().split() if w not in STOPWORDS and len(w) > 2}

def get_hn_score(title):
    """Query HackerNews Algolia API for community engagement score."""
    try:
        kw = " ".join(list(keywords(title))[:4])
        query = urllib.parse.quote(kw)
        url = f"https://hn.algolia.com/api/v1/search?query={query}&tags=story&hitsPerPage=1"
        req = urllib.request.Request(url, headers={"User-Agent": "AIinNews/1.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
        hits = data.get("hits", [])
        if hits:
            return hits[0].get("points", 0) + hits[0].get("num_comments", 0)
    except Exception:
        pass
    return 0

def score_articles(articles):
    """Add hn_score to each article."""
    print("Scoring articles via HackerNews...")
    for article in articles:
        article["hn_score"] = get_hn_score(article["title"])
    return articles

def process_articles(articles):
    # Add HN hype scores
    articles = score_articles(articles)

    # Format articles for Claude
    articles_text = ""
    for i, article in enumerate(articles):
        articles_text += f"""
Article {i+1}:
Title: {article['title']}
Source: {article['source']}
URL: {article['url']}
HN Score: {article['hn_score']}
Summary: {article['summary'][:500]}
---"""

    prompt = f"""You are an editor for "AI in News", a daily newsletter for non-technical founders exploring where technology is moving.

Here are {len(articles)} articles fetched from AI/tech news sources:

{articles_text}

Your job:
1. Select the 8 most relevant articles for founders (skip duplicates, events, job posts, or irrelevant content). Prefer articles with higher HN Score as they signal community interest.
2. For each selected article, produce a structured analysis.

Return ONLY a valid JSON array (no extra text before or after). Each item must have exactly these fields:

{{
  "title": "original article title",
  "url": "original article url",
  "source": "source name",
  "hn_score": <integer, copy from input>,
  "section": one of ["Foundation Layer", "Infrastructure Layer", "Application Layer"],
  "signal_tags": array of 1-3 tags from ["Opportunity", "Enabler", "Disruption", "Platform Shift", "Cost Driver", "New Market"],
  "maturity_tag": one of ["Early Research", "Emerging", "Production-Ready"],
  "summary": "2-3 sentence plain English summary of what happened",
  "founders_lens": "2 sentences in plain English (zero jargon) for a non-technical founder — what does this mean for spotting an opportunity or building a company? Return null if there is no clear founder takeaway."
}}

Section definitions:
- Foundation Layer: core AI/ML research, new model capabilities, breakthroughs, academic findings
- Infrastructure Layer: tools, platforms, compute, APIs, frameworks that builders use
- Application Layer: real-world products, use cases, deployments, companies
"""

    print("Sending articles to Claude for analysis...")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_response = message.content[0].text

    try:
        processed = json.loads(raw_response)
        print(f"Claude selected and analyzed {len(processed)} articles.")
        return processed
    except json.JSONDecodeError:
        print("Warning: Claude didn't return clean JSON. Trying to extract it...")
        start = raw_response.find("[")
        end = raw_response.rfind("]") + 1
        if start != -1 and end != 0:
            processed = json.loads(raw_response[start:end])
            print(f"Extracted {len(processed)} articles from response.")
            return processed
        else:
            print("Could not parse response. Raw output saved to debug.txt")
            with open("debug.txt", "w") as f:
                f.write(raw_response)
            return []


if __name__ == "__main__":
    articles = fetch_articles()
    processed = process_articles(articles)

    if processed:
        print("\nFirst processed article:")
        print(json.dumps(processed[0], indent=2))
