#!/usr/bin/env python3
"""
summarize.py — Reads raw_news.json and writes newsletter.md.

LLM providers supported (set LLM_PROVIDER env var):
  none        — formatted digest only, no AI summary (default, no key needed)
  openai      — OpenAI GPT-4o-mini (requires OPENAI_API_KEY)
  anthropic   — Anthropic Claude (requires ANTHROPIC_API_KEY)
  huggingface — HuggingFace Inference API (requires HF_API_KEY)
"""

import json
import logging
import os
import textwrap
from datetime import datetime, timezone
from typing import Optional

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yml")
INPUT_PATH = os.path.join(ROOT, "raw_news.json")
OUTPUT_PATH = os.path.join(ROOT, "newsletter.md")

# Geopolitical region keywords for basic clustering
REGION_KEYWORDS: dict[str, list[str]] = {
    "Middle East & Africa": [
        "israel", "palestine", "gaza", "iran", "saudi", "yemen", "syria",
        "iraq", "lebanon", "egypt", "africa", "sudan", "ethiopia", "libya",
    ],
    "Europe & Russia": [
        "ukraine", "russia", "nato", "eu ", "european union", "france",
        "germany", "uk ", "britain", "poland", "sweden", "finland", "baltics",
    ],
    "Asia-Pacific": [
        "china", "taiwan", "japan", "korea", "india", "pakistan",
        "south china sea", "asean", "indo-pacific", "australia",
    ],
    "Americas": [
        "united states", "us ", "usa", " us ", "biden", "trump", "canada",
        "mexico", "brazil", "venezuela", "latin america",
    ],
    "Global / Multilateral": [
        "united nations", "un ", "g7", "g20", "wto", "imf", "sanctions",
        "diplomacy", "geopolitics", "international",
    ],
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg["llm_provider"] = os.environ.get("LLM_PROVIDER", cfg.get("llm_provider", "none")).lower()
    cfg["llm_model"] = os.environ.get("LLM_MODEL", cfg.get("llm_model", "gpt-4o-mini"))
    return cfg


def cluster_articles(articles: list[dict]) -> dict[str, list[dict]]:
    """Group articles into regional buckets by keyword matching."""
    clusters: dict[str, list[dict]] = {region: [] for region in REGION_KEYWORDS}
    clusters["Other"] = []

    for art in articles:
        text = (art.get("title", "") + " " + art.get("description", "")).lower()
        assigned = False
        for region, keywords in REGION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                clusters[region].append(art)
                assigned = True
                break
        if not assigned:
            clusters["Other"].append(art)

    # Remove empty clusters
    return {k: v for k, v in clusters.items() if v}


def format_digest(clusters: dict[str, list[dict]], fetched_at: str) -> str:
    """Build newsletter.md without LLM — clean formatted digest."""
    try:
        dt = datetime.fromisoformat(fetched_at)
        date_str = dt.strftime("%B %d, %Y %H:%M UTC")
    except ValueError:
        date_str = fetched_at

    lines = [
        f"# 🌍 GeoPulse Newsletter",
        f"",
        f"**Updated:** {date_str}",
        f"",
        f"---",
        f"",
    ]

    total = sum(len(v) for v in clusters.values())
    lines += [
        f"## Overview",
        f"",
        f"This edition covers **{total} stories** across {len(clusters)} regions.",
        f"",
        f"---",
        f"",
    ]

    for region, articles in clusters.items():
        lines.append(f"## {region}")
        lines.append("")
        for art in articles:
            title = art.get("title", "No title")
            url = art.get("url", "")
            source = art.get("source", "Unknown")
            description = art.get("description", "")
            published = art.get("published_at", "")
            # Format date
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                pub_str = pub_dt.strftime("%b %d, %H:%M UTC")
            except Exception:
                pub_str = published[:16] if published else ""

            lines.append(f"### [{title}]({url})")
            lines.append(f"*{source}* — {pub_str}")
            lines.append("")
            if description:
                lines.append(f"> {description.strip()}")
                lines.append("")

        lines.append("---")
        lines.append("")

    lines.append("*GeoPulse is an automated geopolitics newsletter powered by GitHub Actions.*")
    lines.append("")
    return "\n".join(lines)


def summarize_with_openai(clusters: dict[str, list[dict]], model: str, fetched_at: str) -> str:
    """Use OpenAI to generate AI-powered summaries."""
    import openai

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    try:
        dt = datetime.fromisoformat(fetched_at)
        date_str = dt.strftime("%B %d, %Y %H:%M UTC")
    except ValueError:
        date_str = fetched_at

    lines = [
        "# 🌍 GeoPulse Newsletter",
        "",
        f"**Updated:** {date_str}",
        "",
        "---",
        "",
    ]

    for region, articles in clusters.items():
        article_text = "\n".join(
            f"- {a['title']}: {a.get('description', '')} ({a.get('source', '')})"
            for a in articles
        )
        prompt = textwrap.dedent(f"""
            You are a geopolitics analyst writing a concise newsletter section.
            Region: {region}
            Articles:
            {article_text}

            Write a 2-3 sentence executive summary of the key developments in this region,
            followed by a "Key Takeaway" sentence. Be factual and neutral.
        """).strip()

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
            )
            summary = resp.choices[0].message.content.strip()
        except Exception as exc:
            log.warning("OpenAI summarization failed for %s: %s", region, exc)
            summary = "_AI summary unavailable for this section._"

        lines.append(f"## {region}")
        lines.append("")
        lines.append(summary)
        lines.append("")

        for art in articles:
            title = art.get("title", "")
            url = art.get("url", "")
            source = art.get("source", "")
            lines.append(f"- [{title}]({url}) — *{source}*")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*GeoPulse is an automated geopolitics newsletter powered by GitHub Actions.*")
    lines.append("")
    return "\n".join(lines)


def summarize_with_anthropic(clusters: dict[str, list[dict]], model: str, fetched_at: str) -> str:
    """Use Anthropic Claude to generate AI-powered summaries."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        dt = datetime.fromisoformat(fetched_at)
        date_str = dt.strftime("%B %d, %Y %H:%M UTC")
    except ValueError:
        date_str = fetched_at

    lines = [
        "# 🌍 GeoPulse Newsletter",
        "",
        f"**Updated:** {date_str}",
        "",
        "---",
        "",
    ]

    for region, articles in clusters.items():
        article_text = "\n".join(
            f"- {a['title']}: {a.get('description', '')} ({a.get('source', '')})"
            for a in articles
        )
        prompt = textwrap.dedent(f"""
            You are a geopolitics analyst writing a concise newsletter section.
            Region: {region}
            Articles:
            {article_text}

            Write a 2-3 sentence executive summary of the key developments in this region,
            followed by a "Key Takeaway" sentence. Be factual and neutral.
        """).strip()

        try:
            resp = client.messages.create(
                model=model or "claude-3-haiku-20240307",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = resp.content[0].text.strip()
        except Exception as exc:
            log.warning("Anthropic summarization failed for %s: %s", region, exc)
            summary = "_AI summary unavailable for this section._"

        lines.append(f"## {region}")
        lines.append("")
        lines.append(summary)
        lines.append("")
        for art in articles:
            title = art.get("title", "")
            url = art.get("url", "")
            source = art.get("source", "")
            lines.append(f"- [{title}]({url}) — *{source}*")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*GeoPulse is an automated geopolitics newsletter powered by GitHub Actions.*")
    lines.append("")
    return "\n".join(lines)


def summarize_with_huggingface(clusters: dict[str, list[dict]], fetched_at: str) -> str:
    """Use HuggingFace Inference API for summarization."""
    import requests as req

    api_key = os.environ.get("HF_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    model_url = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"

    try:
        dt = datetime.fromisoformat(fetched_at)
        date_str = dt.strftime("%B %d, %Y %H:%M UTC")
    except ValueError:
        date_str = fetched_at

    lines = [
        "# 🌍 GeoPulse Newsletter",
        "",
        f"**Updated:** {date_str}",
        "",
        "---",
        "",
    ]

    for region, articles in clusters.items():
        article_text = " ".join(
            f"{a['title']}. {a.get('description', '')}"
            for a in articles
        )[:1024]  # BART input limit

        summary = "_AI summary unavailable._"
        try:
            resp = req.post(
                model_url,
                headers=headers,
                json={"inputs": article_text, "parameters": {"max_length": 150, "min_length": 40}},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                summary = data[0].get("summary_text", summary)
        except Exception as exc:
            log.warning("HuggingFace summarization failed for %s: %s", region, exc)

        lines.append(f"## {region}")
        lines.append("")
        lines.append(summary)
        lines.append("")
        for art in articles:
            title = art.get("title", "")
            url = art.get("url", "")
            source = art.get("source", "")
            lines.append(f"- [{title}]({url}) — *{source}*")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*GeoPulse is an automated geopolitics newsletter powered by GitHub Actions.*")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    cfg = load_config()
    provider = cfg["llm_provider"]
    model = cfg["llm_model"]

    if not os.path.exists(INPUT_PATH):
        log.error("raw_news.json not found at %s. Run fetch_news.py first.", INPUT_PATH)
        raise SystemExit(1)

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    articles: list[dict] = data.get("articles", [])
    fetched_at: str = data.get("fetched_at", datetime.now(timezone.utc).isoformat())

    if not articles:
        log.warning("No articles found in raw_news.json. Writing empty newsletter.")
        content = (
            "# 🌍 GeoPulse Newsletter\n\n"
            f"**Updated:** {fetched_at}\n\n"
            "_No articles were available for this edition._\n"
        )
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        return

    clusters = cluster_articles(articles)
    log.info("Clustered into %d regions. Provider: %s", len(clusters), provider)

    try:
        if provider == "openai":
            if not os.environ.get("OPENAI_API_KEY"):
                log.warning("OPENAI_API_KEY not set — falling back to digest mode.")
                content = format_digest(clusters, fetched_at)
            else:
                content = summarize_with_openai(clusters, model, fetched_at)

        elif provider == "anthropic":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                log.warning("ANTHROPIC_API_KEY not set — falling back to digest mode.")
                content = format_digest(clusters, fetched_at)
            else:
                content = summarize_with_anthropic(clusters, model, fetched_at)

        elif provider == "huggingface":
            content = summarize_with_huggingface(clusters, fetched_at)

        else:
            if provider != "none":
                log.warning("Unknown LLM_PROVIDER '%s' — using digest mode.", provider)
            content = format_digest(clusters, fetched_at)

    except Exception as exc:
        log.error("LLM summarization raised an unexpected error: %s. Falling back to digest.", exc)
        content = format_digest(clusters, fetched_at)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("Newsletter written to %s (%d chars)", OUTPUT_PATH, len(content))


if __name__ == "__main__":
    main()
