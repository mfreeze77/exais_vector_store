# WAVE-114 Kansas Civics Legal Exact Result Diversity

## Goal

Fix same-title or same-docket legal ambiguity so exact Kansas court-decision
searches surface distinct matching documents before repeated chunks from one
document.

## Background

WAVE-113 made the `ks-state-civics` cell metadata-aware and moved title+docket
recall from weak generic semantic ranking to strong legal retrieval. One
remaining miss exposed a law-specific issue:

- Query: `State v. Harris docket 116515`
- The planner correctly inferred `docket_number=116515`.
- The corpus contains two `State v. Harris` files with that same docket.
- Chunk ranking filled the top results with one sibling document instead of
  surfacing both documents as an ambiguity set.

For legal search, this is unacceptable. Exact metadata matches should show
distinct matching opinions before duplicate chunks from a single opinion.

## Scope

- Keep the behavior profile-scoped to `ks_civics_legal_v1`.
- Trigger the fix only when the planner inferred file-attribute filters.
- Increase the route fetch depth for legal exact searches so duplicate-heavy
  documents do not hide sibling documents.
- Reorder legal exact search chunks by document diversity before pagination:
  first best chunk from each document, then second best chunk from each
  document, and so on.
- Preserve the existing chunk score values and citation payload shape.
- Record metadata that legal exact document diversity was active.
- Add route-level regression coverage for duplicate document flooding.
- Re-run live Kansas recall proof and record the duplicate fix.

## Out Of Scope

- GraphRAG.
- Legal advice.
- Changing global retrieval behavior.
- Reindexing the Kansas corpus.
- Replacing reranking or adding a new model provider.
- Deduplicating or merging source PDFs in storage.

## Acceptance Criteria

- [x] Non-profiled and non-exact searches keep existing ranking behavior.
- [x] Legal exact searches overfetch beyond the requested page size.
- [x] Legal exact searches interleave distinct documents before duplicate
  chunks from the same document.
- [x] The route records audit metadata showing legal exact diversity was active.
- [x] Focused route tests pass.
- [x] Live `State v. Harris docket 116515` search returns both same-docket
  documents in the first page.
- [x] Live 80-case Kansas recall proof improves the duplicate miss.

## Verification

Expected focused proof:

```powershell
docker run --rm `
  -v "${PWD}:/work" `
  -w /work `
  localhost:5000/expertaiservices/exai-vector-store-api@sha256:<digest> `
  sh -lc "PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent python -m pytest -q tests/test_openai_responses_routes.py tests/test_query_planner.py"
```

Expected live proof:

```powershell
docker exec exais-vector-store-ks-state-civics-api-1 `
  python scripts/release/kscourts-recall-eval.py
```

## Completion Proof 2026-08-08

Implemented profile-scoped legal exact result diversity in the OpenAI
vector-store search route.

Changed behavior:

- Only `ks_civics_legal_v1` searches with inferred `file_attribute_filters`
  activate the legal diversity path.
- Legal exact searches now overfetch to at least `51` chunks for a first-page
  request and record `search_fetch_limit` in `search_metadata.openai_compat`.
- Legal exact chunks are interleaved by `document_id` before pagination, so
  same-docket sibling opinions appear before duplicate chunks from one opinion.
- Existing scores, citations, and result payload shape are preserved.

Docker proof:

```text
SVS_IMAGE_API=localhost:5000/expertaiservices/exai-vector-store-api@sha256:be5c3a418960cb0a1c27622d0abbfeabd36c20e800170bcb86a7f4ab80649cd5
SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1
api health=healthy
```

Focused tests:

```text
48 passed, 2 existing FastAPI deprecation warnings
```

Live targeted proof saved at:

```text
.release/cells/ks-state-civics/evals/ks-civics-harris-diversity-2026-08-08.json
```

`State v. Harris docket 116515` now returns both same-docket opinions in the
first two results:

```text
rank 1: doc_4276554e6b25446a8a878b83 decision_date=2020-07-17 docket=116515
rank 2: doc_305e26160d6145e9b00414c3 decision_date=2018-01-19 docket=116515
```

Live 80-case recall proof saved at:

```text
.release/cells/ks-state-civics/evals/ks-civics-legal-diversity-recall-2026-08-08.json
```

Final live sample result against `vs_a0d3ac76893e4f6f83bf2992`:

| Metric | After WAVE-113 | After WAVE-114 |
|---|---:|---:|
| title+docket recall@1 | 77/80 = 96.25% | 77/80 = 96.25% |
| title+docket recall@3 | 79/80 = 98.75% | 80/80 = 100.00% |
| title+docket recall@10 | 80/80 = 100.00% | 80/80 = 100.00% |

No misses remained in the 80-case recall proof. Observed `p95_ms=1924.878`
for the 80 live search requests.
