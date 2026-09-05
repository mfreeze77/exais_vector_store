# Cell-owned graph ingestion and retrieval profiles

Implemented in WAVE-126, starting from `11eebf7`. The first new profile is for
Grant Intelligence. This is a **code-tested extension**, not evidence of a
populated production grant graph or an activated runtime.

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
