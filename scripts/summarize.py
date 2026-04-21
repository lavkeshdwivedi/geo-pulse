#!/usr/bin/env python3
"""
summarize.py — Reads raw_news.json and writes:
  - newsletter.json  (structured per-article data with 40-50 word summaries,
                      capped at 60)
  - newsletter.md    (markdown archive copy)

Each article gets a summary that ends when the story is complete. Target is
40 to 50 words, hard ceiling is 60. That range delivers a tight two-sentence
brief that fits the card grid without being truncated by the CSS line-clamp
on mobile.

LLM providers: see scripts/llm_client.py. The default chain is free-tier
only, Groq then Gemini, each with a small model pool. Set GROQ_API_KEY or
GEMINI_API_KEY to enable summarization. With no keys set, the pipeline falls
back to a clean description-truncation path.

Token notes: per-story rules live in module-level system prompts so they are
sent once per request instead of being rebuilt per call. User prompts carry
only the title and source text.
"""

import json
import html
import logging
import os
import re
import textwrap
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yml")
STYLE_PATH  = os.path.join(ROOT, "STYLE.md")
INPUT_PATH  = os.path.join(ROOT, "raw_news.json")
JSON_PATH   = os.path.join(ROOT, "newsletter.json")
MD_PATH     = os.path.join(ROOT, "newsletter.md")
MD_HI_PATH  = os.path.join(ROOT, "newsletter.hi.md")


# ---------------------------------------------------------------------------
# Brand helpers — read site title / url from config.yml so newsletter
# markdown rebrands cleanly in a fork. Defaults preserve the GeoPulse output.
# ---------------------------------------------------------------------------
_BRAND_DEFAULTS = {
    "site_title": "GeoPulse",
    "site_url": "https://pulse.lavkesh.com",
}


def _load_brand_from_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return dict(_BRAND_DEFAULTS)
    brand = data.get("brand") or {}
    return {
        "site_title": brand.get("site_title", _BRAND_DEFAULTS["site_title"]),
        "site_url": brand.get("site_url", _BRAND_DEFAULTS["site_url"]),
    }


_BRAND = _load_brand_from_config()
_SITE_TITLE = _BRAND["site_title"]
_SITE_URL_DISPLAY = _BRAND["site_url"].replace("https://", "").replace("http://", "").rstrip("/")

BASE_URL = _BRAND["site_url"]

# Region labels live in scripts/languages.py now so adding a new language
# is one dict entry away. HINDI_REGION_LABELS stays as a name alias for the
# many call sites throughout this module that already reference it.
from languages import region_labels_for, localize_region, language_codes  # noqa: E402

HINDI_REGION_LABELS: dict[str, str] = region_labels_for("hi")


# Replace stiff machine phrases with day-to-day Hindi phrasing.
HINDI_COLLOQUIAL_REPLACEMENTS: list[tuple[str, str]] = [
    ("संयुक्त राज्य अमेरिका", "अमेरिका"),
    ("वार्ता", "बातचीत"),
    ("संघर्ष", "टकराव"),
    ("संघर्ष विराम", "सीजफायर"),
    ("तत्काल", "फौरन"),
    ("उक्त", "यह"),
    ("प्रशासन", "सरकार"),
    ("द्वारा", "की तरफ से"),
    ("अतएव", "इसलिए"),
    ("किंतु", "लेकिन"),
    ("यद्यपि", "हालांकि"),
    # Spacecraft / vehicle landings
    ("नीचे गिर गया", "वापस धरती पर उतरा"),
    ("नीचे गिरी", "वापस धरती पर उतरी"),
    ("नीचे गिरा", "उतरा"),
    # Simpler everyday equivalents
    ("एपोथोसिस", "चरमसीमा"),
    ("अभूतपूर्व रूप से रोमांचक", "बेहद रोमांचक"),
    ("अभूतपूर्व रूप से", "बेमिसाल"),
    ("खंडित", "बंटी हुई"),
    ("विखंडित", "बंटी हुई"),
    ("गहरे अविश्वास को पाटना", "गहरे अविश्वास को दूर करना"),
]


# Financial / technical abbreviations that must not be transliterated.
_ABBREV_RE = re.compile(
    r'\b(?:FX|FI|PLN|USD|EUR|GBP|JPY|CHF|AUD|CAD|NOK|SEK|DKK|HUF|CZK|'
    r'SPW|ETF|NFO|IPO|GDP|KOSPI|KOSDAQ|DAX|FTSE|CAC|SNB|ECB|'
    r'NATO|G7|G20|WTO|IMF|UN|BTC|ETH)\b'
)

# Devanagari block, used throughout for script detection (language branch in
# punctuation normalisation, em dash handling, terminator selection).
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")


def _protect_abbrevs(text: str) -> tuple[str, list[str]]:
    """Replace abbreviations with numbered placeholders before translation."""
    saved: list[str] = []

    def _sub(m: re.Match) -> str:  # type: ignore[type-arg]
        saved.append(m.group(0))
        # Wrap with spaces so Google Translate treats it as a separate token.
        return f" XABR{len(saved) - 1}Z "

    return _ABBREV_RE.sub(_sub, text), saved


def _restore_abbrevs(text: str, saved: list[str]) -> str:
    """Restore original abbreviations after translation."""
    for i, orig in enumerate(saved):
        # Simple replace keeps whatever spacing came from translation.
        text = text.replace(f"XABR{i}Z", orig)
    # Collapse any double-spaces introduced by the wrapping.
    return re.sub(r"  +", " ", text).strip()


def decode_entities(text: str) -> str:
    """Decode HTML entities, handling double-encoded content from feeds.

    Also normalises em dashes. In English text an em dash is commonly a
    sentence-level break so we turn it into ". ". In Hindi (Devanagari)
    text the same character is almost always a mid-clause break, so using
    a period would create a fake sentence boundary that the summariser
    would then treat as two separate sentences. For Hindi we replace it
    with a space instead.
    """
    if not text:
        return ""
    current = text
    for _ in range(3):
        decoded = html.unescape(current)
        if decoded == current:
            break
        current = decoded
    # Context-aware em dash handling. If either neighbour is Devanagari,
    # drop it in favour of a space. Otherwise use the old ". " replacement.
    def _em_dash_sub(m: re.Match) -> str:  # type: ignore[type-arg]
        left = m.group(1) or ""
        right = m.group(2) or ""
        if _DEVANAGARI_RE.search(left) or _DEVANAGARI_RE.search(right):
            return left + " " + right
        return left + ". " + right

    current = re.sub(r"(.?)—(.?)", _em_dash_sub, current)
    return re.sub(r"\s+", " ", current).strip()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def colloquialize_hindi(text: str) -> str:
    polished = normalize_text(text)
    for src, dst in HINDI_COLLOQUIAL_REPLACEMENTS:
        polished = polished.replace(src, dst)
    # Hindi sentences must end on danda (।). If Google Translate (or anything
    # upstream) gave us a trailing English period after a Devanagari clause,
    # swap it back. We only touch sentence-ending periods, not mid-sentence
    # punctuation like abbreviations.
    polished = re.sub(r"([\u0900-\u097f])\s*\.(\s|$)", r"\1।\2", polished)
    return polished.strip()


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
# Full UN-recognised countries grouped by region, plus major capitals and
# common non-state entities. English + Hindi (Devanagari) together so the
# same classifier works for both pipelines. Short names wrapped in spaces
# (" us ", " uk ", " un ") to avoid substring collisions like "russia" or
# "fund". Order of regions is significant: the first region to match any
# keyword wins, and Global / Multilateral sits last so specific-region
# coverage always beats it.
REGION_KEYWORDS: dict[str, list[str]] = {
    "Middle East & Africa": [
        # Middle East countries (English)
        "israel", "palestine", "palestinian", "gaza", "west bank",
        "iran", "iranian", "saudi arabia", "saudi", "yemen", "yemeni",
        "syria", "syrian", "iraq", "iraqi", "lebanon", "lebanese",
        "jordan", "jordanian", "kuwait", "qatar", "bahrain",
        "oman", "omani", " uae ", "united arab emirates", "dubai",
        "abu dhabi", "turkey", "turkish", "istanbul", "ankara",
        # Africa countries (English)
        "egypt", "egyptian", "libya", "libyan", "tunisia", "tunisian",
        "algeria", "algerian", "morocco", "moroccan", "western sahara",
        "sudan", "sudanese", "south sudan", "ethiopia", "ethiopian",
        "eritrea", "somalia", "somali", "djibouti", "kenya", "kenyan",
        "uganda", "tanzania", "rwanda", "burundi", "congo", "drc",
        "central african republic", "chad", "cameroon", "nigeria",
        "nigerian", "niger", "mali ", "burkina faso", "senegal",
        "gambia", "mauritania", "cape verde", "guinea-bissau",
        "guinea", "sierra leone", "liberia", "cote d'ivoire",
        "ivory coast", "ghana", "togo", "benin", "sao tome",
        "equatorial guinea", "gabon", "angola", "zambia", "malawi",
        "zimbabwe", "mozambique", "botswana", "namibia", "south africa",
        "lesotho", "eswatini", "swaziland", "madagascar", "mauritius",
        "comoros", "seychelles", "africa", "african union",
        # Non-state actors + capitals
        "hamas", "houthi", "hezbollah", "muslim brotherhood", "isis",
        "tehran", "jerusalem", "tel aviv", "ramallah", "riyadh",
        "doha", "amman", "baghdad", "damascus", "beirut", "cairo",
        "tripoli", "algiers", "tunis", "rabat", "khartoum", "nairobi",
        "addis ababa", "lagos", "abuja", "accra", "dakar", "kinshasa",
        "johannesburg", "pretoria", "cape town", "harare", "lusaka",
        # Hindi (Devanagari)
        "इजरायल", "इजराइल", "इज़राइल", "फिलिस्तीन", "फ़िलिस्तीन",
        "गाजा", "ग़ाज़ा", "वेस्ट बैंक", "ईरान", "ईरानी",
        "सऊदी अरब", "सऊदी", "यमन", "सीरिया", "इराक", "लेबनान",
        "जॉर्डन", "कुवैत", "कतर", "बहरीन", "ओमान", "यूएई",
        "संयुक्त अरब अमीरात", "दुबई", "अबू धाबी", "तुर्की",
        "इस्तांबुल", "अंकारा",
        "मिस्र", "लीबिया", "ट्यूनीशिया", "अल्जीरिया", "मोरक्को",
        "सूडान", "दक्षिण सूडान", "इथियोपिया", "इरिट्रिया",
        "सोमालिया", "जिबूती", "केन्या", "युगांडा", "तंजानिया",
        "रवांडा", "बुरुंडी", "कांगो", "चाड", "कैमरून",
        "नाइजीरिया", "नाइजर", "माली", "बुर्किना फासो", "सेनेगल",
        "गिनी", "सिएरा लियोन", "लाइबेरिया", "आइवरी कोस्ट",
        "घाना", "टोगो", "बेनिन", "गैबॉन", "अंगोला", "जाम्बिया",
        "मलावी", "जिम्बाब्वे", "मोजाम्बिक", "बोत्सवाना", "नामीबिया",
        "दक्षिण अफ्रीका", "लेसोथो", "स्वाज़ीलैंड", "मेडागास्कर",
        "मॉरीशस", "सेशेल्स", "अफ्रीका", "अफ्रीकी संघ",
        "तेहरान", "यरूशलेम", "जेरूसलम", "तेल अवीव", "रामल्ला",
        "रियाद", "दोहा", "अम्मान", "बगदाद", "दमिश्क", "बेरूत",
        "काहिरा", "त्रिपोली", "अल्जीयर्स", "ट्यूनिस", "रबात",
        "खार्तूम", "नैरोबी", "अदीस अबाबा", "लागोस", "अबुजा",
        "अक्रा", "डकार", "किंशासा", "जोहान्सबर्ग", "प्रिटोरिया",
        "केप टाउन", "हरारे", "लुसाका",
        "हमास", "हूती", "हिज़बुल्लाह", "हिजबुल्लाह", "आईएसआईएस",
        "मुस्लिम ब्रदरहुड",
    ],
    "Europe & Russia": [
        # Russia + former Soviet Europe (English)
        "russia", "russian", "putin", "kremlin", "moscow",
        "ukraine", "ukrainian", "zelensky", "kyiv", "kiev",
        "belarus", "lukashenko", "minsk",
        "moldova", "chisinau",
        "georgia", "tbilisi", "armenia", "yerevan",
        "azerbaijan", "baku",
        # EU / Western Europe (English)
        "european union", " eu ", "nato",
        "france", "french", "paris", "macron",
        "germany", "german", "berlin", "merkel", "scholz",
        "italy", "italian", "rome", "meloni",
        "spain", "spanish", "madrid", "barcelona",
        "portugal", "portuguese", "lisbon",
        "united kingdom", " uk ", "britain", "british", "london",
        "ireland", "irish", "dublin",
        "netherlands", "dutch", "amsterdam", "the hague",
        "belgium", "belgian", "brussels",
        "luxembourg", "switzerland", "swiss", "bern", "geneva",
        "austria", "vienna",
        # Central / Eastern Europe
        "poland", "polish", "warsaw",
        "czech", "prague", "slovakia", "bratislava",
        "hungary", "hungarian", "budapest",
        "romania", "romanian", "bucharest",
        "bulgaria", "bulgarian", "sofia",
        "greece", "greek", "athens",
        "cyprus", "nicosia", "malta", "valletta",
        "croatia", "zagreb", "slovenia", "ljubljana",
        "serbia", "serbian", "belgrade",
        "bosnia", "sarajevo",
        "montenegro", "podgorica",
        "albania", "tirana", "kosovo", "pristina",
        "north macedonia", "macedonia", "skopje",
        # Nordics + Baltics
        "lithuania", "vilnius", "latvia", "riga",
        "estonia", "tallinn", "baltics",
        "finland", "finnish", "helsinki",
        "sweden", "swedish", "stockholm",
        "norway", "norwegian", "oslo",
        "denmark", "danish", "copenhagen",
        "iceland", "reykjavik",
        "vatican", "holy see",
        # Hindi
        "रूस", "रूसी", "पुतिन", "क्रेमलिन", "मॉस्को",
        "यूक्रेन", "जेलेंस्की", "कीव", "बेलारूस", "मिन्स्क",
        "मोल्दोवा", "जॉर्जिया", "आर्मेनिया", "अज़रबैजान", "बाकू",
        "यूरोपीय संघ", "नाटो",
        "फ्रांस", "फ्रांसीसी", "पेरिस", "मैक्रों",
        "जर्मनी", "जर्मन", "बर्लिन", "मर्केल", "शोल्ज़",
        "इटली", "रोम", "मेलोनी",
        "स्पेन", "मैड्रिड", "बार्सिलोना",
        "पुर्तगाल", "लिस्बन",
        "ब्रिटेन", "यूनाइटेड किंगडम", "इंग्लैंड", "लंदन",
        "आयरलैंड", "डबलिन",
        "नीदरलैंड", "एम्स्टर्डम", "हेग",
        "बेल्जियम", "ब्रसेल्स",
        "लक्जमबर्ग", "स्विट्जरलैंड", "बर्न", "जेनेवा",
        "ऑस्ट्रिया", "वियना",
        "पोलैंड", "वारसॉ",
        "चेक", "प्राग", "स्लोवाकिया",
        "हंगरी", "बुडापेस्ट",
        "रोमानिया", "बुखारेस्ट",
        "बुल्गारिया", "सोफिया",
        "ग्रीस", "यूनान", "एथेंस",
        "साइप्रस", "माल्टा",
        "क्रोएशिया", "ज़ाग्रेब",
        "स्लोवेनिया", "सर्बिया", "बेलग्रेड",
        "बोस्निया", "साराजेवो",
        "मॉन्टेनेग्रो", "अल्बानिया", "तिराना",
        "कोसोवो", "मैसेडोनिया",
        "लिथुआनिया", "लातविया", "एस्टोनिया", "बाल्टिक",
        "फिनलैंड", "हेलसिंकी",
        "स्वीडन", "स्टॉकहोम",
        "नॉर्वे", "ओस्लो",
        "डेनमार्क", "कोपेनहेगन",
        "आइसलैंड", "वेटिकन",
    ],
    "Asia-Pacific": [
        # East Asia
        "china", "chinese", "beijing", "shanghai", "hong kong",
        "taiwan", "taipei", "japan", "japanese", "tokyo",
        "south korea", "north korea", "korea", "seoul", "pyongyang",
        "mongolia", "ulaanbaatar",
        # South Asia
        "india", "indian", "delhi", "new delhi", "mumbai",
        "pakistan", "pakistani", "islamabad", "karachi",
        "bangladesh", "dhaka",
        "sri lanka", "colombo", "nepal", "kathmandu",
        "bhutan", "thimphu", "maldives", "male ",
        "afghanistan", "kabul", "taliban",
        # Southeast Asia
        "myanmar", "burma", "yangon", "naypyidaw",
        "thailand", "bangkok", "vietnam", "hanoi", "ho chi minh",
        "laos", "vientiane", "cambodia", "phnom penh",
        "malaysia", "kuala lumpur",
        "singapore", "indonesia", "jakarta",
        "philippines", "manila",
        "brunei", "east timor", "timor-leste",
        # Central Asia
        "kazakhstan", "astana", "nur-sultan",
        "uzbekistan", "tashkent",
        "kyrgyzstan", "bishkek",
        "tajikistan", "dushanbe",
        "turkmenistan", "ashgabat",
        # Oceania
        "australia", "australian", "canberra", "sydney",
        "new zealand", "wellington", "auckland",
        "fiji", "papua new guinea", "port moresby",
        "solomon islands", "vanuatu", "samoa", "tonga",
        "kiribati", "tuvalu", "palau", "micronesia",
        "marshall islands", "nauru",
        # Regional blocs + hotspots
        "asean", "south china sea", "indo-pacific", "quad",
        # Hindi
        "चीन", "चीनी", "बीजिंग", "शंघाई", "हांगकांग",
        "ताइवान", "ताइपे", "जापान", "जापानी", "टोक्यो",
        "दक्षिण कोरिया", "उत्तर कोरिया", "कोरिया", "सियोल",
        "प्योंगयांग", "मंगोलिया",
        "भारत", "भारतीय", "दिल्ली", "नई दिल्ली", "मुंबई",
        "पाकिस्तान", "इस्लामाबाद", "कराची",
        "बांग्लादेश", "ढाका",
        "श्रीलंका", "कोलंबो", "नेपाल", "काठमांडू",
        "भूटान", "मालदीव",
        "अफगानिस्तान", "अफ़ग़ानिस्तान", "काबुल", "तालिबान",
        "म्यांमार", "बर्मा", "यंगून", "नेपीडॉ",
        "थाईलैंड", "बैंकॉक",
        "वियतनाम", "हनोई", "हो ची मिन्ह",
        "लाओस", "कंबोडिया", "नोम पेन्ह",
        "मलेशिया", "कुआलालंपुर",
        "सिंगापुर", "इंडोनेशिया", "जकार्ता",
        "फिलीपींस", "मनीला",
        "ब्रुनेई", "पूर्वी तिमोर",
        "कजाकिस्तान", "अस्ताना",
        "उज्बेकिस्तान", "ताशकंद",
        "किर्गिस्तान", "ताजिकिस्तान", "तुर्कमेनिस्तान",
        "ऑस्ट्रेलिया", "आस्ट्रेलिया", "कैनबरा", "सिडनी",
        "न्यूजीलैंड", "वेलिंगटन", "ऑकलैंड",
        "फिजी", "पापुआ न्यू गिनी",
        "सोलोमन", "वानुअतु", "समोआ", "टोंगा",
        "एशिया-प्रशांत", "हिंद-प्रशांत", "क्वाड",
    ],
    "Americas": [
        # North America (English)
        "united states", " us ", " usa ", " u.s. ", "america",
        "american", "biden", "trump", "obama", "harris",
        "white house", "pentagon", "washington", "new york",
        "canada", "canadian", "ottawa", "toronto", "trudeau",
        "mexico", "mexican", "mexico city", "amlo",
        # Central America + Caribbean
        "guatemala", "belize", "honduras", "el salvador",
        "nicaragua", "costa rica", "panama", "panama city",
        "cuba", "cuban", "havana",
        "haiti", "dominican republic", "jamaica",
        "bahamas", "barbados", "trinidad", "puerto rico",
        # South America
        "brazil", "brazilian", "brasilia", "lula", "bolsonaro",
        "argentina", "argentine", "buenos aires", "milei",
        "chile", "santiago", "boric",
        "colombia", "colombian", "bogota",
        "peru", "peruvian", "lima",
        "venezuela", "venezuelan", "caracas", "maduro",
        "ecuador", "quito",
        "bolivia", "la paz",
        "paraguay", "asuncion",
        "uruguay", "montevideo",
        "guyana", "suriname",
        "latin america", "mercosur",
        # Hindi
        "अमेरिका", "अमेरिकी", "संयुक्त राज्य", "यूएस", "यूएसए",
        "बाइडन", "ट्रंप", "ओबामा", "हैरिस",
        "व्हाइट हाउस", "पेंटागन", "वॉशिंगटन", "वाशिंगटन",
        "न्यूयॉर्क",
        "कनाडा", "ओटावा", "टोरंटो", "ट्रूडो",
        "मेक्सिको", "मेक्सिको सिटी",
        "ग्वाटेमाला", "होंडुरास", "अल साल्वाडोर",
        "निकारागुआ", "कोस्टा रिका", "पनामा",
        "क्यूबा", "हवाना",
        "हैती", "डोमिनिकन गणराज्य", "जमैका",
        "बहामास", "बारबाडोस", "त्रिनिदाद", "प्यूर्टो रिको",
        "ब्राजील", "ब्राज़ील", "ब्रासीलिया",
        "अर्जेंटीना", "ब्यूनस आयर्स",
        "चिली", "सैंटियागो",
        "कोलंबिया", "बोगोटा",
        "पेरू", "लीमा",
        "वेनेजुएला", "कराकास", "मादुरो",
        "इक्वाडोर", "क्विटो",
        "बोलिविया", "ला पाज़",
        "पराग्वे", "उरुग्वे", "मोंटेवीडियो",
        "गुयाना", "सूरीनाम",
        "लैटिन अमेरिका", "दक्षिण अमेरिका", "मर्कोसुर",
    ],
    "Global / Multilateral": [
        # English
        "united nations", " un ", " un.", "unsc", "unga",
        "security council", "general assembly",
        "g7", "g20", "g-7", "g-20", "brics", "opec",
        "wto", "imf", "world bank", "world health organization",
        "who ", "unesco", "unicef", "icc", "icj",
        "sanctions", "treaty", "summit", "diplomacy",
        "geopolitics", "international", "globalization",
        "climate change", "cop28", "cop29", "cop30",
        # Hindi
        "संयुक्त राष्ट्र", "यूएन", "यूएनएससी", "यूएनजीए",
        "सुरक्षा परिषद", "महासभा",
        "जी7", "जी20", "जी-7", "जी-20", "ब्रिक्स", "ओपेक",
        "डब्ल्यूटीओ", "आईएमएफ", "विश्व बैंक",
        "विश्व स्वास्थ्य संगठन", "डब्ल्यूएचओ",
        "यूनेस्को", "यूनिसेफ", "आईसीसी", "आईसीजे",
        "प्रतिबंध", "संधि", "शिखर सम्मेलन", "कूटनीति",
        "भू-राजनीति", "अंतरराष्ट्रीय", "अंतर्राष्ट्रीय",
        "वैश्वीकरण", "जलवायु परिवर्तन",
    ],
}

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg["llm_provider"] = os.environ.get("LLM_PROVIDER", cfg.get("llm_provider", "none")).lower()
    cfg["llm_model"]    = os.environ.get("LLM_MODEL",    cfg.get("llm_model", "gpt-4o-mini"))
    cfg["display_timezone"] = os.environ.get("DISPLAY_TIMEZONE", cfg.get("display_timezone", "Asia/Kolkata"))
    cfg["max_articles"] = int(os.environ.get("MAX_ARTICLES", cfg.get("max_articles", 50)))
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


def classify_region(article: dict) -> str:
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for region, keywords in REGION_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return region
    return "World"


def truncate_words(text: str, limit: int = 60) -> str:
    """Keep whole sentences up to `limit` words. Stop when the story is done.

    If the first sentence alone exceeds `limit`, we do NOT hard-cut mid-word.
    Instead we try, in order:
      1. Accept the full first sentence if it is within `limit + 20` words
         (prefer a complete thought over a clean cut).
      2. Otherwise walk back inside the budget to the last clause break
         (semicolon or comma) and end on a period there.
      3. As a final guard, drop trailing connective words ("and", "to", etc.)
         and end on a period. This is the only path that can still leave a
         summary that reads a bit short, but it never ends mid-clause.
    """
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?\u0964])\s+', text.strip())
    sentences = [s for s in sentences if s.strip()]

    result: list[str] = []
    count = 0
    for s in sentences:
        wc = len(s.split())
        if count + wc > limit:
            break
        result.append(s)
        count += wc
    if result:
        return " ".join(result)

    # No whole sentence fit. Work with the first sentence only.
    first = sentences[0] if sentences else text.strip()
    words = first.split()
    if not words:
        return ""

    # 1. Close enough to budget: take the full sentence.
    if len(words) <= limit + 20:
        return first

    # 2. Clause-break walkback. Look for the last comma or semicolon inside
    # the budget, prefer one closer to `limit` so we keep more content.
    budget = words[:limit]
    clause_idx = -1
    lower_bound = max(0, len(budget) - 25)
    for i in range(len(budget) - 1, lower_bound - 1, -1):
        tok = budget[i]
        # Strip trailing period/question/exclaim, we only want comma/semicolon.
        if tok.endswith(";") or tok.endswith(","):
            clause_idx = i
            break
    if clause_idx > 0:
        trimmed = budget[: clause_idx + 1]
        last = trimmed[-1].rstrip(",;:")
        trimmed[-1] = last + _terminator_for(first)
        return " ".join(trimmed)

    # 3. Final guard: drop dangling connectives and close with a period
    # (or danda for Hindi). This never ends mid-clause, but the result may
    # read slightly short.
    dangling = {"and", "or", "but", "with", "for", "from", "to", "of",
                "in", "on", "at", "by", "the", "a", "an", "as", "that"}
    while budget and budget[-1].lower().strip(",;:.") in dangling:
        budget.pop()
    if not budget:
        return ""
    tail = " ".join(budget).rstrip(",;:")
    if tail and tail[-1] not in _SENTENCE_TERMINATORS:
        tail += _terminator_for(first)
    return tail


def _humanize_text(text: str) -> str:
    """Tidy common punctuation glitches that come out of LLMs or raw feeds.

    Handles both Latin and Devanagari punctuation:
      - collapse runs of spaces
      - drop whitespace before any terminator (period, comma, semicolon,
        colon, exclamation, question, danda)
      - collapse doubled terminators ("..", "।।", etc.)
      - insert a space between a terminator and the next letter
      - strip trailing ellipsis (…, ...) and close with a proper terminator
    """
    if not text:
        return text
    out = text
    # Collapse any run of spaces or tabs to one space.
    out = re.sub(r"[ \t]{2,}", " ", out)
    # Replace three or more dots with a single terminator, and drop the
    # Unicode horizontal ellipsis entirely. LLM prompts forbid ellipsis
    # but some providers and raw RSS descriptions still emit them.
    out = re.sub(r"\.{3,}", ".", out)
    out = out.replace("\u2026", "")
    # No whitespace immediately before a terminator. Includes danda so
    # "कुछ है ।" becomes "कुछ है।".
    out = re.sub(r"\s+([\.,;:!\?\u0964])", r"\1", out)
    # Collapse doubled-up terminators to one. Includes danda.
    out = re.sub(r"([\.,;:!\?\u0964])\1+", r"\1", out)
    # A letter immediately after a terminator should have a space between
    # them. Covers both scripts: "done.Next" and "है।अगला".
    out = re.sub(
        r"([\.\?!,\u0964])([A-Za-z\u0900-\u097f])",
        r"\1 \2",
        out,
    )
    return out.strip()


def _strip_leading_title(summary: str, title: str) -> str:
    """If the summary opens by restating the title verbatim, drop that opener."""
    s = summary.strip()
    t = title.strip()
    if not s or not t:
        return s
    s_fold = s.casefold()
    t_fold = t.casefold()
    if s_fold.startswith(t_fold):
        tail = s[len(t):].lstrip(" \t\u2013\u2014-:,.!?\u0964").strip()
        return tail or s
    return s


def ensure_summary_constraints(
    summary: str,
    article: dict,
    min_words: int = 30,
    max_words: int = 60,
    min_chars: int = 50,
) -> str:
    """Keep summaries concise, readable, and distinct from repeated title text."""
    title = decode_entities(article.get("title", "")).strip()
    description = decode_entities(article.get("description", "")).strip()

    def collapse_repeated_leading_block(text: str, min_block_words: int = 4) -> str:
        words = text.split()
        if len(words) < min_block_words * 2:
            return text

        changed = True
        while changed:
            changed = False
            total = len(words)
            max_block = total // 2
            for block_size in range(min_block_words, max_block + 1):
                block = words[:block_size]
                reps = 1
                while words[block_size * reps:block_size * (reps + 1)] == block:
                    reps += 1
                if reps >= 2:
                    words = block + words[block_size * reps:]
                    changed = True
                    break

        return " ".join(words)

    # Join fallback parts with a terminator so downstream sentence splitting
    # actually separates description from title. Without this, the two blobs
    # merge into a single "sentence" and get copied into the summary as one
    # ugly run-on. Use danda for Hindi, period for everything else.
    def _ensure_trailing_stop(text: str) -> str:
        t = text.strip()
        if not t:
            return t
        if t[-1] in _SENTENCE_TERMINATORS:
            return t
        return t + _terminator_for(t)

    parts = [_ensure_trailing_stop(p) for p in (description, title) if p]
    fallback_text = " ".join(parts).strip()
    fallback_text = collapse_repeated_leading_block(fallback_text)
    if not fallback_text:
        fallback_text = "This report is developing and more details are expected."

    clean_summary = decode_entities(summary).strip()
    clean_summary = collapse_repeated_leading_block(clean_summary)
    clean_summary = _strip_leading_title(clean_summary, title)
    if not clean_summary or clean_summary.casefold() == title.casefold():
        clean_summary = description or fallback_text
        clean_summary = _strip_leading_title(clean_summary, title)

    article_language = str(article.get("language", "en") or "en").lower()

    def _is_wrong_language(sentence: str) -> bool:
        """Reject fallback sentences that are in the wrong script for this
        article. Hindi cards should never splice in a big chunk of English
        from the raw RSS description, and vice versa."""
        if not sentence:
            return False
        letters = [c for c in sentence if c.isalpha()]
        if len(letters) < 8:
            return False
        devanagari = sum(1 for c in letters if "\u0900" <= c <= "\u097f")
        latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
        if article_language == "hi":
            return latin > devanagari
        return devanagari > latin

    def split_sentences(text: str) -> list[str]:
        # Treat ellipsis (both three-dot and U+2026) as a sentence break so
        # blobs like "English blurb... हिंदी पूंछ" don't become one sentence.
        parts = re.split(r"(?<=[.!?\u0964\u2026])\s+|\.{3,}\s*", text)
        return [s.strip().rstrip("\u2026").strip() for s in parts if s and s.strip()]

    def _norm_fold(s: str) -> str:
        """Fold for dedup comparison. Strips trailing punctuation so the same
        sentence with and without a period collapse to one key."""
        return re.sub(r"[\s\.\!\?\u0964,;:\"\'\)\(]+$", "", s.casefold()).strip()

    def _contained(haystack_keys: set[str], candidate: str) -> bool:
        """Skip sentences that are substantively the same as one we already kept."""
        cand = _norm_fold(candidate)
        if not cand:
            return True
        if cand in haystack_keys:
            return True
        for key in haystack_keys:
            if not key:
                continue
            # If one is a strict substring of the other and the overlap is
            # substantial, treat as duplicate. Guards against "A." vs "A".
            if len(cand) >= 12 and cand in key:
                return True
            if len(key) >= 12 and key in cand:
                return True
        return False

    # Start with just the cleaned summary. Only borrow from fallback text
    # (title + description) if the summary is short of the min_words floor.
    primary_sentences = split_sentences(clean_summary)
    fallback_sentences = split_sentences(fallback_text)

    unique_sentences: list[str] = []
    seen: set[str] = set()
    for sentence in primary_sentences:
        if _contained(seen, sentence):
            continue
        seen.add(_norm_fold(sentence))
        unique_sentences.append(sentence)

    if not unique_sentences:
        unique_sentences = [fallback_text]

    words: list[str] = []
    for sentence in unique_sentences:
        sentence_words = sentence.split()
        if not sentence_words:
            continue
        if len(words) + len(sentence_words) > max_words:
            break
        words.extend(sentence_words)

    # Only pad with fallback/description if we still don't meet the floor AND
    # the fallback adds genuinely new information. Skip any sentence that is
    # in the wrong script for this article's language — otherwise a bilingual
    # RSS description can splice raw English into a Hindi card (or vice versa).
    if len(words) < min_words:
        for sentence in fallback_sentences:
            if _contained(seen, sentence):
                continue
            if _is_wrong_language(sentence):
                continue
            seen.add(_norm_fold(sentence))
            sentence_words = sentence.split()
            if not sentence_words:
                continue
            if len(words) + len(sentence_words) > max_words:
                break
            words.extend(sentence_words)
            if len(words) >= min_words:
                break

    if not words:
        # The first sentence alone exceeds the budget. Rather than hard-cut
        # mid-word, lean on truncate_words which knows how to end cleanly on
        # a clause boundary even when no whole sentence fits.
        fallback_single = truncate_words(unique_sentences[0], max_words)
        words = fallback_single.split() if fallback_single else []

    constrained = " ".join(words).strip()

    # Final guard: the result must end on a complete sentence. Walk back to
    # the last terminator we have. Unlike the old version, there is no
    # minimum-word floor on the walk-back: a short but complete sentence
    # always beats a long but truncated one.
    if constrained and constrained[-1] not in _SENTENCE_TERMINATORS:
        cut_at = -1
        for i in range(len(constrained) - 1, -1, -1):
            if constrained[i] in _SENTENCE_TERMINATORS:
                cut_at = i
                break
        if cut_at >= 0:
            constrained = constrained[: cut_at + 1].rstrip()
        else:
            # No terminator anywhere in the kept text. Fall back to
            # truncate_words on the description so we end on a real
            # clause break rather than a manufactured period.
            rescue = truncate_words(description or fallback_text, max_words)
            if rescue:
                constrained = rescue

    # Humanise punctuation. If we somehow still have no terminator, drop
    # trailing connective words and close with a period. This path should
    # be effectively unreachable now, but it protects the JSON schema.
    constrained = _humanize_text(constrained)
    if constrained and constrained[-1] not in _SENTENCE_TERMINATORS:
        tokens = constrained.split()
        dangling = {"and", "or", "but", "with", "for", "from", "to", "of",
                    "in", "on", "at", "by", "the", "a", "an", "as", "that"}
        while tokens and tokens[-1].lower().strip(",;:.") in dangling:
            tokens.pop()
        constrained = " ".join(tokens).rstrip(",;: ")
        if constrained and constrained[-1] not in _SENTENCE_TERMINATORS:
            constrained += _terminator_for(constrained)

    return constrained


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def translate_texts_to_hindi(texts: list[str]) -> list[str]:
    normalized = [normalize_text(text) for text in texts]
    def should_translate(text: str) -> bool:
        if not text:
            return False
        letters = [ch for ch in text if ch.isalpha()]
        if not letters:
            return False
        latin_letters = sum(1 for ch in letters if "A" <= ch <= "z")
        return (latin_letters / len(letters)) >= 0.55

    uniques = [text for text in dict.fromkeys(normalized) if text and should_translate(text)]
    if not uniques:
        return normalized

    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        log.warning("deep-translator not installed; Hindi output will mirror English text.")
        return normalized

    translator = GoogleTranslator(source="auto", target="hi")
    translated_map: dict[str, str] = {}

    for batch in _chunked(uniques, 20):
        # Protect financial/technical abbreviations from being transliterated.
        protected_batch: list[str] = []
        saved_abbrevs: list[list[str]] = []
        for text in batch:
            protected, saved = _protect_abbrevs(text)
            protected_batch.append(protected)
            saved_abbrevs.append(saved)

        try:
            translated_batch = translator.translate_batch(protected_batch)
            if not isinstance(translated_batch, list) or len(translated_batch) != len(batch):
                raise ValueError("unexpected translation response shape")
            for source_text, target_text, saved in zip(batch, translated_batch, saved_abbrevs):
                restored = _restore_abbrevs(target_text, saved)
                translated_map[source_text] = colloquialize_hindi(restored) or source_text
        except Exception as exc:
            log.warning("Hindi batch translation failed (%s). Retrying item by item.", exc)
            for source_text, saved in zip(batch, saved_abbrevs):
                try:
                    protected, _ = _protect_abbrevs(source_text)
                    raw = translator.translate(protected)
                    restored = _restore_abbrevs(raw, saved)
                    translated_map[source_text] = colloquialize_hindi(restored) or source_text
                except Exception as single_exc:
                    log.warning("Hindi translation failed for '%s': %s", source_text[:60], single_exc)
                    translated_map[source_text] = source_text

    return [translated_map.get(text, text) for text in normalized]


# ── LLM helpers ───────────────────────────────────────────────────────────────

# Loaded once at import time so every call in this process uses the same guide.
_STYLE_GUIDE = load_style_guide()

try:
    from llm_client import llm_complete as _llm_complete, any_key_present as _llm_any_key
except ImportError:
    # Fall back to a no-op if the module is missing. Callers handle the None.
    def _llm_complete(*_a, **_kw):
        return None

    def _llm_any_key():
        return False

try:
    from voice import (
        DIGEST_RULES as _LAVKESH_DIGEST_RULES,
        STORY_SUMMARY_RULES as _LAVKESH_STORY_RULES,
    )
except ImportError:
    _LAVKESH_DIGEST_RULES = ""
    _LAVKESH_STORY_RULES = ""


# ---------------------------------------------------------------------------
# Prompt constants.
#
# These live at module level so the rules are built once per process and
# shipped once per request (as the system prompt) rather than being rebuilt
# and re-sent inside every user prompt. User prompts carry only the title
# and source text so the per-call token cost is minimal.
# ---------------------------------------------------------------------------

# Per-story summary rules. Compressed from the older user-prompt form.
# Emphasis on paraphrase (not copy) and on closing every sentence cleanly.
_STORY_RULES_EN = (
    "Write an original news summary in your own words. This is a summary, "
    "not a quote. Do not copy phrases or clauses from the source verbatim. "
    "Rewrite, compress, and lead with the consequence.\n\n"
    "Length: 40 to 50 words, 60 max. Never exceed 60. Two sentences ideal, "
    "three max.\n\n"
    "Every sentence must end on a period. Never stop mid-word or mid-clause. "
    "If you are near the word limit, close the current sentence early on a "
    "period and stop. It is better to finish at 42 words than to run to 60 "
    "with a dangling clause.\n\n"
    "Lead with the key fact (who, what, where, impact). Do not restate the "
    "title. Use concrete names, places, numbers. If the source is thin, use "
    "the title plus known context, do not invent. Stop when the facts end, "
    "no conclusion sentence, no editorialising.\n\n"
    "No quote marks. No labels or headlines. No em dashes. No colons. No "
    "ellipses. Simple punctuation only. Return only the paragraph text.\n\n"
    "Do not include any reasoning, analysis, or internal monologue. Do not "
    "emit <think>, <thinking>, <reasoning>, <analysis>, or any similar tag. "
    "Do not start with 'Okay', 'Let me', 'First I', or any preamble. Your "
    "first token must be the first word of the summary."
)

_STORY_RULES_HI = (
    "अपने शब्दों में मौलिक समाचार सारांश लिखें। यह सारांश है, उद्धरण नहीं। "
    "स्रोत से वाक्य या वाक्यांश हूबहू न उठाएं। दोबारा लिखें, संक्षेप करें, "
    "परिणाम से शुरू करें।\n\n"
    "लंबाई: 40 से 50 शब्द, अधिकतम 60। 60 से ऊपर कभी नहीं। दो वाक्य आदर्श, "
    "तीन अधिकतम।\n\n"
    "हर वाक्य पूर्णविराम (।) पर खत्म हो। शब्द या उपवाक्य के बीच कभी न रुकें। "
    "यदि शब्द सीमा के पास हों तो चालू वाक्य पहले बंद करें और वहीं रुकें। "
    "42 शब्दों पर पूर्ण वाक्य के साथ खत्म होना 60 शब्दों पर अधूरे वाक्य से "
    "हमेशा बेहतर है।\n\n"
    "मुख्य तथ्य से शुरू करें (कौन, क्या, कहां, असर)। शीर्षक दोबारा न कहें। "
    "ठोस नाम, जगह, संख्या रखें। स्रोत पतला हो तो शीर्षक और ज्ञात संदर्भ से "
    "लिखें, कुछ न गढ़ें। तथ्य खत्म होते ही रुकें, निष्कर्ष न जोड़ें।\n\n"
    "कोई उद्धरण, लेबल, शीर्षक, em-dash, कोलन, या तीन बिंदु (...) नहीं। "
    "सिर्फ पैराग्राफ लौटाएं।\n\n"
    "कोई विचार, चिंतन, या आंतरिक संवाद शामिल न करें। <think>, <thinking>, "
    "<reasoning>, <सोचें>, <सोच>, <विचार>, <चिंतन> या कोई भी ऐसा टैग न भेजें। "
    "'ठीक है', 'चलो', 'पहले', 'मुझे सोचना है' जैसी भूमिका से शुरू न करें। "
    "आपका पहला शब्द सारांश का पहला शब्द होना चाहिए।"
)

# Editor's digest rules (2-3 sentence lead paragraph, ~35 to 50 words).
_DIGEST_RULES_EN = (
    "Write a 2 to 3 sentence editor's note "
    "You MUST write between 35 and 50 words. A single short "
    "sentence is not acceptable. Do not stop after the first sentence. "
    "First sentence names what dominates this hour with concrete names "
    "and places. Second sentence adds the next most important thread or "
    "a contrast. Optional third sentence only if it earns its place. "
    "No headline. No bullets. No em dashes. No ellipses. Skip generic "
    "phrasing. Every sentence must end on a period. Return only the "
    "paragraph, no label, no preface, no reasoning tags."
)

_DIGEST_RULES_HI = (
    "2 से 3 वाक्यों में एक संपादकीय नोट लिखें। "
    "आपको 35 से 50 शब्दों के बीच लिखना ही है। एक छोटा वाक्य "
    "स्वीकार्य नहीं है। पहले वाक्य के बाद न रुकें। "
    "पहला वाक्य बताए कि इस घंटे क्या प्रमुख है, ठोस नाम और जगहों के साथ। "
    "दूसरा वाक्य अगली बड़ी खबर या विरोधाभास जोड़े। तीसरा वाक्य तभी लिखें "
    "जब वह अपनी जगह बनाए। "
    "हर वाक्य पूर्णविराम (।) पर खत्म हो। कोई हेडलाइन, बुलेट, em-dash, :, "
    "..., या टैग (<think>, <सोचें>) नहीं। सिर्फ पैराग्राफ लौटाएं।"
)


def _summary_system_prompt(language: str = "en") -> str:
    """Compose the system prompt: Lavkesh voice + compressed rules + STYLE.md.

    The voice block handles persona and banned phrases, the rules block
    handles length and structure, and STYLE.md handles newsroom craft.
    Everything here is constant per-process, so it caches well on providers
    that support prompt caching.
    """
    # Prompt order matters more than length. Voice first, then the editorial
    # style guide, THEN the mechanical format rules. Models weight earlier
    # context more heavily, so leading with "write like X" and "our house
    # style is Y" pulls the voice through before the strict word-count and
    # punctuation rules constrain the output.
    parts: list[str] = []
    if _LAVKESH_STORY_RULES:
        parts.append(_LAVKESH_STORY_RULES)

    if _STYLE_GUIDE:
        parts.append(
            "GeoPulse editorial style guide — follow exactly:\n\n"
            + _STYLE_GUIDE
        )

    rules = _STORY_RULES_HI if language == "hi" else _STORY_RULES_EN
    parts.append(rules)
    return "\n\n".join(parts)


def _summary_user_prompt(title: str, description: str) -> str:
    """Minimal per-call payload. Rules live in the system prompt."""
    return f"Title: {title}\nSource: {description}"


def _hindi_summary_user_prompt(title: str, description: str) -> str:
    """Minimal per-call payload for Hindi. Rules live in the system prompt."""
    return f"शीर्षक: {title}\nस्रोत: {description}"


def _digest_system_prompt(language: str = "en") -> str:
    """System prompt for the once-per-edition editor's digest. Lavkesh's
    digest voice leads if available, followed by the compressed digest rules.
    """
    parts: list[str] = []
    if _LAVKESH_DIGEST_RULES:
        parts.append(_LAVKESH_DIGEST_RULES)
    parts.append(_DIGEST_RULES_HI if language == "hi" else _DIGEST_RULES_EN)
    return "\n\n".join(parts)


def _digest_user_prompt(headlines_blob: str, language: str = "en") -> str:
    """Minimal user prompt for the digest: just the headline list."""
    if language == "hi":
        return f"आज बोर्ड पर लीड स्टोरीज़:\n{headlines_blob}"
    return f"Lead stories on the board right now:\n{headlines_blob}"


def _batch_summarise(
    articles: list[dict],
    *,
    language: str = "en",
    preferred: str | None = None,
    batch_size: int = 5,
) -> list[str | None]:
    """Summarise up to `batch_size` articles per LLM call.

    Combines several headline + lede pairs into one numbered user prompt and
    asks for a numbered block back. One request replaces N, so the system
    prompt (voice + style + rules) is sent once for the whole batch instead
    of N times. Falls back to per-article `_chain_summarise` if the batched
    response fails to parse into the expected number of items.

    Return shape matches `_chain_summarise`: one entry per input article,
    in the same order. Entries may be None when every provider failed.
    """
    if not articles or not _llm_any_key():
        return [None] * len(articles)

    system = _summary_system_prompt(language)
    out: list[str | None] = [None] * len(articles)

    import re as _re

    for start in range(0, len(articles), batch_size):
        batch = articles[start : start + batch_size]
        n = len(batch)

        if language == "hi":
            header = (
                f"नीचे {n} समाचार आइटम हैं। हर एक का अलग सारांश लिखें।\n"
                f"कुल {n} सारांश लौटाएं, प्रत्येक अपनी पंक्ति पर, '1.', '2.', ... से शुरू।\n"
                "हर सारांश शीर्ष प्रणाली नियमों का पालन करे (40-50 शब्द, अधिकतम 60)।\n\n"
            )
            item_fmt = "{i}. शीर्षक: {title}\nस्रोत: {desc}"
        else:
            header = (
                f"Below are {n} news items. Write one summary per item.\n"
                f"Return exactly {n} summaries, each on its own line, numbered "
                "'1.', '2.', etc. Follow the system rules (40-50 words per "
                "summary, hard max 60).\n\n"
            )
            item_fmt = "{i}. Title: {title}\nSource: {desc}"

        parts = []
        for i, art in enumerate(batch, 1):
            title = decode_entities(art.get("title", ""))
            desc = decode_entities(art.get("description") or "")
            # Trim per-item description so batch prompts stay compact.
            if len(desc) > 400:
                desc = desc[:400]
            parts.append(item_fmt.format(i=i, title=title, desc=desc))
        user = header + "\n\n".join(parts)

        # 120 tokens per summary is generous (60 words ~ 90 tokens) and
        # leaves headroom for numbering overhead.
        text = _llm_complete(
            system,
            user,
            max_tokens=max(360, 120 * n),
            temperature=0.25,
            preferred=preferred,
        )

        parsed: list[str] = []
        if text:
            blob = _strip_reasoning(text).strip()
            # Split on lines that start with an integer followed by a dot.
            # Keep the content after the numeric prefix.
            pieces = _re.split(r"(?m)^\s*(\d+)[\.\)]\s*", blob)
            # pieces looks like ['', '1', '...content...', '2', '...', ...]
            i = 1
            while i < len(pieces) - 1:
                try:
                    idx_n = int(pieces[i])
                except ValueError:
                    break
                content = pieces[i + 1].strip()
                # Trim trailing blank separator / next-number preview
                content = _re.sub(r"\n\s*$", "", content).strip()
                if content:
                    # Ensure list is long enough to assign by index.
                    while len(parsed) < idx_n:
                        parsed.append("")
                    parsed[idx_n - 1] = content
                i += 2

        if len(parsed) == n and all(parsed):
            log.info("[%s] batch[%d-%d] ok, %d summaries via 1 call",
                     language, start + 1, start + n, n)
            for i, s in enumerate(parsed):
                out[start + i] = s
        else:
            log.warning("[%s] batch[%d-%d] returned %d/%d — falling back to single calls",
                        language, start + 1, start + n, len([p for p in parsed if p]), n)
            indiv = _chain_summarise(batch, language=language, preferred=preferred)
            for i, s in enumerate(indiv):
                out[start + i] = s

    return out


def _chain_summarise(
    articles: list[dict],
    *,
    language: str = "en",
    preferred: str | None = None,
) -> list[str | None]:
    """Summarise each article via the LLM fallback chain.

    Returns a list the same length as `articles`. Each entry is the summary
    text, or None if every provider failed for that article. The caller is
    expected to handle the Nones (typically with truncation fallback).
    """
    if not articles or not _llm_any_key():
        return [None] * len(articles)

    system = _summary_system_prompt(language)
    user_builder = _hindi_summary_user_prompt if language == "hi" else _summary_user_prompt
    out: list[str | None] = []
    for art in articles:
        title = decode_entities(art.get("title", ""))
        desc = decode_entities(art.get("description") or "")
        # 60 words is roughly 90 BPE tokens. 360 gives the model so much
        # headroom it will always finish a clean sentence well before the
        # ceiling. Any earlier run-to-ceiling was either a cost mistake or
        # a prompt that invited rambling. We would rather pay a few extra
        # tokens than ship a half sentence.
        text = _llm_complete(
            system,
            user_builder(title, desc),
            max_tokens=360,
            temperature=0.25,
            preferred=preferred,
        )
        if not text:
            out.append(None)
            continue
        # Strip any <think>/<सोचें> reasoning blocks the model leaked, THEN
        # trim to the last full sentence. Order matters: trim first would
        # leave us with a sentence-terminated reasoning blob that reads
        # like a real summary and passes all downstream checks.
        cleaned = _strip_reasoning(text.strip())
        cleaned = _trim_to_last_full_sentence(cleaned)

        # If sanitisation wiped out the response (pure reasoning leak with
        # no usable summary text), retry once with a harder-line prompt.
        if not cleaned:
            retry = _llm_complete(
                system,
                user_builder(title, desc)
                + "\n\nReturn only the summary paragraph. No thinking tags.",
                max_tokens=360,
                temperature=0.25,
                preferred=preferred,
            )
            if retry:
                cleaned = _trim_to_last_full_sentence(
                    _strip_reasoning(retry.strip())
                )

        # Reject and retry once if the model just echoed the source instead
        # of summarising. Cheap guard, catches the common "description
        # copy-paste" failure without adding a second provider call.
        if cleaned and desc and _looks_like_verbatim_copy(cleaned, desc):
            retry = _llm_complete(
                system,
                user_builder(title, desc)
                + "\n\nThe last draft copied the source text. Rewrite it in "
                "your own words as a genuine summary.",
                max_tokens=360,
                temperature=0.3,
                preferred=preferred,
            )
            if retry:
                cleaned = _trim_to_last_full_sentence(
                    _strip_reasoning(retry.strip())
                )
        out.append(cleaned or None)
    return out


_SENTENCE_TERMINATORS = {".", "!", "?", "\u0964"}  # includes Hindi danda ।


# Reasoning-model leak scrubber.
#
# Some free-tier Groq models (DeepSeek R1 distill, GPT-OSS, Qwen3) emit a
# chain-of-thought block before the real answer, wrapped in tags like
# <think>, <thinking>, <reasoning>, or their Hindi translations (<सोचें>,
# <सोच>) when the prompt is in Hindi. When that block leaks through, the
# card summary reads as half internal monologue. This strips all common
# variants plus orphan open or close tags left by truncation.
_REASONING_TAGS = (
    "think", "thinking", "thought", "thoughts",
    "reason", "reasoning", "reflection", "analysis",
    "scratch", "scratchpad", "internal",
    # Hindi variants the Hindi prompt is most likely to translate "think" into.
    "\u0938\u094b\u091a\u0947\u0902",  # सोचें
    "\u0938\u094b\u091a",              # सोच
    "\u0935\u093f\u091a\u093e\u0930",  # विचार
    "\u091a\u093f\u0902\u0924\u0928",  # चिंतन
)
_REASONING_TAG_ALT = "|".join(re.escape(t) for t in _REASONING_TAGS)
_REASONING_BLOCK_RE = re.compile(
    rf"<\s*({_REASONING_TAG_ALT})\s*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_REASONING_OPEN_RE = re.compile(
    rf"<\s*(?:{_REASONING_TAG_ALT})\s*>",
    re.IGNORECASE,
)
_REASONING_CLOSE_RE = re.compile(
    rf"<\s*/\s*(?:{_REASONING_TAG_ALT})\s*>",
    re.IGNORECASE,
)


def _strip_reasoning(text: str) -> str:
    """Remove leaked chain-of-thought blocks from LLM output.

    Three cases:
      1. Complete block `<think>...</think>`. Removed in place.
      2. Orphan close tag only (open tag was eaten by truncation upstream).
         Everything before and including the last close tag is discarded.
      3. Orphan open tag only (close tag never emitted). Everything from
         the open tag onward is discarded. If nothing precedes the open
         tag we return empty, and the caller's fallback path takes over.
    """
    if not text:
        return text
    cleaned = _REASONING_BLOCK_RE.sub("", text).strip()

    last_close = None
    for m in _REASONING_CLOSE_RE.finditer(cleaned):
        last_close = m
    if last_close is not None:
        cleaned = cleaned[last_close.end():].strip()

    open_match = _REASONING_OPEN_RE.search(cleaned)
    if open_match:
        cleaned = cleaned[: open_match.start()].strip()

    return cleaned


def _terminator_for(text: str) -> str:
    """Pick the sentence-ending mark that fits the script of `text`.

    Hindi uses the danda (।). Anything else (English, mixed Latin) uses a
    period. We decide based on the presence of Devanagari characters in the
    text. A few Devanagari characters is enough: if the sentence is in Hindi
    it will always have several.
    """
    if text and _DEVANAGARI_RE.search(text):
        return "\u0964"
    return "."


def _looks_like_verbatim_copy(summary: str, source: str, window: int = 10) -> bool:
    """Return True if `summary` copies a long run of words from `source`.

    Uses a sliding-window word match. If more than half of the summary's
    `window`-word spans appear verbatim inside the source, we treat it as
    a copy-paste rather than a real summary. Case-insensitive, punctuation
    stripped so minor surface differences do not hide a near-copy.
    """
    if not summary or not source:
        return False

    def _norm(s: str) -> list[str]:
        return [w.strip(",.;:!?\"'()[]").lower() for w in s.split() if w.strip()]

    sum_tokens = _norm(summary)
    src_tokens = _norm(source)
    if len(sum_tokens) < window or len(src_tokens) < window:
        # Too short to judge by windows. Fall back to full-string containment.
        return summary.strip().lower() in source.lower()

    src_text = " ".join(src_tokens)
    total = len(sum_tokens) - window + 1
    hits = 0
    for i in range(total):
        span = " ".join(sum_tokens[i:i + window])
        if span in src_text:
            hits += 1
    # 0.65 avoids false positives on legitimate summaries that happen to
    # share a named entity or two with the source. Anything above that is
    # almost always the model just echoing whole phrases.
    return (hits / total) > 0.65


def _trim_to_last_full_sentence(text: str) -> str:
    """Remove any trailing half-sentence so the summary never ends mid-word.

    If the text already ends in a sentence terminator, return it as-is.
    Otherwise find the last terminator and cut there. For very short outputs
    with no terminator at all, return the text unchanged and let the
    downstream constraint layer decide what to do.
    """
    if not text:
        return text
    stripped = text.rstrip()
    if stripped and stripped[-1] in _SENTENCE_TERMINATORS:
        return stripped
    # Walk backward to find the last full-sentence terminator. Truncating
    # there is always better than leaving a dangling half-sentence, even if
    # what remains is a bit short. ensure_summary_constraints will re-pad
    # from the source description if that happens.
    for idx in range(len(stripped) - 1, -1, -1):
        if stripped[idx] in _SENTENCE_TERMINATORS:
            return stripped[: idx + 1].rstrip()
    # No terminator anywhere. Leave unchanged.
    return stripped


def _digest_passes_quality(text: str, min_words: int = 20) -> bool:
    """True if the digest looks like an actual editor's note.

    The LLM sometimes returns a single short sentence or stops mid-clause
    because max_tokens ran out. We reject both so the caller can retry or
    fall back to a headline-stitched version.
    """
    if not text:
        return False
    words = text.split()
    if len(words) < min_words:
        return False
    if text[-1] not in _SENTENCE_TERMINATORS:
        return False
    return True


def _fallback_digest(articles: list[dict], language: str = "en") -> str:
    """Build a digest without an LLM, stitched from the top headlines.

    Not pretty, but guaranteed to produce a readable 2-sentence lead
    when every LLM attempt has failed. Better than an empty editor box.
    """
    top = []
    for a in articles[:6]:
        title = decode_entities(a.get("title", "")).strip()
        if title:
            top.append((title, (a.get("region") or "World").strip()))
    if not top:
        return ""

    lead_title, lead_region = top[0]
    count = len(articles)

    if language == "hi":
        region_hi = HINDI_REGION_LABELS.get(lead_region, lead_region)
        second_bit = ""
        if len(top) > 1:
            second_title, second_region = top[1]
            region_hi_2 = HINDI_REGION_LABELS.get(second_region, second_region)
            if region_hi_2 != region_hi:
                second_bit = f" साथ ही {region_hi_2} से भी घटनाक्रम सामने आया है।"
        return (
            f"इस घंटे बोर्ड पर {region_hi} की अगुवाई है, {lead_title} मुख्य खबर है।"
            f"{second_bit} कुल {count} ताज़ा खबरें इस संस्करण में हैं।"
        )

    second_bit = ""
    if len(top) > 1:
        _, second_region = top[1]
        if second_region != lead_region:
            second_bit = f" {second_region} carries the next thread."
    return (
        f"{lead_region} leads the board this hour with {lead_title}.{second_bit} "
        f"{count} fresh dispatches in this edition."
    )


def generate_edition_digest(articles: list[dict], language: str = "en") -> str | None:
    """Produce a short editor's note (2-3 sentences, 35-50 words) summarising
    what is on the board right now. This runs once per pipeline and appears
    at the top of the page.

    Runs up to three LLM attempts, rejecting outputs that are too short or
    that stop mid-sentence. If every attempt fails, returns a headline
    stitched fallback so the page is never left with an empty editor box.
    """
    if not articles:
        return None
    if not _llm_any_key():
        # No LLM configured. Still return something readable rather than
        # leaving the editor box empty on the page.
        return _fallback_digest(articles, language) or None

    # Take the freshest dozen so the digest reads like a lead paragraph,
    # not an exhaustive index.
    headlines_src = []
    for a in articles[:12]:
        title = decode_entities(a.get("title", "")).strip()
        region = (a.get("region") or "").strip()
        if not title:
            continue
        headlines_src.append(f"- [{region or 'World'}] {title}")
    headlines_blob = "\n".join(headlines_src)

    # Hindi takes roughly 2x the tokens per character of English, so bump
    # the ceiling for Hindi to avoid mid-sentence truncation. 600 tokens
    # leaves plenty of room for a 50-word Hindi paragraph plus any small
    # leaked preamble the scrubber strips.
    max_tokens = 600 if language == "hi" else 400

    system_prompt = _digest_system_prompt(language)
    user_prompt = _digest_user_prompt(headlines_blob, language)

    for attempt in range(3):
        # Small temperature bump on retries to shake the model loose from
        # the same too-short answer.
        temp = 0.3 + (attempt * 0.15)
        nudge = ""
        if attempt == 1:
            nudge = (
                "\n\nYour last reply was too short. Write 2 to 3 sentences "
                "totalling 35 to 50 words."
                if language == "en"
                else "\n\nपिछला जवाब बहुत छोटा था। 2 से 3 वाक्य, 35 से 50 शब्द लिखें।"
            )
        elif attempt == 2:
            nudge = (
                "\n\nMust be 2 to 3 full sentences. Must end on a period."
                if language == "en"
                else "\n\n2 से 3 पूर्ण वाक्य लिखें। पूर्णविराम (।) पर खत्म करें।"
            )

        text = _llm_complete(
            system_prompt,
            user_prompt + nudge,
            max_tokens=max_tokens,
            temperature=min(temp, 0.6),
        )
        cleaned = _strip_reasoning((text or "").strip())
        cleaned = _trim_to_last_full_sentence(cleaned)
        if _digest_passes_quality(cleaned):
            return cleaned

    # Every LLM attempt produced something too short or cut off mid-clause.
    # Return the stitched fallback so the editor box stays populated.
    log.warning("Digest LLM attempts all failed quality checks, using fallback.")
    fallback = _fallback_digest(articles, language)
    return fallback or None


# ── Markdown archive builder ──────────────────────────────────────────────────

def localize_article(article: dict, language: str) -> dict:
    if language != "hi":
        return article
    hi = article.get("translations", {}).get("hi", {})
    return {
        **article,
        "title": hi.get("title") or article.get("title", ""),
        "summary": hi.get("summary") or article.get("summary", ""),
        "region": hi.get("region") or article.get("region", "World"),
    }


def build_markdown(enriched: list[dict], generated_at: str, display_tz, language: str = "en") -> str:
    try:
        date_str = format_display_datetime(generated_at, display_tz, "%B %d, %Y %H:%M %Z")
    except ValueError:
        date_str = generated_at

    if language == "hi":
        lines = [
            f"# 🌍 {_SITE_TITLE} हिंदी",
            "",
            f"**अपडेट:** {date_str}",
            "",
            "---",
            "",
        ]
    else:
        lines = [
            f"# 🌍 {_SITE_TITLE} Newsletter",
            "",
            f"**Updated:** {date_str}",
            "",
            "---",
            "",
        ]

    # Group by region for the markdown view
    regions: dict[str, list[dict]] = {}
    for art in enriched:
        view = localize_article(art, language)
        regions.setdefault(view["region"], []).append(view)

    for region, arts in regions.items():
        lines += [f"## {region}", ""]
        for art in arts:
            pub = art.get("published_at", "")
            try:
                pub_str = format_display_datetime(pub, display_tz, "%b %d, %H:%M %Z")
            except Exception:
                pub_str = pub[:16]
            lines += [
                f"### [{art['title']}]({art['url']})",
                # Keep the human-readable tz label for markdown, but append the
                # ISO timestamp in a machine-parseable tail so the site's JS can
                # reformat it in the reader's browser locale.
                f"*{art['source']}* - {pub_str} (iso: {pub})",
            ]
            # Store the image URL as an HTML comment so the archive stays
            # visually clean but the site generator can parse it back out
            # when rendering per-edition pages. Skip when there is no image
            # so the fallback placeholder still kicks in on old-style cards.
            image_url = (art.get("image_url") or "").strip()
            if image_url:
                lines.append(f"<!-- image: {image_url} -->")
            lines += [
                "",
                art["summary"],
                "",
            ]
        lines += ["---", ""]

    if language == "hi":
        lines.append(f"*{_SITE_TITLE}. स्वचालित भू-राजनीति डाइजेस्ट। Hosted at {_SITE_URL_DISPLAY}*")
    else:
        lines.append(f"*{_SITE_TITLE}. automated geopolitics digest. Hosted at {_SITE_URL_DISPLAY}*")
    lines.append("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg      = load_config()
    provider = cfg["llm_provider"]
    model    = cfg["llm_model"]
    display_tz = get_display_timezone(cfg)

    if not os.path.exists(INPUT_PATH):
        log.error("raw_news.json not found at %s. Run fetch_news.py first.", INPUT_PATH)
        raise SystemExit(1)

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    max_articles: int = cfg["max_articles"]
    all_raw: list[dict] = [normalize_article_text(a) for a in data.get("articles", [])]
    # Sort newest-first so the freshest stories win within each language set.
    all_raw.sort(key=lambda a: a.get("published_at", ""), reverse=True)

    # Split by language: Hindi source articles are already in Hindi,
    # so they get their own pipeline with no translation step.
    en_raw: list[dict] = [a for a in all_raw if a.get("language", "en") != "hi"]
    hi_raw: list[dict] = [a for a in all_raw if a.get("language") == "hi"]

    en_articles: list[dict] = en_raw[:max_articles]
    hi_articles: list[dict] = hi_raw[:max_articles]

    fetched_at: str = data.get("fetched_at", datetime.now(timezone.utc).isoformat())
    total_unique_count = int(data.get("total_unique_count", len(all_raw)))

    if not en_articles and not hi_articles:
        log.warning("No articles found. Writing empty newsletter.")
        empty = {
            "generated_at": fetched_at,
            "article_count": 0,
            "total_unique_count": 0,
            "articles": [],
        }
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)
        with open(MD_PATH, "w", encoding="utf-8") as f:
            display_fetched_at = format_display_datetime(fetched_at, display_tz, "%B %d, %Y %H:%M %Z")
            f.write(f"# 🌍 {_SITE_TITLE} Newsletter\n\n**Updated:** {display_fetched_at}\n\n"
                    "_No articles were available for this edition._\n")
        with open(MD_HI_PATH, "w", encoding="utf-8") as f:
            display_fetched_at = format_display_datetime(fetched_at, display_tz, "%B %d, %Y %H:%M %Z")
            f.write(f"# 🌍 {_SITE_TITLE} हिंदी\n\n**अपडेट:** {display_fetched_at}\n\n"
                "_इस संस्करण में कोई लेख उपलब्ध नहीं था।_\n")
        return

    # ── Delta cache: reuse summaries for URLs already in last newsletter ──────
    # Summaries are stable once written — the source title/url doesn't change
    # hour to hour. Reusing previous summaries skips the LLM call entirely for
    # articles that carried over from the last edition, cutting token spend
    # dramatically on typical runs (most hours add only a few new URLs).
    cached_summaries: dict[str, str] = {}
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, encoding="utf-8") as f:
                _prev = json.load(f) or {}
            for _a in _prev.get("articles", []) or []:
                _url = str(_a.get("url", "")).strip()
                _sum = str(_a.get("summary", "")).strip()
                if _url and _sum:
                    cached_summaries[_url] = _sum
            log.info("Delta cache loaded: %d previous summaries available.", len(cached_summaries))
        except Exception as _exc:
            log.warning("Could not read previous newsletter.json for delta cache: %s", _exc)

    def _truncate_all(articles: list[dict]) -> list[str]:
        return [
            truncate_words(decode_entities(a.get("description") or a.get("title", "")))
            for a in articles
        ]

    def _summarise_with_cache(articles: list[dict], language: str, preferred) -> list[str]:
        """Summarise `articles` reusing previous summaries keyed by URL.

        Only articles whose URL has no cached summary go through the LLM
        chain, saving tokens on every run where most URLs carried over."""
        if not articles:
            return []
        cached = [cached_summaries.get(str(a.get("url", "")).strip(), "") for a in articles]
        fresh_indices = [i for i, s in enumerate(cached) if not s]
        hit = len(articles) - len(fresh_indices)
        if not fresh_indices:
            log.info("[%s] all %d summaries served from delta cache, 0 LLM calls.", language, len(articles))
            return cached
        log.info("[%s] delta cache: %d hit, %d miss — LLM will summarise %d.", language, hit, len(fresh_indices), len(fresh_indices))
        fresh_articles = [articles[i] for i in fresh_indices]
        # Batch LLM call when there are enough fresh misses to amortise
        # the system-prompt overhead across articles. Below the threshold
        # we stay per-call so one small run doesn't pay the parse cost.
        if len(fresh_articles) >= 3:
            fresh_summaries = _batch_summarise(fresh_articles, language=language, preferred=preferred)
        else:
            fresh_summaries = _chain_summarise(fresh_articles, language=language, preferred=preferred)
        for idx, summary in zip(fresh_indices, fresh_summaries):
            cached[idx] = summary
        return cached

    # ── Generate summaries for English articles ───────────────────────────────
    log.info("Generating summaries for %d English articles. Provider: %s", len(en_articles), provider)

    # Auto-chain, free tier only: Groq then Gemini via llm_client.
    # Preferred provider (if any) from config / env still wins for the first attempt.
    preferred = provider if provider in ("groq", "gemini") else None
    if _llm_any_key():
        log.info("Using LLM chain for English summaries. Preferred: %s", preferred or "groq")
        chained = _summarise_with_cache(en_articles, language="en", preferred=preferred)
        # Fill any misses with truncation so no article goes empty.
        en_summaries = [
            text if text else truncate_words(decode_entities(a.get("description") or a.get("title", "")))
            for text, a in zip(chained, en_articles)
        ]
    else:
        log.info("No LLM keys set. Falling back to truncation for English summaries.")
        en_summaries = _truncate_all(en_articles)

    # ── Hindi summaries: LLM when a key is available, else truncation ─────────
    log.info("Summarising %d Hindi articles.", len(hi_articles))
    if _llm_any_key():
        hi_chained = _summarise_with_cache(hi_articles, language="hi", preferred=preferred)
        hi_summaries = [
            text if text else truncate_words(decode_entities(a.get("description") or a.get("title", "")))
            for text, a in zip(hi_chained, hi_articles)
        ]
    else:
        hi_summaries = [
            truncate_words(decode_entities(a.get("description") or a.get("title", "")))
            for a in hi_articles
        ]

    # ── Enrich English articles ───────────────────────────────────────────────
    en_enriched: list[dict] = []
    for art, summary in zip(en_articles, en_summaries):
        final_summary = ensure_summary_constraints(summary, art)
        region = classify_region(art)
        en_enriched.append({
            "title":        decode_entities(art.get("title", "")),
            "url":          art.get("url", ""),
            "source":       decode_entities(art.get("source", "")),
            "sources":      art.get("sources", []),
            "published_at": art.get("published_at", ""),
            "image_url":    art.get("image_url", ""),
            "summary":      final_summary,
            "region":       region,
            "language":     "en",
        })

    # Intentionally do NOT translate English articles into Hindi. The user rule
    # is each language page only shows stories whose source is in that
    # language. English articles get an empty translations block so downstream
    # filters reject them from the Hindi page.
    for article in en_enriched:
        article["translations"] = {}

    # ── Enrich Hindi articles (already in Hindi, no translation needed) ───────
    hi_enriched: list[dict] = []
    for art, summary in zip(hi_articles, hi_summaries):
        final_summary = ensure_summary_constraints(summary, art)
        region = classify_region(art)
        hi_enriched.append({
            "title":        decode_entities(art.get("title", "")),
            "url":          art.get("url", ""),
            "source":       decode_entities(art.get("source", "")),
            "sources":      art.get("sources", []),
            "published_at": art.get("published_at", ""),
            "image_url":    art.get("image_url", ""),
            "summary":      final_summary,
            "region":       region,
            "language":     "hi",
            # translations.hi mirrors the article itself, it is already in Hindi.
            "translations": {
                "hi": {
                    "title":  decode_entities(art.get("title", "")),
                    "summary": final_summary,
                    "region": HINDI_REGION_LABELS.get(region, region),
                }
            },
        })

    # ── Editor's digest: 2-3 sentence lead, one LLM call per language ─────────
    digest_en = generate_edition_digest(en_enriched, language="en") if en_enriched else None
    digest_hi = generate_edition_digest(hi_enriched, language="hi") if hi_enriched else None
    # When Hindi sources are thin, translate the English digest so the Hindi
    # site still has an editor's note. Only do this if there is no native digest.
    if digest_en and not digest_hi:
        try:
            digest_hi = translate_texts_to_hindi([digest_en])[0]
        except Exception as exc:
            log.warning("Could not translate digest to Hindi: %s", exc)

    # ── Write newsletter.json (combined; site generator filters by language) ──
    all_enriched = en_enriched + hi_enriched

    payload = {
        "generated_at": fetched_at,
        "article_count": len(all_enriched),
        "total_unique_count": total_unique_count,
        "digest": {
            "en": digest_en or "",
            "hi": digest_hi or "",
        },
        "articles": all_enriched,
    }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("Wrote %s (%d articles: %d en, %d hi)",
             JSON_PATH, len(all_enriched), len(en_enriched), len(hi_enriched))

    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(build_markdown(en_enriched, fetched_at, display_tz, language="en"))
    log.info("Wrote %s", MD_PATH)

    with open(MD_HI_PATH, "w", encoding="utf-8") as f:
        f.write(build_markdown(hi_enriched, fetched_at, display_tz, language="hi"))
    log.info("Wrote %s", MD_HI_PATH)


if __name__ == "__main__":
    main()
