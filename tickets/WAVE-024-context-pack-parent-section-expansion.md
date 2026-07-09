# WAVE-024 Context Pack Parent Section Expansion

## Summary

Implement profile-driven parent-section expansion for native retrieval context
packs so PDF/Markdown RAG callers can receive same-section context from the
heading hierarchy without changing OpenAI-compatible vector-store search result
counts.

Repo references checked on 2026-07-08:

- `docs/TICKET_TRAIL.md`: SVS-055 Neighbor/parent expansion is ready-to-build.
- `configs/retrieval-profiles.yaml`: `hybrid_contextual_pdf_v1` already declares
  `expand_parent_sections: true`.
- `docs/planning-specs/FULL_REPO_SPEC.md`: retrieval flow calls for neighbor and
  parent expansion after reranking and before citation/context construction.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W24-001 | Complete | Implementation/Test | Expanded parent heading sections in context packs under profile control. |

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_retrieval_profile_resolution.py`
- `configs/retrieval-profiles.yaml`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## W24-001 Acceptance Criteria

- [x] `RetrievalService.context_pack` expands same-document parent heading
  sections only when the effective retrieval profile enables
  `expand_parent_sections`.
- [x] Parent expansion uses heading hierarchy: a hit under `["Parent", "Child"]`
  expands chunks sharing the `["Parent"]` prefix; a top-level hit expands chunks
  sharing that top-level heading.
- [x] Parent expansion applies only to native context packs and does not change
  `/v1/vector_stores/{id}/search` or Responses file-search result counts.
- [x] Expansion preserves tenant/business/security filtering, vector-store or
  knowledge-base filters, safe file-attribute filters, and post-ACL checks.
- [x] Parent-expanded chunks are de-duplicated, ordered readably around each
  direct hit, and then token-trimmed together with neighbor-expanded chunks.
- [x] Parent-section citations keep OpenAI-core annotations while richer native
  citation metadata identifies the relation to the direct hit.
- [x] Focused tests prove enabled expansion, disabled/no-heading preservation,
  filter SQL construction, citation relation metadata, and search result-count
  isolation.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py
22 passed in 1.12s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_openai_compat_search.py
47 passed in 1.56s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -q packages apps tests
exit 0

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
138 passed, 2 warnings in 4.65s

git diff --check
exit 0
```

## Notes

This ticket does not add explicit `parent_chunk_id` storage, database migrations,
OpenAI search-result expansion, API-key behavior, provider routing, or admin UI
changes.
