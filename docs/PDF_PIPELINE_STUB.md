# PDF Pipeline Stub

Your existing large PDF -> Markdown process is treated as production-ready external parsing.

## Mode

`pdf_markdown_external_v1`

Expected input:

- Markdown content
- optional original PDF ID/path
- optional page markers
- optional section/page map

Supported page markers in the scaffold chunker:

```markdown
<!-- page: 12 -->
# Section
...
```

or:

```markdown
Page 12
```

SVS owns chunking, embeddings, sparse indexing, citations, retrieval evals, security, and audit. The external pipeline owns PDF parsing/OCR/table extraction upstream.
