#!/usr/bin/env python3
"""
fetch_news.py — Fetches geopolitics news from GDELT, RSS feeds, and optionally NewsAPI.
Outputs raw_news.json with deduplicated articles.
"""

import json
import html
import logging
import os
import re
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
NEWSLETTER_JSON_PATH = os.path.join(ROOT, "newsletter.json")


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _get_with_retry(
    url: str,
    timeout: int = 20,
    max_retries: int = 4,
    backoff_base: float = 2.0,
    **kwargs,
) -> requests.Response:
    """GET *url* with exponential backoff on HTTP 429 / 5xx responses.

    Raises :class:`requests.RequestException` if all retries are exhausted.
    """
    last_exc: Exception = RuntimeError(f"All retries failed for {url}")
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = backoff_base * (2 ** attempt)
                log.warning(
                    "HTTP %d for %s — retrying in %.0fs (attempt %d/%d)…",
                    resp.status_code,
                    url,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            wait = backoff_base * (2 ** attempt)
            log.warning(
                "Request error for %s: %s — retrying in %.0fs (attempt %d/%d)…",
                url,
                exc,
                wait,
                attempt + 1,
                max_retries,
            )
            time.sleep(wait)
    raise last_exc


def _decode_entities(text: str) -> str:
    """Decode HTML entities, including double-encoded sequences."""
    if not text:
        return ""
    current = text
    for _ in range(3):
        decoded = html.unescape(current)
        if decoded == current:
            break
        current = decoded
    return re.sub(r"\s+", " ", current).strip()


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
    hooks_enabled = os.environ.get("AUDIENCE_HOOKS_ENABLED")
    if hooks_enabled is not None:
        cfg["audience_hooks_enabled"] = hooks_enabled.lower() in {"1", "true", "yes", "on"}
    hook_cap = os.environ.get("AUDIENCE_HOOKS_MAX_PER_FEED")
    if hook_cap:
        cfg["audience_hooks_max_per_feed"] = int(hook_cap)
    return cfg


def build_google_news_rss_url(query: str, hl: str = "en-IN", gl: str = "IN", ceid: str = "IN:en") -> str:
    params = {
        "q": query,
        "hl": hl,
        "gl": gl,
        "ceid": ceid,
    }
    return f"https://news.google.com/rss/search?{urlencode(params)}"


def build_audience_hook_feeds(cfg: dict) -> list[dict]:
    """Build optional, attribution-preserving audience hook feeds.

    These hooks are lightweight expansions around the primary feed set so
    GeoPulse can discover additional reporting surfaces without replacing
    core editorial sources.
    """
    hooks: list[dict] = []

    # Generic hook feeds configured by the user.
    for item in cfg.get("audience_hook_feeds", []):
        url = (item.get("url") or "").strip()
        source = (item.get("source") or "").strip()
        if url and source:
            hooks.append({"url": url, "source": source})

    # Inshorts-compatible hook path via Google News RSS search.
    inshorts_terms = cfg.get("inshorts_hook_queries", [])
    for term in inshorts_terms:
        term = (term or "").strip()
        if not term:
            continue
        g_query = f"site:inshorts.com {term}"
        hooks.append(
            {
                "url": build_google_news_rss_url(g_query),
                "source": "Inshorts (via Google News)",
            }
        )

    return hooks


def _gdelt_artlist(query: str, max_records: int, timespan_hours: int) -> list[dict]:
    """Inner helper: call GDELT v2 artlist and return parsed article dicts."""
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": min(max_records, 75),
        "format": "json",
        "timespan": f"{timespan_hours}H",
    }
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{urlencode(params)}"
    resp = _get_with_retry(url, timeout=25)
    data = resp.json()
    articles = []
    for art in data.get("articles", []):
        pub = art.get("seendate", "")
        try:
            dt = datetime.strptime(pub, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            published_at = dt.isoformat()
        except ValueError:
            published_at = pub
        articles.append(
            {
                "title": _decode_entities(art.get("title", "")),
                "url": art.get("url", ""),
                "source": _decode_entities(art.get("domain", "GDELT")),
                "published_at": published_at,
                "description": _decode_entities(art.get("title", "")),
                "image_url": art.get("socialimage", ""),
            }
        )
    return articles


def fetch_gdelt(query: str, max_articles: int, hours_back: int = 24) -> list[dict]:
    """Fetch from GDELT GKG v2 API — no key required.

    Falls back to a simplified query and/or a shorter look-back window if the
    primary call is rate-limited or returns nothing.
    """
    log.info("Fetching from GDELT (last %dh)…", hours_back)

    # Primary attempt — full query, full look-back.
    try:
        articles = _gdelt_artlist(query, max_articles, hours_back)
        if articles:
            log.info("GDELT returned %d articles.", len(articles))
            return articles
        log.warning("GDELT returned 0 articles; trying shorter look-back.")
    except Exception as exc:
        log.warning("GDELT primary fetch failed: %s", exc)

    # Fallback 1 — shorter look-back window (6 h).
    try:
        time.sleep(3)
        articles = _gdelt_artlist(query, max_articles, min(hours_back, 6))
        if articles:
            log.info("GDELT (6h fallback) returned %d articles.", len(articles))
            return articles
        log.warning("GDELT 6h fallback returned 0 articles; trying simplified query.")
    except Exception as exc:
        log.warning("GDELT 6h fallback failed: %s", exc)

    # Fallback 2 — simplified single-keyword query, 24 h.
    simple_query = (query.split(" OR ")[0]).strip()
    try:
        time.sleep(3)
        articles = _gdelt_artlist(simple_query, max_articles, hours_back)
        if articles:
            log.info("GDELT (simplified query) returned %d articles.", len(articles))
            return articles
    except Exception as exc:
        log.warning("GDELT simplified-query fallback failed: %s", exc)

    log.warning("All GDELT attempts returned 0 articles.")
    return []


def _extract_image_url(entry) -> str:
    """Try to extract an image URL from an RSS entry."""
    # media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url", "")
    # media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for mc in entry.media_content:
            if mc.get("type", "").startswith("image/") or mc.get("url", ""):
                return mc.get("url", "")
    # enclosures
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href", enc.get("url", ""))
    # og:image in summary HTML
    summary_html = entry.get("summary", entry.get("description", ""))
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary_html)
    if img_match:
        return img_match.group(1)
    return ""


def fetch_rss(feeds: list[dict], max_per_feed: int = 10) -> list[dict]:
    """Fetch from a list of RSS feed URLs.

    Uses :func:`_get_with_retry` to download each feed so that transient 429
    or 5xx responses are retried with exponential back-off before giving up.
    """
    log.info("Fetching from %d RSS feeds...", len(feeds))
    articles = []
    for feed_cfg in feeds:
        url = feed_cfg["url"]
        source = _decode_entities(feed_cfg.get("source", url))
        try:
            resp = _get_with_retry(url, timeout=15)
            parsed = feedparser.parse(resp.content)
            count = 0
            for entry in parsed.entries:
                if count >= max_per_feed:
                    break
                title = _decode_entities(entry.get("title", ""))
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

                image_url = _extract_image_url(entry)

                if title and link:
                    articles.append(
                        {
                            "title": title,
                            "url": link,
                            "source": source,
                            "published_at": published_at,
                            "description": _decode_entities(_strip_html(summary))[:400],
                            "image_url": image_url,
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
        resp = _get_with_retry(url, timeout=20)
        data = resp.json()
        for art in data.get("articles", []):
            if art.get("title") == "[Removed]":
                continue
            articles.append(
                {
                    "title": _decode_entities(art.get("title") or ""),
                    "url": art.get("url", ""),
                    "source": _decode_entities((art.get("source") or {}).get("name", "NewsAPI")),
                    "published_at": art.get("publishedAt", ""),
                    "description": _decode_entities(art.get("description") or "")[:400],
                    "image_url": art.get("urlToImage", ""),
                }
            )
        log.info("NewsAPI returned %d articles.", len(articles))
    except Exception as exc:
        log.warning("NewsAPI fetch failed: %s", exc)
    return articles


def fetch_gnews_rss(queries: list[str], max_per_query: int = 8) -> list[dict]:
    """Fetch from Google News RSS for a list of search queries.

    Google News RSS is free, requires no API key, and serves fresh results.
    Each query is turned into a feed URL via :func:`build_google_news_rss_url`.
    """
    if not queries:
        return []
    feeds = [
        {
            "url": build_google_news_rss_url(q, hl="en-US", gl="US", ceid="US:en"),
            "source": f"Google News ({q[:40]})",
        }
        for q in queries
    ]
    log.info("Fetching Google News RSS for %d queries…", len(queries))
    return fetch_rss(feeds, max_per_feed=max_per_query)


def deduplicate(articles: list[dict]) -> list[dict]:
    """Deduplicate by URL and near-duplicate titles.

    Instead of discarding articles with the same title, their (url, source)
    pairs are merged into the primary article's ``sources`` list so the card
    can offer readers multiple outlets covering the same story.
    """
    seen_urls: set[str] = set()
    title_to_idx: dict[str, int] = {}
    unique: list[dict] = []
    for art in articles:
        url = art["url"].rstrip("/")
        title_key = art["title"].lower()[:60]
        if not art["title"] or not art["url"]:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        if title_key in title_to_idx:
            # Merge this source into the already-kept article.
            primary = unique[title_to_idx[title_key]]
            if not primary.get("sources"):
                # First duplicate encountered: seed the list with the primary's own source.
                primary["sources"] = [{"url": primary["url"], "source": primary["source"]}]
            primary["sources"].append({"url": url, "source": art["source"]})
        else:
            title_to_idx[title_key] = len(unique)
            unique.append(art)
    return unique


def _strip_html(text: str) -> str:
    """Very lightweight HTML tag stripper."""
    return re.sub(r"<[^>]+>", "", text)


def load_previous_articles(max_articles: int) -> list[dict]:
    """Fallback to prior newsletter stories if fresh sources return nothing."""
    if not os.path.exists(NEWSLETTER_JSON_PATH):
        return []

    try:
        with open(NEWSLETTER_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        previous = []
        for art in data.get("articles", []):
            title = (art.get("title") or "").strip()
            url = (art.get("url") or "").strip()
            if not title or not url:
                continue
            previous.append(
                {
                    "title": _decode_entities(title),
                    "url": url,
                    "source": _decode_entities(art.get("source", "GeoPulse Archive")),
                    "published_at": art.get("published_at", ""),
                    "description": _decode_entities(art.get("summary") or title)[:400],
                    "image_url": art.get("image_url", ""),
                }
            )
        return previous[:max_articles]
    except Exception as exc:
        log.warning("Unable to load previous newsletter fallback: %s", exc)
        return []


def main() -> None:
    cfg = load_config()
    sources = cfg.get("news_sources", ["gdelt", "rss"])
    query = cfg["news_query"]
    max_articles = cfg["max_articles"]

    # Threshold below which we activate additional fallback layers.
    LOW_WATER_MARK = max(5, max_articles // 4)

    all_articles: list[dict] = []

    # ── Layer 1: GDELT ────────────────────────────────────────────────────────
    if "gdelt" in sources:
        all_articles.extend(fetch_gdelt(query, max_articles))
        time.sleep(1)  # be polite

    # ── Layer 2: Primary RSS feeds ────────────────────────────────────────────
    if "rss" in sources:
        rss_feeds = cfg.get("rss_feeds", [])
        all_articles.extend(fetch_rss(rss_feeds, max_per_feed=10))

    # ── Layer 3: NewsAPI (optional, key required) ─────────────────────────────
    if "newsapi" in sources:
        api_key = os.environ.get("NEWSAPI_KEY", "")
        if api_key:
            all_articles.extend(fetch_newsapi(query, api_key, max_articles))
        else:
            log.warning("newsapi source enabled but NEWSAPI_KEY not set — skipping.")

    # ── Layer 4: Audience hooks ───────────────────────────────────────────────
    if cfg.get("audience_hooks_enabled", True):
        hook_feeds = build_audience_hook_feeds(cfg)
        hook_cap = int(cfg.get("audience_hooks_max_per_feed", 3))
        if hook_feeds:
            log.info("Fetching audience hooks from %d feeds...", len(hook_feeds))
            all_articles.extend(fetch_rss(hook_feeds, max_per_feed=hook_cap))

    # ── Layer 5: Google News RSS (always active; free, no key required) ───────
    gnews_queries = cfg.get("gnews_rss_queries", [])
    if gnews_queries:
        all_articles.extend(fetch_gnews_rss(gnews_queries, max_per_query=8))

    # ── Fallback A: fallback RSS feeds (activated when we have too few items) ─
    if len(deduplicate(all_articles)) < LOW_WATER_MARK:
        fallback_feeds = cfg.get("fallback_rss_feeds", [])
        if fallback_feeds:
            log.warning(
                "Only %d articles so far (threshold %d); pulling fallback RSS feeds…",
                len(all_articles),
                LOW_WATER_MARK,
            )
            all_articles.extend(fetch_rss(fallback_feeds, max_per_feed=10))

    # ── Fallback B: retry primary RSS with a higher per-feed cap ─────────────
    if not all_articles:
        log.warning("No articles fetched from any source; retrying primary RSS with higher cap…")
        rss_feeds = cfg.get("rss_feeds", [])
        all_articles.extend(fetch_rss(rss_feeds, max_per_feed=20))

    unique = deduplicate(all_articles)
    unique = unique[:max_articles]

    # ── Fallback C: re-use previous newsletter articles ───────────────────────
    if not unique:
        log.warning("No unique articles available; falling back to previous newsletter stories.")
        unique = load_previous_articles(max_articles)

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
