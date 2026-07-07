# Conversation Goal Checklist

| Goal | Captured in scaffold |
|---|---|
| Recreate useful OpenAI vector-store behavior while owning storage | `/v1/vector_stores` API routes, `vector_store_repo.py`, `docs/OPENAI_COMPAT.md` |
| Store embeddings from OpenAI or other providers in own store | `providers.py`, `model-gateway`, `embeddings` table, Qdrant adapter |
| Holy-grail retrieval DB instead of vector swamp | Postgres truth model, Qdrant dense index, OpenSearch sparse index, object store, audit/usage |
| Per tenant / user / business instance | DB schema, RLS, `Principal`, `RetrievalScope`, instance manifests |
| Security levels and ACLs | `configs/security-levels.yaml`, `security.py`, post-ACL hydration, RLS draft |
| Production ready, not MVP | infra templates, runbooks, production docs, ticket trail |
| 2 TB retrieval and Hetzner planning | `docs/HETZNER_SIZING.md`, Terraform/dedicated notes |
| Micro-production per business/user | `instances/_templates`, `instance-agent`, `docs/MICRO_PRODUCTION.md` |
| Base product + per-instance setup/update flow | Dockerfiles, Compose, instance manifests, fleet upgrade scripts |
| Frontend mode selects vectorization strategy | `configs/vectorization-modes.yaml`, `model_registry.py`, `/api/v1/vectorization/modes` |
| Use OpenAI, specialized models, Hugging Face, RunPod | `configs/model-registry.yaml`, `model-gateway`, `infra/runpod` |
| Existing PDF-to-Markdown process is good and should be stubbed | `pdf_markdown_external_v1`, `PDF_PIPELINE_STUB.md`, `pdf_markdown_external_chunks()` |
| Continue PDF research | `raw_pdf_research_v1` mode and planning specs |
| Ticket trail | `docs/TICKET_TRAIL.md` |
