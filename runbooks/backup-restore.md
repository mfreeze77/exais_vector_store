# Backup And Restore

RM-006 covers repo-buildable backup artifact manifests and nondestructive restore preflight. It does not prove an external/offsite backup target, live object-storage credentials, or a full external restore drill.

## Create A Bundle

```bash
bash scripts/backup-instance.sh instances/expert-ai-services/prod/instance.yaml backups
```

The command creates a timestamped bundle directory and tarball. Each bundle includes:

- `manifest.json`: schema-versioned backup artifact manifest.
- `CHECKSUMS.sha256`: checksum metadata for bundle files.
- `postgres/`: Postgres dump when `DATABASE_URL_SYNC` and `pg_dump` are available, otherwise a metadata marker.
- `qdrant/`: Qdrant snapshot response when `QDRANT_URL` is available, otherwise a metadata marker.
- `opensearch/`: OpenSearch index listing when `OPENSEARCH_URL` is available, otherwise a metadata marker.
- `object-store/`: local object-store file listing when `SVS_LOCAL_OBJECT_STORE_PATH` exists, otherwise a metadata marker.
- `config/`: instance/config metadata without expanding secret values.
- `audit/`: audit export when `SVS_AUDIT_EXPORT_PATH` points at a file, otherwise a metadata marker.

The manifest records `schema_version`, `generated_at`, `product_version`, `bundle_id`, and artifact entries with relative paths, sha256 checksums, sizes, required flags, sources, and notes.

## Validate A Bundle Without Restoring

```bash
bash scripts/restore-instance.sh --preflight-only backups/<bundle>.tar.gz restore-work
```

Preflight extracts the bundle, validates `manifest.json`, enumerates artifacts, checks artifact hashes/sizes, and verifies `CHECKSUMS.sha256` when present. It does not require `DATABASE_URL_SYNC` and does not run `pg_restore`.

The shared validator can also be run directly:

```bash
python scripts/release/backup_common.py validate restore-work/<bundle>/manifest.json --print-artifacts
```

## Restore Path

```bash
DATABASE_URL_SYNC=postgresql://... bash scripts/restore-instance.sh backups/<bundle>.tar.gz restore-work
```

Normal restore validates the bundle before restore work. If `postgres/svs.dump` is present, the script requires `DATABASE_URL_SYNC` and runs `pg_restore`. Qdrant and OpenSearch artifacts are enumerated and validated, but cluster-specific restore APIs remain manual until the external restore drill gate.

## External Proof Boundary

`validate_backup_manifest(..., require_external=True)` is reserved for the later external restore/offsite proof lane. RM-006 tests use `require_external=False`; marker artifacts are acceptable for local proof when live services or offsite credentials are not configured.
