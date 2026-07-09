# WAVE-033 Blue/Green Index Versioning

## Summary

Implement `SVS-035` by adding an operator-controlled external index version
suffix for Qdrant collections and OpenSearch indices. Existing deployments keep
their current physical names by default; setting `SVS_INDEX_VERSION=blue` or
`SVS_INDEX_VERSION=green` lets a cell build/search an alternate dense/sparse
index generation before traffic or environment cutover.

## Background

W32 proved idempotent reindexing. The next production durability step is making
that replay target an isolated physical generation so operators can build a new
index version without overwriting the currently serving external index. This is
especially important for embedding-profile changes, index schema changes, and
large corpus repair.

## Scope

- Add an optional active index version setting that defaults to existing
  collection/index names.
- Version Qdrant collection and OpenSearch index names when the setting is
  provided.
- Keep retrieval, ingestion, and reindex using the same active version through
  adapter naming helpers.
- Persist reindex target collection and stable point IDs back to embedding rows
  after replay.
- Document the env control in local and production env templates.
- Update `SVS-035` tracker status with proof.

## Code Anchors

- `packages/svs_common/svs_common/config.py`
- `packages/svs_common/svs_common/qdrant_adapter.py`
- `packages/svs_common/svs_common/opensearch_adapter.py`
- `packages/svs_common/svs_common/maintenance.py`
- `tests/test_reindex_idempotency.py`
- `.env.example`
- `.env.production.example`

## Out Of Scope

- Database migrations.
- Qdrant alias management APIs.
- OpenSearch alias rollover APIs.
- Multi-version fanout search.
- Operator cutover automation.

## Acceptance Criteria

- [x] Default Qdrant/OpenSearch names are unchanged when no index version is
  configured.
- [x] Versioned Qdrant/OpenSearch names are deterministic, lowercase, and safe
  for hyphen/space inputs.
- [x] Reindex writes to the active versioned collection and persists
  `embeddings.vector_collection` plus missing stable point IDs.
- [x] Focused tests cover default names, versioned names, and reindex metadata
  persistence.
- [x] Broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_index_versioning.py tests/test_reindex_idempotency.py tests/test_opensearch_adapter.py tests/test_qdrant_repair_all_script.py tests/test_qdrant_repair_proof_script.py
15 passed in 1.14s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
181 passed, 2 warnings in 3.70s

git diff --check
<exit 0>
```

## Notes

This ticket intentionally stops short of external alias APIs. It gives the
current reindex/ingest/search paths a deterministic blue/green generation target
without changing default deployments.
