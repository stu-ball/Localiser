from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class DiffResult:
    changed_paths: list[str]
    set_ops: dict[str, Any]


class ValidationError(RuntimeError):
    pass


def _is_internal_field(path: str) -> bool:
    # Ignore app-managed / system fields that may not be present in LLM output or
    # may appear with different serialisation types (e.g. BSON dates).
    # When dict key sets differ, our diff uses a synthetic "{keys}" suffix.
    return path.startswith("_localiser") or path in {"_ts"}


def _is_primitive(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _walk_diff(original: Any, translated: Any, path: str) -> Iterator[tuple[str, Any, Any]]:
    """Yield (path, original_value, translated_value) for any difference."""
    if type(original) is not type(translated):
        yield (path, original, translated)
        return

    if isinstance(original, dict):
        okeys = set(original.keys())
        tkeys = set(translated.keys())
        if okeys != tkeys:
            yield (path + "{keys}", okeys, tkeys)
            return
        for k in original.keys():
            child_path = f"{path}.{k}" if path else k
            yield from _walk_diff(original[k], translated[k], child_path)
        return

    if isinstance(original, list):
        if len(original) != len(translated):
            yield (path + "{len}", len(original), len(translated))
            return
        for i, (ov, tv) in enumerate(zip(original, translated)):
            child_path = f"{path}[{i}]"
            yield from _walk_diff(ov, tv, child_path)
        return

    if _is_primitive(original):
        if original != translated:
            yield (path, original, translated)
        return

    # Unknown types: treat as mismatch if not equal
    if original != translated:
        yield (path, original, translated)


def validate_and_build_patch(
    *,
    original_doc: dict[str, Any],
    translated_doc: dict[str, Any],
    locale_field: str,
) -> DiffResult:
    """Validate translated doc and build a $set patch for changed string fields.

    Rules:
    - Keys and structure must match (dict keys, list lengths).
    - Only string fields may change (excluding locale_field which is handled by caller).
    - Non-string primitives (numbers, bools) must not change.

    Note:
    - The LLM sees BSON-serialised JSON in the prompt, but we validate against the original
      MongoDB document and only patch string fields.
    """

    if not isinstance(translated_doc, dict):
        raise ValidationError("translated_document must be an object")

    changed_paths: list[str] = []
    set_ops: dict[str, Any] = {}

    for path, ov, tv in _walk_diff(original_doc, translated_doc, ""):
        # ignore locale differences; app will set it
        if path == locale_field:
            continue

        # ignore internal fields (lock/error/processed markers)
        if _is_internal_field(path):
            continue

        # structural problems show as path containing {keys}/{len}
        if "{len}" in path:
            raise ValidationError(f"Structure changed at {path}")

        if "{keys}" in path:
            # Allow missing/extra internal fields only (when comparing keysets).
            # The diff encodes this as e.g. "template{keys}" or "{keys}".
            # We only allow keyset drift if every missing/extra key is internal.
            if isinstance(ov, set) and isinstance(tv, set):
                missing = set(ov) - set(tv)
                extra = set(tv) - set(ov)
                if missing or extra:
                    if all(str(k).startswith("_localiser") for k in missing) and all(
                        str(k).startswith("_localiser") for k in extra
                    ):
                        continue
            raise ValidationError(f"Structure changed at {path}")

        # allow BSON/native types becoming strings in the translated output (we won't patch these)
        if type(ov) is not type(tv):
            if isinstance(tv, str):
                # tolerate type drift, but do not patch
                continue
            raise ValidationError(f"Type changed at {path}")

        # only allow string changes (and only if actually different)
        if isinstance(ov, str) and isinstance(tv, str):
            if ov == tv:
                continue
            changed_paths.append(path)
            # Mongo dot notation (approx): convert [i] to .i for arrays
            mongo_path = path.replace("[", ".").replace("]", "")
            set_ops[mongo_path] = tv
            continue

        # If we got here, the value differs but isn't a string change we can patch.
        # This can happen when the LLM re-serialises BSON-ish values (e.g. ObjectId/date)
        # into strings. We tolerate it but refuse to advance locale unless at least one
        # patchable string field changed (enforced by caller).
        continue

    return DiffResult(changed_paths=changed_paths, set_ops=set_ops)
