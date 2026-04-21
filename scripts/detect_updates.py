#!/usr/bin/env python3
"""Detect whether a fetch produced net-new stories worth publishing.

Compares URLs in `raw_news.json` (fresh fetch) against URLs currently
published in `newsletter.json` (last successful edition).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_NEWS_PATH = ROOT / "raw_news.json"
NEWSLETTER_PATH = ROOT / "newsletter.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_urls(payload: dict) -> set[str]:
    urls: set[str] = set()
    for article in payload.get("articles", []) or []:
        url = str(article.get("url", "")).strip()
        if url:
            urls.add(url)
    return urls


def _set_output(name: str, value: str) -> None:
    from os import environ

    github_output_raw = environ.get("GITHUB_OUTPUT")
    if not github_output_raw:
        return

    github_output = Path(github_output_raw)
    with github_output.open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> None:
    fetched = _load_json(RAW_NEWS_PATH)
    published = _load_json(NEWSLETTER_PATH)

    fetched_urls = _extract_urls(fetched)
    published_urls = _extract_urls(published)

    new_urls = fetched_urls - published_urls
    has_news = bool(new_urls)

    _set_output("has_news", "true" if has_news else "false")
    _set_output("new_story_count", str(len(new_urls)))
    _set_output("fetched_story_count", str(len(fetched_urls)))
    _set_output("published_story_count", str(len(published_urls)))

    print(
        "Detect updates: "
        f"fetched={len(fetched_urls)} "
        f"published={len(published_urls)} "
        f"new={len(new_urls)} "
        f"has_news={has_news}"
    )


if __name__ == "__main__":
    main()