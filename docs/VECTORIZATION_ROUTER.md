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

Do not fine-tune first. First improve parsing, chunking, metadata, hybrid search, reranking, and evals. Fine-tune only when evals show persistent domain gaps.
