# Contributing to GeoPulse

Thanks for looking. This is a personal template that happens to be public, not a supported product. Contributions are welcome and read, but kept realistic.

## The ground rules

There is no SLA on pull requests. I review them when I have time, which is usually weekends. If your PR has been sitting unreviewed for a month, ping me on the PR thread. If you need it merged urgently, you are better off maintaining the change on your own fork.

Small PRs land faster than big ones. If you want to rework a subsystem, open an issue first so we can agree on the shape before you write the code. I am much more likely to merge a scoped change with a clear rationale than a sweeping refactor.

## What I will probably merge

Bug fixes with a clear reproduction. Correctness improvements in the news-fetch, dedup, or summarization paths. Dependency bumps that fix known CVEs. Typos and documentation fixes. Small accessibility improvements in the generated site.

## What I am less likely to merge

Style refactors without a functional change. New optional features that add configuration surface area without broad applicability. Anything that makes the free-tier API path harder to use. Personal-branding-specific changes (those should live in your fork).

## Local checks before opening a PR

```bash
pip install -r requirements.txt
pre-commit install
pre-commit run --all-files
python scripts/generate_site.py   # confirms the site still renders
```

If the site render fails, your change probably broke something.

## Adding a new language

The language registry lives in `scripts/languages.py`. To add a third language (say Spanish):

1. Append an entry for your language to the `LANGUAGES` dict in `scripts/languages.py`. There is a commented-out Spanish example in place showing every required key: code, display name, site subdirectory, markdown filename, UI strings, region-label map, and a script-dominance check.

2. Add Spanish-language RSS feeds in `scripts/fetch_news.py` so articles get `language="es"` in `raw_news.json`. Reuse the existing Hindi source pattern.

3. Extend `REGION_KEYWORDS` in `scripts/summarize.py` with Spanish country names, capitals, and leaders so the classifier buckets Spanish articles into the right region.

4. For an MVP, `summarize.py` and `generate_site.py` currently branch on language in a few places (`if language == "hi"`). Duplicate those branches for your new code or, better, loop over `language_codes()` from `scripts/languages.py`. The registry is there so a bigger refactor later becomes a one-file change.

5. Run the workflow. The new language gets its own `/es/` subdirectory, filter pills, archive pages, and language switcher entry once `generate_site.py` sees it.

If you add a language and something breaks, the workflow's validation step will fail loudly rather than silently serving stale content. That's by design.

## Licensing

By contributing, you agree your changes are licensed under the same [MIT license](LICENSE) that covers the rest of the project.
