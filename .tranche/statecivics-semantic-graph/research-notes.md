# Additional verified research / risks for enrichment

Read by the enricher after the base-ticket gate. These details refine the same
goal; they do not expand scope to transactions, forecasting or other cells.

## Verified local interfaces

- `packages/svs_common/svs_common/retrieval.py:RetrievalService.search` performs
  `_query_embedding` before sparse retrieval and before `_fusion_weights`.
  Setting embedding weight to zero alone does not produce a provider-free exact/
  lexical baseline or outage fallback. Tickets must implement/test the actual
  bypass, including reranking, in the fiscal path.
- Qdrant pin: `docker-compose.yml:29` is v1.14.1. Current official hybrid docs
  introduce Query API in1.10 but parameterized RRF `k` in1.16. Keep existing
  ExAIS RRF unless a measured reason and explicit compatible implementation
  justify changing it. Inspect `qdrant_adapter.py` before promising API calls.
- Upstream existing appropriation action vocabulary is
  `contracts/civic-impact/appropriation-action.schema.json`: appropriate,
  increase,decrease,lapse,transfer,reappropriate,limit,veto,override,
  technical_correction. Money is a decimal string; amount may be null.
  Reuse that vocabulary and preserve conditions and from/to accounts. A no-limit
  authorization is not a zero-dollar appropriation. Do not add a competing enum.
- Account crosswalk schema already owns same_account, alias_of, predecessor_of,
  successor_of, not_same, unknown and review/publication/effective periods.
  Reuse the canonical fiscal ontology and source ledger, not a graph-specific
  second set of authoritative account IDs.
- StateCivics `scripts/run_gate.sh statewide [pytest args...]` passes focused
  test selectors through and performs required mounts/memory/env checks. Final
  upstream verification commands must use this script, not handwritten Docker
  commands that omit its worktree/git mounts.

## Real non-SB125 cases verified against published source pages

- 2024 SB28 / Ch88 §67(a–b), §68(a),(f),(k),(q), §69, §§141–142: Commerce
  (agency300) and Transportation (276) have appropriations, lapses, transfers,
  expenditure-limit changes, incomplete/missing account strings and conditions.
  §142(a) State Highway Fund is explicitly "No limit". §142(i) contains a
  condition dependent on enactment of other legislation. These exercise format,
  action and agency variation; the benchmark must resolve the exact effective
  legal text including veto/override markers before publishing expected facts.
  Source: https://sos.ks.gov/publications/sessionlaws/2024/Chapter-88-SB-28.html
- 2024 HSubSB387 / Ch111 §3(a) contains the FY2026 supplemental-state-aid base
  appropriation and a separate reappropriation condition. It supplies a real
  predecessor-law case for the later SB125 lapse, not an invented amount oracle.
  Source: https://sos.ks.gov/publications/sessionlaws/2024/Chapter-111-SB-387.html
- 2025 SSubHB2125 / Ch128 §7 specifically amends KSA79-2989 as amended by SB125
  §204; §1 concerns the school levy. The Ch117 "amended by128" banner does not
  by itself replace SB125 §96(j) or §97(a). This is a useful amendment-scope/
  no-appropriation-path case, not a full legal-history feature expansion.
  Source: https://sos.ks.gov/publications/sessionlaws/2025/Chapter-128-HB-2125.html
- The benchmark needs a positive held-out bill/agency path as well as negative
  amendment/gap cases. Do not pick only a no-path tax bill for the heldout gate,
  and do not make the heldout another bill funding the same Education account
  while claiming agency generalization. Freeze exact case split in its first
  ticket; add an additional official enacted law if required.

## Scale and generalization risks that the build contract must resolve

- WAVE-132 currently caps an entire artifact at1,000nodes/2,000edges and serves
  one selected run. The real ontology already has49,026budgetaccounts. Define
  bounded batches/partitions and complete-manifest activation or a scoped query
  projection so arbitrary bills can coexist without hardcoded bill-specific
  graphs or replacing the previous bill on every load. Do not simply raise
  unbounded limits, and do not silently truncate eligible records.
- Year-scoped canonical IDs remain distinct even if descriptor text is equal.
  Cached vectors may share a text/model hash, but separate fiscal identities,
  eligibility and source references must not collapse across year or agency.
- Historical fiscal evidence can be valid for an as-of query even when its
  fiscal period has ended. Distinguish historical coverage from withdrawn or
  superseded source revisions. The answer must declare the requested period
  and graph/source snapshot rather than always treating the newest year as truth.
- Graph distance alone is not a complete path. A law-to-account-to-agency/fund-
  to-document answer needs multiple typed edges; retain direction, action role,
  year and per-edge provenance. Semantic proximity never inserts an edge.
- Public entity descriptions need the same visibility/source-currentness checks
  as graph nodes, including when ordinary semantic search is used without a
  graph lens. A disabled graph does not excuse leaking candidate descriptors.
- Monetary facts should hydrate from canonical action/observation records and
  original cited spans; semantic descriptions are search material. Retrieval
  quality evaluation must not turn a generated synopsis into the answer oracle.

These are design conclusions based on the code and sources above, not claims
that any new functionality has been implemented or measured yet.
