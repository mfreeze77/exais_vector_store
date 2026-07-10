# WAVE-109 Expert AI Services Live Retrieval Quality Gate

## Goal

Replace architecture-level confidence with an empirical, repeatable quality
scorecard against the live `expertaiservices` ticket corpus.

## Scope

- Define a 19-query, filename-judged golden set across ingestion, embeddings,
  repair, hybrid retrieval, reranking, diversity, context expansion, filters,
  pagination, citations, OpenAPI, and tenant-isolation topics.
- Verify that returned passages contain answer-support terms, not only that the
  expected document appears.
- Compare the production default with query rewriting, no reranker, dense-only,
  and sparse-only ranking options.
- Record citation completeness, unique-file coverage, duplication, errors, and
  live latency without persisting returned passage text.
- Rank documents by the first occurrence of each unique filename while
  retaining raw result rank, deduplicated document rank, file ID, and chunk ID
  in the redacted proof.
- Require a material score delta before recommending a production ranking
  change from this bounded pilot.

## Out Of Scope

- Changing retrieval ranking or production profile defaults.
- Claiming quality for customer corpora outside `tickets/`.
- Raw PDF/OCR, multimodal, code-repository, log, table, or structured-data
  quality proof.
- Live cross-model reindexing or provider bakeoff.

## Acceptance Criteria

- [x] The golden set uses stable filenames and every query has answer-support
  terms.
- [x] The evaluator measures hit@k, top-1, recall, precision, MRR, NDCG,
  passage support, citation completeness, unique files, duplication, errors,
  and latency.
- [x] Proof output contains result IDs, filenames, ranks, scores, and metrics,
  but not returned passage text or credentials.
- [x] Hit, top-1, MRR, and NDCG use the explicit
  `unique_filename_first_occurrence` document-ranking contract; passage support,
  citations, and duplication inspect raw chunk results.
- [x] The live production-default candidate passes every declared threshold.
- [x] Candidate failures remain visible instead of being averaged into a false
  pass.
- [x] An alternative must beat the passing default by at least `0.01` selection
  score before the evaluator recommends promotion.

## Live Corpus

```text
vector_store_id=vs_06f82c1f93ec4296b8a5e760
name=expertaiservices
alias=eais
status=completed
files=118/118
active_chunks=906
active_embeddings=906
embedding_profile=openai_text_embedding_3_small_1536
```

## Live Command

```powershell
docker run --rm `
  --network exais-vector-store-local_default `
  -v "${PWD}:/work" `
  -w /work `
  sha256:2be494069ee4bbd8d05dddc853330ddc88e7ce09e679b72d06b7a02b906cd9cd `
  python scripts/release/corpus-quality-eval.py `
    --api http://api:8080 `
    --vector-store-id vs_06f82c1f93ec4296b8a5e760 `
    --pace-ms 250 `
    --output /work/.release/cells/local/evals/expertaiservices-tickets-v1.json
```

Result: `QUALITY_STATUS=PASS`.

The redacted machine-local proof is
`.release/cells/local/evals/expertaiservices-tickets-v1.json`.

```text
golden_sha256=b8512e62700d820934adee2636226dfe84c39bc48bd4bea301d2a9d197030d49
proof_sha256=a5b0a7a80341867d268e9a296b5db87c941e819cd11bf2a175d4552076964853
generated_at=2026-07-09T22:25:01.024984-05:00
recommendation=default_auto
recommendation_reason=required_candidate_within_promotion_margin
```

## Scorecard

| Candidate | Status | Top-1 | Hit@5 | MRR | NDCG@5 | Support@10 | Citations | p95 ms | Threshold failures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `default_auto` | PASS | 0.842105 | 1.000000 | 0.903509 | 0.927944 | 1.000000 | 1.000000 | 465.850 | none |
| `dense_only_auto` | PASS | 0.842105 | 1.000000 | 0.903509 | 0.927944 | 1.000000 | 1.000000 | 446.567 | none |
| `no_rerank` | FAIL | 0.842105 | 1.000000 | 0.912281 | 0.934835 | 0.947368 | 1.000000 | 375.864 | passage support |
| `sparse_only_auto` | FAIL | 0.789474 | 1.000000 | 0.877193 | 0.908519 | 0.947368 | 1.000000 | 398.136 | passage support |
| `default_auto_rewrite` | FAIL | 0.736842 | 1.000000 | 0.842105 | 0.882203 | 0.947368 | 1.000000 | 838.040 | top-1, passage support, p95 latency |

The default returned an average of `5.210526` unique files in the first ten
chunks, with mean same-file duplicate rate `0.476608`. It had zero query errors
and no query-level hit, support, or citation failures.

`dense_only_auto` scored `0.922525` versus `0.922379` for the default. The
`0.000146` difference is below the configured `0.01` promotion margin, so the
evaluator correctly retained `default_auto`. This pilot does not justify
removing sparse retrieval.

## Judgment Audit

The first durable run scored `18/19` support-complete queries and therefore
failed the passage-support threshold because the multi-query judgment required
the singular term `subquery`, while the retrieved and source passages correctly
used `subqueries`, `query arrays`, and `merge results`. Inspection proved this
was an invalid lexical judgment, not a ranking miss. The golden support contract
was corrected to `query arrays` plus `merge results`; no retrieval code or
production configuration changed.

## Verification

Focused evaluator tests:

```text
python -m pytest -q tests/test_corpus_quality_eval.py tests/test_bakeoff.py tests/test_live_bakeoff.py tests/test_openai_file_search_parity_eval.py
23 passed, 2 existing FastAPI deprecation warnings
```

Broad non-integration regression:

```text
python -m pytest -q -rs --ignore=tests/integration
574 passed, 2 existing FastAPI deprecation warnings
```

Compile and whitespace:

```text
python -m compileall -q packages apps scripts tests
git diff --check
pass
```

Independent quality control: `PASS WITH NOTES`.

- The reviewer independently recomputed metrics, thresholds, and selection
  scores from the final proof and found no blocking defects.
- The proof redaction and rank/file/chunk field contracts passed review.
- The known-topic ticket pilot is not a held-out customer-query or no-answer
  evaluation.
- Default p95 was `465.850 ms` against the `500 ms` threshold; repeated-load
  latency proof remains useful but is outside this ticket.

## Claim Boundary

This is objective live quality proof for 19 judged questions against the
current 118-file ticket corpus. It is strong evidence for Markdown/ticket search
in this store. It is not proof for unjudged customer documents, raw PDF/OCR,
multimodal inputs, or other workload modes.

The thresholds were established from the initial ticket-corpus pilot and are a
repeatable regression acceptance band, not a preregistered blind holdout. The
recorded ranks and metrics are empirical, but generalization requires a larger
independently authored customer query set.
