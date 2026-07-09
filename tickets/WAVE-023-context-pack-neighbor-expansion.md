# WAVE-023 Context Pack Neighbor Expansion

## Summary

Implement profile-driven neighbor expansion for native retrieval context packs so
RAG callers receive surrounding chunk context without changing OpenAI-compatible
vector-store search result counts.

Repo references checked on 2026-07-08:

- `docs/TICKET_TRAIL.md`: SVS-055 Neighbor/parent expansion is ready-to-build.
- `configs/retrieval-profiles.yaml`: default retrieval profiles already declare
  `expand_neighbors` and `neighbor_window`.
- `docs/planning-specs/FULL_REPO_SPEC.md`: retrieval profiles include neighbor
  expansion as part of context construction.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W23-001 | Complete | Implementation/Test | Expand neighboring chunks in context packs under profile control. |

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_retrieval_profile_resolution.py`
- `configs/retrieval-profiles.yaml`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## W23-001 Acceptance Criteria

- [x] `RetrievalService.context_pack` expands same-document neighboring chunks
  only when the effective retrieval profile enables `expand_neighbors` with a
  positive `neighbor_window` or structured `before`/`after` window.
- [x] Neighbor expansion applies only to native context packs and does not change
  `/v1/vector_stores/{id}/search` or Responses file-search result counts.
- [x] Expansion preserves tenant/business/security filtering, vector-store or
  knowledge-base filters, safe file-attribute filters, and post-ACL checks.
- [x] Expanded chunks are de-duplicated and ordered around each direct hit so
  preceding neighbors, the direct hit, and following neighbors form readable
  context.
- [x] Context-pack citations and returned chunks correspond to the actual
  context included after `max_context_tokens` trimming.
- [x] Expanded neighbor citations keep OpenAI-core annotations while richer
  citation metadata identifies the relation to the direct hit.
- [x] Focused tests prove enabled expansion, disabled/no-window preservation,
  ACL/filter SQL construction, citation relation metadata, and result-count
  isolation from vector-store search.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py
18 passed in 1.11s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_openai_compat_search.py
43 passed in 1.18s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
134 passed, 2 warnings in 3.87s

git diff --check
<exit 0>
```

## Notes

This ticket does not implement parent-section expansion, OpenAI search-result
expansion, database migrations, API-key behavior, provider routing, or admin UI
changes.
