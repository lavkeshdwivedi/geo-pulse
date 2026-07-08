"""
Shared LLM helper for GeoPulse — backed by kognios.

Provider chain (free tier only, Gemini-first for GeoPulse's workload):
  1. Gemini    GEMINI_API_KEY[_N]   best quality on free tier
  2. Groq      GROQ_API_KEY[_N]     fastest fallback, generous quota

Multiple API keys per provider are supported via a numeric suffix:
GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3, ... (and same for GROQ).
Adding a second account key roughly doubles effective throughput because
cooldowns are tracked per (key, model) pair inside kognios.

Returns None when every provider fails. Callers degrade to truncation or
whatever non-LLM path they had.

Usage:
    from llm_client import llm_complete, llm_json, any_key_present
    text = llm_complete(system_prompt, user_prompt, max_tokens=200, temperature=0.25)
    if text is None:
        ...  # fall back to non-LLM path
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

log = logging.getLogger(__name__)

try:
    from kognios.models.chain import free_tier_chain, _collect_keys, _GEMINI_MODELS, _GROQ_MODELS
    _KOGNIOS_OK = True
except ImportError:
    _KOGNIOS_OK = False


def any_key_present() -> bool:
    if not _KOGNIOS_OK:
        return False
    return bool(_collect_keys("GEMINI_API_KEY") or _collect_keys("GROQ_API_KEY"))


def llm_complete(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 400,
    temperature: float = 0.25,
    preferred: str | None = None,
    providers: list[str] | None = None,
    **_,
) -> str | None:
    """Run a prompt through the GeoPulse free-tier chain (Gemini -> Groq)."""
    if not _KOGNIOS_OK:
        return None

    _preferred = preferred or "gemini"
    gemini_pool = _GEMINI_MODELS
    groq_pool = _GROQ_MODELS

    if providers:
        wanted = {p.lower() for p in providers}
        gemini_pool = _GEMINI_MODELS if "gemini" in wanted else []
        groq_pool = _GROQ_MODELS if "groq" in wanted else []
        if "groq" in wanted and "gemini" not in wanted:
            _preferred = "groq"

    chain = free_tier_chain(
        preferred=_preferred,
        gemini_models=gemini_pool or None,
        groq_models=groq_pool or None,
        together_models=[],
        anthropic_models=[],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if not chain.models:
        return None
    try:
        resp = chain.complete(
            [{"role": "user", "content": user_prompt}],
            system=system_prompt,
        )
        return resp.content or None
    except RuntimeError as exc:
        log.info("[LLM] chain exhausted: %s", exc)
        return None


# ── JSON helpers ──────────────────────────────────────────────────────────────

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def llm_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 800,
    temperature: float = 0.2,
    providers: list[str] | None = None,
) -> dict[str, Any]:
    """Same as llm_complete but parses the first JSON object in the output.

    Raises RuntimeError if every provider fails or no valid JSON can be salvaged.
    """
    text = llm_complete(system_prompt, user_prompt, max_tokens=max_tokens,
                        temperature=temperature, providers=providers)
    if not text:
        raise RuntimeError("LLM chain returned no text for JSON request")
    try:
        return _parse_llm_json(text)
    except ValueError as exc:
        log.info("[LLM] json parse failed (%s), retrying with strict prompt", exc)
        strict_system = (
            system_prompt.rstrip()
            + "\n\nReturn a single valid JSON object only. No prose, no markdown "
            "fences, no comments. All string values must have newlines escaped "
            "as \\n and any literal double quote escaped as \\\"."
        )
        retry_text = llm_complete(strict_system, user_prompt, max_tokens=max_tokens,
                                  temperature=min(temperature, 0.3), providers=providers)
        if not retry_text:
            raise RuntimeError(f"LLM JSON parse failed and retry returned nothing: {exc}") from exc
        try:
            return _parse_llm_json(retry_text)
        except ValueError as exc2:
            snippet = (retry_text or text)[:400].replace("\n", "\\n")
            raise RuntimeError(
                f"LLM JSON parse failed after retry: {exc2}. First 400 chars: {snippet!r}"
            ) from exc2


def _parse_llm_json(text: str) -> dict[str, Any]:
    candidates: list[str] = []
    stripped = text.strip()
    fence = _JSON_FENCE_RE.match(stripped)
    if fence:
        stripped = fence.group(1).strip()
    candidates.append(stripped)
    balanced = _extract_balanced_object(stripped)
    if balanced and balanced != stripped:
        candidates.append(balanced)
    last_error: Exception | None = None
    for candidate in candidates:
        for attempt in (candidate, _repair_json(candidate)):
            try:
                result = json.loads(attempt)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(result, dict):
                return result
            last_error = ValueError(f"JSON root was {type(result).__name__}, expected object")
    raise ValueError(f"Could not parse JSON from LLM output: {last_error}")


def _extract_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start: i + 1]
    return None


def _repair_json(text: str) -> str:
    repaired = (text.replace("“", '"').replace("”", '"')
                    .replace("‘", "'").replace("’", "'"))
    out: list[str] = []
    in_string, escape = False, False
    for ch in repaired:
        if in_string:
            if escape:
                out.append(ch); escape = False; continue
            if ch == "\\":
                out.append(ch); escape = True; continue
            if ch == '"':
                out.append(ch); in_string = False; continue
            if ch == "\n":
                out.append("\\n"); continue
            if ch == "\r":
                out.append("\\r"); continue
            if ch == "\t":
                out.append("\\t"); continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return _TRAILING_COMMA_RE.sub(r"\1", "".join(out))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if not any_key_present():
        print("No free-tier LLM keys set. Set GEMINI_API_KEY or GROQ_API_KEY.", file=sys.stderr)
        sys.exit(2)
    import sys as _sys
    sys_msg = "You are a terse assistant. Reply in one sentence."
    usr_msg = _sys.argv[1] if len(_sys.argv) > 1 else "Say hi in five words."
    out = llm_complete(sys_msg, usr_msg, max_tokens=80)
    print(out or "[all providers failed]")
