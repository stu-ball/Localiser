from __future__ import annotations

import argparse
import json
import sys
import time

from .config import load_settings
from .db import apply_patch_and_finish, claim_one, get_collection, unlock_with_error
from .llm_client import LlmSettings
from .translator import translate_document
from .validate import ValidationError, validate_and_build_patch


def _log(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localiser")
    parser.add_argument("--max-docs", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-on-error",
        action="store_true",
        help="On per-document error, mark error and set locale to target to avoid infinite retries.",
    )
    args = parser.parse_args(argv)

    s = load_settings()
    max_docs = args.max_docs if args.max_docs is not None else s.max_docs
    dry_run = args.dry_run or s.dry_run
    skip_on_error = args.skip_on_error

    llm = LlmSettings(
        base_url=s.lmstudio_base_url,
        model=s.lmstudio_model,
        api_key=s.lmstudio_api_key,
        timeout_s=s.lmstudio_timeout_s,
        temperature=s.llm_temperature,
    )

    col = get_collection(s.mongodb_uri, s.mongodb_db, s.mongodb_collection)

    processed = 0
    while True:
        if max_docs is not None and processed >= max_docs:
            _log({"event": "done", "reason": "max_docs_reached", "processed": processed})
            break

        _log({"event": "claim_attempt", "processed": processed})
        claim = claim_one(
            col,
            locale_field=s.mongodb_locale_field,
            source_locale=s.source_locale,
            lock_field=s.lock_field,
            lock_lease_s=s.lock_lease_s,
            error_field=s.error_field,
        )
        if claim is None:
            _log({"event": "done", "reason": "no_more_source_locale_docs"})
            break

        doc = claim.doc
        _id = doc.get("_id")

        _log({"event": "claimed", "_id": str(_id)})

        try:
            _log({"event": "llm_translate_start", "_id": str(_id)})
            translated = translate_document(
                doc=doc,
                llm=llm,
                source_locale=s.source_locale,
                target_locale=s.target_locale,
                locale_field=s.mongodb_locale_field,
            )
            _log({"event": "llm_translate_done", "_id": str(_id)})
            diff = validate_and_build_patch(
                original_doc=doc,
                translated_doc=translated,
                locale_field=s.mongodb_locale_field,
            )

            _log(
                {
                    "_id": str(_id),
                    "changed_paths": diff.changed_paths,
                    "changed_count": len(diff.changed_paths),
                    "dry_run": dry_run,
                }
            )

            if not dry_run:
                modified = apply_patch_and_finish(
                    col,
                    _id=_id,
                    lock_field=s.lock_field,
                    owner=claim.owner,
                    locale_field=s.mongodb_locale_field,
                    target_locale=s.target_locale,
                    processed_mark_field=s.processed_mark_field,
                    set_ops=diff.set_ops,
                )
                if modified != 1:
                    raise RuntimeError("Update failed (lock lost or document changed)")

            processed += 1

        except (ValidationError, Exception) as e:
            _log({"event": "error", "_id": str(_id), "message": str(e)})

            # Prevent hot-looping the same problematic documents.
            if skip_on_error and not dry_run:
                apply_patch_and_finish(
                    col,
                    _id=_id,
                    lock_field=s.lock_field,
                    owner=claim.owner,
                    locale_field=s.mongodb_locale_field,
                    target_locale=s.target_locale,
                    processed_mark_field=s.processed_mark_field,
                    set_ops={s.error_field: {"message": str(e)}},
                )
            else:
                unlock_with_error(
                    col,
                    _id=_id,
                    lock_field=s.lock_field,
                    owner=claim.owner,
                    error_field=s.error_field,
                    error_message=str(e),
                )

            # avoid hot loop on repeatedly failing docs
            time.sleep(0.2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
