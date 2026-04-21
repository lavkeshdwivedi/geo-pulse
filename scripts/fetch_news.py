import re as _re_for_title


# Short labels we routinely see before a colon in wire headlines. When the
# left-hand side of a colon matches one of these (case-insensitive, ignoring
# trailing qualifiers), the cleaner drops the label and keeps the real story.
# Includes English AND common Hindi (Devanagari) kicker prefixes — Hindi
# aggregators heavily use them in titles.
_TITLE_COLON_PREFIXES = {
    # English kickers
    "live", "live updates", "live blog", "live coverage", "live news",
    "breaking", "breaking news", "update", "updates", "developing",
    "exclusive", "watch", "video", "analysis", "opinion", "explainer",
    "explained", "factbox", "factcheck", "fact check", "interview",
    "profile", "editorial", "comment", "podcast", "photos", "in pictures",
    "in pics", "pics", "feature", "special report", "report", "spotlight",
    "just in", "flash", "alert", "top story", "top news", "morning briefing",
    "evening briefing", "what we know", "what you need to know",
    "world news", "india news", "business news", "sports news",
    "news", "news update", "big story", "big news", "top headlines",
    "petrol price", "gold price", "market update", "weather update",
    # Hindi kickers (Devanagari)
    "लाइव", "लाइव अपडेट", "लाइव ब्लॉग", "लाइव कवरेज", "लाइव न्यूज",
    "ब्रेकिंग", "ब्रेकिंग न्यूज", "एक्सक्लूसिव", "वीडियो", "देखें",
    "तत्काल", "फौरन", "फ्लैश", "अलर्ट", "खास", "खास खबर",
    "बड़ी खबर", "बड़ी ख़बर", "ताजा खबर", "ताज़ा खबर", "ताजा अपडेट",
    "मुख्य खबर", "टॉप खबर", "टॉप न्यूज", "विश्लेषण", "रिपोर्ट",
    "विशेष रिपोर्ट", "स्पेशल रिपोर्ट", "राय", "संपादकीय",
    "क्या आप जानते हैं", "जानिए",
}


def _strip_publisher_suffix(text: str) -> str:
    """Drop trailing ' - Publisher Name' that Google News RSS always adds.

    Matches ' - ' (hyphen) or ' | ' (pipe) followed by a short publisher tag
    at the end of the headline. Keeps the core story intact. Handles three
    flavours of publisher tails:
      1. Title-case or ALL-CAPS brand: "...ceasefire - Reuters"
      2. Domain names: "...फैसला - bhaskarhindi.com"
      3. Dot-com-style with TLD anywhere: "... | timesofindia.indiatimes.com"
    """
    if not text:
        return text
    # Hyphen/pipe/en-dash/em-dash separated tail, up to ~60 chars.
    m = _re_for_title.search(r"\s+[\-\|\u2013\u2014]\s+([^\-\|\u2013\u2014]{2,60})$", text)
    if not m:
        return text
    tail = m.group(1).strip()
    words = tail.split()
    if not words or len(words) > 6 or tail.endswith(("?", "!")):
        return text
    # Flavour 1: brand-style (Title Case, ALL CAPS, or starts uppercase).
    if tail[0].isupper() or tail.isupper():
        return text[: m.start()].rstrip()
    # Flavour 2 + 3: domain-like tail. Anything with a recognised TLD is a
    # publisher, regardless of case. Covers *.com, *.in, *.org, *.net, *.co,
    # *.co.in, *.co.uk, *.news, *.io, and nested subdomains.
    if _re_for_title.search(
        r"\.(com|in|org|net|co|co\.in|co\.uk|news|io|gov|edu)(?:\b|$)",
        tail.lower(),
    ):
        return text[: m.start()].rstrip()
    return text


def _strip_colon_prefix(text: str) -> str:
    """If the title opens with a short label followed by a colon, drop it.

    "Live updates: Trump says X" -> "Trump says X"
    "Breaking: ceasefire holds"  -> "ceasefire holds"
    Keeps the headline if the left side is long or substantive (e.g.
    "India vs Pakistan: new talks" stays unchanged).
    """
    if not text or ":" not in text:
        return text
    left, _, right = text.partition(":")
    left_clean = left.strip().lower()
    right_clean = right.strip()
    if not right_clean:
        return text
    # If the left side is long, it's probably part of the real headline.
    if len(left.strip()) > 35 or len(left_clean.split()) > 5:
        return text
    # Match against the known prefix set, allowing a trailing qualifier like
    # "live updates 2 April".
    for prefix in _TITLE_COLON_PREFIXES:
        if left_clean == prefix or left_clean.startswith(prefix + " "):
            # Capitalise the first letter of the remaining title.
            return right_clean[0].upper() + right_clean[1:] if right_clean else right_clean
    # Generic fallback: if the left side is short AND the right side is
    # substantially longer, treat the left as a kicker and drop it.
    if len(right_clean) > len(left.strip()) * 2 and len(right_clean.split()) >= 4:
        return right_clean[0].upper() + right_clean[1:] if right_clean else right_clean
    return text


def clean_title(text: str) -> str:
    """Normalise a raw RSS/NewsAPI title into a reader-friendly headline.

    Removes the "Source - Publisher" suffix that Google News always appends,
    strips short kicker labels before a colon ("Live updates: ..."), squashes
    repeated whitespace, and trims stray punctuation at either end. Preserves
    meaningful colons (e.g. "India vs Pakistan: what we know next").
    """
    if not text:
        return text
    t = _re_for_title.sub(r"\s+", " ", text).strip()
    # Up to two passes because Google News sometimes double-stacks the source.
    for _ in range(2):
        t = _strip_publisher_suffix(t)
    t = _strip_colon_prefix(t)
    # Strip stray leading separators left over from prefix removal.
    t = t.lstrip(" \u2013\u2014-:,.|").rstrip(" \u2013\u2014-:,|").strip()
    return t


def truncate_title(text: str, max_chars: int = 100) -> str:
    """Clean and truncate to max_chars without cutting words. No ellipsis is
    appended - the user rule is zero ellipsis anywhere in the pipeline. A
    clean word-boundary cut reads better than a dangling …."""
    text = clean_title(text)
    if not text or len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_space = cut.rfind(' ')
    if last_space > 40:
        cut = cut[:last_space]
    return cut.rstrip(' ,.;:–—‐।…')
#!/usr/bin/env python3
"""
fetch_news.py — Fetches geopolitics news from GDELT, RSS feeds, and optionally NewsAPI.
Outputs raw_news.json with deduplicated articles tagged by language (en/hi).

English sources produce language="en" articles.
Hindi sources produce language="hi" articles.
The two sets never cross-contaminate.
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
# Brand user-agent — read once at import from config.yml, with a generic
# template fallback so a fork that strips the brand block still functions.
# ---------------------------------------------------------------------------
_DEFAULT_USER_AGENT = "GeoPulseTemplate/1.0"


def _load_user_agent_from_config() -> str:
    """Return brand.user_agent from config.yml, or a safe template fallback."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return _DEFAULT_USER_AGENT
    brand = data.get("brand") or {}
    ua = (brand.get("user_agent") or "").strip()
    return ua or _DEFAULT_USER_AGENT


_GP_USER_AGENT = _load_user_agent_from_config()


def _load_site_title_from_config() -> str:
    """Return brand.site_title for fallback tags. Defaults to GeoPulse."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return "GeoPulse"
    return (data.get("brand") or {}).get("site_title") or "GeoPulse"


_GP_SITE_TITLE_FALLBACK = _load_site_title_from_config()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_devanagari_text(text: str, threshold: float = 0.35) -> bool:
    """Return True if ≥ threshold fraction of alphabetic chars are Devanagari."""
    if not text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 5:
        return False
    devanagari = sum(1 for ch in letters if "\u0900" <= ch <= "\u097f")
    return (devanagari / len(letters)) >= threshold


def _is_latin_text(text: str, threshold: float = 0.65) -> bool:
    """Return True if ≥ threshold fraction of alphabetic chars are Latin/ASCII."""
    if not text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 5:
        return False
    latin = sum(1 for ch in letters if "A" <= ch <= "z")
    return (latin / len(letters)) >= threshold


def _matches_language(title: str, lang: str) -> bool:
    """Return True when the article title script matches the expected language.

    For English ("en") we require the title to be predominantly Latin.
    For Hindi ("hi") we require it to contain a meaningful share of Devanagari.
    Any other language code is always accepted (no filter).
    """
    if lang == "en":
        return _is_latin_text(title)
    if lang == "hi":
        return _is_devanagari_text(title)
    return True


def _safe_url(url: str) -> str:
    """Return a log-safe version of *url* with sensitive query params redacted."""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    try:
        parsed = urlparse(url)
        sensitive = {"apikey", "api_key", "key", "token", "access_token", "secret"}
        qs = parse_qs(parsed.query, keep_blank_values=True)
        redacted = {
            k: (["[REDACTED]"] if k.lower() in sensitive else v)
            for k, v in qs.items()
        }
        safe_query = urlencode(redacted, doseq=True)
        return urlunparse(parsed._replace(query=safe_query))
    except Exception:
        return "<url>"


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
    safe = _safe_url(url)
    last_exc: Exception | None = None
    last_resp = None
    for attempt in range(max_retries):
        wait = backoff_base * (2 ** attempt)
        is_last = attempt == max_retries - 1
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_resp = resp
                if is_last:
                    break
                log.warning(
                    "HTTP %d for %s — retrying in %.0fs (attempt %d/%d)…",
                    resp.status_code,
                    safe,
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
            if is_last:
                break
            log.warning(
                "Request error for %s: %s — retrying in %.0fs (attempt %d/%d)…",
                safe,
                type(exc).__name__,
                wait,
                attempt + 1,
                max_retries,
            )
            time.sleep(wait)
    if last_exc is not None:
        raise last_exc
    if last_resp is not None:
        raise requests.HTTPError(
            f"HTTP {last_resp.status_code} after {max_retries} attempts for {safe}",
            response=last_resp,
        )
    raise requests.RequestException(f"All retries failed for {safe}")


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


def _tag_language(articles: list[dict], lang: str) -> list[dict]:
    """Tag each article with a language code in-place and return the list."""
    for art in articles:
        art["language"] = lang
    return articles


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
    """Build optional, attribution-preserving English audience hook feeds."""
    hooks: list[dict] = []

    for item in cfg.get("audience_hook_feeds", []):
        url = (item.get("url") or "").strip()
        source = (item.get("source") or "").strip()
        if url and source:
            hooks.append({"url": url, "source": source})

    # geopulse-compatible hook path via Google News RSS search.
    geopulse_terms = cfg.get("geopulse_hook_queries", [])
    for term in geopulse_terms:
        term = (term or "").strip()
        if not term:
            continue
        g_query = f"site:geopulse.com {term}"
        hooks.append(
            {
                "url": build_google_news_rss_url(g_query),
                "source": "geopulse (via Google News)",
            }
        )

    return hooks

def _extract_image_url(entry) -> str:
    """Try to extract an image URL from an RSS entry."""
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url", "")
    if hasattr(entry, "media_content") and entry.media_content:
        for mc in entry.media_content:
            if mc.get("type", "").startswith("image/") or mc.get("url", ""):
                return mc.get("url", "")
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href", enc.get("url", ""))
    summary_html = entry.get("summary", entry.get("description", ""))
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary_html)
    if img_match:
        return img_match.group(1)
    return ""


# ── og:image scraper ─────────────────────────────────────────────────────────
# When the feed does not ship an image, pull one from the article page itself.
# Every mainstream news site sets og:image or twitter:image. Results are
# cached per run so re-parsing the same URL from multiple feeds is cheap.

_OG_IMAGE_CACHE: dict[str, str] = {}

_OG_META_RES = [
    re.compile(
        r"""<meta[^>]+?property=["']og:image(?::secure_url)?["'][^>]+?content=["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<meta[^>]+?name=["']og:image["'][^>]+?content=["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<meta[^>]+?name=["']twitter:image(?::src)?["'][^>]+?content=["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<meta[^>]+?property=["']twitter:image(?::src)?["'][^>]+?content=["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    # Some sites swap attribute order (content before name/property).
    re.compile(
        r"""<meta[^>]+?content=["']([^"']+)["'][^>]+?property=["']og:image(?::secure_url)?["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<meta[^>]+?content=["']([^"']+)["'][^>]+?name=["']twitter:image(?::src)?["']""",
        re.IGNORECASE,
    ),
]


def _absolute_url(base: str, candidate: str) -> str:
    """Resolve a possibly-relative image URL against the article URL."""
    from urllib.parse import urljoin
    if not candidate:
        return ""
    try:
        return urljoin(base, candidate.strip())
    except Exception:
        return candidate.strip()


def fetch_og_image(article_url: str, timeout: float = 8.0) -> str:
    """Pull og:image / twitter:image from the article's HTML. Returns "" on miss.

    Kept deliberately small and dependency-free: one GET with a browser-like
    user agent, regex scan of the first 200 KB, done. We cap the read so a
    slow or giant page never holds the pipeline up.
    """
    if not article_url:
        return ""
    cached = _OG_IMAGE_CACHE.get(article_url)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            article_url,
            timeout=timeout,
            allow_redirects=True,
            headers={
                "User-Agent": f"Mozilla/5.0 (compatible; {_GP_USER_AGENT})",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.8",
            },
            stream=True,
        )
        if resp.status_code >= 400:
            _OG_IMAGE_CACHE[article_url] = ""
            return ""
        head = b""
        for chunk in resp.iter_content(chunk_size=8192):
            head += chunk
            if len(head) >= 200_000:
                break
        resp.close()
    except Exception:
        _OG_IMAGE_CACHE[article_url] = ""
        return ""

    try:
        text = head.decode("utf-8", errors="replace")
    except Exception:
        text = head.decode("latin-1", errors="replace")

    # Limit scan to the <head> block; that is where og meta lives.
    head_end = text.lower().find("</head>")
    scan_area = text if head_end < 0 else text[:head_end]

    for pat in _OG_META_RES:
        m = pat.search(scan_area)
        if m:
            img = html.unescape((m.group(1) or "").strip())
            absolute = _absolute_url(resp.url if hasattr(resp, "url") else article_url, img)
            _OG_IMAGE_CACHE[article_url] = absolute
            return absolute

    _OG_IMAGE_CACHE[article_url] = ""
    return ""


# ── Stock image fallback (Pexels, then Unsplash) ─────────────────────────────
# When the feed and the article page both fail to hand us an image, we search
# Pexels first (no attribution required, generous free quota) and then Unsplash.
# Both are keyed on a short query string derived from the article's title so we
# get something topically relevant rather than a generic stock photo. Results
# are cached per query to keep the call count low across a pipeline run.

_STOCK_IMAGE_CACHE: dict[str, str] = {}


_STOCK_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "at", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "has", "have", "had", "do", "does", "did", "will",
    "would", "should", "could", "may", "might", "must", "this", "that",
    "these", "those", "it", "its", "he", "she", "they", "them", "his",
    "her", "their", "our", "we", "you", "i", "my", "your", "not", "no",
    "says", "said", "after", "before", "over", "under", "into", "out",
    "live", "update", "updates", "news", "breaking", "report", "analysis",
    "amid", "amidst", "new", "latest", "today", "year", "years",
}


def _stock_query_from_title(title: str) -> str:
    """Build a short query for stock image search from an article title."""
    if not title:
        return ""
    cleaned = re.sub(r"[\"\'\u2018\u2019\u201c\u201d]", " ", title)
    cleaned = re.sub(r"[^\w\s\u0900-\u097f]+", " ", cleaned, flags=re.UNICODE)
    tokens = [t for t in cleaned.split() if t]
    meaningful: list[str] = []
    for t in tokens:
        if t.lower() in _STOCK_STOPWORDS:
            continue
        meaningful.append(t)
        if len(meaningful) >= 4:
            break
    if not meaningful:
        meaningful = tokens[:4]
    return " ".join(meaningful).strip()


def fetch_pexels_image(query: str, timeout: float = 8.0) -> str:
    """Return a Pexels photo URL for the query, or empty string on miss."""
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key or not query:
        return ""
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={
                "Authorization": api_key,
                "User-Agent": _GP_USER_AGENT,
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json() or {}
        photos = data.get("photos") or []
        if not photos:
            return ""
        src = photos[0].get("src") or {}
        return (
            src.get("large2x")
            or src.get("large")
            or src.get("original")
            or photos[0].get("url", "")
        )
    except Exception:
        return ""


def fetch_unsplash_image(query: str, timeout: float = 8.0) -> str:
    """Return an Unsplash photo URL for the query, or empty string on miss."""
    access_key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not access_key or not query:
        return ""
    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={
                "Authorization": f"Client-ID {access_key}",
                "User-Agent": _GP_USER_AGENT,
                "Accept-Version": "v1",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json() or {}
        results = data.get("results") or []
        if not results:
            return ""
        urls = results[0].get("urls") or {}
        return (
            urls.get("regular")
            or urls.get("small")
            or urls.get("full")
            or ""
        )
    except Exception:
        return ""


def fetch_stock_image(title: str) -> str:
    """Pexels first, Unsplash second. Per-query caching keeps calls low."""
    query = _stock_query_from_title(title)
    if not query:
        return ""
    cached = _STOCK_IMAGE_CACHE.get(query)
    if cached is not None:
        return cached
    img = fetch_pexels_image(query)
    if not img:
        img = fetch_unsplash_image(query)
    _STOCK_IMAGE_CACHE[query] = img
    return img


def ensure_image_url(entry_image: str, article_url: str, title: str = "") -> str:
    """Return a non-empty image URL.

    Order of preference:
    1. Image already attached by the feed entry.
    2. og:image / twitter:image on the article page.
    3. Pexels stock photo keyed on the article title.
    4. Unsplash stock photo keyed on the article title.
    """
    if entry_image:
        return entry_image
    scraped = fetch_og_image(article_url)
    if scraped:
        return scraped
    return fetch_stock_image(title)


def fetch_rss(feeds: list[dict], max_per_feed: int = 10, language: str = "") -> list[dict]:
    """Fetch from a list of RSS feed URLs.

    If *language* is "en" or "hi", articles whose title script does not match
    are silently skipped so English feeds never carry Hindi stories and vice
    versa.
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
            skipped = 0
            for entry in parsed.entries:
                if count >= max_per_feed:
                    break
                title = truncate_title(_decode_entities(entry.get("title", "")))
                link = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))
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
                    if language and not _matches_language(title, language):
                        skipped += 1
                        continue
                    # Backfill missing images. First try og:image on the
                    # article page, then Pexels/Unsplash stock photos keyed on
                    # the title so every card has something to show.
                    if not image_url:
                        image_url = ensure_image_url("", link, title=title)
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
            if skipped:
                log.info("  %s: %d articles (%d skipped — wrong script)", source, count, skipped)
            else:
                log.info("  %s: %d articles", source, count)
        except Exception as exc:
            log.warning("RSS feed %s failed: %s", url, exc)
    return articles


def fetch_newsapi(query: str, api_key: str, max_articles: int) -> list[dict]:
    """Fetch from NewsAPI (requires NEWSAPI_KEY). English only."""
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
            link = art.get("url", "")
            image_url = art.get("urlToImage", "") or ""
            raw_title = truncate_title(_decode_entities(art.get("title") or ""))
            if not image_url:
                image_url = ensure_image_url("", link, title=raw_title)
            articles.append(
                {
                    "title": raw_title,
                    "url": link,
                    "source": _decode_entities((art.get("source") or {}).get("name", "NewsAPI")),
                    "published_at": art.get("publishedAt", ""),
                    "description": _decode_entities(art.get("description") or "")[:400],
                    "image_url": image_url,
                }
            )
        log.info("NewsAPI returned %d articles.", len(articles))
    except Exception as exc:
        log.warning("NewsAPI fetch failed: %s", exc)
    return articles


def fetch_gnews_rss(queries: list[str], max_per_query: int = 8) -> list[dict]:
    """Fetch from Google News RSS for English search queries."""
    if not queries:
        return []
    feeds = [
        {
            "url": build_google_news_rss_url(q, hl="en-US", gl="US", ceid="US:en"),
            "source": f"Google News ({q[:40]})",
        }
        for q in queries
    ]
    log.info("Fetching Google News RSS (English) for %d queries…", len(queries))
    return fetch_rss(feeds, max_per_feed=max_per_query, language="en")


def fetch_gnews_rss_hindi(queries: list[str], max_per_query: int = 8) -> list[dict]:
    """Fetch from Google News RSS using Hindi language settings."""
    if not queries:
        return []
    feeds = [
        {
            "url": build_google_news_rss_url(q, hl="hi-IN", gl="IN", ceid="IN:hi"),
            "source": f"Google News Hindi ({q[:40]})",
        }
        for q in queries
    ]
    log.info("Fetching Google News RSS (Hindi) for %d queries…", len(queries))
    return fetch_rss(feeds, max_per_feed=max_per_query, language="hi")


# ---------------------------------------------------------------------------
# Junk filter. Astrology / horoscope columns, obvious ad placements, and
# articles that are basically the source masthead with no story attached.
# Kept conservative so genuine geopolitics content is never accidentally
# dropped, e.g. "war of the worlds" does not trip the horoscope rule.
# ---------------------------------------------------------------------------

# Terms that, when they appear in the title or the first sentence of the
# summary, almost always indicate a horoscope/numerology/vastu column.
_JUNK_TOPIC_TERMS = (
    # English astrology / self-help that is not news
    "horoscope", "zodiac sign", "your stars", "tarot", "numerology",
    "astrologer", "astrology", "vastu", "palmistry", "rashi fal",
    "daily prediction", "weekly prediction", "lucky number", "lucky colour",
    "lucky color",
    # Hindi astrology
    "राशिफल",  # rashifal
    "कुंडली",  # kundali
    "ज्योतिष",  # jyotish
    "भविष्यफल",  # bhavishyafal
    "वास्तु",  # vastu (shastra)
    "दैनिक राशि",  # daily rashi
    "साप्ताहिक राशि",  # weekly rashi
    "अंकज्योतिष",  # ankajyotish
    # Commerce / clickbait
    "best deal", "top deal", "coupon code", "discount code",
    "buy now", "shop now", "sale ends", "limited time offer",
    "affiliate link", "promoted content", "sponsored content",
    "sponsored post", "paid partnership", "advertorial",
    # Hindi commerce / promo
    "विज्ञापन",  # vigyapan = advertisement
    "प्रायोजित",  # prayojit = sponsored
    # Publisher aggregator/roundup boilerplate, e.g. "Read today's top news"
    # landing pages that some sites push through their RSS feed alongside real
    # stories. These read like SEO filler and not reporting.
    "समाचार पढ़ें और अपडेट रहें",  # "read news and stay updated"
    "ताजा और ब्रेकिंग न्यूज",  # "fresh and breaking news" (as exact phrase)
    "मुख्य और ताजा समाचार",  # "main and fresh news"
    "लाइव ब्रेकिंग न्यूज",  # "live breaking news"
    "लाइव अपडेट उपलब्ध",  # "live updates available"
    "पढ़ें आज की ताजा",  # "read today's fresh"
    "पढ़ें आज की ताज़ा",  # nuqta variant
    "read today's top news", "read today's breaking news",
    "latest news updates today", "top headlines today",
    "breaking news live updates", "stay updated with the latest",
)

# Hindi zodiac names. A standalone zodiac sign in the title is a horoscope
# tell; left as single-word hits because combinators like "मेष राशि"
# ("Aries zodiac") are what we actually want to catch.
_HINDI_ZODIAC_PAIR = (
    "मेष राशि", "वृषभ राशि",
    "मिथुन राशि", "कर्क राशि",
    "सिंह राशि", "कन्या राशि",
    "तुला राशि", "वृश्चिक राशि",
    "धनु राशि", "मकर राशि",
    "कुम्भ राशि", "मीन राशि",
)


def _junk_reason(art: dict) -> str:
    """Return a short reason code if the article is junk, else empty string.

    Reason codes: empty_title, topic (horoscope/ad/etc.), zodiac,
    roundup (publisher aggregator pages), source_equals_title,
    source_name_spam. The caller aggregates these so the workflow log shows
    exactly which rule is eating stories."""
    title = (art.get("title") or "").strip()
    summary = (art.get("description") or art.get("summary") or "").strip()
    source = (art.get("source") or "").strip()

    if not title:
        return "empty_title"

    blob = (title + "  " + summary[:200]).lower()
    for term in _JUNK_TOPIC_TERMS:
        if term in blob:
            return "topic"
    for pair in _HINDI_ZODIAC_PAIR:
        if pair in blob:
            return "zodiac"

    # Structural roundup detector. Real headlines report; aggregator landing
    # pages start with an imperative "Read"/"पढ़ें" followed by a date or
    # "today's"/"आज की" hook. We only fire when both signals coincide so a
    # genuine story like "Read why India abstained" is not caught.
    title_l = title.lower()
    starts_read_hi = title.startswith("\u092a\u095c\u0947\u0902 ") or title.startswith("\u092a\u0922\u093c\u0947\u0902 ")
    starts_read_en = title_l.startswith("read ")
    if starts_read_hi or starts_read_en:
        date_or_today_hi = (
            "\u0906\u091c \u0915\u0940 " in title or "\u0906\u091c \u0915\u093e " in title
            or re.search(r"\d{1,2}\s*(\u091c\u0928\u0935\u0930\u0940|\u092b\u0930\u0935\u0930\u0940|\u092e\u093e\u0930\u094d\u091a|\u0905\u092a\u094d\u0930\u0948\u0932|\u092e\u0908|\u091c\u0942\u0928|\u091c\u0941\u0932\u093e\u0908|\u0905\u0917\u0938\u094d\u0924|\u0938\u093f\u0924\u0902\u092c\u0930|\u0905\u0915\u094d\u091f\u0942\u092c\u0930|\u0928\u0935\u0902\u092c\u0930|\u0926\u093f\u0938\u0902\u092c\u0930)", title) is not None
        )
        date_or_today_en = (
            "today" in title_l or "today's" in title_l
            or re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}\b", title_l) is not None
            or re.search(r"\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b", title_l) is not None
        )
        if date_or_today_hi or date_or_today_en:
            return "roundup"

    if source:
        src_fold = source.casefold()
        title_fold = title.casefold()
        if title_fold == src_fold:
            return "source_equals_title"
        residual = title_fold.replace(src_fold, " ")
        residual = " ".join(residual.split())
        residual = residual.strip(" -|–—:,.").strip()
        junk_words = {"news", "live", "update", "updates", "latest",
                      "headlines", "breaking", "top", "today", "hindi",
                      "english", "world", "india", "report",
                      "समाचार", "ताज़ा",
                      "ब्रेकिंग", "लाइव", "हिंदी"}
        residual_tokens = [t for t in residual.split() if t]
        if not residual_tokens:
            return "source_name_spam"
        if all(t in junk_words for t in residual_tokens):
            return "source_name_spam"

    return ""


def _is_junk_article(art: dict) -> bool:
    """Return True when an article should be dropped before dedupe.

    Thin wrapper around _junk_reason kept for readability and backwards
    compatibility with callers that only want a boolean answer."""
    return bool(_junk_reason(art))


def deduplicate(articles: list[dict]) -> list[dict]:
    """Deduplicate by URL and near-duplicate titles."""
    seen_urls: set[str] = set()
    title_to_idx: dict[str, int] = {}
    unique: list[dict] = []
    junk_counts: dict[str, int] = {}
    junk_samples: dict[str, str] = {}
    url_dupes = 0
    title_dupes = 0
    incoming = len(articles)
    for art in articles:
        reason = _junk_reason(art)
        if reason:
            junk_counts[reason] = junk_counts.get(reason, 0) + 1
            if reason not in junk_samples:
                junk_samples[reason] = (art.get("title") or "")[:80]
            continue
        url = art["url"].rstrip("/")
        title_key = art["title"].lower()[:60]
        if not art["title"] or not art["url"]:
            continue
        if url in seen_urls:
            url_dupes += 1
            continue
        seen_urls.add(url)
        if title_key in title_to_idx:
            title_dupes += 1
            primary = unique[title_to_idx[title_key]]
            if not primary.get("sources"):
                primary["sources"] = [{"url": primary["url"], "source": primary["source"]}]
            primary["sources"].append({"url": url, "source": art["source"]})
        else:
            title_to_idx[title_key] = len(unique)
            unique.append(art)

    junk_total = sum(junk_counts.values())
    log.info(
        "Dedupe: incoming=%d kept=%d junk_dropped=%d url_dupes=%d title_dupes=%d",
        incoming, len(unique), junk_total, url_dupes, title_dupes,
    )
    if junk_total:
        breakdown = ", ".join(
            f"{reason}={count}" for reason, count in sorted(junk_counts.items(), key=lambda x: -x[1])
        )
        log.info("Junk filter breakdown: %s", breakdown)
        for reason, sample in junk_samples.items():
            log.info("  junk[%s] sample: %r", reason, sample)
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
                    "title": truncate_title(_decode_entities(title)),
                    "url": url,
                    "source": _decode_entities(art.get("source", f"{_GP_SITE_TITLE_FALLBACK} Archive")),
                    "published_at": art.get("published_at", ""),
                    "description": _decode_entities(art.get("summary") or title)[:400],
                    "image_url": art.get("image_url", ""),
                    "language": art.get("language", "en"),
                }
            )
        return previous[:max_articles]
    except Exception as exc:
        log.warning("Unable to load previous newsletter fallback: %s", exc)
        return []


def main() -> None:
    cfg = load_config()
    sources = cfg.get("news_sources", ["rss"])
    query = cfg["news_query"]
    max_articles = cfg["max_articles"]

    # Threshold below which fallback feeds kick in (per language).
    low_water_mark = max(5, max_articles // 4)

    en_articles: list[dict] = []
    hi_articles: list[dict] = []

    # ── English: Primary RSS ──────────────────────────────────────────────────
    if "rss" in sources:
        en_feeds = cfg.get("english_rss_feeds", cfg.get("rss_feeds", []))
        en_articles.extend(_tag_language(fetch_rss(en_feeds, max_per_feed=10, language="en"), "en"))

    # ── English: NewsAPI (optional, key required) ─────────────────────────────
    if "newsapi" in sources:
        api_key = os.environ.get("NEWSAPI_KEY", "")
        if api_key:
            en_articles.extend(_tag_language(fetch_newsapi(query, api_key, max_articles), "en"))
        else:
            log.warning("newsapi source enabled but NEWSAPI_KEY not set — skipping.")

    # ── English: Audience hooks ───────────────────────────────────────────────
    if cfg.get("audience_hooks_enabled", True):
        hook_feeds = build_audience_hook_feeds(cfg)
        hook_cap = int(cfg.get("audience_hooks_max_per_feed", 3))
        if hook_feeds:
            log.info("Fetching English audience hooks from %d feeds...", len(hook_feeds))
            en_articles.extend(_tag_language(fetch_rss(hook_feeds, max_per_feed=hook_cap, language="en"), "en"))

    # ── English: Google News RSS ──────────────────────────────────────────────
    en_gnews = cfg.get("english_gnews_queries", cfg.get("gnews_rss_queries", []))
    if en_gnews:
        en_articles.extend(_tag_language(fetch_gnews_rss(en_gnews, max_per_query=8), "en"))

    # ── Hindi: Primary RSS ────────────────────────────────────────────────────
    if "rss" in sources:
        hi_feeds = cfg.get("hindi_rss_feeds", [])
        if hi_feeds:
            hi_articles.extend(_tag_language(fetch_rss(hi_feeds, max_per_feed=10, language="hi"), "hi"))

    # ── Hindi: Google News RSS ────────────────────────────────────────────────
    hi_gnews = cfg.get("hindi_gnews_queries", [])
    if hi_gnews:
        hi_articles.extend(_tag_language(fetch_gnews_rss_hindi(hi_gnews, max_per_query=8), "hi"))

    # ── English fallback (only triggers if primary set is very thin) ──────────
    unique_en = deduplicate(en_articles)
    if len(unique_en) < low_water_mark:
        en_fallback = cfg.get("english_fallback_rss_feeds", cfg.get("fallback_rss_feeds", []))
        if en_fallback:
            log.warning(
                "English: only %d unique articles (threshold %d); pulling fallback feeds…",
                len(unique_en), low_water_mark,
            )
            en_articles.extend(_tag_language(fetch_rss(en_fallback, max_per_feed=10, language="en"), "en"))

    # ── Hindi fallback (only triggers if primary set is very thin) ────────────
    unique_hi = deduplicate(hi_articles)
    if len(unique_hi) < low_water_mark:
        hi_fallback = cfg.get("hindi_fallback_rss_feeds", [])
        if hi_fallback:
            log.warning(
                "Hindi: only %d unique articles (threshold %d); pulling fallback feeds…",
                len(unique_hi), low_water_mark,
            )
            hi_articles.extend(_tag_language(fetch_rss(hi_fallback, max_per_feed=10, language="hi"), "hi"))

    # ── Combine and deduplicate (within-language dedup already done above) ────
    all_articles = en_articles + hi_articles
    unique = deduplicate(all_articles)
    total_unique_count = len(unique)
    published_articles = unique

    # ── Last-resort fallback: re-use previous newsletter articles ─────────────
    if not published_articles:
        log.warning("No unique articles available; falling back to previous newsletter stories.")
        published_articles = load_previous_articles(max_articles)
        total_unique_count = len(published_articles)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "article_count": len(published_articles),
        "total_unique_count": total_unique_count,
        "articles": published_articles,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info(
        "Wrote %s (article_count=%d, total_unique_count=%d)",
        OUTPUT_PATH, len(published_articles), total_unique_count,
    )


if __name__ == "__main__":
    main()
