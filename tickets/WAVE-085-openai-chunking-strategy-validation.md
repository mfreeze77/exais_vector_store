# WAVE-085 OpenAI Chunking Strategy Validation

## Objective

Tighten OpenAI vector-store mimicry by validating `chunking_strategy` wherever
OpenAI-compatible vector-store file attach and batch attach requests accept it.

## Evidence Anchors

- OpenAI retrieval guide chunking section: default chunking is 800 tokens with
  400 overlap; `max_chunk_size_tokens` must be 100-4096 inclusive; overlap must
  be non-negative and no more than half the max.
- OpenAI file-batch create reference: batch-level `attributes` or
  `chunking_strategy` apply to `file_ids`, while per-file `files[]` entries can
  carry their own `attributes` or `chunking_strategy`.
- `packages/svs_common/svs_common/schemas.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_vector_store_object.py`
- `tests/test_openai_files.py`

## Scope

- Add one shared OpenAI chunking-strategy validator.
- Validate typed vector-store create/update `chunking_strategy`.
- Validate direct vector-store file attach and file-batch global/per-file
  `chunking_strategy` before storing it in attachment attributes.
- Preserve the existing metadata storage shape for valid requests.
- Add focused regression proof and docs.

## Non-Goals

- Changing chunking execution, parser behavior, indexing semantics, retrieval
  ranking, API-key behavior, tenant isolation, database migrations, provider
  routing, deployment, or admin UI behavior.
- Rewriting existing vector-store file response payload shape.

## Acceptance

- [x] `auto` chunking accepts only `{ "type": "auto" }`.
- [x] `static` chunking rejects unknown fields and invalid
  `max_chunk_size_tokens` values outside 100-4096.
- [x] `static` chunking rejects negative overlap or overlap greater than half
  the effective max chunk size.
- [x] File-batch global and per-file chunking metadata still round-trips for
  valid OpenAI-shaped requests.
- [x] Focused vector-store/file-batch tests pass.
- [x] Compile, broad non-integration tests, and `git diff --check` pass.

## Proof

- Focused vector-store/file-batch:
  `python -m pytest -q -rs tests/test_openai_vector_store_object.py tests/test_openai_files.py tests/test_openapi_contract.py`
  passed with `91 passed, 2 warnings in 3.94s`.
- Compile:
  `python -m compileall -f -q packages apps tests` passed.
- Broad non-integration:
  `python -m pytest -q -rs tests --ignore=tests/integration` passed with
  `383 passed, 2 warnings in 4.91s`.
- Whitespace:
  `git diff --check` passed.
