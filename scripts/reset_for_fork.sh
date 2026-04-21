#!/usr/bin/env bash
# Remove the previous owner's content so a forked template starts clean.
# Runs from the repo root. Safe to re-run: anything not present is skipped.
#
# What it clears:
#   - newsletter.md, newsletter.hi.md, newsletter.json, raw_news.json
#   - all archived editions under newsletters/ and newsletters/hi/
#   - all generated pages and archives under site/, except css/svg/png/manifest/CNAME
#
# What it keeps:
#   - your config.yml edits, your brand art, your CSS, your workflow file
#
# After running this, either push an empty commit or hit
# Actions -> GeoPulse Newsletter -> Run workflow. The first run rebuilds
# everything from your config and a fresh feed pull.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Clearing archived editions..."
rm -f newsletter.md newsletter.hi.md newsletter.json raw_news.json
rm -f newsletters/*.md
rm -f newsletters/hi/*.md
rm -f site/newsletters/*.md
rm -f site/newsletters/hi/*.md

echo "Clearing generated HTML and feed..."
rm -f site/index.html
rm -f site/hi/index.html
rm -f site/feed.xml

echo "Done. Commit the deletions, push, then trigger the workflow for a fresh build."
