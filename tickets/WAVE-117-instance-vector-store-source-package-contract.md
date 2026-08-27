# WAVE-117 Instance Vector-Store Source Package Contract

## Summary

Make every customer instance/vector store reproducible before the first VPS
rollout: each vector store that is loaded from scraped or externally collected
data must have an instance-owned source package that records the scraper,
source manifest, update policy, API ingestion path, graph build path, and proof
artifacts needed to recreate or incrementally update the store.

## Product Decision

The API remains the production ingestion/vectorization boundary. Instance source
packages do not write directly to Postgres, Qdrant, MinIO, or graph tables.
They describe and automate source collection, manifest diffing, API upload,
vector-store attachment, graph refresh, and quality proof.

Reusable scrapers should live in shared source-connector code or an upstream
collector repository. Each instance folder must still contain a portable source
package that pins the connector entrypoint, source revision, commands, manifest
schema, storage location, vector-store IDs, and last known proof. Customer-only
or one-off scrapers may be copied into that instance package.

## Background

The KS State Civics pilot now has a live Docker cell with persisted local
volumes and a populated Kansas Court Decisions vector store. That proves the
data plane can retain and serve vectorized content, but VPS rollout needs a
second guarantee: if the VPS is lost, rebuilt, or updated, the operator must be
able to reproduce and refresh each vector store from the original source
workflow instead of depending on opaque local volumes.

The Kansas court source currently comes from the external collector archive
root:

```text
C:\Users\mfrie\Ai_Projects\ksa-diff-collector-main\data\raw\kscourts-decisions
```

The source connector provides official-host validation, discovery/metadata
parsing, resumable downloads, CSV manifests, year directories, retries, rate
limits, and bounded workers. WAVE-117 turns that into an instance-level contract
that can be checked before moving the first customer cell to Hetzner.

## Proposed Instance Layout

```text
instances/{instance_slug}/
  instance.yaml
  vector-stores/
    {vector_store_slug}/
      store.yaml
      README.md
      sources/
        {source_slug}/
          source.yaml
          collect.py or collect.ps1
          manifest.schema.json
          ingest-plan.yaml
          source.lock.json
          eval-plan.yaml
```

Large raw corpora, PDFs, model outputs, and generated manifests should not be
committed by default. Store them in the cell object store, release proof
artifacts, or offsite backup target, and commit a `source.lock.json` pointer
with checksum, object URI, source revision, document count, byte count, and
timestamp. Small manifests may be committed only when size and privacy allow.

## Scope

- Add a versioned source-package schema for instance vector stores.
- Add a validator that checks every declared source package under
  `instances/{instance_slug}/vector-stores/*`.
- Add a KS State Civics source package for the `Kansas Court Decisions` vector
  store.
- Capture the collector entrypoint and update commands for the Kansas courts
  source without relying on a machine-local `C:\...` path as the only source of
  truth.
- Record the current live vector store ID
  `vs_a0d3ac76893e4f6f83bf2992`, tenant ID `ten_ks_state_civics`, business
  instance ID `biz_ks_state_civics`, and knowledge base ID
  `kb_ks_state_civics` in the instance store package.
- Define a manifest diff policy based on stable source identity and content
  checksums.
- Define the API-only update path for new/changed/deleted source records.
- Define graph refresh and eval proof steps for sources with GraphRAG enabled.
- Add a pre-VPS gate that fails if the instance has vector stores without
  source packages or unresolved local-only source paths.

## Out Of Scope

- Reingesting the full Kansas corpus in this ticket.
- Moving local Docker volumes to Hetzner.
- Publishing images to an external registry.
- Adding a public scraper API.
- Committing raw PDFs, extracted full text, or large generated manifests to git
  by default.
- Adding per-api-key vector-store grants.
- Making GraphRAG cover every document in the corpus; this ticket only makes
  the source/update path reproducible.

## Deliverables

- `contracts/vector-store-source-package.schema.json`
- `scripts/release/validate-instance-source-packages.py`
- Optional API-driven update runner, either:
  - `scripts/release/instance-source-update.py`, or
  - an extension of `scripts/release/kscourts-ingest.py` that consumes the new
    source package.
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/store.yaml`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/README.md`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/sources/kscourts-decisions/source.yaml`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/sources/kscourts-decisions/source.lock.json`
- KS Civics VPS runbook update requiring source-package validation before the
  first production launch or migrated-volume handoff.
- Focused tests for schema validation, local-path rejection, manifest lock
  parsing, and update-plan generation.

## Acceptance Criteria

- [x] Source-package schema validates a vector store's source connector,
  storage pointer, manifest pointer, vector-store identity, API ingestion mode,
  update policy, graph policy, and eval policy.
- [x] Validator discovers source packages from an instance slug and fails when a
  vector store package has no `source.yaml`.
- [x] Validator rejects unresolved Windows-only local paths as the sole source
  location for production packages.
- [x] Validator allows local paths only when explicitly marked as local proof or
  development input.
- [x] KS Civics package records the current Kansas Court Decisions vector store
  ID, tenant/business/knowledge-base IDs, source connector entrypoint, collector
  revision or portable source reference, current source manifest checksum or
  object URI, and update strategy.
- [x] Update plan computes added, changed, unchanged, and removed source records
  from two manifests using stable row identity and checksum fields.
- [x] Update runner sends new and changed records through the API file/vector
  store lifecycle; it does not write directly to DB/Qdrant/MinIO.
- [x] Update runner supports dry-run mode that prints counts and redacted
  commands without uploading data or mutating the vector store.
- [x] GraphRAG-enabled packages declare graph extract/load/eval commands and
  expected proof artifacts.
- [x] KS Civics VPS launch runbook treats source-package validation as a
  required gate before first VPS rollout or migrated-volume handoff.
- [x] Tests cover schema validation, path policy, manifest diffing, and dry-run
  update planning.

## Dependencies

- WAVE-111 Kansas court decisions ingestion.
- WAVE-112 Kansas court decisions GraphRAG readiness.
- WAVE-116 instance-scoped caller vector-store lifecycle.
- External Kansas court collector repository or a vendored portable collector
  snapshot for `kscourts-decisions`.
- Operator decision on whether the first VPS restores current local volumes or
  replays the source package into a fresh cell.

## Verification

Expected local/static checks:

```powershell
python scripts\release\validate-instance-source-packages.py `
  --instance ks-state-civics `
  --production

python -m pytest -q -rs tests/test_instance_source_packages.py
```

Expected dry-run update proof:

```powershell
python scripts\release\instance-source-update.py `
  --instance ks-state-civics `
  --vector-store kansas-court-decisions `
  --source kscourts-decisions `
  --dry-run
```

Expected VPS preflight gate:

```bash
python scripts/release/validate-instance-source-packages.py \
  --instance ks-state-civics \
  --production
```

The VPS gate must pass before `cell-up.py`, migrated-volume handoff, or
production corpus update is called complete.

## Notes

- The source package is an operations contract, not a data dump.
- Raw source artifacts belong in object storage or backup bundles, with commit
  pointers and checksums in the instance package.
- API ingestion should use scoped API keys created through the instance
  lifecycle from WAVE-116.
- Idempotency keys should derive from source identity plus content checksum so
  retries and updates are safe.
- Deletions should be explicit: default to soft-delete/expire semantics, and
  require a separate operator approval path before destructive source removal.
- The first implementation should prioritize KS Civics because it is the first
  planned Hetzner VPS cell.

## Implementation Proof

Completed on 2026-08-27.

Changed source:

- `contracts/vector-store-source-package.schema.json`
- `scripts/release/instance_source_packages.py`
- `scripts/release/validate-instance-source-packages.py`
- `scripts/release/instance-source-update.py`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/store.yaml`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/README.md`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/sources/kscourts-decisions/source.yaml`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/sources/kscourts-decisions/source.lock.json`
- `tests/test_instance_source_packages.py`
- `docs/TICKET_TRAIL.md`
- `runbooks/ks-state-civics-hetzner-vps-launch.md`

Verification:

- `python scripts\release\validate-instance-source-packages.py --instance ks-state-civics --production`
  -> `PASS instance=ks-state-civics packages=1 issues=0`.
- `python scripts\release\instance-source-update.py --instance ks-state-civics --vector-store kansas-court-decisions --source kscourts-decisions --dry-run --production`
  -> dry-run plan reported `api_only_update_path=true`,
  `direct_storage_writes=false`, `mutation_performed=false`, and
  `unchanged=16728`.
- `python -m py_compile scripts\release\instance_source_packages.py scripts\release\validate-instance-source-packages.py scripts\release\instance-source-update.py`
  passed on host Python.
- Host `python -m pytest -q -rs tests\test_instance_source_packages.py` could
  not run because host Python does not have `pytest` installed.
- Docker API-image focused tests passed:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_instance_source_packages.py`
  -> `6 passed`.
