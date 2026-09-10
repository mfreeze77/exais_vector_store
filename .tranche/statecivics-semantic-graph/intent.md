# Owner intent and research handoff — 2026-09-10

**Superseded drafting input.** The owner has now accepted the developer-manager
answers in [manager-alignment.md](manager-alignment.md); continue from the
`aligned/` artifacts, not the original base draft. The historical intent below
does not authorize restarting the ongoing statute harvest or a parallel exporter.

Owner asks: should KanView records be vectorized so semantic search can help
GraphRAG; research and write executable tickets; avoid designing a system that
works only for SB125. This turn is research and ticket preparation, not runtime
implementation, live indexing, provider calls, deployment or source publication.

Owner paused the first draft to supply existing legal assets, then requested
alignment. The current required input is `manager-alignment.md`; the earlier
`legal-assets-alignment.md` is supporting research with superseded harvest advice.
Reuse retained Session Laws immediately; full statute harvesting is a separate
connected expansion, not a prerequisite for the first law-to-money milestone.
The original canonical goal below remains unchanged.

Canonical goal: Enable the Kansas State Civics cell to answer law-to-money
questions across bills and fiscal years by combining semantic and exact retrieval
over source-bound entity descriptions and documents with validated structured
graph relationships, proven on diverse real sources including an unseen bill.

## Repository and artifact locations

- ExAIS implementation worktree: `/Users/mfrieson/Developer/exais-vector-store-ovh`
  (base bb7e575, existing uncommitted WAVE-132 runtime/audit work). Preserve it.
- StateCivics planning worktree: `/Users/mfrieson/Developer/statecivics-fiscal-graph-plan`
  (branch plan/fiscal-semantic-graph, base c47a600d). Canonical repository is
  `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai`, main clean at
  creation. Develop/author the upstream tickets in the clean planning worktree.
- Tranche artifacts: `/Users/mfrieson/Developer/exais-vector-store-ovh/.tranche/statecivics-semantic-graph/`
- Skill: `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/exais_vector_store/.codex/skills/ticket-tranche/`
- For artifact file fields, use absolute file paths so the deterministic gate
  can check both repositories. Also carry repository and relative_path when useful.
- Final Markdown tickets must be addressable in their owner repository's
  `tickets/`; root will materialize them after gates. Base artifact IDs T-001...
  map to canonical IDs later. StateCivics new IDs begin KS-650, consecutive;
  ExAIS new WAVE IDs begin WAVE-133. Existing upstream KS-600/KS-601 own legal
  reconciliation and account crosswalks: reference/extend bounded subsets of
  those tickets, do not create competing canonical models/resolvers. WAVE-132
  stays the reopened parent; the new tranche closes its real-data gaps.

## Confirmed local facts (root inspected; wave 2 rechecks anchors)

- KanView bulk corpus lives outside Git at
  `/Users/mfrieson/Developer/statecivics-kanview-corpus`. Agency Exp/Rev CSVs are
  structured source data; vendor and payroll are different datasets. Do not
  read employee names or copy bulk CSVs into Git or ExAIS.
- Upstream 109,424 dimensions, 410,814 observations, 49,026 budget accounts
  exist. Counts are dated snapshots, not implementation requirements.
- The account audit at ExAIS `scripts/release/kansas-fiscal-corpus-audit.py`
  verified 16 real Education expenditure extracts, 75,746 rows, 44 candidate
  records in 15 years. FY2016 no match; this is not a zero-spending conclusion.
  FY2023/FY2026 Budget_Ref=840 versus 0840 in FY2025. Only the existing kanview-1
  Budget_Ref rule strips leading zeros. KanView has no subunit field.
- FY2026 account 652-1000-840, UUID 01a089bd-bd57-7555-8c25-adc9639ac677, is
  candidate/unresolved. Agency/fund/budget-unit dimensions are candidate/resolved.
  CSV source revision 01a089bc-3323-7aa3-b086-d33deb935bed; source SHA
  ea386136d6135334aa71f84331ec8ab68b2d5c83d9b992efe72b41e1a569eaed.
  Observations currently have empty source locators and no canonical SourceSpans.
  No invented public review or UUID may turn this into a production graph.
- Root's active-chunk snapshot: 68 docs/13,179 chunks includes two active probe
  chunks => 66 real narrative docs/13,177 active chunks; no populated page fields.
  Owner's other snapshot includes additional del/smoke probes. Tickets require
  scoped fresh inventory and explicit probe exclusion; no cleanup is authorized.
- Some PDF revisions have two distinct active extraction versions. Retain raw
  PDF hash AND parsed-text hash/version; do not choose arbitrary first quote.
- Upstream retrieval_exporter.py explicitly excludes chart_of_accounts/raw CSV
  from its narrative export. A sibling graph/semantic-description projection is
  needed; keep source ownership upstream and all ExAIS writes through scoped API.
- ExAIS `fiscal_graph.py` and `fiscal_graph_artifact.py` currently require every
  node to have a PDF/chunk/SourceSpan binding. The graph supports six types and
  five relations, one-hop document expansion. This is NOT accepted real-data
  architecture; structured-only nodes and multi-edge paths need explicit support.
- Existing ExAIS retrieval.py already merges dense and sparse retrieval with
  reciprocal_rank_fusion. docker-compose.yml pins Qdrant v1.14.1. Reuse existing
  retrieval/provider/scope services. Current Qdrant documentation contains newer
  APIs; do not assume v1.16+ features are available or require a vendor migration.

## Proposed design, to verify and refine in the ticket waves

1. Keep canonical accounting data, exact decimals, fiscal year, action type,
   code system, source revision, review/currentness and deterministic joins in
   structured records. Graph and vectors are rebuildable scoped projections.
2. Embed legal/budget passages and compact source-derived descriptions of
   agencies, funds, budget accounts and appropriation/provision concepts.
   Describe labels/aliases/context, bind canonical IDs and source hashes in
   payload, and identify text/template/model versions. Do not embed every CSV
   row, every alias or quarterly Total to recreate the database in embeddings.
   Descriptions should be deterministic source projections; no unreviewed LLM
   summary becomes financial or legal truth. Candidate descriptions cannot leak
   into public search even if graph expansion is disabled; private operator
   preview, if designed, has a separately enforced audience.
3. Exact identifiers and lexical retrieval are first-class alongside dense
   semantic retrieval. A plain-language question finds candidate IDs; scoped
   structured validation checks year, agency/fund/account, publication, source
   currency; bounded typed traversal assembles actual relationships and cited
   evidence. A high vector score is never a legal join or a review decision.
4. Support distinct evidence kinds for structured CSV observations and legal/
   document spans. No fake PDF pages/chunks. One owner for source identity,
   record locator generation, profile/run binding, eligibility, publication
   and withdrawal propagation. Do not generate unrestricted SQL/Cypher from
   user text. Existing PostgreSQL graph and Qdrant can implement this pattern.
5. Preserve money roles (base appropriation, additional appropriation, lapse,
   reappropriation, transfer, expenditure limit, approved estimate, observation).
   Do not sum retrieved passages or compare partial source coverage as annual
   totals. Graph models should allow multi-year and multi-account bill evidence.
6. Benchmark before broad rollout: exact/lexical baseline; document semantic;
   entity-description semantic; hybrid; hybrid + graph. Record candidate recall,
   rank quality, complete correct paths, monetary/year/source accuracy, refusal
   quality, ACL leakage, stale/withdrawn leakage, latency, and embedding/storage
   cost. Freeze nontrivial thresholds/denominators before tuning, require graph
   value beyond semantic-only and no regression on exact identifiers. No fake
   passes from generic keywords, all-refusal outputs or duplicate-source leakage.

## Generalization requirements

- SB125 is a worked case, never a runtime constant or branch. All extraction,
  query, graph identities and joins accept bill/session/version/provision/year
  and agency/account inputs.
- At least three distinct enacted bills, two legislative sessions, two fiscal
  years and three agencies in the real acceptance matrix; include multiple
  action types and at least one held-out bill/agency combination whose answer
  labels are not used for prompt, extraction or retrieval tuning.
- Useful primary-source corpus candidates already verified by root:
  2025 SB125 (Ch117), 2024 HSubSB387 (Ch111), 2024 SB28 (Ch88), and 2025
  SSubHB2125 (Ch128). Verify exact provision/agency/action coverage before
  freezing. HB2125 amends SB125 section204 (79-2989); it is a targeted amendment
  case and must not imply blanket replacement of SB125 appropriations. A missing
  appropriation edge on a tax-only provision is a useful explicit no-path case.
- Include source gaps, ambiguous aliases scoped to agency/year, absent subunit,
  wrong-year lookalikes, budget recommendation vs enacted authority, duplicate
  extraction, changed/vetoed provisions, exact-code queries and natural-language
  aliases. Derive fixtures/labels from retained original bytes, not invented rows.
- Growing coverage to another bill should require new source records/config and
  review, not parser branches, new schema or a separate bill-specific graph.
- No whole-project ontology, payments/payroll/recipient attribution, forecasts,
  Workbench features, new graph product/vendor, VPS procurement or deployment
  execution in this planning task. Activation steps may be specified as a gated
  final ticket, scoped only to ks-state-civics/kansas-fiscal-documents.

## Primary research sources (read 2026-09-10)

- https://microsoft.github.io/graphrag/query/local_search/ — entity-description
  embeddings identify graph access points, then connected graph data and source
  text are prioritized for context. This supports the pattern, not a dependency
  on Microsoft's full extraction/community-summary system.
- https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html —
  VectorCypherRetriever and HybridCypherRetriever combine vector/full-text seeds
  with traversal; external vector DB mapping uses stable IDs. Pattern reference
  only; Neo4j and generated Cypher are not required dependencies here.
- https://qdrant.tech/documentation/search/hybrid-queries/ — dense/sparse fusion
  supported by Query API since1.10. Later parameterized RRF features have later
  version requirements. Existing ExAIS RRF is a compatible reuse seam.
- https://sos.ks.gov/publications/sessionlaws/2025/Chapter-117-SB-125.html
- https://sos.ks.gov/publications/sessionlaws/2024/Chapter-111-SB-387.html
- https://sos.ks.gov/publications/sessionlaws/2024/Chapter-88-SB-28.html
- https://sos.ks.gov/publications/sessionlaws/2025/Chapter-128-HB-2125.html
- https://budget.kansas.gov/wp-content/uploads/FY2026_Comparison_Report-07.16.2025.pdf

## Output quality

Produce roughly 8–10 coherent implementation units rather than microtickets.
Each needs ownership, dependencies, non-goals, evidence, real code anchors,
testable acceptance, executable verification, risks/rollback and expected output.
Use existing KS-600/KS-601 as integration dependencies with bounded acceptance
addenda, not competing implementations. Research/plan does not mark existing
runtime complete. User-facing research brief and linked canonical ticket index
must be delivered along with build-contract.json and stack.index.json.
Allow up to 12 units if required to give existing-asset reuse and optional statute
intake/source-package alignment explicit owners. Mark any broad statute expansion
optional and non-blocking for the fiscal milestone. Do not include court corpus
migration, OpenAI expert replacement or the five-table lineage overlay.
