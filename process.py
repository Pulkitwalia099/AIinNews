import json
import re
import time
import urllib.request
import urllib.parse
import anthropic

client = anthropic.Anthropic()

# ---------------------------------------------------------------------------
# HN Scoring — exact title match first, then keyword fallback
# ---------------------------------------------------------------------------

STOPWORDS = {"the", "a", "an", "is", "in", "of", "for", "to", "and", "on",
             "with", "how", "why", "new", "ai", "its", "by", "at", "from",
             "are", "was", "it", "that", "this", "has", "have", "will", "can"}


def normalize_title(title):
    """Lowercase, strip punctuation, collapse whitespace."""
    t = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", t).strip()


def title_similarity(a, b):
    """Word-overlap ratio between two titles (0-1)."""
    words_a = set(normalize_title(a).split())
    words_b = set(normalize_title(b).split())
    if not words_a or not words_b:
        return 0
    overlap = words_a & words_b
    return len(overlap) / min(len(words_a), len(words_b))


def _hn_search(query, hits=5):
    """Raw HN Algolia search, returns list of hits."""
    try:
        q = urllib.parse.quote(query)
        url = f"https://hn.algolia.com/api/v1/search?query={q}&tags=story&hitsPerPage={hits}"
        req = urllib.request.Request(url, headers={"User-Agent": "AIinNews/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read())
        return data.get("hits", [])
    except Exception:
        return []


def get_hn_score(title):
    """
    Query HackerNews for community engagement score.
    Strategy: exact title search first, then keyword fallback.
    Only count a hit if title similarity > 0.5.
    """
    norm = normalize_title(title)

    # Pass 1: search exact title
    hits = _hn_search(title, hits=5)
    for hit in hits:
        hn_title = hit.get("title", "")
        if title_similarity(norm, hn_title) > 0.5:
            return hit.get("points", 0) + hit.get("num_comments", 0)

    # Pass 2: keyword fallback (top 5 meaningful words)
    keywords = [w for w in norm.split() if w not in STOPWORDS and len(w) > 2][:5]
    if keywords:
        hits = _hn_search(" ".join(keywords), hits=3)
        for hit in hits:
            hn_title = hit.get("title", "")
            if title_similarity(norm, hn_title) > 0.5:
                return hit.get("points", 0) + hit.get("num_comments", 0)

    return 0


def score_articles(articles):
    """Add hn_score to each article with rate-limit-friendly pacing."""
    print("Scoring articles via HackerNews...")
    for i, article in enumerate(articles):
        article["hn_score"] = get_hn_score(article["title"])
        if (i + 1) % 10 == 0:
            print(f"  Scored {i + 1}/{len(articles)}...")
            time.sleep(0.5)  # be nice to HN API
    scored = sum(1 for a in articles if a["hn_score"] > 0)
    print(f"  Done. {scored}/{len(articles)} articles matched on HN.")
    return articles


# ---------------------------------------------------------------------------
# Deduplication — remove near-duplicate articles by title similarity
# ---------------------------------------------------------------------------

def deduplicate_articles(articles):
    """Remove duplicate articles. Keep the one with the higher HN score."""
    seen = []
    for article in articles:
        norm = normalize_title(article["title"])
        is_dup = False
        for i, (seen_norm, seen_article) in enumerate(seen):
            if title_similarity(norm, seen_norm) > 0.7:
                # Keep the one with higher HN score
                if article.get("hn_score", 0) > seen_article.get("hn_score", 0):
                    seen[i] = (norm, article)
                is_dup = True
                break
        if not is_dup:
            seen.append((norm, article))

    deduped = [article for _, article in seen]
    removed = len(articles) - len(deduped)
    if removed:
        print(f"  Dedup: removed {removed} duplicate(s), {len(deduped)} remain.")
    return deduped


# ---------------------------------------------------------------------------
# Two-pass Claude pipeline
# ---------------------------------------------------------------------------

def select_articles(articles):
    """
    Pass 1 (Haiku): Fast selection of the most relevant articles.
    Returns indices of selected articles.
    """
    articles_text = ""
    for i, article in enumerate(articles):
        articles_text += f"\n[{i}] {article['title']} (Source: {article['source']}, HN: {article.get('hn_score', 0)})\n"
        if article.get("summary"):
            articles_text += f"    {article['summary'][:200]}\n"

    prompt = f"""You are the selection editor for "AI in News", a daily AI briefing for builders and tech executives.

Here are {len(articles)} candidate articles:

{articles_text}

Select the 8-10 BEST articles for this audience. Prioritize:
1. Articles with high HN scores (strong community signal)
2. Major product launches, funding rounds, partnerships, or policy changes
3. Meaningful research breakthroughs with business implications
4. Skip: job posts, event announcements, listicles, opinion pieces with no news, duplicates

Return ONLY a JSON array of the selected article indices (e.g. [0, 3, 5, 7, 12, 15, 18, 21]).
No explanation, just the JSON array."""

    print("Pass 1: Selecting articles with Haiku...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    try:
        indices = json.loads(raw)
        selected = [articles[i] for i in indices if i < len(articles)]
        print(f"  Haiku selected {len(selected)} articles.")
        return selected
    except (json.JSONDecodeError, IndexError):
        # Fallback: try to extract array
        match = re.search(r"\[[\d,\s]+\]", raw)
        if match:
            indices = json.loads(match.group())
            selected = [articles[i] for i in indices if i < len(articles)]
            print(f"  Haiku selected {len(selected)} articles (extracted).")
            return selected
        # Last resort: take top 10 by HN score
        print("  Haiku selection failed. Falling back to top 10 by HN score.")
        return sorted(articles, key=lambda a: a.get("hn_score", 0), reverse=True)[:10]


def analyze_articles(articles):
    """
    Pass 2 (Sonnet): Deep analysis with editorial voice for HBS MBA audience.
    Returns fully structured article objects.
    """
    articles_text = ""
    for i, article in enumerate(articles):
        articles_text += f"""
Article {i+1}:
Title: {article['title']}
Source: {article['source']}
URL: {article['url']}
HN Score: {article.get('hn_score', 0)}
Summary: {article.get('summary', '')[:500]}
---"""

    prompt = f"""You are the senior analyst for "AI in News", a daily briefing read by builders, YC alumni, and technical executives.

Your readers are smart, time-pressed, and care about:
- Where to deploy capital or attention
- What shifts create new company-building opportunities
- What infrastructure changes affect their stack or costs
- What research will become products in 6-18 months

Here are {len(articles)} pre-selected articles to analyze:

{articles_text}

For each article, produce a structured analysis. Return ONLY a valid JSON array. Each item:

{{
  "title": "original article title",
  "url": "original article url",
  "source": "source name",
  "hn_score": <integer from input>,
  "section": one of ["Foundation Layer", "Infrastructure Layer", "Application Layer"],
  "signal_tags": array of 1-3 tags from ["Opportunity", "Enabler", "Disruption", "Platform Shift", "Cost Driver", "New Market"],
  "maturity_tag": one of ["Early Research", "Emerging", "Production-Ready"],
  "summary": "2-3 crisp sentences. Lead with what happened, then why it matters. No filler.",
  "builders_lens": "2-3 sentences for someone building in AI — whether that's a startup, a class project, a career move, or a product feature. Be specific — name the opportunity, the risk, or the strategic move. Return null if no actionable takeaway.",
  "impact_level": one of ["act", "watch", "context"] — "act" means builders should do something now, "watch" means monitor this closely, "context" means good to know,
  "technical_detail": "1 sentence of technical specifics for technical readers (model size, API details, benchmark numbers, architecture). Return null if the article is non-technical."
}}

Section definitions:
- Foundation Layer: core AI/ML research, new model capabilities, breakthroughs
- Infrastructure Layer: tools, platforms, compute, APIs, frameworks builders use
- Application Layer: real-world products, deployments, company moves, funding"""

    print("Pass 2: Analyzing articles with Sonnet...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text
    try:
        processed = json.loads(raw)
        print(f"  Sonnet analyzed {len(processed)} articles.")
        return processed
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end != 0:
            processed = json.loads(raw[start:end])
            print(f"  Extracted {len(processed)} articles from response.")
            return processed
        print("  Could not parse Sonnet response. Saving to debug.txt")
        with open("debug.txt", "w") as f:
            f.write(raw)
        return []


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_articles(articles):
    """Full pipeline: score → dedup → select (Haiku) → analyze (Sonnet)."""
    # Step 1: HN scoring
    articles = score_articles(articles)

    # Step 2: Deduplicate
    articles = deduplicate_articles(articles)

    # Step 3: Select (Haiku — fast, cheap)
    selected = select_articles(articles)

    # Step 4: Analyze (Sonnet — deep, editorial)
    processed = analyze_articles(selected)

    return processed


if __name__ == "__main__":
    from fetch import fetch_articles
    articles = fetch_articles()
    processed = process_articles(articles)

    if processed:
        print(f"\nFirst processed article:")
        print(json.dumps(processed[0], indent=2))
