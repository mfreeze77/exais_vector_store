# WAVE-086 OpenAI Citation Orphan Marker Guard

## Objective

Tighten OpenAI citation mimicry by making the Responses citation integrity guard
reject visible `【n†source】` markers that do not have a matching strict
OpenAI `file_citation` annotation.

## Evidence Anchors

- OpenAI Responses file-search examples emit citations as visible source
  markers in assistant `output_text.text` plus `output_text.annotations`
  entries with `type`, `index`, `file_id`, and `filename`.
- OpenAI Assistants annotation guidance describes source-marker substrings as
  client-replaceable annotation spans.
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## Scope

- Preserve the current strict OpenAI `file_citation` annotation object.
- Preserve same-index multi-citation support where several annotations point to
  one visible marker.
- Reject orphan visible `【n†source】` markers in Responses `output_text` parts
  when no annotation points at that marker offset.
- Add focused regression proof and docs.

## Non-Goals

- Changing citation marker text, marker placement, or annotation fields.
- Removing native ExAIS citation proof.
- Changing retrieval ranking, API keys, tenant isolation, indexing, provider
  routing, deployment, or admin UI behavior.

## Acceptance

- [x] Valid Responses citations still pass integrity checks.
- [x] Same-index multi-citations still pass integrity checks.
- [x] A Responses payload with an extra visible source marker and no matching
  annotation fails the integrity guard.
- [x] Docs describe orphan visible marker rejection as part of the citation
  compatibility contract.
- [x] Focused citation tests pass.
- [x] Compile, broad non-integration tests, and `git diff --check` pass.

## Proof

- Focused citation/OpenAPI/native answer verification:
  `python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py tests/test_retrieval_answer_routes.py`
  passed with `118 passed, 2 warnings in 4.28s`.
- Compile:
  `python -m compileall -f -q packages apps tests` passed.
- Broad non-integration:
  `python -m pytest -q -rs tests --ignore=tests/integration` passed with
  `384 passed, 2 warnings in 5.05s`.
- Whitespace:
  `git diff --check` passed.
