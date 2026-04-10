#!/usr/bin/env python3
"""
fetch_news.py — Fetches geopolitics news from GDELT, RSS feeds, and optionally NewsAPI.
Outputs raw_news.json with deduplicated articles.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import feedparser
import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yml")
OUTPUT_PATH = os.path.join(ROOT, "raw_news.json")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # Allow env overrides
    cfg["llm_provider"] = os.environ.get("LLM_PROVIDER", cfg.get("llm_provider", "none"))
    cfg["max_articles"] = int(os.environ.get("MAX_ARTICLES", cfg.get("max_articles", 20)))
    cfg["news_query"] = os.environ.get("NEWS_QUERY", cfg.get("news_query", "geopolitics"))
    sources_env = os.environ.get("NEWS_SOURCES")
    if sources_env:
        cfg["news_sources"] = [s.strip() for s in sources_env.split(",")]
    return cfg


def fetch_gdelt(query: str, max_articles: int, hours_back: int = 24) -> list[dict]:
    """Fetch from GDELT GKG API — no key required."""
    log.info("Fetching from GDELT...")
    articles = []
    try:
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": min(max_articles, 75),
            "format": "json",
            "timespan": f"{hours_back}H",
        }
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?{urlencode(params)}"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        for art in data.get("articles", []):
            pub = art.get("seendate", "")
            # GDELT date format: YYYYMMDDTHHMMSSZ
            try:
                dt = datetime.strptime(pub, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                published_at = dt.isoformat()
            except ValueError:
                published_at = pub
            articles.append(
                {
                    "title": art.get("title", "").strip(),
                    "url": art.get("url", ""),
                    "source": art.get("domain", "GDELT"),
                    "published_at": published_at,
                    "description": art.get("title", ""),
                }
            )
        log.info("GDELT returned %d articles.", len(articles))
    except Exception as exc:
        log.warning("GDELT fetch failed: %s", exc)
    return articles


def fetch_rss(feeds: list[dict], max_per_feed: int = 10) -> list[dict]:
    """Fetch from a list of RSS feed URLs."""
    log.info("Fetching from %d RSS feeds...", len(feeds))
    articles = []
    for feed_cfg in feeds:
        url = feed_cfg["url"]
        source = feed_cfg.get("source", url)
        try:
            parsed = feedparser.parse(url)
            count = 0
            for entry in parsed.entries:
                if count >= max_per_feed:
                    break
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))
                # Parse published date
                published_at = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        published_at = dt.isoformat()
                    except Exception:
                        published_at = entry.get("published", "")
                else:
                    published_at = entry.get("published", "")

                if title and link:
                    articles.append(
                        {
                            "title": title,
                            "url": link,
                            "source": source,
                            "published_at": published_at,
                            "description": _strip_html(summary)[:300],
                        }
                    )
                    count += 1
            log.info("  %s: %d articles", source, count)
        except Exception as exc:
            log.warning("RSS feed %s failed: %s", url, exc)
    return articles


def fetch_newsapi(query: str, api_key: str, max_articles: int) -> list[dict]:
    """Fetch from NewsAPI (requires NEWSAPI_KEY)."""
    log.info("Fetching from NewsAPI...")
    articles = []
    try:
        from_time = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "q": query,
            "from": from_time,
            "sortBy": "publishedAt",
            "pageSize": min(max_articles, 100),
            "apiKey": api_key,
            "language": "en",
        }
        url = f"https://newsapi.org/v2/everything?{urlencode(params)}"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        for art in data.get("articles", []):
            if art.get("title") == "[Removed]":
                continue
            articles.append(
                {
                    "title": (art.get("title") or "").strip(),
                    "url": art.get("url", ""),
                    "source": (art.get("source") or {}).get("name", "NewsAPI"),
                    "published_at": art.get("publishedAt", ""),
                    "description": (art.get("description") or "")[:300],
                }
            )
        log.info("NewsAPI returned %d articles.", len(articles))
    except Exception as exc:
        log.warning("NewsAPI fetch failed: %s", exc)
    return articles


def deduplicate(articles: list[dict]) -> list[dict]:
    """Remove duplicate articles by URL and near-duplicate titles."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique = []
    for art in articles:
        url = art["url"].rstrip("/")
        title_key = art["title"].lower()[:60]
        if url in seen_urls or title_key in seen_titles:
            continue
        if not art["title"] or not art["url"]:
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)
        unique.append(art)
    return unique


def _strip_html(text: str) -> str:
    """Very lightweight HTML tag stripper."""
    import re
    return re.sub(r"<[^>]+>", "", text)


def main() -> None:
    cfg = load_config()
    sources = cfg.get("news_sources", ["gdelt", "rss"])
    query = cfg["news_query"]
    max_articles = cfg["max_articles"]

    all_articles: list[dict] = []

    if "gdelt" in sources:
        all_articles.extend(fetch_gdelt(query, max_articles))
        time.sleep(1)  # be polite

    if "rss" in sources:
        rss_feeds = cfg.get("rss_feeds", [])
        all_articles.extend(fetch_rss(rss_feeds, max_per_feed=10))

    if "newsapi" in sources:
        api_key = os.environ.get("NEWSAPI_KEY", "")
        if api_key:
            all_articles.extend(fetch_newsapi(query, api_key, max_articles))
        else:
            log.warning("newsapi source enabled but NEWSAPI_KEY not set — skipping.")

    # Fallback: if nothing was fetched, retry RSS only
    if not all_articles:
        log.warning("No articles fetched from primary sources; retrying RSS fallback...")
        rss_feeds = cfg.get("rss_feeds", [])
        all_articles.extend(fetch_rss(rss_feeds, max_per_feed=15))

    unique = deduplicate(all_articles)
    unique = unique[:max_articles]

    log.info("Total unique articles after dedup: %d", len(unique))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "article_count": len(unique),
                "articles": unique,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    log.info("Saved to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
