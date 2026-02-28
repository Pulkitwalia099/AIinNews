"""
Idempotent daily newsletter runner.
Checks if today's newsletter already exists before generating.
Can be called by cron, Vercel cron, or manually.
"""
import os
from datetime import date


def run():
    today = date.today().isoformat()
    path = f"newsletters/{today}.json"

    if os.path.exists(path):
        print(f"Newsletter for {today} already exists. Skipping.")
        return False

    print(f"Generating newsletter for {today}...")
    from generate import generate_newsletter
    generate_newsletter()
    return True


if __name__ == "__main__":
    run()
