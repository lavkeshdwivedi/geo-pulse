"""
Shared LLM helper for GeoPulse, modelled after the fallback pattern used in
lavkesh.com/scripts/generate_article.py.

Pure stdlib. No external deps. Caller provides system + user prompts and gets
back plain text. The helper tries a chain of free-tier providers in
cost/latency order. Inside each provider we walk a sizeable model pool and
retry transient failures with exponential backoff, so one rate-limited model
should not kill the whole run.

Provider chain (free tier only):
  1. Groq      (fastest, generous free tier)        GROQ_API_KEY[_N]
  2. Gemini    (Google AI Studio free tier)         GEMINI_API_KEY[_N]

Multi-key support. Free tiers enforce per-account rate limits, so adding a
second account key doubles your effective throughput. Set the primary as
GROQ_API_KEY / GEMINI_API_KEY and additional ones as GROQ_API_KEY_2,
GROQ_API_KEY_3, ... (same for GEMINI). Keys are tried in order, with the
full model pool attempted against each. Cooldowns are tracked per
(model, key) pair so a 429 on key 1 does not block the same model on key 2.

If no keys are set, or every provider fails, returns None. Callers then
degrade to truncation or whatever non-LLM path they had.

Rate pacing: every outbound request passes through _pace_request so we never
exceed Groq's 30-RPM free-tier ceiling. On 429 we honour retry-after and
park the offending model for the cool-down window the provider asked for,
so the next call jumps straight to the next model in the pool instead of
hammering the one that's currently rate-limited.

Usage:
    from llm_client import llm_complete
    text = llm_complete(system_prompt, user_prompt, max_tokens=200, temperature=0.25)
    if text is None:
        ...  # fall back to non-LLM path
"""

from __future__ import annotations

import json
import logging
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


# Overall safety net so one provider cannot burn the whole budget.
OVERALL_TIMEOUT_SECONDS = 180
PER_CALL_TIMEOUT_SECONDS = 25

# How many times we retry the SAME model on a transient error (5xx, timeout).
# A 429 always skips straight to the next model because the current one is
# rate limited and another request will not help.
PER_MODEL_RETRIES = 2
RETRY_BACKOFF_BASE = 1.2  # seconds, multiplied by 2**attempt with jitter.

# ── Rate pacing ───────────────────────────────────────────────────────────────
# Groq free tier caps most models at 30 RPM. Space each call so a whole run of
# 40 summaries (20 en + 20 hi) stays comfortably below that ceiling for the
# same model. 3.0s between calls is exactly 20 RPM, comfortably under every
# free-tier ceiling and leaves plenty of headroom for retries.
# Groq free tier caps most models at 30 RPM. 2.0s between calls = 30 RPM
# exactly, which fully utilises the allowance (previous 3.0s capped at 20
# RPM and left a third of the throughput on the table). Override with the
# LLM_MIN_INTERVAL env var if a specific model has a tighter per-minute
# limit or if throttling becomes an issue.
MIN_REQUEST_INTERVAL_SECONDS = float(os.environ.get("LLM_MIN_INTERVAL", "2.0"))

# When a model returns 429 we park it for a cool-down window. The Groq
# response includes a `retry-after` header (seconds or HTTP date). We honour
# that when present, falling back to this default otherwise.
DEFAULT_COOLDOWN_SECONDS = 65

# Module-level bookkeeping. Kept intentionally simple: a single monotonic
# timestamp for last-request pacing and a per-model epoch-seconds cool-until
# map so we can skip recently-limited models without sleeping.
_last_request_at = 0.0
_model_cooldown_until: dict[str, float] = {}

# Models that returned a 404 (not found) or a 400 "decommissioned" at least
# once during this process. We never try them again for the rest of the run.
# This is separate from cooldowns because those failures are permanent for
# the lifetime of the process. A redeploy re-reads the pool from scratch.
_dead_models: set[str] = set()


# ── Model pools, fastest / highest daily quota first ────────────────────────

# Groq free tier, ordered so the cheapest and most generous-quota models go
# first, and reasoning-heavy models last. Reasoning models (gpt-oss, qwen3)
# tend to emit <think>...</think> or <सोचें>...</सोचें> blocks that leak
# into the summary. Summarize.py strips them, but it is cheaper and more
# reliable to try a non-reasoning model first. If you hit a 429 on one we
# fall through to the next immediately.
#
# Models decommissioned on Groq's free tier (confirmed 404/400 in prod
# logs, April 2026): llama-4-maverick-17b-128e-instruct, kimi-k2-instruct-0905,
# deepseek-r1-distill-llama-70b. Leaving them in the pool just wastes
# attempts on every call, so they are removed here.
_GROQ_MODELS = [
    # Small, fast, instruction-tuned non-reasoning models first. These
    # produce clean summaries and never leak <think> blocks.
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    # Reasoning-capable models next. Output may include <think> blocks,
    # callers sanitise and reasoning_format=hidden is also sent server-side.
    "qwen/qwen3-32b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
]
# Previously included but confirmed decommissioned in prod logs (April 2026):
#   gemma2-9b-it, llama-3.2-11b-vision-preview, llama-3.2-90b-vision-preview.
# Dropped so the pool stops wasting one attempt per run on each.

# Model substrings whose APIs accept the Groq-specific `reasoning_format`
# field. Setting it to "hidden" asks the backend to strip chain-of-thought
# before returning the response, which saves both tokens and post-processing.
# For models that do not recognise the field, we simply do not send it.
_GROQ_REASONING_MODEL_HINTS = ("deepseek-r1", "gpt-oss", "qwen3")

# Gemini free tier on AI Studio. 2.0-flash-lite has the highest RPD quota,
# so it leads. 2.5 models are stronger but more rate limited on free tier.
#
# gemini-1.5-flash and gemini-1.5-flash-8b were deprecated on AI Studio's
# free tier in early 2026 and now 404. Dropped from the pool.
_GEMINI_MODELS = [
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    # Speculative tail. Experimental endpoints that may have free-tier
    # quota on AI Studio. Retired automatically if they 404.
    "gemini-2.0-flash-exp",
    "gemini-exp-1206",
]


# Shared User-Agent for every outbound HTTP call so providers can identify us
# and so Google's edge does not flag the request as a bare client.
# ---------------------------------------------------------------------------
# Read User-Agent from config.yml so a fork can rebrand without code changes.
# Falls back to the generic template UA if config is missing.
# ---------------------------------------------------------------------------
def _load_user_agent_from_config() -> str:
    import os as _os
    try:
        import yaml as _yaml
    except Exception:
        return "GeoPulseTemplate/1.0"
    cfg_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "config.yml",
    )
    try:
        with open(cfg_path, encoding="utf-8") as _f:
            _data = _yaml.safe_load(_f) or {}
    except Exception:
        return "GeoPulseTemplate/1.0"
    _ua = ((_data.get("brand") or {}).get("user_agent") or "").strip()
    return _ua or "GeoPulseTemplate/1.0"


_USER_AGENT = f"Mozilla/5.0 (compatible; {_load_user_agent_from_config()})"


# Status codes. 429 = rate limited, move on. 5xx = transient, retry same model.
_RETRYABLE_SAME_MODEL = {500, 502, 503, 504}
_MOVE_TO_NEXT_MODEL = {408, 409}
_FATAL_BREAK_PROVIDER = {401, 403}


def _env_override_first(env_var, fallback_pool):
    """Let the caller force a single model via env, else use the whole pool."""
    override = os.environ.get(env_var)
    if override:
        return [override] + [m for m in fallback_pool if m != override]
    return list(fallback_pool)


# Per-provider max number of additional (numbered) keys to look up.
# GROQ_API_KEY_2, GROQ_API_KEY_3, ... up to _KEY_LIMIT. Plenty of room to
# stack free-tier accounts without polluting the env namespace.
_KEY_LIMIT = 8


def _collect_keys(env_prefix: str) -> list[str]:
    """Return an ordered, de-duplicated list of API keys for one provider.

    Looks up `<PREFIX>` as the primary key and `<PREFIX>_2` through
    `<PREFIX>_<LIMIT>` as additional keys. Empty values are skipped.
    """
    raw: list[str] = []
    primary = os.environ.get(env_prefix, "").strip()
    if primary:
        raw.append(primary)
    for i in range(2, _KEY_LIMIT + 1):
        k = os.environ.get(f"{env_prefix}_{i}", "").strip()
        if k:
            raw.append(k)
    seen: set[str] = set()
    uniq: list[str] = []
    for k in raw:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def _key_tag(api_key: str) -> str:
    """Short, stable, non-sensitive tag for a key.

    Used as the cooldown namespace so a 429 on one account does not block
    the same model on another account. We hash the key so the log line
    does not leak secrets, and keep just 6 hex chars, which is plenty to
    distinguish a handful of keys while remaining unguessable.
    """
    import hashlib
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:6]


def _sleep_backoff(attempt):
    """Exponential backoff with a little jitter. Attempt is 0-indexed."""
    delay = RETRY_BACKOFF_BASE * (2 ** attempt)
    delay = min(delay, 8.0)  # cap so we do not stall the whole run
    delay += random.uniform(0, 0.4)
    time.sleep(delay)


def _pace_request():
    """Sleep just long enough to keep us under the per-minute ceiling.

    We only need provider-agnostic pacing because Groq and Gemini both
    enforce per-minute caps on the free tier. Using one timer is simpler
    than per-provider buckets and plenty for a sequential pipeline.
    """
    global _last_request_at
    now = time.monotonic()
    gap = now - _last_request_at
    if gap < MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(MIN_REQUEST_INTERVAL_SECONDS - gap)
    _last_request_at = time.monotonic()


def _parse_retry_after(header_value):
    """Parse a retry-after header (seconds or HTTP date) into a delay."""
    if not header_value:
        return DEFAULT_COOLDOWN_SECONDS
    v = str(header_value).strip()
    try:
        return max(1.0, float(v))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(v)
        if dt is not None:
            import datetime as _dt
            delta = (dt - _dt.datetime.now(dt.tzinfo)).total_seconds()
            return max(1.0, min(delta, 300.0))
    except Exception:
        pass
    return DEFAULT_COOLDOWN_SECONDS


def _cool_key(model: str, instance: str = "") -> str:
    """Namespace a model's cooldown by API key tag.

    Empty instance keeps the old behaviour (cooldown is global for that
    model). When callers pass a key tag, different keys get independent
    cooldown buckets so one account hitting a 429 does not stall another
    account that still has quota.
    """
    return f"{model}|{instance}" if instance else model


def _model_is_cooling(model, instance: str = ""):
    until = _model_cooldown_until.get(_cool_key(model, instance), 0.0)
    return until > time.time()


def _cool_down_model(model, seconds, instance: str = ""):
    _model_cooldown_until[_cool_key(model, instance)] = time.time() + float(seconds)


def _single_request(req, provider_label, model):
    """Send one HTTP request and return (status, body, headers, exc).

    status is an int for HTTP responses and None for network errors so the
    caller can decide whether to retry or move on. Headers are returned so
    the walker can honour retry-after when the provider sends one.
    """
    _pace_request()
    try:
        with urllib.request.urlopen(req, timeout=PER_CALL_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, dict(resp.headers), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        try:
            headers = dict(exc.headers) if exc.headers is not None else {}
        except Exception:
            headers = {}
        return exc.code, body, headers, exc
    except (socket.timeout, urllib.error.URLError) as exc:
        log.warning("[%s] %s network error: %s", provider_label, model, exc)
        return None, None, {}, exc
    except Exception as exc:
        log.warning("[%s] %s unexpected %s", provider_label, model, type(exc).__name__)
        return None, None, {}, exc


def _walk_models(models, build_request, extract_text, provider_label, deadline, instance: str = ""):
    """Run the shared per-model retry + fallback loop.

    Skips any model currently cooling down from a recent 429 so we never burn
    attempts on a model the provider has already asked us to back off from.
    When `instance` is set (a per-API-key tag), cooldowns and the skip
    logic are scoped to that key, so a second account can try the same
    model without waiting for the first account's cooldown to clear.
    """
    last_error = None

    # Skip models that are permanently dead in this process (prior 404 /
    # decommissioned response). Among the survivors, prefer those not in
    # a cool-down window. Declared order wins inside each bucket.
    live = [m for m in models if m not in _dead_models]
    ready = [m for m in live if not _model_is_cooling(m, instance)]
    cooling = [m for m in live if _model_is_cooling(m, instance)]
    ordered = ready + cooling

    for model in ordered:
        if time.time() > deadline:
            log.info("[%s] deadline reached, skipping remaining models", provider_label)
            break
        if _model_is_cooling(model, instance):
            wait = _model_cooldown_until[_cool_key(model, instance)] - time.time()
            if wait > 6.0 or time.time() + wait > deadline:
                continue
            time.sleep(max(0.0, wait))

        for attempt in range(PER_MODEL_RETRIES + 1):
            req = build_request(model)
            status, body, headers, exc = _single_request(req, provider_label, model)

            # Network-level failure (timeout, DNS, connection reset).
            if status is None:
                last_error = "%s: network %s" % (model, type(exc).__name__)
                if attempt < PER_MODEL_RETRIES:
                    _sleep_backoff(attempt)
                    continue
                break

            # Success path.
            if 200 <= status < 300:
                try:
                    raw = json.loads(body or "{}")
                    text = (extract_text(raw) or "").strip()
                except Exception as parse_exc:
                    last_error = "%s: parse %s" % (model, parse_exc)
                    break
                if text:
                    log.info("[%s] ok via %s", provider_label, model)
                    return text
                last_error = model + ": empty response"
                break

            # HTTP error path.
            snippet = (body or "")[:80].replace("\n", " ")
            last_error = "%s: HTTP %s %s" % (model, status, snippet)

            if status in _FATAL_BREAK_PROVIDER:
                log.warning("[%s] %s failed: %s %s", provider_label, model, status, snippet)
                log.info("[%s] auth failure, giving up on provider", provider_label)
                return None
            # 404 Not Found or 400 "decommissioned" mean this model is not
            # coming back during this process. Retire it permanently so we
            # do not keep wasting attempts on every call.
            if status == 404 or (status == 400 and "decommis" in (body or "").lower()):
                _dead_models.add(model)
                log.warning(
                    "[%s] %s retired (HTTP %s). Will not retry this run.",
                    provider_label, model, status,
                )
                break
            if status == 429:
                retry_after = _parse_retry_after(
                    headers.get("retry-after") or headers.get("Retry-After") or ""
                )
                _cool_down_model(model, retry_after, instance)
                log.info(
                    "[%s] %s hit rate limit, cooling %.0fs",
                    provider_label, model, retry_after,
                )
                break
            if status in _MOVE_TO_NEXT_MODEL:
                log.warning("[%s] %s failed: %s %s", provider_label, model, status, snippet)
                break
            if status in _RETRYABLE_SAME_MODEL and attempt < PER_MODEL_RETRIES:
                log.warning("[%s] %s failed: %s %s", provider_label, model, status, snippet)
                _sleep_backoff(attempt)
                continue
            log.warning("[%s] %s failed: %s %s", provider_label, model, status, snippet)
            break

    if last_error:
        log.info("[%s] giving up. last error: %s", provider_label, last_error)
    return None


def _openai_extract_text(raw):
    return (raw.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _openai_chat(
    base_url,
    api_key,
    models,
    system_prompt,
    user_prompt,
    max_tokens,
    temperature,
    provider_label,
    deadline,
    instance: str = "",
):
    # is_groq check stays on provider_label rather than base_url so a future
    # Groq-compatible endpoint can be added without breaking this.
    is_groq = provider_label.startswith("Groq")

    def build(model):
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        # Groq-specific: ask reasoning models to suppress their chain of
        # thought server-side. Non-reasoning models ignore the field on
        # Groq. Other providers that reach this function should not see
        # a parameter they do not recognise.
        if is_groq and any(hint in model for hint in _GROQ_REASONING_MODEL_HINTS):
            payload["reasoning_format"] = "hidden"
        return urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "Authorization": "Bearer " + api_key,
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )

    return _walk_models(models, build, _openai_extract_text, provider_label, deadline, instance)


def _gemini_extract_text(raw):
    candidates = raw.get("candidates") or []
    chunks = []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            piece = part.get("text")
            if piece:
                chunks.append(piece)
    return "\n".join(chunks)


def _gemini_generate(
    api_key,
    models,
    system_prompt,
    user_prompt,
    max_tokens,
    temperature,
    deadline,
    provider_label: str = "Gemini",
    instance: str = "",
):
    """Call Gemini's native generateContent endpoint."""
    def build(model):
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        return urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-goog-api-key": api_key,
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )

    return _walk_models(models, build, _gemini_extract_text, provider_label, deadline, instance)


def _try_groq(system_prompt, user_prompt, max_tokens, temperature, deadline):
    """Iterate through every Groq key until one produces a summary.

    Each key gets its own cooldown namespace via _key_tag, so hitting a 429
    on key 1 does not block the same model when we fall through to key 2.
    Models already in _dead_models are skipped regardless of key.
    """
    keys = _collect_keys("GROQ_API_KEY")
    if not keys:
        return None
    for idx, api_key in enumerate(keys, start=1):
        if time.time() > deadline:
            return None
        # Always include the key index so logs show groq1, groq2, ... and
        # you can see exactly which configured API key handled a call.
        label = f"groq{idx}"
        log.info("[LLM] using %s (key %d of %d)", label, idx, len(keys))
        instance = _key_tag(api_key)
        result = _openai_chat(
            base_url="https://api.groq.com/openai/v1/chat/completions",
            api_key=api_key,
            models=_env_override_first("GROQ_MODEL", _GROQ_MODELS),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            provider_label=label,
            deadline=deadline,
            instance=instance,
        )
        if result:
            return result
    return None


def _try_gemini(system_prompt, user_prompt, max_tokens, temperature, deadline):
    """Iterate through every Gemini key until one produces a summary.

    Same pattern as _try_groq: per-key cooldown namespace via _key_tag,
    keys tried in declaration order, first non-empty result wins.
    """
    keys = _collect_keys("GEMINI_API_KEY")
    if not keys:
        return None
    for idx, api_key in enumerate(keys, start=1):
        if time.time() > deadline:
            return None
        # Always include the key index so logs show gemini1, gemini2, ... and
        # you can see exactly which configured API key handled a call.
        label = f"gemini{idx}"
        log.info("[LLM] using %s (key %d of %d)", label, idx, len(keys))
        instance = _key_tag(api_key)
        result = _gemini_generate(
            api_key=api_key,
            models=_env_override_first("GEMINI_MODEL", _GEMINI_MODELS),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            deadline=deadline,
            provider_label=label,
            instance=instance,
        )
        if result:
            return result
    return None


_DEFAULT_CHAIN = [
    ("groq", _try_groq),
    ("gemini", _try_gemini),
]


def llm_complete(
    system_prompt,
    user_prompt,
    max_tokens=400,
    temperature=0.25,
    preferred=None,
):
    """Run a prompt through the free-tier provider chain."""
    start = time.time()
    deadline = start + OVERALL_TIMEOUT_SECONDS

    chain = list(_DEFAULT_CHAIN)
    if preferred:
        chain.sort(key=lambda item: 0 if item[0] == preferred else 1)

    for name, runner in chain:
        if time.time() > deadline:
            log.info("[LLM] overall timeout hit, skipping remaining providers")
            break
        if not _has_key(name):
            continue
        log.info("[LLM] trying %s", name)
        text = runner(system_prompt, user_prompt, max_tokens, temperature, deadline)
        if text:
            return text
    return None


def _has_key(provider):
    mapping = {
        "groq":   "GROQ_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    return bool(os.environ.get(mapping.get(provider, "")))


def any_key_present():
    """Quick check for callers that want to decide the strategy upfront."""
    return any(_has_key(p) for p, _ in _DEFAULT_CHAIN)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if not any_key_present():
        print("No free-tier LLM keys set. Set GROQ_API_KEY or GEMINI_API_KEY.", file=sys.stderr)
        sys.exit(2)
    sys_msg = "You are a terse assistant. Reply in one sentence."
    usr_msg = sys.argv[1] if len(sys.argv) > 1 else "Say hi in five words."
    out = llm_complete(sys_msg, usr_msg, max_tokens=80)
    print(out or "[all providers failed]")
