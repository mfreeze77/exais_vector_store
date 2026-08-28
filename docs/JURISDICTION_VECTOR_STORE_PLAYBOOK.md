# Jurisdiction Vector Store Playbook

This is the repeatable pattern for every new jurisdiction, customer instance,
and vector store we add to ExAIS.

The goal is not just to search text. The goal is to preserve legal source
structure, source provenance, citation URLs, update paths, and optional graph
relationships so a caller agent can search the store today and a legislative
workbench can reuse the same corpus later.

## Core Decisions

### 1. Caller agents only call ExAIS

The customer-facing boundary is the ExAIS API over HTTPS with scoped bearer
keys. Caller agents must not call Qdrant, Postgres, MinIO, RunPod Marker,
embedding providers, or model-gateway directly.

For a customer instance, the caller receives:

```text
EXAIS_API_BASE=https://api.<customer-domain>
EXAIS_VECTOR_STORE_ID=vs_...
EXAIS_BEARER_KEY=<one-time-created caller key>
```

Everything behind that API is implementation detail.

### 2. Source packages are mandatory

Every vector store loaded from scraped, downloaded, or externally collected
data must have an instance-owned source package under:

```text
instances/{instance_slug}/vector-stores/{vector_store_slug}/sources/{source_slug}/
```

The source package must record how to reproduce the store:

- source identity and jurisdiction identity;
- acquisition method and connector entrypoint;
- source manifests and checksums;
- raw capture or artifact storage pointers;
- extracted Markdown/HTML storage pointers;
- citation URL map;
- graph build/load/eval commands when graph is enabled;
- last successful proof;
- update policy for added, changed, unchanged, and removed source records.

Large raw data does not need to be committed to Git, but the package must
contain stable pointers, checksums, counts, and commands that make the data
recoverable.

### 3. Vectorization is downstream of source quality

Do not vectorize until the source artifact quality gate passes.

The standard sequence is:

```text
capture -> clean/extract -> source package -> citation map -> graph artifact
-> artifact quality gate -> vector ingest -> graph API load -> lens search eval
-> caller docs -> VPS/public proof
```

PDF and OCR processing belongs to the configured remote processor, currently
the RunPod Marker path. The customer VPS should not be sized around local PDF
conversion or local embedding model execution.

Embeddings are created by the configured external provider, such as Voyage or
OpenAI. The provider, model, and dimensions are part of the vector-store
compatibility contract and must be pinned in store metadata.

### 4. GraphRAG is a lens, not a replacement

Semantic search remains the default. GraphRAG adds opt-in or inferred expansion
for legal relationships that are already present in the loaded graph artifact.

Each graph-capable store should expose lenses through:

```http
GET /v1/vector_stores/{vector_store_id}/search_lenses
```

Caller agents should use `status="available"` lenses only. They should not
pretend graph search ran when a lens is `planned`, `disabled`, or `empty`.

### 5. Citation URLs are result-aware

The primary result citation URL must identify the document being returned.

For example:

- if the returned result is a codified section, cite the section URL;
- if the returned result is an ordinance PDF extraction, cite the official PDF
  URL;
- if the graph relationship is "ordinance PDF amends section," preserve both
  relationship URLs in graph metadata, but display the returned document URL as
  the result citation.

Graph metadata should expose:

```text
citation_url               URL for the returned result
relationship_source_url    URL for the edge source
relationship_target_url    URL for the edge target
relation_type              relationship type
seed_node_id               graph seed used for expansion
related_node_id            graph node matched to the returned result
graph_distance             hop count, when applicable
```

This is a legal trust invariant. It is not UI decoration.

## Required Instance Layout

Use this shape for every customer instance:

```text
instances/{instance_slug}/
  instance.yaml
  vector-stores/
    {vector_store_slug}/
      store.yaml
      README.md
      sources/
        {source_slug}/
          source.yaml
          source.lock.json
          ingest-plan.yaml
          eval-plan.yaml
          manifest.schema.json
          seed/
            README.md
            manifests/
            raw/
            extracted/
            graph/
```

The exact `seed/` contents can point to object storage or release artifacts
instead of containing large files directly. What matters is that the source
package owns the identity, commands, checksums, and proof.

## Jurisdiction Schema Template

Each new jurisdiction needs a schema adapter. Start by mapping the publisher's
structure into this shape.

| Concept | Example Node Type | Stable Key | Citation URL |
| --- | --- | --- | --- |
| Jurisdiction | `jurisdiction` | `ks-topeka` | official city or county URL |
| Code book | `code` | `tmc` | code root URL |
| Title | `title` | `14` | title URL |
| Chapter | `chapter` | `14.40` | chapter URL |
| Article or division | `article`, `division` | publisher citation | article/division URL |
| Section | `section` | `14.40.055` | section URL |
| Definition | `definition` | section plus normalized term | section URL |
| Ordinance | `ordinance` | ordinance number | ordinance page or PDF URL |
| Ordinance PDF | `ordinance_pdf` | ordinance number | official PDF URL |

Preferred graph edge types:

| Edge Type | Meaning |
| --- | --- |
| `CONTAINS` | hierarchy: code -> title -> chapter -> article -> section |
| `REFERENCES` | one section cites another section or code location |
| `DEFINES` | a section defines a legal term |
| `HAS_ORDINANCE_HISTORY` | a section lists ordinance/adoption history |
| `ORDINANCE_AMENDS_SECTION` | an ordinance PDF appears to amend or affect a section |
| `SAME_ORDINANCE` | multiple sections or PDFs share an ordinance number |

Only claim an edge type when the extractor can preserve evidence and source
URLs for it.

## Quality Gates

Each new source package must pass the narrowest applicable gate before moving
to the next stage.

### Capture gate

- Required URLs are accounted for.
- Challenge pages, login pages, blank shells, and partial pages fail closed.
- Captures include source URL, retrieved timestamp, status code when available,
  content hash, and acquisition adapter version.
- Resume behavior is idempotent.

### Extraction gate

- Every extracted document has stable source identity.
- Every searchable document has a public or official citation URL.
- Markdown/HTML preserves enough headings and structure for citations and
  future workbench projections.
- Parser emits zero critical section-text or citation-map issues.

### Graph gate

- Graph nodes and edges have stable IDs.
- Dangling edges must be zero.
- Edge counts and node counts are recorded by type.
- Edge provenance records extraction method and evidence when available.
- Graph artifact eval passes before graph API load.

### Ingestion gate

- Ingestion uses the ExAIS API path only.
- Direct writes to Postgres, Qdrant, MinIO, or graph tables are not allowed for
  source packages.
- Vector store metadata pins embedding provider, model, dimensions, corpus, and
  source collection.
- Source package validation passes:

```powershell
python scripts\release\validate-instance-source-packages.py --instance <instance_slug> --production
```

### Search gate

- `GET /v1/vector_stores/{id}/search_lenses` reports expected lens status.
- Default semantic search still works without a graph lens.
- Each explicit graph lens returns `applied=true` when expected.
- Result citations point at the returned document URL.
- Graph metadata preserves source and target relationship URLs.
- Recall eval includes direct questions and relationship questions.

### VPS/public gate

Local Docker proof is not public proof. Before go-live, rerun health, lens
discovery, graph load, search smoke, recall eval, API-key lifecycle proof, TLS,
firewall, and backup/restore proof against the production HTTPS endpoint.

On Windows Docker Desktop, host port forwarding may fail even when the Compose
network is healthy. Use Docker-network proof for local cell behavior and keep
host-loopback failures separate from VPS readiness.

## Topeka Baseline

The Topeka municipal-code store is the first full worked example of this
pattern.

Current local proof from 2026-08-28:

- vector store: `vs_d4185d1004604f08a55299fa`;
- documents: `3,066`;
- active chunks: `6,153`;
- codified code documents: `2,702`;
- ordinance PDF Markdown documents: `364`;
- graph nodes: `4,969`;
- graph edges: `10,167`;
- graph API load: `loaded_nodes=4969`, `loaded_edges=10167`,
  `dangling_edges=0`;
- available lenses: `municipal_code_structure`,
  `municipal_code_cross_reference`, `municipal_code_history`.

The important reusable lessons from Topeka:

- hierarchy can come from a URL manifest even when container pages are hard to
  fetch;
- official PDF extractions should stay attached to the same vector store as the
  codified sections when they provide amendment history;
- Decodo or another approved acquisition path is an acquisition adapter, not a
  vectorization path;
- ordinance PDFs, extracted Markdown, citation maps, graph artifacts, and proof
  files are part of the source package;
- GraphRAG must expose caveats per lens, especially when it is not a full legal
  citator.

## New Jurisdiction Checklist

Use this checklist before starting another jurisdiction.

- [ ] Define customer instance slug and vector store slug.
- [ ] Decide whether this is a new VPS cell or another vector store inside an
      existing customer cell.
- [ ] Create `store.yaml` with provider/model/dimension/corpus metadata.
- [ ] Create at least one source package under `sources/`.
- [ ] Define acquisition adapter and allowed source locations.
- [ ] Preserve raw captures or stable object-storage pointers.
- [ ] Preserve extracted Markdown/HTML where the caller or workbench may need
      displayable source text.
- [ ] Emit `citation-url-map.jsonl`.
- [ ] Emit graph `nodes.jsonl` and `edges.jsonl` when relationships exist.
- [ ] Run artifact quality before vectorization.
- [ ] Ingest through ExAIS API.
- [ ] Load graph through `POST /v1/vector_stores/{id}/graph`.
- [ ] Verify `/search_lenses`.
- [ ] Verify default semantic search.
- [ ] Verify every explicit graph lens.
- [ ] Verify result citation URLs and graph relationship URLs.
- [ ] Record all counts, digests, commands, and proof paths in `source.lock.json`
      and `store.yaml`.
- [ ] Only then wire caller tools or public routes.

## Related Docs

- [Caller Agent Integration](CALLER_AGENT_INTEGRATION.md)
- [Topeka Municipal Code Seeding Spec](TOPEKA_MUNICIPAL_CODE_SEEDING_SPEC.md)
- [KS State Civics Graph Citation Backlinks](KS_STATE_CIVICS_GRAPH_CITATION_BACKLINKS.md)
- [API Reference](API.md)
- [WAVE-117 Instance Vector-Store Source Package Contract](../tickets/WAVE-117-instance-vector-store-source-package-contract.md)
- [WAVE-121 KS Civics VPS Go-Live Handoff](../tickets/WAVE-121-KS-civics-vps-go-live-handoff.md)
- [WAVE-122 Topeka Municipal Code GraphRAG API Handler](../tickets/WAVE-122-topeka-municipal-code-graphrag-api-handler.md)
