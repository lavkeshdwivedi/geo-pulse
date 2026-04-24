# 🌍 GeoPulse

GeoPulse is a self-running, hourly geopolitics newsletter that publishes to GitHub Pages with zero servers and zero upkeep. You fork it, fill in a few free API keys, flip on Pages, and a GitHub Actions workflow quietly does the rest every hour. Live demo at [pulse.lavkesh.com](https://pulse.lavkesh.com).

## Use this template

Click the green **Use this template** button above and pick **Create a new repository**. That gives you a clean copy of the code without the history of my personal runs. If the button is not showing, the fork owner needs to go to **Settings → General** and tick **Template repository** first. Once ticked, GitHub gives every visitor the **Use this template** button on the repo landing page.

## Minimum-viable setup

1. Clone your new repo locally.
2. Open `config.yml` and edit the `brand:` block. These are the only keys you have to change to make the published output yours:
   - `editor_name` and `editor_name_hi` shown in the about block and the footer credit. The `_hi` variant is used on the Hindi edition.
   - `editor_website` rendered inside the about paragraphs.
   - `site_title` used in the browser tab, every meta tag, and the header brand mark.
   - `site_url` the canonical URL. It must match whatever GitHub Pages actually serves you.
   - `language_switch_path` where the header language toggle points. Leave it at `/hi` if you want a Hindi edition, set it to `/` to disable the toggle.
   - `user_agent` the `User-Agent` header every outbound request sends. Publishers do read this, so keep a reachable contact URL inside the string.
   - `custom_domain` your GitHub Pages custom domain. Leave empty and the build will remove any stale `site/CNAME`. Set it to `news.example.com` and the build writes CNAME for you so a fork never inherits the previous owner's domain.
   - `social` the six footer icons. Blank any value to hide that icon.
3. In **Settings → Secrets and variables → Actions**, add the API keys you want. Every key is optional but having at least one LLM key is what gives you real summaries instead of RSS blurbs:
   - `GROQ_API_KEY` or `GEMINI_API_KEY` for LLM summaries. Both have free tiers that comfortably cover 24 hourly runs a day.
   - `PEXELS_API_KEY` and `UNSPLASH_ACCESS_KEY` for the stock image fallback when articles do not ship their own og:image.
   - `NEWSAPI_KEY` if you want NewsAPI as a news source on top of RSS and Google News. Optional.
4. In **Settings → Pages**, set the source to **GitHub Actions**. In **Settings → Actions → General**, set **Workflow permissions** to **Read and write permissions** so the workflow can commit the generated site back to `main`.
5. Start with a clean slate. "Use this template" copies every archived edition the original owner had published. Run `bash scripts/reset_for_fork.sh` to wipe `newsletters/`, `site/newsletters/`, and the generated HTML so your first build is genuinely yours. Commit the deletions and push.
6. Either wait for the hourly cron or trigger the first run manually from **Actions → GeoPulse Newsletter → Run workflow**. The first run takes a few minutes because it has to pull every feed from cold.
7. Visit whatever URL you set as `site_url`. You should see your newsletter live.

## Other files a forker should touch

A few brand surfaces live outside the Python code and `config.yml`:

- `site/manifest.webmanifest` PWA name, short name, description, and the shortcut copy.
- `site/favicon.svg`, `site/logo.svg`, `site/apple-touch-icon.svg` and the matching PNG set under `site/` your artwork.
- `linkedin-featured/` the original owner's LinkedIn profile featured card. The build does not reference it; delete the directory or replace the SVG with your own if you use LinkedIn's "featured" section.
- `STYLE.md` the editorial voice guide the LLM reads on every run. Rewrite if you want a different tone.
- `scripts/voice.py` the persona the LLM inherits. There is a `TODO (forker)` banner at the top telling you what to swap.
- The about-the-editor paragraphs inside `scripts/generate_site.py` `SITE_COPY` are personal copy. They have a `TODO (forker)` marker right above them.

## Features

Hourly geopolitics news aggregation. Smart update detection so it only publishes when fresh stories appear. Optional AI summaries with free-tier LLM providers. Completely automated via GitHub Actions with direct commits to `main`. Responsive dashboard with dark and light mode, thirteen accent colours, and a Hindi edition. RSS feed for subscribers. Every hourly edition kept forever as archived markdown under `newsletters/`.

## Live Site

**[pulse.lavkesh.com](https://pulse.lavkesh.com)**

<!-- README-AUTO-STATUS:START -->
## Project Status (auto-updated)

- Last newsletter build: 2026-04-24 17:01 UTC
- Stories published on homepage: 42
- Unique stories found this run: 256
- Latest archive file: 2026-04-24-17.md
- Total archived editions: 213
- Configured schedule (cron): `0 * * * *`
- README status last synced: 2026-04-24 17:01 UTC
<!-- README-AUTO-STATUS:END -->

## Configuration

All configuration lives in `config.yml`. You can also override any setting via GitHub Actions variables.

The site homepage renders its `Updated` label in each visitor's browser timezone. Static generated files like the README block and newsletter markdown use `display_timezone` from `config.yml` or `DISPLAY_TIMEZONE` in Actions variables.

To change the update frequency, edit the `cron` schedule in `.github/workflows/newsletter.yml`.

| Secret / Variable | Purpose |
|---|---|
| `NEWSAPI_KEY` *(secret)* | Enable NewsAPI as a news source |
| `GROQ_API_KEY` *(secret)* | Enable Groq Llama summaries (free tier, recommended) |
| `GEMINI_API_KEY` *(secret)* | Enable Google Gemini summaries (free tier, alternative) |
| `PEXELS_API_KEY` *(secret)* | Stock image fallback when article lacks og:image |
| `UNSPLASH_ACCESS_KEY` *(secret)* | Secondary stock image fallback after Pexels |
| `HF_API_KEY` *(secret)* | Enable HuggingFace summarization |
| `LLM_PROVIDER` *(variable)* | `groq` / `gemini` / `huggingface` / `none` (default: `groq`) |
| `LLM_MODEL` *(variable)* | Model name, e.g. `llama-3.1-8b-instant` |
| `NEWS_SOURCES` *(variable)* | Comma-separated: `rss,newsapi` (default: `rss`) |
| `MAX_ARTICLES` *(variable)* | Max stories published to the homepage per run (default: `21`) |
| `DISPLAY_TIMEZONE` *(variable)* | Human-facing timezone for generated static files (default: `Asia/Kolkata`) |

## Repository Structure

```
geo-pulse/
├── .github/workflows/newsletter.yml   # Scheduled workflow
├── scripts/
│   ├── fetch_news.py                  # News fetching (RSS + NewsAPI + Google News)
│   ├── summarize.py                   # LLM summarization with graceful fallback
│   ├── generate_site.py               # Static site + RSS feed generator
│   └── update_readme.py               # Auto-sync README status block
├── site/
│   ├── index.html                     # GitHub Pages dashboard (auto-generated)
│   ├── styles.css                     # Responsive CSS with dark/light mode
│   ├── feed.xml                       # RSS feed (auto-generated)
│   ├── manifest.webmanifest           # PWA manifest (edit on fork)
│   └── favicon.svg, logo.svg, ...     # Brand art (edit on fork)
├── newsletters/                       # Auto-archived past editions (kept forever)
├── newsletter.md                      # Latest newsletter (auto-generated)
├── config.yml                         # Configuration (brand block at top)
└── requirements.txt                   # Python dependencies
```

## Local Development

```bash
pip install -r requirements.txt
python scripts/fetch_news.py     # raw_news.json
python scripts/summarize.py      # newsletter.md
python scripts/generate_site.py  # site/index.html + site/feed.xml
python scripts/update_readme.py  # refresh auto-managed README status
```

Open `site/index.html` in your browser to preview the dashboard.

## Linting Hook

This repo includes a pre-commit hook for Python linting and formatting.

```bash
pip install -r requirements.txt
pre-commit install
pre-commit run --all-files
```

The hook runs `ruff check` and `ruff format --check`.

## Support

This is a personal template, published publicly because it is useful. It is not a supported product. Issues and pull requests are welcome but there is no SLA and no guarantee anything will get merged. Expect slow response, especially on questions about your specific domain, DNS, GitHub Pages quirks, or third-party API changes. If you build something with it, a link back is appreciated but not required.

## License

MIT. See [LICENSE](LICENSE).
