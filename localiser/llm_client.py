from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class LlmSettings:
    base_url: str
    model: str
    api_key: str | None
    timeout_s: int
    temperature: float


class LlmError(RuntimeError):
    pass


def _strip_json_comments(s: str) -> str:
    # Remove // comments (model sometimes emits them).
    # This is a best-effort heuristic; we keep it conservative.
    s = re.sub(r"(?m)^\s*//.*$", "", s)
    s = re.sub(r"(?m)\s+//.*$", "", s)
    return s


def _extract_json_object(text: str) -> str:
    """Best-effort extraction of a JSON object from model output.

    LM Studio/models sometimes:
    - wrap JSON in ```json fences
    - prepend/append extra text
    - return multiple JSON objects back-to-back
    - include stray braces in strings (e.g. in templates)

    We try to extract the FIRST valid top-level JSON object.
    """

    s = text.strip()
    if s.startswith("```"):
        # remove leading fence line and trailing fence
        s = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s)
        s = s.strip()

    s = _strip_json_comments(s).strip()

    # Fast-path: already pure JSON object.
    if s.startswith("{"):
        try:
            json.loads(s)
            return s
        except Exception:
            pass

    # Robust extraction: find the first balanced JSON object using the JSON decoder.
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        brace = s.find("{", idx)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(s[brace:])
            if isinstance(obj, dict):
                return s[brace : brace + end]
        except Exception:
            idx = brace + 1
            continue
        idx = brace + 1

    # Last resort: greedy brace capture (may still fail at json.loads call site)
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        return m.group(0).strip()

    return s


def _headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def chat_completion_json(
    *,
    settings: LlmSettings,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call an OpenAI-compatible /chat/completions endpoint and return parsed JSON content."""

    url = settings.base_url.rstrip("/") + "/chat/completions"
    # Note: some LM Studio builds/models do not support `response_format`.
    # We enforce JSON-only via prompting and then `json.loads`.
    payload = {
        "model": settings.model,
        "temperature": settings.temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        with httpx.Client(timeout=settings.timeout_s, headers=_headers(settings.api_key)) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # pragma: no cover
        raise LlmError(f"LLM request failed: {e}") from e

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        raise LlmError(f"Unexpected LLM response shape: {e}") from e

    try:
        extracted = _extract_json_object(content)
        return json.loads(extracted)
    except Exception as e:
        raise LlmError(
            f"LLM did not return valid JSON: {e}. Raw content: {content[:500]}"
        ) from e
