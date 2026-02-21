import json
import anthropic
from fetch import fetch_articles

client = anthropic.Anthropic()

def process_articles(articles):
    # Format articles into a simple text list for Claude to read
    articles_text = ""
    for i, article in enumerate(articles):
        articles_text += f"""
Article {i+1}:
Title: {article['title']}
Source: {article['source']}
URL: {article['url']}
Summary: {article['summary'][:500]}
---"""

    prompt = f"""You are an editor for "AI in News", a newsletter for founders exploring where technology is moving.

Here are {len(articles)} articles fetched from AI/tech news sources today:

{articles_text}

Your job:
1. Select the 8 most relevant articles for founders (skip duplicates, events, job posts, or irrelevant content)
2. For each selected article, produce a structured analysis

Return ONLY a valid JSON array (no extra text before or after). Each item in the array must have exactly these fields:

{{
  "title": "original article title",
  "url": "original article url",
  "source": "source name",
  "section": one of ["Foundational", "Infra", "Application", "Research"],
  "signal_tags": array of 1-3 tags from ["Opportunity", "Enabler", "Disruption", "Platform Shift", "Cost Driver", "New Market"],
  "maturity_tag": one of ["Early Research", "Emerging", "Production-Ready"],
  "summary": "2-3 sentence plain English summary of what happened",
  "so_what": "1 paragraph from a founder lens — what does this mean for someone building a company or exploring ideas?"
}}

Section definitions:
- Foundational: core AI/ML research, models, capabilities
- Infra: tools, platforms, compute, APIs that builders use
- Application: real-world products, use cases, deployments
- Research: academic papers, lab findings, experiments
"""

    print("Sending articles to Claude for analysis...")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_response = message.content[0].text

    # Parse the JSON response
    try:
        processed = json.loads(raw_response)
        print(f"Claude selected and analyzed {len(processed)} articles.")
        return processed
    except json.JSONDecodeError:
        print("Warning: Claude didn't return clean JSON. Trying to extract it...")
        # Sometimes Claude adds a small intro — try to find the JSON array
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
