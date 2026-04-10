#!/usr/bin/env python3
"""Update the auto-managed status block inside README.md."""

from __future__ import annotations

import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"
NEWSLETTER_JSON_PATH = ROOT / "newsletter.json"
CONFIG_PATH = ROOT / "config.yml"
ARCHIVES_GLOB = str(ROOT / "newsletters" / "????-??-??-??.md")

START_MARKER = "<!-- README-AUTO-STATUS:START -->"
END_MARKER = "<!-- README-AUTO-STATUS:END -->"


def _format_iso(iso_ts: str | None) -> str:
    if not iso_ts:
        return "unknown"
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso_ts


def _read_newsletter_data() -> tuple[str, int]:
    if not NEWSLETTER_JSON_PATH.exists():
        return "unknown", 0

    data = json.loads(NEWSLETTER_JSON_PATH.read_text(encoding="utf-8"))
    generated_at = _format_iso(data.get("generated_at"))
    article_count = int(data.get("article_count", 0))
    return generated_at, article_count


def _read_config_schedule() -> str:
    if not CONFIG_PATH.exists():
        return "unknown"

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    schedule = cfg.get("update_schedule", "unknown")
    return str(schedule)


def _read_archive_stats() -> tuple[str, int]:
    archives = sorted(glob.glob(ARCHIVES_GLOB))
    if not archives:
        return "none", 0

    latest = Path(archives[-1]).name
    return latest, len(archives)


def _build_block() -> str:
    generated_at, article_count = _read_newsletter_data()
    latest_archive, archive_count = _read_archive_stats()
    schedule = _read_config_schedule()
    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        START_MARKER,
        "## Project Status (auto-updated)",
        "",
        f"- Last newsletter build: {generated_at}",
        f"- Articles in latest edition: {article_count}",
        f"- Latest archive file: {latest_archive}",
        f"- Total archived editions: {archive_count}",
        f"- Configured schedule (cron): `{schedule}`",
        f"- README status last synced: {synced_at}",
        END_MARKER,
    ]
    return "\n".join(lines)


def main() -> None:
    if not README_PATH.exists():
        raise SystemExit("README.md does not exist")

    readme = README_PATH.read_text(encoding="utf-8")
    block = _build_block()

    if START_MARKER in readme and END_MARKER in readme:
        start = readme.index(START_MARKER)
        end = readme.index(END_MARKER) + len(END_MARKER)
        updated = readme[:start] + block + readme[end:]
    else:
        updated = readme.rstrip() + "\n\n" + block + "\n"

    README_PATH.write_text(updated, encoding="utf-8")
    print("README status block updated")


if __name__ == "__main__":
    main()
