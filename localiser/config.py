from __future__ import annotations

import os
from dataclasses import dataclass


def _getenv(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


def _getenv_int(name: str, default: int) -> int:
    val = _getenv(name)
    if val is None:
        return default
    return int(val)


def _getenv_bool(name: str, default: bool = False) -> bool:
    val = _getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    mongodb_db: str
    mongodb_collection: str
    mongodb_locale_field: str

    lmstudio_base_url: str
    lmstudio_model: str
    lmstudio_api_key: str | None
    lmstudio_timeout_s: int

    source_locale: str
    target_locale: str

    max_docs: int | None
    dry_run: bool

    llm_max_retries: int
    llm_temperature: float

    lock_field: str
    lock_lease_s: int

    processed_mark_field: str
    error_field: str


def load_settings() -> Settings:
    mongodb_uri = _getenv("MONGODB_URI")
    mongodb_db = _getenv("MONGODB_DB")
    mongodb_collection = _getenv("MONGODB_COLLECTION")
    lmstudio_base_url = _getenv("LMSTUDIO_BASE_URL")
    lmstudio_model = _getenv("LMSTUDIO_MODEL")

    missing = [
        name
        for name, val in [
            ("MONGODB_URI", mongodb_uri),
            ("MONGODB_DB", mongodb_db),
            ("MONGODB_COLLECTION", mongodb_collection),
            ("LMSTUDIO_BASE_URL", lmstudio_base_url),
            ("LMSTUDIO_MODEL", lmstudio_model),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    return Settings(
        mongodb_uri=mongodb_uri,  # type: ignore[arg-type]
        mongodb_db=mongodb_db,  # type: ignore[arg-type]
        mongodb_collection=mongodb_collection,  # type: ignore[arg-type]
        mongodb_locale_field=_getenv("MONGODB_LOCALE_FIELD", "locale") or "locale",
        lmstudio_base_url=lmstudio_base_url,  # type: ignore[arg-type]
        lmstudio_model=lmstudio_model,  # type: ignore[arg-type]
        lmstudio_api_key=_getenv("LMSTUDIO_API_KEY"),
        lmstudio_timeout_s=_getenv_int("LMSTUDIO_TIMEOUT_S", 120),
        source_locale=_getenv("SOURCE_LOCALE", "en-AU") or "en-AU",
        target_locale=_getenv("TARGET_LOCALE", "de-DE") or "de-DE",
        max_docs=(lambda v: int(v) if v is not None else None)(_getenv("MAX_DOCS")),
        dry_run=_getenv_bool("DRY_RUN", False),
        llm_max_retries=_getenv_int("LLM_MAX_RETRIES", 3),
        llm_temperature=float(_getenv("LLM_TEMPERATURE", "0.2") or "0.2"),
        lock_field=_getenv("LOCK_FIELD", "_localiserLock") or "_localiserLock",
        lock_lease_s=_getenv_int("LOCK_LEASE_S", 300),
        processed_mark_field=_getenv("PROCESSED_MARK_FIELD", "_localiserProcessedAt")
        or "_localiserProcessedAt",
        error_field=_getenv("ERROR_FIELD", "_localiserLastError") or "_localiserLastError",
    )
