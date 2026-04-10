#!/usr/bin/env python3
"""
generate_site.py — Converts newsletter.md to site/index.html and generates an RSS feed.
Also archives the current newsletter into newsletters/YYYY-MM-DD-HH.md.
"""

import glob
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone

import markdown
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yml")
NEWSLETTER_PATH = os.path.join(ROOT, "newsletter.md")
SITE_DIR = os.path.join(ROOT, "site")
ARCHIVE_DIR = os.path.join(ROOT, "newsletters")
INDEX_PATH = os.path.join(SITE_DIR, "index.html")
FEED_PATH = os.path.join(SITE_DIR, "feed.xml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg["archive_days"] = int(os.environ.get("ARCHIVE_DAYS", cfg.get("archive_days", 30)))
    return cfg


def archive_newsletter(content: str, cfg: dict) -> list[dict]:
    """Archive current newsletter and return list of archive metadata."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.now(timezone.utc)
    archive_name = now.strftime("%Y-%m-%d-%H") + ".md"
    archive_path = os.path.join(ARCHIVE_DIR, archive_name)

    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("Archived newsletter to %s", archive_path)

    # Prune old archives beyond archive_days
    cutoff = now.timestamp() - cfg["archive_days"] * 86400
    pattern = os.path.join(ARCHIVE_DIR, "*.md")
    archives = []
    for path in sorted(glob.glob(pattern)):
        fname = os.path.basename(path)
        if fname == ".gitkeep":
            continue
        try:
            # Parse YYYY-MM-DD-HH.md
            stem = fname.replace(".md", "")
            parts = stem.split("-")
            if len(parts) == 4:
                dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]),
                               tzinfo=timezone.utc)
                if dt.timestamp() < cutoff:
                    os.remove(path)
                    log.info("Pruned old archive: %s", fname)
                    continue
                archives.append(
                    {
                        "filename": fname,
                        "date": dt.strftime("%B %d, %Y %H:00 UTC"),
                        "label": dt.strftime("%Y-%m-%d %H:00 UTC"),
                    }
                )
        except (ValueError, IndexError):
            pass

    archives.sort(key=lambda x: x["filename"], reverse=True)
    return archives


def build_archive_sidebar(archives: list[dict]) -> str:
    if not archives:
        return "<p class='no-archive'>No previous editions.</p>"
    items = "\n".join(
        f'<li><a href="../newsletters/{a["filename"]}" title="{a["date"]}">{a["label"]}</a></li>'
        for a in archives[:30]
    )
    return f'<ul class="archive-list">\n{items}\n</ul>'


def md_to_html(md_content: str) -> str:
    md = markdown.Markdown(extensions=["extra", "toc", "nl2br"])
    return md.convert(md_content)


def extract_title_and_date(md_content: str) -> tuple[str, str]:
    """Extract title and updated date from newsletter.md header."""
    title = "GeoPulse Newsletter"
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y %H:%M UTC")
    title_match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
    date_match = re.search(r"\*\*Updated:\*\*\s+(.+)", md_content)
    if date_match:
        date_str = date_match.group(1).strip()
    return title, date_str


def build_html(body_html: str, title: str, date_str: str, archive_sidebar: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css" />
  <link rel="alternate" type="application/rss+xml" title="GeoPulse RSS" href="feed.xml" />
  <meta name="description" content="Automated geopolitics newsletter — fresh global affairs insights every hour." />
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <div class="branding">
        <span class="logo">🌍</span>
        <span class="site-title">GeoPulse</span>
        <span class="tagline">Automated Geopolitics Intelligence</span>
      </div>
      <div class="header-actions">
        <a href="feed.xml" class="rss-link" title="Subscribe via RSS">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
               fill="currentColor" aria-hidden="true">
            <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19.01 7.38 20 6.18
                     20C4.98 20 4 19.01 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56
                     15.56 0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0
                     5.66a9.9 9.9 0 0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4
                     13.37V10.1z"/>
          </svg>
          RSS
        </a>
        <button id="theme-toggle" class="theme-toggle" aria-label="Toggle dark/light mode">
          <span class="icon-light">☀️</span>
          <span class="icon-dark">🌙</span>
        </button>
      </div>
    </div>
    <div class="last-updated">Last updated: <time>{date_str}</time></div>
  </header>

  <div class="layout">
    <main class="main-content">
      <article class="newsletter-body">
        {body_html}
      </article>
    </main>

    <aside class="sidebar">
      <h2 class="sidebar-title">📚 Archive</h2>
      {archive_sidebar}
    </aside>
  </div>

  <footer class="site-footer">
    <p>
      GeoPulse is an automated newsletter powered by
      <a href="https://github.com/features/actions" target="_blank" rel="noopener">GitHub Actions</a>.
      Data sourced from public news feeds. No guarantees of accuracy.
    </p>
  </footer>

  <script>
    const toggle = document.getElementById('theme-toggle');
    const html = document.documentElement;
    const stored = localStorage.getItem('geopulse-theme');
    if (stored) html.setAttribute('data-theme', stored);

    toggle.addEventListener('click', () => {{
      const current = html.getAttribute('data-theme');
      const next = current === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', next);
      localStorage.setItem('geopulse-theme', next);
    }});
  </script>
</body>
</html>"""


def generate_rss(md_content: str, archives: list[dict]) -> str:
    """Generate a basic RSS 2.0 feed from the latest newsletter."""
    title, date_str = extract_title_and_date(md_content)
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Build one item per archive edition
    items = ""
    for arch in archives[:10]:
        pub_date = arch.get("label", "")
        try:
            dt = datetime.strptime(pub_date, "%Y-%m-%d %H:00 UTC").replace(tzinfo=timezone.utc)
            rfc_date = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except ValueError:
            rfc_date = now_rfc
        fname = arch["filename"]
        items += f"""
    <item>
      <title>GeoPulse — {arch['date']}</title>
      <link>https://lavkeshdwivedi.github.io/geo-pulse/newsletters/{fname}</link>
      <guid>https://lavkeshdwivedi.github.io/geo-pulse/newsletters/{fname}</guid>
      <pubDate>{rfc_date}</pubDate>
      <description>Automated geopolitics digest for {arch['date']}</description>
    </item>"""

    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>GeoPulse — Automated Geopolitics Newsletter</title>
    <link>https://lavkeshdwivedi.github.io/geo-pulse/</link>
    <description>Hourly geopolitics intelligence powered by GitHub Actions.</description>
    <language>en-us</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="https://lavkeshdwivedi.github.io/geo-pulse/feed.xml"
               rel="self" type="application/rss+xml" />
    {items}
  </channel>
</rss>"""


def main() -> None:
    cfg = load_config()
    os.makedirs(SITE_DIR, exist_ok=True)

    if not os.path.exists(NEWSLETTER_PATH):
        log.error("newsletter.md not found at %s. Run summarize.py first.", NEWSLETTER_PATH)
        raise SystemExit(1)

    with open(NEWSLETTER_PATH, encoding="utf-8") as f:
        md_content = f.read()

    # Archive and get archive list
    archives = archive_newsletter(md_content, cfg)

    # Convert Markdown → HTML
    body_html = md_to_html(md_content)
    title, date_str = extract_title_and_date(md_content)
    archive_sidebar = build_archive_sidebar(archives)

    # Write index.html
    html = build_html(body_html, title, date_str, archive_sidebar)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("Wrote %s", INDEX_PATH)

    # Copy styles.css if not already in site/
    styles_src = os.path.join(SITE_DIR, "styles.css")
    if not os.path.exists(styles_src):
        log.warning("styles.css not found in site/ — skipping copy.")

    # Write RSS feed
    rss = generate_rss(md_content, archives)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        f.write(rss)
    log.info("Wrote %s", FEED_PATH)


if __name__ == "__main__":
    main()
