# Intelligent Vectorization Router

The frontend should pick a mode, not just a tokenizer. A mode expands into:

```text
parser -> normalizer -> token counter -> chunker -> metadata extractor
-> embedding profile -> sparse profile -> reranker -> retrieval profile
-> security policy -> eval profile
```

Primary modes:

- `markdown_docs_v1`
- `pdf_markdown_external_v1`
- `raw_pdf_research_v1`
- `code_repo_v1`
- `tables_csv_json_v1`
- `logs_errors_v1`
- `mixed_multimodal_v1`
- `auto_detect_v1`

Specialized parser coverage:

- `code_repo_v1` chunks common code files around detected symbols such as
  functions, classes, methods, and module preambles.
- `tables_csv_json_v1` produces schema/record-aware chunks for JSON arrays,
  JSON objects, CSV/TSV rows, and Markdown pipe tables with row/table metadata.
- `logs_errors_v1` chunks log input on event boundaries so multi-line errors
  and stack traces remain retrievable as a unit.
- `raw_pdf_research_v1` and `mixed_multimodal_v1` route to defined multimodal
  retrieval profiles that reuse the existing dense+sparse RRF, local rerank,
  lexical MMR diversity, context expansion, citation, and post-ACL contract.

Raw PDF handling is upload-specific: `/api/v1/documents/upload` can call the
configured external RunPod Marker endpoint and then ingest the returned Markdown
as `pdf_markdown_external_v1`. JSON ingestion still expects already-converted
text content.

Do not fine-tune first. First improve parsing, chunking, metadata, hybrid search, reranking, and evals. Fine-tune only when evals show persistent domain gaps.
