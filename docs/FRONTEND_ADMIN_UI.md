# Frontend / Admin UI Scaffold

The frontend is intentionally thin. It is not the security authority; it only selects modes and passes user/tenant context to the API.

## Current capabilities

- Lists vectorization modes from `/api/v1/vectorization/modes`.
- Selects a mode such as `markdown_docs_v1`, `pdf_markdown_external_v1`, `code_repo_v1`, or `auto_detect_v1`.
- Creates an OpenAI-compatible vector store through `/v1/vector_stores`.
- Ingests Markdown/text content through `/api/v1/documents/ingest`.
- Searches through `/api/v1/retrieval/search`.
- Sends dev tenant/business/user/security headers for local testing.

## Production UI contract

The production UI should not make provider/security decisions on its own. It should call the API with:

```json
{
  "mode": "pdf_markdown_external_v1",
  "vector_store_id": "vs_...",
  "knowledge_base_id": "kb_...",
  "security_level": 2,
  "attributes": {
    "source_pdf_id": "pdf_...",
    "parser": "user_external_pdf_md_pipeline"
  }
}
```

The backend then resolves:

```text
mode -> parser -> chunker -> tokenizer/counter -> embedding profile -> sparse profile -> reranker -> retrieval profile -> security policy
```

## Production hardening tickets

- Replace dev headers with session/OIDC/API-key principal resolution.
- Add instance switcher and business/user vault switcher.
- Add upload progress and resumable ingest jobs.
- Add source-system connection screens.
- Add retrieval eval dashboard and golden query set authoring.
- Add deployment/fleet version dashboard.
