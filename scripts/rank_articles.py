#!/usr/bin/env python3
"""
rank_articles.py — LLM-based ranker that trims raw_news.json down to the most
newsworthy stories before summarize.py spends LLM tokens on each one.

Pipeline position
-----------------
fetch_news.py   →  raw_news.json   (50-150 stories)
rank_articles.py →  raw_news.json   (top N stories, this script)
summarize.py    →  newsletter.json (LLM summaries for the top N)

Why
---
Summarization is the most expensive step (one LLM call per story, plus a
translation call for Hindi). Ranking lets us spend that budget on the
stories that actually matter for a global affairs front page, instead of
shovelling the freshest 50 stories — many of them sports highlights or
local feature pieces — into the summarizer.

How it works
------------
1. Load raw_news.json
2. Group articles by language (English and Hindi) so each language gets its
   own ranking call (cheaper context, better signal-to-noise per group)
3. Build a compact ranking prompt: numbered list of {title, source, region,
   description-first-line}
4. One LLM call per language returns a JSON array of top-N indices, ranked
5. Reorder articles by the LLM's pick and write back the trimmed file

Falls back gracefully
---------------------
- No LLM keys → keep the original date-sorted ordering, just trim to keep_top
- LLM returns garbage → log + keep original ordering
- LLM picks fewer than keep_top → fill remainder from the unpicked, by date

Tunables (env)
--------------
RANKER_KEEP_TOP    int, default 35. How many articles per language to keep.
RANKER_DISABLE     "1" to skip ranking entirely (date sort + trim only)
RANKER_MAX_INPUT   int, default 80. Cap raw input fed to the LLM per call.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

# Local imports — same script directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import llm_complete, any_key_present

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("rank_articles")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_PATH = os.path.join(ROOT, "raw_news.json")

KEEP_TOP_DEFAULT = int(os.environ.get("RANKER_KEEP_TOP", "35"))
MAX_INPUT_DEFAULT = int(os.environ.get("RANKER_MAX_INPUT", "80"))
DISABLED = os.environ.get("RANKER_DISABLE") == "1"


SYSTEM_PROMPT = (
    "You are a senior geopolitics editor curating a global affairs front page. "
    "Given a numbered list of news items (title, source, region, lede), pick "
    "the top {keep_top} items most worth running on the page right now.\n\n"
    "Prioritize:\n"
    "- Cross-border conflicts, military escalations, ceasefires, peace talks\n"
    "- Major elections, government changes, sanctions, trade actions\n"
    "- Macroeconomic shifts that move global markets (oil, rates, currencies)\n"
    "- Diplomatic moves between major powers (US, China, EU, Russia, India)\n"
    "- Humanitarian crises and large-scale displacement\n"
    "- Energy, supply chain, and infrastructure stories with global ripple\n\n"
    "De-prioritize:\n"
    "- Local sports, celebrity news, lifestyle, religion (unless globally relevant)\n"
    "- Opinion columns and editorials\n"
    "- Near-duplicate coverage of the same story (pick the most authoritative)\n"
    "- Pure tech/product launches with no geopolitical angle\n\n"
    "Return ONLY a JSON array of integer indices (0-based), top item first. "
    "Exactly {keep_top} indices, no commentary, no markdown fencing. Example: "
    "[12, 3, 45, 7, 22, ...]"
)


def _short(text, n=140):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:n]


def _build_user_prompt(articles, keep_top):
    lines = []
    for i, art in enumerate(articles):
        title = _short(art.get("title", ""), 160)
        source = _short(art.get("source", ""), 40)
        region = _short(art.get("region", "World"), 30)
        desc = _short(art.get("description", ""), 220)
        lines.append(f"[{i}] {title} — {source} ({region}) :: {desc}")
    return (
        f"Pick the top {keep_top} indices from the {len(articles)} items below. "
        "Return ONLY a JSON array of integers, e.g. [3, 7, 12, ...].\n\n"
        + "\n".join(lines)
    )


def _parse_indices(text, n_total, keep_top):
    """Extract the integer list from the LLM response. Tolerant of extra text."""
    if not text:
        return []
    # Strip code fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Pick the first JSON array in the response
    m = re.search(r"\[[\d,\s]+\]", text)
    if not m:
        return []
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    seen = set()
    picked = []
    for v in raw:
        try:
            idx = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < n_total and idx not in seen:
            seen.add(idx)
            picked.append(idx)
        if len(picked) >= keep_top:
            break
    return picked


def _date_sort(articles):
    return sorted(articles, key=lambda a: a.get("published_at", ""), reverse=True)


def rank_group(articles, keep_top, label):
    """Return up to `keep_top` articles for a language group, ranked."""
    if not articles:
        return []
    if len(articles) <= keep_top:
        log.info("[%s] %d items, fits under cap %d — returning as-is", label, len(articles), keep_top)
        return _date_sort(articles)
    # Cap input so the prompt stays manageable on free-tier models
    max_input = min(len(articles), MAX_INPUT_DEFAULT)
    pool = _date_sort(articles)[:max_input]

    if DISABLED or not any_key_present():
        log.info("[%s] LLM ranker disabled or no key — falling back to date-sort top %d", label, keep_top)
        return pool[:keep_top]

    system = SYSTEM_PROMPT.format(keep_top=keep_top)
    user = _build_user_prompt(pool, keep_top)
    log.info("[%s] ranking %d items down to top %d via LLM", label, len(pool), keep_top)
    raw = llm_complete(
        system_prompt=system,
        user_prompt=user,
        max_tokens=400,
        temperature=0.1,
    )
    indices = _parse_indices(raw, len(pool), keep_top)
    if not indices:
        log.warning("[%s] LLM returned no usable indices, falling back to date-sort", label)
        return pool[:keep_top]
    log.info("[%s] LLM picked %d indices (first 10: %s)", label, len(indices), indices[:10])
    picked = [pool[i] for i in indices]
    # Pad with unpicked, oldest-first preference dropped — top up by date so
    # the page still has enough stories if LLM picked fewer than keep_top
    if len(picked) < keep_top:
        used = set(id(p) for p in picked)
        leftovers = [a for a in pool if id(a) not in used]
        picked.extend(leftovers[: keep_top - len(picked)])
    return picked


def main():
    if not os.path.exists(INPUT_PATH):
        log.error("raw_news.json not found at %s. Run fetch_news.py first.", INPUT_PATH)
        raise SystemExit(1)

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    articles = data.get("articles", [])
    if not articles:
        log.info("raw_news.json is empty, nothing to rank")
        return

    en_pool = [a for a in articles if a.get("language", "en") != "hi"]
    hi_pool = [a for a in articles if a.get("language") == "hi"]
    log.info(
        "Loaded %d articles (%d English, %d Hindi). Cap per language: %d",
        len(articles), len(en_pool), len(hi_pool), KEEP_TOP_DEFAULT,
    )

    en_top = rank_group(en_pool, KEEP_TOP_DEFAULT, "EN")
    hi_top = rank_group(hi_pool, KEEP_TOP_DEFAULT, "HI")

    trimmed = en_top + hi_top
    data["articles"] = trimmed
    data["ranked_at"] = datetime.now(timezone.utc).isoformat()
    data["ranked_total"] = len(trimmed)
    data["ranked_input_count"] = len(articles)

    with open(INPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(
        "Wrote ranked raw_news.json: %d English + %d Hindi = %d total (was %d)",
        len(en_top), len(hi_top), len(trimmed), len(articles),
    )


if __name__ == "__main__":
    main()
