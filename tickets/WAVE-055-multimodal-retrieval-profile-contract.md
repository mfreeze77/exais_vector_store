# WAVE-055 Multimodal Retrieval Profile Contract

## Status

Complete.

## Context

`configs/vectorization-modes.yaml` routes `raw_pdf_research_v1` to
`hybrid_multimodal_pdf_v1` and `mixed_multimodal_v1` to
`hybrid_multimodal_secure_v1`, but `configs/retrieval-profiles.yaml` does not
define either profile. That leaves router-selected research modes with
unresolvable retrieval profile IDs and weakens the end-to-end vector-store build
contract.

This ticket adds the missing retrieval profiles as registry contracts using
existing retrieval capabilities only: dense+sparse RRF, local lexical rerank,
lexical MMR diversity, parent/neighbor context expansion, citations, and
post-ACL checks.

## Scope

- Add `hybrid_multimodal_pdf_v1` to `configs/retrieval-profiles.yaml`.
- Add `hybrid_multimodal_secure_v1` to `configs/retrieval-profiles.yaml`.
- Add tests that every vectorization mode with a `retrieval_profile` references
  a defined retrieval profile.
- Add tests that the multimodal profiles declare existing quality/safety knobs.
- Update docs and ticket trail.

## Out of Scope

- New embedding providers, reranker providers, model-gateway behavior, API-key
  behavior, migrations, indexing semantics, tenant isolation, deployment, and
  admin UI changes.
- Implementing native multimodal parsing or OCR.
- Replacing the existing local reranker with a provider-backed multimodal
  reranker.

## Acceptance Criteria

- [x] `hybrid_multimodal_pdf_v1` exists in the retrieval profile registry.
- [x] `hybrid_multimodal_secure_v1` exists in the retrieval profile registry.
- [x] All mode registry `retrieval_profile` references resolve.
- [x] New profiles use only existing retrieval knobs.
- [x] New profiles preserve post-ACL checks and citation requirements.
- [x] Focused registry/retrieval tests pass.
- [x] Full non-integration verification passes.

## Proof

- Focused registry/retrieval tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_vectorization_plan.py`
  - Result: `53 passed`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass.
- Full non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: `265 passed, 2 warnings`.
- Hygiene:
  `git diff --check`
  - Result: pass.
  `rg -n "[ \t]+$" configs/retrieval-profiles.yaml tests/test_retrieval_profile_resolution.py docs/VECTORIZATION_ROUTER.md docs/TICKET_TRAIL.md tickets/README.md tickets/WAVE-055-multimodal-retrieval-profile-contract.md`
  - Result: no matches.
