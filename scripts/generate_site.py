#!/usr/bin/env python3
"""
generate_site.py — Reads newsletter.json and builds:
  - site/index.html  (Inshorts-style card dashboard)
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
from datetime import datetime, timezone

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH  = os.path.join(ROOT, "config.yml")
JSON_PATH    = os.path.join(ROOT, "newsletter.json")
MD_PATH      = os.path.join(ROOT, "newsletter.md")
SITE_DIR     = os.path.join(ROOT, "site")
ARCHIVE_DIR  = os.path.join(ROOT, "newsletters")
INDEX_PATH   = os.path.join(SITE_DIR, "index.html")
FEED_PATH    = os.path.join(SITE_DIR, "feed.xml")

SITE_URL     = "https://pulse.lavkesh.com"
SITE_TITLE   = "GeoPulse"
SITE_DESC    = "Automated geopolitics digest — fresh global affairs updates, every hour."

ALL_REGIONS  = ["All", "Americas", "Asia-Pacific", "Europe & Russia",
                "Middle East & Africa", "Global / Multilateral", "World"]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg["archive_days"] = int(os.environ.get("ARCHIVE_DAYS", cfg.get("archive_days", 30)))
    return cfg


# ── Archive helpers ───────────────────────────────────────────────────────────

def archive_newsletter(cfg: dict) -> list[dict]:
    """Copy newsletter.md into newsletters/ and prune old editions."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    if not os.path.exists(MD_PATH):
        return []

    now = datetime.now(timezone.utc)
    archive_name = now.strftime("%Y-%m-%d-%H") + ".md"
    shutil.copy2(MD_PATH, os.path.join(ARCHIVE_DIR, archive_name))
    log.info("Archived newsletter → newsletters/%s", archive_name)

    cutoff = now.timestamp() - cfg["archive_days"] * 86400
    archives = []
    for path in sorted(glob.glob(os.path.join(ARCHIVE_DIR, "????-??-??-??.md"))):
        fname = os.path.basename(path)
        stem  = fname.replace(".md", "")
        parts = stem.split("-")
        try:
            dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]),
                          tzinfo=timezone.utc)
            if dt.timestamp() < cutoff:
                os.remove(path)
                log.info("Pruned %s", fname)
                continue
            archives.append({
                "filename": fname,
                "label":    dt.strftime("%d %b %Y, %H:00 UTC"),
                "iso":      dt.isoformat(),
            })
        except (ValueError, IndexError):
            pass

    archives.sort(key=lambda x: x["filename"], reverse=True)
    return archives


# ── Time helper ───────────────────────────────────────────────────────────────

def time_ago(iso: str) -> str:
    """Return a human-readable 'X ago' string."""
    try:
        dt  = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return "just now"
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

def render_card(art: dict) -> str:
    title     = html.escape(art.get("title", ""))
    summary   = html.escape(art.get("summary", ""))
    url       = html.escape(art.get("url", "#"))
    source    = html.escape(art.get("source", ""))
    region    = html.escape(art.get("region", "World"))
    pub       = art.get("published_at", "")
    ago       = time_ago(pub)
    image_url = art.get("image_url", "")

    img_html = ""
    if image_url:
        safe_img = html.escape(image_url)
        img_html = f'<img class="card-img" src="{safe_img}" alt="" loading="lazy" onerror="this.parentElement.style.display=\'none\'">'

    return f"""
  <article class="card" data-region="{region}" data-url="{url}">
    {f'<div class="card-img-wrap">{img_html}</div>' if image_url else ''}
    <div class="card-body">
      <div class="card-meta-top">
        <span class="card-region">{region}</span>
        <span class="card-time">{ago}</span>
      </div>
      <h2 class="card-title">{title}</h2>
      <p class="card-summary">{summary}</p>
      <div class="card-footer">
        <a class="card-source" href="{url}" target="_blank" rel="noopener noreferrer">{source}</a>
        <a class="card-read-more" href="{url}" target="_blank" rel="noopener noreferrer">
          Read full story →
        </a>
      </div>
    </div>
  </article>"""


def render_archive_list(archives: list[dict]) -> str:
    if not archives:
        return '<li class="archive-empty">No previous editions</li>'
    items = "\n".join(
        f'<li><a href="{SITE_URL}/newsletters/{a["filename"]}">{a["label"]}</a></li>'
        for a in archives[:30]
    )
    return items


# ── Full page builder ─────────────────────────────────────────────────────────

def build_html(articles: list[dict], generated_at: str, archives: list[dict]) -> str:
    try:
        dt       = datetime.fromisoformat(generated_at)
        date_str = dt.strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        date_str = generated_at

    cards_html    = "\n".join(render_card(a) for a in articles) if articles else \
                    '<p class="empty-state">No stories in this edition yet.</p>'
    archive_items = render_archive_list(archives)
    count         = len(articles)

    # Build region filter tabs
    present_regions = sorted({a.get("region", "World") for a in articles})
    tab_html = '<button class="filter-tab active" data-filter="All">All <span class="tab-count">' + str(count) + '</span></button>\n'
    for reg in present_regions:
        n = sum(1 for a in articles if a.get("region") == reg)
        tab_html += f'<button class="filter-tab" data-filter="{html.escape(reg)}">{html.escape(reg)} <span class="tab-count">{n}</span></button>\n'

    articles_json = json.dumps(articles, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{SITE_TITLE} — Geopolitics in brief</title>
  <meta name="description" content="{SITE_DESC}" />
  <meta property="og:title" content="{SITE_TITLE}" />
  <meta property="og:description" content="{SITE_DESC}" />
  <meta property="og:url" content="{SITE_URL}" />
  <meta name="twitter:card" content="summary" />
  <link rel="stylesheet" href="styles.css" />
  <link rel="alternate" type="application/rss+xml" title="GeoPulse RSS" href="{SITE_URL}/feed.xml" />
</head>
<body>

  <!-- ── Header ─────────────────────────────────────────────────── -->
  <header class="app-header">
    <div class="header-inner">
      <a class="brand" href="{SITE_URL}">
        <span class="brand-logo">🌍</span>
        <span class="brand-name">GeoPulse</span>
      </a>
      <div class="header-right">
        <span class="update-badge">Updated {date_str}</span>
        <a class="rss-btn" href="{SITE_URL}/feed.xml" title="RSS feed" aria-label="RSS">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19.01 7.38 20 6.18 20
                     C4.98 20 4 19.01 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56
                     0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0
                     0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 13.37V10.1z"/>
          </svg>
        </a>
        <button id="theme-btn" class="theme-btn" aria-label="Toggle theme">
          <span class="light-icon">☀️</span><span class="dark-icon">🌙</span>
        </button>
      </div>
    </div>
    <p class="tagline">{SITE_DESC}</p>
  </header>

  <!-- ── Filter tabs ────────────────────────────────────────────── -->
  <nav class="filter-bar" aria-label="Filter by region">
    <div class="filter-inner">
      {tab_html}
    </div>
  </nav>

  <!-- ── Main layout ────────────────────────────────────────────── -->
  <div class="page-layout">

    <!-- Card feed -->
    <main class="card-feed" id="card-feed">
      {cards_html}
    </main>

    <!-- Sidebar -->
    <aside class="sidebar">
      <section class="sidebar-section">
        <h2 class="sidebar-heading">📚 Past Editions</h2>
        <ul class="archive-list">
          {archive_items}
        </ul>
      </section>
      <section class="sidebar-section about-section">
        <h2 class="sidebar-heading">About</h2>
        <p>GeoPulse fetches geopolitics news hourly and delivers each story in
           up to 100&nbsp;words — inspired by <a href="https://www.inshorts.com" target="_blank" rel="noopener">Inshorts</a>.</p>
        <p>Runs entirely on <strong>GitHub Actions</strong>. No servers. No ads.</p>
      </section>
    </aside>

  </div>

  <!-- ── Footer ─────────────────────────────────────────────────── -->
  <footer class="app-footer">
    <p>
      © GeoPulse · <a href="{SITE_URL}/feed.xml">RSS</a> ·
      Powered by <a href="https://github.com/lavkeshdwivedi/geo-pulse" target="_blank" rel="noopener">GitHub Actions</a>
      · Hosted at <a href="{SITE_URL}">{SITE_URL.replace("https://", "")}</a>
    </p>
  </footer>

  <script>
    // ── Theme toggle ─────────────────────────────────────────────
    const html = document.documentElement;
    const btn  = document.getElementById('theme-btn');
    const saved = localStorage.getItem('gp-theme');
    if (saved) html.dataset.theme = saved;
    btn.addEventListener('click', () => {{
      const next = html.dataset.theme === 'dark' ? 'light' : 'dark';
      html.dataset.theme = next;
      localStorage.setItem('gp-theme', next);
    }});

    // ── Region filter ────────────────────────────────────────────
    const tabs  = document.querySelectorAll('.filter-tab');
    const feed  = document.getElementById('card-feed');
    const cards = Array.from(feed.querySelectorAll('.card'));

    tabs.forEach(tab => {{
      tab.addEventListener('click', () => {{
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const filter = tab.dataset.filter;
        cards.forEach(card => {{
          const show = filter === 'All' || card.dataset.region === filter;
          card.style.display = show ? '' : 'none';
        }});
      }});
    }});
    // ── Clickable cards (tap anywhere to open source) ────────────
    document.querySelectorAll('.card[data-url]').forEach(card => {{
      card.addEventListener('click', e => {{
        if (!e.target.closest('a')) {{
          window.open(card.dataset.url, '_blank', 'noopener,noreferrer');
        }}
      }});
    }});
  </script>

</body>
</html>"""


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
    <title>{SITE_TITLE} — Geopolitics in brief</title>
    <link>{SITE_URL}</link>
    <description>{SITE_DESC}</description>
    <language>en-us</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    {items}
  </channel>
</rss>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = load_config()
    os.makedirs(SITE_DIR, exist_ok=True)

    if not os.path.exists(JSON_PATH):
        log.error("newsletter.json not found — run summarize.py first.")
        raise SystemExit(1)

    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    articles     = data.get("articles", [])
    generated_at = data.get("generated_at", datetime.now(timezone.utc).isoformat())

    archives = archive_newsletter(cfg)

    html_out = build_html(articles, generated_at, archives)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html_out)
    log.info("Wrote %s", INDEX_PATH)

    rss_out = build_rss(articles, archives)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        f.write(rss_out)
    log.info("Wrote %s", FEED_PATH)


if __name__ == "__main__":
    main()

