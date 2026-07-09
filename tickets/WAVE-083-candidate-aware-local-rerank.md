# WAVE-083 Candidate-Aware Local Rerank

## Objective

Improve the default secure retrieval path by making the local lexical reranker
candidate-aware, so ExAIS can promote stronger evidence without external
reranker credentials.

## Evidence Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `tests/test_retrieval_profile_resolution.py`
- `configs/retrieval-profiles.yaml`
- OpenAI file search is documented as combining semantic and keyword retrieval;
  this ticket improves the local post-fusion keyword relevance layer while
  preserving the OpenAI-facing response/citation shape.

## Scope

- Keep the existing `local_lexical_overlap_v1` profile contract.
- Score local rerank candidates with query-token IDF across the candidate set,
  plus exact phrase, ordered query-pair, and token-proximity signals.
- Preserve dense/sparse fusion, ACL checks, citations, OpenAI annotations,
  model-gateway reranking, and `ranker: none` behavior.
- Add focused regression proof and docs.

## Non-Goals

- Changing external model-gateway reranker contracts.
- Changing embedding, Qdrant/OpenSearch/Postgres sparse search, vector-store
  APIs, API keys, tenant isolation, or citation annotation fields.
- Renaming retrieval profiles or changing the OpenAI-compatible request schema.

## Acceptance

- [x] Local rerank scores can prefer a candidate containing discriminating query
  terms over a higher-fusion candidate that only matches common terms.
- [x] Rerank audit records the local scoring strategy.
- [x] Strict OpenAI citation annotations remain unchanged.
- [x] Focused retrieval/OpenAI compatibility tests pass.
- [x] Compile, broad non-integration tests, and `git diff --check` pass.

## Proof

- Focused retrieval/OpenAI compatibility:
  `python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_openai_compat_search.py tests/test_opensearch_adapter.py`
  passed with `126 passed in 1.44s`.
- Compile:
  `python -m compileall -f -q packages apps tests` passed.
- Broad non-integration:
  `python -m pytest -q -rs tests --ignore=tests/integration` passed with
  `380 passed, 2 warnings in 5.40s`.
- Whitespace:
  `git diff --check` passed.
