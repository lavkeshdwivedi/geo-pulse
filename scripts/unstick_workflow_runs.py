"""
Cancels GitHub Actions runs of a given workflow that are stuck in a
non-terminal state (waiting on deployment review, queued, or in_progress)
past a threshold.

Why this exists: newsletter.yml's build-and-deploy job targets the
github-pages environment inside a `newsletter-deploy` concurrency group
with cancel-in-progress: false. If that environment ever gains an
unreviewed deployment protection rule (e.g. required reviewers), the run
holding the job enters "waiting" and sits there forever — nobody is
watching to click approve. Every later scheduled run then queues behind
it and gets silently cancelled the moment the next hourly run supersedes
it in the queue, so the pipeline stops publishing with no failure ever
surfacing for monitor.yml (which only reacts to conclusion == 'failure')
to catch. This script clears that deadlock by cancelling the stale run
so the queue can drain again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

STUCK_STATUSES = {"waiting", "queued", "in_progress"}
THRESHOLD_MINUTES = 30


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> None:
    workflow = sys.argv[1] if len(sys.argv) > 1 else "newsletter.yml"
    repo = os.environ["GH_REPO"]

    # Query each stuck status directly rather than pulling the most recent
    # N runs and filtering client-side: an hourly cron produces hundreds of
    # runs between now and when a run got wedged, so a wedged run can fall
    # out of any "last N runs" window long before it's ever noticed.
    runs_by_id: dict[int, dict] = {}
    for status in STUCK_STATUSES:
        result = _run([
            "gh", "run", "list", "--repo", repo, "--workflow", workflow,
            "--status", status, "--json", "databaseId,status,createdAt", "--limit", "50",
        ])
        if result.returncode != 0:
            print(f"[unstick] gh run list --status {status} failed: {result.stderr.strip()}", file=sys.stderr)
            continue
        for run in json.loads(result.stdout or "[]"):
            runs_by_id[run["databaseId"]] = run

    now = datetime.now(timezone.utc)
    cancelled = 0

    for run in runs_by_id.values():
        created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
        age_minutes = (now - created).total_seconds() / 60
        if age_minutes < THRESHOLD_MINUTES:
            continue

        run_id = str(run["databaseId"])
        print(f"[unstick] cancelling run {run_id} ({run['status']}, {age_minutes:.0f}m old)")
        cancel = _run(["gh", "run", "cancel", run_id, "--repo", repo])
        if cancel.returncode == 0:
            cancelled += 1
        else:
            print(f"[unstick] cancel failed for {run_id}: {cancel.stderr.strip()}", file=sys.stderr)

    print(f"[unstick] done, cancelled {cancelled} stuck run(s)")


if __name__ == "__main__":
    main()
