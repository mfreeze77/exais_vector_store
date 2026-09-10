# WAVE-130 Fiscal Variant Of The Graph Artifact Attribute Contract

Filed: 2026-09-10, from `feat/wave-126-kansas-fiscal-documents` at `57398de`
(0 behind / 18 ahead of canonical `chore/dropbox-relocation-paths` at `7b8663b`).
Canonical's highest ticket id is 126; this branch already carries 127, 128 and
129, so 130 is the first free id. `WAVE-005` and `WAVE-123` are each duplicated
on canonical, so ids in this store were checked rather than assumed.

## Goal

Define a fiscal-corpus variant of the WAVE-126 graph artifact contract so a
Kansas fiscal graph can eventually be expressed without pretending its rows are
Grant Intelligence Projection rows, and record the identity, vocabulary, review
and scale work that must land first. This is a contract-design ticket. It
authorises no load, no activation and no change to the live KS cell.

## Background

`docs/CELL_GRAPH_PROFILES.md` "Grant graph artifact contract v1" and
`packages/svs_common/svs_common/grant_graph.py` require node attributes to
contain **exactly**:

`gip_generation_id`, `gip_search_document_id`, `gip_entity_id`,
`gip_source_version_sha256`, `gip_citation_id`, `visibility`

and edge attributes to contain **exactly**:

`gip_generation_id`, `gip_relationship_id`, `gip_relationship_sha256`,
`review_status`, `visibility`, `evidence_citation_ids`.

Every one of those is a Grant Intelligence Projection identifier. A Kansas
fiscal corpus has none of them, and `validate_grant_graph` rejects extra or
missing keys, so the fiscal case cannot be squeezed into the existing contract
by adding fields.

This extends WAVE-115, which is **done** — Kansas court GraphRAG expansion is
implemented, all its acceptance criteria are checked, and it has live proof from
2026-08-08 (loader `loaded_nodes=1188`, `loaded_edges=2569`; live graph search
with `applied=true`). WAVE-130 does not restate or redo any of that. It also
follows WAVE-129, which delivers the fiscal *document* source package and
explicitly puts "indexing KanView transaction rows" and "resolving fiscal
aliases, dimensions, accounts, or crosswalks in retrieval" out of scope.

Upstream StateCivics tickets: **KS-595** (`in_review`) owns the immutable source
ledger this depends on; **KS-598** (`in_progress`) owns the fiscal dimension
ontology; **KS-601** (`proposed`) owns the crosswalk/payment bridge and is the
hard blocker in section 3; **KS-612** (`proposed`) owns recipient-payment
ingestion and depends on KS-595, KS-601 and KS-610.

## 1. Identity mapping — verified, with three corrections

Verified against `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai`
`src/kansas_accountability/models/source_artifacts.py` (KS-595) and
`alembic/versions/100_civic_fiscal_dimensions.py` (KS-598).

| Grant contract attribute | StateCivics equivalent | Holds? |
| --- | --- | --- |
| `gip_source_version_sha256` | `civic_source_artifact_revisions.content_hash_sha256` | Yes, with a normalization caveat |
| `gip_citation_id` | `civic_source_spans.id` | Yes, format-compatible |
| `gip_generation_id` | `civic_derivation_runs.id` (plus `fingerprint_sha256`, `code_commit`, `method_version`) | Yes — the better mapping, see below |
| `gip_entity_id` | `civic_fiscal_dimensions.id` / `civic_fiscal_budget_accounts.id` | Partly; vendor payees have no canonical entity id yet |
| `gip_search_document_id` | the WAVE-129 fiscal logical document projected into the ExAIS store | Needs a new file-attribute contract, see below |
| `visibility: public` | `publication_status` | No — nine-valued, not a boolean |

Corrections to the framing this ticket was filed from:

1. **Table name.** It is `civic_source_spans` (model `SourceSpan`), not
   `civic_source_span`.
2. **`content_hash_sha256` is not lowercase-enforced upstream.** Its only check
   constraint is `length(content_hash_sha256) = 64`
   (`ck_civic_source_revisions_content_hash`). ExAIS enforces
   `_HASH = ^[0-9a-f]{64}$`. By contrast the KS-598 alias hashes *are* regex
   constrained (`candidate_set_key_sha256 ~ '^[0-9a-f]{64}$'` etc.). A fiscal
   exporter must therefore normalize and assert lowercase hex rather than assume
   the ledger already guarantees it.
3. **`source_span_id` is nullable.** `_evidence_columns()` in migration 100
   makes `source_revision_id` and `derivation_run_id` `nullable=False` but
   `source_span_id` `nullable=True`. Since `gip_citation_id` is mandatory on
   every node and `evidence_citation_ids` needs 1–20 per edge, **rows without a
   span cannot produce contract-conformant nodes or edges at all**. Span
   presence, not just span existence, is a precondition.

Two findings that strengthen the mapping:

- **The generation analogue already exists and is mandatory.** Every KS-598
  fiscal row carries a non-null `derivation_run_id`, and `civic_derivation_runs`
  is exactly a versioned generation: unique `fingerprint_sha256`, `code_commit`,
  `method_name`/`method_version`, `input_set_hash_sha256`,
  `output_set_hash_sha256`, `status`. The Grant contract's single-generation
  equality requirement maps onto one derivation run cleanly.
- **Identifier formats are already compatible.** StateCivics ids come from
  `new_uuid7_str()`, documented and implemented as a canonical lowercase UUID
  string, so they satisfy ExAIS `_uuid()` (`str(UUID(v)) == v`) and a span id
  also satisfies `_CITATION = ^[A-Za-z0-9_.:-]{1,128}$`. No id reformatting is
  needed; only attribute *names* and *semantics* need a variant.

Additional gap found while verifying: the Grant expansion SQL joins graph nodes
to **vector-store files** on `gip_search_document_id`, `gip_generation_id`,
`gip_source_version_sha256`, `gip_entity_id`, `gip_entity_type` and
`gip_citation_id`. So a fiscal variant is not only a node/edge attribute schema
— the fiscal *documents* must carry the matching file attributes too, and
WAVE-129's documents currently carry StateCivics logical-document and
source-revision provenance under different names. Note `gip_entity_type` appears
on the file side only; it is not one of the six node attributes.

`visibility` needs an explicit projection rule, not a rename. KS-598 defines
nine `publication_status` values (`candidate`, `validated`, `in_review`,
`published`, `corrected`, `superseded`, `rejected`, `quarantined`, `withdrawn`)
plus separate `resolution_status` and `lifecycle_status`. Only `published` +
`resolved` + `active` should be able to project to `visibility: public`, and the
variant must say so in one place rather than leaving it to an exporter.

## 2. Node and edge vocabulary — what is reusable, what is missing

Reusable today from `GRANT_NODE_TYPES`: `vendor`, `recipient`, `document`, and —
correcting the framing this ticket was filed from — **`program`, which does
already exist**. `procurement` and `contract` are also plausibly reusable for
state contract spending.

Reusable today from `GRANT_RELATIONS`: `paid_to`, `funds`, `awarded_to`, and
`authorizes`, which is a natural fit for a bill or enacted appropriation
authorising spending authority. So KanView vendor payments really do fit with no
new types, as long as the projection stays payee-and-payment shaped.

Missing for appropriations. KS-598's `_DIMENSION_TYPES` are
`agency`, `fund`, `budget_unit`, `program`, `function`, `account`. Five of those
six have **no** ExAIS node type — only `program` exists. Also absent:
`appropriation`, `budget_account`, `fiscal_year`. New edge types would be needed
for the hierarchy and the crosswalk that are the entire point of KS-601, at
minimum a roll-up relation (`agency`→`fund`→`budget_unit`→`account`) and a
crosswalk relation between an appropriation account and a payment code. None of
these can be added by config; `GRANT_NODE_TYPES` and `GRANT_RELATIONS` are
frozen code constants, and `validate_grant_graph` rejects unknown types.

## 3. Review blocker — hard dependency, not a caveat

The contract rejects "private or candidate declarations" and requires
`review_status: accepted` with 1–20 `evidence_citation_ids` on every edge
(`grant_graph.py`: `if attrs["review_status"] != "accepted" or
attrs["visibility"] != "public": reject`).

`civic_fiscal_dimension_aliases.publication_status` is created with
`server_default="candidate"`, and migration 100's own downgrade guard treats
`publication_status <> 'candidate'` as the signal that human review has happened
at all. The owner reports **all 229,591 rows are `publication_status =
candidate`**; that count is a live-database observation and is not recorded
anywhere in the StateCivics repo, so this ticket does not assert the number —
but the schema default and KS-601's status make the shape credible, and nothing
in the repo contradicts it.

Consequence: **no fiscal graph edge can be built from those alias rows until
analyst review lands.** That is KS-601's first acceptance criterion — "A public
bridge resolves through a reviewed decision and source evidence, not a hidden
heuristic" — and KS-601 is `status: proposed`, so it is unmet. Treat KS-601 as a
blocking dependency of this ticket, not as related work. KS-612 additionally
states that "unresolved account mappings do not block custody but do block
public law attribution", which is the same boundary from the payment side.

## 4. Scale — the fiscal graph must be a curated projection

A single load is bounded at `MAX_GRAPH_NODES = 10000` and
`MAX_GRAPH_EDGES = 20000`, and `docs/CELL_GRAPH_PROFILES.md` says larger graphs
"require a deliberately reviewed batching/update contract; do not silently
truncate them".

Verified in the StateCivics repo: `VendorData_7_2025.csv` is **88,312 rows for a
single month** (12.3 MB), and the repo's own projection is "roughly 88k
rows/month x 12 x 5 years is **~5.3M rows / ~740 MB**"
(`docs/specs/civic-impact-intelligence/KANSAS_SOURCE_ACQUISITION_FINDINGS.md`).
The FY2025 agency harvest is 276,839 rows across 220 files.

Correction: the figure this ticket was filed from — 10.16M vendor payment rows —
is roughly double the repo's documented projection and is not recorded anywhere
in the StateCivics repo. It may be a live table count; it is not asserted here.
The conclusion is identical either way: at 5.3M or 10.16M rows, a payment-level
edge set exceeds the 20,000-edge bound by two to three orders of magnitude.

The 9,484 distinct payees figure is likewise unverified in-repo, and "nodes fit"
deserves a sharper reading. If it is right, 9,484 payee nodes consume 95% of the
10,000-node budget, leaving **516 nodes** for every agency, fund, budget unit,
account, appropriation and document in the same load. Nodes fit only for a
payee-only projection; they do not fit for a payee-plus-appropriation graph.

State it plainly: **a Kansas fiscal graph must be a curated projection, and
choosing what it contains is a product decision, not a mechanical one.** There is
no mechanical rule that turns 5–10M payment rows into 20,000 reviewed edges.
Someone must decide which agencies, funds, fiscal years, payment thresholds or
policy questions the graph is *for*. Until that decision exists, no exporter
should be written, because the exporter's selection logic *is* the decision.

## Scope

- Write the fiscal variant of the artifact contract into
  `docs/CELL_GRAPH_PROFILES.md` as its own section: attribute names, the
  `publication_status` → `visibility` projection rule, the derivation-run
  generation binding, and the matching **file** attribute requirements.
- Specify the node/edge vocabulary additions in section 2 as a reviewed code
  change to a fiscal handler's own constants; do not widen `GRANT_NODE_TYPES` or
  `GRANT_RELATIONS`.
- Register a fiscal handler/corpus pair in
  `svs_common.cell_graph.GRAPH_HANDLERS` and widen the API's grant-only corpus
  gate in `_cell_graph_profile_or_503`, or state explicitly that a fiscal
  profile stays unloadable until that lands.
- Record the curated-projection selection decision as an owner decision, with
  the node/edge budget it implies.
- Define the batching/update contract for anything above 10,000 nodes or 20,000
  edges, or declare the projection permanently below both bounds.

## Out Of Scope

- Loading any fiscal graph artifact.
- Activating any cell graph profile, including
  `instances/ks-state-civics/graph/profile.yaml`.
- Changing the live Kansas court or Topeka GraphRAG routing, both of which stay
  on their existing env-gated handlers.
- Indexing KanView transaction rows into a vector store (WAVE-129 out of scope).
- Resolving fiscal aliases, dimensions, accounts or crosswalks inside retrieval;
  StateCivics remains the canonical resolver.
- Substituting structural `review_status: accepted` metadata for actual analyst
  review.

## Acceptance Criteria

- [ ] A fiscal attribute contract exists in `docs/CELL_GRAPH_PROFILES.md` with
  its own attribute names, and no fiscal node or edge reuses a `gip_*` key.
- [ ] The `publication_status`/`resolution_status`/`lifecycle_status` →
  `visibility` projection rule is written down and rejects all eight non-
  `published` statuses.
- [ ] The contract requires a non-null `civic_source_spans.id` per node and 1–20
  span-derived citation ids per edge, and states that span-less rows are omitted
  rather than defaulted.
- [ ] The contract requires lowercase-hex normalization of
  `content_hash_sha256`, since the upstream constraint checks length only.
- [ ] One derivation run per artifact is required, mirroring the Grant
  single-generation equality rule.
- [ ] The node/edge vocabulary lists the appropriation types to add and names
  the file attributes the fiscal documents must carry for expansion to join.
- [ ] KS-601 review completion is recorded as a blocking dependency, with the
  candidate-alias state cited.
- [ ] The curated-projection selection is an owner decision recorded in this
  ticket, with an explicit node/edge budget under 10,000/20,000.
- [ ] No graph artifact is loaded and no profile is enabled by this ticket.

## Verification

Facts above were verified by reading, not by running anything:

- `packages/svs_common/svs_common/grant_graph.py` — exact attribute key sets,
  `GRANT_NODE_TYPES`, `GRANT_RELATIONS`, `MAX_GRAPH_NODES = 10000`,
  `MAX_GRAPH_EDGES = 20000`, `_HASH`, `_CITATION`, `_uuid`, the file-join SQL.
- `packages/svs_common/svs_common/cell_graph.py` — `GRAPH_HANDLERS` contains the
  Grant handler only.
- `apps/api/svs_api/main.py` — `_cell_graph_profile_or_503` returns before
  reading any manifest unless the corpus is `reviewed_public_grant_evidence`.
- StateCivics `src/kansas_accountability/models/source_artifacts.py`,
  `src/kansas_accountability/core/identifiers.py`,
  `alembic/versions/100_civic_fiscal_dimensions.py`,
  `alembic/versions/102_civic_fiscal_facts.py`,
  `tickets/KS-595…`, `KS-598…`, `KS-601…`, `KS-612…`,
  `docs/specs/civic-impact-intelligence/KANSAS_SOURCE_ACQUISITION_FINDINGS.md`,
  `docs/specs/civic-impact-intelligence/FISCAL_INGESTION_IMPLEMENTATION_PLAN.md`.

Not verified: the 229,591 candidate-alias count, the 10.16M vendor payment row
count and the 9,484 distinct payee count. All three are live-database
observations with no corroborating record in either repo, and the repo's own
documented vendor projection is ~5.3M rows. No database was queried for this
ticket.

## Notes

The related deliverable `instances/ks-state-civics/graph/profile.yaml` is a
declaration only: it ships `enabled: false`, is mounted nowhere, and cannot be
loaded until a KS handler is registered and the API's corpus gate is widened.
The Kansas fiscal store is deliberately not bound in it, because
`instances/ks-state-civics/vector-stores/kansas-fiscal-documents/store.yaml`
still carries the source-package placeholder `vs_kansas_fiscal_documents_pending`
rather than a real store identity.

Cross-references: extends WAVE-115 (done, live-proven); contract origin
WAVE-126; fiscal source package WAVE-129; graph readiness WAVE-112; lens
catalog WAVE-120; municipal handler WAVE-122. StateCivics KS-595, KS-598,
KS-601 (blocking), KS-612.
