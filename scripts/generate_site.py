#!/usr/bin/env python3
"""
generate_site.py — Reads newsletter.json and builds:
  - site/index.html  (geopulse-style card dashboard)
  - site/feed.xml    (RSS 2.0 feed)
Also archives newsletter.md into newsletters/YYYY-MM-DD-HH.md.
"""

import glob
import html
import json
import logging
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH  = os.path.join(ROOT, "config.yml")
JSON_PATH    = os.path.join(ROOT, "newsletter.json")
MD_PATH      = os.path.join(ROOT, "newsletter.md")
MD_HI_PATH   = os.path.join(ROOT, "newsletter.hi.md")
SITE_DIR     = os.path.join(ROOT, "site")
ARCHIVE_DIR  = os.path.join(ROOT, "newsletters")
ARCHIVE_HI_DIR = os.path.join(ARCHIVE_DIR, "hi")
SITE_ARCHIVE_DIR = os.path.join(SITE_DIR, "newsletters")
SITE_ARCHIVE_HI_DIR = os.path.join(SITE_ARCHIVE_DIR, "hi")
SITE_HI_DIR  = os.path.join(SITE_DIR, "hi")

# Ensure the Hindi site directory exists before trying to write to it.
os.makedirs(SITE_HI_DIR, exist_ok=True)
INDEX_PATH   = os.path.join(SITE_DIR, "index.html")
HI_INDEX_PATH = os.path.join(SITE_HI_DIR, "index.html")
FEED_PATH    = os.path.join(SITE_DIR, "feed.xml")
NOJEKYLL_PATH = os.path.join(SITE_DIR, ".nojekyll")

# ---------------------------------------------------------------------------
# Brand / ownership values. Defaults keep Lavkesh's live site unchanged so
# existing runs do not shift, but every value can be overridden in
# config.yml under the `brand:` key. A forker only needs to edit config.yml.
# ---------------------------------------------------------------------------
_BRAND_DEFAULTS = {
    "editor_name": "Lavkesh Dwivedi",
    "editor_name_hi": "लवकेश द्विवेदी",
    "editor_website": "https://lavkesh.com",
    "site_title": "GeoPulse",
    "site_url": "https://pulse.lavkesh.com",
    "language_switch_path": "/hi",
    "user_agent": "GeoPulseTemplate/1.0",
    "custom_domain": "",
}


def _load_brand_from_config() -> dict:
    """Return the `brand:` block from config.yml, falling back per-key to
    _BRAND_DEFAULTS. Safe to call at import time; never raises."""
    data: dict = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    brand = data.get("brand") or {}
    return {
        "editor_name": brand.get("editor_name", _BRAND_DEFAULTS["editor_name"]),
        "editor_name_hi": brand.get("editor_name_hi", _BRAND_DEFAULTS["editor_name_hi"]),
        "editor_website": brand.get("editor_website", _BRAND_DEFAULTS["editor_website"]),
        "site_title": brand.get("site_title", _BRAND_DEFAULTS["site_title"]),
        "site_url": brand.get("site_url", _BRAND_DEFAULTS["site_url"]),
        "language_switch_path": brand.get(
            "language_switch_path", _BRAND_DEFAULTS["language_switch_path"]
        ),
        "custom_domain": (brand.get("custom_domain") or "").strip(),
        "user_agent": brand.get("user_agent", _BRAND_DEFAULTS["user_agent"]),
    }


BRAND = _load_brand_from_config()
_EDITOR_WEBSITE_DISPLAY = re.sub(r"^https?://", "", BRAND["editor_website"]).rstrip("/")




SITE_URL     = BRAND["site_url"].rstrip("/")
HI_SITE_URL  = f"{SITE_URL}{BRAND['language_switch_path']}"
SITE_TITLE   = BRAND["site_title"]
SITE_DESC    = f"Signal-first briefings on geopolitics, edited by {BRAND['editor_name']}."
SITE_TAGLINE = "Hourly briefings with context."

ALL_REGIONS  = ["All", "Americas", "Asia-Pacific", "Europe & Russia",
                "Middle East & Africa", "Global / Multilateral", "World"]

# Canonical filter-pill regions. We render a pill for every bucket including
# the two "catch-all" ones (World and Global / Multilateral) so the sum of
# pill counts reconciles with the All count. Same set on EN and HI for
# consistency.
FILTER_REGIONS = ["Americas", "Asia-Pacific", "Europe & Russia",
                  "Middle East & Africa", "Global / Multilateral", "World"]

# Region labels and per-language metadata live in scripts/languages.py now.
# HINDI_REGION_LABELS stays as an alias for the many existing call sites.
# Adding a new language (Spanish, French, etc.) is a one-block edit in
# scripts/languages.py — see the "Add new languages here" marker there.
from languages import (  # noqa: E402
    LANGUAGES,
    region_labels_for,
    localize_region,
    language_codes,
    non_default_codes,
    default_code,
    site_subdir as lang_site_subdir,
    display_name as lang_display_name,
)

HINDI_REGION_LABELS: dict[str, str] = region_labels_for("hi")

SITE_COPY = {
  "en": {
    "page_title": f"{SITE_TITLE}. Geopolitics in brief",
    "site_desc": SITE_DESC,
    "tagline": SITE_TAGLINE,
    "updated_prefix": "Updated",
    "rss_label": "RSS",
    "rss_subscribe_aria": "Subscribe via RSS",
    "rss_subscribe_title": "Subscribe via RSS. Paste the feed URL into any reader for push updates.",
    "language_switch_label": "Language",
    "accent_aria": "Choose accent colour",
    "theme_aria": "Toggle theme",
    "hero_title": "Geopolitics in brief.",
    "hero_description": "An editorial front page for global affairs. A fast, signal-first scan of borders, trade routes, power shifts, and the context behind the headlines.",
    "hero_primary": "Read the latest",
    "hero_secondary_archive": "Browse archive",
    "hero_secondary_rss": "Follow via RSS",
    "beta_banner_text": "GeoPulse for Android is in closed beta. I need a dozen testers held for two weeks before Google will unlock the public Play Store release.",
    "beta_banner_cta": "Become a tester",
    "beta_banner_dismiss_aria": "Dismiss this notice",
    "coverage_map": "Coverage map",
    "latest_story_landed": "Latest story landed",
    "edition_stamped_in": "edition stamped in",
    "filter_aria": "Filter by region",
    "latest_briefing": "Latest briefing",
    "story_board": "Story board",
    "feed_summary_template": "{count} {words} off the wire",
    "archive_toggle": "Past editions",
    "latest_edition": "Latest",
    "showing_all": "Showing all",
    "showing_prefix": "Showing",
    "empty_filter": "No stories match this region right now.",
    "lead_story": "Lead story",
    "archive_eyebrow": "Archive",
    "archive_heading": "Past editions",
    "archive_copy": "Browse previous hourly snapshots exactly as they were published.",
    "about_eyebrow": "About",
    "about_heading": "Hi, I'm Lavkesh.",
    "about_paragraphs": [
      "I started GeoPulse because the world brief I wanted to read every morning did not exist anywhere. So I built it. Every hour it picks up the top stories from around the world, strips the drama, keeps the facts, and lays them out on one page you can actually finish in five minutes.",
      f"Outside this page, I write about engineering and AI at {_EDITOR_WEBSITE_DISPLAY}. I have spent the last fifteen years building software across medical imaging, real-time collaboration, fintech and cloud platforms, and that habit of chasing signal over noise is what you are reading here too. No spin, no hot takes, just the shape of the story as it stands right now.",
    ],
    # TODO (forker): about_paragraphs and about_heading above are the
    # editor's personal copy. Swap in your own bio before going live.
    "sidebar_about_heading": "About GeoPulse",
    "sidebar_about_copy": "A signal-first front page for global affairs. Every hour it pulls the top stories from around the world, strips the drama, and keeps the facts on one page you can finish in five minutes.",
    "sidebar_about_link": "Read more →",
    "about_page_title": f"About · {SITE_TITLE}",
    "about_page_eyebrow": "About",
    "about_page_heading": "About GeoPulse",
    "about_back_link": "← Back to the front page",
    "archive_page_title": f"Archive · {SITE_TITLE}",
    "archive_page_eyebrow": "Archive",
    "archive_page_heading": "Past editions",
    "archive_page_copy": "Every hourly briefing ever published, opened in a new tab as its own front page.",
    "archive_back_link": "← Back to the front page",
    "archive_empty_label": "No archived editions available yet.",
    "footer_archive_label": "Archive",
    "footer_about_label": "About",
    "edition_page_kicker": "Archived edition",
    "edition_page_back": "← Back to the latest",
    "edition_page_browse": "Browse all editions →",
    "edition_page_view_latest": "View the latest edition",
    "editor_label": "Built and curated by",
    "editor_name": BRAND["editor_name"],
    "brand_eyebrow": BRAND["editor_name"],
    "footer_hosted": "Hosted at",
    "just_now": "just now",
    "story_singular": "story",
    "story_plural": "stories",
    "stories_label": "stories",
    "regions_label": "regions",
    "editions_label": "editions",
  },
  "hi": {
    "page_title": f"{SITE_TITLE}. हिंदी संस्करण",
    "site_desc": "भू-राजनीति पर सिग्नल-फर्स्ट संक्षिप्त ब्रीफिंग। संपादक लवकेश द्विवेदी।",
    "tagline": "हर घंटे खबरें, संदर्भ के साथ।",
    "updated_prefix": "अपडेट",
    "rss_label": "RSS",
    "rss_subscribe_aria": "RSS से सब्सक्राइब करें",
    "rss_subscribe_title": "RSS से सब्सक्राइब करें। अपने पसंदीदा रीडर में फ़ीड URL पेस्ट करें।",
    "language_switch_label": "भाषा",
    "accent_aria": "ऐक्सेंट रंग चुनें",
    "theme_aria": "थीम बदलें",
    "hero_title": "भू-राजनीति संक्षेप में।",
    "hero_description": "GeoPulse वैश्विक मामलों का संपादकीय फ्रंट पेज है। सीमाओं, व्यापार मार्गों, शक्ति संतुलन और सुर्खियों के पीछे के संदर्भ का तेज, सिग्नल-फर्स्ट स्कैन।",
    "hero_primary": "ताज़ा पढ़ें",
    "hero_secondary_archive": "आर्काइव देखें",
    "hero_secondary_rss": "RSS से फ़ॉलो करें",
    "beta_banner_text": "GeoPulse का Android ऐप क्लोज़्ड बीटा में है। पब्लिक प्ले स्टोर रिलीज़ अनलॉक करने के लिए मुझे दो हफ्तों तक एक दर्जन टेस्टर चाहिए।",
    "beta_banner_cta": "टेस्टर बनें",
    "beta_banner_dismiss_aria": "यह सूचना हटाएँ",
    "coverage_map": "कवरेज मैप",
    "latest_story_landed": "ताज़ा स्टोरी आई",
    "edition_stamped_in": "संस्करण समय क्षेत्र",
    "filter_aria": "क्षेत्र के अनुसार फ़िल्टर करें",
    "latest_briefing": "ताज़ा ब्रीफिंग",
    "story_board": "स्टोरी बोर्ड",
    "feed_summary_template": "ताज़ा {count} {words}",
    "archive_toggle": "पिछले संस्करण",
    "latest_edition": "ताज़ा",
    "showing_all": "सभी दिख रहे हैं",
    "showing_prefix": "दिख रहा है",
    "empty_filter": "इस क्षेत्र में अभी कोई स्टोरी नहीं है।",
    "lead_story": "मुख्य स्टोरी",
    "archive_eyebrow": "आर्काइव",
    "archive_heading": "पिछले संस्करण",
    "archive_copy": "पिछले प्रति-घंटा स्नैपशॉट वैसे ही देखें जैसे वे प्रकाशित हुए थे।",
    "about_eyebrow": "परिचय",
    "about_heading": "नमस्ते, मैं लवकेश हूं।",
    "about_paragraphs": [
      "GeoPulse इसलिए शुरू किया क्योंकि रोज़ सुबह जैसी दुनिया की झलक मैं खुद पढ़ना चाहता था, वैसी कहीं एक जगह मिलती नहीं थी। तो मैंने खुद बना ली। हर घंटे दुनिया भर की सबसे बड़ी खबरें उठाई जाती हैं, शोर छांटा जाता है, तथ्य बचाए जाते हैं, और एक ऐसे पेज पर सामने रख दिए जाते हैं जिसे आप पांच मिनट में आराम से पूरा पढ़ सकें।",
      f"इसके अलावा मैं {_EDITOR_WEBSITE_DISPLAY} पर इंजीनियरिंग और एआई पर लिखता हूं। पिछले पंद्रह साल मेडिकल इमेजिंग, रीयल-टाइम कोलैबोरेशन, फिनटेक और क्लाउड प्लेटफॉर्म्स पर सॉफ्टवेयर बनाने में बीते हैं। वही आदत, सिग्नल पर ध्यान और हल्ले-गुल्ले से दूरी, यहां भी दिखती है। कोई राय नहीं, कोई नाटक नहीं, बस कहानी इस वक्त जिस शक्ल में है उसी शक्ल में।",
    ],
    # TODO (forker): about_paragraphs and about_heading above are the
    # editor's personal copy. Swap in your own bio before going live.
    "sidebar_about_heading": "GeoPulse के बारे में",
    "sidebar_about_copy": "वैश्विक मामलों का सिग्नल-फर्स्ट फ्रंट पेज। हर घंटे दुनिया भर की प्रमुख खबरें उठाई जाती हैं, शोर हटाया जाता है, और तथ्य एक ऐसे पन्ने पर रखे जाते हैं जिसे आप पाँच मिनट में पढ़ सकें।",
    "sidebar_about_link": "और पढ़ें →",
    "about_page_title": f"परिचय · {SITE_TITLE}",
    "about_page_eyebrow": "परिचय",
    "about_page_heading": "GeoPulse के बारे में",
    "about_back_link": "← मुख्य पृष्ठ पर लौटें",
    "archive_page_title": f"आर्काइव · {SITE_TITLE}",
    "archive_page_eyebrow": "आर्काइव",
    "archive_page_heading": "पिछले संस्करण",
    "archive_page_copy": "हर घंटे प्रकाशित हुई हर ब्रीफिंग, अपने अलग टैब में अपने ही फ्रंट पेज की तरह खुलती है।",
    "archive_back_link": "← मुख्य पृष्ठ पर लौटें",
    "archive_empty_label": "अभी कोई आर्काइव संस्करण उपलब्ध नहीं है।",
    "footer_archive_label": "आर्काइव",
    "footer_about_label": "परिचय",
    "edition_page_kicker": "आर्काइव संस्करण",
    "edition_page_back": "← ताज़ा संस्करण पर लौटें",
    "edition_page_browse": "सभी संस्करण देखें →",
    "edition_page_view_latest": "ताज़ा संस्करण देखें",
    "editor_label": "निर्माण और चयन",
    "editor_name": BRAND["editor_name_hi"],
    "brand_eyebrow": BRAND["editor_name_hi"],
    "footer_hosted": "होस्ट:",
    "just_now": "अभी",
    "story_singular": "खबर",
    "story_plural": "खबरें",
    "stories_label": "खबरें",
    "regions_label": "क्षेत्र",
    "editions_label": "संस्करण",
  },
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # archive_days is retained in config for backwards compat but no longer
    # used — archives live forever.
    cfg["archive_days"] = int(os.environ.get("ARCHIVE_DAYS", cfg.get("archive_days", 0)))
    cfg["display_timezone"] = os.environ.get("DISPLAY_TIMEZONE", cfg.get("display_timezone", "Asia/Kolkata"))
    return cfg


def get_display_timezone(cfg: dict):
    tz_name = str(cfg.get("display_timezone") or "UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        log.warning("Unknown display_timezone '%s' - falling back to UTC.", tz_name)
        return timezone.utc


def format_display_datetime(iso_ts: str, display_tz, fmt: str) -> str:
    ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return ts.astimezone(display_tz).strftime(fmt)


# ── Archive helpers ───────────────────────────────────────────────────────────

def archive_newsletter_variant(cfg: dict, display_tz, source_md: str, archive_dir: str, site_archive_dir: str, label: str) -> list[dict]:
  """Copy a newsletter markdown file into archive folders and prune old editions."""
  os.makedirs(archive_dir, exist_ok=True)
  os.makedirs(site_archive_dir, exist_ok=True)
  if not os.path.exists(source_md):
    return []

  now = datetime.now(timezone.utc)
  archive_name = now.strftime("%Y-%m-%d-%H") + ".md"
  shutil.copy2(source_md, os.path.join(archive_dir, archive_name))
  log.info("Archived %s newsletter → %s/%s", label, archive_dir.replace(ROOT + "/", ""), archive_name)

  # Archive pruning disabled: GitHub Pages storage is cheap at this scale
  # (a ~10KB file per hour is ~90MB per year) and every archived edition
  # is a unique indexed URL that catches long-tail search traffic. Keep
  # them all forever and let the homepage stay focused on the latest feed.
  archives: list[dict] = []
  for path in sorted(glob.glob(os.path.join(archive_dir, "????-??-??-??.md"))):
    fname = os.path.basename(path)
    stem = fname.replace(".md", "")
    parts = stem.split("-")
    try:
      dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), tzinfo=timezone.utc)
      archives.append({
        "filename": fname,
        "label": dt.astimezone(display_tz).strftime("%d %b %Y, %H:00"),
        "iso": dt.isoformat(),
      })
    except (ValueError, IndexError):
      continue

  archives.sort(key=lambda x: x["filename"], reverse=True)

  # The deployed site only routes through the rendered per-edition pages
  # under site_archive_dir/<edition_id>/index.html — nothing links to a raw
  # .md, so copying every archived markdown into site_archive_dir was just
  # doubling the deploy size with no consumer. Keep the cleanup pass so any
  # leftovers from the old behaviour get swept on the next run.
  for old in glob.glob(os.path.join(site_archive_dir, "????-??-??-??.md")):
    try:
      os.remove(old)
    except OSError:
      continue

  return archives


def archive_newsletter(cfg: dict, display_tz, language: str = "en") -> list[dict]:
  if language == "hi":
    return archive_newsletter_variant(cfg, display_tz, MD_HI_PATH, ARCHIVE_HI_DIR, SITE_ARCHIVE_HI_DIR, "Hindi")
  return archive_newsletter_variant(cfg, display_tz, MD_PATH, ARCHIVE_DIR, SITE_ARCHIVE_DIR, "English")


# ── Time helper ───────────────────────────────────────────────────────────────

def time_ago(iso: str, language: str = "en") -> str:
    """Return a human-readable 'X ago' string."""
    try:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            # Crisis Group / Drupal: "Tuesday, June 30, 2026 - 15:20"
            dt = datetime.strptime(iso, "%A, %B %d, %Y - %H:%M")
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
          return SITE_COPY.get(language, SITE_COPY["en"]).get("just_now", "just now")
        if diff < 3600:
            m = diff // 60
            return f"{m}m ago"
        if diff < 86400:
            h = diff // 3600
            return f"{h}h ago"
        d = diff // 86400
        return f"{d}d ago"
    except Exception:
        return ""


# ── Card HTML ─────────────────────────────────────────────────────────────────

def _upgrade_image_url(url: str) -> str:
    """Upgrade known low-res thumbnails to higher-resolution variants."""
    if not url:
        return url
    # BBC ichef: bump the size segment (e.g. /240/ → /624/)
    url = re.sub(r'(ichef\.bbci\.co\.uk/ace/[^/]+/)(\d+)/', r'\g<1>624/', url)
    return url


def _safe_external_url(url: str) -> str:
    """Allow only absolute http(s) URLs for externally linked content."""
    if not url:
        return ""
    candidate = str(url).strip()
    try:
        parsed = urlparse(candidate)
    except Exception:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""
    return candidate


def _is_devanagari_dominant(text: str, threshold: float = 0.30) -> bool:
    """Return True when the text reads as Hindi (enough Devanagari letters)."""
    if not text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False
    dev = sum(1 for ch in letters if "\u0900" <= ch <= "\u097f")
    return (dev / len(letters)) >= threshold


def _is_latin_dominant(text: str, threshold: float = 0.65) -> bool:
    """Return True when the text is mostly Latin/ASCII (English)."""
    if not text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False
    latin = sum(1 for ch in letters if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    return (latin / len(letters)) >= threshold


_HUMAN_PUNCT_PATTERNS = [
    # Collapse multiple spaces
    (re.compile(r"[ \t]{2,}"), " "),
    # Space before sentence punctuation
    (re.compile(r"\s+([\.,;:!\?])"), r"\1"),
    # Missing space after sentence punctuation when followed by a letter
    (re.compile(r"([\.\?!,])([A-Za-z\u0900-\u097f])"), r"\1 \2"),
    # Duplicate punctuation like "..", "!!"
    (re.compile(r"([\.,;:!\?])\1+"), r"\1"),
    # Orphan quote or bracket at the start/end
    (re.compile(r"^[\"'\)\]\s]+"), ""),
    (re.compile(r"\s+$"), ""),
]


def _humanize_punctuation(text: str) -> str:
    """Fix the little punctuation tells that give LLM or feed text away."""
    if not text:
        return text
    out = text
    for pat, repl in _HUMAN_PUNCT_PATTERNS:
        out = pat.sub(repl, out)
    return out.strip()


_SENTENCE_END_CHARS = ".!?\u0964"


def _ensure_sentence_ending(text: str, lang: str = "en") -> str:
    """Make sure the summary ends on a real terminator so it reads complete.

    Walks back to the last full sentence if the tail is clearly dangling
    (mid-word or mid-clause). Appends a period/danda as a last resort so the
    card never trails off with no punctuation. For Hindi, also converts a
    stray trailing Latin period into a Devanagari danda so machine-translated
    output reads correctly.
    """
    if not text:
        return text
    stripped = text.rstrip()
    if not stripped:
        return stripped
    # Hindi: swap a trailing Latin period for a danda. A lot of translation
    # output ends in "." even when the body is Devanagari, which looks off.
    if lang == "hi" and stripped[-1] == ".":
        stripped = stripped[:-1].rstrip() + "\u0964"
    if stripped[-1] in _SENTENCE_END_CHARS:
        return stripped
    # Trailing common connector words suggest a truncated clause — walk back.
    tail = stripped.split()[-1].lower() if stripped.split() else ""
    dangling = {"and", "or", "but", "with", "for", "from", "to", "of", "in",
                "on", "at", "by", "the", "a", "an"}
    if tail in dangling:
        for idx in range(len(stripped) - 1, -1, -1):
            if stripped[idx] in _SENTENCE_END_CHARS:
                return stripped[: idx + 1].rstrip()
    terminator = "।" if lang == "hi" else "."
    return stripped + terminator


_SOURCE_SIGNOFF_PATTERNS = [
    # "<source> reported earlier", "as reported by <source>",
    re.compile(r"\b(?:reported by|according to|as per|via)\s+[A-Z][\w .&'-]{2,40}\b\.?", re.IGNORECASE),
    # Trailing "- Reuters" / "| BBC" publisher tails.
    re.compile(r"\s+[\-\u2013\u2014\|]\s+[A-Z][\w .&'-]{2,40}\s*$"),
    # Self-referential "Subscribe to ...", "Follow us on ..." lines.
    re.compile(r"(?:subscribe|follow us|read more|click here|watch now)\b[^.!?\u0964]*", re.IGNORECASE),
]


def _scrub_source_mentions(text: str, source: str = "") -> str:
    """Remove self-referential publisher chatter that RSS feeds often glue
    to the end of a summary (Subscribe / Follow us / "- BBC World")."""
    if not text:
        return text
    cleaned = text
    for pat in _SOURCE_SIGNOFF_PATTERNS:
        cleaned = pat.sub("", cleaned)
    if source:
        # Strip bare mentions of the source name at the end of the summary.
        src_pat = re.compile(rf"[\s\-\u2013\u2014\|:,.]+{re.escape(source)}[\s\.!?]*$", re.IGNORECASE)
        cleaned = src_pat.sub("", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


_REPEAT_WORD_RE = re.compile(r"\b(\w{3,})(?:\s+\1\b){1,}", re.IGNORECASE | re.UNICODE)
_REPEAT_PHRASE_RE = re.compile(r"\b(.{6,40}?)\s+\1\b", re.IGNORECASE | re.UNICODE)


def _collapse_repeated_words(text: str) -> str:
    """Collapse "the the" / "news news news" / "Delhi Delhi" into one copy."""
    if not text:
        return text
    # Word-level first, then phrase-level.
    out = _REPEAT_WORD_RE.sub(r"\1", text)
    out = _REPEAT_PHRASE_RE.sub(r"\1", out)
    return out


# Catches an orphaned anchor URL fragment that some feeds leak into titles or
# summaries when the leading `<` of an `<a href="...">` tag is already stripped
# upstream — the URL plus the closing `">` survive. Anchored on `//` (with an
# optional `http(s):` prefix) and walks to the next `">`, allowing internal
# whitespace because the LLM occasionally re-spaces the URL when echoing it
# ("//news. sky. com/..."). Tag-stripping in fetch_news handles the
# well-formed case; this is for the malformed leftover.
_ANCHOR_JUNK_RE = re.compile(
    r'(?:https?:)?/{1,2}[\w./:?&=#%\-\s]+?"\s*>\s*',
    re.IGNORECASE,
)

# WordPress / Asia Times / many other RSS feeds tack a self-promotional
# footer onto the syndicated description: "The post <title> appeared first
# on <site>." Sometimes preceded by an empty markdown link "[]" or a stray
# bracket. We strip the whole tail starting at "The post" so the summary
# ends on real prose instead of a self-reference.
_WP_FOOTER_RE = re.compile(
    r"\s*(?:\[\s*\]\s*)?The post .+?(?:appeared first on|first appeared on)\s+[^.]*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Loose orphan markdown brackets like " []" or "[ ]" left behind when a
# feed item contained a markdown link that an upstream stripper emptied.
_ORPHAN_BRACKETS_RE = re.compile(r"\s*\[\s*\]\s*")

# "Read more on X" / "Read more at X" / "Continue reading at X" tails that
# some news aggregators append. We only strip the trailing form.
_READMORE_FOOTER_RE = re.compile(
    r"\s*(?:Read more (?:on|at)|Continue reading (?:on|at))\s+\S+(?:\s+\S+){0,4}\s*$",
    re.IGNORECASE,
)


def _strip_anchor_junk(text: str) -> str:
    if not text:
        return text
    cleaned = text
    if '">' in cleaned:
        cleaned = _ANCHOR_JUNK_RE.sub("", cleaned)
    # Order matters: strip the WP footer first (it may itself contain "[]"
    # at the front), then any standalone empty brackets, then read-more
    # tails. Each pattern is anchored or guarded so a no-op is cheap.
    cleaned = _WP_FOOTER_RE.sub("", cleaned)
    cleaned = _ORPHAN_BRACKETS_RE.sub(" ", cleaned)
    cleaned = _READMORE_FOOTER_RE.sub("", cleaned)
    return cleaned.strip()


def _clean_summary_for_display(summary: str, title: str, language: str = "en") -> str:
    """Remove title duplication, normalise punctuation, and guarantee a clean ending."""
    summary_text = _strip_anchor_junk(html.unescape(summary or "")).strip()
    title_text = html.unescape(title or "").strip()
    if not summary_text:
        return ""
    if not title_text:
        return _ensure_sentence_ending(_humanize_punctuation(summary_text), language)

    summary_compact = re.sub(r"\s+", " ", summary_text)
    title_compact = re.sub(r"\s+", " ", title_text)
    summary_fold = summary_compact.casefold()
    title_fold = title_compact.casefold()

    # If summary is just the title (possibly repeated), keep one copy.
    if summary_fold == title_fold or summary_fold == f"{title_fold} {title_fold}":
        return _ensure_sentence_ending(title_compact, language)

    # Drop a leading restatement of the title ("<title>. The rest...").
    lead_pattern = re.compile(rf"^{re.escape(title_compact)}[\s\-:,.!?]*", re.IGNORECASE)
    cleaned = lead_pattern.sub("", summary_compact).strip() or summary_compact

    # Remove duplicated trailing title: "<summary>. <title>"
    suffix_pattern = re.compile(rf"(?:[\s\-:,.!?]+){re.escape(title_compact)}[\s\-:,.!?]*$", re.IGNORECASE)
    cleaned = re.sub(suffix_pattern, "", cleaned).strip()

    # If title still appears more than once, collapse to a single mention.
    occurrences = cleaned.casefold().count(title_fold)
    if occurrences > 1:
        first_idx = cleaned.casefold().find(title_fold)
        cleaned = (cleaned[: first_idx + len(title_compact)]).strip()

    # Strip repeated leading sentence (e.g. same sentence typed twice by the feed).
    sentences = re.split(r"(?<=[\.!?\u0964])\s+", cleaned)
    deduped: list[str] = []
    seen_fold: set[str] = set()
    for s in sentences:
        key = s.strip().casefold()
        if not key:
            continue
        if key in seen_fold:
            continue
        seen_fold.add(key)
        deduped.append(s.strip())
    cleaned = " ".join(deduped) if deduped else cleaned

    # Drop self-referential "Subscribe to NDTV" / trailing "- BBC World"
    # style noise and collapse obvious word/phrase repeats that RSS feeds
    # occasionally produce when the same copy is concatenated twice.
    cleaned = _scrub_source_mentions(cleaned)
    cleaned = _collapse_repeated_words(cleaned)

    cleaned = _humanize_punctuation(cleaned)
    cleaned = _ensure_sentence_ending(cleaned, language)

    return cleaned or _ensure_sentence_ending(title_compact, language)


def build_related_story_index(articles: list[dict], archives: list[dict], archive_dir: str = ARCHIVE_DIR) -> list[dict]:
    """Build related-story index from current articles and archived markdown editions."""
    items: list[dict] = []

    for art in articles:
        title = str(art.get("title", "")).strip()
        url = _safe_external_url(art.get("url", ""))
        if not title or not url:
            continue
        items.append({
            "title": title,
            "url": url,
            "region": str(art.get("region", "World") or "World").strip(),
            "scope": "latest",
            "edition": "Latest",
        })

    region_heading_re = re.compile(r"^##\s+(.+?)\s*$")
    story_link_re = re.compile(r"^###\s+\[(.+?)\]\((https?://[^)]+)\)")
    for archive in archives[:30]:
        archive_file = os.path.join(archive_dir, archive.get("filename", ""))
        if not os.path.exists(archive_file):
            continue
        current_region = "World"
        try:
            with open(archive_file, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    region_match = region_heading_re.match(line)
                    if region_match:
                        current_region = region_match.group(1).strip()
                        continue
                    story_match = story_link_re.match(line)
                    if story_match:
                        title = story_match.group(1).strip()
                        url = _safe_external_url(story_match.group(2).strip())
                        if not title or not url:
                            continue
                        items.append({
                            "title": title,
                            "url": url,
                            "region": current_region,
                            "scope": "archive",
                            "edition": archive.get("label", "Archive"),
                        })
        except OSError:
            continue

    # Deduplicate exact URL+region entries while preserving first occurrence.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for item in items:
        key = (item["url"], item["region"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _parse_archive_markdown(archive_file: str) -> list[dict]:
    """Parse archived newsletter markdown into card-friendly story payloads."""
    if not os.path.exists(archive_file):
      return []

    region_heading_re = re.compile(r"^##\s+(.+?)\s*$")
    story_link_re = re.compile(r"^###\s+\[(.+?)\]\((https?://[^)]+)\)")
    source_line_re = re.compile(r"^\*(.+?)\*\s+[\u2013\u2014-]\s+(.+)$")
    iso_tail_re = re.compile(r"\(iso:\s*([^)]+)\)\s*$")
    # HTML comment produced by summarize.py that carries the original image
    # URL for each story. Present on editions produced after the archive
    # format bump; older archives silently fall back to the region-tinted
    # placeholder the regular card path uses.
    image_comment_re = re.compile(r"^<!--\s*image:\s*(\S+)\s*-->$")

    stories: list[dict] = []
    current_region = "World"
    current_story: dict | None = None
    summary_lines: list[str] = []

    def flush_story() -> None:
        nonlocal current_story, summary_lines
        if not current_story:
            return
        summary = re.sub(r"\s+", " ", " ".join(summary_lines)).strip()
        if not summary:
            summary = current_story.get("title", "")
        current_story["summary"] = summary
        stories.append(current_story)
        current_story = None
        summary_lines = []

    try:
        with open(archive_file, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue

                region_match = region_heading_re.match(line)
                if region_match:
                    flush_story()
                    current_region = region_match.group(1).strip()
                    continue

                story_match = story_link_re.match(line)
                if story_match:
                    flush_story()
                    title = story_match.group(1).strip()
                    url = _safe_external_url(story_match.group(2).strip())
                    if not title or not url:
                        continue
                    current_story = {
                        "title": title,
                        "url": url,
                        "region": current_region,
                        "source": "",
                        "published_label": "",
                        "summary": "",
                        "image_url": "",
                    }
                    continue

                if current_story:
                    image_match = image_comment_re.match(line)
                    if image_match:
                        current_story["image_url"] = image_match.group(1).strip()
                        continue
                    source_match = source_line_re.match(line)
                    if source_match and not current_story.get("source"):
                        current_story["source"] = source_match.group(1).strip()
                        tail = source_match.group(2).strip()
                        iso_match = iso_tail_re.search(tail)
                        if iso_match:
                            current_story["published_at"] = iso_match.group(1).strip()
                            tail = iso_tail_re.sub("", tail).rstrip(" ·-\u2013\u2014")
                        current_story["published_label"] = tail
                        continue
                    if line.startswith("---") or line.startswith("*GeoPulse"):
                        continue
                    summary_lines.append(line)
    except OSError:
        return []

    flush_story()
    return stories


def build_edition_index(archives: list[dict], archive_dir: str = ARCHIVE_DIR) -> dict[str, dict]:
    """Build a per-edition payload map for in-page rendering."""
    edition_map: dict[str, dict] = {}
    for archive in archives[:30]:
        filename = archive.get("filename", "")
        edition_id = str(filename).replace(".md", "")
        if not edition_id:
            continue
        archive_file = os.path.join(archive_dir, filename)
        stories = _parse_archive_markdown(archive_file)
        if not stories:
            continue
        edition_map[edition_id] = {
            "id": edition_id,
            "label": archive.get("label", edition_id),
            "iso": archive.get("iso", ""),
            "stories": stories,
        }
    return edition_map


# Region-tuned placeholder palette for the branded fallback image. Picked so
# each region reads as a distinct colour without clashing with the accent
# picker. Light/dark agnostic because the gradient carries its own contrast.
_REGION_PLACEHOLDER_COLORS: dict[str, tuple[str, str]] = {
    "Middle East & Africa": ("#c2410c", "#7c2d12"),
    "Europe & Russia":      ("#1d4ed8", "#1e3a8a"),
    "Asia-Pacific":         ("#047857", "#064e3b"),
    "Americas":             ("#b91c1c", "#7f1d1d"),
    "Global / Multilateral": ("#6d28d9", "#4c1d95"),
    "World":                ("#334155", "#0f172a"),
    # Hindi region labels so hi-language cards get the right tint.
    "मध्य पूर्व और अफ्रीका": ("#c2410c", "#7c2d12"),
    "यूरोप और रूस":          ("#1d4ed8", "#1e3a8a"),
    "एशिया-प्रशांत":         ("#047857", "#064e3b"),
    "अमेरिका":               ("#b91c1c", "#7f1d1d"),
    "वैश्विक / बहुपक्षीय":   ("#6d28d9", "#4c1d95"),
    "विश्व":                 ("#334155", "#0f172a"),
}


def _placeholder_registry_script() -> str:
    """Build a tiny script that registers every region's placeholder data URL
    on window.gpPH and exposes a helper the card onerror handlers call. The
    old approach inlined the full SVG data URL into every card's onerror
    attribute, which pushed the homepage past 1MB. This keeps a single copy
    in the head and lets cards reference it by region key."""
    registry = {
        region: _region_placeholder_data_url(region)
        for region in _REGION_PLACEHOLDER_COLORS
    }
    registry_json = json.dumps(registry, ensure_ascii=False)
    # Helper intentionally tiny. Closes over the registry, guards against
    # infinite onerror loops by checking the current src, and falls back to
    # the World palette when an unknown region slips through.
    return (
        "<script>"
        f"window.gpPH=(function(m){{"
        f"return function(img,r){{"
        f"var u=m[r]||m['World'];"
        f"if(u&&img.src!==u)img.src=u;"
        f"}};"
        f"}})({registry_json});"
        "</script>"
    )


def _region_placeholder_data_url(region: str) -> str:
    """Return a data-URL SVG placeholder so every card shows something.

    The placeholder carries the GeoPulse monogram and a region-tuned gradient.
    Data URL keeps us self-contained, no extra static asset to ship.
    """
    start, stop = _REGION_PLACEHOLDER_COLORS.get(region, _REGION_PLACEHOLDER_COLORS["World"])
    import urllib.parse
    svg = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 450' preserveAspectRatio='xMidYMid slice'>"
        "<defs>"
        f"<linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>"
        f"<stop offset='0%' stop-color='{start}'/>"
        f"<stop offset='100%' stop-color='{stop}'/>"
        "</linearGradient>"
        "</defs>"
        "<rect width='800' height='450' fill='url(#bg)'/>"
        "<g transform='translate(400 225)' fill='rgba(255,255,255,0.92)'>"
        "<circle r='92' fill='none' stroke='rgba(255,255,255,0.25)' stroke-width='3'/>"
        "<path d='M-30 -40 L-30 40 M-30 -40 L15 -40 A30 30 0 0 1 15 20 L-30 20' "
        "fill='none' stroke='rgba(255,255,255,0.95)' stroke-width='8' stroke-linecap='round' stroke-linejoin='round'/>"
        "</g>"
        "</svg>"
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg, safe="")


def _truncate_at_word_boundary(text: str, max_chars: int, language: str = "en") -> str:
    """Shorten text to at most max_chars. Prefer a clean sentence boundary
    (., !, ?, ।) over a mid-sentence cut so cards never trail off into an
    ellipsis. Falls back to a whitespace cut with no ellipsis if no sentence
    terminator sits inside a reasonable walk-back window.

    For Hindi we still break on whitespace — Devanagari words are
    space-separated the same way Latin ones are."""
    if not text:
        return ""
    text = text.strip()
    # Strip any ellipsis the upstream summary may already carry; we never
    # want a card to end with one.
    text = text.replace("…", "").rstrip()
    if len(text) <= max_chars:
        return text

    # Allow a 15 percent grace window so a sentence that slightly overruns
    # the cap gets kept whole rather than chopped. Keeps cards reading as
    # complete thoughts instead of clipped fragments.
    grace_max = int(max_chars * 1.15)
    terminator_floor = max(40, max_chars // 2)

    # Collect every sentence terminator position, then pick the latest one
    # that fits inside the grace window and sits above the floor. Latest
    # wins so we keep as much of the summary as the budget allows.
    best_term = -1
    for ch in (".", "!", "?", "।"):
        start = 0
        while True:
            idx = text.find(ch, start)
            if idx < 0 or idx > grace_max:
                break
            if idx >= terminator_floor and idx > best_term:
                best_term = idx
            start = idx + 1
    if best_term >= 0:
        return text[: best_term + 1].rstrip()

    # No terminator anywhere in the grace window. Fall back to a clean
    # whitespace cut at the budget line with NO ellipsis. The user rule
    # is never append ellipsis; CSS line-clamp is the safety net for any
    # residual overflow on narrow viewports.
    window = text[:max_chars]
    last_space = max(window.rfind(" "), window.rfind(" "))
    min_span = max(20, max_chars // 3)
    if last_space >= min_span:
        window = window[:last_space]
    return window.rstrip("  ,.;:–—‐।")


_HI_DANDA = "।"


def _cap_words(text: str, max_words: int) -> str:
    """Cap text to at most max_words, preferring a clean sentence end.

    Word-based rather than char-based so EN and HI behave identically
    (Devanagari glyphs render wider but "word" means the same thing).
    Strips any pre-existing ellipsis, then keeps adding whole words
    until max_words is reached. If the last kept word ended a sentence
    (period, !, ?, danda), we stop there. Otherwise walk back to the
    last sentence terminator as long as it sits above half the budget;
    failing that, return a clean word cut with NO ellipsis appended.
    """
    if not text:
        return ""
    clean = text.replace("\u2026", "").strip()
    words = clean.split()
    if len(words) <= max_words:
        return clean
    # Grace window: allow up to 15 percent overrun to preserve a full
    # sentence when the natural ending sits just past the cap.
    grace = int(max_words * 1.15)
    # Soft floor — we prefer NOT to cut below a quarter of the budget, but
    # if no terminator sits above that line we still walk all the way back
    # rather than leaving a dangling mid-sentence cut. Better a slightly
    # shorter complete sentence than a broken thought with an ellipsis.
    soft_floor = max(4, max_words // 4)
    terminators = {".", "!", "?", "\u0964"}
    # First pass: prefer the last terminator inside the grace window above
    # the soft floor.
    best = -1
    for i, w in enumerate(words[:grace]):
        stripped = w.rstrip(' ,;:"\')')
        if stripped and stripped[-1] in terminators and i >= soft_floor - 1:
            best = i
    if best >= 0:
        return " ".join(words[: best + 1])
    # Second pass: no terminator above the soft floor. Walk back as far
    # as needed to find ANY terminator inside the grace window.
    for i in range(min(grace, len(words)) - 1, -1, -1):
        stripped = words[i].rstrip(' ,;:"\')')
        if stripped and stripped[-1] in terminators:
            return " ".join(words[: i + 1])
    # Third pass: still no terminator. Hard word cut at max_words, strip
    # trailing punctuation so we don't leave a dangling comma, then append
    # an ellipsis so readers know the thought continues elsewhere.
    cut = " ".join(words[:max_words]).rstrip(' ,;:\u2013\u2014\u2010\u0964')
    return cut + "\u2026"


def _apply_card_length_caps(title: str, summary: str, featured: bool, language: str) -> tuple[str, str]:
    """Titles are never truncated — readers deserve the full headline, even
    when it runs long. Summaries still get a word cap so the card grid stays
    visually even. _cap_words prefers a clean sentence boundary and never
    appends ellipsis."""
    if featured:
        summary_words = 110
    else:
        summary_words = 100
    summary_cut = _cap_words(summary, summary_words)
    return title.strip(), summary_cut


def render_card(art: dict, featured: bool = False, language: str = "en") -> str:
    copy = SITE_COPY.get(language, SITE_COPY["en"])
    raw_title = _strip_anchor_junk(art.get("title", "")).strip()
    raw_summary = art.get("summary", "")
    cleaned_summary = _clean_summary_for_display(raw_summary, raw_title, language=language)

    # Cap title and summary lengths on whole-word boundaries before they hit
    # the DOM. CSS line-clamp still catches overflow but should only fire on
    # unusually narrow viewports, so readers stop seeing words chopped in
    # half with a trailing ellipsis.
    capped_title, capped_summary = _apply_card_length_caps(
        raw_title, cleaned_summary, featured=featured, language=language,
    )

    title     = html.escape(capped_title)
    summary   = html.escape(capped_summary)
    safe_url_raw = _safe_external_url(art.get("url", ""))
    url          = html.escape(safe_url_raw or "")
    region    = html.escape(art.get("region", "World"))
    pub       = art.get("published_at", "")
    ago       = time_ago(pub, language)
    image_url = _safe_external_url(_upgrade_image_url(art.get("image_url", "")))
    # Every card shows an image. If the feed did not carry one and the
    # og:image scrape missed, fall back to a branded placeholder tinted by
    # region so the grid stays visually consistent. The fallback data URL
    # is no longer inlined per card — it lives in window.gpPH (built once
    # in the head) and gpPH(img, region) swaps it in on error. That alone
    # trims roughly 1MB off the rendered index.
    region_key = art.get("region", "World")
    placeholder_url = _region_placeholder_data_url(region_key)
    effective_image = image_url or placeholder_url
    safe_img = html.escape(effective_image)
    img_alt = html.escape(raw_title or "Story image")
    region_js_attr = html.escape(json.dumps(region_key), quote=True)
    loading_attrs = 'loading="eager" fetchpriority="high"' if featured else 'loading="lazy"'
    img_html = (
        f'<img class="card-img" src="{safe_img}" alt="{img_alt}" {loading_attrs} '
        f'onerror="gpPH(this,{region_js_attr})">'
    )

    # Source chips and "Open story" label removed — the whole card is already a
    # link to the original story, so extra attribution or CTA text just eats
    # real estate without giving the reader anything new.

    card_classes = ["card"]
    if featured:
        card_classes.append("featured-card")
    if not image_url:
        card_classes.append("placeholder-card")

    featured_kicker = f'<p class="featured-kicker">{html.escape(copy["lead_story"])}</p>' if featured else ""
    title_tag = "h2" if featured else "h3"
    # Leave data-url on the article so the filter/related JS and the keyboard
    # fallback can still find clickable cards, but drop role="link"/tabindex
    # because the real anchor below is now the accessible link. That anchor
    # uses ::after to stretch across the whole card so every visible pixel
    # navigates, and the browser handles open-in-new-tab, middle-click,
    # right-click, and screen reader semantics natively. This replaces the
    # old event-delegation + window.open approach, which popup blockers and
    # some mobile browsers were silently dropping.
    card_attrs = f" class=\"{' '.join(card_classes)}\" data-region=\"{region}\""
    if safe_url_raw:
        card_attrs += f' data-url="{url}"'

    if safe_url_raw:
        title_html = (
            f'<{title_tag} class="card-title">'
            f'<a class="card-link" href="{url}" '
            f'target="_blank" rel="noopener noreferrer" '
            f'aria-label="Open story: {title}">{title}</a>'
            f'</{title_tag}>'
        )
    else:
        title_html = f'<{title_tag} class="card-title">{title}</{title_tag}>'

    return f"""
  <article{card_attrs}>
    <div class="card-img-wrap">{img_html}</div>
    <div class="card-body">
      <div class="card-meta-top" role="group" aria-label="Story meta">
        <div class="card-topic-wrap"></div>
        <span class="card-time" data-published-at="{html.escape(pub)}">{ago}</span>
      </div>
      {featured_kicker}
      {title_html}
      <p class="card-summary">{summary}</p>
    </div>
  </article>"""


def render_archive_list(archives: list[dict], language: str = "en") -> str:
    language_param = "" if language == "en" else "&lang=hi"
    if not archives:
        return ""
    items = "\n".join(
    f'<li><a href="?edition={html.escape(a["filename"].replace(".md", ""))}{language_param}" data-edition-id="{html.escape(a["filename"].replace(".md", ""))}" data-archive-iso="{html.escape(a["iso"])}">{a["label"]}</a></li>'
        for a in archives[:30]
    )
    return items


# ── Full page builder ─────────────────────────────────────────────────────────

def build_html(
    articles: list[dict],
    generated_at: str,
    archives: list[dict],
    display_tz,
    language: str = "en",
    digest: str = "",
    editor_note: dict | None = None,
) -> str:
    copy = SITE_COPY.get(language, SITE_COPY["en"])
    page_url = SITE_URL if language == "en" else HI_SITE_URL
    switch_url = HI_SITE_URL if language == "en" else SITE_URL
    switch_label = "हिंदी" if language == "en" else "English"
    html_lang = "en" if language == "en" else "hi"
    asset_prefix = "" if language == "en" else "../"
    archive_fetch_base = f"{SITE_URL}/newsletters" if language == "en" else f"{SITE_URL}/newsletters/hi"
    generated_at_attr = html.escape(generated_at)
    # Section routes stay language-scoped so the Hindi footer links land on
    # the Hindi about/archive pages instead of bouncing to English.
    about_path = f"{page_url}/about/"
    archive_path = f"{page_url}/archive/"

    # Footer credit data. Year comes from the edition timestamp so the footer
    # stays accurate even when the cron spans midnight on Dec 31. Editor name
    # picks the language-specific variant so the Hindi edition reads cleanly.
    try:
        footer_year = int(generated_at[:4])
    except (ValueError, TypeError):
        footer_year = datetime.now(timezone.utc).year
    footer_editor = html.escape(
        BRAND["editor_name_hi"] if language == "hi" else BRAND["editor_name"]
    )

    if language == "hi":
        localized_articles: list[dict] = []
        for article in articles:
            hi = article.get("translations", {}).get("hi", {})
            localized_articles.append({
                **article,
                "title": hi.get("title") or article.get("title", ""),
                "summary": hi.get("summary") or article.get("summary", ""),
                "region": hi.get("region") or HINDI_REGION_LABELS.get(article.get("region", "World"), article.get("region", "World")),
            })
        articles = localized_articles

    # Prefer bigger contexts and drop smaller ones. The summariser targets
    # 45-90 words, so anything below 25 is the under-cooked tail — a one- or
    # two-sentence card that looks empty next to a fat neighbour. Drop it.
    # Compensated upstream by widening the rank cap so the grid still has
    # enough fat candidates.
    MIN_RENDER_SUMMARY_WORDS = 25
    before_floor = len(articles)
    articles = [
        article for article in articles
        if len((article.get("summary") or "").split()) >= MIN_RENDER_SUMMARY_WORDS
    ]
    log.info(
        "Render %s homepage: %d articles in -> %d after %d-word floor",
        language, before_floor, len(articles), MIN_RENDER_SUMMARY_WORDS,
    )

    featured_article = None
    ordered_articles = articles
    if articles:
        # The lead slot uses the largest type and the widest image, so a
        # thin-content article looks awkwardly empty up there. Require both
        # an image and a substantive summary; fall back to image-only, then
        # to the first article if neither pool has anything.
        LEAD_MIN_SUMMARY_WORDS = 45

        def _has_image(article: dict) -> bool:
            return bool(_safe_external_url(_upgrade_image_url(article.get("image_url", ""))))

        def _summary_word_count(article: dict) -> int:
            return len((article.get("summary") or "").split())

        featured_article = next(
            (
                article for article in articles
                if _has_image(article) and _summary_word_count(article) >= LEAD_MIN_SUMMARY_WORDS
            ),
            None,
        )
        if featured_article is None:
            featured_article = next(
                (article for article in articles if _has_image(article)),
                articles[0],
            )
        ordered_articles = [featured_article] + [
            article for article in articles if article is not featured_article
        ]

    cards_html = "\n".join(
        render_card(article, featured=index == 0, language=language)
        for index, article in enumerate(ordered_articles)
    ) if ordered_articles else '<p class="empty-state">No stories in this edition yet.</p>'

    present_regions = sorted({a.get("region", "World") for a in articles})
    region_counts = Counter(a.get("region", "World") for a in articles)

    story_total = len(articles)
    story_word = copy["story_singular"] if story_total == 1 else copy["story_plural"]
    story_label = f"{story_total} {story_word}"
    region_label = f"{len(present_regions)} {copy['regions_label']}"
    archive_label = f"{len(archives)} {copy['editions_label']}"
    feed_summary_default = copy["feed_summary_template"].format(
        count=story_total, words=story_word,
    )
    latest_story_ago = time_ago(articles[0].get("published_at", ""), language) if articles else copy.get("just_now", "just now")

    try:
        edition_stamp = format_display_datetime(generated_at, display_tz, "%d %b %Y · %H:%M %Z")
    except Exception:
        edition_stamp = generated_at

    coverage_map_html = "".join(
        f'<li><span>{html.escape(region)}</span><strong>{count}</strong></li>'
        for region, count in region_counts.most_common(4)
    ) or '<li><span>World</span><strong>0</strong></li>'

    # Option A: Editions tab is hidden. Archive markdown is still generated
    # for SEO and direct links, but the UI stays focused on the latest feed
    # only. Set this flag early so the JSON index builds below can skip
    # producing data no code path will read.
    view_tab_html = ""
    editions_feature_enabled = bool(view_tab_html)

    archive_items = render_archive_list(archives, language=language)
    editions_list_html = f'<ul class="archive-list">{archive_items}</ul>' if archive_items else '<p class="archive-empty">No archived editions available yet.</p>'
    archive_dir = ARCHIVE_DIR if language == "en" else ARCHIVE_HI_DIR
    # When the editions tab is off we skip building the two heavy lookup
    # indexes and emit empty placeholders so the homepage does not ship
    # ~900KB of JSON nothing on the page ever reads. When the tab returns,
    # this block goes back to full build.
    if editions_feature_enabled:
        related_index = build_related_story_index(articles, archives, archive_dir=archive_dir)
        related_index_json = html.escape(json.dumps(related_index, ensure_ascii=False))
        edition_index = build_edition_index(archives, archive_dir=archive_dir)
        edition_index_json = html.escape(json.dumps(edition_index, ensure_ascii=False))
    else:
        related_index_json = "[]"
        edition_index_json = "{}"

    # Archive picker dropdown options. Cap at 30 to match the edition index
    # and keep the DOM lean. Labels get re-rendered in local time by the JS
    # on load so each visitor sees their own tz.
    archive_options_html = "\n            ".join(
        f'<button type="button" class="archive-option" '
        f'data-edition-id="{html.escape(a["filename"].replace(".md", ""))}" '
        f'data-archive-iso="{html.escape(a["iso"])}" role="menuitem">'
        f'{a["label"]}</button>'
        for a in archives[:30]
    )

    count = len(articles)

    # Build region filter tabs. Full canonical set on both languages.
    all_label = "All" if language == "en" else "सभी"
    tab_html = '<button type="button" class="filter-tab active" data-filter="All" aria-pressed="true">' + all_label + ' <span class="tab-count">' + str(count) + '</span></button>\n'
    for reg in FILTER_REGIONS:
        label = HINDI_REGION_LABELS.get(reg, reg) if language == "hi" else reg
        # Article cards carry data-region as the localized label (see
        # localized_articles loop above), so data-filter and the counter must
        # match that localized key. Using the English canonical reg here would
        # leave every pill at 0 on the Hindi page.
        match_key = label
        n = sum(1 for a in articles if a.get("region") == match_key)
        tab_html += f'<button type="button" class="filter-tab" data-filter="{html.escape(match_key)}" aria-pressed="false">{html.escape(label)} <span class="tab-count">{n}</span></button>\n'

    secondary_href = "?view=editions"
    secondary_label = copy["hero_secondary_archive"]

    # Editor's digest: a short LLM-generated lead that sits in the hero panel.
    # Suppressed when a manual editor_note is configured in config.yml — the
    # hand-written note carries the editorial voice better, and the auto
    # summary tends to surface the grimmest headline of the run, which
    # reads oddly stacked above a friendly announcement card.
    digest_text = (digest or "").strip()
    _editor_note_body_key = "body_hi" if language == "hi" else "body"
    _has_manual_editor_note = bool(
        editor_note and (editor_note.get(_editor_note_body_key) or "").strip()
    )
    if digest_text and not _has_manual_editor_note:
        digest_label = "Editor's note" if language == "en" else "संपादकीय नोट"
        digest_html = (
            '<div class="editor-note">'
            f'<p class="editor-note-label">{digest_label}</p>'
            f'<p class="editor-note-body">{html.escape(digest_text)}</p>'
            '</div>'
        )
    else:
        digest_html = ""

    # Hindi pages pull in Devanagari-friendly serif and sans for a more
    # flowing read on card titles and body copy. English pages stay lean.
    if language == "hi":
        fonts_href = (
            "https://fonts.googleapis.com/css2?"
            "family=Fraunces:opsz,wght@9..144,300;9..144,400&"
            "family=JetBrains+Mono:wght@400;500&"
            "family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&"
            "family=Tiro+Devanagari+Hindi:ital@0;1&"
            "family=Noto+Sans+Devanagari:wght@300;400;500;600;700&"
            "display=swap"
        )
    else:
        fonts_href = (
            "https://fonts.googleapis.com/css2?"
            "family=Fraunces:opsz,wght@9..144,300;9..144,400&"
            "family=JetBrains+Mono:wght@400;500&"
            "family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&"
            "display=swap"
        )

    install_label = "Install app" if language == "en" else "ऐप इंस्टॉल करें"

    # Editor's note (one-off announcement card under the hero). Renders only
    # when config.yml has editor_note.body for this language. Card auto-hides
    # on the empty case so removing the announcement is just a config edit.
    editor_note_html = ""
    if editor_note:
        body_key = "body_hi" if language == "hi" else "body"
        title_key = "title_hi" if language == "hi" else "title"
        cta_label_key = "cta_label_hi" if language == "hi" else "cta_label"
        note_body = (editor_note.get(body_key) or "").strip()
        note_title = (editor_note.get(title_key) or "").strip()
        note_cta_label = (editor_note.get(cta_label_key) or "").strip()
        note_cta_href = (editor_note.get("cta_href") or "").strip()
        if note_body:
            cta_html = ""
            if note_cta_label and note_cta_href:
                cta_html = (
                    f' <a class="release-note-cta" href="{html.escape(note_cta_href, quote=True)}">'
                    f'{html.escape(note_cta_label)} <span aria-hidden="true">→</span></a>'
                )
            title_html = ""
            if note_title:
                title_html = f'<p class="release-note-title">{html.escape(note_title)}</p>'
            editor_note_html = (
                '<aside class="release-note" aria-label="Note from the editor">'
                '<div class="release-note-inner">'
                f'{title_html}'
                f'<p class="release-note-body">{html.escape(note_body)}{cta_html}</p>'
                '</div>'
                '</aside>'
            )
    install_hint = (
        "On iPhone, open in Safari and tap Share → Add to Home Screen."
        if language == "en"
        else "iPhone पर Safari में खोलें और Share → Add to Home Screen दबाएं।"
    )

    latest_tab = "Latest" if language == "en" else "ताज़ा"
    editions_tab = "Editions" if language == "en" else "एडिशन"
    locale = "en_US" if language == "en" else "hi_IN"
    alt_locale = "hi_IN" if language == "en" else "en_US"
    hreflang_self = "en" if language == "en" else "hi"
    hreflang_alt = "hi" if language == "en" else "en"
    og_image_url = f"{SITE_URL}/icon-512.png"
    structured_data = {
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "WebSite",
          "@id": f"{page_url}#website",
          "name": SITE_TITLE,
          "url": page_url,
          "inLanguage": html_lang,
          "description": copy["site_desc"],
        },
        {
          "@type": "CollectionPage",
          "@id": f"{page_url}#collection",
          "isPartOf": {"@id": f"{page_url}#website"},
          "name": copy["page_title"],
          "url": page_url,
          "inLanguage": html_lang,
          "description": copy["site_desc"],
          "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": min(len(ordered_articles), 20),
            "itemListElement": [
              {
                "@type": "ListItem",
                "position": idx,
                "item": {
                  "@type": "NewsArticle",
                  "@id": _safe_external_url(article.get("url", "")),
                  "headline": str(article.get("title", "")).strip()[:110],
                  "description": str(article.get("summary", "")).strip()[:300],
                  "url": _safe_external_url(article.get("url", "")),
                  "datePublished": article.get("published_at", ""),
                  "dateModified": article.get("published_at", ""),
                  "inLanguage": html_lang,
                  "isAccessibleForFree": True,
                  "image": (
                    [article.get("image_url")]
                    if str(article.get("image_url", "")).startswith(("http://", "https://"))
                    else [og_image_url]
                  ),
                  "publisher": {
                    "@type": "Organization",
                    "name": str(article.get("source", "")).strip() or SITE_TITLE,
                  },
                  "author": {
                    "@type": "Organization",
                    "name": SITE_TITLE,
                  },
                  "articleSection": str(article.get("region", "")).strip() or "World",
                },
              }
              for idx, article in enumerate(ordered_articles[:20], start=1)
              if str(article.get("title", "")).strip() and _safe_external_url(article.get("url", ""))
            ],
          },
        },
      ],
    }
    structured_data_json = json.dumps(structured_data, ensure_ascii=False).replace("</", "<\\/")

    # Region -> placeholder SVG registry, emitted once in the head so card
    # onerror handlers can look it up instead of each card inlining the same
    # data URL.
    placeholder_registry_script = _placeholder_registry_script()

    # Only emit the related/edition JSON script tags when the editions tab
    # is actually enabled. The JS reader guards with `if (relatedDataEl)`
    # so the absence is safe.
    index_data_scripts = (
        f'<script id="related-index" type="application/json">{related_index_json}</script>\n'
        f'  <script id="edition-index" type="application/json">{edition_index_json}</script>'
        if editions_feature_enabled else ""
    )

    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{copy['page_title']}</title>
  <meta name="description" content="{copy['site_desc']}" />
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1" />
  <meta name="color-scheme" content="light dark" />
  <meta property="og:title" content="{copy['page_title']}" />
  <meta property="og:description" content="{copy['site_desc']}" />
  <meta property="og:url" content="{page_url}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="{SITE_TITLE}" />
  <meta property="og:locale" content="{locale}" />
  <meta property="og:locale:alternate" content="{alt_locale}" />
  <meta property="og:image" content="{og_image_url}" />
  <meta property="og:image:alt" content="{SITE_TITLE} logo" />
  <meta property="og:image:width" content="512" />
  <meta property="og:image:height" content="512" />
  <meta name="twitter:card" content="summary" />
  <meta name="twitter:title" content="{copy['page_title']}" />
  <meta name="twitter:description" content="{copy['site_desc']}" />
  <meta name="twitter:image" content="{og_image_url}" />
  <meta name="referrer" content="strict-origin-when-cross-origin" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' https: data:; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'self'; upgrade-insecure-requests" />
  <link rel="canonical" href="{page_url}" />
  <link rel="alternate" hreflang="{hreflang_self}" href="{page_url}" />
  <link rel="alternate" hreflang="{hreflang_alt}" href="{switch_url}" />
  <link rel="alternate" hreflang="x-default" href="{SITE_URL}" />
  <link rel="alternate" type="application/rss+xml" title="{SITE_TITLE} RSS" href="{SITE_URL}/feed.xml" />
  <link rel="icon" type="image/svg+xml" href="{asset_prefix}favicon.svg" />
  <link rel="alternate icon" type="image/png" sizes="32x32" href="{asset_prefix}favicon-32.png" />
  <link rel="apple-touch-icon" sizes="180x180" href="{asset_prefix}apple-touch-icon.png" />
  <link rel="manifest" href="{asset_prefix}manifest.webmanifest" />
  <meta name="application-name" content="{SITE_TITLE}" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-title" content="{SITE_TITLE}" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="mobile-web-app-capable" content="yes" />
  <meta name="theme-color" content="#e9e5de" media="(prefers-color-scheme: light)" />
  <meta name="theme-color" content="#05070d" media="(prefers-color-scheme: dark)" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <!-- Preload the Google Fonts stylesheet so the browser starts fetching
       the font face definitions before CSSOM blocks parsing. The swap
       font-display keeps text visible with a system fallback in the
       window between preload and full font ready, so readers don't see
       invisible text flashing. -->
  <link rel="preload" as="style" href="{fonts_href}" />
  <link rel="stylesheet" href="{fonts_href}" />
  <link rel="stylesheet" href="{asset_prefix}styles.css" />
  <script type="application/ld+json">{structured_data_json}</script>

  <script>(function(){{var t=localStorage.getItem('gp-theme');if(!t){{var h=new Date().getHours();t=(h>=7&&h<19)?'light':'dark';}}document.documentElement.dataset.theme=t;}})();</script>
  {placeholder_registry_script}
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>

  <!-- ── Header ─────────────────────────────────────────────────── -->
  <header class="app-header">
    <div class="header-inner">
      <a class="brand" href="{page_url}">
        <span class="brand-mark" aria-hidden="true">
          <img class="brand-logo" src="{asset_prefix}logo.svg" alt="" />
        </span>
        <span class="brand-copy">
          <span class="brand-name">{SITE_TITLE}</span>
          <span class="brand-eyebrow brand-tagline">{copy['tagline']}</span>
        </span>
      </a>
      <div class="header-right">
        <a class="header-link language-switch" href="{switch_url}">{switch_label}</a>
        <button type="button" id="theme-btn" class="theme-btn" aria-label="{copy['theme_aria']}">
          <span class="light-icon" aria-hidden="true">☀️</span><span class="dark-icon" aria-hidden="true">🌙</span>
        </button>
      </div>
    </div>
  </header>

  <aside class="beta-banner" id="beta-banner" hidden>
    <p class="beta-banner-text">
      <span class="beta-banner-emoji" aria-hidden="true">📱</span>
      {copy['beta_banner_text']}
      <a class="beta-banner-link" href="mailto:shiveshsolutions@gmail.com?subject=GeoPulse%20Android%20tester&amp;body=Hi%20Lav%2C%20please%20add%20my%20Gmail%20to%20the%20GeoPulse%20Android%20closed%20beta.%20My%20address%20is%3A%20">{copy['beta_banner_cta']} →</a>
    </p>
    <button type="button" class="beta-banner-close" id="beta-banner-close" aria-label="{copy['beta_banner_dismiss_aria']}">×</button>
  </aside>

  <main id="main-content">

  <section class="hero-shell">
    <div class="hero-grid">
      <div class="hero-copy">
        <p class="hero-kicker"><span class="hero-kicker-stamp"><span id="hero-edition-stamp" data-generated-at="{generated_at_attr}">Edition timestamp</span> · </span>{story_label} on the board</p>
        <h1 class="hero-title">{copy['hero_title']}</h1>
        <p class="hero-description">{copy['hero_description']}</p>
        {digest_html}
        <div class="hero-actions">
          <a class="hero-action hero-action-primary" href="#card-feed">{copy['hero_primary']}</a>
          <button type="button" class="hero-action hero-action-install" id="install-btn" hidden>{install_label} <span aria-hidden="true">↓</span></button>
        </div>
        <p class="hero-install-hint" id="install-hint" hidden>{install_hint}</p>
      </div>
    </div>
  </section>

    {editor_note_html}

    <!-- ── Filter tabs ──────────────────────────────────────────── -->
    <nav class="filter-bar" aria-label="{copy['filter_aria']}">
      <div class="filter-inner">
        {tab_html}
      </div>
    </nav>

    <!-- ── Main layout ──────────────────────────────────────────── -->
    <div class="page-layout">

      <section class="content-column">
        <div class="feed-head">
          <div>
            <p class="section-kicker">{copy['latest_briefing']}</p>
            <h2 class="feed-title">{copy['story_board']}</h2>
          </div>
          <p class="feed-summary" id="feed-summary">{feed_summary_default}</p>
        </div>

        <div class="card-feed" id="card-feed">
          {cards_html}
        </div>
        <p class="empty-filter-state" id="empty-filter-state" hidden>{copy['empty_filter']}</p>
      </section>


    </div>

  </main>

  {index_data_scripts}

  <!-- ── Footer ─────────────────────────────────────────────────── -->
  <footer class="app-footer">
    <nav class="footer-nav" aria-label="Site sections">
      <a class="footer-nav-link" href="{about_path}">{copy['footer_about_label']}</a>
      <span class="footer-nav-sep" aria-hidden="true">·</span>
      <a class="footer-nav-link" href="{archive_path}">{copy['footer_archive_label']}</a>
      <span class="footer-nav-sep" aria-hidden="true">·</span>
      <a class="footer-nav-link" href="{SITE_URL}/terms/">Terms</a>
      <span class="footer-nav-sep" aria-hidden="true">·</span>
      <a class="footer-nav-link" href="{SITE_URL}/privacy/">Privacy</a>
    </nav>
    <p class="footer-credit">Built by <a href="{BRAND['editor_website']}" target="_blank" rel="noopener">Lavkesh Dwivedi</a> · <a class="footer-rss" href="{SITE_URL}/feed.xml" target="_blank" rel="noopener noreferrer">RSS</a></p>
  </footer>

  <script>
    // Normalize *.html paths to clean URLs without trailing slashes.
    // Examples: /index.html -> /, /about/index.html -> /about, /about.html -> /about
    const path = window.location.pathname;
    const lowerPath = path.toLowerCase();
    if (lowerPath.endsWith('.html')) {{
      let cleanPath = path.slice(0, -5); // remove ".html"
      if (cleanPath.toLowerCase().endsWith('/index')) {{
        cleanPath = cleanPath.slice(0, -6) || '/';
      }}
      if (cleanPath.length > 1 && cleanPath.endsWith('/')) {{
        cleanPath = cleanPath.slice(0, -1);
      }}
      window.location.replace(cleanPath + window.location.search + window.location.hash);
    }}

    // ── Theme toggle ─────────────────────────────────────────────
    const html = document.documentElement;
    const btn  = document.getElementById('theme-btn');
    // dark is default; toggle to light and back
    btn.addEventListener('click', () => {{
      const next = html.dataset.theme === 'light' ? 'dark' : 'light';
      html.dataset.theme = next;
      localStorage.setItem('gp-theme', next);
    }});


    // ── Android beta banner ────────────────────────────
    // Hidden by default; reveal unless the reader has dismissed it.
    // Swap in the public Play opt-in link once the AAB lands on the
    // Closed testing track, then this whole block becomes a clickthrough.
    (function() {{
      const banner = document.getElementById('beta-banner');
      const close  = document.getElementById('beta-banner-close');
      if (!banner) return;
      let dismissed = false;
      try {{ dismissed = localStorage.getItem('gp-beta-banner-dismissed') === '1'; }} catch (_) {{}}
      if (!dismissed) banner.hidden = false;
      if (close) close.addEventListener('click', () => {{
        banner.hidden = true;
        try {{ localStorage.setItem('gp-beta-banner-dismissed', '1'); }} catch (_) {{}}
      }});
    }})();

    // ── Edition timestamp in hero ────────────────────────────────
    (function() {{
      const heroEditionStamp = document.getElementById('hero-edition-stamp');
      if (!heroEditionStamp) return;
      const raw = heroEditionStamp.dataset.generatedAt || '';
      const parsed = new Date(raw);
      if (Number.isNaN(parsed.getTime())) return;
      heroEditionStamp.textContent = parsed.toLocaleString([], {{
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
      }});
    }})();

    // ── Relative "X ago" labels on cards, driven by the browser clock so
    //    they stay accurate regardless of the reader's timezone.
    function relativeAgo(iso) {{
      if (!iso) return '';
      const t = new Date(iso);
      if (Number.isNaN(t.getTime())) return '';
      const diff = Math.max(0, Math.floor((Date.now() - t.getTime()) / 1000));
      if (diff < 60)    return 'just now';
      if (diff < 3600)  return Math.floor(diff / 60) + 'm ago';
      if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
      return Math.floor(diff / 86400) + 'd ago';
    }}
    function refreshRelativeTimes() {{
      document.querySelectorAll('.card-time[data-published-at]').forEach(el => {{
        const iso = el.getAttribute('data-published-at') || '';
        const text = relativeAgo(iso);
        if (text) el.textContent = text;
      }});
    }}
    refreshRelativeTimes();
    setInterval(refreshRelativeTimes, 60000);

    // ── Region filter ────────────────────────────────────────────
    const tabs  = document.querySelectorAll('.filter-tab');
    const feed  = document.getElementById('card-feed');
    const feedSummary = document.getElementById('feed-summary');
    const emptyFilterState = document.getElementById('empty-filter-state');
    const getCards = () => Array.from(feed ? feed.querySelectorAll('.card') : []);

    function updateFeedState(filter) {{
      const visibleCards = getCards().filter(card => card.style.display !== 'none');
      const countLabel = visibleCards.length + ' ' + (visibleCards.length === 1 ? {json.dumps(copy['story_singular'])} : {json.dumps(copy['story_plural'])});
      if (feedSummary) {{
        if (filter === 'All') {{
          const tmpl = {json.dumps(copy['feed_summary_template'])};
          const n = visibleCards.length;
          const words = (n === 1 ? {json.dumps(copy['story_singular'])} : {json.dumps(copy['story_plural'])});
          feedSummary.textContent = tmpl.replace('{{count}}', n).replace('{{words}}', words);
        }} else {{
          feedSummary.textContent = {json.dumps(copy['showing_prefix'])} + ' ' + filter + ' · ' + countLabel;
        }}
      }}
      if (emptyFilterState) {{
        emptyFilterState.hidden = visibleCards.length !== 0;
      }}
    }}

    tabs.forEach(tab => {{
      tab.addEventListener('click', () => {{
        tabs.forEach(t => {{
          t.classList.remove('active');
          t.setAttribute('aria-pressed', 'false');
        }});
        tab.classList.add('active');
        tab.setAttribute('aria-pressed', 'true');
        const filter = tab.dataset.filter;
        getCards().forEach(card => {{
          const show = filter === 'All' || card.dataset.region === filter;
          card.style.display = show ? '' : 'none';
        }});
        updateFeedState(filter);
      }});
    }});
    updateFeedState('All');

    // ── Clickable cards ─────────────────────────────────────────
    // Primary navigation is now the native .card-link anchor inside each
    // card. This block is a compatibility net: if a click lands on a part
    // of the card that somehow sits above the stretched link's ::after
    // overlay (for example a future interactive child), we still find the
    // nearest card anchor and trigger it. Uses anchor.click() rather than
    // window.open so popup blockers treat it as a direct user click.
    if (feed) {{
      feed.addEventListener('click', e => {{
        // Let real link clicks and buttons handle themselves.
        if (e.target.closest('a, button')) return;
        const card = e.target.closest('.card[data-url]');
        if (!card) return;
        const anchor = card.querySelector('a.card-link');
        if (!anchor) return;
        anchor.click();
      }});
    }}

    // ── PWA: service worker + install prompt ─────────────────────
    (function() {{
      if ('serviceWorker' in navigator) {{
        window.addEventListener('load', () => {{
          navigator.serviceWorker.register('/service-worker.js').catch(() => null);
        }});
      }}
      const installBtn = document.getElementById('install-btn');
      const installHint = document.getElementById('install-hint');
      if (!installBtn) return;
      const isStandalone = window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
      if (isStandalone) return;
      const ua = (navigator.userAgent || '').toLowerCase();
      const isIOS = /iphone|ipad|ipod/.test(ua);
      if (isIOS && installHint) {{
        installHint.hidden = false;
        return;
      }}
      let deferred = null;
      window.addEventListener('beforeinstallprompt', (e) => {{
        e.preventDefault();
        deferred = e;
        installBtn.hidden = false;
      }});
      installBtn.addEventListener('click', async () => {{
        if (!deferred) return;
        deferred.prompt();
        try {{ await deferred.userChoice; }} catch (_) {{}}
        deferred = null;
        installBtn.hidden = true;
      }});
      window.addEventListener('appinstalled', () => {{
        installBtn.hidden = true;
        if (installHint) installHint.hidden = true;
      }});
    }})();
  </script>

<script>(function(){{var btn=document.querySelector(".language-switch");if(!btn)return;btn.addEventListener("click",function(e){{e.preventDefault();var p=location.pathname,s=location.search||"",h=location.hash||"",t;var onHi=(p==="/hi"||p==="/hi/"||p.indexOf("/hi/")===0||p.indexOf("/newsletters/hi/")===0);if(onHi){{if(p.indexOf("/newsletters/hi/")===0){{t="/newsletters/"+p.substring(16);}}else if(p==="/hi"||p==="/hi/"){{t="/";}}else{{t=p.substring(3)||"/";}}}}else{{if(p.indexOf("/newsletters/")===0&&p.indexOf("/newsletters/hi/")!==0){{t="/newsletters/hi/"+p.substring(13);}}else if(p==="/"||p===""){{t="/hi/";}}else{{t="/hi"+p;}}}}s=s.replace(/[?&]lang=[^&]*/g,"").replace(/^&/,"?");if(s==="?")s="";location.href=t+s+h;}});}})();</script>
</body>
</html>"""



# ── Section pages (About, Archive, per-Edition) ───────────────────────────────

_SECTION_PAGE_SKELETON = """<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{page_title}</title>
  <meta name="description" content="{page_desc}" />
  <meta name="robots" content="{robots}" />
  <meta name="color-scheme" content="light dark" />
  <meta property="og:title" content="{page_title}" />
  <meta property="og:description" content="{page_desc}" />
  <meta property="og:url" content="{canonical}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="{site_title}" />
  <meta property="og:image" content="{site_url}/icon-512.png" />
  <meta property="og:image:alt" content="{site_title} logo" />
  <meta property="og:image:width" content="512" />
  <meta property="og:image:height" content="512" />
  <meta name="twitter:card" content="summary" />
  <meta name="twitter:title" content="{page_title}" />
  <meta name="twitter:description" content="{page_desc}" />
  <meta name="twitter:image" content="{site_url}/icon-512.png" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' https: data:; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'self'; upgrade-insecure-requests" />
  <link rel="canonical" href="{canonical}" />
  <link rel="alternate" type="application/rss+xml" title="{site_title} RSS" href="{site_url}/feed.xml" />
  <link rel="icon" type="image/svg+xml" href="{asset_prefix}favicon.svg" />
  <link rel="alternate icon" type="image/png" sizes="32x32" href="{asset_prefix}favicon-32.png" />
  <link rel="apple-touch-icon" sizes="180x180" href="{asset_prefix}apple-touch-icon.png" />
  <link rel="manifest" href="{asset_prefix}manifest.webmanifest" />
  <meta name="theme-color" content="#e9e5de" media="(prefers-color-scheme: light)" />
  <meta name="theme-color" content="#05070d" media="(prefers-color-scheme: dark)" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <!-- Preload font CSS so font-face discovery starts before CSSOM settles. -->
  <link rel="preload" as="style" href="{fonts_href}" />
  <link rel="stylesheet" href="{fonts_href}" />
  <link rel="stylesheet" href="{asset_prefix}styles.css" />
  <script>(function(){{var t=localStorage.getItem('gp-theme');if(!t){{var h=new Date().getHours();t=(h>=7&&h<19)?'light':'dark';}}document.documentElement.dataset.theme=t;}})();</script>
  {extra_head}
</head>
<body class="section-page {body_class}">
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="app-header">
    <div class="header-inner">
      <a class="brand" href="{home_url}">
        <span class="brand-mark" aria-hidden="true">
          <img class="brand-logo" src="{asset_prefix}logo.svg" alt="" />
        </span>
        <span class="brand-copy">
          <span class="brand-name">{site_title}</span>
          <span class="brand-eyebrow brand-tagline">{tagline}</span>
        </span>
      </a>
      <div class="header-right">
        <a class="header-link language-switch" href="{switch_url}">{switch_label}</a>
        <button type="button" id="theme-btn" class="theme-btn" aria-label="{theme_aria}">
          <span class="light-icon" aria-hidden="true">☀️</span><span class="dark-icon" aria-hidden="true">🌙</span>
        </button>
      </div>
    </div>
  </header>
  <main id="main-content" class="section-main">
    {body_html}
  </main>
  <footer class="app-footer">
    <nav class="footer-nav" aria-label="Site sections">
      <a class="footer-nav-link" href="{about_path}">{footer_about_label}</a>
      <span class="footer-nav-sep" aria-hidden="true">·</span>
      <a class="footer-nav-link" href="{archive_path}">{footer_archive_label}</a>
      <span class="footer-nav-sep" aria-hidden="true">·</span>
      <a class="footer-nav-link" href="{site_url}/terms/">Terms</a>
      <span class="footer-nav-sep" aria-hidden="true">·</span>
      <a class="footer-nav-link" href="{site_url}/privacy/">Privacy</a>
    </nav>
    <p class="footer-credit">Built by <a href="{editor_website}" target="_blank" rel="noopener">Lavkesh Dwivedi</a> · <a class="footer-rss" href="{site_url}/feed.xml" target="_blank" rel="noopener noreferrer">RSS</a></p>
  </footer>
  <script>
    var html = document.documentElement;
    var btn = document.getElementById('theme-btn');
    if (btn) {{
      btn.addEventListener('click', function () {{
        var next = html.dataset.theme === 'light' ? 'dark' : 'light';
        html.dataset.theme = next;
        try {{ localStorage.setItem('gp-theme', next); }} catch (_) {{}}
      }});
    }}
    (function() {{
      var els = document.querySelectorAll('[data-archive-iso]');
      for (var i = 0; i < els.length; i++) {{
        var el = els[i];
        var raw = el.getAttribute('data-archive-iso') || '';
        if (!raw) continue;
        var parsed = new Date(raw);
        if (isNaN(parsed.getTime())) continue;
        var label = parsed.toLocaleString([], {{
          day: '2-digit', month: 'short', year: 'numeric',
          hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
        }});
        if (label) el.textContent = label;
      }}
    }})();
  </script>
<script>(function(){{var btn=document.querySelector(".language-switch");if(!btn)return;btn.addEventListener("click",function(e){{e.preventDefault();var p=location.pathname,s=location.search||"",h=location.hash||"",t;var onHi=(p==="/hi"||p==="/hi/"||p.indexOf("/hi/")===0||p.indexOf("/newsletters/hi/")===0);if(onHi){{if(p.indexOf("/newsletters/hi/")===0){{t="/newsletters/"+p.substring(16);}}else if(p==="/hi"||p==="/hi/"){{t="/";}}else{{t=p.substring(3)||"/";}}}}else{{if(p.indexOf("/newsletters/")===0&&p.indexOf("/newsletters/hi/")!==0){{t="/newsletters/hi/"+p.substring(13);}}else if(p==="/"||p===""){{t="/hi/";}}else{{t="/hi"+p;}}}}s=s.replace(/[?&]lang=[^&]*/g,"").replace(/^&/,"?");if(s==="?")s="";location.href=t+s+h;}});}})();</script>
</body>
</html>"""


def _section_page_defaults(language: str, generated_at: str, depth: int = 1) -> dict:
    """Shared key/value pairs used by every section page template.

    depth is how many directories the section page sits below the language
    root. /about/ and /archive/ are depth 1. /newsletters/{id}/ is also
    depth 1 (the edition folder itself). Hindi pages add one extra level on
    top. asset_prefix joins the right number of "../" so static assets at
    the site root resolve correctly from every depth.
    """
    copy = SITE_COPY.get(language, SITE_COPY["en"])
    page_url = SITE_URL if language == "en" else HI_SITE_URL
    switch_url = HI_SITE_URL if language == "en" else SITE_URL
    switch_label = "हिंदी" if language == "en" else "English"
    html_lang = "en" if language == "en" else "hi"
    # Total directory levels above the section page where styles.css lives.
    # Hindi pages live one level deeper than English pages.
    levels_to_root = depth + (1 if language == "hi" else 0)
    asset_prefix = "../" * levels_to_root
    about_path = f"{page_url}/about/"
    archive_path = f"{page_url}/archive/"
    try:
        footer_year = int(str(generated_at)[:4])
    except (ValueError, TypeError):
        footer_year = datetime.now(timezone.utc).year
    footer_editor = html.escape(
        BRAND["editor_name_hi"] if language == "hi" else BRAND["editor_name"]
    )
    if language == "hi":
        fonts_href = (
            "https://fonts.googleapis.com/css2?"
            "family=Fraunces:opsz,wght@9..144,300;9..144,400&"
            "family=JetBrains+Mono:wght@400;500&"
            "family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&"
            "family=Tiro+Devanagari+Hindi:ital@0;1&"
            "family=Noto+Sans+Devanagari:wght@300;400;500;600;700&"
            "display=swap"
        )
    else:
        fonts_href = (
            "https://fonts.googleapis.com/css2?"
            "family=Fraunces:opsz,wght@9..144,300;9..144,400&"
            "family=JetBrains+Mono:wght@400;500&"
            "family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&"
            "display=swap"
        )
    return {
        "copy": copy,
        "html_lang": html_lang,
        "site_title": SITE_TITLE,
        "site_url": SITE_URL,
        "asset_prefix": asset_prefix,
        "fonts_href": fonts_href,
        "home_url": page_url,
        "switch_url": switch_url,
        "switch_label": switch_label,
        "theme_aria": copy.get("theme_aria", "Toggle theme"),
        "about_path": about_path,
        "archive_path": archive_path,
        "footer_year": footer_year,
        "footer_editor": footer_editor,
        "footer_about_label": html.escape(copy.get("footer_about_label", "About")),
        "footer_archive_label": html.escape(copy.get("footer_archive_label", "Archive")),
        "editor_website": BRAND["editor_website"],
        "editor_website_display": _EDITOR_WEBSITE_DISPLAY,
        "tagline": copy.get("tagline", SITE_TAGLINE),
    }


def _render_skeleton(base: dict, *, page_title: str, page_desc: str, robots: str,
                     canonical: str, body_class: str, body_html: str,
                     extra_head: str = "") -> str:
    """Format the skeleton with one shared base map plus the page-specific bits."""
    return _SECTION_PAGE_SKELETON.format(
        page_title=page_title,
        page_desc=page_desc,
        robots=robots,
        canonical=canonical,
        body_class=body_class,
        body_html=body_html,
        extra_head=extra_head,
        html_lang=base["html_lang"],
        site_title=base["site_title"],
        site_url=base["site_url"],
        asset_prefix=base["asset_prefix"],
        fonts_href=base["fonts_href"],
        home_url=base["home_url"],
        switch_url=base["switch_url"],
        switch_label=base["switch_label"],
        theme_aria=base["theme_aria"],
        about_path=base["about_path"],
        archive_path=base["archive_path"],
        footer_year=base["footer_year"],
        footer_editor=base["footer_editor"],
        footer_about_label=base["footer_about_label"],
        footer_archive_label=base["footer_archive_label"],
        editor_website=base["editor_website"],
        editor_website_display=base["editor_website_display"],
        tagline=base["tagline"],
    )


def build_about_html(generated_at: str, language: str = "en") -> str:
    """Render the dedicated About page carrying the editor's first-person bio."""
    base = _section_page_defaults(language, generated_at, depth=1)
    copy = base["copy"]
    home_url = base["home_url"]
    paragraphs_html = "\n".join(
        f'<p>{html.escape(p)}</p>' for p in copy.get("about_paragraphs", [])
    )
    body_html = (
        '<section class="section-shell about-page">'
        f'<p class="section-eyebrow">{html.escape(copy.get("about_page_eyebrow", "About"))}</p>'
        f'<h1 class="section-heading">{html.escape(copy.get("about_heading", "About"))}</h1>'
        '<div class="section-body">'
        f'{paragraphs_html}'
        f'<p class="about-byline">{html.escape(copy.get("editor_label", "Edited by"))} <strong>{html.escape(copy.get("editor_name", BRAND["editor_name"]))}</strong></p>'
        '</div>'
        f'<p class="section-back"><a class="section-back-link" href="{home_url}">{html.escape(copy.get("about_back_link", "Back"))}</a></p>'
        '</section>'
    )
    page_title = html.escape(copy.get("about_page_title", f"About · {SITE_TITLE}"))
    return _render_skeleton(
        base,
        page_title=page_title,
        page_desc=html.escape(copy.get("site_desc", SITE_DESC)),
        robots="index,follow",
        canonical=base["about_path"],
        body_class="about-section-page",
        body_html=body_html,
    )


def build_archive_html(archives: list[dict], generated_at: str, language: str = "en") -> str:
    """Render the archive index: a full list of past editions with per-edition links."""
    base = _section_page_defaults(language, generated_at, depth=1)
    copy = base["copy"]
    home_url = base["home_url"]
    items_html_parts = []
    for a in archives or []:
        edition_id = (a.get("filename") or "").replace(".md", "")
        if not edition_id:
            continue
        iso_raw = a.get("iso", "")
        # Render labels in UTC server-side and drop data-archive-iso so the
        # JS in the section-page skeleton does not rewrite the text to the
        # reader's local timezone. UTC keeps every visitor on the same
        # timestamp the URL slug already encodes.
        try:
            iso_dt = datetime.fromisoformat(iso_raw.replace("Z", "+00:00")) if iso_raw else None
            utc_label = iso_dt.astimezone(timezone.utc).strftime("%d %b %Y, %H:00 UTC") if iso_dt else a.get("label", edition_id)
        except Exception:
            utc_label = a.get("label", edition_id)
        # Per-edition pages live under site/newsletters/{id}/ for English and
        # site/newsletters/hi/{id}/ for Hindi. The directory structure does
        # not mirror the language root, so build the URL off SITE_URL plus
        # an explicit /hi segment for Hindi to keep archive links from 404.
        if language == "hi":
            edition_url = f'{SITE_URL}/newsletters/hi/{edition_id}/'
        else:
            edition_url = f'{SITE_URL}/newsletters/{edition_id}/'
        items_html_parts.append(
            f'<li class="archive-entry">'
            f'<a class="archive-entry-link" href="{edition_url}" target="_blank" rel="noopener">{html.escape(utc_label)}</a>'
            f'</li>'
        )
    if items_html_parts:
        list_html = '<ul class="archive-entry-list">' + "\n".join(items_html_parts) + '</ul>'
    else:
        list_html = f'<p class="archive-empty">{html.escape(copy.get("archive_empty_label", "No archived editions available yet."))}</p>'
    body_html = (
        '<section class="section-shell archive-page">'
        f'<p class="section-eyebrow">{html.escape(copy.get("archive_page_eyebrow", "Archive"))}</p>'
        f'<h1 class="section-heading">{html.escape(copy.get("archive_page_heading", "Past editions"))}</h1>'
        f'<p class="section-lede">{html.escape(copy.get("archive_page_copy", ""))}</p>'
        '<div class="section-body">'
        f'{list_html}'
        '</div>'
        f'<p class="section-back"><a class="section-back-link" href="{home_url}">{html.escape(copy.get("archive_back_link", "Back"))}</a></p>'
        '</section>'
    )
    page_title = html.escape(copy.get("archive_page_title", f"Archive · {SITE_TITLE}"))
    return _render_skeleton(
        base,
        page_title=page_title,
        page_desc=html.escape(copy.get("site_desc", SITE_DESC)),
        robots="index,follow",
        canonical=base["archive_path"],
        body_class="archive-section-page",
        body_html=body_html,
    )


def build_edition_html(edition_id: str, archive_meta: dict, stories: list[dict], generated_at: str, language: str = "en") -> str:
    """Render a single archived edition as its own front page with card layout."""
    base = _section_page_defaults(language, generated_at, depth=2)
    copy = base["copy"]
    home_url = base["home_url"]
    archive_path = base["archive_path"]
    placeholder_registry_script = _placeholder_registry_script()
    iso_raw = archive_meta.get("iso", "")
    iso_attr = html.escape(iso_raw)
    label = html.escape(archive_meta.get("label", edition_id))
    region_counts = Counter(s.get("region", "World") for s in stories if s)
    present_regions = sorted(region_counts.keys())
    story_total = len(stories)
    story_word = copy["story_singular"] if story_total == 1 else copy["story_plural"]
    story_label_text = f"{story_total} {story_word}"
    region_label_text = f"{len(present_regions)} {copy['regions_label']}"
    coverage_map_html = "".join(
        f'<li><span>{html.escape(region)}</span><strong>{count}</strong></li>'
        for region, count in region_counts.most_common(4)
    ) or '<li><span>World</span><strong>0</strong></li>'
    all_label = "All" if language == "en" else "सभी"
    tab_html = (
        f'<button type="button" class="filter-tab active" data-filter="All" '
        f'aria-pressed="true">{all_label} <span class="tab-count">{story_total}</span></button>\n'
    )
    for reg in FILTER_REGIONS:
        label = HINDI_REGION_LABELS.get(reg, reg) if language == "hi" else reg
        # region_counts keys are canonical English; the card data-region on
        # the page may be the localized label. Use the localized label for
        # data-filter so the JS filter actually matches card regions.
        match_key = label
        n = region_counts.get(reg, 0)
        tab_html += (
            f'<button type="button" class="filter-tab" data-filter="{html.escape(match_key)}" '
            f'aria-pressed="false">{html.escape(label)} <span class="tab-count">{n}</span></button>\n'
        )
    cards_html = "\n".join(
        render_card(s, featured=(idx == 0), language=language)
        for idx, s in enumerate(stories)
    ) if stories else f'<p class="empty-state">{html.escape(copy.get("empty_filter", "No stories in this edition yet."))}</p>'
    feed_summary_default = copy["feed_summary_template"].format(
        count=story_total, words=story_word,
    )
    body_html = (
        '<section class="hero-shell edition-hero">'
        '<div class="hero-grid">'
        '<div class="hero-copy">'
        f'<p class="hero-kicker"><span class="hero-kicker-stamp">{html.escape(copy.get("edition_page_kicker", "Archived edition"))} · </span><span data-archive-iso="{iso_attr}">{label}</span></p>'
        f'<h1 class="hero-title">{html.escape(copy.get("story_board", "Story board"))}</h1>'
        f'<p class="hero-description">{html.escape(copy.get("archive_page_copy", ""))}</p>'
        '<div class="hero-actions">'
        f'<a class="hero-action hero-action-primary" href="#card-feed">{html.escape(copy.get("hero_primary", "Read the latest"))}</a>'
        f'<a class="hero-action" href="{archive_path}">{html.escape(copy.get("edition_page_browse", "Browse all editions"))}</a>'
        '</div>'
        '</div>'
        '</div>'
        '</section>'
        f'<nav class="filter-bar" aria-label="{html.escape(copy.get("filter_aria", "Filter by region"))}">'
        f'<div class="filter-inner">{tab_html}</div>'
        '</nav>'
        '<div class="page-layout">'
        '<section class="content-column">'
        '<div class="feed-head">'
        '<div>'
        f'<p class="section-kicker">{html.escape(copy.get("latest_briefing", "Latest briefing"))}</p>'
        f'<h2 class="feed-title">{html.escape(copy.get("story_board", "Story board"))}</h2>'
        '</div>'
        f'<p class="feed-summary" id="feed-summary">{html.escape(feed_summary_default)}</p>'
        '</div>'
        f'<div class="card-feed" id="card-feed">{cards_html}</div>'
        f'<p class="empty-filter-state" id="empty-filter-state" hidden>{html.escape(copy.get("empty_filter", ""))}</p>'
        '</section>'
        '</div>'
        f'<p class="section-back edition-back">'
        f'<a class="section-back-link" href="{archive_path}">{html.escape(copy.get("edition_page_browse", "Browse all editions"))}</a> · '
        f'<a class="section-back-link" href="{home_url}">{html.escape(copy.get("edition_page_back", "Back"))}</a></p>'
    )
    filter_script = (
        '<script>'
        '(function(){'
        'var tabs=document.querySelectorAll(".filter-tab");'
        'var feed=document.getElementById("card-feed");'
        'var summary=document.getElementById("feed-summary");'
        'var empty=document.getElementById("empty-filter-state");'
        # Card-click delegation: any click anywhere inside a card with a data-url
        # triggers the inner card-link anchor. Mirrors the homepage behaviour so
        # edition / archive pages feel the same.
        'if(feed){'
        'feed.addEventListener("click",function(e){'
        # Let real anchors, buttons, and region chips handle their own clicks.
        'if(e.target.closest("a,button,.card-region-btn"))return;'
        'var card=e.target.closest(".card[data-url]");'
        'if(!card)return;'
        'var anchor=card.querySelector("a.card-link");'
        'if(anchor)anchor.click();'
        '});'
        '}'
        'if(!tabs.length||!feed)return;'
        'var cards=Array.prototype.slice.call(feed.querySelectorAll(".card"));'
        'tabs.forEach(function(tab){'
        'tab.addEventListener("click",function(){'
        'var filter=tab.getAttribute("data-filter")||"All";'
        'tabs.forEach(function(t){t.classList.toggle("active",t===tab);t.setAttribute("aria-pressed",t===tab?"true":"false");});'
        'var visible=0;'
        'cards.forEach(function(card){var reg=card.getAttribute("data-region")||"";var match=filter==="All"||reg===filter;card.style.display=match?"":"none";if(match)visible+=1;});'
        'if(empty)empty.hidden=visible!==0;'
        'if(summary){summary.textContent=visible+" "+(visible===1?"story":"stories")+(filter==="All"?"":" · "+filter);}'
        '});});})();'
        '</script>'
    )
    body_html = body_html + filter_script
    extra_head = placeholder_registry_script
    page_title = f"{html.escape(archive_meta.get('label', edition_id))} · {SITE_TITLE}"
    # Canonical URL must match the file path, not the language home root.
    if language == "hi":
        canonical = f"{SITE_URL}/newsletters/hi/{edition_id}/"
    else:
        canonical = f"{SITE_URL}/newsletters/{edition_id}/"
    return _render_skeleton(
        base,
        page_title=page_title,
        page_desc=html.escape(copy.get("site_desc", SITE_DESC)),
        robots="index,follow",
        canonical=canonical,
        body_class="edition-section-page",
        body_html=body_html,
        extra_head=extra_head,
    )


def build_terms_html(generated_at: str) -> str:
    """Render the Terms of Service page (English only)."""
    base = _section_page_defaults("en", generated_at, depth=1)
    effective_date = "1 January 2026"
    body_html = (
        '<section class="section-shell about-page">'
        '<p class="section-eyebrow">Legal</p>'
        '<h1 class="section-heading">Terms of Service</h1>'
        '<div class="section-body">'
        f'<p><strong>Effective date:</strong> {effective_date}</p>'
        '<p>GeoPulse is a free, automated news aggregation service that curates geopolitics headlines from publicly available RSS feeds and third-party news sources. By using this site or the GeoPulse mobile application, you agree to these terms.</p>'
        '<h2>1. Content and Sources</h2>'
        '<p>GeoPulse does not produce original journalism. All article titles, summaries, and links belong to their respective publishers. Summaries are generated by AI and may contain errors or omissions. Always follow the source link for the full, authoritative article.</p>'
        '<h2>2. No Warranties</h2>'
        '<p>GeoPulse is provided "as is" without warranties of any kind. We make no guarantee of accuracy, completeness, or timeliness. News information changes rapidly; use your judgement before acting on anything you read here.</p>'
        '<h2>3. Third-Party Links</h2>'
        '<p>This service links to third-party websites. We are not responsible for the content, privacy practices, or availability of those sites.</p>'
        '<h2>4. Acceptable Use</h2>'
        '<p>You may use GeoPulse for personal, non-commercial purposes. You may not scrape, redistribute, or commercialise the aggregated content in bulk without permission from the original publishers.</p>'
        '<h2>5. Changes</h2>'
        '<p>We may update these terms at any time. Continued use of the service after changes constitutes acceptance of the revised terms.</p>'
        '<h2>6. Governing Law</h2>'
        '<p>These terms are governed by the laws of India. Any disputes shall be subject to the exclusive jurisdiction of the courts of Mumbai, Maharashtra.</p>'
        '<h2>Contact</h2>'
        f'<p>Questions? Reach the editor at <a href="{BRAND["editor_website"]}" target="_blank" rel="noopener">{_EDITOR_WEBSITE_DISPLAY}</a>.</p>'
        '</div>'
        f'<p class="section-back"><a class="section-back-link" href="{base["home_url"]}">← Back to the front page</a></p>'
        '</section>'
    )
    return _render_skeleton(
        base,
        page_title=html.escape(f"Terms of Service · {SITE_TITLE}"),
        page_desc="Terms of Service for the GeoPulse geopolitics news aggregator.",
        robots="index,follow",
        canonical=f"{SITE_URL}/terms/",
        body_class="about-section-page",
        body_html=body_html,
    )


def build_privacy_html(generated_at: str) -> str:
    """Render the Privacy Policy page (English only)."""
    base = _section_page_defaults("en", generated_at, depth=1)
    effective_date = "1 January 2026"
    body_html = (
        '<section class="section-shell about-page">'
        '<p class="section-eyebrow">Legal</p>'
        '<h1 class="section-heading">Privacy Policy</h1>'
        '<div class="section-body">'
        f'<p><strong>Effective date:</strong> {effective_date}</p>'
        '<p>GeoPulse respects your privacy. This policy explains what data is collected when you use the GeoPulse website and mobile application.</p>'
        '<h2>1. Data We Do Not Collect</h2>'
        '<p>GeoPulse does not require account registration. We do not collect your name, email address, location, or any personally identifiable information through the website.</p>'
        '<h2>2. Analytics</h2>'
        '<p>The website is hosted on GitHub Pages. GitHub may collect standard server logs (IP address, browser type, referring URL) as described in the <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub Privacy Statement</a>. GeoPulse itself does not run additional analytics scripts.</p>'
        '<h2>3. Mobile App</h2>'
        '<p>The GeoPulse mobile app fetches publicly available news data from our feed. If push notifications are enabled, your device token is used solely to deliver news alerts and is not shared with third parties. We use Firebase Cloud Messaging (Google) to send notifications; see the <a href="https://firebase.google.com/support/privacy" target="_blank" rel="noopener noreferrer">Firebase Privacy Policy</a> for details.</p>'
        '<h2>4. Cookies and Local Storage</h2>'
        '<p>The website uses browser localStorage only to remember your theme preference (dark/light mode). No tracking cookies are set.</p>'
        '<h2>5. Third-Party Content</h2>'
        '<p>Articles link to third-party news sites. Those sites have their own privacy policies which we do not control.</p>'
        '<h2>6. Changes</h2>'
        '<p>We may update this policy. The effective date above reflects the most recent revision.</p>'
        '<h2>Contact</h2>'
        f'<p>Privacy questions? Contact the editor at <a href="{BRAND["editor_website"]}" target="_blank" rel="noopener">{_EDITOR_WEBSITE_DISPLAY}</a>.</p>'
        '</div>'
        f'<p class="section-back"><a class="section-back-link" href="{base["home_url"]}">← Back to the front page</a></p>'
        '</section>'
    )
    return _render_skeleton(
        base,
        page_title=html.escape(f"Privacy Policy · {SITE_TITLE}"),
        page_desc="Privacy Policy for the GeoPulse geopolitics news aggregator.",
        robots="index,follow",
        canonical=f"{SITE_URL}/privacy/",
        body_class="about-section-page",
        body_html=body_html,
    )


def write_section_pages(archives: list[dict], generated_at: str, language: str = "en") -> None:
    """Write the About, Archive index, and per-edition HTML files to disk."""
    if language == "hi":
        section_root = SITE_HI_DIR
        archive_dir_src = ARCHIVE_HI_DIR
        edition_root = SITE_ARCHIVE_HI_DIR
    else:
        section_root = SITE_DIR
        archive_dir_src = ARCHIVE_DIR
        edition_root = SITE_ARCHIVE_DIR

    about_dir = os.path.join(section_root, "about")
    os.makedirs(about_dir, exist_ok=True)
    with open(os.path.join(about_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_about_html(generated_at, language=language))
    log.info("Wrote %s", os.path.join(about_dir, "index.html"))

    archive_dir = os.path.join(section_root, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    with open(os.path.join(archive_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_archive_html(archives, generated_at, language=language))
    log.info("Wrote %s", os.path.join(archive_dir, "index.html"))

    if language == "en":
        terms_dir = os.path.join(SITE_DIR, "terms")
        os.makedirs(terms_dir, exist_ok=True)
        with open(os.path.join(terms_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(build_terms_html(generated_at))
        log.info("Wrote %s", os.path.join(terms_dir, "index.html"))

        privacy_dir = os.path.join(SITE_DIR, "privacy")
        os.makedirs(privacy_dir, exist_ok=True)
        with open(os.path.join(privacy_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(build_privacy_html(generated_at))
        log.info("Wrote %s", os.path.join(privacy_dir, "index.html"))

    edition_id_re = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}$")
    if os.path.isdir(edition_root):
        for name in os.listdir(edition_root):
            full = os.path.join(edition_root, name)
            if not os.path.isdir(full):
                continue
            if not edition_id_re.match(name):
                continue
            try:
                shutil.rmtree(full)
            except OSError as exc:
                log.warning("Could not remove stale edition dir %s: %s", full, exc)

    written = 0
    for archive in (archives or []):
        edition_id = (archive.get("filename") or "").replace(".md", "")
        if not edition_id:
            continue
        archive_md = os.path.join(archive_dir_src, archive.get("filename", ""))
        stories = _parse_archive_markdown(archive_md)
        if not stories:
            continue
        ed_dir = os.path.join(edition_root, edition_id)
        os.makedirs(ed_dir, exist_ok=True)
        with open(os.path.join(ed_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(build_edition_html(edition_id, archive, stories, generated_at, language=language))
        written += 1
    log.info("Wrote %d per-edition pages under %s", written, edition_root)

# ── RSS feed ──────────────────────────────────────────────────────────────────

def build_rss(articles: list[dict], archives: list[dict]) -> str:
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = ""
    for art in articles[:20]:
        t   = html.escape(art.get("title", ""))
        u   = html.escape(art.get("url", ""))
        s   = html.escape(art.get("summary", ""))
        src = html.escape(art.get("source", ""))
        pub = art.get("published_at", "")
        try:
            pub_rfc = datetime.fromisoformat(pub.replace("Z", "+00:00"))\
                              .strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            pub_rfc = now_rfc
        items += f"""
    <item>
      <title>{t}</title>
      <link>{u}</link>
      <guid isPermaLink="true">{u}</guid>
      <pubDate>{pub_rfc}</pubDate>
      <source url="{SITE_URL}/feed.xml">{src}</source>
      <description>{s}</description>
    </item>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{SITE_TITLE}. Geopolitics in brief</title>
    <link>{SITE_URL}</link>
    <description>{SITE_DESC}</description>
    <language>en-us</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    {items}
  </channel>
</rss>"""


def write_nojekyll_marker() -> None:
    """Ensure GitHub Pages serves files as-is without Jekyll processing."""
    with open(NOJEKYLL_PATH, "w", encoding="utf-8") as f:
        f.write("\n")


def sync_cname_from_brand() -> None:
    """Write or remove site/CNAME based on brand.custom_domain.

    When brand.custom_domain is set to a non-empty value, this writes it to
    site/CNAME so GitHub Pages serves the site at that domain. When unset
    (the default for a fresh fork of the template), any stale site/CNAME
    inherited from the original owner is deleted so a fork never silently
    collides with someone else's domain. Idempotent and safe to call every
    build."""
    cname_path = os.path.join(SITE_DIR, "CNAME")
    domain = (BRAND.get("custom_domain") or "").strip()
    # Strip any accidental protocol / trailing path a user might paste.
    domain = re.sub(r"^https?://", "", domain).strip("/ ")
    if domain:
        with open(cname_path, "w", encoding="utf-8") as f:
            f.write(domain + "\n")
        log.info("Wrote %s with custom domain %s", cname_path, domain)
    else:
        if os.path.exists(cname_path):
            try:
                os.remove(cname_path)
                log.info("Removed stale %s (brand.custom_domain is empty)", cname_path)
            except OSError as exc:
                log.warning("Could not remove %s: %s", cname_path, exc)


def write_directory_index_guard(path: str, target: str) -> None:
    """Write a minimal index file to avoid exposing raw directory paths."""
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <meta name="robots" content="noindex,follow" />
  <title>Redirecting...</title>
  <meta http-equiv="refresh" content="0; url={target}" />
  <script>window.location.replace({json.dumps(target)});</script>
</head>
<body>
  <p>Redirecting to <a href="http://example.com">{html.escape(target)}</a>...</p>
<script>(function(){{var btn=document.querySelector(".language-switch");if(!btn)return;btn.addEventListener("click",function(e){{e.preventDefault();var p=location.pathname,s=location.search||"",h=location.hash||"",t;var onHi=(p==="/hi"||p==="/hi/"||p.indexOf("/hi/")===0||p.indexOf("/newsletters/hi/")===0);if(onHi){{if(p.indexOf("/newsletters/hi/")===0){{t="/newsletters/"+p.substring(16);}}else if(p==="/hi"||p==="/hi/"){{t="/";}}else{{t=p.substring(3)||"/";}}}}else{{if(p.indexOf("/newsletters/")===0&&p.indexOf("/newsletters/hi/")!==0){{t="/newsletters/hi/"+p.substring(13);}}else if(p==="/"||p===""){{t="/hi/";}}else{{t="/hi"+p;}}}}s=s.replace(/[?&]lang=[^&]*/g,"").replace(/^&/,"?");if(s==="?")s="";location.href=t+s+h;}});}})();</script>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def write_directory_guards() -> None:
    """Create explicit directory index files for archive paths."""
    write_directory_index_guard(
      os.path.join(SITE_ARCHIVE_DIR, "index.html"),
      f"{SITE_URL}/",
    )
    write_directory_index_guard(
      os.path.join(SITE_ARCHIVE_HI_DIR, "index.html"),
      f"{HI_SITE_URL}/",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = load_config()
    display_tz = get_display_timezone(cfg)
    os.makedirs(SITE_DIR, exist_ok=True)
    os.makedirs(SITE_HI_DIR, exist_ok=True)

    if not os.path.exists(JSON_PATH):
        log.error("newsletter.json not found — run summarize.py first.")
        raise SystemExit(1)

    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    articles     = data.get("articles", [])
    generated_at = data.get("generated_at", datetime.now(timezone.utc).isoformat())
    digest       = data.get("digest", {}) or {}

    # Sort newest-first so the latest stories always appear at the top.
    articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)

    # Per-edition cap mirrors config.yml max_articles so the site never drifts
    # out of sync with summarize.py.
    per_edition_cap = int(cfg.get("max_articles", 25) or 25)

    def _title_of(a: dict, lang: str) -> str:
        if lang == "hi":
            return (a.get("translations", {}) or {}).get("hi", {}).get("title") or a.get("title", "")
        return a.get("title", "")

    def _summary_of(a: dict, lang: str) -> str:
        if lang == "hi":
            return (a.get("translations", {}) or {}).get("hi", {}).get("summary") or a.get("summary", "")
        return a.get("summary", "")

    def _english_ok(a: dict) -> bool:
        """Accept only articles whose title/summary read as English."""
        if a.get("language") == "hi":
            return False
        title = _title_of(a, "en")
        summary = _summary_of(a, "en")
        # Reject any article whose title is Devanagari-dominant.
        if _is_devanagari_dominant(title):
            return False
        # Require the title to be visibly Latin so odd unicode does not slip in.
        if title and not _is_latin_dominant(title):
            return False
        # Summary is allowed to be thin, but if it exists it must be Latin.
        return True

    def _hindi_ok(a: dict) -> bool:
        """Accept only articles with a genuine Hindi title and summary.

        An article whose source is English but whose translation fell back to
        English is rejected here so the Hindi page never shows Latin-script
        headlines.
        """
        title = _title_of(a, "hi")
        summary = _summary_of(a, "hi")
        if not _is_devanagari_dominant(title):
            return False
        # If there is a summary, it must be Devanagari-dominant too.
        if summary and not _is_devanagari_dominant(summary):
            return False
        return True

    # Route each article to the correct site by language tag and by script.
    # Strict filtering prevents English headlines from bleeding into the Hindi
    # edition (when translation fell back) and vice versa.

    en_articles = [a for a in articles if _english_ok(a)][:per_edition_cap]
    hi_articles = [a for a in articles if _hindi_ok(a)][:per_edition_cap]
    log.info(
        "Rendering %d English and %d Hindi stories (cap %d per edition).",
        len(en_articles), len(hi_articles), per_edition_cap,
    )

    archives = archive_newsletter(cfg, display_tz, language="en")
    archives_hi = archive_newsletter(cfg, display_tz, language="hi")

    html_out = build_html(en_articles, generated_at, archives, display_tz, language="en", digest=digest.get("en", ""), editor_note=cfg.get("editor_note"))
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html_out)
    log.info("Wrote %s", INDEX_PATH)

    html_hi_out = build_html(hi_articles, generated_at, archives_hi, display_tz, language="hi", digest=digest.get("hi", ""), editor_note=cfg.get("editor_note"))
    with open(HI_INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html_hi_out)
    log.info("Wrote %s", HI_INDEX_PATH)

    rss_out = build_rss(en_articles, archives)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        f.write(rss_out)
    log.info("Wrote %s", FEED_PATH)

    write_nojekyll_marker()
    log.info("Wrote %s", NOJEKYLL_PATH)

    sync_cname_from_brand()

    # Copy newsletter.json into site/ so the mobile app can fetch it directly
    # from the same domain (pulse.lavkesh.com/newsletter.json).
    site_json_path = os.path.join(SITE_DIR, "newsletter.json")
    shutil.copy2(JSON_PATH, site_json_path)
    log.info("Copied newsletter.json → %s", site_json_path)

    write_directory_guards()
    log.info("Wrote directory index guards for archive paths")

    # Section pages (About, Archive index, per-edition front pages). These
    # run after the homepage so the site/ tree is in a known shape before
    # they touch /newsletters/ and /archive/.
    write_section_pages(archives, generated_at, language="en")
    write_section_pages(archives_hi, generated_at, language="hi")


if __name__ == "__main__":
    main()