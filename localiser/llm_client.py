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

    LM Studio/models sometimes wrap JSON in ```json fences or add comments.
    """

    s = text.strip()
    if s.startswith("```"):
        # remove leading fence line and trailing fence
        s = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s)
        s = s.strip()

    # If still not pure JSON, attempt to grab first {...} block.
    if not s.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            s = m.group(0)

    s = _strip_json_comments(s).strip()
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
