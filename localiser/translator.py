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
        f"Translate ONLY user-facing text into German appropriate for {target_locale}. "
        "User-facing text includes titles, labels, descriptions, and messages intended for end users. "
        "Do NOT change any non-user-facing content such as identifiers, codes, URLs, emails, hashes, tokens, timestamps, or configuration. "
        "Do NOT change JSON keys or the structure (objects/arrays). "
        "Do NOT change numbers, booleans, nulls. "
        "Preserve placeholders exactly (e.g. {name}, ${amount}, {{var}}, %s, %d). "
        "Preserve markup: keep HTML/Markdown tags and translate only visible text. "
        f"Do not modify the locale field '{locale_field}' in the returned document; it will be set by the application. "
        "Return STRICT JSON (no markdown, no code fences, no comments, no trailing commas). "
        "Respond ONLY with a single valid JSON object matching this schema, with no extra wrapper keys, no explanations, and no extra text: "
        '{"translated_document": <object>, "changed_paths": <array of strings>, "notes": <string or null>}'
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
    return "Translate this document following the rules above. Document JSON:\n" + json_util.dumps(
        doc, ensure_ascii=False
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
    if not isinstance(result, dict) or "translated_document" not in result:
        raise TranslationError(
            "LLM response missing translated_document. "
            "(LM Studio may be applying a response wrapper; try a different model or tighten the prompt.)"
        )

    translated_document = result.get("translated_document")
    if not isinstance(translated_document, dict):
        raise TranslationError("translated_document must be an object")

    return translated_document
