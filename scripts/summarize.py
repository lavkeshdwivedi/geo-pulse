#!/usr/bin/env python3
"""
summarize.py — Reads raw_news.json and writes:
  - newsletter.json  (structured per-article data with up to 100-word summaries)
  - newsletter.md    (markdown archive copy)

Each article gets a summary that ends when the story is complete, capped at 100 words.

LLM providers (set LLM_PROVIDER env var):
  none        — truncate description to 100 words, no AI  (default, no key needed)
  openai      — OpenAI GPT-4o-mini  (requires OPENAI_API_KEY)
  anthropic   — Anthropic Claude    (requires ANTHROPIC_API_KEY)
  huggingface — HuggingFace BART    (requires HF_API_KEY or works anonymously)
"""

import json
import html
import logging
import os
import re
import textwrap
from datetime import datetime, timezone

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yml")
STYLE_PATH  = os.path.join(ROOT, "STYLE.md")
INPUT_PATH  = os.path.join(ROOT, "raw_news.json")
JSON_PATH   = os.path.join(ROOT, "newsletter.json")
MD_PATH     = os.path.join(ROOT, "newsletter.md")

BASE_URL = "https://pulse.lavkesh.com"


def decode_entities(text: str) -> str:
    """Decode HTML entities, handling double-encoded content from feeds."""
    if not text:
        return ""
    current = text
    for _ in range(3):
        decoded = html.unescape(current)
        if decoded == current:
            break
        current = decoded
    return re.sub(r"\s+", " ", current).strip()


def normalize_article_text(article: dict) -> dict:
    """Return an article with textual fields normalized for output and prompts."""
    normalized_sources = []
    for src in article.get("sources", []) or []:
        normalized_sources.append({
            "url": src.get("url", ""),
            "source": decode_entities(src.get("source", "")),
        })

    return {
        **article,
        "title": decode_entities(article.get("title", "")),
        "description": decode_entities(article.get("description", "")),
        "source": decode_entities(article.get("source", "")),
        "sources": normalized_sources,
    }


def load_style_guide() -> str:
    """Load the editorial style guide from STYLE.md at the repo root."""
    try:
        with open(STYLE_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        log.warning("STYLE.md not found at %s — using empty style guide.", STYLE_PATH)
        return ""

# ── Region keyword map ────────────────────────────────────────────────────────
REGION_KEYWORDS: dict[str, list[str]] = {
    "Middle East & Africa": [
        "israel", "palestine", "gaza", "iran", "saudi", "yemen", "syria",
        "iraq", "lebanon", "egypt", "africa", "sudan", "ethiopia", "libya",
    ],
    "Europe & Russia": [
        "ukraine", "russia", "nato", "european union", "france",
        "germany", " uk ", "britain", "poland", "sweden", "finland", "baltics",
    ],
    "Asia-Pacific": [
        "china", "taiwan", "japan", "korea", "india", "pakistan",
        "south china sea", "asean", "indo-pacific", "australia",
    ],
    "Americas": [
        "united states", " us ", "usa", "biden", "trump", "canada",
        "mexico", "brazil", "venezuela", "latin america",
    ],
    "Global / Multilateral": [
        "united nations", " un ", "g7", "g20", "wto", "imf", "sanctions",
        "diplomacy", "geopolitics", "international",
    ],
}

GENRE_KEYWORDS: dict[str, list[str]] = {
    "World History": [
        "anniversary", "archive", "historic", "historical", "centenary",
        "declassified", "world war", "cold war", "partition", "empire",
        "memorial", "legacy",
    ],
    "Geography": [
        "strait", "border", "island", "coast", "ocean", "sea", "river",
        "mountain", "desert", "arctic", "terrain", "maritime", "hormuz",
    ],
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg["llm_provider"] = os.environ.get("LLM_PROVIDER", cfg.get("llm_provider", "none")).lower()
    cfg["llm_model"]    = os.environ.get("LLM_MODEL",    cfg.get("llm_model", "gpt-4o-mini"))
    return cfg


def classify_region(article: dict) -> str:
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for region, keywords in REGION_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return region
    return "World"


def classify_genre(article: dict) -> str:
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for genre, keywords in GENRE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return genre
    return "Geopolitics"


def truncate_words(text: str, limit: int = 100) -> str:
    """Keep whole sentences up to `limit` words. Stop when the story is done.
    If no complete sentence fits within the limit, hard-cut at the limit."""
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    result = []
    count = 0
    for s in sentences:
        wc = len(s.split())
        if count + wc > limit:
            break
        result.append(s)
        count += wc
    if not result:
        words = text.split()
        return " ".join(words[:limit])
    return " ".join(result)


# ── LLM helpers ───────────────────────────────────────────────────────────────

# Loaded once at import time so every call in this process uses the same guide.
_STYLE_GUIDE = load_style_guide()


def _inshorts_prompt(title: str, description: str) -> str:
    return textwrap.dedent(f"""
        {_STYLE_GUIDE}

        Story title: {title}
        Details: {description}

        Write the summary now.
    """).strip()


def summarise_batch_openai(articles: list[dict], model: str) -> list[str]:
    import openai
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    summaries = []
    for art in articles:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": _inshorts_prompt(
                    art.get("title", ""), art.get("description", ""))}],
                max_tokens=160,
                temperature=0.3,
            )
            summaries.append(resp.choices[0].message.content.strip())
        except Exception as exc:
            log.warning("OpenAI failed for '%s': %s", art.get("title", "")[:40], exc)
            summaries.append(truncate_words(art.get("description", art.get("title", ""))))
    return summaries


def summarise_batch_anthropic(articles: list[dict], model: str) -> list[str]:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    summaries = []
    for art in articles:
        try:
            resp = client.messages.create(
                model=model or "claude-3-haiku-20240307",
                max_tokens=160,
                messages=[{"role": "user", "content": _inshorts_prompt(
                    art.get("title", ""), art.get("description", ""))}],
            )
            summaries.append(resp.content[0].text.strip())
        except Exception as exc:
            log.warning("Anthropic failed for '%s': %s", art.get("title", "")[:40], exc)
            summaries.append(truncate_words(art.get("description", art.get("title", ""))))
    return summaries


def summarise_batch_huggingface(articles: list[dict]) -> list[str]:
    import requests as req
    api_key = os.environ.get("HF_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    summaries = []
    for art in articles:
        text = (art.get("title", "") + ". " + art.get("description", ""))[:1000]
        try:
            resp = req.post(
                url, headers=headers,
                json={"inputs": text, "parameters": {"max_length": 130, "min_length": 30}},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            summary = data[0].get("summary_text", "") if isinstance(data, list) else ""
            summaries.append(truncate_words(summary) if summary else
                             truncate_words(art.get("description", art.get("title", ""))))
        except Exception as exc:
            log.warning("HuggingFace failed for '%s': %s", art.get("title", "")[:40], exc)
            summaries.append(truncate_words(art.get("description", art.get("title", ""))))
    return summaries


# ── Markdown archive builder ──────────────────────────────────────────────────

def build_markdown(enriched: list[dict], generated_at: str) -> str:
    try:
        dt = datetime.fromisoformat(generated_at)
        date_str = dt.strftime("%B %d, %Y %H:%M UTC")
    except ValueError:
        date_str = generated_at

    lines = [
        "# 🌍 GeoPulse Newsletter",
        "",
        f"**Updated:** {date_str}",
        "",
        "---",
        "",
    ]

    # Group by region for the markdown view
    regions: dict[str, list[dict]] = {}
    for art in enriched:
        regions.setdefault(art["region"], []).append(art)

    for region, arts in regions.items():
        lines += [f"## {region}", ""]
        for art in arts:
            pub = art.get("published_at", "")
            try:
                pub_str = datetime.fromisoformat(
                    pub.replace("Z", "+00:00")).strftime("%b %d, %H:%M UTC")
            except Exception:
                pub_str = pub[:16]
            lines += [
                f"### [{art['title']}]({art['url']})",
                f"*{art['source']}* — {pub_str}",
                "",
                art["summary"],
                "",
            ]
        lines += ["---", ""]

    lines.append("*GeoPulse — automated geopolitics digest. Hosted at pulse.lavkesh.com*")
    lines.append("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg      = load_config()
    provider = cfg["llm_provider"]
    model    = cfg["llm_model"]

    if not os.path.exists(INPUT_PATH):
        log.error("raw_news.json not found at %s. Run fetch_news.py first.", INPUT_PATH)
        raise SystemExit(1)

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    articles: list[dict] = [normalize_article_text(a) for a in data.get("articles", [])]
    fetched_at: str = data.get("fetched_at", datetime.now(timezone.utc).isoformat())

    if not articles:
        log.warning("No articles found — writing empty newsletter.")
        empty = {
            "generated_at": fetched_at,
            "article_count": 0,
            "articles": [],
        }
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)
        with open(MD_PATH, "w", encoding="utf-8") as f:
            f.write(f"# 🌍 GeoPulse Newsletter\n\n**Updated:** {fetched_at}\n\n"
                    "_No articles were available for this edition._\n")
        return

    # ── Generate summaries ────────────────────────────────────────────────────
    log.info("Generating summaries for %d articles. Provider: %s", len(articles), provider)

    try:
        if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
            summaries = summarise_batch_openai(articles, model)
        elif provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            summaries = summarise_batch_anthropic(articles, model)
        elif provider == "huggingface":
            summaries = summarise_batch_huggingface(articles)
        else:
            if provider not in ("none", ""):
                log.warning("Provider '%s' key missing or unknown — using truncation.", provider)
            summaries = [
                truncate_words(decode_entities(a.get("description") or a.get("title", "")))
                for a in articles
            ]
    except Exception as exc:
        log.error("Summarisation error: %s — falling back to truncation.", exc)
        summaries = [
            truncate_words(decode_entities(a.get("description") or a.get("title", "")))
            for a in articles
        ]

    # ── Enrich articles ───────────────────────────────────────────────────────
    enriched: list[dict] = []
    for art, summary in zip(articles, summaries):
        enriched.append({
            "title":        decode_entities(art.get("title", "")),
            "url":          art.get("url", ""),
            "source":       decode_entities(art.get("source", "")),
            "sources":      art.get("sources", []),
            "published_at": art.get("published_at", ""),
            "image_url":    art.get("image_url", ""),
            "summary":      decode_entities(summary),
            "region":       classify_region(art),
            "genre":        classify_genre(art),
        })

    # ── Write newsletter.json ─────────────────────────────────────────────────
    output = {
        "generated_at":  fetched_at,
        "article_count": len(enriched),
        "articles":      enriched,
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info("Wrote %s (%d articles)", JSON_PATH, len(enriched))

    # ── Write newsletter.md (archive copy) ───────────────────────────────────
    md = build_markdown(enriched, fetched_at)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    log.info("Wrote %s", MD_PATH)


if __name__ == "__main__":
    main()

