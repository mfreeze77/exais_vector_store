# WAVE-134: Ingest scoped projections with consistent eligibility and lifecycle

Status: in progress — bounded document coordinates; canonical projection integration pending. Parent: WAVE-132 (reopened). Filed 2026-09-10.

## Summary

Keep semantic descriptions, exact records and derived graph projections aligned with upstream publication, correction and source lifecycle in the Kansas fiscal scope.

## Background

The existing ingestion path is document-oriented. A graph-only publication check would leave candidate entity descriptions visible through ordinary semantic search, while partial corrections or withdrawals could leave stale results in another index.

## Scope

- Explicit KS-650 record dispatch precedes custody/logical_document_id access. Existing document branch retains current API uploads. Entity branch uses WAVE-133 adapter, existing graph API and IngestionService extension; it creates no synthetic documents/chunks.
- Store canonical entity/description/evidence fields in staged fiscal graph attributes with kind, canonical revision, publication/snapshot/source/template/manifest/partition/profile IDs. Index only eligible compact descriptors as separate entity Qdrant points; exact/lexical fields stay in scoped graph projections. Do not insert fake rows into chunks or embeddings tables that require chunk FKs.
- One fiscal_projection predicate owns audience, publication/resolution/lifecycle, source allowlist/custody/rights, requested FY/as-of and approved active-manifest membership. Server derives fiscal scope from actual store/corpus ownership even for native/unscoped requests; client metadata cannot disable it. Candidates are withheld from ordinary indexes, backend filters exclude them, and final canonical hydration rejects stale injected points. Graph enabled/disabled/invalid state cannot change eligibility.
- Use existing QdrantAdapter, configured profile/provider services and usage ledger. Descriptor vectors carry profile/model/dimensions/text hash; encode document/query correctly per store. Current profile discovery scans only chunk embeddings, so add descriptor manifest profile lookup. Equal descriptor text never merges FY/agency identity; no raw-score joins or dimension-equality assumption.
- Stage immutable partitions; require all expected hashes/counts/source bindings/profile/index acknowledgements before guarded compare-and-swap on the scoped vector-store row. Activation is a later operator action gated by WAVE-136/WAVE-132. Partial indexing preserves prior approved view. Never treat swallowed index failure/empty results as a successful stage.
- Corrections retain old audit revisions and expose only an independently reviewed complete replacement. Withdrawals/rights/custody downgrades durably deny source/subject revisions before external index removal; invalidate descriptions/exact lookups/relationships/citations/caches, then retry idempotent deletion to verified completion. Recheck eligibility after external awaits and before serialization.
- Rollback to a prior complete approved manifest revalidates current source rights/tombstones. It cannot resurrect withdrawn material; if prior snapshot is unsafe, keep its audit artifact and expose eligible exact/document fallback with explicit gaps. Historical FY evidence is distinct from source supersession/revocation. No candidate preview or automatic cross-store execution is added.

## Out Of Scope

- New embedding provider
- Global visibility policy changes
- Automatic cross-store expansion
- Bulk paid indexing in this turn
- OpenAI expert overwrite
- Court-corpus migration
- Deployment in this turn

## Prior Art

Verified during ticket enrichment on 2026-09-10. Read these existing owners before implementing. New files and signatures below are proposed work.

- **Code** — [scripts/release/kansas-fiscal-document-ingest.py](../scripts/release/kansas-fiscal-document-ingest.py): `load_manifest`. Document-only parsing currently; dispatch before field assumptions.
- **Code** — [scripts/release/kansas-fiscal-document-ingest.py](../scripts/release/kansas-fiscal-document-ingest.py): `plan_operations`. Existing removal-first desired-state replay by logical document.
- **Code** — [packages/svs_common/svs_common/ingestion.py](../packages/svs_common/svs_common/ingestion.py): `IngestionService.ingest_now`. Reuse provider/index/usage service, typed extension avoids fake CSV docs.
- **Code** — [packages/svs_common/svs_common/ingestion.py](../packages/svs_common/svs_common/ingestion.py): `embedding_profile_config`. Existing configured profile lookup.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService._hydrate_and_acl`. ACL hydration lacks mandatory fiscal publication/snapshot check independently of graph.
- **Code** — [packages/svs_common/svs_common/security.py](../packages/svs_common/svs_common/security.py): `build_qdrant_filter`. Existing mandatory scope/active/security and optional file-attribute filters.
- **Code** — [packages/svs_common/svs_common/qdrant_adapter.py](../packages/svs_common/svs_common/qdrant_adapter.py): `QdrantAdapter.delete_by_filter`. Existing removal API may return 0 on nonstrict failure; completion must be verified.
- **Code** — [apps/api/svs_api/main.py](../apps/api/svs_api/main.py): `update_vector_store`. Existing scoped idempotent store mutation seam for active manifest guard.
- **Code** — [packages/svs_common/svs_common/cell_graph.py](../packages/svs_common/svs_common/cell_graph.py): `cell_graph_profile_for_store`. Exact trusted tenant/business/store binding; graph flag is not eligibility.
- **Code** — [tests/test_fiscal_graph_routes.py](../tests/test_fiscal_graph_routes.py): `test_semantic_independent_even_with_invalid_graph_config`. Preserve semantic independence while adding candidate exclusion.
- **Code** — [tests/test_kansas_fiscal_document_ingest.py](../tests/test_kansas_fiscal_document_ingest.py): `test_plan_is_removal_first_and_repeat_upsert_is_a_noop`. Existing lifecycle replay seam.

## Current Evidence

The existing ingestion path is document-oriented. A graph-only publication check would leave candidate entity descriptions visible through ordinary semantic search, while partial corrections or withdrawals could leave stale results in another index.

The Prior Art anchors distinguish existing code from the missing behavior. Source inventory and earlier synthetic test passes do not establish real-source product acceptance.

## Implementation Notes

Follow [the agreed law-and-money handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md). Preserve existing canonical owners, native contract shapes and record-level evidence requirements.

Before a bulk retained-Markdown run, address the measured source-coordinate
gap in [the semantic/graph metadata handoff](../instances/ks-state-civics/research/semantic-graph-metadata.md).
The current text branch selects `markdown_docs_v1`; switching to the existing
PDF-Markdown chunker also does not preserve the CPU `<!-- page N -->` format.
Review `chunking.py:markdown_heading_chunks`, `pdf_markdown_external_chunks`,
`split_oversized`, and `ingestion.py:IngestionService.ingest_now` before choosing
a bounded source-specific path. Assign any shared chunker edit explicitly in
the build contract before implementation; no global chunker behavior change is
authorized by this planning note. Propagate exact revision/page/range mapping
through search-result hydration, keep tags outside retained bytes, and confirm
the effective embedding profile. The real Book 2 lapse must map to page 358;
whole-book line metadata or the observed erroneous page 214 cannot pass.

Use the shared-owner map in [build-contract.json](../.tranche/statecivics-semantic-graph/aligned/build-contract.json) and look up affected files/symbols in [stack.index.json](../.tranche/statecivics-semantic-graph/aligned/stack.index.json). These are local planning artifacts; their signatures describe future work unless marked existing. Runtime must not depend on worktree paths or these planning files.

### 2026-09-12 — P5-PLAN lane B: entity-projection ingestion

**Dispatch site.** `kansas-fiscal-document-ingest.py` has no record dispatch
today: `load_manifest` (:300) calls `_validate_record` (:137) unconditionally,
and that function's first act is a required-field loop that includes
`logical_document_id` — the one field A's entity branch deliberately omits.
`record_kind` appears zero times in the script (confirmed by grep count and by
an AST walk of the loop's literal tuple). An A B1 manifest therefore fails today
with `manifest line N: missing logical_document_id`, which is a shape error
masquerading as a data error.

The dispatch belongs at the top of the per-line loop in `load_manifest`, before
`_validate_record`: read `record_kind`/`record_version` from the line and route
to `_validate_record` (untagged) or a new `_validate_entity_record` (tagged),
raising on any other kind or version with no fallback. Keep the two record kinds
in separate id-uniqueness namespaces — the existing `logical_ids` set cannot be
reused, because entity identity is `(entity_logical_id, entity_revision)` and
`export_record_id` is the only field the two branches share.

**Store id.** Entity projections go to a NEW vector store, never
`vs_kansas_fiscal_documents_pending`, `vs_kansas_statutes_pending` or any
document collection. Proposed: `vs_ks_fiscal_entities_v1` (slug
`kansas-fiscal-entities`), its own source package and its own `source.lock.json`
pinned to the **entity** branch digest.

A new store id is NOT sufficient, and this is the round's sharpest finding.
`svs_biz_ks_state_civics_voyage_4_docs_1024` is a **Qdrant collection**, not a
store id, and `QdrantAdapter.collection_name` (qdrant_adapter.py:40) derives it
from `business_instance_id` + `embedding_profile_id` + index-version suffix —
`vector_store_id` is not an input. A new store on the same instance with
`voyage_4_docs_1024` lands its points in exactly the shared collection that the
instruction forbids, beside the 83,858 statute + fiscal document points. Keeping
entity points out of it requires a **distinct embedding profile**, e.g.
`voyage_4_entities_1024`, giving `svs_biz_ks_state_civics_voyage_4_entities_1024`.
That is an owner decision: it is a new profile, not a rename.

**Lifecycle.** `ingestion.action == "remove"` DELETES the point; it does not
write a tombstone. A's removal record is identity-minimal by construction (no
`entity`, no `description`, no `derivation`), so there is nothing to retain and
retaining a shell would be a fabricated record. The tombstone lives upstream in
A's ledger, where `lifecycle.state` and `replaced_by` are columns; B's store
holds current state only. Mirror the existing `updatePolicy`: removal-first,
dry-run required. `lifecycle.removal_required` must agree with the action, as
`_validate_record` already enforces for documents (:233).

**Idempotency.** Extend `ingest_idempotency_key` (:530) rather than adding a
second scheme: key on `(vector_store_id, entity_logical_id, entity_revision,
action, record_digest_sha256)`. `record_digest_sha256` already covers A's
description text and template hashes, so a re-export that changes nothing
re-plans as a noop, and a changed description re-embeds exactly once. Do not key
on `export_record_id` alone — A derives it from entity kind, logical id,
revision and exporter version, so an exporter version bump would re-embed the
whole store for no semantic change.

**Spend.** See WAVE-133's note: fake embedding provider in tests, one real run of
at most 20 descriptions in `ks-fiscal-local`, under 5,000 tokens total.

## Deliverables

- [scripts/release/kansas-fiscal-document-ingest.py](../scripts/release/kansas-fiscal-document-ingest.py) — Single upstream manifest consumer gains explicit record dispatch. Shared file owner: WAVE-134. Edit sequence: WAVE-134.
- [packages/svs_common/svs_common/ingestion.py](../packages/svs_common/svs_common/ingestion.py) — Typed fiscal descriptor indexing through existing profile/provider/index clients. Shared file owner: WAVE-134. Edit sequence: WAVE-134.
- [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py) — Mandatory ordinary dense/sparse/exact hydration checks. Shared file owner: WAVE-135. Edit sequence: WAVE-134 → WAVE-135 → WAVE-136.
- [packages/svs_common/svs_common/security.py](../packages/svs_common/svs_common/security.py) — Fiscal-only forced payload predicates, no other-domain policy change. Shared file owner: WAVE-134. Edit sequence: WAVE-134.
- [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py) — Guard active complete manifest and lifecycle invalidation. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [apps/api/svs_api/main.py](../apps/api/svs_api/main.py) — Existing graph staging and guarded store-pointer transition. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [scripts/release/kansas-fiscal-graphrag.py](../scripts/release/kansas-fiscal-graphrag.py) — Existing load/activation/rollback preflight extension. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-136.
- [tests/test_kansas_fiscal_document_ingest.py](../tests/test_kansas_fiscal_document_ingest.py) — Dispatch, removals, failed/repeated replay. Shared file owner: WAVE-134. Edit sequence: WAVE-134.
- [tests/test_fiscal_graph_routes.py](../tests/test_fiscal_graph_routes.py) — Graph-off candidate exclusion and late revocation. Shared file owner: WAVE-134. Edit sequence: WAVE-134 → WAVE-135.
- [tests/test_fiscal_graph_postgres.py](../tests/test_fiscal_graph_postgres.py) — Canonical eligibility, complete activation, rollback and failure proof. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [tickets/WAVE-134-fiscal-projection-ingestion-lifecycle.md](WAVE-134-fiscal-projection-ingestion-lifecycle.md) — NEW: scoped projection/lifecycle follow-up. Shared file owner: WAVE-134. Edit sequence: WAVE-134.
- `packages/svs_common/svs_common/fiscal_projection.py` (planned new file) — NEW: one fiscal eligibility/hydration adapter, shared with retrieval/traversal/citations. Shared file owner: WAVE-134. Edit sequence: WAVE-134.

Expected integrated output: WAVE-134 stages eligible entity descriptor points through existing scoped ingestion/profile/index clients and activates only a complete verified manifest through a guarded scoped pointer transition. One refreshed eligibility predicate excludes candidate/denied/wrong-scope records from ordinary graph-off dense/sparse/exact retrieval, traversal and final citations. Replay/removal/late revocation/failure/rollback proof demonstrates durable denial before index deletion, no fake chunks, no hidden partial success, preserved prior approved view, and rollback that cannot resurrect withdrawn evidence.

## Acceptance Criteria

- Extend existing scoped API/ingestion/provider/source services to consume the upstream KS-650 document and entity/relationship record variants. Preserve document-export compatibility and use a bounded adapter if needed; StateCivics is not required to implement the provisional statecivics.fiscal-graph-publisher.v1 envelope. No direct authoritative StateCivics database writes or second exporter stack.
- Record source/canonical revision, publication/correction state, snapshot/as-of, template and raw/parsed extraction identities, profile/run identity, eligibility and complete graph manifest. Apply explicit record-level prerequisites rather than assuming schema existence means producer/readiness.
- Use a consistent policy for ordinary semantic search, exact retrieval, graph expansion and citation hydration. Candidates and ineligible records must be absent from ordinary semantic results even with graph expansion disabled. If private candidate preview exists, enforce separate explicit authorization. Enforce redistribution, license_profile, custody_status, current/superseded/corrected/withdrawn and removal_required handling.
- Make ingest/replay idempotent and reconcile corrections/supersession/withdrawal/removal across descriptions, exact records, relationships and source citations. Activate only a complete eligible manifest; retain a prior approved snapshot and verify rollback after partial failure. Historical as-of access, if allowed, is explicit and cannot expose withdrawn material contrary to source policy.
- Use each store configured embedding profile and encode queries accordingly. Keep profile compatibility and index separation explicit; canonical-ID joins do not require equal vector dimensions or raw-score comparability across stores. Any cross-store access requires an explicit allowlist and compatible declared source snapshot, with no automatic expansion.
- Focused ingestion and search tests prove idempotent replay, complete-manifest activation, revision correction/removal, ordinary-search candidate exclusion, source/audience isolation, raw/parsed distinction and correctly selected query/profile pairs. Preserve other tenant/source scopes and existing uncommitted runtime work during planning.

## Dependencies

- Canonical prerequisite: KS-650
- Canonical prerequisite: WAVE-133

Dependencies apply to the specific contracts, evidence and eligible records consumed here. Do not wait for unrelated payments/forecasts/outcomes or the full K.S.A. harvest. KS-613 keeps its existing scope; KS-651 owns the separate generalization benchmark.

## Verification

Run after implementation in the required test environment; these commands were not executed during ticket drafting.

```sh
pytest -q tests/test_kansas_fiscal_document_ingest.py tests/test_fiscal_graph_routes.py tests/test_fiscal_graph_postgres.py
```

Graph-off/unscoped candidate exclusion, stale injected points, late revocation, failed deletion, partial activation, safe rollback and scope/profile isolation.

StateCivics commands must use scripts/run_gate.sh statewide; no host dependency installs. ExAIS pytest commands run inside its existing configured test/container environment; PostgreSQL proof needs explicitly disposable SVS_FISCAL_GRAPH_TEST_DATABASE_URL and cannot count skipped tests as passed. Real-source product acceptance is separate from synthetic tests.

## Risks

A failed index deletion or partial update can expose withdrawn material. One current eligibility owner must reject stale/candidate results even when graph expansion is disabled; rollback must not re-enable withdrawn content.

## Rollback

Stop new fiscal projection ingestion and serving, reconcile removals, and restore only a complete generation that is still eligible. Never revive corrected/withdrawn records merely to restore an older index.

## Implementation Log

The owner has prioritized Tier 2 on 2026-09-10: populate the existing chunk
page/character columns from retained page-marked Markdown, before attaching
canonical legal references. The StateCivics manager reports all 13,181 current
chunks lack page/character coordinates; this is reported operational evidence,
not a new ExAIS database measurement.

The bounded document-coordinate increment starts independently of canonical
KS-600/650 records. Its exact active-worktree files/owner are assigned in
`build-contract.json:document_coordinate_increment` and `stack.index.json`.
An explicit StateCivics page-chunking profile preserves the current embedding
mode/provider and existing non-opted-in/PDF behavior. Preview and ingestion use
the same parser; chunks are exact original-text slices with page bounds and
zero-based, end-exclusive Unicode code-point offsets. Profile-aware replay must
not silently reuse old unlocated chunks or duplicate canonical document identity.
No live reindex, paid embedding batch or deployment is performed by this increment.

Canonical action references belong to reviewed exact span-to-action bindings.
A chunk may overlap section 96(i) and 96(j); it must not acquire either action
merely from keyword or label matching. This increment creates no such references.
Full canonical entity/lifecycle integration retains the dependencies and
acceptance criteria above.

The bounded coordinate increment is implemented and verified offline. See
[implementation proof](../.tranche/statecivics-semantic-graph/aligned/wave-134-document-coordinate-proof.md)
and [second independent QC](../.tranche/statecivics-semantic-graph/aligned/wave-134-document-coordinate-qc-2.md),
which returned PASS WITH NOTES after two initial review findings were fixed.
Root's combined regression passed 490 tests with zero skips; the independent
focused run passed 106 with zero skips. All seven retained Session Laws books
were exercised. Separate disposable PostgreSQL checks verified profile migration,
evidence-context changes, dedupe, retries and source/tenant scope. Full migrated
API/backend integration, live replay and the canonical projection acceptance
criteria above remain incomplete; this ticket stays in progress.

### 2026-09-13 — lane B increment: the entity/document record adapter

Filed under this ticket rather than a new WAVE id. The Scope bullet already
says "Entity branch uses WAVE-133 adapter"; the 2026-09-12 P5-PLAN note above
specifies exactly this dispatch, the store-id/profile finding and the branch
separation. A new ticket would split one deliverable across two ids.

**What landed.** `packages/svs_common/svs_common/statecivics_record_adapter.py`
reads a mixed JSONL manifest and returns branch-separated, branch-validated
records. It is a reader: no embedding, no API call, no upload, no store write.

* The routing comes from the contract, not from this repository. It reuses
  `statecivics_contract_pin.dispatch_subtree`, so the object it reads is
  byte-for-byte the one `DISPATCH_SHA256` pins, takes the tag key from the root
  `if.required` and each arm's `$defs` target from `then`/`else`, and maps each
  target back to a pin name through `BRANCH_ROOTS`. `EXPECTED_DISPATCH_REQUIRED`
  is a cross-check asserted against the contract, never the source, so a
  re-rooted dispatch fails by name rather than only as a digest mismatch.
* A record is validated against the branch the dispatch chose and refused there
  by name. The document branch is NOT relaxed to admit entity records; a test
  asserts both entity fixtures fail `legacy_document_record` while passing
  `entity_projection_envelope`.
* `entity_collection_name` refuses when the entity collection would equal the
  document one. `QdrantAdapter.collection_name` takes
  `(business_instance_id, embedding_profile_id)` and NOT `vector_store_id`, so a
  new vector store separates nothing; the embedding profile is the only
  separator and choosing one stays an owner decision, so both profile ids are
  arguments.

**`load_manifest` is untouched** — signature, body and contract-pin enforcement.
The adapter reads the manifest itself and verifies only the pins for branches it
actually saw, matching `ENFORCED_PINS`. It therefore adds no `load_manifest`
call site, so the discovered/declared `contractPin.enforcedAt` sets stay equal
and `test_every_load_manifest_caller_enforces_the_pin` is unaffected. Asserted
structurally by `test_the_adapter_adds_no_load_manifest_call_site`.

**Validation scope, stated rather than implied.** There is no `jsonschema` in
this repository, so the evaluator is bounded to the pinned contract's keyword
vocabulary, and `SUPPORTED_KEYWORDS` is closed: an unimplemented keyword raises
instead of being ignored. Remote `$ref` is not followed — the same policy
`branch_closure` already applies — and every unfollowed ref is reported in
`unvalidated_remote_refs`, so the two KS-600 payload contracts and the
source-artifact vocabulary are named as unchecked rather than silently skipped.
Offline corroboration: the evaluator's verdicts were compared against
`jsonschema` 4.26.0 + `rfc3339-validator` (installed in a scratch venv only,
never a repo dependency) over the fixtures and a 34-case mutation battery
covering every keyword class the contract uses — 44 cases, 0 disagreements.

**Fixtures** (`tests/fixtures/statecivics-*.jsonl`, 7.7 KB total). The legacy
document record and both entity payloads are StateCivics' OWN committed fixtures
at 314beafe, fetched with `git show`, never invented; the entity envelopes
reproduce `entity_projection.build_entity_record` at that commit.

**Not verified here.** No live ingestion, no descriptor indexing, no idempotency
key change, no `source.lock.json` for an entity store, and no owner decision on
the entity embedding profile. The KS-600 `entity` payloads are not validated by
this adapter by construction. Those remain open under this ticket.
