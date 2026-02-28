"""
Fetch trending AI/ML repositories from GitHub.
Queries the GitHub search API for repos created/updated in the past 7 days
across key AI topics. Deduplicates and caps at 15 repos.
"""
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

TOPICS = [
    "large language model",
    "AI agent",
    "machine learning framework",
    "generative AI",
    "LLM inference",
]

MAX_REPOS = 15


def fetch_github_trending():
    """Fetch trending AI/ML repos from the past 7 days."""
    since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    seen_urls = set()
    repos = []

    for topic in TOPICS:
        try:
            query = urllib.parse.quote(f"{topic} created:>{since}")
            url = (
                f"https://api.github.com/search/repositories"
                f"?q={query}&sort=stars&order=desc&per_page=10"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": "AIinNews/1.0",
                "Accept": "application/vnd.github.v3+json",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            for item in data.get("items", []):
                repo_url = item.get("html_url", "")
                if repo_url in seen_urls:
                    continue
                seen_urls.add(repo_url)

                stars = item.get("stargazers_count", 0)
                if stars < 50:
                    continue  # skip low-signal repos

                repos.append({
                    "title": f"{item['full_name']}: {item.get('description', 'No description')[:100]}",
                    "url": repo_url,
                    "summary": (
                        f"GitHub repo with {stars} stars. "
                        f"Language: {item.get('language', 'Unknown')}. "
                        f"{item.get('description', '')[:200]}"
                    ),
                    "source": "GitHub Trending",
                    "tier": "builder",
                    "hn_score": stars,  # use stars as proxy score
                })

        except Exception as e:
            print(f"  GitHub search failed for '{topic}': {e}")
            continue

    # Sort by stars descending, cap at MAX_REPOS
    repos.sort(key=lambda r: r.get("hn_score", 0), reverse=True)
    repos = repos[:MAX_REPOS]

    print(f"  GitHub: found {len(repos)} trending repos")
    return repos


if __name__ == "__main__":
    repos = fetch_github_trending()
    for r in repos:
        print(f"  [{r['hn_score']} stars] {r['title']}")
