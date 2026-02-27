from __future__ import annotations

import json
from typing import Any

from bson import json_util

from .llm_client import LlmSettings, chat_completion_json

class TranslationError(RuntimeError):
    pass

def build_system_prompt(*, source_locale: str, target_locale: str, locale_field: str) -> str:
    return (
        "You are a careful localisation assistant. "
        "You will receive a MongoDB document as JSON. "
        f"The document's current locale is {source_locale}. "
        f"Translate ALL user-facing text into German appropriate for {target_locale}. "
        "User-facing text includes titles, labels, descriptions, button text, headings, and end-user messages. "
        "If a string is already German, keep it as-is. If a string is English, translate it. "
        "You MUST translate at least one user-facing string when any exist; do not return the document unchanged. "
        "Do NOT change any non-user-facing content such as identifiers, codes, URLs, emails, hashes, tokens, timestamps, or configuration. "
        "Do NOT change JSON keys or the structure (objects/arrays). "
        "Do NOT change numbers, booleans, nulls. "
        "Preserve placeholders exactly (e.g. {name}, ${amount}, {{var}}, %s, %d). "
        "Preserve markup: keep HTML/Markdown tags and translate only visible text. "
        f"Do not modify the locale field '{locale_field}' in the returned document; it will be set by the application. "
        "Return STRICT JSON (no markdown, no code fences, no comments, no trailing commas). "
        "Respond ONLY with a single valid JSON object. "
        "The JSON you return must be EXACTLY the same shape as the input document (same keys, same arrays). "
        "Do not wrap it in any outer object. Do not add any keys. "
        "Output MUST be only the JSON object and nothing else."
    )

def _json_default(o: Any):
    # Make common BSON-ish / datetime values serialisable for the prompt.
    # This is for prompt transport only; it does not modify MongoDB.
    try:
        import datetime
        if isinstance(o, (datetime.datetime, datetime.date)):
            return o.isoformat()
    except Exception:
        pass
    # Fallback
    return str(o)

def build_user_prompt(*, doc: dict[str, Any]) -> str:
    # Use MongoDB/BSON-aware JSON conversion so types like datetime/ObjectId are serialisable.
    # This is for prompt transport only; it does not alter the record.
    # Explicitly include the required top-level key set to reduce accidental key drops/additions.
    keys = sorted(list(doc.keys()))
    return (
        "Translate this document following the rules above.\n"
        "You MUST return a JSON object with EXACTLY these top-level keys (no more, no less):\n"
        + json.dumps(keys, ensure_ascii=False)
        + "\nDocument JSON:\n"
        + json_util.dumps(doc, ensure_ascii=False)
    )

def translate_document(
    *,
    doc: dict[str, Any],
    llm: LlmSettings,
    source_locale: str,
    target_locale: str,
    locale_field: str,
) -> dict[str, Any]:
    system_prompt = build_system_prompt(
        source_locale=source_locale, target_locale=target_locale, locale_field=locale_field
    )
    user_prompt = build_user_prompt(doc=doc)

    result = chat_completion_json(settings=llm, system_prompt=system_prompt, user_prompt=user_prompt)

    # We now require the model to return the translated document directly as a JSON object
    # (no wrapper keys like translated_document/changed_paths/notes).
    if not isinstance(result, dict):
        raise TranslationError("LLM response must be a single JSON object")

    return result
