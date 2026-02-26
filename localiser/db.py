from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection


@dataclass(frozen=True)
class Claim:
    owner: str
    doc: dict[str, Any]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_collection(mongodb_uri: str, db_name: str, collection_name: str) -> Collection:
    # Fail fast if DNS/host is not resolvable (common when using K8s service names locally).
    client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5_000)
    return client[db_name][collection_name]


def claim_one(
    collection: Collection,
    *,
    locale_field: str,
    source_locale: str,
    lock_field: str,
    lock_lease_s: int,
    error_field: str = "_localiserLastError",
) -> Claim | None:
    now = utcnow()
    expires_at = now + timedelta(seconds=lock_lease_s)
    owner = str(uuid4())

    lock_available_filter = {
        "$or": [
            {lock_field: {"$exists": False}},
            {f"{lock_field}.expiresAt": {"$lt": now}},
        ]
    }

    # Avoid immediately re-claiming documents that have already failed.
    # Note: error field name comes from settings at write-time, but we also hard-filter
    # the default field to prevent hot loops if user overrides.
    not_errored_filter = {
        "$or": [
            {error_field: {"$exists": False}},
            {error_field: None},
        ]
    }

    res = collection.find_one_and_update(
        filter={locale_field: source_locale, **lock_available_filter, **not_errored_filter},
        update={
            "$set": {
                lock_field: {
                    "owner": owner,
                    "lockedAt": now,
                    "expiresAt": expires_at,
                }
            }
        },
        sort=[("_id", 1)],
        return_document=ReturnDocument.AFTER,
    )

    if res is None:
        return None

    return Claim(owner=owner, doc=res)


def unlock_with_error(
    collection: Collection,
    *,
    _id: Any,
    lock_field: str,
    owner: str,
    error_field: str,
    error_message: str,
) -> None:
    collection.update_one(
        filter={"_id": _id, f"{lock_field}.owner": owner},
        update={
            "$set": {error_field: {"message": error_message, "at": utcnow()}},
            "$unset": {lock_field: ""},
        },
    )


def apply_patch_and_finish(
    collection: Collection,
    *,
    _id: Any,
    lock_field: str,
    owner: str,
    locale_field: str,
    target_locale: str,
    processed_mark_field: str,
    set_ops: dict[str, Any],
    unset_lock: bool = True,
) -> int:
    update_doc: dict[str, Any] = {"$set": {**set_ops, locale_field: target_locale, processed_mark_field: utcnow()}}
    if unset_lock:
        update_doc["$unset"] = {lock_field: ""}

    res = collection.update_one(
        filter={"_id": _id, f"{lock_field}.owner": owner},
        update=update_doc,
    )
    return int(res.modified_count)
