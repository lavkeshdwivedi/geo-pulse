"""Central language registry.

Every language-specific piece of configuration for geo-pulse lives here.
Adding a new language is meant to be a one-block change in this file plus
an RSS source addition in fetch_news.py. Downstream scripts
(summarize.py, generate_site.py) read from LANGUAGES rather than hard-coding
"en" vs "hi" branches.

To add a new language (e.g. Spanish "es"):

    1. Append an "es" entry to LANGUAGES below with all required keys.
    2. Add Spanish RSS feeds / source URLs in scripts/fetch_news.py under
       your feed config so articles get language="es" in raw_news.json.
    3. Add keyword variants in Spanish to REGION_KEYWORDS in
       scripts/summarize.py (country names, capitals, leaders).
    4. Redeploy. The site will pick up a /es/ subdirectory, filter pills,
       archive pages, and a language switcher entry automatically.

The ordering in LANGUAGES controls the language-switcher order in the UI.
English is first so the canonical routes (/, /newsletters/, /feed.xml)
stay at the root. Any other language renders under its subdir (/hi/, /es/,
etc).
"""

from __future__ import annotations

from typing import Callable, TypedDict


class LangConfig(TypedDict, total=False):
    code: str                              # ISO-ish short code ("en", "hi")
    display_name: str                      # shown in language switcher
    is_default: bool                       # True for the root-served language
    site_subdir: str                       # "" for root, "hi" for /hi/, etc.
    md_filename: str                       # per-language markdown archive filename
    all_label: str                         # "All" / "सभी" / "Todo"
    digest_label: str                      # "Editor's note" heading
    filter_aria: str                       # ARIA label on the filter tablist
    empty_filter: str                      # message when no stories match filter
    region_labels: dict[str, str]          # canonical English -> localized label
    script_tag: str                        # "latin", "devanagari", "arabic", ...
    # Script guardrail: returns True if the text reads as this language's
    # script. Used by generate_site.py to reject cross-language bleed.
    script_dominant_check: Callable[[str], bool] | None


# ──────────────────────────────────────────────────────────────────────────────
# Script dominance helpers. Lazy-imported in the checks to avoid pulling
# heavy deps from summarize.py. Keep these tiny and self-contained.
# ──────────────────────────────────────────────────────────────────────────────

def _latin_dominant(text: str, threshold: float = 0.30) -> bool:
    if not text:
        return False
    total = sum(1 for ch in text if ch.isalpha())
    if total == 0:
        return False
    latin = sum(1 for ch in text if ch.isalpha() and ord(ch) < 0x0250)
    return (latin / total) >= threshold


def _devanagari_dominant(text: str, threshold: float = 0.30) -> bool:
    if not text:
        return False
    total = sum(1 for ch in text if ch.isalpha())
    if total == 0:
        return False
    dev = sum(1 for ch in text if 0x0900 <= ord(ch) <= 0x097F)
    return (dev / total) >= threshold


# Canonical ordered list of language codes. First entry is the root-served
# language; everything else gets a /{code}/ subdirectory.
LANGUAGES: dict[str, LangConfig] = {
    "en": {
        "code": "en",
        "display_name": "English",
        "is_default": True,
        "site_subdir": "",
        "md_filename": "newsletter.md",
        "all_label": "All",
        "digest_label": "Editor's note",
        "filter_aria": "Filter by region",
        "empty_filter": "No stories match this region right now.",
        "script_tag": "latin",
        "script_dominant_check": _latin_dominant,
        # English uses the canonical region names as-is so the map is
        # identity. Kept here so downstream code does not need to special-
        # case EN — it can always go through LANGUAGES[lang]["region_labels"].
        "region_labels": {
            "Middle East & Africa": "Middle East & Africa",
            "Europe & Russia": "Europe & Russia",
            "Asia-Pacific": "Asia-Pacific",
            "Americas": "Americas",
            "Global / Multilateral": "Global / Multilateral",
            "World": "World",
        },
    },
    "hi": {
        "code": "hi",
        "display_name": "हिंदी",
        "is_default": False,
        "site_subdir": "hi",
        "md_filename": "newsletter.hi.md",
        "all_label": "सभी",
        "digest_label": "संपादकीय नोट",
        "filter_aria": "क्षेत्र के अनुसार फ़िल्टर करें",
        "empty_filter": "इस समय इस क्षेत्र से मेल खाने वाली कोई खबर नहीं है।",
        "script_tag": "devanagari",
        "script_dominant_check": _devanagari_dominant,
        "region_labels": {
            "Middle East & Africa": "मध्य पूर्व और अफ्रीका",
            "Europe & Russia": "यूरोप और रूस",
            "Asia-Pacific": "एशिया-प्रशांत",
            "Americas": "अमेरिका",
            "Global / Multilateral": "वैश्विक / बहुपक्षीय",
            "World": "दुनिया",
        },
    },
    # ── Add new languages here ──────────────────────────────────────────────
    # "es": {
    #     "code": "es",
    #     "display_name": "Español",
    #     "is_default": False,
    #     "site_subdir": "es",
    #     "md_filename": "newsletter.es.md",
    #     "all_label": "Todo",
    #     "digest_label": "Nota del editor",
    #     "filter_aria": "Filtrar por región",
    #     "empty_filter": "Ninguna noticia coincide con esta región en este momento.",
    #     "script_tag": "latin",
    #     "script_dominant_check": _latin_dominant,
    #     "region_labels": {
    #         "Middle East & Africa": "Medio Oriente y África",
    #         "Europe & Russia": "Europa y Rusia",
    #         "Asia-Pacific": "Asia-Pacífico",
    #         "Americas": "Américas",
    #         "Global / Multilateral": "Global / Multilateral",
    #         "World": "Mundo",
    #     },
    # },
}


# ──────────────────────────────────────────────────────────────────────────────
# Convenience helpers so callers don't need to know the dict shape.
# ──────────────────────────────────────────────────────────────────────────────

def language_codes() -> list[str]:
    """All configured language codes in display/route order."""
    return list(LANGUAGES.keys())


def non_default_codes() -> list[str]:
    """Language codes that render under a /{code}/ subdirectory."""
    return [c for c, cfg in LANGUAGES.items() if not cfg.get("is_default")]


def default_code() -> str:
    """The root-served language code (defaults to 'en')."""
    for c, cfg in LANGUAGES.items():
        if cfg.get("is_default"):
            return c
    return next(iter(LANGUAGES))


def region_labels_for(lang: str) -> dict[str, str]:
    """Canonical English region -> localized label map for `lang`.

    Falls back to the canonical English identity map if `lang` is unknown
    so callers never crash on typos or stray language codes.
    """
    return LANGUAGES.get(lang, {}).get(
        "region_labels",
        LANGUAGES[default_code()]["region_labels"],
    )


def localize_region(region: str, lang: str) -> str:
    """Translate a canonical English region into the `lang` display label."""
    labels = region_labels_for(lang)
    return labels.get(region, region)


def site_subdir(lang: str) -> str:
    """Relative site subdirectory for `lang` (empty string for default)."""
    return LANGUAGES.get(lang, {}).get("site_subdir", "")


def md_filename(lang: str) -> str:
    """Markdown archive filename for `lang`."""
    return LANGUAGES.get(lang, {}).get("md_filename", f"newsletter.{lang}.md")


def display_name(lang: str) -> str:
    """Human-readable language name for UI (language switcher, footers)."""
    return LANGUAGES.get(lang, {}).get("display_name", lang.upper())


def is_dominant(text: str, lang: str) -> bool:
    """True when `text` reads as the script of `lang`."""
    check = LANGUAGES.get(lang, {}).get("script_dominant_check")
    if check is None:
        return True  # no check configured, accept
    return check(text)


__all__ = [
    "LANGUAGES",
    "LangConfig",
    "language_codes",
    "non_default_codes",
    "default_code",
    "region_labels_for",
    "localize_region",
    "site_subdir",
    "md_filename",
    "display_name",
    "is_dominant",
]
