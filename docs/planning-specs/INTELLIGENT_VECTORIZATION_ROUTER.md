# Intelligent Vectorization Router — Production Spec Supplement

This supplement extends the `exai_vector_store` design with a frontend-driven **mode router** that chooses the best ingestion, tokenization, chunking, embedding, sparse retrieval, reranking, and evaluation strategy for each document type and business instance.

Your existing large-PDF process that converts PDFs into Markdown is treated as a first-class production feature named `external_pdf_to_markdown_v1`. This spec stubs the interface so the platform can consume your Markdown output while the research track continues evaluating native PDF, OCR, multimodal, and visual-document embedding options.

---

## 1. Product idea

The frontend should expose a simple intent such as:

```txt
What are we vectorizing?

- Markdown knowledge base
- Large PDF already converted to Markdown
- Raw PDF / OCR document
- Code repository
- API docs
- Legal / contracts
- Financial docs
- Tickets / CRM notes
- Tables / CSV / JSON
- Logs / stack traces
- Mixed multimodal document
- Auto-detect
```

Internally, that mode must not only select a tokenizer. It should select a full **Vectorization Profile**:

```txt
mode
  -> parser profile
  -> normalization profile
  -> tokenizer/counting profile
  -> chunking profile
  -> metadata extraction profile
  -> embedding model profile
  -> sparse/vector/late-interaction index profile
  -> reranker profile
  -> retrieval profile
  -> security policy
  -> cost/latency policy
  -> evaluation profile
```

The goal is to make the system feel simple in the UI while remaining highly tunable in production.

---

## 2. Core design principle

A tokenizer is model-specific. You do not generally choose a tokenizer independently from the model and expect universal correctness.

The stable abstraction is:

```txt
TokenCounter
  knows how to estimate tokens for a provider/model

EmbeddingProvider
  accepts normalized chunk input
  returns vectors and model metadata

VectorizationProfile
  ties parser + chunker + model + tokenizer + index together
```

So the UI mode should map to a `vectorization_profile_id`, not a raw model name.

---

## 3. New services

Add these services to the base SVS product.

```txt
svs-router
  Selects vectorization profile for a document/query.

svs-tokenizer
  Counts tokens using provider/model-aware counters.

svs-model-gateway
  Normalizes OpenAI, Voyage, Cohere, Jina, local Hugging Face, RunPod, and custom endpoints.

svs-model-registry
  Stores model capabilities, dimensions, context limits, costs, privacy constraints, and versions.

svs-eval-runner
  Runs retrieval regression tests, model bakeoffs, and per-instance evals.

svs-finetune-lab
  Builds training/eval datasets and fine-tunes open embedding/reranking models when justified.
```

The model gateway should expose an internal OpenAI-like contract even when the backend is not OpenAI:

```txt
POST /internal/models/embeddings
POST /internal/models/rerank
POST /internal/models/classify
POST /internal/models/tokenize
POST /internal/models/estimate-cost
```

---

## 4. New repo folders

```txt
apps/
  router/
  tokenizer/
  model-gateway/
  eval-runner/
  finetune-lab/

configs/
  vectorization-modes.example.yaml
  model-registry.example.yaml
  routing-rules.example.yaml
  eval-profiles.example.yaml
  runpod-endpoints.example.yaml

infra/
  runpod/
    embedding-worker.Dockerfile
    rerank-worker.Dockerfile
    handler.py
    tei-runpod-template.md
    infinity-runpod-template.md

runbooks/
  embedding-model-bakeoff.md
  add-new-vectorization-mode.md
  add-new-model-provider.md
  runpod-model-endpoint.md
  embedding-finetune-playbook.md
  pdf-pipeline-research.md

evals/
  schemas/
    golden-query.schema.json
    eval-run.schema.json
  default-golden-sets/
  reports/
```

---

## 5. Vectorization mode registry

Create `configs/vectorization-modes.example.yaml`.

```yaml
modes:
  markdown_docs_v1:
    label: Markdown docs
    description: Heading-aware Markdown ingestion for docs, wikis, manuals, policies, and notes.
    parser: markdown_ast_v1
    normalizer: markdown_semantic_clean_v1
    tokenizer: provider_model_token_counter_v1
    chunker: markdown_heading_hierarchy_v2
    metadata_extractor: markdown_frontmatter_links_headings_v1
    embedding_profile: openai_text_embedding_3_small_1536
    sparse_profile: opensearch_bm25_docs_v1
    reranker_profile: voyage_rerank_2_5_lite_default
    retrieval_profile: hybrid_rrf_secure_v2
    eval_profile: docs_qa_retrieval_v1
    default_security_level: 1

  pdf_markdown_external_v1:
    label: Large PDF already converted to Markdown
    description: Consumes user-provided PDF-to-Markdown output. PDF extraction itself is external/stubbed.
    parser: trusted_pdf_markdown_bundle_v1
    normalizer: pdf_markdown_cleanup_v1
    tokenizer: provider_model_token_counter_v1
    chunker: markdown_heading_page_hybrid_v1
    metadata_extractor: pdf_markdown_page_heading_citation_v1
    embedding_profile: voyage_context_3_docs_default
    sparse_profile: opensearch_bm25_pdf_markdown_v1
    reranker_profile: qwen3_reranker_or_voyage_rerank_v1
    retrieval_profile: hybrid_contextual_pdf_v1
    eval_profile: pdf_qa_citation_v1
    default_security_level: 2
    feature_status: stubbed_external_parser_ready

  raw_pdf_research_v1:
    label: Raw PDF / OCR research mode
    description: Experimental native PDF/OCR flow for scanned or visually complex PDFs.
    parser_candidates:
      - user_external_pdf_to_md_v1
      - mistral_ocr_v3
      - docling_vlm_v1
      - marker_v1
      - pymupdf4llm_v1
    embedding_candidates:
      - jina_embeddings_v4_multimodal
      - cohere_embed_v4_multimodal
      - voyage_multimodal_3_5
      - text_embedding_3_large_text_only_after_md
    chunker: page_heading_visual_region_hybrid_v1
    retrieval_profile: hybrid_multimodal_pdf_v1
    eval_profile: visually_rich_pdf_retrieval_v1
    default_security_level: 3
    feature_status: research

  code_repo_v1:
    label: Code repository
    description: Symbol-aware indexing for functions, classes, routes, configs, tests, and errors.
    parser: tree_sitter_symbol_graph_v1
    normalizer: code_language_preserve_v1
    tokenizer: model_specific_code_counter_v1
    chunker: code_symbol_dependency_chunker_v2
    metadata_extractor: git_repo_symbol_metadata_v1
    embedding_profile: voyage_code_3_or_qwen3_code_v1
    sparse_profile: opensearch_code_bm25_ngram_v1
    reranker_profile: qwen3_reranker_code_v1
    retrieval_profile: hybrid_code_symbol_rrf_v2
    eval_profile: code_search_v1
    default_security_level: 2

  tables_csv_json_v1:
    label: Tables / CSV / JSON
    description: Row/object-aware embeddings with schema summaries and exact lookup indexes.
    parser: structured_record_parser_v1
    normalizer: schema_value_summary_v1
    tokenizer: provider_model_token_counter_v1
    chunker: record_group_schema_chunker_v1
    metadata_extractor: structured_schema_metadata_v1
    embedding_profile: openai_text_embedding_3_small_1536
    sparse_profile: opensearch_structured_keyword_v1
    reranker_profile: lightweight_cross_encoder_v1
    retrieval_profile: structured_hybrid_filter_first_v1
    eval_profile: structured_lookup_v1
    default_security_level: 2

  logs_errors_v1:
    label: Logs / errors / stack traces
    description: Exact-first retrieval for stack traces, error codes, service names, and event patterns.
    parser: log_event_parser_v1
    normalizer: stacktrace_preserve_v1
    tokenizer: provider_model_token_counter_v1
    chunker: event_window_chunker_v1
    metadata_extractor: service_env_timestamp_metadata_v1
    embedding_profile: bge_m3_or_openai_small_v1
    sparse_profile: opensearch_logs_exact_ngram_v1
    reranker_profile: disabled_by_default
    retrieval_profile: sparse_first_then_semantic_v1
    eval_profile: incident_lookup_v1
    default_security_level: 3

  mixed_multimodal_v1:
    label: Mixed multimodal document
    description: Documents with text, tables, charts, figures, screenshots, and visual layout.
    parser: multimodal_document_parser_v1
    normalizer: text_image_table_interleave_v1
    tokenizer: multimodal_provider_counter_v1
    chunker: visual_region_page_section_chunker_v1
    metadata_extractor: visual_doc_metadata_v1
    embedding_profile: cohere_embed_v4_or_jina_v4
    sparse_profile: opensearch_bm25_docs_v1
    reranker_profile: multimodal_reranker_candidate_v1
    retrieval_profile: hybrid_multimodal_v1
    eval_profile: multimodal_doc_qa_v1
    default_security_level: 3
```

---

## 6. Model registry

Create `configs/model-registry.example.yaml`.

```yaml
providers:
  openai:
    type: external_api
    supports_embeddings: true
    supports_rerank: false
    privacy_tier: external_vendor
    adapter: OpenAIEmbeddingAdapter

  anthropic:
    type: external_api
    supports_embeddings: false
    supports_rerank: false
    supports_llm: true
    privacy_tier: external_vendor
    adapter: AnthropicLLMAdapter
    notes: Use Claude for classification, summaries, synthetic eval question generation, and answer generation; do not route embedding calls here.

  voyage:
    type: external_api
    supports_embeddings: true
    supports_contextual_embeddings: true
    supports_code_embeddings: true
    supports_multimodal_embeddings: true
    supports_rerank: true
    privacy_tier: external_vendor
    adapter: VoyageAdapter

  cohere:
    type: external_api_or_bedrock_or_azure
    supports_embeddings: true
    supports_multimodal_embeddings: true
    supports_rerank: true
    privacy_tier: external_vendor_or_cloud
    adapter: CohereAdapter

  jina:
    type: external_api_or_self_hosted
    supports_embeddings: true
    supports_multimodal_embeddings: true
    supports_pdf_direct: true
    supports_task_adapters: true
    privacy_tier: external_vendor_or_self_hosted
    adapter: JinaAdapter

  huggingface_tei:
    type: self_hosted
    supports_embeddings: true
    supports_openai_compatible_api: true
    runtime: text-embeddings-inference
    privacy_tier: local_or_private_gpu
    adapter: OpenAICompatibleEmbeddingAdapter

  infinity:
    type: self_hosted
    supports_embeddings: true
    supports_rerank: true
    supports_clip: true
    supports_colpali: true
    runtime: infinity
    privacy_tier: local_or_private_gpu
    adapter: OpenAICompatibleEmbeddingAdapter

  runpod_serverless:
    type: private_gpu_endpoint
    supports_embeddings: true
    supports_rerank: true
    runtime: custom_container
    privacy_tier: private_gpu
    adapter: RunPodModelAdapter

models:
  openai_text_embedding_3_small_1536:
    provider: openai
    model: text-embedding-3-small
    output_dimensions: 1536
    max_input_tokens: 8192
    use_for:
      - general_docs
      - markdown
      - structured_records
    deployment: external_api

  openai_text_embedding_3_large_3072:
    provider: openai
    model: text-embedding-3-large
    output_dimensions: 3072
    max_input_tokens: 8192
    use_for:
      - high_quality_general_docs
      - multilingual
      - legal_when_allowed
    deployment: external_api

  voyage_4_docs:
    provider: voyage
    model: voyage-4
    use_for:
      - general_retrieval
      - markdown
      - multilingual
    deployment: external_api

  voyage_context_3_docs_default:
    provider: voyage
    model: voyage-context-3
    use_for:
      - contextual_chunk_embeddings
      - long_documents
      - pdf_markdown
    deployment: external_api

  voyage_code_3:
    provider: voyage
    model: voyage-code-3
    use_for:
      - code_retrieval
      - repo_search
      - stack_trace_context
    deployment: external_api

  cohere_embed_v4_multimodal:
    provider: cohere
    model: cohere.embed-v4
    output_dimensions_allowed: [256, 512, 1024, 1536]
    use_for:
      - multimodal_docs
      - images_plus_text
      - visual_pdf_after_policy_approval
    deployment: external_api_or_cloud

  jina_embeddings_v4_multimodal:
    provider: jina
    model: jina-embeddings-v4
    output_dimensions_allowed: [128, 256, 512, 1024, 2048]
    use_for:
      - visual_documents
      - direct_pdf_embedding
      - code_adapter
      - multilingual
    deployment: external_api_or_self_hosted

  qwen3_embedding_0_6b_local:
    provider: runpod_serverless
    model: Qwen/Qwen3-Embedding-0.6B
    use_for:
      - local_private_embeddings
      - multilingual
      - code
      - cost_control
    deployment: runpod_or_local_gpu

  qwen3_embedding_4b_local:
    provider: runpod_serverless
    model: Qwen/Qwen3-Embedding-4B
    use_for:
      - high_quality_private_embeddings
      - multilingual
      - code
    deployment: runpod_gpu

  bge_m3_local:
    provider: huggingface_tei
    model: BAAI/bge-m3
    use_for:
      - dense_sparse_colbert_hybrid
      - multilingual
      - long_chunks
      - private_local
    deployment: local_or_runpod_gpu

  nomic_embed_text_v1_5_local:
    provider: huggingface_tei
    model: nomic-ai/nomic-embed-text-v1.5
    use_for:
      - local_cost_effective_general_docs
      - dimension_experiments
    deployment: local_cpu_or_gpu
```

---

## 7. Routing rules

Create `configs/routing-rules.example.yaml`.

```yaml
routing:
  defaults:
    disallow_external_models_above_security_level: 3
    require_instance_allowlist_for_external_models: true
    fallback_embedding_profile: openai_text_embedding_3_small_1536
    fallback_private_embedding_profile: bge_m3_local
    rerank_top_n: 50

  rules:
    - id: high_security_local_only
      when:
        security_level_gte: 4
      then:
        allow_external_models: false
        embedding_candidates:
          - qwen3_embedding_4b_local
          - bge_m3_local
        reranker_candidates:
          - qwen3_reranker_4b_local

    - id: pdf_markdown_contextual
      when:
        mode: pdf_markdown_external_v1
        security_level_lte: 3
      then:
        embedding_candidates:
          - voyage_context_3_docs_default
          - openai_text_embedding_3_large_3072
          - jina_embeddings_v4_multimodal
        reranker_candidates:
          - voyage_rerank_2_5
          - qwen3_reranker_0_6b_local

    - id: code_repo_code_models
      when:
        mode: code_repo_v1
      then:
        embedding_candidates:
          - voyage_code_3
          - qwen3_embedding_4b_local
          - jina_embeddings_v4_multimodal
        sparse_profile: opensearch_code_bm25_ngram_v1

    - id: visual_doc_multimodal
      when:
        mode: mixed_multimodal_v1
      then:
        embedding_candidates:
          - cohere_embed_v4_multimodal
          - jina_embeddings_v4_multimodal
          - voyage_multimodal_3_5
        require_visual_artifacts: true
```

---

## 8. Model routing algorithm

The router should choose a model in two stages.

### 8.1 Candidate filtering

Filter models by hard constraints:

```txt
instance allowlist
provider availability
security level
external-vendor permission
region/data-residency rule
mode capability
input modality
max context / chunk size
output dimensions supported by target vector collection
cost ceiling
latency SLO
```

### 8.2 Candidate scoring

Score remaining candidates:

```txt
score =
  eval_quality_weight       * last_eval_score
+ mode_match_weight         * capability_match
+ cost_weight               * normalized_cost_score
+ latency_weight            * latency_score
+ privacy_weight            * privacy_score
+ operational_weight        * endpoint_health_score
+ freshness_weight          * model_registry_freshness
```

Never route production traffic to a model solely because it is new or high on a public benchmark. The model must pass per-instance evals.

---

## 9. API additions

### 9.1 List vectorization modes

```http
GET /v1/vectorization/modes
```

Returns frontend-safe modes:

```json
{
  "data": [
    {
      "id": "pdf_markdown_external_v1",
      "label": "Large PDF already converted to Markdown",
      "status": "stable",
      "requires": ["markdown_bundle"],
      "supportsPreview": true
    }
  ]
}
```

### 9.2 Preview ingestion plan

```http
POST /v1/ingestion/preview
```

Request:

```json
{
  "businessInstanceId": "biz_expert_ai_services",
  "knowledgeBaseId": "kb_policy",
  "mode": "pdf_markdown_external_v1",
  "source": {
    "type": "markdown_bundle",
    "files": ["s3://bucket/path/doc.md"]
  },
  "securityLevel": 2,
  "options": {
    "embeddingPreference": "quality",
    "allowExternalProviders": true
  }
}
```

Response:

```json
{
  "mode": "pdf_markdown_external_v1",
  "selectedProfile": "pdf_markdown_contextual_v1",
  "parser": "trusted_pdf_markdown_bundle_v1",
  "chunker": "markdown_heading_page_hybrid_v1",
  "embeddingCandidates": [
    "voyage_context_3_docs_default",
    "openai_text_embedding_3_large_3072"
  ],
  "selectedEmbedding": "voyage_context_3_docs_default",
  "selectedReranker": "voyage_rerank_2_5_lite",
  "estimatedChunks": 18450,
  "estimatedTokens": 12800000,
  "estimatedVectorStorageBytes": 75571200000,
  "warnings": []
}
```

### 9.3 Create ingestion job

```http
POST /v1/ingestion/jobs
```

Request:

```json
{
  "businessInstanceId": "biz_expert_ai_services",
  "knowledgeBaseId": "kb_policy",
  "mode": "pdf_markdown_external_v1",
  "source": {
    "type": "markdown_bundle",
    "uri": "s3://exai-vector-store-prod/instances/expert-ai-services/imports/pdf-md-bundle-001/manifest.json"
  },
  "profileOverrides": {
    "embeddingProfile": "voyage_context_3_docs_default",
    "chunker": "markdown_heading_page_hybrid_v1"
  }
}
```

### 9.4 Run model bakeoff

```http
POST /v1/evals/model-bakeoffs
```

Request:

```json
{
  "businessInstanceId": "biz_expert_ai_services",
  "knowledgeBaseId": "kb_policy",
  "mode": "pdf_markdown_external_v1",
  "candidateProfiles": [
    "voyage_context_3_docs_default",
    "openai_text_embedding_3_large_3072",
    "qwen3_embedding_4b_local",
    "bge_m3_local"
  ],
  "goldenSetId": "golden_expert_ai_services_policy_qa_v3",
  "metrics": ["recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "citation_hit_rate", "latency_p95", "cost_per_1k_queries"]
}
```

### 9.5 Register model endpoint

```http
POST /v1/model-endpoints
```

Request:

```json
{
  "provider": "runpod_serverless",
  "endpointType": "embedding",
  "name": "qwen3-embedding-4b-private-us",
  "baseUrl": "https://api.runpod.ai/v2/<endpoint-id>/runsync",
  "model": "Qwen/Qwen3-Embedding-4B",
  "supports": ["embeddings"],
  "securityMaxLevel": 5,
  "dimensions": 2560,
  "authSecretRef": "secret://instances/global/runpod-qwen3-embedding-4b"
}
```

---

## 10. Database additions

```sql
CREATE TABLE model_providers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_key TEXT UNIQUE NOT NULL,
  provider_type TEXT NOT NULL,
  supports_embeddings BOOLEAN NOT NULL DEFAULT FALSE,
  supports_rerank BOOLEAN NOT NULL DEFAULT FALSE,
  supports_llm BOOLEAN NOT NULL DEFAULT FALSE,
  privacy_tier TEXT NOT NULL,
  adapter_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_registry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_key TEXT UNIQUE NOT NULL,
  provider_key TEXT NOT NULL REFERENCES model_providers(provider_key),
  model_name TEXT NOT NULL,
  model_kind TEXT NOT NULL CHECK (model_kind IN ('embedding','reranker','llm','tokenizer','ocr','parser')),
  output_dimensions INT,
  output_dimensions_allowed INT[],
  max_input_tokens INT,
  supports_text BOOLEAN NOT NULL DEFAULT TRUE,
  supports_image BOOLEAN NOT NULL DEFAULT FALSE,
  supports_pdf BOOLEAN NOT NULL DEFAULT FALSE,
  supports_code BOOLEAN NOT NULL DEFAULT FALSE,
  supports_multilingual BOOLEAN NOT NULL DEFAULT FALSE,
  supports_sparse BOOLEAN NOT NULL DEFAULT FALSE,
  supports_multivector BOOLEAN NOT NULL DEFAULT FALSE,
  deployment_mode TEXT NOT NULL CHECK (deployment_mode IN ('external_api','self_hosted','runpod','local_cpu','local_gpu')),
  license TEXT,
  cost_json JSONB NOT NULL DEFAULT '{}',
  capabilities_json JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'candidate',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vectorization_modes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mode_key TEXT UNIQUE NOT NULL,
  label TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  default_security_level INT NOT NULL DEFAULT 1,
  config_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vectorization_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_key TEXT UNIQUE NOT NULL,
  mode_key TEXT NOT NULL REFERENCES vectorization_modes(mode_key),
  parser_key TEXT NOT NULL,
  normalizer_key TEXT NOT NULL,
  tokenizer_key TEXT NOT NULL,
  chunker_key TEXT NOT NULL,
  metadata_extractor_key TEXT NOT NULL,
  embedding_model_key TEXT NOT NULL REFERENCES model_registry(model_key),
  sparse_profile_key TEXT,
  reranker_model_key TEXT,
  retrieval_profile_key TEXT NOT NULL,
  eval_profile_key TEXT NOT NULL,
  profile_version INT NOT NULL DEFAULT 1,
  config_json JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_endpoints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  endpoint_key TEXT UNIQUE NOT NULL,
  provider_key TEXT NOT NULL REFERENCES model_providers(provider_key),
  model_key TEXT NOT NULL REFERENCES model_registry(model_key),
  endpoint_type TEXT NOT NULL CHECK (endpoint_type IN ('embedding','reranker','llm','ocr','parser')),
  base_url TEXT NOT NULL,
  auth_secret_ref TEXT,
  region TEXT,
  max_security_level INT NOT NULL DEFAULT 3,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  health_status TEXT NOT NULL DEFAULT 'unknown',
  p95_latency_ms INT,
  last_health_check_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingestion_plan_previews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  business_instance_id UUID NOT NULL,
  knowledge_base_id UUID NOT NULL,
  requested_mode_key TEXT NOT NULL,
  selected_profile_key TEXT,
  estimate_json JSONB NOT NULL,
  warnings_json JSONB NOT NULL DEFAULT '[]',
  created_by UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_eval_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  business_instance_id UUID NOT NULL,
  knowledge_base_id UUID NOT NULL,
  mode_key TEXT NOT NULL,
  golden_set_id UUID,
  candidate_profiles TEXT[] NOT NULL,
  metrics_json JSONB NOT NULL,
  winner_profile_key TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE golden_queries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  business_instance_id UUID NOT NULL,
  knowledge_base_id UUID NOT NULL,
  golden_set_id UUID NOT NULL,
  query TEXT NOT NULL,
  expected_document_ids UUID[] NOT NULL DEFAULT '{}',
  expected_chunk_ids UUID[] NOT NULL DEFAULT '{}',
  expected_answer_summary TEXT,
  security_level INT NOT NULL DEFAULT 1,
  metadata_json JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE finetune_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  business_instance_id UUID NOT NULL,
  base_model_key TEXT NOT NULL REFERENCES model_registry(model_key),
  training_dataset_uri TEXT NOT NULL,
  validation_dataset_uri TEXT NOT NULL,
  training_method TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  output_model_uri TEXT,
  eval_before_json JSONB,
  eval_after_json JSONB,
  approved_for_production BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 11. Your PDF-to-Markdown feature stub

Treat your existing PDF process as a provider:

```txt
provider_key: user_pdf_to_markdown
parser_key: trusted_pdf_markdown_bundle_v1
mode_key: pdf_markdown_external_v1
status: production_ready_external_dependency
```

Expected bundle format:

```json
{
  "sourcePdf": {
    "filename": "original.pdf",
    "sha256": "...",
    "pageCount": 842
  },
  "markdown": {
    "uri": "s3://bucket/doc.md",
    "sha256": "..."
  },
  "assets": [
    {
      "type": "image",
      "page": 12,
      "uri": "s3://bucket/assets/page-012-figure-001.png",
      "caption": "optional"
    }
  ],
  "pageMap": [
    {
      "page": 1,
      "markdownStartOffset": 0,
      "markdownEndOffset": 9132,
      "headings": ["Introduction"]
    }
  ],
  "quality": {
    "tablesExtracted": true,
    "imagesExtracted": true,
    "ocrUsed": false,
    "confidence": 0.94
  }
}
```

The ingestion system should not care how the Markdown was produced. It only needs stable Markdown, source-page mapping, asset references, extraction-quality metadata, and hashes.

Recommended chunking for this mode:

```txt
chunk by heading
preserve page ranges
include parent heading path
include previous/next chunk pointers
include table captions and table IDs
include image/figure references as retrievable metadata
create a document-level summary vector
create a section-level summary vector
create normal chunk vectors
```

---

## 12. PDF research track

Keep your existing pipeline as the default, but continue benchmarking these options for specific PDF types:

```txt
Mistral OCR / OCR 3
  Good candidate for scanned PDFs, tables, equations, and ordered markdown-style extraction.

Docling / Granite-Docling
  Good candidate for open-source/local document understanding and structured exports.

Marker
  Good candidate for open-source conversion to Markdown/JSON/chunks/HTML with GPU/CPU/MPS support.

PyMuPDF4LLM
  Good candidate for lightweight, no-GPU Markdown/JSON/TXT extraction and local pipelines.

Jina Embeddings v4 direct PDF / visual document mode
  Good candidate for visually rich PDFs, charts, tables, and mixed visual/text retrieval.

Cohere Embed v4 multimodal
  Good candidate for mixed image/text enterprise documents.

Voyage multimodal / contextual embeddings
  Good candidate for long-document and multimodal retrieval bakeoffs.
```

Production rule: do not replace your current PDF pipeline unless the challenger beats it on a golden set for that customer's PDF style.

---

## 13. Serverless GPU model endpoint design

A RunPod-style endpoint should be an optional model backend, not the whole retrieval platform.

```txt
SVS API / workers
  -> svs-model-gateway
  -> provider adapter
  -> RunPod serverless endpoint
  -> TEI / Infinity / custom Python handler
  -> embedding or rerank response
```

### 13.1 RunPod worker contract

Request:

```json
{
  "operation": "embeddings",
  "model": "Qwen/Qwen3-Embedding-4B",
  "input": ["text 1", "text 2"],
  "options": {
    "normalize": true,
    "dimensions": null,
    "inputType": "document"
  }
}
```

Response:

```json
{
  "model": "Qwen/Qwen3-Embedding-4B",
  "data": [
    {"index": 0, "embedding": [0.01, -0.02]},
    {"index": 1, "embedding": [0.03, 0.04]}
  ],
  "usage": {
    "items": 2,
    "estimatedTokens": 412
  }
}
```

### 13.2 Recommended server runtimes

```txt
Hugging Face Text Embeddings Inference
  Best for high-performance open embedding models with Docker deployment.

Infinity
  Best for one server that can do embeddings, reranking, CLIP, CLAP, and ColPali-like models.

Custom handler
  Best when the model requires special prompts, pooling, task adapters, multi-vector output, or nonstandard postprocessing.
```

### 13.3 Network volume strategy

Use network volumes for model cache only. Do not use a shared writable model volume as a coordination database. Preload models into `/runpod-volume/models`, mount read-only in the worker when possible, and rebuild a new volume for major model upgrades.

---

## 14. Fine-tuning loop

Do not start with fine-tuning. Start with model bakeoffs and routing.

Fine-tune only when:

```txt
1. Off-the-shelf models fail on a stable, measured eval.
2. The failure is semantic/domain-specific, not parser/chunker/metadata related.
3. You have enough positive pairs and hard negatives.
4. A cheaper reranker/chunker change does not fix the issue.
5. The fine-tuned model wins on validation and does not regress security/citation behavior.
```

Training data sources:

```txt
user query -> clicked source chunk
user query -> cited answer chunk
support ticket -> resolution document
question -> known policy clause
code error -> fixing commit / doc / source file
synthetic question -> human-approved source chunk
failed retrieval -> corrected chunk
```

Dataset shape:

```json
{
  "query": "How do I rotate API keys for project users?",
  "positiveChunkId": "chk_123",
  "hardNegativeChunkIds": ["chk_456", "chk_789"],
  "mode": "markdown_docs_v1",
  "securityLevel": 2,
  "metadata": {
    "source": "human_corrected",
    "businessInstanceId": "biz_expert_ai_services"
  }
}
```

Recommended eval metrics:

```txt
Recall@5
Recall@10
MRR
nDCG@10
citation hit rate
answer faithfulness
latency p95
cost per 1k queries
security false-positive retrieval count
security false-negative retrieval count
```

Deployment gate:

```txt
candidate model must beat baseline on target metric
candidate must not reduce citation hit rate
candidate must not retrieve unauthorized chunks
candidate must pass latency/cost ceiling
candidate must have rollback plan
```

---

## 15. Multi-vector and hybrid retrieval support

Some modern models produce or support more than one retrieval representation:

```txt
dense single vector
sparse token weights
late-interaction / multi-vector representations
image vectors
section summary vectors
document summary vectors
```

Update the index schema so one chunk can have multiple representations:

```txt
chunk_id
  embedding_set:
    - dense_default
    - sparse_default
    - multivector_late_interaction
    - summary_vector
    - title_vector
    - image_vector
```

Qdrant/OpenSearch routing:

```txt
Qdrant: dense vectors, named vectors, payload filters
OpenSearch: BM25, ngrams, exact terms, field-aware phrase search
Optional: late-interaction store for ColBERT/ColPali-style retrieval
Fusion: RRF or weighted fusion
Rerank: cross-encoder or provider reranker
```

---

## 16. Instance-level settings

Every business/user instance should be able to override model policies without forking the product.

```yaml
instanceId: inst_expert_ai_services_prod
vectorization:
  allowedModes:
    - markdown_docs_v1
    - pdf_markdown_external_v1
    - code_repo_v1
  defaultMode: markdown_docs_v1

models:
  externalProvidersAllowed: true
  externalProvidersDeniedAboveSecurityLevel: 3
  allowedProviders:
    - openai
    - voyage
    - runpod_serverless
  preferredEmbeddingProfiles:
    markdown_docs_v1: openai_text_embedding_3_small_1536
    pdf_markdown_external_v1: voyage_context_3_docs_default
    code_repo_v1: voyage_code_3
  fallbackPrivateEmbeddingProfile: bge_m3_local

runpod:
  endpoints:
    embeddings:
      - qwen3-embedding-4b-private-us
    rerankers:
      - qwen3-reranker-4b-private-us

evals:
  requireBakeoffBeforeModelChange: true
  minGoldenQueriesForAutoPromotion: 100
```

---

## 17. Cost control

Add cost estimation before ingestion:

```txt
estimated_pages
estimated_markdown_chars
estimated_tokens_by_candidate_model
estimated_chunks
estimated_embedding_cost
estimated_vector_storage
estimated_sparse_index_storage
estimated_rerank_cost_per_query
estimated_monthly_query_cost
```

Use content-hash caching:

```txt
embedding_cache_key = sha256(
  normalized_chunk_text
  + embedding_model_key
  + dimensions
  + chunker_version
  + metadata_policy_version
)
```

Never re-embed unchanged chunks when only document-level metadata changes, unless the metadata is injected into the embedding text.

---

## 18. Security policy for model routing

Each model route must enforce:

```txt
instance provider allowlist
security level limit
data residency limit
tenant API key isolation
no raw secrets in model payloads
PII redaction rules when required
provider-specific data processing approval
full audit event for external calls
```

Security-sensitive examples:

```txt
security level 0-2: external APIs allowed if instance policy allows
security level 3: external APIs allowed only with explicit profile approval
security level 4-5: local/private endpoint only by default
```

The vectorization mode should never override security policy.

---

## 19. Frontend UX

The frontend should expose three layers.

### Simple mode

```txt
What are you uploading?
[ Markdown docs ] [ PDF converted to Markdown ] [ Code repo ] [ Tables ] [ Auto-detect ]
```

### Advanced mode

```txt
Quality vs cost: Balanced / Cheapest / Highest quality / Private local only
Security level: Public / Internal / Confidential / Regulated
Provider preference: Auto / OpenAI / Voyage / Local / RunPod / No external APIs
```

### Expert mode

```txt
Parser profile
Chunker profile
Embedding profile
Reranker profile
Sparse profile
Eval profile
Dimensions
Overlap
Top-K
Fusion strategy
Rerank top-N
```

Always show an ingestion preview before committing:

```txt
Selected profile
Estimated chunks
Estimated tokens
Estimated cost
Estimated storage
Security warnings
Provider warnings
```

---

## 20. Acceptance tests

```txt
1. Markdown mode preserves heading hierarchy and citations.
2. PDF Markdown external mode accepts a bundle manifest and preserves page references.
3. Code mode chunks by symbols, not arbitrary token windows.
4. High-security content never routes to external embedding APIs.
5. Same document + same profile does not duplicate embeddings.
6. Different model/dimension/profile creates a separate embedding version.
7. Model bakeoff produces comparable metrics across candidates.
8. Failed model endpoint falls back according to policy.
9. RunPod endpoint health failures disable routing automatically.
10. Fine-tuned model cannot promote without eval improvement and approval.
```

---

## 21. Initial model recommendation matrix

| Mode | Default | Quality candidate | Private/local candidate | Notes |
|---|---|---|---|---|
| Markdown docs | OpenAI `text-embedding-3-small` | Voyage `voyage-4` / `voyage-context-3` | BGE-M3 / Qwen3 0.6B | Start cheap, bake off per customer. |
| Large PDF -> Markdown | Voyage contextual | OpenAI large / Jina v4 | Qwen3 4B / BGE-M3 | Your PDF->MD pipeline is default parser. |
| Raw/visual PDFs | Research mode | Cohere Embed v4 / Jina v4 / Voyage multimodal | Jina v4 self-hosted if feasible | Use only after eval beats PDF->MD. |
| Code repos | Voyage Code | Qwen3 Embedding + Qwen3 Reranker | Qwen3 local | Add symbol graph + exact search. |
| Tables/JSON | OpenAI small | Cohere/Jina for mixed docs | BGE-M3 | Prefer schema-aware records plus exact filters. |
| Logs/errors | Sparse first | BGE-M3 hybrid | BGE-M3 | Exact terms often matter more than vectors. |
| Confidential docs | Instance policy | Provider allowlist only | BGE-M3/Qwen3/RunPod | Security policy wins over quality. |

---

## 22. Source notes for current research

- OpenAI embeddings expose vectors that can be stored externally; `text-embedding-3-small` defaults to 1536 dimensions and `text-embedding-3-large` to 3072, with dimension reduction available.
- Anthropic’s documentation says Anthropic does not offer its own embedding model and points to Voyage AI as one embedding provider option.
- Voyage AI currently offers general, contextual, code, multimodal, and reranker models.
- Cohere Embed v4 supports multimodal embeddings and Matryoshka dimensions.
- Qwen3 Embedding/Reranker models were released as open models and include embedding and reranking variants.
- BGE-M3 supports dense, sparse, and multi-vector retrieval modes, multilingual retrieval, and up to 8192-token inputs.
- Hugging Face Text Embeddings Inference and Infinity are strong candidates for self-hosted embedding/reranking servers.
- RunPod serverless endpoints are suitable for bursty GPU model inference; network volumes can reduce model download/cold start pain, but shared-write volume behavior must be handled carefully.
- PDF research candidates include Mistral OCR/OCR 3, Docling/Granite-Docling, Marker, PyMuPDF4LLM, Jina Embeddings v4, Cohere Embed v4, and Voyage multimodal/contextual models.
