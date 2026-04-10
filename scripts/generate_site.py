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
from urllib.parse import urlparse

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH  = os.path.join(ROOT, "config.yml")
JSON_PATH    = os.path.join(ROOT, "newsletter.json")
MD_PATH      = os.path.join(ROOT, "newsletter.md")
SITE_DIR     = os.path.join(ROOT, "site")
ARCHIVE_DIR  = os.path.join(ROOT, "newsletters")
SITE_ARCHIVE_DIR = os.path.join(SITE_DIR, "newsletters")
INDEX_PATH   = os.path.join(SITE_DIR, "index.html")
FEED_PATH    = os.path.join(SITE_DIR, "feed.xml")

SITE_URL     = "https://pulse.lavkesh.com"
SITE_TITLE   = "GeoPulse"
SITE_DESC    = "Signal-first briefs on geopolitics, geography, and world history."
SITE_TAGLINE = "Global affairs, without the noise."

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
    os.makedirs(SITE_ARCHIVE_DIR, exist_ok=True)
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

    # Publish archive files under site/newsletters so links never point
    # to files outside the deployed Pages artifact.
    for old in glob.glob(os.path.join(SITE_ARCHIVE_DIR, "????-??-??-??.md")):
        try:
            os.remove(old)
        except OSError:
            pass

    published_archives: list[dict] = []
    for a in archives:
        src = os.path.join(ARCHIVE_DIR, a["filename"])
        dst = os.path.join(SITE_ARCHIVE_DIR, a["filename"])
        try:
            shutil.copy2(src, dst)
            if os.path.exists(dst):
                published_archives.append(a)
        except OSError as exc:
            log.warning("Failed to publish archive %s: %s", a["filename"], exc)

    return published_archives


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


def render_card(art: dict) -> str:
    title     = html.escape(art.get("title", ""))
    summary   = html.escape(art.get("summary", ""))
    safe_url_raw = _safe_external_url(art.get("url", ""))
    url          = html.escape(safe_url_raw or "#")
    region    = html.escape(art.get("region", "World"))
    genre     = html.escape(art.get("genre", "Geopolitics"))
    pub       = art.get("published_at", "")
    ago       = time_ago(pub)
    image_url = _safe_external_url(_upgrade_image_url(art.get("image_url", "")))

    img_html = ""
    if image_url:
        safe_img = html.escape(image_url)
        img_html = f'<img class="card-img" src="{safe_img}" alt="" loading="lazy" onerror="this.parentElement.style.display=\'none\'">'

    # Build source chips — use the merged sources list when available and
    # non-empty, otherwise fall back to the single url/source on the article.
    _sources = art.get("sources")
    raw_sources: list[dict] = _sources if _sources else [{"url": art.get("url", ""), "source": art.get("source", "")}]
    source_chips = "".join(
      f'<a class="card-source-chip" href="{html.escape(_safe_external_url(s["url"]))}" '
        f'target="_blank" rel="noopener noreferrer">{html.escape(s["source"])}</a>'
        for s in raw_sources
      if _safe_external_url(s.get("url", "")) and s.get("source")
    )
    sources_html = f'<div class="card-sources">{source_chips}</div>' if source_chips else ""

    return f"""
  <article class="card" data-region="{region}" data-url="{url}">
    {f'<div class="card-img-wrap">{img_html}</div>' if image_url else ''}
    <div class="card-body">
      <div class="card-meta-top">
        <div class="card-topic-wrap">
          <span class="card-region">{region}</span>
          <span class="card-genre">{genre}</span>
        </div>
        <span class="card-time">{ago}</span>
      </div>
      <h2 class="card-title">{title}</h2>
      <p class="card-summary">{summary}</p>
      {sources_html}
    </div>
  </article>"""


def render_archive_list(archives: list[dict]) -> str:
  if not archives:
    return ""
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
    archive_section = ""
    if archive_items:
        archive_section = f"""
      <section class="sidebar-section">
        <h2 class="sidebar-heading">📚 Past Editions</h2>
        <ul class="archive-list">
          {archive_items}
        </ul>
      </section>"""
    count         = len(articles)

    # Build region filter tabs
    present_regions = sorted({a.get("region", "World") for a in articles})
    tab_html = '<button class="filter-tab active" data-filter="All">All <span class="tab-count">' + str(count) + '</span></button>\n'
    for reg in present_regions:
        n = sum(1 for a in articles if a.get("region") == reg)
        tab_html += f'<button class="filter-tab" data-filter="{html.escape(reg)}">{html.escape(reg)} <span class="tab-count">{n}</span></button>\n'

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
  <meta name="referrer" content="strict-origin-when-cross-origin" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' https: data:; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; upgrade-insecure-requests" />
  <link rel="canonical" href="{SITE_URL}" />
  <link rel="icon" type="image/svg+xml" href="favicon.svg" />
  <link rel="alternate icon" type="image/svg+xml" href="favicon.svg" />
  <link rel="apple-touch-icon" href="favicon.svg" />
  <meta name="theme-color" content="#0078d4" media="(prefers-color-scheme: light)" />
  <meta name="theme-color" content="#131109" media="(prefers-color-scheme: dark)" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=JetBrains+Mono:wght@400;500&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&display=swap" />
  <link rel="stylesheet" href="styles.css" />
  <link rel="alternate" type="application/rss+xml" title="GeoPulse RSS" href="{SITE_URL}/feed.xml" />
  <script>(function(){{var t=localStorage.getItem('gp-theme');if(t)document.documentElement.dataset.theme=t;var a=localStorage.getItem('gp-accent');if(a)document.documentElement.dataset.accent=a;}})();</script>
</head>
<body>

  <!-- ── Header ─────────────────────────────────────────────────── -->
  <header class="app-header">
    <div class="header-inner">
      <a class="brand" href="{SITE_URL}">
        <img class="brand-logo" src="logo.svg" alt="GeoPulse logo" />
        <span class="brand-name">GeoPulse</span>
      </a>
      <div class="header-right">
        <div class="header-time-group">
          <span class="update-badge" title="Last generated (UTC)">Updated {date_str}</span>
          <span class="local-clock" id="local-clock">
            <svg class="clock-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            <span id="local-time">--:--:--</span>
            <span id="local-tz" class="local-tz"></span>
          </span>
        </div>
        <a class="rss-btn" href="{SITE_URL}/feed.xml" title="RSS feed" aria-label="RSS">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19.01 7.38 20 6.18 20
                     C4.98 20 4 19.01 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56
                     0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0
                     0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 13.37V10.1z"/>
          </svg>
        </a>
        <div class="accent-picker" id="accent-picker">
          <button class="accent-picker-btn" id="accent-btn" aria-label="Choose accent colour" aria-haspopup="true" aria-expanded="false">
            <span class="accent-dot" id="accent-dot"></span>
          </button>
          <div class="accent-menu" id="accent-menu" hidden role="listbox" aria-label="Accent colour">
            <button role="option" data-accent=""         style="background:#e63946" title="Crimson (default)" aria-selected="true"></button>
            <button role="option" data-accent="azure"    style="background:#0078d4" title="Azure"></button>
            <button role="option" data-accent="ocean"    style="background:#0ea5e9" title="Ocean"></button>
            <button role="option" data-accent="emerald"  style="background:#10b981" title="Emerald"></button>
            <button role="option" data-accent="mint"     style="background:#2dd4bf" title="Mint"></button>
            <button role="option" data-accent="ember"    style="background:#e07020" title="Ember"></button>
            <button role="option" data-accent="sunset"   style="background:#fb923c" title="Sunset"></button>
            <button role="option" data-accent="gold"     style="background:#d4a017" title="Gold"></button>
            <button role="option" data-accent="violet"   style="background:#a855f7" title="Violet"></button>
            <button role="option" data-accent="lavender" style="background:#c084fc" title="Lavender"></button>
            <button role="option" data-accent="rose"     style="background:#f472b6" title="Rose"></button>
            <button role="option" data-accent="storm"    style="background:#6366f1" title="Storm"></button>
            <button role="option" data-accent="slate"    style="background:#64748b" title="Slate"></button>
          </div>
        </div>
        <button id="theme-btn" class="theme-btn" aria-label="Toggle theme">
          <span class="light-icon">☀️</span><span class="dark-icon">🌙</span>
        </button>
      </div>
    </div>
    <p class="tagline">{SITE_TAGLINE}</p>
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
      {archive_section}
      <section class="sidebar-section about-section">
        <h2 class="sidebar-heading">About GeoPulse</h2>
        <p>GeoPulse is my editorial desk for global affairs: concise, verified, and signal-first coverage for people who need context, not noise.</p>
        <p>The brief covers geopolitics, geography, and world-history threads that explain how events connect across regions and time.</p>
        <p class="about-byline"><strong>Editor:</strong> Lavkesh Dwivedi</p>
        <ul class="profile-links">
          <li><a href="https://lavkesh.com" target="_blank" rel="noopener">Website</a></li>
          <li><a href="https://linkedin.com/in/lavkesh" target="_blank" rel="noopener">LinkedIn</a></li>
          <li><a href="https://x.com/lavkeshdwivedi" target="_blank" rel="noopener">X</a></li>
          <li><a href="https://github.com/lavkeshdwivedi" target="_blank" rel="noopener">GitHub</a></li>
          <li><a href="https://instagram.com/lavkeshdwivedi" target="_blank" rel="noopener">Instagram</a></li>
          <li><a href="https://facebook.com/lavkesh" target="_blank" rel="noopener">Facebook</a></li>
        </ul>
      </section>
    </aside>

  </div>

  <!-- ── Footer ─────────────────────────────────────────────────── -->
  <footer class="app-footer">
    <p>
      © GeoPulse · <a href="{SITE_URL}/feed.xml">RSS</a> ·
      Hosted at <a href="{SITE_URL}">{SITE_URL.replace("https://", "")}</a> ·
      <a href="https://lavkesh.com" target="_blank" rel="noopener">lavkesh.com</a>
    </p>
    <p class="footer-social-links">
      <a href="https://linkedin.com/in/lavkesh" target="_blank" rel="noopener">LinkedIn</a> ·
      <a href="https://x.com/lavkeshdwivedi" target="_blank" rel="noopener">X</a> ·
      <a href="https://github.com/lavkeshdwivedi" target="_blank" rel="noopener">GitHub</a>
    </p>
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
    const saved = localStorage.getItem('gp-theme');
    if (saved) html.dataset.theme = saved;
    btn.addEventListener('click', () => {{
      const next = html.dataset.theme === 'dark' ? 'light' : 'dark';
      html.dataset.theme = next;
      localStorage.setItem('gp-theme', next);
    }});

    // ── Local clock ──────────────────────────────────────────────
    (function() {{
      const timeEl = document.getElementById('local-time');
      const tzEl   = document.getElementById('local-tz');
      function tick() {{
        const now = new Date();
        if (timeEl) timeEl.textContent = now.toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit', second: '2-digit' }});
        if (tzEl && !tzEl.textContent) {{
          try {{
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            tzEl.textContent = tz.split('/').pop().replace(/_/g, '\u00a0');
          }} catch (_) {{}}
        }}
      }}
      tick();
      setInterval(tick, 1000);
    }})();

    // ── Accent picker ─────────────────────────────────────────────
    const accentBtn  = document.getElementById('accent-btn');
    const accentMenu = document.getElementById('accent-menu');
    if (accentBtn && accentMenu) {{
      const savedAccent = localStorage.getItem('gp-accent') || '';
      if (savedAccent) html.dataset.accent = savedAccent;
      accentMenu.querySelectorAll('[role=option]').forEach(b => {{
        b.setAttribute('aria-selected', (b.dataset.accent || '') === savedAccent ? 'true' : 'false');
      }});
      const closeMenu = () => {{
        accentMenu.hidden = true;
        accentBtn.setAttribute('aria-expanded', 'false');
      }};
      accentBtn.addEventListener('click', e => {{
        e.stopPropagation();
        const isOpen = !accentMenu.hidden;
        accentMenu.hidden = isOpen;
        accentBtn.setAttribute('aria-expanded', String(!isOpen));
      }});
      accentMenu.querySelectorAll('[role=option]').forEach(b => {{
        b.addEventListener('click', () => {{
          const v = b.dataset.accent || '';
          if (v) {{ html.dataset.accent = v; }} else {{ delete html.dataset.accent; }}
          localStorage.setItem('gp-accent', v);
          accentMenu.querySelectorAll('[role=option]').forEach(x => x.setAttribute('aria-selected', 'false'));
          b.setAttribute('aria-selected', 'true');
          closeMenu();
        }});
      }});
      document.addEventListener('click', e => {{
        if (!accentBtn.contains(e.target) && !accentMenu.contains(e.target)) closeMenu();
      }});
    }}

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
          const targetUrl = card.dataset.url || '';
          try {{
            const parsed = new URL(targetUrl);
            if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return;
          }} catch (_) {{
            return;
          }}
          window.open(targetUrl, '_blank', 'noopener,noreferrer');
        }}
      }});
    }});

    // ── Hide broken archive links/section ────────────────────────
    (function() {{
      const anchors = Array.from(document.querySelectorAll('.archive-list a'));
      if (!anchors.length) return;
      const checks = anchors.map(async a => {{
        const li = a.closest('li');
        try {{
          const res = await fetch(a.href, {{ method: 'HEAD', cache: 'no-store' }});
          if (!res.ok && li) li.remove();
        }} catch (_) {{
          if (li) li.remove();
        }}
      }});
      Promise.all(checks).then(() => {{
        document.querySelectorAll('.archive-list').forEach(list => {{
          if (!list.querySelector('li')) {{
            const section = list.closest('.sidebar-section');
            if (section) section.remove();
          }}
        }});
      }});
    }})();
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

    # Sort newest-first so the latest stories always appear at the top.
    articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)

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

