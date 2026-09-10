Decision: PASS

Ticket reviewed:
- `tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md`

Evidence reviewed:
- `tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md`
- `docs/CELL_GRAPH_PROFILES.md` (Kansas fiscal law-and-money artifact contract v1)
- `.tranche/kansas-fiscal-graphrag/README.md`
- `.tranche/kansas-fiscal-graphrag/scope-decision.md`
- `.tranche/kansas-fiscal-graphrag/wave-130-proof.md`
- Existing anchors in `grant_graph.py`, `cell_graph.py`, `schemas.py`, `search_lenses.py`, `main.py`, `kansas-fiscal-document-ingest.py`, and the StateCivics source models/exporter named by the ticket
- Commands: `git diff --check` (no whitespace errors); the standard-library scope/link check recorded in `wave-130-proof.md` (PASS); local review of the existing graph request schema, profile resolver, search-lens registry, and fiscal file attributes

Acceptance criteria:
- [pass] Fiscal-specific node/edge identity and attributes are documented without Grant `gip_*` keys; the approved five-link chain, typed endpoints, FY/bill-version context, and 1,000/2,000 design bounds are explicit.
- [pass] Exact source revision, non-null source-span, and active current-chunk evidence are required; the contract requires an inspectable span-to-chunk adapter and rejects ambiguous, stale, missing, or span-less bindings rather than selecting a first chunk.
- [pass] One completed relationship-export `DerivationRun` binds the artifact and is repeated on nodes/edges, while individual source derivation provenance is retained and no per-file graph generation is invented.
- [pass] Many entities/spans per document are supported through evidence-node identity; graph-only changes do not add scalar entity/span/run attributes to document files, and the graph selector remains separate from document filters.
- [pass] The proposed `fiscal_relationships` lens requires an explicit relationship and exact `derivation_run_id`, matched to the operator-managed current-store run attribute; the separate fiscal manifest example/runtime path preserves the existing court manifest and single-profile resolver boundary.
- [pass] Enacted provisions require legal-status/effective-period and veto/override/supersession verification; enrollment alone is explicitly insufficient. Appropriation actions and ontology dimensions have distinct publication rules.
- [pass] Conditional AccountCrosswalk handling uses its actual status/publication_allowed/review fields; positive links require reviewed publishable evidence, while `not_same`, candidate, unresolved, and ambiguous decisions cannot create positive edges.
- [pass] Fixture-only artifacts are marked `fixture_only`, isolated, and rejected by runtime load/search paths; no source publication, live graph load, handler activation, or upstream write is claimed.
- [pass] Scope is limited to documentation for the owner-approved enacted provision → appropriation → agency/fund/account → supporting budget documents chain. Payments, outcomes, forecasts, simulation, deployment, and runtime implementation remain out of scope.

Findings:
- none

Required fixes before next ticket:
- none

The proof is documentation-scope proof only; it does not certify runtime behavior, source publication, or live activation, consistent with the ticket's explicit boundary.
