# WAVE-133 independent offline foundation — implementation proof

Date: 2026-09-10. Base: `3230b74`.
Worktree: `/Users/mfrieson/Developer/exais-vector-store-law-money`.
Branch: `feat/statecivics-law-money-projection`.

The owner authorized independent ExAIS implementation with coder and quality
agents and confirmed that the StateCivics manager owns the KS tickets. This
increment does not complete WAVE-133 or advance WAVE-134 through WAVE-136.

## Implemented scope

- `schemas.py`: internal, strict immutable evidence/citation/entity and
  partition/manifest types. Structured CSV evidence requires no fake PDF,
  document or chunk. Canonical references are supplied opaque identities;
  source-span locators remain evidence, never provision IDs.
- `fiscal_graph.py`: pure scoped projection IDs, bounded hashing and streaming
  manifest validation. Checks counts, digests, partition order/completeness,
  identity conflicts, cross-partition endpoints, consistent source/extraction
  revision hashes and immutable retained partitions. Adding bill B requires the
  caller-designated retained partitions of A; the helper cannot authorize removal.
- `fiscal_graph_artifact.py`: exact retained CSV byte/record verification using
  the existing audit's canonical `headers`/`values` digest representation.
- `kansas-fiscal-graphrag.py`: separate offline `verify-structured-evidence`
  command. Outputs hashes, counts and locators with `evidence_only=true` and
  `publication_allowed=false`; the legacy artifact loader rejects that output.
- New focused tests in `test_fiscal_projection_contract.py` and
  `test_fiscal_structured_evidence.py`; operator instructions and ticket status.

The internal `exais.fiscal-projection.offline.v1` types are not a KS-650 producer
schema or an integrated fiscal v2 API. No public serving, database, embedding,
provider, deployment, upstream publication or harvest changes were made.

## Verification

Coder runs: **87 passed** for the projection/legacy graph tests; **68 passed**
for structured evidence/legacy adapter tests. These overlap with the combined
run below and are not additive counts. Both had zero skips.

Root combined regression command:

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-kanview-corpus:/corpus:ro \
  -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  -e SVS_FISCAL_CORPUS_ROOT=/corpus -e SVS_FISCAL_CUSTODY_ROOT=/custody \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 \
  python -m pytest -q -rs --tb=short -p no:cacheprovider \
  tests/test_fiscal_projection_contract.py tests/test_fiscal_structured_evidence.py \
  tests/test_fiscal_graph.py tests/test_fiscal_graph_artifact.py \
  tests/test_fiscal_graph_routes.py tests/test_fiscal_real_corpus.py \
  tests/test_openapi_contract.py tests/test_grant_cell_graph.py
```

Final result after the composition fix: **272 passed, 0 skipped, 3 existing
deprecation warnings, 9.89 seconds**.
The warnings concern FastAPI startup events and Starlette/AnyIO. Test image ID:
`sha256:181a0c365c2c056014c1366d772d69e815b36b8bbd486ee24bad1318b8d27f19`.
`git diff --check` passed. No dependencies were installed on the host.
An AST comparison against `3230b74` confirmed that all 200 pre-existing
function/class definitions in `fiscal_graph.py`, `fiscal_graph_artifact.py` and
`schemas.py` are unchanged. Both fiscal source/profile declarations still set
`enabled: false`.

New tests comprise 111 projection/parser/CLI mechanics cases and ten real-source
cases, including five direct verifier-to-locator composition cases. The real
cases verify all five selected
Education records: FY2025 data records 987, 2568 and 3742; FY2026 records 384
and 2671. Their raw source hashes, official harvest manifests, custody bytes and
record digests agree with the independently implemented retained-source audit.
Source-byte, wrong-locator and altered budget-reference padding negatives fail.
The existing eight real-corpus tests also ran without skips.

The initial combined run passed 256 tests, but independent review found that
the verifier's physical-line diagnostic was rejected by the strict locator
schema. The coder preserved that optional bounded field, added logical/physical
line consistency and unknown-value handling, and tested direct composition with
multiline CSV and all five retained records. The final command above includes
those added regressions. Review 1 is retained in `wave-133-offline-qc-1.md`.

Synthetic parser/manifest adversarial cases prove mechanics, not legal truth.
Real record matching proves exact evidence location, not a reviewed legal join.
The retained source still lacks a subunit; none is supplied or inferred.

## Bounds and remaining acceptance

CSV verification is bounded to 16 MiB, 100,000 source records, 1,000 requested
references, 256 columns and 65,536 characters per field. It retains the real
trailing empty column and distinguishes CSV records from physical lines.

Projection batches retain the 1,000-node/2,000-edge limits, with at most 256
partitions, 256,000 nodes, 512,000 edges, 4 MiB per batch and 128 MiB total
serialized batch content. These describe selected projections; they do not
claim that all 109,424 dimensions plus 410,814 observations fit or have been
covered. Exceeding a bound rejects the input rather than truncating it.

Upstream readiness was inspected read-only at planning `3650b8c5` and
operational `8ffabad9`: the KS-600 provision contract and KS-650 second record
kind were absent. The remaining handoff requires their actual schemas,
publication-subject compatibility and reviewed real records with canonical
revisions, directed relationships, native derivations, exact evidence,
publication/snapshot context and a correction/removal example.

Still pending: that adapter, typed legal/derivation semantics, actual source and
publication eligibility, extraction-parent provenance, API/persistence integration and disposable PostgreSQL
proof. No new persistence behavior was implemented, so this increment does not
claim a new PostgreSQL test result. WAVE-134 owns lifecycle/active-state guards;
WAVE-135/136 own retrieval and real-answer acceptance. WAVE-132 stays reopened
and the fiscal profile stays disabled.

Independent quality review returned **PASS WITH NOTES** after the composition
fix; see `wave-133-offline-qc-2.md`. Its separate new-test run passed 121 tests
with zero skips, and its original composition, cross-partition conflict and
nested-model bypass probes passed. This approval is limited to the offline
increment, with full-ticket dependencies unchanged.
