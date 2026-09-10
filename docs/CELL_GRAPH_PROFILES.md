# Cell-owned graph ingestion and retrieval profiles

Implemented in WAVE-126, starting from `11eebf7`. The first new profile is for
Grant Intelligence. This is a **code-tested extension**, not evidence of a
populated production grant graph or an activated runtime.

WAVE-132 adds the separate State Civics fiscal law-and-money handler described
below. Shared handler registration does not enable it in other cells.

## Ownership boundary

Each cell owns its source acquisition, graph extraction/normalization rules,
ontology, evidence requirements, update policy and evaluated corpus. ExAIS
shares authentication, queued document ingestion, graph tables, scoped graph
loading, retrieval ACL checks and result citations. Do not fork these engines
for every customer, or treat a generic LLM's extracted relationship as accepted
canonical truth.

| Layer | Shared mechanism | Cell/domain-owned input |
| --- | --- | --- |
| Source ingestion | Existing document API and worker | Source packages, collector, chunking/vectorization profile |
| Graph artifact | Existing node/edge load API | Versioned extractor, node/edge types, evidence and review rules |
| Graph selection | Trusted deployment manifest and handler allowlist | Exact tenant, business instance, store and profile binding |
| Retrieval | Existing ACL hydrator and result-aware citations | Explicit lens, generation filter, domain-specific bounded expansion |

One cell can contain several corpora with different graph needs; this does not
mean one universal ontology per cell. The current new manifest binds **one
versioned handler to one or more explicitly listed stores**. A future cell with
several new handlers should extend this to an explicit profile catalog, not
select executable Python from request metadata. Existing court and Topeka
handlers retain their existing routing/configuration in this wave; they are not
silently migrated to the new manifest format.

## Trusted selection

Grant's reviewed deployment manifest is:

`instances/grant-intelligence/graph/profile.yaml`

`svs_common.cell_graph` reads `SVS_CELL_GRAPH_PROFILE_PATH`. This must be an
absolute path to a small, operator-owned YAML file mounted **read-only** into the
API container. It is not a URL, include mechanism or dynamic plugin loader.
Unset means disabled. Invalid/unreadable configured manifests return a generic
503 for Grant profile operations without echoing configuration contents.

All of these must match before the profile can be used:

- authenticated `Principal.tenant_id`;
- authenticated `Principal.business_instance_id`;
- the requested vector-store ID in the explicit binding list;
- store attribute `corpus: reviewed_public_grant_evidence`;
- store attribute `graph_profile_id: grant-intelligence.public-evidence.v1`.

A corpus label, ingestion attribute or query cannot override those bindings.
`enabled: false` allows an authorized operator to validate/load an artifact but
keeps graph search disabled. New profiles are checked against a code-reviewed
handler/corpus allowlist. Extra manifest fields and out-of-bounds settings fail
validation. The Grant handler is capped at one hop and 0–10 expansions; the
checked-in cell policy sets 3. A request-level internal cap can only lower it.

The `profileManifest` / `profileId` entries in `instance.yaml` and
`graphProfileId` in `store.yaml` are reviewable deployment inventory, **not an
automatic mount or API metadata update**. Both runtime steps are explicit below.

## Grant graph artifact contract v1

Use the existing `POST /v1/vector_stores/{id}/graph` endpoint. The caller needs
`vector_stores:write`; Grant's application search and document-writer keys do
not have it. Use a separate operator credential, never widen the application's
keys. The authenticated scope is supplied by the server, not the artifact.

Grant source truth remains in the Grant Intelligence canonical database and
source packages. ExAIS graph tables are disposable derived projections.

The load request has the existing `nodes`, `edges`, `replace`, `dry_run` fields.
Prefer `dry_run: true` first and `replace: false` to append a new generation
without erasing the currently served one. `replace: true` replaces the **whole
scoped store graph**, not only the submitted generation; use it only for an
explicitly planned replacement/cleanup. A load is bounded at 10,000 nodes and
20,000 edges. Larger graphs require a deliberately reviewed batching/update
contract; do not silently truncate them.

Node types currently supported:

`program`, `opportunity`, `award`, `winner`, `recipient`, `project`,
`procurement`, `contract`, `vendor`, `document`.

Node attributes must contain exactly:

- `gip_generation_id`: canonical UUID of the Grant search projection generation;
- `gip_search_document_id`: canonical UUID of that generation's SearchDocument;
- `gip_entity_id`: canonical UUID of the underlying Grant entity;
- `gip_source_version_sha256`: exact 64-character lowercase source-version hash;
- `gip_citation_id`: that projection's bounded canonical citation identity;
- `visibility`: `public`.

Node identity:
`gip:{vector_store_id}:{gip_generation_id}:{gip_search_document_id}`.
Use one node per cited search projection; do not substitute publisher URLs for
canonical IDs. Node labels are optional display text, not evidence.

Edge types currently supported:

`awarded_to`, `funds`, `authorizes`, `uses_procurement`, `has_contract`,
`paid_to`, `has_winner`.

Edge attributes must contain exactly:

- `gip_generation_id`: the same generation as both loaded endpoints;
- `gip_relationship_id`: canonical UUID of the accepted relationship;
- `gip_relationship_sha256`: exact canonical relationship-version SHA-256;
- `review_status`: `accepted`;
- `visibility`: `public`;
- `evidence_citation_ids`: 1–20 citation IDs belonging to nodes in this artifact.

Edge identity:
`gip:{vector_store_id}:{gip_generation_id}:edge:{gip_relationship_id}`.
Its `source` and `target` must reference loaded node IDs. Mixed generations,
dangling/duplicate identities, legal-only relation types, private or candidate
declarations, arbitrary extra metadata, `properties` and uncontrolled provenance
objects are rejected. Store exact source/review custody in the canonical system
and reference it through hashes and citation identities.

These are **structural checks of an authorized publisher's assertions**, not
independent verification of a human approval. The Grant exporter still must
verify current canonical versions, accepted/publication-allowed status, actual
review evidence and source custody. Missing evidence or unprojected entity types
must produce explicit omissions/gaps; neither tags nor active matching links
automatically become reviewed graph edges. This wave does not implement that
canonical exporter and does not load real grant relationships.

## Search contract

The lens catalog is still `GET /v1/vector_stores/{id}/search_lenses`.
`grant_evidence` appears only for the Grant corpus. It is disabled without an
enabled bound profile, empty without loaded nodes and edges, and never inferred
from natural language. Semantic search remains the default.

Example request after explicit activation and artifact loading:

```json
{
  "query": "community development funding",
  "lens": "grant_evidence",
  "inputs": {"relationship": "funds"},
  "filters": {
    "gip_generation_id": "11111111-1111-4111-8111-111111111111",
    "state_code": "KS"
  },
  "max_num_results": 10
}
```

Replace the illustrative generation with the actual served generation. Public
API filters are direct comparisons; `file_attribute_filters` is an **internal**
representation, not the public request wrapper. Grant requires one exact
generation equality; a cross-generation OR query is not sufficient.

Expansion joins graph nodes to completed vector-store files on generation,
projection ID, entity ID/type, source-version hash and citation identity. It
requires active current-version public chunks and accepted public graph edges.
Candidate SQL enforces tenant/business/store and document/knowledge-base/
classification/ACL-bucket filters. The existing hydrator reapplies file
comparison/range/alternative/exclusion filters and principal group/role ACLs.
Supporting citations may point to a third document rather than an endpoint.
Every supporting citation must still resolve to a completed, exactly bound,
current public document/chunk accessible to the principal's groups/roles. A
private, stale, missing or cancelled supporting document suppresses the edge;
even its canonical citation ID is not exposed through graph metadata. Supporting
evidence is access-checked but need not match the returned result's topic filters.
At most 10 seed documents and `20 * max_expansions` candidate rows are inspected;
bounded candidate selection can omit relevant relationships. This is not an
exhaustive funding-chain traversal.

Returned document citations are preserved. Minimal graph metadata adds the
relationship ID/hash, directed endpoint IDs, generation and evidence citation
IDs; it never changes the primary citation into the seed's citation. Catalog
node/edge counts are store-wide, **not** proof of generation/corpus completeness.
The per-search graph summary reports actual expansion use and cell profile ID.

## Activation checklist (not executed in WAVE-126)

1. Finish and qualify the canonical Grant exporter and source packages; record
   its exact revision, input generation and artifact digest.
2. Build/pin a new API image containing this commit. Do not rebuild or restart
   the StateCivics cell. No database migration is required for this extension.
3. Copy the reviewed manifest into the private Grant runtime directory, mount
   read-only and set `SVS_CELL_GRAPH_PROFILE_PATH` for **that API service only**.
   Keep `enabled: false` initially.
4. Preserve existing store attributes while adding the exact `graph_profile_id`
   using the existing vector-store update API with an operator credential.
5. Validate then load the artifact through the graph API after the matching
   document projections have completed. Never load via caller-side SQL.
6. Enable the private runtime profile for a bounded synthetic acceptance test;
   verify citations, negative filters, version changes and cleanup. Then run
   separately labeled, reviewed real-corpus evaluations before claiming readiness.
7. Record image digest, profile/artifact digests, observed generation, tests and
   limitations. Disable the profile to turn graph expansion off; semantic search
   and document ingestion do not require removal of graph rows.

## Verification

`tests/test_grant_cell_graph.py` exercises bindings, strict graph payloads,
explicit routing, scope denial, disabled/default behavior and bounds.
`tests/test_grant_graph_postgres.py` is an opt-in fixture-only regression using
the existing migrations, graph loader and ACL hydrator under the restricted
`svs_app` role (NOSUPERUSER, NOBYPASSRLS). It never selects a live cell URL.
The dedicated `SVS_GRANT_GRAPH_TEST_DATABASE_URL` must point to an explicitly
disposable migrated database; all fixture changes additionally roll back.

See the wave ticket for exact observed results and remaining gates.

## Kansas fiscal law-and-money alignment

The [2026-09-10 StateCivics handoff](STATECIVICS_LAW_MONEY_ALIGNMENT.md)
governs the corrected fiscal implementation. KS-600 defines provision identity
and reconciliation; KS-595/597 supply source/span infrastructure and population;
KS-650 extends the existing exporter with an entity/relationship record kind.
ExAIS consumes canonical typed derivations and structured/document evidence.
WAVE-133 through WAVE-136 own the required changes and real-source proof.

The v1 section below records the existing WAVE-130/WAVE-132 design and mechanics
for diagnosis. Its universal PDF/chunk binding, SourceSpan-as-provision identity
and provisional publisher envelope are superseded requirements. Source code has
not been corrected by this documentation change. Do not use these legacy details
as instructions for the StateCivics exporter or as evidence of activation readiness.

## Historical Kansas fiscal artifact contract v1

**Historical WAVE-130 contract, implemented provisionally under WAVE-132.**
Synthetic/runtime proof establishes mechanics only. Real-source acceptance is
reopened. The original scope was:

**Enacted provision → appropriation → agency/fund/account → supporting budget
documents.** Start with SB 125 Supplemental State Aid, FY2026 and FY2027. This
selection does not approve the example's underlying source records for public
use. Payments, recipients, observed outcomes, forecasts, claim adjudication,
district allocation, and drafting simulation are outside this release.

StateCivics owns canonical legal/fiscal records, review, source revisions/spans,
amounts, and corrections. ExAIS consumes a rebuildable, cited relationship
projection. Relationship retrieval never calculates totals by summing chunks.
An appropriation is spending authority; its graph link does not establish an
expenditure or a payment. Budget requests and recommendations retain their stage
and cannot establish enacted authority.

### Fiscal types, relations, and selection

V1 fiscal constants reside in `svs_common.fiscal_graph`, separate
from Grant constants. The corpus is `kansas_fiscal_documents`, handler
`kansas_fiscal_law_money_graph_v1`, and profile
`ks-state-civics.kansas-fiscal-documents.v1`.

Node types are exactly `enacted_provision`, `appropriation_action`,
`budget_account`, `agency`, `fund`, and `fiscal_document`. A `budget_account`
references the canonical composite account, including its budget-unit component;
do not equate a bare account suffix with that identity.

| Directed relation | Source → target | Meaning |
| --- | --- | --- |
| `contains_appropriation` | enacted_provision → appropriation_action | Exact enacted span contains the published legal operation. |
| `targets_account` | appropriation_action → budget_account | Published operation names this reviewed account for the stated fiscal year. |
| `account_of_agency` | budget_account → agency | Reviewed component/ownership relationship for that period. |
| `account_in_fund` | budget_account → fund | Reviewed fund component for that period. |
| `documented_by` | appropriation_action, budget_account, agency, or fund → fiscal_document | The cited budget-document span documents this entity/action in the specified context. |

`documented_by` is contextual evidence, not proof that an entire budget document
has the legal force of an appropriation. No relationship comes from a nearest
neighbor, shared name, or code suffix alone. Unknown types and reversed endpoint
types are rejected. Retrieval may visit either endpoint of a recorded edge, but
returned metadata always retains its original direction and meaning.

The first artifact contains only the approved SB 125 account chain and its
supporting legal/budget evidence, capped at **1,000 nodes and 2,000 edges**, with
no silent truncation or bulk transaction export. These deliberately sit below
the existing Grant validator's 10,000/20,000 bounds; the shared request schema
itself does not impose those count limits. Fiscal validation must enforce its
own limits. An incomplete chain reports the missing links and cannot be called
end-to-end ready. A useful partial document search remains available separately.

### Fiscal artifact and identity contract

**Real-data correction, 2026-09-10:** this implemented v1 contract is under
revision. Its mandatory chunk binding for every fiscal entity excludes the
existing KanView structured observations. It must not be treated as the accepted
real-corpus design. [FISCAL_GRAPH_REAL_DATA.md](FISCAL_GRAPH_REAL_DATA.md) records
the measured account/source evidence, required structured/document distinction,
and the gaps that must be closed before fiscal activation.

Use the existing `VectorStoreGraphLoadRequest` JSON envelope (`nodes`, `edges`,
`replace`, `dry_run`). Add no top-level envelope fields to the shared API.
Explicitly set `replace: false` and `dry_run: true` for initial validation;
the schema defaults are `replace: true`, `dry_run: false`. A separate operator
manifest records the canonical export digest, assembled load-request digest,
source manifest, schema `svs.fiscal-law-money.v1`, and selection/gap report.

One artifact uses exactly one completed **relationship-export** `DerivationRun` UUID,
repeated on every node and edge. Creating that upstream export run is future
StateCivics work. Do not invent a run or assume that all input canonical entities
were produced by the same derivation. Retain their individual source derivation
IDs in the export's canonical provenance. The graph run references that input
set and its hashes. A content change creates a new run/artifact; replays of the
same export and chunk bindings are deterministic.

Node attributes must contain exactly these fields:

| Attribute | Required value |
| --- | --- |
| `fiscal_schema_version` | `svs.fiscal-law-money.v1` |
| `fiscal_artifact_class` | `reviewed_public` for real data; `fixture_only` for isolated development |
| `fiscal_derivation_run_id` | Canonical lowercase UUID of the relationship-export run |
| `fiscal_entity_id` | Opaque canonical identity, 1–256 characters; never a display label |
| `fiscal_entity_sha256` | Digest of the exact exported canonical record revision |
| `fiscal_logical_document_id` | Existing WAVE-129 logical-document identity: 64 lowercase hex characters, **not a UUID** |
| `fiscal_source_revision_id` | Canonical source-revision UUID |
| `fiscal_source_content_hash_sha256` | Exact source bytes' SHA-256, 64 lowercase hex characters |
| `fiscal_source_span_id` | Non-null canonical SourceSpan UUID |
| `fiscal_chunk_id` | Exact ExAIS chunk binding resolved after document ingestion |
| `fiscal_year` | Integer FY explicitly supported by the cited span, 1900–2200 |
| `fiscal_bill_version_id` | Exact canonical bill-version ID for provisions/actions; null for other types |
| `fiscal_publication_status` | `published`, a normalized exporter assertion governed below |
| `visibility` | `public` |

V1 used the canonical SourceSpan ID as `fiscal_entity_id` for
`enacted_provision`. This is a known identity defect, not the accepted convention:
WAVE-133 must consume KS-600's new version-specific provision reference and bind
SourceSpan separately as evidence. V1 uses the source-revision ID for
`fiscal_document`. Other entity IDs
come from their canonical records. Export record digests use
`statecivics-canonical-json-v1` (UTF-8 JSON, sorted keys, compact separators,
non-ASCII preserved), over the explicitly supplied canonical record body. The
upstream export must retain that body/digest association; ExAIS does not derive
an identity or approval by parsing prose. Validate hex before lowercasing source
hashes; malformed 64-character strings are rejected. Compare against the exact
custodied revision and existing document file attributes, never rewrite a file
hash merely to make a join pass.

One node represents an entity's evidence binding, not every occurrence of that
entity across the corpus. Its ID is `fiscal:{store_id}:{run_id}:node:{digest}`,
where `digest` is SHA-256 of canonical JSON containing the node `type` and all
its `attributes`. Thus two entities/spans in one document remain distinct, and
one entity cited by multiple documents can have multiple evidence nodes.

Edge attributes must contain exactly `fiscal_schema_version`, `fiscal_artifact_class`,
`fiscal_derivation_run_id`, `fiscal_relationship_id`,
`fiscal_relationship_sha256`, `fiscal_review_status`,
`fiscal_publication_allowed`, `fiscal_year`, `visibility`, and
`evidence_citation_ids`. Schema/run match the endpoints; relationship ID is a
bounded opaque canonical ID (1–256 characters), relationship hash is lowercase
SHA-256 of its exported canonical revision, review status is `accepted`,
publication allowed is `true`, and visibility is `public`. Artifact class must
match every node and edge. Fiscal year must
match both endpoints; represent separate FY contexts as separate evidence
nodes/edges, even when the source document covers both years.

`evidence_citation_ids` contains 1–20 distinct SourceSpan UUIDs belonging to
nodes in the same artifact, including any third-document support. A repeated
span ID must identify the same source revision and canonical locator/quote
binding wherever it occurs. The edge ID
is `fiscal:{store_id}:{run_id}:edge:{digest}`, hashing canonical JSON containing
`type`, `source`, `target`, and all edge `attributes`. Both endpoint IDs must
exist in the artifact. Duplicate IDs, dangling links, mixed runs, uncontrolled
`properties`/`provenance`/extra fields, and missing citations are rejected.
Optional node `label` is bounded display text (max 256 characters), never
evidence; node `key` is omitted. Domain provenance stays in StateCivics.

### Publication and evidence mapping

The upstream structured relationship exporter must apply these type-specific
rules before emitting normalized `published`/`accepted` assertions:

- Fiscal dimensions and composite budget accounts require
  `publication_status=published`, `resolution_status=resolved`, and
  `lifecycle_status=active`, with source-backed observations. All other
  publication/resolution/lifecycle states are ineligible.
- Appropriation actions require their contract's `status=published`, actual
  completed review evidence, an exact bill version and source span, and a
  resolved canonical target account. Their contract does not have the
  ontology status triplet; do not invent those columns.
- An enacted provision additionally requires upstream verification of its
  legal status and effective period, including applicable veto/override or
  supersession. A source being an enrolled bill, or an action being published,
  is insufficient by itself. Workbench engineering candidates are ineligible.
- Legal and supporting budget documents must satisfy the existing retrieval
  export's current, retained, full-redistribution conditions. Official source
  status alone does not approve a proposed account relationship.
- Every relationship requires actual review/publication evidence and the
  compatible entity/source revisions named in its canonical record. Preserve
  fiscal stage, evidence class, legal applicability, conditions, and period in
  that source record and any returned explanatory evidence. Graph attributes
  do not replace fiscal facts or calculate final authority.

The canonical exporter must retain review references, source span/quote/locator,
record bodies and hashes, and source derivation lineage for audit. These are
**trusted publisher assertions**; the ExAIS validator verifies shape and
bindings, not the authenticity of an upstream human decision. No new signing
service or direct cross-service database access is assumed.

KS-601 is conditional: if a chain uses an account crosswalk, it must have a
current positive reviewed/publishable decision with corroborating source refs.
`AccountCrosswalk` uses `status`, `publication_allowed`, and `review`, not the
ontology triplet. A published `not_same` is negative evidence and never a
positive link. Candidate aliases, including unique candidates, and ambiguous
sets are insufficient. The first vocabulary has no generic crosswalk or
payment edge; a directly reviewed canonical account binding need not wait for
all recipient/payment work or for the entire KS-601 ticket to close.

### Document/chunk binding and search

The existing fiscal document file attributes remain the join keys:
`source_collection=statecivics-kansas-fiscal-documents`, `logical_document_id`,
`source_revision_id`, and `source_content_hash_sha256`. Preserve
`export_record_id` and `export_record_digest_sha256` for traceability. **No
entity ID, entity type, span ID, or graph generation is added as a scalar file
attribute:** one document can support many entities/spans and multiple graph
generations. This deliberately differs from Grant's one-projection-per-file
contract and avoids re-embedding documents for graph-only changes.

After ingestion, the ExAIS artifact adapter resolves each canonical span to a
specific active chunk of the exactly bound current document version. It records
the span locator/quote hash and the chosen chunk in its evidence-binding report.
The binding must prove that the cited material is present; choosing the first
chunk of a document is insufficient. Ambiguous, missing, stale, or span-less
bindings are omitted with an explicit gap. Assembly requires a bounded,
inspectable span-to-chunk resolution path before a real artifact can load.

The proposed explicit lens is `fiscal_relationships`, with
`inputs.relationship` (`all` or one allowed relation) and required
`inputs.derivation_run_id` (exact UUID). Keep this graph selector **out of
document filters**: existing fiscal files have no graph generation attribute.
The requested run must equal operator-managed store attribute
`fiscal_graph_derivation_run_id`, the currently served export. This store
attribute is read alongside exact corpus/profile binding; it is not a new field
on the strict `CellGraphProfile` manifest. Unset or mismatched run fails closed.
This requires a fiscal-specific input/dispatch change; it is not current API
behavior. Ordinary semantic search never infers or runs this lens.

One request expands one hop, with at most 10 seed chunks, 200 candidate edges,
and 0–10 added chunks (default profile cap 3). Returned chunks must satisfy the
original document/file filters and Principal's tenant/business/group/role ACLs
through scoped SQL and the existing authorized hydrator. Supporting evidence
is also access-checked, even when a third document does not match topic filters.
An inaccessible support span suppresses the edge and its identifiers. Retain
the target chunk's primary citation plus the exact canonical source-span
reference; deduplicate returned chunks while keeping distinct bounded edges.
Never synthesize a multi-hop chain from unrelated search hits. An end-to-end
demonstration follows each recorded hop explicitly in the same run and reports
its coverage/gaps; one-hop search does not promise complete chain traversal.

### Fiscal load, activation, and correction boundaries

WAVE-132 implements the fiscal handler/corpus registration, fiscal validation
before the shared graph loader, explicit `fiscal_relationships` lens, and a
publisher-to-chunk artifact adapter. The profile resolver accepts this handler
only with the exact operator manifest and store binding. This code is shared
in ExAIS; activation is specific to the State Civics fiscal cell/store. The
checked-in fiscal profile example remains disabled. See
[`FISCAL_GRAPH_OPERATOR.md`](FISCAL_GRAPH_OPERATOR.md) for the versioned publisher
input, commands, and live-data prerequisites. The upstream producer for that
reviewed graph envelope is still required; document ingestion alone does not
provide approved relationships.

Use a distinct fiscal profile example under the fiscal source package and a
separate operator-rendered runtime manifest selected by
`SVS_CELL_GRAPH_PROFILE_PATH`. The current resolver accepts one strict manifest;
do not append fiscal configuration to
`instances/ks-state-civics/graph/profile.yaml`, which declares the court profile.
Grant/court/Topeka behavior is unchanged. Do not bind the placeholder store or
use document counts as activation constants; first verify actual store scope,
corpus, source package, and current file/chunk identities read-only.

Fixture-only development uses isolated stores and cannot activate real-corpus
support. The runtime load/search path rejects `fiscal_artifact_class=fixture_only`;
only an explicit isolated test harness may accept that class, and synthetic
publication assertions are not real review evidence. The real exporter manifest
and assembled artifact digests, source
review/evidence, chunk-binding report, input/run identities, dry-run, and scoped
load/read/correction/ACL proof are required before enabling the fiscal profile.
The complete SB 125 demonstration must cover all five approved relation types;
partial coverage is reported honestly. No source approvals are granted here.

New graph generations may be staged with `replace: false`; a serving-run switch
occurs only after validation. Reject overwriting an existing generation with
different content. `replace: true` deletes the entire scoped store graph and
requires an explicit replacement/rollback plan. A withdrawal, correction, or
lost publication eligibility requires invalidating the affected serving run
before a replacement is served. Operators disable the fiscal profile if that
invalidation cannot be established. Revalidate document/chunk/source bindings
at search time so superseded or removed documents do not contribute edges.
Disabling the fiscal profile is the immediate rollback; no document re-ingestion
or graph deletion is necessary to preserve ordinary search.
