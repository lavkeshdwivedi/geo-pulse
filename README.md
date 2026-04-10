# 🌍 GeoPulse

GeoPulse is an automated geopolitics newsletter delivering curated global affairs updates and smart summaries to your GitHub Pages site. Fresh insights, every hour.

## Features

- ⏰ Hourly (configurable) geopolitics news updates
- 🤖 AI-powered summaries (optional — works without any API key)
- ⚡ Completely automated using GitHub Actions
- 🌐 Beautiful responsive dashboard via GitHub Pages
- 📰 RSS feed for subscribers
- 🗂️ Auto-archiving of past editions with pruning

## How it works

1. **Fetch** — GitHub Actions polls GDELT and RSS feeds (BBC, Al Jazeera, Reuters, NYT, Guardian) for the latest geopolitics news.
2. **Summarise** — Articles are clustered by region and optionally summarised by an LLM.
3. **Publish** — A static site (`site/`) is built and deployed to GitHub Pages automatically.

## Live Site

**[pulse.lavkesh.com](https://pulse.lavkesh.com)**

<!-- README-AUTO-STATUS:START -->
## Project Status (auto-updated)

- Last newsletter build: 2026-04-10 16:01 UTC
- Articles in latest edition: 20
- Latest archive file: 2026-04-10-16.md
- Total archived editions: 1
- Configured schedule (cron): `0 * * * *`
- README status last synced: 2026-04-10 16:17 UTC
<!-- README-AUTO-STATUS:END -->

## Setup

### 1. Enable GitHub Pages

Go to **Settings → Pages → Source** and set it to **GitHub Actions**.

### 2. Grant workflow permissions

Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions**.

### 3. (Optional) Add API keys for richer content

In **Settings → Secrets and variables → Actions**, you can add:

| Secret / Variable | Purpose |
|---|---|
| `NEWSAPI_KEY` *(secret)* | Enable NewsAPI as a news source |
| `OPENAI_API_KEY` *(secret)* | Enable OpenAI GPT summaries |
| `ANTHROPIC_API_KEY` *(secret)* | Enable Anthropic Claude summaries |
| `HF_API_KEY` *(secret)* | Enable HuggingFace summarization |
| `LLM_PROVIDER` *(variable)* | `openai` / `anthropic` / `huggingface` / `none` (default: `none`) |
| `LLM_MODEL` *(variable)* | Model name, e.g. `gpt-4o-mini` |
| `NEWS_SOURCES` *(variable)* | Comma-separated: `gdelt,rss,newsapi` (default: `gdelt,rss`) |
| `MAX_ARTICLES` *(variable)* | Max articles per run (default: `20`) |
| `ARCHIVE_DAYS` *(variable)* | Days of archive to retain (default: `30`) |

> **No key needed to get started.** The default configuration uses GDELT and free RSS feeds with a formatted digest (no AI).

### 4. Trigger the first run

Go to **Actions → GeoPulse Newsletter → Run workflow** to trigger the first run manually.

## Configuration

All configuration is in `config.yml`. You can also override any setting via GitHub Actions variables.

To change the update frequency, edit the `cron` schedule in `.github/workflows/newsletter.yml`.

## Repository Structure

```
geo-pulse/
├── .github/workflows/newsletter.yml   # Scheduled workflow
├── scripts/
│   ├── fetch_news.py                  # News fetching (GDELT + RSS + NewsAPI)
│   ├── summarize.py                   # LLM summarization with graceful fallback
│   ├── generate_site.py               # Static site + RSS feed generator
│   └── update_readme.py               # Auto-sync README status block
├── site/
│   ├── index.html                     # GitHub Pages dashboard (auto-generated)
│   ├── styles.css                     # Responsive CSS with dark/light mode
│   └── feed.xml                       # RSS feed (auto-generated)
├── newsletters/                       # Auto-archived past editions
├── newsletter.md                      # Latest newsletter (auto-generated)
├── config.yml                         # Configuration
└── requirements.txt                   # Python dependencies
```

## Local Development

```bash
pip install -r requirements.txt
python scripts/fetch_news.py     # → raw_news.json
python scripts/summarize.py      # → newsletter.md
python scripts/generate_site.py  # → site/index.html + site/feed.xml
python scripts/update_readme.py   # → refresh auto-managed README status
```

Open `site/index.html` in your browser to preview the dashboard.

## Linting Hook

This repo now includes a pre-commit hook for Python linting and formatting checks.

```bash
pip install -r requirements.txt
pre-commit install
pre-commit run --all-files
```

The hook runs:

- `ruff check`
- `ruff format --check`