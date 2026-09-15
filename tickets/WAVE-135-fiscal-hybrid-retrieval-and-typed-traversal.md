# WAVE-135: Combine exact and semantic retrieval with validated typed traversal

> **Civic Impact work paused by owner — 2026-09-14.**
> [Current delivery, pending CI and resume order](../runbooks/civic-impact-pause.md) supersede older dispatch instructions. Historical proof and unmet acceptance criteria remain.

Status: proposed. Parent: WAVE-132 (reopened). Filed 2026-09-10.

## Summary

Answer scoped law-to-money questions through exact identifiers and semantic candidates that resolve to upstream canonical facts and supported typed paths.

## Background

Current fiscal expansion starts from chunks and traverses one hop. That does not provide the complete typed law-to-account path, structured citations, or a provider-free exact/lexical baseline. Zero embedding weight alone still invokes provider-dependent work.

## Scope

- Add explicit fiscal mode enum in existing SearchRequest/native fiscal options: exact_lexical, document_semantic, entity_semantic, hybrid, hybrid_graph. Keep ordinary default behavior for other domains. Exact mode branches BEFORE profile discovery/_query_embedding and bypasses _rerank_chunks/model gateway entirely; use exact canonical identifiers plus PostgreSQL lexical retrieval. Zero fusion weight is not sufficient. Outage fallback records degradation and reruns that same branch without a second embedding/reranker attempt.
- Exact canonical lookup matches bill/chapter/KSA/account/fund/agency IDs with requested FY/agency/code-system and reviewed aliases. Existing symbol boost only reranks existing chunks, so implement canonical lookup inside RetrievalService using indexed/scoped projected fields. Semantic modes retrieve document or compact entity candidates separately, hybrid uses existing local rank fusion; no provider or parallel retriever is added.
- Hydrate all candidates through WAVE-134 mandatory eligibility and upstream canonical revisions before traversal. Carry explicit FY/as-of/snapshot, unresolved or ambiguous identities and source gaps. Similarity may select seeds but cannot add edges or resolve account identity.
- Extend the fiscal handler only to bounded directed traversal with an initial maximum of six edges, ten seeds, 200 visited/candidate nodes and explicit result cap; preserve timeout/truncation metadata and refuse to label a partial path complete. Six permits provision/action/derivation/fact/account/agency-or-fund plus evidence attachment as typed data; use precise allowlisted path shapes, visited-set cycle protection and per-edge provenance. Retain other handlers at one hop. Graph distance alone is never sufficient.
- Traverse canonical provision -> action -> FY account -> agency/fund and source evidence, preserving joint derivation run context and supported correspondence. Source/record/edge eligibility is independently rechecked. No implied Cartesian action/fact links, vector joins, unresolved History edges or section/code equality edges.
- Native fiscal answer branch renders exact canonical amounts and KS-600 derived authority facts, action/stage/metric/evidence class and requested snapshot. It validates input/output/source hashes but does not invent a second arithmetic policy or sum snippets. Unsupported numeric claims return explicit gaps/unreconciled state; positive supported paths must produce useful cited answers.
- Native result/context/answer fields include typed FiscalEntityResult/FiscalEvidenceCitation; document hits remain real ChunkRecord/ContextCitation. Structured CSV evidence exposes source/record/column locators and official URL with no fake chunk/file IDs. File-only compatibility endpoints return actual document support or explicit unsupported typed capability; never coerce structured rows into fake file annotations. Revalidate citations after any external await.
- Use each explicitly allowed store profile for query encoding; current multi-profile search is not federation. This milestone runs in the Kansas fiscal store. Any later cross-store canonical-ID traversal needs explicit allowlist plus compatible source snapshot; no automatic expansion, raw-score comparisons, equal-dimension requirement, free-form SQL/Cypher or global policy change.

## Out Of Scope

- New canonical arithmetic/account resolver in ExAIS
- Semantic similarity as graph proof
- Totals from partial retrieval coverage
- Generated unrestricted queries
- Automatic cross-store traversal
- Using held-out labels in development

## Prior Art

Verified during ticket enrichment on 2026-09-10. Read these existing owners before implementing. New files and signatures below are proposed work.

- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService.search`. Single pipeline; query embedding happens before fusion weights today.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService._query_embedding`. Per-profile query encoding/cache uses input_type=query.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService._postgres_sparse_search`. Reuse PostgreSQL lexical document retrieval.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService._apply_exact_symbol_boost`. Boosts existing chunks; does not guarantee canonical exact-ID recall.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService._rerank_chunks`. Must bypass remote reranking for exact baseline/outage fallback.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `reciprocal_rank_fusion`. Existing local fusion; no new Qdrant hybrid API assumption.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService.answer`. Existing extractive chunk answer; add native typed fiscal branch.
- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `expand_fiscal_graph`. Current one-hop chunk expansion is not full typed law-money traversal.
- **Code** — [packages/svs_common/svs_common/cell_graph.py](../packages/svs_common/svs_common/cell_graph.py): `CellGraphProfile`. max_hops is Literal[1]; fiscal-specific bounded extension required.
- **Code** — [packages/svs_common/svs_common/schemas.py](../packages/svs_common/svs_common/schemas.py): `SearchResponse`. Chunk-only current results; consume separate entity/evidence types.
- **Code** — [apps/api/svs_api/main.py](../apps/api/svs_api/main.py): `_openai_vector_store_search_page`. Single-store graph expansion after document search, not federation.
- **Code** — [packages/svs_common/svs_common/search_lenses.py](../packages/svs_common/svs_common/search_lenses.py): `search_lens_relation_types`. Existing allowlisted relation selection.

## Current Evidence

Current fiscal expansion starts from chunks and traverses one hop. That does not provide the complete typed law-to-account path, structured citations, or a provider-free exact/lexical baseline. Zero embedding weight alone still invokes provider-dependent work.

The Prior Art anchors distinguish existing code from the missing behavior. Source inventory and earlier synthetic test passes do not establish real-source product acceptance.

## Implementation Notes

Follow [the agreed law-and-money handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md). Preserve existing canonical owners, native contract shapes and record-level evidence requirements.

Use the shared-owner map in [build-contract.json](../.tranche/statecivics-semantic-graph/aligned/build-contract.json) and look up affected files/symbols in [stack.index.json](../.tranche/statecivics-semantic-graph/aligned/stack.index.json). These are local planning artifacts; their signatures describe future work unless marked existing. Runtime must not depend on worktree paths or these planning files.

## Deliverables

- [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py) — Own five modes/exact canonical lookup/fusion/bypass/native fiscal answer. Shared file owner: WAVE-135. Edit sequence: WAVE-134 → WAVE-135 → WAVE-136.
- [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py) — Bounded directed path traversal using WAVE-133 relations and WAVE-134 eligibility. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [packages/svs_common/svs_common/schemas.py](../packages/svs_common/svs_common/schemas.py) — Wire native fiscal response/options using WAVE-133 single-owner types. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-135.
- [packages/svs_common/svs_common/cell_graph.py](../packages/svs_common/svs_common/cell_graph.py) — Fiscal-only bounded multihop configuration, preserve other handlers. Shared file owner: WAVE-135. Edit sequence: WAVE-135.
- [packages/svs_common/svs_common/search_lenses.py](../packages/svs_common/svs_common/search_lenses.py) — Explicit fiscal query mode/snapshot inputs. Shared file owner: WAVE-135. Edit sequence: WAVE-135.
- [apps/api/svs_api/main.py](../apps/api/svs_api/main.py) — Native typed fiscal search/context/answer and truthful compatibility handling. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [tests/test_fiscal_graph.py](../tests/test_fiscal_graph.py) — Multistep direction/provenance/joint-lineage guards. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-135.
- [tests/test_fiscal_graph_routes.py](../tests/test_fiscal_graph_routes.py) — Five modes, exact bypass and scope/citation wiring. Shared file owner: WAVE-134. Edit sequence: WAVE-134 → WAVE-135.
- [tests/test_fiscal_graph_postgres.py](../tests/test_fiscal_graph_postgres.py) — Exact/entity canonical hydration and full typed path proof. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [tickets/WAVE-135-fiscal-hybrid-retrieval-and-typed-traversal.md](WAVE-135-fiscal-hybrid-retrieval-and-typed-traversal.md) — NEW: single pipeline five-mode retrieval follow-up. Shared file owner: WAVE-135. Edit sequence: WAVE-135.
- `tests/test_fiscal_hybrid_retrieval.py` (planned new file) — NEW: provider spies, mode separation, answer/citation correctness and outage fallback. Shared file owner: WAVE-135. Edit sequence: WAVE-135 → WAVE-136.

Expected integrated output: WAVE-135 exposes exact_lexical, document_semantic, entity_semantic, hybrid and hybrid_graph through the existing retrieval/answer pipeline. Exact baseline/outage fallback make zero embedding/reranker calls. Canonical scoped hydration precedes bounded directed source-backed traversal and exact upstream-derived numeric answers with native legal/structured citations and explicit gaps. Tests prove mode separation, profile-aware encoding, exact-ID preservation, useful positive paths, provenance/joint-lineage limits, citation correctness and no automatic cross-store expansion or second fiscal arithmetic policy.

## Acceptance Criteria

- Use existing retrieval/ranking seams for exact bill/chapter/KSA/agency/fund/account identifiers and natural-language aliases. Exact/lexical baseline and outage fallback bypass both embedding and remote reranking calls. Evaluate existing configured providers in ExAIS scope; add no provider or parallel retriever.
- Semantic document and compact entity-description matches only propose candidates. Validate canonical identity, source/audience eligibility, requested FY/as-of, agency/fund/account scope, exact structured values and legal action role before bounded allowlisted typed traversal and citation hydration.
- Traverse the upstream-validated enacted provision to appropriation action to fiscal-year account to agency/fund path and attached evidence with explicit source/snapshot/run provenance. Preserve joint derivation lineage and do not assert one-to-one action/fact correspondence unless explicitly supported. Do not create edges from semantic similarity, statute History references, matching section numbers or account-code normalization.
- Hydrate numeric answers from canonical fiscal records and KS-600 reproducible derivations/snapshot policy. Keep action_type, stage, metric and evidence_class distinct. Never sum snippets, count linked action/fact amounts twice, combine incompatible balances/flows/transfer legs, infer zero from incomplete coverage, or classify upstream facts independently.
- Cite exact legal spans or structured record evidence appropriate to each claim, disclose requested period and source/graph snapshot, and distinguish authority from actual expenditure. Return supported positive paths; disclose ambiguity/gaps and decline unsupported arithmetic rather than treating every unknown as zero or passing by refusing everything.
- Query each store using its configured embedding profile. Federate only explicitly allowed canonical-ID/snapshot paths; no automatic cross-store expansion, equal-dimension requirement, raw-score comparison across profiles, free-form SQL/Cypher or global policy change.
- Focused tests cover provider/reranker bypass, exact-code preservation, natural-language candidate recall, separate retrieval modes, structured validation, typed path direction/provenance, joint-derivation limits, source/ACL isolation, source-backed numeric/citation correctness, and explicit ambiguity/no-path behavior.

## Dependencies

- Canonical prerequisite: KS-651
- Canonical prerequisite: WAVE-133
- Canonical prerequisite: WAVE-134
- KS-651 coverage, labels/denominators and thresholds must be frozen before tuning. General retrieval implementation may be prepared without exposure to reviewer-controlled held-out answer labels.

Dependencies apply to the specific contracts, evidence and eligible records consumed here. Do not wait for unrelated payments/forecasts/outcomes or the full K.S.A. harvest. KS-613 keeps its existing scope; KS-651 owns the separate generalization benchmark.

## Verification

Run after implementation in the required test environment; these commands were not executed during ticket drafting.

```sh
pytest -q tests/test_fiscal_hybrid_retrieval.py tests/test_fiscal_graph.py tests/test_fiscal_graph_routes.py tests/test_fiscal_graph_postgres.py
```

Five separate modes, zero provider/reranker calls in exact baseline, outage fallback, real canonical numeric/path/citation correctness and explicit gaps.

StateCivics commands must use scripts/run_gate.sh statewide; no host dependency installs. ExAIS pytest commands run inside its existing configured test/container environment; PostgreSQL proof needs explicitly disposable SVS_FISCAL_GRAPH_TEST_DATABASE_URL and cannot count skipped tests as passed. Real-source product acceptance is separate from synthetic tests.

## Risks

Similarity scores can be mistaken for reviewed joins, and generated answers can combine incompatible amounts. Reuse canonical eligibility and typed derivations, expose gaps, and prove exact-mode provider bypass with spies and outage cases.

## Rollback

Disable the new fiscal traversal/modes and retain eligible ordinary document retrieval. Keep canonical records, scoped authorization and lifecycle checks active.

## Implementation Log

Implementation has not started under this ticket. Planning only: corrected against the 2026-09-10 developer-manager handoff and independently gated ticket stack. Record actual changed code and verification results here during execution.
