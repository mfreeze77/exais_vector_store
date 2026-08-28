# WAVE-119 Topeka Workbench Canonical Projection

## Summary

Add an artifact-only projection layer that converts saved Topeka Municipal Code
scrape outputs into stable workbench-ready legal components. The goal is to let
the same saved scrape archive support ExAIS semantic/GraphRAG search now and a
future StateCivics legislative drafting workbench later, without treating
embeddings or freeform extracted text as canonical legal truth.

## Product Decision

Saved source captures are the preservation layer. `sections.jsonl`,
`definitions.jsonl`, `nodes.jsonl`, and `edges.jsonl` are parser/search
projections. A separate workbench projection must expose stable component IDs,
parent-child structure, ordinals, citations, source URLs, content hashes, and
source HTML hashes so future amendment and redline tools can target exact legal
components.

The projection is not ingestion. It must not call ExAIS ingestion, embedding
providers, Qdrant, Postgres, MinIO, OpenSearch, or a graph write path.

## Background

The StateCivics legislative workbench repository models drafting around
canonical structured documents, stable components, component projections,
subtree hashes, and amendment operations with precondition hashes. Topeka source
artifacts already preserve section-level citations, source URLs, blocks,
definitions, ordinance history, `content_hash`, `source_html_hash`, and
GraphRAG `CONTAINS` hierarchy. The missing bridge is a deterministic projection
that maps those artifacts into the workbench's component-shaped world.

## Scope

- Add a Topeka-specific workbench projection script.
- Read existing saved Topeka artifact files only:
  - `sections.jsonl`
  - `definitions.jsonl`
  - `nodes.jsonl`
  - `edges.jsonl`
  - `url-manifest.jsonl`
  - optional `crawl_report.json`
  - optional `quality-report.json`
- Emit a `workbench/` artifact set:
  - `canonical-document.json`
  - `components.jsonl`
  - `component-projection.jsonl`
  - `component-relations.jsonl`
  - `slices.jsonl`
  - `workbench-import-manifest.json`
- Preserve stable source component keys and deterministic UUIDv5 workbench
  component IDs.
- Preserve section ancestry from the URL manifest/`CONTAINS` graph.
- Convert section blocks into paragraph/table components under the section.
- Convert definitions into definition components under the section.
- Emit title/chapter slices so the workbench can import focused portions of the
  municipal code.
- Wire the projection into the Topeka codified-code source package as a
  generated artifact step.
- Add focused tests for deterministic IDs, hierarchy preservation, slice
  filtering, output files, and projection quality.

## Out Of Scope

- Full StateCivics workbench integration.
- Editing, applying, previewing, or validating amendments.
- Changing vector-store ingestion, retrieval, API key behavior, tenant
  isolation, or GraphRAG load semantics.
- Re-scraping Topeka pages.
- Vectorizing or ingesting Topeka records.
- Adding Cloudflare bypass/evasion, stealth browser logic, CAPTCHA solving,
  cookies, credential capture, or proxy routing.

## Deliverables

- `scripts/release/topeka-code-workbench-project.py`
- `tests/test_topeka_workbench_projection.py`
- Topeka codified-code `source.yaml` projection command/output contract.
- `docs/TOPEKA_MUNICIPAL_CODE_SEEDING_SPEC.md` update documenting the saved
  scrape to workbench projection lane.
- This ticket with implementation proof.

## Acceptance Criteria

- [x] The projection script creates all six `workbench/` artifact files from an
  existing Topeka source output folder.
- [x] Component IDs are deterministic across repeated runs against the same
  source artifact set.
- [x] Fetched sections keep their title/chapter ancestry and do not import
  unfetched manifest-only sections as editable section bodies.
- [x] Section blocks become child paragraph/table components with stable source
  component keys, citations, ordinals, `content_hash`, `source_url`, and
  `source_html_hash`.
- [x] Definitions become child definition components with stable source
  component keys and `DEFINES` relations.
- [x] `component-relations.jsonl` preserves `CONTAINS`, `REFERENCES`, `DEFINES`,
  and `HAS_ORDINANCE_HISTORY` relations when source data supports them.
- [x] `slices.jsonl` contains title/chapter slices that point to section
  component IDs and source URLs.
- [x] The projection manifest states the artifact-only boundary and reports
  quality status without enabling ingestion/vectorization.
- [x] Tests cover the projection behavior and existing source-package validation
  still passes.

## Verification

```powershell
docker run --rm -v "${PWD}:/work" -w /work `
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent `
  localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate `
  python -m pytest -q tests/test_topeka_workbench_projection.py tests/test_instance_source_packages.py tests/test_topeka_artifact_quality.py

docker run --rm -v "${PWD}:/work" -w /work `
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent `
  localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate `
  python scripts/release/topeka-code-workbench-project.py `
    --source-output .tmp/topeka-decodo-window-batches-20260827220454/output/batch-001 `
    --output-dir .tmp/topeka-decodo-window-batches-20260827220454/output/batch-001/workbench
```

## Implementation Proof

Completed on 2026-08-28.

Changed source:

- `scripts/release/topeka-code-workbench-project.py`
- `tests/test_topeka_workbench_projection.py`
- `contracts/vector-store-source-package.schema.json`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/source.yaml`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/source.lock.json`
- `docs/TOPEKA_MUNICIPAL_CODE_SEEDING_SPEC.md`
- `tickets/README.md`
- `tickets/WAVE-118-topeka-municipal-code-source-seeding.md`
- `tickets/WAVE-119-topeka-workbench-canonical-projection.md`

Verification:

- `python -m json.tool contracts/vector-store-source-package.schema.json`
  passed.
- Docker API-image focused tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q tests/test_topeka_workbench_projection.py tests/test_instance_source_packages.py tests/test_topeka_artifact_quality.py`
  -> `16 passed`.
- Source-package validation:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/validate-instance-source-packages.py --instance ks-state-civics --production`
  -> `PASS instance=ks-state-civics packages=3 issues=0`.
- Real saved batch projection, batch 001:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/topeka-code-workbench-project.py --source-output .tmp/topeka-decodo-window-batches-20260827220454/output/batch-001 --output-dir .tmp/topeka-decodo-window-batches-20260827220454/output/batch-001/workbench`
  -> projection quality passed, 200 source sections, 1,489 components, 1,828 relations, 19 slices, zero projection errors.
- Real saved batch projection, batch 002:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/topeka-code-workbench-project.py --source-output .tmp/topeka-decodo-window-batches-20260827220454/output/batch-002 --output-dir .tmp/topeka-decodo-window-batches-20260827220454/output/batch-002/workbench`
  -> projection quality passed, 200 source sections, 888 components, 1,235 relations, 23 slices, zero projection errors.
- Real saved batch projection, batch 003:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/topeka-code-workbench-project.py --source-output .tmp/topeka-decodo-window-batches-20260827220454/output/batch-003 --output-dir .tmp/topeka-decodo-window-batches-20260827220454/output/batch-003/workbench`
  -> projection quality passed, 200 source sections, 1,265 components, 1,499 relations, 22 slices, zero projection errors.

Known limitations:

- This is a projection and import contract only. It does not implement the
  StateCivics drafting workbench import API or editor UI.
- Batch-level projection success is not full-corpus production approval. The
  full Topeka corpus still needs acquisition, artifact quality, workbench
  projection, ingestion, graph, and recall gates before production use.
