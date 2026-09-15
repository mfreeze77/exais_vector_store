# WAVE-134: Ingest scoped projections with consistent eligibility and lifecycle

> **Civic Impact work paused by owner — 2026-09-14.**
> [Current delivery, pending CI and resume order](../runbooks/civic-impact-pause.md) supersede older dispatch instructions. Historical proof and unmet acceptance criteria remain.

Status: paused by owner — local HB 2513 candidate ingestion/retrieval is merged and pushed. CI repair is pushed but unmerged pending the scoped upstream secret and hosted green run. Broader publication/lifecycle acceptance remains open. The old Item 8 block is not the current candidate-runtime state; see the pause record.

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

### 2026-09-13 — lane B round two: the validator, the collision guard, the check

Quality control FAILED the lane B increment at `664f62c`. Three fixes, none
touching `load_manifest` or the document consumer.

**F1 — the validator was fail-open inside classes its own battery "covered".**
QC reproduced the round-one cross-check independently, extended it to 93 cases
and found six divergences from `jsonschema`: five fail-open, three reachable on
the unmodified pinned contract. The two decisive ones: `value != schema["const"]`
used Python equality, and `True == 1`, so `record_version: true` satisfied
`const: 1` and was ADMITTED through the kind/version gate the contract calls
"sufficient on its own to refuse an unknown kind or version"; and `format: date`
was a shape regex, so `2026-02-31`, `2026-13-99` and `0000-99-99` all passed on
both branches. Round one's battery covered every keyword by NAME and agreed on
all of them -- the defects were in their SEMANTICS. That is WAVE-133's defect
class one layer inside the check built to avoid it.

Fixed semantically, not renamed:

* `const` / `enum` — typed equality (`_json_equal`). A boolean is never equal to
  a number; an int and a float of equal mathematical value are equal.
* `format: date` / `date-time` — parsed by `datetime`, offset REQUIRED on
  date-time. A local time is not an instant.
* `uniqueItems` — a typed equality key, so `[true, 1]` is unique and `[1, 1.0]`
  is not.
* `type: integer` — accepts integer-valued floats, per draft 2020-12. That was
  QC's fail-CLOSED finding.

The single `SUPPORTED_KEYWORDS` set is replaced by `EXACT_KEYWORDS` /
`APPROXIMATED_KEYWORDS` / `ANNOTATION_KEYWORDS`, disjoint and asserted disjoint,
with everything outside all three still raising. What remains approximate is
DISCLOSED through the `unvalidated_remote_refs` mechanism: a second channel,
`RecordValidation.unsupported_keyword_semantics`, whose exact value is pinned by
a test. Today it is `("format:uri", "pattern")` for the mixed manifest and
`("pattern",)` for an entity record alone.

Cross-check re-run with `jsonschema` 4.26.0 + `rfc3339-validator` in the SCRATCH
venv only, organised by SEMANTIC boundary rather than by keyword name, at least
three near-miss cases per boundary: **86 comparable cases, 0 disagreements**
across bool-vs-number (28), date-calendar (15), datetime-calendar (13),
int-vs-float (13), whole-record fixtures (10) and uniqueitems-nested (7). The
`format: uri` divergence is reported separately and is fail-CLOSED: `jsonschema`
registers no `uri` checker without the optional `rfc3987`, so it accepts what
this refuses. It is unreachable through this contract, whose only `uri`-formatted
required field also carries `pattern: ^https?://`.

Honest limit, recorded because the cross-check cannot show it: `pattern` uses
Python `re` in BOTH implementations, so a cross-check against `jsonschema`
cannot detect ECMA-262 divergence. Only replacing the evaluator can, which is
[WAVE-145](WAVE-145-adopt-jsonschema-and-retire-the-hand-written-evaluator.md),
filed in the same commit.

**F2 — the collision guard asked its caller for the hazard.** It took
`document_embedding_profile_id` as an argument, so QC's probe -- pass a document
profile that is not the statute profile -- got the REAL shared statute collection
back with no collision raised, and `entity_embedding_profile_id=None` returned
the degenerate `ks_civics_biz_ks_state_civics_`. The document side is now READ
FROM THE INSTANCE TREE by `read_instance_collection_roster`: `instance.yaml` for
`businessInstanceId` and `storage.qdrant.collectionPrefix`, each store's own
source package for `ingestion.embeddingProfile`. `EntityCollectionCollision`
fires against ANY declared document collection, whatever the caller passes; an
empty or non-string entity profile is refused rather than resolved.

Two further refusals, both failing toward blocking:
`DocumentCollectionRosterIncomplete` when a store declares no embedding profile,
because a non-collision guard that cannot enumerate what it must avoid has no
answer; and `InstanceCollectionConfigError` when the adapter's settings prefix
disagrees with `instance.yaml`, because names computed for another cell are not
an answer about this one.

**Finding, from the real tree.** Only `kansas-statutes` declares an
`ingestion.embeddingProfile` (`voyage_4_docs_1024`). `kansas-fiscal-documents`,
`kansas-court-decisions` and `topeka-municipal-code` declare none in any source
package, so the real instance CANNOT pass this guard today, and a test asserts
that refusal by name. Declaring those profiles is prerequisite work for entity
ingestion under this ticket.

**F3 — the separation test asserted `X == X`.** It computed
`statute_collection` and `document_collection` with the same call and the same
arguments. Both halves are now independent: the statute collection comes from
`instance.yaml` + the statute store's `source.yaml` and is asserted equal to
`ks_civics_biz_ks_state_civics_voyage_4_docs_1024`, the CONFIGURED name. Round
one asserted `svs_biz_ks_state_civics_voyage_4_docs_1024`, which was taken from
this ticket's planning note and is not what the config resolves to: the prefix is
`ks_civics_`, not `svs_`, and the business instance id is `biz_ks_state_civics`,
not `biz-ks-state-civics`.

**Baseline, R-P9, regime beside every count.** Corpus vars are
`SVS_STATUTE_EXPORT_ROOT`, `SVS_STATUTE_CORPUS_ROOT`, `SVS_STATUTE_CUSTODY_ROOT`,
`SVS_STATUTE_ROLLOUT_SEED`. Measured on `main` at `cc01547`: regime UNSET, 10
failed + 31 errors = 41 ids; regime SET, 7 failed + 31 errors = 38 ids. This
supersedes the "5 + 31 = 36" figure reported in the round-one log entry above,
which was measured with `PYTHONPATH` exported and did not state its regime.

### 2026-09-13 — lane B round three: deployment-resolved collections, jsonschema adopted

Round two's F1/F2 approach is REPLACED, on the owner's instruction, after the
owner measured the running deployment rather than the checked-in YAML.

**R1 — collections resolve from the target deployment.** Round two derived
document collection names from `instance.yaml`'s
`storage.qdrant.collectionPrefix` (`ks_civics_`). That is faithful to the file
and wrong about the deployment. Confirmed independently here, from four places:
`config.py:31` defaults `qdrant_collection_prefix` to `svs_`;
`generate-cell-env.py` writes `svs_` in both its blocks; `.env.example` and
`.env.production.example` say `svs_`; and `docker inspect
exais-vector-store-ks-fiscal-local-api-1` shows `QDRANT_COLLECTION_PREFIX=svs_`
with no `SVS_INDEX_VERSION`. And `grep -rn collectionPrefix --include=*.py`
finds NO runtime reader — the YAML key is unread config. The prefix now comes
from the adapter's own settings, the same object `QdrantAdapter.collection_name`
reads; `instance.yaml` is consulted only for `businessInstanceId`. The
disagreement is [WAVE-146](WAVE-146-qdrant-collection-prefix-config-runtime-mismatch.md),
filed in this commit, because reconciling it either orphans 96,437 indexed
points or contradicts `.release/cells/ks-state-civics/.env.cell`.

**Both document collections are covered.** The running cell holds two, and only
one is named by a source package. The other,
`svs_biz_ks_state_civics_openai_text_embedding_3_small_1536` (12,579 points),
is declared in `instance.yaml` under `models.preferredEmbeddingProfiles`. The
roster reads both places, so both are enumerated and guarded; a test asserts the
resolved set equals exactly the two collections the cell holds. Nothing is
declared that the runtime does not use.

**R2 — an entity store is not a document store.** `entity_store_slugs` are
excluded from the document side entirely, so the guard can never fire against
the entity store itself; a test shows the same tree refusing without the
classification and resolving with it. Missing profiles are tracked per SOURCE,
never per store: round two collected profiles across a store's sources and
treated the store as declared if ANY source named one, which hid the other.
`topeka-municipal-code` really does carry two source packages, and QC's masking
reproduction is now a test. A store with no source package at all is reported
too, rather than silently contributing nothing.

**R3 — `jsonschema` adopted, hand-written evaluator RETIRED.** See
[WAVE-145](WAVE-145-adopt-jsonschema-and-retire-the-hand-written-evaluator.md),
now DONE. `jsonschema==4.25.1` (matching repo A's pin, so producer and consumer
judge the same record identically) and `rfc3339-validator==0.1.4` are pinned in
all four `apps/*/requirements.txt`. `FormatChecker` is passed explicitly, since
draft 2020-12 makes `format` an annotation by default. The vocabulary guard
survives, derived from `Draft202012Validator.VALIDATORS`. The
`unvalidated_remote_refs` policy is unchanged, and
`unsupported_keyword_semantics` survives with the same values —
`("pattern",)` / `("format:uri", "pattern")` — exactly as WAVE-145 predicted,
verified rather than dropped.

**R4 — nothing re-embeds.** No provider call, no API call, no store write, no
index touched. The only runtime interaction in this round was
`docker inspect` on the fiscal cell's api container, reading configuration.

**Release gate, NOT done here.** Adding a dependency changes every app image.
`.release/cells/*/.env.images` records immutable digests
(`SVS_IMAGE_API@sha256:867e4c15…` and four more). This commit changes the
requirements sets only; building the images and recording new digests is a
release action with its own approval, and I did not perform it. Until it is,
the running cell's images do not contain `jsonschema`, so this adapter must not
be invoked inside them.

**R5 — composition milestone: NOT STARTED, and BLOCKED. Two blockers, both
upstream, both reported rather than accommodated.**

*Blocker 1 — there is no candidate export to receive.* Repo A is on
`ks-600-a2-1-hb2513-slice` at `eb460ef4`. `git grep -- "--candidates" HEAD`
returns nothing; the only `candidate` hits in A are an unrelated political
candidate harvester. `eb460ef4` adds exactly one file,
`scripts/operator/ks600_a2_1_hb2513_slice.py`, which reads the operator database
and writes rows — it is not an export.

*Blocker 2 — and this one is structural.* The pinned contract's
`entity_eligibility.status` enum is `["reviewed", "published"]`. `candidate` is
NOT a permitted value, and the contract's own description says so in terms: "a
row that does not already say reviewed or published is not exported at all, so
only those two values can appear." A record stamped `eligibility.status =
"candidate"` is therefore **contract-invalid on the pinned entity branch**, and
B's adapter will refuse it — for the wrong reason. Refusing a candidate record
because the schema forbids the word is not the same deliverable as accepting it
into a candidate-only path and refusing it for the live entity store. Either the
enum must be extended upstream (which moves `ENTITY_BRANCH_SHA256` and requires
a deliberate re-pin here) or the candidate marker must live somewhere other than
`eligibility.status`. That is an owner/upstream decision and I have not guessed
at it.

*On the `source.url` warning.* Not reproducible at `eb460ef4`: the A2-1 slice
uses `source_url` (lines 411, 462), `sourceRef` in
`appropriation-action.schema.json` declares `source_url` under
`additionalProperties: false`, and `git grep '"url"'` over A's `civic_impact`
services returns nothing. More importantly, **B's adapter could not refuse it
even if it arrived.** The `entity` payload is validated by a REMOTE `$ref`
(`appropriation-action.schema.json`), which this module deliberately does not
resolve — it names a separate contract with its own pin. Such a record would
pass B's adapter with the ref reported in `unvalidated_remote_refs`. Making that
refusal real means pinning the two KS-600 payload contracts as fixtures the way
`retrieval-export-record.schema.json` already is, with their own digests. That
is new scope and a new pin, so it is reported here rather than improvised.

### 2026-09-13 — lane B items 6 and 8 (items 5 and 7 blocked on repo A)

**Item 6 — the live path refuses a candidate before anything is spent.**

`admit_entity_records(records, *, path)` is the gate. It is PURE: two
parameters, no client, no injected callable, no I/O seam, so there is no
arrangement of it that can spend money or write state before it decides. A test
asserts its signature is exactly `{records, path}` so that stays true.

`stage_entity_descriptors(records, *, path, collection, embed, index_write)`
calls the gate first, over the WHOLE batch, and raises out before the first
`embed`. Per-record refusal would have embedded the clean records ahead of the
candidate — the money is spent and the point is written whatever the refusal
then says — so a single candidate anywhere refuses the batch. `embed` and
`index_write` are keyword-only with NO defaults, asserted by test, so this
cannot be invoked into doing I/O by accident; this module holds no provider and
no index client.

The ordering proof does not assert "the spy list is empty afterwards", which
only holds for the run that happened. The callables DETONATE — they raise
`AssertionError("embed was called before the eligibility gate refused a
candidate")` — so an inversion fails loudly and names which call fired.

The named refusal reads:

> refusing entity record '…' (appropriation_action 'ks:2026:…' revision 1) for
> the live entity store: eligibility.status is 'candidate', and the live store
> admits only ['published', 'reviewed']. Stage it on the 'candidate' path
> instead. Nothing has been embedded or indexed.

Symmetry is enforced too: the candidate path REFUSES a reviewed record. A
reviewed revision parked among candidates is invisible to the live store that
should have had it. A missing or unrecognised `eligibility.status` raises
`UnknownEligibilityStatus` rather than being defaulted in either direction.

`candidate_collection_name` refuses when the candidate collection would equal
the LIVE entity collection, on top of the existing document-collection guard:
ordinary retrieval reads the live entity collection, so a candidate landing
there is served whatever the gate decided earlier.

**`format-nongpl` — the owner's correction was right and my round-three note was
wrong.** Verified from the installed 4.25.1 metadata rather than assumed:
`Provides-Extra: format, format-nongpl`; `format` pulls GPL `rfc3987`, while
`format-nongpl` pulls `rfc3986-validator>0.1.0` and `rfc3987-syntax>=1.1.0`,
neither GPL. All four requirements sets now pin
`jsonschema[format-nongpl]==4.25.1`. With it installed, `uri` asserts
(`'not a uri'` and `'/relative/path'` refused, `urn:isbn:…` accepted), so
`format:uri` drops out of `unsupported_keyword_semantics` **on its own** — the
set is derived from the checker registry, so no code changed, only the
expectation. The disclosure tuple is now `("pattern",)` on BOTH branches.
WAVE-145's prediction therefore held for `pattern` and did NOT hold for
`format:uri`; both are recorded rather than quietly adjusted.

**Divergence this creates, which must reach A.** Repo A pins
`jsonschema = "4.25.1"` with NO extra: `grep -c` over A's `poetry.lock` finds
`rfc3339-validator` (1) but `rfc3986-validator` (0), `rfc3987-syntax` (0) and
`rfc3987` (0). So A asserts `date`/`date-time` and does NOT assert `uri`. After
this change B is STRICTER than A on `uri`, which is the opposite of "both repos
validate identically". The direction is fail-closed for B, and the exposure on
this contract is exactly one field: `retrieval_url` on the document branch,
which is the only `uri`-formatted field with no `pattern` beside it
(`citation_url` carries `pattern: ^https?://`; the entity branch has no
`uri` field). **A should add the same extra.** Until it does, a record A accepts
could be refused by B for a `retrieval_url` reason — which for item 7 would be
the WRONG refusal.

**Item 8 — PROPOSED RELEASE ACTION. NOT EXECUTED.**

Nothing below was run. No image was built, no digest recorded, no `.env.images`
written, no container touched.

Scope: four of the five app images change. `apps/{api,worker,model_gateway,
instance_agent}/Dockerfile` each `COPY <app>/requirements.txt` then
`pip install`, and each also `COPY packages/`, so both the new dependency and
the adapter source land in them. `apps/admin_ui/Dockerfile` contains no
`requirements.txt` reference and copies only `apps/admin_ui`, so admin-ui is
unchanged by this branch — its `.env.images` line is rewritten by the publish
step but its content does not change.

```sh
# 1. Build. Version comes from VERSION (0.9.8-production-candidate).
python scripts/release/build-images.py \
  --service api --service worker --service model-gateway --service instance-agent \
  --manifest-output .release/image-build-manifest.json

# 2. Publish and record the pinned digests for the target cell.
python scripts/release/publish-images.py --cell ks-state-civics

# 3. The five SVS_IMAGE_* lines in .release/cells/ks-state-civics/.env.images
#    are rewritten by step 2. Superseded values, for rollback:
#      SVS_IMAGE_API            @sha256:867e4c1540927c1bc1a5d77741ff1fbe5dc2111eb9129c094caf4c673b56fcce
#      SVS_IMAGE_WORKER         @sha256:60577793484ed5947c4c119ab1c5664325450bdc97d0f37ea78cd6079debe2a1
#      SVS_IMAGE_MODEL_GATEWAY  @sha256:60f2dd5137a54b6e3acda4167594f4e81882fe82a156686e3b269d4b1c3cadbd
#      SVS_IMAGE_ADMIN_UI       @sha256:aebffd553eaf86ee87752c9f696e816cc0a8d63e4fd27f006fa2e84bdc90941e
#      SVS_IMAGE_INSTANCE_AGENT @sha256:55868ba8ed9e274c067f6c2653934fa9de6ea78a9931b35679f3dba26040ecce
```

Gate: item 7's proof runs in the TEST image, never inside the running cell
(`exais-vector-store-ks-fiscal-local-*`). Until the rebuild is executed, that
cell's images do not contain `jsonschema`, so this adapter must not be invoked
inside them. `rpds-py` (via `jsonschema` → `referencing`) is a compiled wheel;
the platform matrix should be confirmed during the build, not after.

**Item 5 — BLOCKED on A.** Waiting on A's published three digests from A's new
main. When they arrive I re-derive all three MYSELF with `branch_digests` over
`git show <A sha>:contracts/civic-impact/retrieval-export-record.schema.json`
rather than copying A's values, re-pin `ENTITY_BRANCH_SHA256` only, add the
`("entity", <old commit>, <old digest>)` supersession triple in the existing
`SUPERSEDED_BRANCH_SHA256` form, and assert `DOCUMENT_BRANCH_SHA256` and
`DISPATCH_SHA256` unchanged.

**Item 7 — BLOCKED on A.** Needs the two real HB 2513 revision-2 records. Held
in place meanwhile:
`test_the_pinned_contract_still_forbids_the_candidate_status` asserts the enum
is still `["reviewed","published"]` at 314beafe and that a candidate record is
refused by `adapt_records` today — so the day item 5 lands, that test fails and
says exactly what to update. The no-fallback-to-revision-1 requirement is the
one that would fail silently, and it is not testable here: B receives whatever
records A's as-of selection emits and cannot see the rows it did not choose.
B's side of it is that `(entity_logical_id, entity_revision)` is the identity
and revision 1 and 2 are distinct records; proving the as-of query does not
quietly pick revision 1 requires A's selection, and the test must assert the
emitted revision is 2 for both records.

### 2026-09-13 — lane B items 5 and 7: the re-pin, and the composition milestone

**Item 5 — re-pinned, all three digests re-derived here, not copied.**

Re-derivation is a two-step check, because a mismatch is only meaningful if the
two sides agree on the method first. My walker (`branch_digests`) was run on the
PRE-change contract and reproduced all three current pins exactly
(`d3a7212a…`, `d5248a54…`, `03dc1784…`), which mirrors A's own corroboration
method. Only then was it run on `git show 24c9d3de:<contract>`:

| branch | re-derived here | vs A published | moved |
|---|---|---|---|
| document | `d3a7212a4873a2f375d451e74ab4d5f11a56ff50bbbeb5a162dae1f8640807e2` | match | no |
| entity | `52fd9ee50585c805664a39f5548ba04d00c0ac1a16c4095e2149d06451817058` | match | YES |
| dispatch | `03dc178429d04275f7b49a6d4ab9e05ee56bc970a31de78268942eb3de3b7940` | match | no |

`ENTITY_BRANCH_SHA256` re-pinned, `PINNED_BRANCH_COMMIT["entity"]` → 24c9d3de,
supersession triple `("entity", "314beafe…", "d5248a54…")` recorded in the
existing form, and both `source.lock.json` / `source.yaml` pin blocks updated
(`supersededEntityBranch` becomes a LIST, since there are now two, with set
equality asserted against the module in both directions). Fixture replaced with
A's file at 24c9d3de and renamed accordingly; byte-identity re-asserted against
`git show`, and `git diff` of A's contract 314beafe→24c9d3de confirms the whole
change sits inside `$defs.entity_eligibility` — which is *why* document and
dispatch did not move. **This is the first time the per-branch pin has had a
real constraint change to carry, and it did what it was built for.**

**Two things the re-pin forced that were not in the instruction, both reported
rather than done quietly.**

1. `PINNED_CONTRACT_COMMIT` is GONE. It was defined as the document branch's
   commit and documented as "valid only while the three agree". They stopped
   agreeing at 24c9d3de, and `test_the_fixture_is_the_upstream_contract_at_the_pinned_commit`
   used it to fetch the blob for the byte-identity check — so leaving it would
   have compared the new fixture against the file at 314beafe. It is replaced by
   `FIXTURE_CONTRACT_COMMIT`, the commit the FIXTURE BYTES came from, which is a
   different fact from any branch pin. A test asserts the old name is absent,
   that document and dispatch still agree with each other, and that entity does
   not agree with them.
2. **`24c9d3de` IS NOT AN ANCESTOR OF A's `main`.** It is 13 commits ahead on
   `ks-600-a2-1-hb2513-slice` and reachable from that branch and no other. The
   provenance check required ancestry of `main`, on the stated ground that
   pinning to an object no branch reaches is how a pin outlives the work it
   pinned. I did not weaken that check to a pass. `PROVISIONAL_BRANCH_COMMIT`
   now records `{"entity": "ks-600-a2-1-hb2513-slice"}`; the commit must still
   be an ancestor of the branch named beside it, so the check is still "say
   where this lives", not "any object will do". **It carries its own staleness
   tripwire: the moment 24c9d3de merges to main, the test FAILS and tells you to
   delete the entry** — a pin left provisional after its branch merges is
   indistinguishable from one that was never checked. `document` and `dispatch`
   are asserted never to be provisional.

**Item 7 — the milestone, proved on the record I could verify, and NOT on the
parts I could not.**

Proved, on repo A's committed `_provision_record()` at 24c9d3de — the real
HB 2513 Sec. 15(b) provision, `entity_logical_id f4cf16d51a93…`,
`entity_revision 2`, `eligibility.status "candidate"`. Lifted by `git show` and
parsed with `ast`, so nothing in A's tree was imported or executed and A's
working tree was never read.

1. **VALID** under the widened contract, through the full reader, and — the part
   that makes the re-pin load-bearing — the *identical* record is shown INVALID
   against a copy with the pre-change enum restored.
2. **REFUSED by the live path** with the named refusal, naming the logical id
   and `revision 2`. Sharpened so the refusal cannot be for the wrong reason:
   the record validates cleanly, and the same record with only `status` changed
   to `reviewed` or `published` passes the live path. Ordered: the detonating
   callables show zero embed and zero index calls.
3. **ACCEPTED by the candidate path**, embedded once, written to the candidate
   collection.
4. **NO FALLBACK**: the emitted `entity_revision` is asserted to be 2. The test
   also builds the revision-1 twin and demonstrates it would be admitted by the
   live path — i.e. on arrival a silent fallback is indistinguishable from a
   legitimate live record, which is exactly why the assertion has to be on the
   revision as emitted. A's compiled-SQL proof is the other half and B cannot
   see it.

**WHAT I COULD NOT VERIFY — four supplied values do not appear at the fixed sha,
and nothing was reconstructed to cover the gap.**

* The candidate MANIFEST `sha256 8b495ed7d427c41639fe3d18db91e2255de112f331fdb3728af37539708f1f95`
  is not a committed file at 24c9d3de and is not on disk anywhere I can read
  (searched `~/Developer` and both project trees).
* The **appropriation_action ENVELOPE does not exist** at the fixed sha. A
  committed its KS-600 *payload* (`VALID_ACTION_PAYLOAD`) and a full envelope
  for the provision only. Assembling an action envelope would have meant
  inventing `export_record_id`, `record_digest_sha256`, `as_of`, `exporter` and
  the three relationships — writing the milestone instead of proving it. So
  `export_record_id f3f72004…` is unverified and appears nowhere on disk, and
  the edge set (`action_relies_on_provision`→rev 2,
  `action_enacted_by_bill_version`→4782, `action_supersedes_action`→rev 1) is
  **unproved on B's side**.
* Provision `record_digest_sha256`: supplied as `f504a500b9f0e80b…`; A committed
  **`0a6fd52238749d4c…`**. The fixture carries A's committed value.
* `exporter.code_commit`: supplied as the exporter commit `24c9d3de…`; A
  committed **`cda8d7937abbf3ef2e254aa1a0216415d5d598be`**.
* Observation for A, not resolved here: the envelope says `entity_revision: 2`
  while its KS-600 payload carries `provision_reference_revision: 1`, and
  `VALID_ACTION_PAYLOAD` carries `revision: 1` / `provision_reference_revision: 1`.
  That may be deliberate (payload fields are the row's own columns) or it may be
  the fallback this ruling is about. B cannot tell, and B does not validate the
  payload — it is a remote `$ref` with its own pin.
* `entity.source` keys: the coordinator's list is for the ACTION payload. The
  provision's evidence entry carries
  `{source_revision_id, source_span_id, locator}` and **no stray `url`**, which
  is asserted.

So: **three of item 7's four proofs are complete on a real record, and the
fourth is complete for the provision.** The milestone is NOT complete for the
appropriation_action, and the manifest-level proof is not started, both for want
of artefacts that do not exist at the sha I was given. Send the manifest file
(or commit it) and the action envelope, and the remaining half is a short step.

**Item 8 remains PREPARED AND NOT EXECUTED.** No image built, no digest
recorded, no `.env.images` written, no container touched.

### 2026-09-13 — item 7 COMPLETE: both HB 2513 revision-2 records

The artifacts landed at A `5e9b88cc`. Verified before use, not after:
`tests/fixtures/civic_impact/ks600-a2-1-entities-candidates.jsonl` read with
`git show`, sha256 `8b495ed7d427c41639fe3d18db91e2255de112f331fdb3728af37539708f1f95`
recomputed here and matching, two records, byte-identical to the copy committed
as `tests/fixtures/statecivics-ks600-a2-1-entities-candidates.5e9b88cc.jsonl`.

**The pin did not move, and that was checked rather than accepted.** The
contract at `5e9b88cc` is byte-identical to the committed fixture
(`9bd52e29…`), and all three digests recompute unchanged
(`d3a7212a…`/`52fd9ee5…`/`03dc1784…`). `PROVISIONAL_BRANCH_COMMIT` stays as-is,
with its merge tripwire armed.

**All four proofs, now for BOTH records** (parametrised over
`appropriation_action` and `provision_reference`):

1. **VALID** under the widened contract, individually and as a manifest through
   `adapt_manifest` — 2 entity records, 0 document records, pins
   `('dispatch', 'entity')`. And the identical records are shown INVALID against
   a copy with the pre-change enum restored, so the widening is load-bearing.
2. **REFUSED by the live path** with the named refusal, naming the logical id,
   the export record id and `revision 2`. Sharpened the same way as the
   provision: each record validates cleanly, and the same record with ONLY
   `status` changed to `reviewed` or `published` passes the live path AND stays
   valid — so the refusal is candidacy and nothing else. Ordered: the whole
   manifest on the live path produces **0 embed calls and 0 index calls**.
3. **ACCEPTED by the candidate path**, both records, embedded twice, written to
   the candidate collection.
4. **NO FALLBACK**: `entity_revision == 2` **and** payload revision `== 2`, for
   both records — A's fallback signature, asserted directly. The revision-1-twin
   test is kept and is what makes assertion 4 load-bearing: it shows the
   superseded twin WOULD be admitted by the live path, because revision 1 is
   `reviewed` and on arrival a silent fallback is indistinguishable from a
   legitimate live record.

**Edges, proved from the artifact** (all `basis: exact_shared_identifier`). The
four split three-and-one, which is what the contract requires — an action
carries the three its own columns support, a provision carries only its
supersession, because the action side owns that FK:

* action: `action_relies_on_provision` → provision `f4cf16d5…18998` revision
  **2**; `action_enacted_by_bill_version` → `4782`; `action_supersedes_action` →
  itself revision 1.
* provision: `provision_supersedes_provision` → itself revision 1.

Crossed against each other rather than against constants: the action's
`relies_on` target equals the provision record's own `entity_logical_id` and
`entity_revision`, and its `supersedes` target equals its own id at
`entity_revision - 1`. An edge pointing at revision 1 would be the fallback
wearing a different hat, so this is asserted explicitly.

**The revision discrepancy is closed, and the resolution went the other way from
what a guess would have produced.** The exporter was always correct; a
hand-written fixture at `fa74ca7a` had gone stale and was reused inside a
revision-2 envelope at `e84a4642`. Refusing to reconstruct the missing record
surfaced that. The values this repo carried from that fixture —
`record_digest_sha256 0a6fd522…` and `exporter.code_commit cda8d793…` — are gone
from both trees; the authoritative values are asserted from the committed
artifact:

| | export_record_id | record_digest_sha256 |
|---|---|---|
| action | `f3f72004…f742941` | `09164d89…bb14313` |
| provision | `f4c67403…5343684` | `f504a500…68efc80` |

both with `exporter.code_commit = 24c9d3de…`.

**One detail found while asserting, worth recording.** `eligibility.publication_allowed`
is `null` on the action and `false` on the provision. That is correct and the
contract says why — `civic_appropriation_actions` has no such column, so null
says "no column" rather than inventing a permissive default. My first assertion
used one value for both and failed; it is now asserted per entity type, because
a single assertion would have hidden the distinction rather than checked it.

**Item 7 is complete. Item 8 remains PREPARED AND NOT EXECUTED** — no image
built, no digest recorded, no `.env.images` written, no container touched.

### 2026-09-13 — round five: two real gaps closed, and the release proposal corrected

**Both gaps reproduced here before anything was changed.** The second was worse
than reported.

**Gap 1 — envelope and payload were never related.** Changing only the
ENVELOPE's `eligibility.status` to `published` leaves the PAYLOAD saying
`candidate`. Executed on both real records: schema-valid `True`,
`adapt_records` accepts, the live gate admits, **and the embed and index
callbacks are reached**. The revision twin (envelope 2, payload 1) was
schema-valid too. JSON Schema cannot express this — the two halves are
validated against different contracts and nothing relates them.

This was reported to me as a strength: "the same record with only `status`
changed passes the live path" was my own single-reason discrimination in item 7,
and it was proving the opposite of what it claimed. The test helper that built
those twins rewrote one half of the record, so every use of it was testing a
record that could not be true.

`assert_envelope_payload_agreement` compares `entity_logical_id`,
`entity_revision` and `eligibility.status` against the payload's identity,
revision and status, and refuses on any mismatch with the field and BOTH values
named. It runs in `adapt_records` after schema validation, and again in
`admit_entity_records`, because records can reach the gate without coming from
a manifest and every path to embedding runs through it. Removal records carry no
payload by construction and are skipped rather than failed. **No schema change:
the three digests recompute unmoved, asserted by test.**

**Gap 2 — the guards were not wired to the function that embeds.** This is the
sharper finding, and it is worse than "accepts a caller-supplied collection":
driving `stage_entity_descriptors` with
`svs_biz_ks_state_civics_voyage_4_docs_1024` embedded and indexed **into the
shared statute and document collection**. The collision guard, the roster, the
entity-store classification — all built, all passing their own tests, none of
them called by the function that writes points. A guard nothing calls does not
hold an invariant; it describes one. My own
`test_entity_records_never_reach_the_shared_statute_collection` passed
throughout, because it exercised a routing dict written in the test rather than
the staging entrypoint.

`stage_entity_descriptors` now resolves its destination through
`resolve_staging_collection`, which calls `entity_collection_name` /
`candidate_collection_name`. `collection=` became an ASSERTION: refused unless
it equals what the guards resolve, so it can no longer select anything. Every
guard is inherited through that seam — `DocumentCollectionRosterIncomplete` and
`EntityCollectionCollision` both now refuse from inside staging, before any
callback.

**Ordering proved by inversion, three times, each reverted by `git checkout --`
of the committed file with `git status --porcelain` empty after:**

| experiment | result |
|---|---|
| remove the cross-field rule from the gate | 3 tests fail, incl. the pre-embed ordering one |
| resolve the collection AFTER embedding | 4 tests fail; `AssertionError: embed was called before the eligibility gate refused a candidate` |
| honour the caller's collection again (the original defect) | `test_r5_2_a_caller_supplied_document_collection_is_refused` fails |

**Item 3 — release proposal corrected, and the finding that matters more.**

The proposal in the earlier log entry named the WRONG CELL. The running cell is
**`ks-fiscal-local`** (`exais-vector-store-ks-fiscal-local-*`), not
`ks-state-civics`. Two further facts found while correcting it, both verified:

* `.release/cells/ks-fiscal-local/.env.images` **does not exist** anywhere on
  disk — only `ks-state-civics`, `local`, `restore`, `restore-src`,
  `rm005-smoke` and `config-proof` are checked in. So the five superseded
  digests quoted earlier are `ks-state-civics`'s and are NOT the running cell's.
  The running containers report image ids `sha256:e7271b65…` (api) and
  `sha256:d66e0316…` (worker), which is what a rollback for THIS cell would have
  to be pinned against.
* **There is no application caller of `adapt_manifest` or
  `stage_entity_descriptors`.** `grep` over `scripts/`, `apps/` and `packages/`
  outside the adapter itself returns nothing, and this is now asserted by
  `test_r5_2g_there_is_no_application_caller_of_adapt_manifest`, which walks the
  tracked source and FAILS when such a caller appears — the moment a rebuild
  becomes meaningful. So a rebuild today would ship a library nothing invokes.

Wiring `adapt_manifest` into `kansas-fiscal-document-ingest.py`'s dispatch is
the remaining WAVE-134 scope and is P5-BUILD's first item, on the TEST image.
**The cell rebuild is authorized only after that caller exists and is tested —
not before. Item 8 stays PREPARED AND NOT EXECUTED**; the corrected proposal
must also be re-derived for `ks-fiscal-local` once that cell's env and image
pins are available, since the ones recorded earlier belong to a different cell.

**Merge order acknowledged.** A merges first and reports its merge sha; I then
delete the `PROVISIONAL_BRANCH_COMMIT` entry (its tripwire is designed to fail
at exactly that moment — that failure is the signal), re-derive all three
digests with my own walker against A's MERGE COMMIT, and report the three
digests together with the sha they were computed from. Then B merges.

### 2026-09-13 — F3, F4, the pin retirement, and a BASELINE RETRACTION

**F3 — a real staging bypass, reproduced before it was fixed.**

`assert_envelope_payload_agreement` returned silently whenever `entity` was
missing. Executed here: a record with `lifecycle.state: current`,
`ingestion.action: upsert` and its `description` intact — a tombstone by no
reading — but with its payload stripped was staged, embedded and indexed into
`svs_biz_ks_state_civics_voyage_4_entities_1024`. Absence of the thing being
checked was read as permission to skip the check.

The payload requirement is now decided by `ingestion.action`, with the lifecycle
asserted to agree with it. `record_kind` is NOT the discriminator: it says the
record is an entity projection and says nothing about upsert versus removal.

| action | lifecycle.state | removal_required | payload |
|---|---|---|---|
| `upsert` | `current` | `false` | REQUIRED |
| `remove` | `superseded` / `withdrawn` | `true` | FORBIDDEN |

A tombstone is valid to ADAPT and is refused for descriptor STAGING by
`RemovalRecordNotStageable`: it directs a DELETE and carries no description to
embed, so letting it through would either crash on the missing description or
embed something invented in its place.

Four checks, each by execution: a payload-less current upsert refused before any
callback (`entity` missing and `entity: null`, both entity types); six
contradictory action/lifecycle combinations refused; legitimate tombstones
adapt AND never embed, both halves, both states; existing valid upserts still
stage, as the positive control so the fix cannot be satisfied by refusing
everything. A fifth test pins the discriminator itself: two records with the
same `record_kind` and different actions get different payload requirements.

**F4** — `test_r5_1c` gains the "both halves are individually schema-valid"
precondition, so it cannot pass by a schema incidentally catching the mutation.
A related repair: the status-rule test now MIRRORS its mutation into the payload
instead of dropping it, so it isolates the status rule rather than tripping the
new payload rule.

**Pin retirement.** The provisional entry's tripwire fired, unprompted, on the
first run after A merged:

> `AssertionError: 24c9d3ded3... HAS merged to StateCivics main, so the
> provisional entry PROVISIONAL_BRANCH_COMMIT['entity'] = 'ks-600-a2-1-hb2513-slice'
> is stale. Delete it: a pin left provisional after its branch merges is
> indistinguishable from one that was never checked.`

`PROVISIONAL_BRANCH_COMMIT` is now `{}`, and the docstring says to keep it that
way.

**One deviation from the instruction, and the reason for it.** I was asked to
re-pin `ENTITY_BRANCH_SHA256` from `677d126d` and record a supersession triple.
Re-derived with my own walker at `677d126d`:

| branch | digest @677d126d | moved since 24c9d3de |
|---|---|---|
| document | `d3a7212a4873a2f375d451e74ab4d5f11a56ff50bbbeb5a162dae1f8640807e2` | no |
| entity | `52fd9ee50585c805664a39f5548ba04d00c0ac1a16c4095e2149d06451817058` | **no** |
| dispatch | `03dc178429d04275f7b49a6d4ab9e05ee56bc970a31de78268942eb3de3b7940` | no |

**The entity digest did not move**, so there was nothing to re-pin and no
supersession to record. `ENTITY_BRANCH_SHA256` is already that value.
`PINNED_BRANCH_COMMIT["entity"]` stays at `24c9d3de`, which is the commit at
which the branch actually last changed — the documented meaning of that field —
and is now an ancestor of A's `main`, so the provenance check passes against
`main` with nothing special about it. Writing `677d126d` there, or adding a
supersession triple for a digest that is unchanged, would have recorded
something false.

**Fixture manifest refreshed** to `677d126d`, sha256
`dd795e63359238697d57eca693307a04cebc0ec1888bae91113496d1878b61a8` recomputed
here and byte-identical to `git show`. The QC's nuance was verified rather than
taken on report — I diffed the two manifests field by field, and they differ in
EXACTLY two: `exporter.code_commit` (now `d3000e98...`, not `24c9d3de...`) and
`record_digest_sha256`. Every substantive field is identical, so item 7's
semantic conclusions carry over unchanged and only the digest assertions were
re-run. New digests asserted: action
`3479ae3bbc5b7df554230c8434510e2b6803ea281e9f38261791d1a2b68d9334`, provision
`14c01e5a8f9a6bf11902f741a52bd76dc3c5c86725525c6a30256e67eb2322b0`.

## BASELINE RETRACTION (R-P9)

**Every "regime SET" figure in the log entries above is WITHDRAWN. It was never
the SET regime.**

`SVS_STATUTE_ROLLOUT_SEED` pointed at
`~/Developer/statecivics-statute-ingestion/wave-139/seed-state.json`. That file
EXISTS, so the suite's `required()` helper — which checks `path.exists()` —
passed it. But its sha256 is `bfb88ed4...` and the rollout module demands
`SEED_SHA256 = b64003f370c161c45c6dc5384951ea787242cba56be6446b12327099755d5c2d`,
so every module-scoped fixture raised "unapproved seed hash" and the 31 setup
errors never cleared. I read those 31 errors as an environmental constant across
both regimes and reported the counts beside a label that was wrong. **Resolving
is not the same as correct, and a path check that only asks whether a file
exists cannot tell the difference.** This is R-P9's own failure mode occurring
inside the rule meant to prevent it.

The seed was located by matching that hash, not by guessing:
`~/Developer/statecivics-statute-ingestion/ks-fiscal-local-kansas-statutes.json`.

The regimes, re-measured with the same command on both sides:

| regime | main @`cc01547` | branch | set difference |
|---|---|---|---|
| corpus vars UNSET | 10 failed + 31 errors = **41 ids** | 10 failed + 31 errors = **41 ids** | empty both directions |
| corpus vars SET **(resolving)** | 7 failed + 4 errors = **11 ids** | 7 failed + 4 errors = **11 ids** | empty both directions |

**Neither number is a green baseline, and neither should be quoted as one.**
The 11 that survive the resolving regime are 4 `test_kansas_statute_tranches`
setup errors, 4 `test_fiscal_document_evidence` + 1 `test_statecivics_statutes`
subprocess-`PYTHONPATH` failures (WAVE-144), and 2 `test_kscourts_graphrag_load`
failures (missing `psycopg`). All pre-existing, none touched by this branch.

**F5 filed as [WAVE-147](WAVE-147-statecivics-envelope-payload-helper-robustness.md)**
against repo A, in the same commit that names it.


### 2026-09-13 — lane B landed

Merged to `main` as `1565a84` (`--no-ff`), branch tip `830ccb7`, ten commits.
`wave-134-entity-record-adapter` deleted after the merge.

Post-merge verification on `main`, same commands as the branch: corpus vars
UNSET 10 failed + 31 errors = 41 ids; corpus vars SET (resolving) 7 failed + 4
errors = 11 ids. Identical to the pre-merge measurements on both sides. Neither
is a green baseline — see the retraction above for what the 11 are.

Still open under this ticket, unchanged by the merge:

* **No application caller exists.** `adapt_manifest` and
  `stage_entity_descriptors` are invoked by nothing outside their own module,
  asserted by `test_r5_2g_there_is_no_application_caller_of_adapt_manifest`,
  which fails when one appears. Wiring the dispatch into
  `kansas-fiscal-document-ingest.py` is P5-BUILD's first item, on the TEST image.
* **Item 8 remains PREPARED AND NOT EXECUTED.** No image built, no digest
  recorded, no `.env.images` written, no container touched. The proposal must
  still be re-derived for `ks-fiscal-local` — the running cell — whose
  `.env.images` is not checked in anywhere; the digests recorded earlier belong
  to `ks-state-civics`.
* [WAVE-146](WAVE-146-qdrant-collection-prefix-config-runtime-mismatch.md): the
  `instance.yaml` / runtime collection-prefix disagreement.
* [WAVE-147](WAVE-147-statecivics-envelope-payload-helper-robustness.md): the
  same cross-field rule's laxer form in repo A's public helper.

### 2026-09-13 — the adapter connected to the real ingestion entrypoint

P5-BUILD item 1. `scripts/release/kansas-fiscal-document-ingest.py` now
dispatches on the contract's own routing predicate, and the entity branch has an
entrypoint of its own. Deployment stays deferred; this runs on the TEST image.

**The document path is unchanged, proved DIFFERENTIALLY.** "Still passing" is
not the claim on a file that was byte-untouched through WAVE-133's seven rounds
and all of WAVE-134, and through which 28,812 documents were ingested. The
pre-change consumer is read out of git at the fixed sha `a7b2843`, loaded
alongside the new one, and both are handed the same manifest:

* `LoadedManifest.sha256`, `byte_count`, `path` and `records` are equal;
* five malformed-manifest refusals produce IDENTICAL message strings on both;
* the missing-schema refusal is identical word for word;
* `inspect.signature(load_manifest)` is equal between the two.

Not a copy kept beside the test, which would drift, and not a description of the
old behaviour, which would be a second implementation to get wrong.

**What changed in the document path is one guard**, at the top of the per-line
loop, before `_validate_record`: classify the record by the contract's own
dispatch and refuse an entity record by name. For an untagged record that is a
two-key read returning the document branch, and everything after it is what it
was. The old failure was `manifest line N: missing logical_document_id` — a
shape error wearing a data error's clothes, which is the defect this ticket
opened on. It now says what the record is and where to read it.

**The entity entrypoint.** `--record-kind entity` routes to
`load_entity_manifest`, which verifies the ENTITY and DISPATCH pins (never the
document pin — a consumer must not verify a branch it does not read), validates
through `adapt_manifest`, enforces envelope/payload agreement, and only then
applies the eligibility gate. It returns a `LoadedEntityManifest`, deliberately
NOT a `LoadedManifest`, so a caller cannot hand entity records to
`plan_operations`, which speaks in `logical_document_id`. `--entity-path`
without `--record-kind entity` is refused: a flag that silently does nothing is
worse than one that refuses.

**Candidate refusal at the COMMAND, proved by inversion.** `main()` is driven
with real argv, `--apply` deliberately included, and every API seam
(`ensure_vector_store`, `apply_operations`, `default_headers`,
`upload_document`) replaced by a callable that raises if reached. Three
inversions, each reverted by `git checkout --` of the committed file with
`git status --porcelain` empty after:

| inversion | result |
|---|---|
| gate returns the adapted records ungated | `test_the_command_refuses_a_candidate_for_the_live_store` fails |
| touch `default_headers` before the gate | `AssertionError: default_headers was called before the entity gate refused a candidate` |
| remove the document-path dispatch guard | 4 tests fail across both suites |

**Both tripwires, reported honestly.**

`test_r5_2g` fired by design — it asserted that no application caller of
`adapt_manifest` existed and was built to fail the moment one appeared, because
until then a rebuild would ship a library nothing invokes. That signal has been
delivered, so the assertion is INVERTED rather than deleted: it now requires
`adapt_manifest`, `admit_entity_records` and `classify_record` to be reachable
from the consumer, and fails if the wiring is removed. Deleting it would have
thrown away the check that the wiring stays wired.

`test_every_load_manifest_caller_enforces_the_pin` **did NOT fire, and I checked
why rather than assuming.** The walker discovers FILES containing calls to the
consumer's `load_manifest` and compares that set against `contractPin.enforcedAt`.
The only such call in this file is `main()`'s, at what is now line 1149, and
`scripts/release/kansas-fiscal-document-ingest.py --contract-schema` was already
declared. The new entity entrypoint calls `adapt_manifest`, not `load_manifest`,
so no file entered or left the discovered set and the declaration is untouched.
The test passes on its own terms, not because it was quieted.

**Lint parity.** `ruff check` on the consumer reports the same 10 findings
before and after, diffed line by line — zero introduced. (One new `F401` was
introduced and removed before commit.)

**Baselines, carried forward, not re-derived loosely.** Same commands, same
resolving seed located by matching `SEED_SHA256 = b64003f3…`:

| regime | carried-forward baseline | this branch | NEW failures |
|---|---|---|---|
| corpus vars UNSET | 10 failed + 31 errors = 41 ids | 10 failed + 31 errors = 41 ids | **none** |
| corpus vars SET (resolving) | 7 failed + 4 errors = 11 ids | 7 failed + 4 errors = 11 ids | **none** |

Neither is green; the 11 are the pre-existing statute-tranche, WAVE-144
subprocess-`PYTHONPATH` and `psycopg` failures.

**Deployment still deferred. Item 8 stays PREPARED AND NOT EXECUTED.** An
application caller now exists, so a rebuild would ship something that is
invoked — but the proposal must still be re-derived for `ks-fiscal-local`, the
running cell, whose `.env.images` is not checked in anywhere; the digests
recorded earlier belong to `ks-state-civics`. Nothing here touched the running
cell.


### 2026-09-13 — the entrypoint integration landed

Merged to `main` as `0b15b6a` (`--no-ff`), branch tip `5aef516`.
`wave-134-entity-ingest-integration` deleted after the merge.

QC PASS. Two things from it worth carrying, because both make this repo's own
record more accurate rather than less:

* The QC ran **34 manifests** through both consumer versions against my 5. Of
  the 6 divergences, all are one class — a document record carrying
  `record_kind` at any value — and none is blocking on three independent
  grounds: `legacy_document_record` declares `additionalProperties: false`, so
  such a record was never contract-valid; A's producer cannot emit one; and
  `grep -c record_kind kansas-statutes.jsonl` is 0.
* **My sealed-seam evidence was thinner than I stated.** The fixture named four
  seams including `upload_document`, which does not exist in the module, so its
  `hasattr` guard silently sealed 3 of 4. The conclusion held — the QC
  re-confirmed `CandidateRecordRefused` with all 12 real network-capable seams
  plus `socket.socket` and `urllib.request.urlopen` sealed — but a guard that
  skips what it cannot find is the same shape as the defects this ticket keeps
  finding, and it was in a test written to prove the opposite. Fixed under WAVE-148, merged as the
  commit below.

Deployment stays deferred. **Item 8 remains PREPARED AND NOT EXECUTED**, and is
now blocked on WAVE-148 plus re-deriving the proposal for `ks-fiscal-local`,
whose `.env.images` is not checked in anywhere.

### 2026-09-13 — WAVE-148: the runtime refusals the docstrings already claimed

Three fixes, all reproduced before being fixed, all proved by inversion. Folded
into a branch rather than filed as a ticket, because each is small and leaving
them open would have left the docstrings saying more than the program does.

**1. `plan_operations` refused with `KeyError`, not by name.**
`LoadedEntityManifest` is a distinct type, so the two cannot be confused
STATICALLY — but `plan_operations` is duck-typed, and handed a forged
`LoadedManifest` of entity records it produced `KeyError: 'logical_document_id'`.
The docstring's "cannot hand it to `plan_operations` … in the type system, not
by convention" was true of type checking and not of the program. **A claim that
holds only until somebody constructs the object by hand is a claim about the
type checker.** `_assert_document_records` now refuses by name, and separately
refuses an untagged record with no `logical_document_id`. The forged-manifest
tests pass `state={}` deliberately: the guard must raise before anything reads
the state, and a real state dict would hide that ordering.

**2. The `record_kind` message advised a path that would also refuse.**
For `record_kind: "nonsense"` the refusal said "Read it with `--record-kind
entity`" — which routes to the entity branch, where the kind/version gate
refuses it too. Routing is by PRESENCE, per the contract's own `if.required`,
so an unknown kind lands in the same guard as a real entity record. The two now
get different advice, and "known" is READ from
`$defs.entity_kind_version_gate.properties.record_kind.const` rather than
written here, so a contract that renames its kind changes the message with it.
A test asserts a contract with the gate removed yields `None` rather than
silently making every kind known.

**3. My own sealed-seam evidence was thinner than I stated.** The fixture named
four seams behind a `hasattr` guard, and one — `upload_document` — does not
exist in the module, so it sealed three of four while the report said four. The
conclusion held, and QC re-confirmed it with every seam sealed, but **a guard
that skips what it cannot find is the same shape as the defects this ticket
keeps turning up, and this one was inside a test written to prove the
opposite.** The fixture now enumerates all 11 network-capable module attributes,
ASSERTS each exists before sealing it, and seals `socket.socket` and
`urllib.request.urlopen` underneath so an unenumerated seam still cannot reach
the network. A test asserts `upload_document` is not in the list and says why.

| inversion | result |
|---|---|
| remove the `plan_operations` guard | 2 tests fail |
| restore the one-size-fits-all message | 5 tests fail |
| put `upload_document` back in the seal list | `['upload_document'] are named as network seams but do not exist in the module` |

Each reverted by `git checkout --` of the committed file; `git status
--porcelain` empty after.

**Lint parity**: `ruff check` on the consumer gives the same 10 findings on
`main` and on this branch, diffed line by line — 0 new. (My first parity check
was itself wrong: `git stash` on a clean tree stashed nothing, so it diffed the
changed file against itself and reported a trivially identical result. Redone
against `git show main:`.)

**Baselines**, same commands, resolving seed: corpus vars UNSET 41 ids both
sides; SET (resolving) 11 ids both sides; **zero new failures in either
regime**. Neither is green.

**Deployment still deferred.** Item 8 remains PREPARED AND NOT EXECUTED and is
now blocked only on re-deriving the proposal for `ks-fiscal-local`, whose
`.env.images` is not checked in anywhere.


### Candidate storage delivery — 2026-09-14

The owner paused the other workers and transferred execution to Codex. Finish
one durable HB 2513 pilot through the authenticated API, isolated candidate
index and candidate search. Ordinary retrieval and existing document collections
are not destinations. No full-cell rebuild or database migration is required.

The new API uses the pinned envelope and committed, hashed payload schemas from
A, validates record digests, resolves candidate collection names through the
adapter, uses a real embedding profile, upserts with wait=True, and compares
full-record readback. Repeating the same manifest skips embedding and writes.
Older revisions and conflicting payloads for the same revision refuse.

The runtime document model registry supplies a conservative collection catalog:
`embedding_profile_config` refuses profiles outside it, including any new
candidate index profile. This covers dynamic routing/fallbacks without claiming
that the four undeclared sources each use a guessed profile. Existing source
declarations are still included and the original strict guard remains the
default when the runtime catalog is unavailable.

The candidate API is disabled by default. Enable only in ks-fiscal-local after
focused API/adapter checks and a target-specific API image build. Rollback is
disabling that API flag and restoring the previous API image; retained candidate
points remain separate from document and live-entity collections.


Validation at `5e24383`: 281 focused tests passed with no skips across candidate
storage, entity CLI, adapter, contract pins and document CLI. The first harness
run omitted `SVS_STATECIVICS_REPO`; after mounting A, its operator clone's `main`
ref was stale. Fetching canonical A main resolved the provenance failure. No test
or pin exception was added. The final image built from `apps/api/Dockerfile`
passed all 11 candidate-storage tests under its own Python 3.12 dependencies,
and importing the full API registered both routes.

Local activation uses a candidate API service alongside the existing API on the
ks-fiscal-local network, with its own loopback port and DNS alias. The existing
API, worker and model gateway remain running. This is an operator candidate
endpoint, not a public-UI release or a five-image cell release. Its image ID,
source commit, route checks and durable-record receipts are recorded with the
pilot handoff. The existing cell currently uses local header principals; this
exercise does not claim bearer-token authentication in that local deployment.


### Pilot delivered — 2026-09-14

The durable manifest `0ac68077…`, exported by A at `8a618c3f` and committed
in A at `0d199c6b`, passed the real operator CLI into the local candidate API.
Two real descriptors were embedded with OpenAI text-embedding-3-small and two
full records were written and read back exactly. The nursing-fund query returned
action revision 3 first, with `amount_kind=no_limit`, period end 2027-06-30, and
committed source span `01a0a168-d786-767d-a484-c31e6839ff2e` at [7763,7813).
A database join separately confirmed both the quote and source revision hash.

A repeated import reported embedded=0, written=0, unchanged=2. The live CLI
refused before contacting the API; the live API independently returned 422
CandidateRecordRefused. Existing document point counts stayed 83,858 and
12,579. The original API image is unchanged.

Final focused B validation at `ba359c3`: **293 passed, none skipped**, including
the complete candidate test matrix against the committed durable manifest and
byte equality of the vendored payload schemas/manifest with A's fixed commits.
`SVS_STATECIVICS_REPO=/upstream` mounted the refreshed plain operator clone.
No claim is made that the unrelated full baseline is green.

Runnable handoff: `runbooks/statecivics-candidate-pilot.md`. The adjacent JSON
receipt records actual index and retrieval results. The source `80092998` bulk
parser branch remains unmerged; full-bill import and public-UI deployment remain
outstanding.

### Bulk candidate command — 2026-09-14

A exported 2,588 durable records (2,391 actions, 197 provisions), with full
manifest SHA-256 5155056a4b2d411896787ff6e681d90a8cd58655cf3ddf6805849ca9dccc791b.
The exact compressed artifact is committed in A at c49d7105 and copied here.
The existing API accepts at most two million manifest characters per request,
so the operator command now validates the entire artifact before sending bounded
batches of at most 100 records / 1.5 MB. Bytes and record digests are preserved.
The proof records completed batches and remains applied=false on partial failure;
rerunning uses the API's existing digest idempotence. No API or image change.
Tests exercise real records, CRLF preservation, file changes after admission,
and a failure after a successful first batch.

Focused validation at `4e8ae97`: **298 passed, none skipped** across bulk command,
candidate storage, entity-ingest integration, adapter, contract-pin and document
consumer suites. A later-batch invalid payload is refused before the first
request. The first run of the new test file used pytest's reserved `setup` name;
it was renamed and all new tests then executed. The container used
`ks-test-runner:formatnongpl`, both plain operator clones, network disabled, and
`SVS_STATECIVICS_REPO=/upstream`. The original application image remains active.


### Bulk delivery verified — 2026-09-14

All 2,588 records were persisted through the running candidate API: 2,391 actions
and 197 provisions. Complete Qdrant readback equals the producer artifact,
record-for-record. Three fund queries returned the expected action at rank 1:
PKU treatment ($199,274), sexually violent predator expense fund (No limit), and
nurse fair treatment and recovery fund (No limit), each for FY ending 2027-06-30.
The returned payloads carry durable source spans and match A's manifest exactly.

The committed full-manifest CLI then completed all 26 batches with embedded=0,
written=0, unchanged=2,588. Live-path ingestion independently refused candidates
with HTTP 422. Document collections stayed at 83,858 and 12,579 points. The
candidate API image and all other application containers were unchanged.

Two provider failures interrupted the initial run: a read timeout at batch 19
and a connection error at batch 21. Both occurred before that batch's index
write. Resuming confirmed batch receipts completed the run. The 2,588 embedding
count describes successful batches, not total provider usage; failed attempts
and three search-query embeddings are additional activity.

The repeatable verification command is committed in B at `4adb5fe` and was run
from its plain operator clone in Docker. The entire corpus readback, three query
responses, operator ledger fingerprints, pre/post backups and interrupted-run
receipts are preserved in the delivery JSON. A Qdrant snapshot was downloaded
outside Dropbox and its SHA-256 matched the server checksum. Its restore was not
exercised. Fifty other-spending entries and eight claimant/leading passages stay
cited review items; candidates were not promoted and the VPS UI was not deployed.

Receipt: `runbooks/statecivics-bulk-delivery-20260914.json`. Commands:
`runbooks/statecivics-candidate-bulk.md`. The historical pilot runbook now points
to the full manifest and no longer suggests replaying superseded export metadata.
