# WAVE-126 — Cell-owned Grant graph ingestion/retrieval profile

Date: 2026-09-05. Starting revision: `11eebf7`.
Authorization: owner requested Grant-specific cell behavior, reusable per-cell
graph ingestion in ExAIS, an explicit work trail and commits.

## Implemented

- Dedicated Grant local-cell inventory (created during the preceding connection
  milestone); credentials/runtime files remain outside the repo and Dropbox.
- Trusted, bounded, strict deployment manifest with exact tenant, business,
  store, corpus and profile bindings; static reviewed handler allowlist, no
  arbitrary-code import or request-selected profile installation.
- Grant graph artifact validation using canonical projection generation, entity
  and relationship identities, source/relationship hashes, accepted/public
  declarations and evidence citation bindings.
- Explicit `grant_evidence` search lens; one-hop bounded expansion reusing
  existing graph tables, load API, ACL hydrator and citation response machinery.
- Current document-version and exact file-attribute binding; no filter widening
  across document, knowledge base, classification, ACL bucket, file tags or ACLs.
- Court/Topeka handlers and all `instances/ks-state-civics/**` files unchanged.
- Contract, operator activation sequence and truth boundaries documented in
  `docs/CELL_GRAPH_PROFILES.md`.

## Verification observed before source commit

- First focused offline regression: **188 passed**, including existing court,
  Topeka, query planner, response routing, retrieval and security tests.
- Final focused run plus actual PostgreSQL regression: **221 passed**, 2 existing
  FastAPI startup deprecation warnings, 2.32s. Includes **29** new opt-in real SQL
  cases. It loaded the actual migrations through `004_wave125_caller_identity`,
  used the existing graph loader and retrieval hydrator under NOSUPERUSER /
  NOBYPASSRLS `svs_app`, and verified citations, stale generations/hashes/versions,
  deleted/cancelled records, private/group/role restrictions, cell/store isolation
  and comparison/range/alternative/exclusion filters.
- PostgreSQL ran in throwaway container `svs-grant-graph-test-20260905` with
  network isolation, no published port and tmpfs data. Test fixture writes rolled
  back. No production source data, ExAIS cell volume, publisher API or provider
  was involved in this graph test.
- Ruff check and format check passed for all four new Python files. Whitespace
  diff check passed. Existing large modules were patched without bulk reformat.
- Runtime API/worker/model-gateway images remain pinned to the previously
  qualified `11eebf7` build. New profile checked in **disabled**. No graph load,
  profile activation, credential widening or StateCivics restart occurred.

Reproduction: use the pinned API dependency image
`exais-grant-intelligence/exai-vector-store-api@sha256:682d385a7225569b2808e581372bdbad6010fad1d4977cea99e5e12591323709`,
mount this checkout's packages/apps/tests/instances and `pyproject.toml`, and run:

```text
pytest -q -p no:cacheprovider tests/test_grant_graph_postgres.py \
  tests/test_grant_cell_graph.py tests/test_openai_responses_routes.py \
  tests/test_query_planner.py tests/test_retrieval_profile_resolution.py \
  tests/test_kscourts_graphrag_load.py tests/test_topeka_graphrag.py \
  tests/test_security.py
```

Set `SVS_GRANT_GRAPH_TEST_DATABASE_URL` only to the disposable migrated test
database; without it the SQL tests skip. No normal `DATABASE_URL` fallback.

### Committed baseline and evidence-ACL hardening

- Baseline committed as `3e55104`. A clean detached clone then passed the entire
  non-integration suite: **924 passed, 29 skipped**, 3 dependency deprecation
  warnings, 6.95s. The clone stayed clean; `tests/integration` was explicitly
  excluded and the dedicated SQL URL was unset. This does not claim unrun gates.
- Final review identified a third-document evidence boundary: valid public
  endpoints alone do not authorize publishing a supporting citation ID after
  its source becomes private, stale, deleted or unavailable. Candidate SQL now
  requires every evidence citation to resolve to current, public, exactly bound
  same-cell/generation source chunks with the principal's group/role access.
- The real SQL fixture now uses a distinct third evidence document. Eight
  negative cases cover evidence groups/roles, private document/chunk, cancelled
  file, stale source hash/version and missing citation. Two positive cases prove
  actual group/role members retain access.
- Updated focused result: **231 passed**, including **39 real PostgreSQL cases**,
  2 existing warnings, 2.94s. New throwaway database:
  `svs-grant-evidence-test-20260905`, again tmpfs/network-isolated/no host port.
  All writes roll back; no operating database or provider calls are involved.
- The original `svs-grant-graph-test-20260905` container was stopped and removed
  after its tests; only synthetic tmpfs fixture data was discarded.

### Final clean-checkout qualification

- Hardening committed as `2da4954`. A clean detached clone of that revision ran
  the complete non-integration suite **with** the dedicated PostgreSQL URL:
  **963 passed, 0 skipped**, 3 existing dependency deprecation warnings, 8.53s.
  This includes all 39 real graph SQL/RLS cases. `tests/integration` remains
  explicitly excluded; no provider or running-cell integration is inferred.
- Command: the pinned dependency image above, clone mounted at `/app`,
  `PYTHONDONTWRITEBYTECODE=1`, dedicated test URL, then
  `pytest -q -p no:cacheprovider --ignore=tests/integration`.
  The clone at `/tmp/exais-grant-profile-qualification.SOYtcv/repo` stayed clean.
- `svs-grant-evidence-test-20260905` was stopped and removed after completion;
  only throwaway synthetic tmpfs data was discarded. StateCivics has no changed
  files relative to `11eebf7`; Grant runtime image and credentials are unchanged.

## Still open — do not relabel this as a complete grant graph

- Canonical Grant DB target selection remains outside this ExAIS change.
- Build deterministic Grant exporter from accepted, publication-allowed,
  version-bound relationships with verified review/source evidence; explicitly
  report unsupported/unprojected nodes and missing citations.
- Source package/reviewed real corpus and evaluated grant questions remain
  pending. Structural `accepted` metadata is not independent approval proof.
- Build/pin/restart only the Grant API, explicitly mount profile and update
  matching store metadata, then execute a scoped synthetic end-to-end graph
  acceptance and clean it up. That is separate from this SQL/RLS regression.
- Integrate explicit graph lens selection and graph provenance presentation in
  the Grant caller; ordinary semantic search remains unchanged.
- A future multi-profile catalog can extend the trusted resolver when a cell
  needs several new handlers. Do not migrate existing civics behavior implicitly.
