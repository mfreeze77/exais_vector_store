# WAVE-113 Kansas Civics Instance Query Planner

## Goal

Make the `ks-state-civics` customer cell search like a legal corpus instead of
a generic document pile by enabling an instance-owned query planner profile and
repeatable recall proof for Kansas court decisions.

## Background

Full-corpus WAVE-111 ingestion proved the Kansas court decisions vector store is
present and indexed, but live recall testing showed a planner gap:

- `80` sampled title+docket queries returned the expected document at rank 1 in
  `28/80` cases.
- The same sample with explicit `docket_number` metadata filters returned the
  expected document at rank 3 in `80/80` cases.

That means the data is present. The missing layer is query planning that turns
legal identifiers in natural language into metadata filters before retrieval.

## Scope

- Add a shared query-planner profile named `ks_civics_legal_v1`.
- Keep the global/default planner behavior unchanged when no profile is set.
- Extract Kansas legal metadata filters from natural-language queries:
  `docket_number`, `decision_date`, `decision_year`, `court`, and `status`.
- Remove extracted docket/date/court/status tokens from the semantic query text
  so vector search focuses on title or issue language.
- Apply planned filters in the OpenAI-compatible vector store search route.
- Make the Kansas civics cell opt in with
  `SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1`.
- Record planner metadata in `search_metadata.openai_compat` for auditability.
- Add regression tests for profile extraction, explicit-filter precedence, and
  route-level forwarding into retrieval.
- Add a repeatable Kansas recall evaluator script for the cell.
- Re-run the live recall check after the cell is updated.

## Out Of Scope

- GraphRAG extraction or graph backend selection.
- Changing global retrieval profile defaults.
- Reindexing the Kansas corpus.
- Adding a reranker or authority graph expansion.
- Legal advice or legal correctness guarantees.

## Acceptance Criteria

- [x] Default `plan_query()` behavior is unchanged for non-profiled calls.
- [x] `ks_civics_legal_v1` extracts docket, date/year, court, and publication
  status into `file_attribute_filters`.
- [x] Explicit request filters win over inferred filters when they conflict.
- [x] OpenAI-compatible `/v1/vector_stores/{id}/search` applies instance
  planned filters per query/subquery.
- [x] The Kansas civics Docker cell is configured with
  `SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1`.
- [x] A repeatable Kansas recall evaluator script exists and has live proof.
- [x] Focused tests pass.
- [x] Live recall proof is rerun and recorded with the new planner enabled.

## Verification

Expected focused proof:

```powershell
python -m pytest -q tests\test_query_planner.py tests\test_openai_responses_routes.py
```

Expected live proof:

```powershell
docker run --rm `
  --network exais-vector-store-ks-state-civics_default `
  -v "${PWD}:/work" `
  -w /work `
  -e SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1 `
  localhost:5000/expertaiservices/exai-vector-store-api@sha256:c2f303c2425ac91a08f95ca53c3efde66ededc1e93d7c407f330212d6da33d80 `
  python scripts/release/kscourts-recall-eval.py `
    --api http://api:8080 `
    --output /work/.release/cells/ks-state-civics/evals/ks-civics-query-planner-recall-2026-08-08.json
```

The live proof script should sample known Kansas vector store files, issue
title+docket searches against `vs_a0d3ac76893e4f6f83bf2992`, and compare
top-k hit rates before and after planner activation.

## Notes

This wave keeps the planner instance-specific and the implementation global.
That is the intended split: every customer cell can opt into its own profile,
while shared APIs and tests stay maintainable.

## Completion Proof 2026-08-08

Implemented the shared `ks_civics_legal_v1` planner profile and enabled it in
the `ks-state-civics` Docker cell.

Changed behavior:

- Default query planning remains unprofiled and behavior-compatible.
- The Kansas profile extracts docket numbers, decision dates/years, court, and
  publication status into internal `file_attribute_filters`.
- The OpenAI vector-store search route now applies planned filters per
  query/subquery and records `query_planner_profile_id` plus `planned_filters`
  under `search_metadata.openai_compat`.
- Explicit caller filters keep precedence over inferred planner filters.
- `scripts/release/kscourts-recall-eval.py` runs the repeatable live recall
  proof for this corpus.

Docker proof:

```text
SVS_IMAGE_API=localhost:5000/expertaiservices/exai-vector-store-api@sha256:c2f303c2425ac91a08f95ca53c3efde66ededc1e93d7c407f330212d6da33d80
SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1
api health=healthy
```

Focused tests:

```text
47 passed, 2 existing FastAPI deprecation warnings
```

Live recall proof saved at:

```text
.release/cells/ks-state-civics/evals/ks-civics-query-planner-recall-2026-08-08.json
```

Live sample result against `vs_a0d3ac76893e4f6f83bf2992`:

| Metric | Before planner | After planner |
|---|---:|---:|
| title+docket recall@1 | 28/80 = 35.00% | 77/80 = 96.25% |
| title+docket recall@3 | 37/80 = 46.25% | 79/80 = 98.75% |
| title+docket recall@10 | 40/80 = 50.00% | 80/80 = 100.00% |

Final proof was generated from inside the pinned API image at
`2026-08-08T08:41:35Z`; observed `p95_ms=1591.702` for the 80 live search
requests.

The remaining exact-document @3 miss is `State v. Harris docket 116515`, where
the corpus has two `State v. Harris` files with the same docket number. The
planner applied the correct docket filter; chunk ranking selected the sibling
same-title/same-docket document first. Disambiguating that case needs date/year
in the user query or a later duplicate-aware legal reranking rule.
