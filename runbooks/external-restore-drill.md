# External Restore Drill Runbook

RM-015 is an operator proof gate. It proves that a real backup target can
restore into an external staging or customer cell. It must not be closed from
`scripts/release/local-restore-drill.py`; that script proves only local Docker
source and restore cells.

## Proof Boundary

Use this runbook when all of these are true:

- The backup source is a real offsite or external target, not a local marker
  bundle.
- The restore destination is an external staging/customer cell with its own
  topology, volumes, object store, indexes, and production-reference env file.
- The operator can preserve raw command output without printing secret values.

Do not close RM-015 from local evidence alone. Local restore output may be
attached as supporting context, but the acceptance proof is the external drill
record described below.

## Required Operator Inputs

Record these values in the proof packet before any restore command runs:

| Input | Required evidence |
|---|---|
| Backup target | Redacted bucket/container/repository URI, provider/account, region, retention or object-lock setting, and backup bundle id |
| External cell | Cell id, host identifier, cloud/VPS/dedicated topology, compose project name, and whether it is staging or customer-facing |
| Env file | Path to the generated production env file with secret references only |
| Restore scope | Tenant/business instance, vector store id or corpus id, one Qdrant collection, one OpenSearch index, and object prefix |
| Secret source | SOPS/age/Vault/envref locator names only; never decrypted values |
| Rollback target | Previous deployment/env reference and the command used to stop or replace the restored cell |

## Preflight

Validate the production env file without printing values:

```bash
python scripts/release/prod-env-preflight.py --env-file <external-cell-env>
```

Fetch or mount the backup bundle from the real target, then validate it before
restore:

```bash
bash scripts/restore-instance.sh --preflight-only <offsite-bundle.tar.gz> <restore-work-dir>
python scripts/release/backup_common.py validate <restore-work-dir>/<bundle>/manifest.json --require-external --print-artifacts
```

The `--require-external` check must pass. The manifest must include external or
offsite markers for every required artifact kind:

- `postgres_metadata`
- `qdrant_vectors`
- `opensearch_sparse`
- `object_store`
- `config_metadata`
- `audit_export`
- `checksum_metadata`

If any artifact is only a local marker such as `metadata_marker`,
`restore_drill_marker`, or `not_configured`, stop and mark the drill incomplete.

## Restore Procedure

Start or prepare the external restore cell from pinned images and the validated
env file. Place that file at the cell release path, then activate an
operator-approved published release manifest. Keep the raw command and `ps`
output:

```bash
mkdir -p .release/cells/<cell-id>
cp <external-cell-env> .release/cells/<cell-id>/.env.cell
python scripts/release/cell-up.py \
  --cell <cell-id> \
  --release-manifest <operator-approved-published-release-manifest>
```

Prove the restored cell is reachable through the supported access path:

```bash
python scripts/release/cell-access-proof.py --cell <cell-id>
```

Restore each layer and keep proof output:

| Layer | Required proof |
|---|---|
| Postgres metadata | `DATABASE_URL_SYNC=<restore-dsn-ref-or-runtime-env> bash scripts/restore-instance.sh <offsite-bundle.tar.gz> <restore-work-dir>` against the external restore database only |
| Object artifacts | Provider CLI or object-store restore command showing source target, destination bucket/prefix, object count, byte count, and checksum or version evidence |
| Qdrant collection | Snapshot restore command/API response for one collection plus before/after point counts for the restored vector store |
| OpenSearch index | Snapshot restore command/API response for one index plus before/after document count and health status |
| Config/secrets references | `prod-env-preflight.py` pass after restore, showing variable names only and no plaintext secret values |
| Audit/export artifacts | Immutable export object or restored audit artifact listing with checksum/version evidence |

The external cell may use provider-specific commands for object storage,
Qdrant, and OpenSearch. The proof packet must include the exact commands, the
redacted target identifiers, and the raw success output.

## Retrieval And Eval Smoke

After restore, prove application readiness and restored retrieval behavior:

```bash
python scripts/release/cell-access-proof.py --cell <cell-id>
python scripts/release/search-bench.py --cell <cell-id> --vector-store-id <restored-vector-store-id> --queries 20 --warmup-queries 10 --p95-ms 500 --pace-ms 800
python scripts/release/live-bakeoff.py --api-base <external-api-base> --api-token <redacted-token-source> --vector-store-id <restored-vector-store-id> --retrieval-profile-id hybrid_rrf_secure_v2
```

If the restored cell is not exposed through local compose metadata, replace
`--cell` commands with equivalent API/admin health checks and attach the raw
curl output. Do not paste bearer tokens or decrypted secrets.

## Completion Checklist

RM-015 can be marked externally proved only when the packet includes:

- External/offsite backup target identity and backup bundle id.
- External staging/customer cell identity and topology.
- Passing `prod-env-preflight.py` output for the restore env.
- Passing `backup_common.py validate ... --require-external --print-artifacts`.
- Postgres restore evidence against the external restore database.
- Object artifact restore evidence with counts and checksum/version metadata.
- One Qdrant collection restore with point-count proof.
- One OpenSearch index restore with document-count proof.
- Config/secrets reference proof with no disclosed values.
- Retrieval search or eval smoke proof against the restored environment.
- Rollback command and operator sign-off.

Until all items are present, record RM-015 as packaged but operator-dependent.
