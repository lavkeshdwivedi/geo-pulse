"""
LLM-powered workflow monitor for GeoPulse GitHub Actions.

Triggered by monitor.yml on workflow failure. Fetches logs, asks an LLM to
diagnose, applies a one-file patch or retriggers, never loops (monitor.yml
blocks retriggers from github-actions[bot] via triggering_actor check).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from llm_client import llm_json

REPO_ROOT = Path(__file__).resolve().parent.parent

WORKFLOW_SCRIPT_MAP: dict[str, list[str]] = {
    "newsletter.yml": [
        "scripts/fetch_news.py",
        "scripts/rank_articles.py",
        "scripts/summarize.py",
        "scripts/generate_site.py",
    ],
}

MAX_LOG_LINES = 150
MAX_SCRIPT_CHARS = 6000

SYSTEM_PROMPT = textwrap.dedent("""
    You are a GitHub Actions workflow repair bot for GeoPulse, an automated
    geopolitics newsletter. The site runs Python scripts to fetch, rank,
    summarise, and publish news via hourly scheduled workflows.
    Your job is to diagnose a workflow failure and decide the safest corrective action.

    Respond with a single valid JSON object only, no prose, no markdown fences:
    {
      "action": "retry" | "fix" | "skip",
      "reason": "one sentence diagnosis",
      "patch": {
        "file": "scripts/relative/path.py",
        "old_string": "exact string that must appear exactly once in the file",
        "new_string": "replacement string"
      }
    }

    Decision rules:
    - "retry": transient error (rate limit, network timeout, API 5xx, flaky gh command).
    - "fix": you can write a precise, safe patch. old_string MUST appear exactly once.
      Patch only Python scripts, never workflow YML files, never monitor.py itself.
      Patches must be minimal — one targeted change only.
    - "skip": secret missing, auth error, logic too complex, or ambiguous root cause.
    - Set patch to null for retry and skip.
""").strip()


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def fetch_logs(run_id: str) -> str:
    result = _run(["gh", "run", "view", run_id, "--log-failed"])
    raw = (result.stdout or result.stderr or "(no log output)").strip()
    lines = raw.splitlines()
    if len(lines) > MAX_LOG_LINES:
        omitted = len(lines) - MAX_LOG_LINES
        lines = [f"[... {omitted} earlier lines omitted ...]"] + lines[-MAX_LOG_LINES:]
    return "\n".join(lines)


def read_script(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    if not path.exists():
        return f"[{rel_path} not found]"
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > MAX_SCRIPT_CHARS:
        content = content[:MAX_SCRIPT_CHARS] + f"\n[... truncated at {MAX_SCRIPT_CHARS} chars ...]"
    return content


def build_user_prompt(workflow_file: str, workflow_name: str, logs: str, scripts: dict[str, str]) -> str:
    script_block = ""
    for rel_path, content in scripts.items():
        script_block += f"\n\n--- {rel_path} ---\n{content}"

    return textwrap.dedent(f"""
        Workflow: {workflow_name} ({workflow_file})

        === FAILED STEP LOGS (last {MAX_LOG_LINES} lines) ===
        {logs}

        === RELEVANT SCRIPTS ==={script_block}

        Diagnose and respond with the JSON action object.
    """).strip()


def apply_patch(patch: dict) -> bool:
    rel_path = patch.get("file", "")
    old_string = patch.get("old_string", "")
    new_string = patch.get("new_string", "")

    if not rel_path or not old_string:
        print("[monitor] patch missing file or old_string", file=sys.stderr)
        return False

    if rel_path in ("scripts/monitor.py", ".github/workflows/monitor.yml"):
        print("[monitor] refusing self-patch", file=sys.stderr)
        return False

    path = REPO_ROOT / rel_path
    if not path.exists():
        print(f"[monitor] patch target not found: {rel_path}", file=sys.stderr)
        return False

    content = path.read_text(encoding="utf-8")
    count = content.count(old_string)
    if count == 0:
        print(f"[monitor] old_string not found in {rel_path}", file=sys.stderr)
        return False
    if count > 1:
        print(f"[monitor] old_string appears {count} times, refusing ambiguous patch", file=sys.stderr)
        return False

    path.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
    print(f"[monitor] patched {rel_path}", file=sys.stderr)
    return True


def git_commit_and_push(rel_path: str, reason: str) -> bool:
    steps = [
        ["git", "config", "user.name", "github-actions[bot]"],
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        ["git", "add", rel_path],
        ["git", "commit", "-m", f"monitor: auto-fix {Path(rel_path).name}\n\n{reason}"],
    ]
    for cmd in steps:
        r = _run(cmd, cwd=REPO_ROOT)
        if r.returncode != 0:
            print(f"[monitor] git failed ({' '.join(cmd)}): {r.stderr.strip()}", file=sys.stderr)
            return False

    for attempt in range(1, 4):
        _run(["git", "pull", "--rebase", "origin", "main"], cwd=REPO_ROOT)
        r = _run(["git", "push", "origin", "HEAD:main"], cwd=REPO_ROOT)
        if r.returncode == 0:
            print("[monitor] pushed fix to main", file=sys.stderr)
            return True
        print(f"[monitor] push attempt {attempt} failed", file=sys.stderr)
    return False


def retrigger(workflow_file: str) -> None:
    r = _run(["gh", "workflow", "run", workflow_file, "--ref", "main"])
    if r.returncode == 0:
        print(f"[monitor] retriggered {workflow_file}", file=sys.stderr)
    else:
        print(f"[monitor] retrigger failed: {r.stderr.strip()}", file=sys.stderr)


def main() -> None:
    run_id = os.environ.get("FAILING_RUN_ID", "")
    workflow_name = os.environ.get("FAILING_WORKFLOW_NAME", "unknown")
    workflow_path = os.environ.get("FAILING_WORKFLOW_FILE", "")
    workflow_file = Path(workflow_path).name if workflow_path else ""

    if not run_id:
        print("[monitor] FAILING_RUN_ID not set, nothing to do", file=sys.stderr)
        sys.exit(0)

    print(f"[monitor] analysing run {run_id} ({workflow_name})", file=sys.stderr)

    logs = fetch_logs(run_id)
    rel_scripts = WORKFLOW_SCRIPT_MAP.get(workflow_file, [])
    scripts = {p: read_script(p) for p in rel_scripts}
    user_prompt = build_user_prompt(workflow_file, workflow_name, logs, scripts)

    try:
        response = llm_json(
            SYSTEM_PROMPT,
            user_prompt,
            max_tokens=800,
            temperature=0.2,
            providers=["gemini", "groq"],
        )
    except RuntimeError as exc:
        print(f"[monitor] LLM failed: {exc}", file=sys.stderr)
        print("[monitor] defaulting to retry", file=sys.stderr)
        if workflow_file:
            retrigger(workflow_file)
        sys.exit(0)

    action = response.get("action", "skip")
    reason = response.get("reason", "(no reason given)")
    patch = response.get("patch")

    print(f"[monitor] action={action} | {reason}", file=sys.stderr)

    if action == "fix" and isinstance(patch, dict):
        patched = apply_patch(patch)
        if patched:
            pushed = git_commit_and_push(patch["file"], reason)
            if pushed and workflow_file:
                retrigger(workflow_file)
            elif not pushed:
                print("[monitor] push failed, skipping retrigger", file=sys.stderr)
        else:
            print("[monitor] patch could not be applied, falling back to retry", file=sys.stderr)
            if workflow_file:
                retrigger(workflow_file)

    elif action == "retry":
        if workflow_file:
            retrigger(workflow_file)
        else:
            print("[monitor] retry requested but workflow file unknown", file=sys.stderr)

    else:
        print(f"[monitor] skipping: {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()
