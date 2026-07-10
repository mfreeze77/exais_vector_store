# Expert AI Services Ticket Corpus Quality Gate

`golden.json` is the filename-judged, answerability-aware golden set for the
`expertaiservices` vector store built from `tickets/`. It uses stable filenames
instead of database IDs so a clean reingestion can run the same judgments.

The gate measures document hit rate, top-1 accuracy, MRR, NDCG, passage support,
citation completeness, unique-file coverage, duplicate rate, errors, and live
latency. Returned passage text is inspected in memory for support terms but is
never written to the proof artifact.

Document metrics rank the first occurrence of each unique filename. Raw chunk
order is retained separately as `result_rank`; each judged file record also
keeps its deduplicated `document_rank`, `file_id`, and `chunk_id`. Passage
support, citation validation, and duplication still inspect the raw chunk list.

Run from the repository root against the local Docker cell:

```powershell
docker run --rm `
  --network exais-vector-store-local_default `
  -v "${PWD}:/work" `
  -w /work `
  <pinned-api-image> `
  python scripts/release/corpus-quality-eval.py `
    --api http://api:8080 `
    --vector-store-id <vector-store-id> `
    --output /work/.release/cells/local/evals/expertaiservices-tickets-v1.json
```

The output under `.release/` is machine-local and ignored by Git. A passing
ticket-corpus run does not prove quality for other customer corpora, raw PDF/OCR,
multimodal retrieval, or unjudged questions.

This set is a regression baseline calibrated from the first ticket-corpus
pilot, not a blind holdout. Add independently authored customer queries before
using it to make broader product-quality claims.
