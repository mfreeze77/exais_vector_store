# WAVE-100 Retrieval Capability Tracker Proof

## Goal

Reconcile the retrieval tracker with the current implementation evidence for
dense search, sparse search, post-retrieval ACL verification, and
neighbor/parent context expansion.

## Background

`docs/TICKET_TRAIL.md` still listed several EPIC-006 retrieval items as
`scaffolded` or `ready-to-build`, even though later wave tickets implemented and
verified those capabilities:

- Qdrant dense indexing/search: strict adapter behavior, health checks,
  versioned collections, stale-vector cleanup, and repair proof.
- OpenSearch/Postgres sparse retrieval: strict adapter behavior, phrase-aware
  sparse search, safe file-attribute filters, and Postgres FTS fallback.
- Post-retrieval ACL: authoritative hydration followed by
  group/role/security-level post-filtering.
- Neighbor/parent expansion: W23/W24 profile-driven context-pack expansion with
  relation metadata and result-count isolation.

## Scope

- Add focused characterization proof for `_hydrate_and_acl` post-ACL filtering
  of security levels, groups, and roles.
- Update `docs/TICKET_TRAIL.md` EPIC-006 statuses for SVS-050, SVS-051,
  SVS-053, and SVS-055 to match proved current behavior.
- Register this proof ticket in `tickets/README.md`.

## Out of scope

- Changing dense/sparse indexing semantics.
- Changing retrieval ranking, reranking, MMR, context expansion behavior,
  citations, API-key behavior, tenant/RLS policy, database migrations, provider
  routing, deployment, or admin UI behavior.
- Claiming provider-backed reranker or live external backend readiness beyond
  existing proof artifacts.

## Acceptance criteria

- [x] Focused regression proves hydration/post-ACL filters out backend-returned
  candidates that exceed the principal security level or lack required
  group/role membership.
- [x] SVS-050 and SVS-051 tracker entries reflect implemented dense/sparse
  backend behavior without overstating live-provider proof.
- [x] SVS-053 tracker entry reflects implemented post-retrieval ACL verification
  and focused proof.
- [x] SVS-055 tracker entry reflects completed neighbor/parent context expansion
  and its native-only scope.
- [x] Focused, compile, broad non-integration, and whitespace verification pass.

## Changed files

- `tests/test_retrieval_profile_resolution.py`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-100-retrieval-capability-tracker-proof.md`

## Verification

Focused post-ACL retrieval proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py
52 passed in 1.30s
```

Expanded retrieval/OpenSearch/OpenAI proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_opensearch_adapter.py tests/test_openai_compat_search.py
134 passed in 1.99s
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
412 passed, 2 warnings in 5.99s
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.

## QC

Decision: PASS

Ticket reviewed:
- `tickets/WAVE-100-retrieval-capability-tracker-proof.md`

Evidence reviewed:
- `tests/test_retrieval_profile_resolution.py`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- Focused post-ACL retrieval proof: `52 passed in 1.30s`
- Expanded retrieval/OpenSearch/OpenAI proof: `134 passed in 1.99s`
- Compile proof: passed
- Broad non-integration proof: `412 passed, 2 warnings in 5.99s`
- Whitespace proof: `git diff --check` passed

Acceptance criteria:
- [pass] Focused regression proves hydration/post-ACL filters out candidates
  that exceed the principal security level or lack required group/role
  membership.
- [pass] SVS-050 and SVS-051 tracker entries reflect implemented dense/sparse
  backend behavior without overstating live-provider proof.
- [pass] SVS-053 tracker entry reflects implemented post-retrieval ACL
  verification and focused proof.
- [pass] SVS-055 tracker entry reflects completed neighbor/parent context
  expansion and its native-only scope.
- [pass] Focused, compile, broad non-integration, and whitespace verification
  passed.

Findings:
- None.

Required fixes before next ticket:
- None.
