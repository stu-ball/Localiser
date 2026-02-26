# Localiser

Basic Python app that processes one MongoDB document at a time where `locale == en-AU`, uses LM Studio (OpenAI-compatible API) to translate **only user-facing text** to German, and updates the document locale to `de-DE`.

## Requirements
- Python 3.11+
- MongoDB
- LM Studio running with OpenAI-compatible server enabled (e.g. `http://localhost:1234/v1`)

## Environment variables
Required:
- `MONGODB_URI`
- `MONGODB_DB`
- `MONGODB_COLLECTION`
- `LMSTUDIO_BASE_URL` (e.g. `http://localhost:1234/v1`)
- `LMSTUDIO_MODEL`

Optional:
- `MONGODB_LOCALE_FIELD` (default `locale`)
- `SOURCE_LOCALE` (default `en-AU`)
- `TARGET_LOCALE` (default `de-DE`)
- `DRY_RUN` (default `false`)
- `MAX_DOCS` (default unlimited)
- `LOCK_FIELD` (default `_localiserLock`)
- `LOCK_LEASE_S` (default `300`)
- `PROCESSED_MARK_FIELD` (default `_localiserProcessedAt`)
- `ERROR_FIELD` (default `_localiserLastError`)

## Run
```bash
export MONGODB_URI='mongodb://localhost:27017'
export MONGODB_DB='mydb'
export MONGODB_COLLECTION='mycollection'
export LMSTUDIO_BASE_URL='http://localhost:1234/v1'
export LMSTUDIO_MODEL='local-model'

python -m localiser --dry-run
python -m localiser
```

## Notes
- The app uses an atomic claim-and-lock in Mongo so multiple workers can run safely.
- The app validates the LLM output and rejects any change that modifies structure or non-string values.
