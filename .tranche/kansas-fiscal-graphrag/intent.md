# Kansas fiscal GraphRAG implementation planning

User intent: prepare the StateCivics ExAIS cell for an OVH VPS deployment and think through the fiscal GraphRAG implementation. This tranche covers fiscal GraphRAG only; deployment is separate ongoing work. Produce a build-ready plan, not implementation or live activation.

Canonical goal: Enable explicitly selected, citation-preserving fiscal relationship expansion for the Kansas fiscal document store using reviewed, published StateCivics canonical evidence, while preserving ordinary document search and existing court, Topeka, and Grant behavior.

Known context from parent inspection on 2026-09-10, ExAIS bb7e575:
- Fiscal document ingestion, embeddings, source revision provenance, and persisted Marker Markdown handoff exist (WAVE-129; embedding batching fix WAVE-131).
- Fiscal GraphRAG is not implemented or activated. The fiscal source package declares graph.enabled=false.
- WAVE-130 is an unfinished fiscal artifact contract proposal. Extend and reconcile it rather than pretending its work is done or creating competing contracts.
- Existing shared graph profile allowlist only registers Grant. API _cell_graph_profile_or_503 is Grant-gated. Existing court and Topeka graph routing remains separate and already proven.
- Graph expansion is PostgreSQL-backed. Reuse the graph loader, ACL/citation checks, search-lens registry, and cell profile binding; do not introduce a new graph database or duplicate engine.
- StateCivics owns fiscal entity resolution, amounts, publication/review decisions, custody, and derivation runs. ExAIS consumes cited projections. Never infer canonical joins from embeddings or ingest all transaction rows as narrative documents.
- WAVE-130 reports KS-601 review as an upstream blocker; current upstream status must be checked in enrichment, not assumed unchanged.
- The document source package still has a placeholder store ID; resolve actual runtime identity before activation rather than committing a guessed ID.
- Separate safe fixture implementation/evaluation from real-corpus publication/activation gates. No unreviewed fiscal relationships should become public or be described as ready.
- Consider a small curated projection below current loader bounds (10,000 nodes/20,000 edges), one derivation run per artifact, exact source spans/citations, lifecycle withdrawal, version changes, ACL isolation, and bounded one-hop expansion. Larger traversal and unrestricted graph ingestion are out of scope.

ExAIS repo: /Users/mfrieson/Developer/exais-vector-store-ovh
Upstream StateCivics read-only repo: /Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai
Relevant suspected files: tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md, docs/CELL_GRAPH_PROFILES.md, packages/svs_common/svs_common/{cell_graph,grant_graph,kscourts_graphrag,search_lenses,retrieval,expert_profiles,schemas}.py, apps/api/svs_api/main.py, scripts/release/kansas-fiscal-document-ingest.py, instances/ks-state-civics/vector-stores/kansas-fiscal-documents/.

Plan a bounded 4-6 ticket stack with executable acceptance and explicit upstream dependencies. Keep source artifacts, verified refs, shared ownership, and an addressable index. Use the ticket-tranche skill's three sequential waves and gates. No mutations to upstream, running cells, or production from planning agents.

## Additional user-directed grounding, 2026-09-10

The user asked to read the overall plans in `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/statecivics-civic-impact-intelligence`. The root agent read all fifteen numbered specification chapters, the SB 125 examples, contract overview, and supersession note, then checked current StateCivics tickets and fiscal implementation notes. See `project-alignment.md` for the resulting constraints and source precedence. This additional context preserves the canonical goal; it clarifies the product chain that the retrieval projection must serve.
