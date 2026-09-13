# WAVE-133: Project canonical identities and typed structured evidence into the fiscal graph

Status: landed 2026-09-13. landed_by: aaa8bf6 (merge), ad41770 (branch tip). Parent: WAVE-132 (reopened). Filed 2026-09-10.

**Pin label vs pin content.** The three per-branch digests are pinned at StateCivics commit `314beafe`. That commit is a LABEL FOR THE FILE'S CONTENT, not a claim about A's current tip: `contracts/civic-impact/retrieval-export-record.schema.json` hashes to `899b541a8ba03431e0a129c09a8a3733b2d43057e4bb260b8bdb010dece2e8a7` at `314beafe`, at `9f8ed9b3` (the KS-650 B1.2 merge, which touched nothing under `contracts/`) and at A's `main` `38258704`; `git log 314beafe..38258704 -- contracts/` is empty and `314beafe` is an ancestor of `main`. So the pin is correct and only the label is older than A's main. `test_the_fixture_is_the_upstream_contract_at_the_pinned_commit` asserts both the byte-identity and the ancestry, and fails rather than skips when `SVS_STATECIVICS_REPO` is unset.

## Summary

Replace the current provision identity and document-only evidence constraints with a rebuildable ExAIS projection of the upstream canonical contract.

## Background

The provisional fiscal graph uses SourceSpan as legal provision identity and requires document/chunk bindings for every entity. Accounting dimensions derived from CSVs therefore cannot be represented truthfully, and existing single-run replacement needs complete manifest and partition semantics.

## Scope

- Add fiscal v2 canonical references, document_span|structured_record evidence, typed derivation/run references, relationship assertions, bounded batches and complete manifests in schemas.py. Distinguish canonical legal/entity version IDs, evidence IDs and ExAIS projection IDs. Document spans bind real documents/chunks where present; CSV structured records require no chunk/document.
- Reuse graph_nodes/graph_edges for rebuildable projections with bounded canonical fields, descriptions, evidence/publication/snapshot metadata. Add explicit derivation run nodes/refs with directional inputs/outputs; supported stronger correspondence is separate. No canonical graph engine or new authority ledger.
- Keep existing max 1000 nodes/2000 edges PER BATCH. Manifest declares snapshot/run, ordered partition IDs/digests/counts and total expected nodes/edges. Validate complete accounting, duplicate/conflicting identity, cross-partition endpoint resolution and stream/batch limits before activation. No silent truncation or unbounded cap increase.
- Use immutable manifest/partition identity. A new bill stages into a new complete manifest that explicitly includes all retained approved bill/FY partitions. Replay guard compares identical partition contents rather than demanding one whole-run load. WAVE-134 owns active-pointer switching and removal; loading bill B cannot silently evict A.
- Retain historical v1 validation for audit/approved rollback; do not reinterpret SourceSpan identities as new provisions or require StateCivics to emit provisional publisher v1. Rebuild corrected v2 projection from KS-650 records and KS-600 identity.
- Define FiscalEvidenceCitation separately from ContextCitation: evidence kind, canonical subject/revision, source revision/raw hash, exact locator/public URL/digest, optional actual chunk/document only for document_span. Define entity results separately from ChunkRecord. WAVE-135 exposes native fiscal typed results/answers; a file-only compatibility endpoint cannot fake a file citation for a structured row.

## Out Of Scope

- Canonical civic graph ownership in ExAIS
- New graph engine or universal ontology
- Unbounded graph limits
- Fabricated document/chunk bindings
- Inferred Cartesian derivation edges
- Global policy changes

## Prior Art

Verified during ticket enrichment on 2026-09-10. Read these existing owners before implementing. New files and signatures below are proposed work.

- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `validate_fiscal_graph`. V1 strict SourceSpan provision identity, chunk fields, one run, same-year endpoints and 1000/2000 bounds.
- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `validate_fiscal_graph_bindings`. Every entity requires an accessible current chunk; structured-only cannot work currently.
- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `guard_fiscal_graph_generation`. Whole-run replay comparison must become partition-aware.
- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `fiscal_node_id`. Existing scoped deterministic projection IDs; distinct from canonical identities.
- **Code** — [packages/svs_common/svs_common/fiscal_graph_artifact.py](../packages/svs_common/svs_common/fiscal_graph_artifact.py): `build_fiscal_graph_artifact`. Historical provisional publisher/PDF-only evidence adapter.
- **Code** — [packages/svs_common/svs_common/fiscal_graph_artifact.py](../packages/svs_common/svs_common/fiscal_graph_artifact.py): `validate_built_artifact`. Existing manifest digest validation seam.
- **Code** — [packages/svs_common/svs_common/schemas.py](../packages/svs_common/svs_common/schemas.py): `ContextCitation`. Requires chunk_id/document_id; separate structured citation type needed.
- **Code** — [apps/api/svs_api/main.py](../apps/api/svs_api/main.py): `load_vector_store_graph`. Existing store-locked graph API and persistence integration.
- **Code** — [scripts/release/kansas-fiscal-graphrag.py](../scripts/release/kansas-fiscal-graphrag.py): `main`. Existing build/validate/load entry point.
- **Code** — [tests/test_fiscal_graph_postgres.py](../tests/test_fiscal_graph_postgres.py): `test_immutable_replay_and_separate_generation`. Existing generation persistence proof.

## Current Evidence

The provisional fiscal graph uses SourceSpan as legal provision identity and requires document/chunk bindings for every entity. Accounting dimensions derived from CSVs therefore cannot be represented truthfully, and existing single-run replacement needs complete manifest and partition semantics.

The Prior Art anchors distinguish existing code from the missing behavior. Source inventory and earlier synthetic test passes do not establish real-source product acceptance.

## Implementation Notes

Follow [the agreed law-and-money handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md). Preserve existing canonical owners, native contract shapes and record-level evidence requirements.

Use the shared-owner map in [build-contract.json](../.tranche/statecivics-semantic-graph/aligned/build-contract.json) and look up affected files/symbols in [stack.index.json](../.tranche/statecivics-semantic-graph/aligned/stack.index.json). These are local planning artifacts; their signatures describe future work unless marked existing. Runtime must not depend on worktree paths or these planning files.

### 2026-09-12 — P5-PLAN lane B: vocabulary, version dispatch, KS-650 adapter

Verified at StateCivics `e94a894e`; pin re-computed and landed at `314beafe`.

`314beafe` is a LABEL FOR THE FILE'S CONTENT, not a claim about A's tip: `git -C <A> show <commit>:contracts/civic-impact/retrieval-export-record.schema.json` is sha256 `899b541a8ba03431e0a129c09a8a3733b2d43057e4bb260b8bdb010dece2e8a7` at `314beafe`, at `9f8ed9b3` (the KS-650 B1.2 merge, which touched no path under `contracts/`) and at A's current main `38258704` alike — so the pin is correct and the label is merely older than A's tip.

**Vocabulary.** `FISCAL_RELATIONS` (fiscal_graph.py:32) has five names, *none with
a producer*. A repo-wide sweep found no script, fixture, artifact, DB seed or
dump that ever emitted one; they exist only as the constant, the `_ENDPOINTS` map
(:50), prose in CELL_GRAPH_PROFILES.md, and runtime-synthesised test literals
(fiscal_graph_test_support.py:44, test_fiscal_graph_artifact.py:67).
`kansas-fiscal-graphrag.py` echoes operator input and generates nothing; the only
recorded edge count, 5, is a rolled-back synthetic PostgreSQL transaction. A owns
canonical identity and edges, so B adopts A's four names verbatim; B's five
survive only as `derived` with a producer, and none qualifies now.

| B relation | A canonical edge | Ruling |
|---|---|---|
| `contains_appropriation` | `action_relies_on_provision` | Nearest match but **not** a rename: direction reversed, containment != reliance. A's name wins. |
| `targets_account` | — | No counterpart; A v1 has no `budget_account`. Retire. |
| `account_of_agency` / `account_in_fund` | — | Retire. |
| `documented_by` | — | A's entity branch carries no document identity by design. Retire. |
| — | `action_enacted_by_bill_version` | New; B holds this as node attribute `fiscal_bill_version_id`, not an edge. |
| — | `provision_supersedes_provision`, `action_supersedes_action` | New; B has no supersession vocabulary. |

Edge-name intersection is empty. Node types intersect on `appropriation_action`
only — a **collision, not a match**: B keys it by span/chunk binding, A by
`(entity_logical_id, entity_revision)`. A's `provision_reference` is likewise not
B's `enacted_provision` (ledger vs SourceSpan UUID). Merge neither.

**Version dispatch.** Beside the constants at fiscal_graph_artifact.py:27-28 add
`ENTITY_PROJECTION_SCHEMA_VERSION = "statecivics.entity-projection-record.v1"` and
`ENTITY_ARTIFACT_MANIFEST_VERSION = "exais.fiscal-entity-graph-artifact.v1"`, and
dispatch on `(record_kind, record_version)` read from those two keys alone,
mirroring the guards at :387 and :507 — raise on unknown, no fallback, no default.

**Adapter.** `build_fiscal_graph_artifact` cannot be extended — A's B1 manifest is
a different shape (JSONL records, no envelope, no `derivation_run`, no chunk
evidence). Add a sibling `build_entity_projection_artifact`. Reuse
`validate_vector_store_id`; extend `_eligible` for A's four eligibility fields;
**do not call `_bind_evidence`** (entity records have no chunk). New:
`_entity_node_key` keying `(logical_id, revision)`, `_entity_edge` for the four
types, `validate_built_entity_artifact`. Description text embedded ONLY from A's
`description.text`; `ingestion.action == "remove"` becomes a removal.

It must NOT derive edges from similarity, section labels or account-label
normalization; invent a `logical_document_id` (A omits it deliberately, yet
`fiscal_logical_document_id` is a required sha256 today); read the prohibited joins
(`vector_similarity`, `fuzzy_name_match`, `code_suffix_match_without_context`,
`llm_assertion`); or require `fiscal_year`, which A's entity records lack.

Tests: unknown kind/version refused with no fallback; `(logical_id, revision)`
identity and the `appropriation_action` collision; all four edge types plus
rejection of a fifth; tombstone carries no entity/description/derivation;
description bytes equal A's and never synthesised; no chunk binding attempted; a
target outside the batch (B raises on dangling today — decide and pin that).

**Spend (P5-BUILD).** Tests use a fake embedding provider: zero tokens. One real
end-to-end run only — at most 20 fixture descriptions, each capped at 600 chars by
`compact_description`, into the new entity store, cell `ks-fiscal-local` only:
~3,000 embedding tokens (20 x ~150) plus ~200 for a recall probe, so **under
5,000 tokens in one request**, far below the 300k per-request cap.

### 2026-09-13 — pin round 2: QC FAIL remediation, and the (commit, digest) chain

QC returned FAIL on two findings, both reproduced here before acting.

**Chain of entity-branch pins, unbroken (R-P6).** `da242fd8…` computed at
`e94a894e` (B1) was superseded the same day by `d5248a54…`, which A introduced at
`1de6312e` and which is still the value at `314beafe` (B1 + B1.1, landed_by
`121083e9`); the contract file is byte-identical across those three. The cause
was prose: A rewrote two entity-branch descriptions after recording that JSON
Schema cannot refuse an unknown kind "before any field access". The document
branch never moved. The superseded pair is carried in
`statecivics_contract_pin.SUPERSEDED_BRANCH_SHA256` and in all four source
packages, and a test asserts no superseded digest is ever pinned live.
(The ruling's wording names `d5248a54…` as the superseded value; the digest that
was actually superseded within the day is `da242fd8…`, and `d5248a54…` is the
live one. Logged as the chain actually is.)

**Finding 1 — a pin enforced on some of the real paths.**
`kansas-statute-rollout.py` called `load_manifest` with no schema, and
enforcement was `if contract_schema is not None`. That file contained zero
contract references while the same `source.yaml` declared it as
`chapterTranches.rolloutRunner` for 85 tranches / 31,079 records. `contract_schema`
is now REQUIRED and refuses by naming the entrypoint that omitted it. The
callers are no longer counted by hand here or anywhere else: they are
enumerated by
`tests/test_statecivics_contract_pin.py::test_every_load_manifest_caller_enforces_the_pin`,
and `enforcedAt` must equal what that test discovers. (Round two still wrote
"two"; the real number was three. See the round-three entry below.)

**Finding 2 — the semantic digest was wrong and is deleted (R-P2).** JSON Schema
property names share a namespace with annotation keywords, so stripping keys
named `description`/`title` also stripped the real properties
`legacy_document_record.properties.title` (the ENFORCED branch) and
`entity_projection_record.properties.description`. Tightening `title`, or
deleting it so `additionalProperties: false` newly rejects every record carrying
one, was reported as "annotation-only drift" with an unchanged digest. The
mechanism is removed, not merely unused, and a test fails if it returns.

**Three literal digests, all enforced (R-P3).** `document`, `entity`, and
`dispatch` — the top-level `if`/`then`/`else` routing predicate. Swapping
`then`/`else` leaves both branch subtrees byte-identical and sends every untagged
record to the entity branch, so routing is pinned on its own. Each consumer
verifies its own branch plus dispatch, never the other branch.

**Approved plan, for P5-BUILD.** B adopts A's four edge names verbatim as
canonical. All five B relations retire — the constant, the `_ENDPOINTS` entries,
the prose in CELL_GRAPH_PROFILES.md and the synthesised test literals — on the
evidence that `git log --all -S` returns exactly one commit (`a587ad9`) for each
of the five, so none was ever added and later removed, and no producer, fixture,
artifact, DB seed or dump ever emitted one. The adapter is a sibling
`build_entity_projection_artifact`, not an extension of
`build_fiscal_graph_artifact`. Ingestion dispatches on `record_kind` BEFORE
`_validate_record`'s `logical_document_id` requirement.

### 2026-09-13 — pin round 3: the caller list becomes a construction

**R-P7 — the third runner, and why there will not be a fourth surprise.**
Round two's QC found `kansas-fiscal-marker-handoff.py` calling `load_manifest`
with no schema. No call site in this section is cited by line. Round three wrote
one down and it had already moved by round six; a written-down line number is the
same defect as a written-down caller list, and this section is about replacing
written-down caller lists with a construction. Every `load_manifest` call site is
derived, with its file and line, by
`tests/test_statecivics_contract_pin.py::test_every_load_manifest_caller_enforces_the_pin`
— read them from there. `kansas-fiscal-marker-handoff.py` is a real runner: the
`source.yaml` and `source.lock.json` of the fiscal source package declare it a
`runner`, and the kansas-fiscal-documents README documents its invocation. Because the new refusal is unconditional, that script
returned 1 on EVERY invocation, plan included, and
`tests/test_kansas_fiscal_marker_handoff.py::test_plan_makes_no_api_call_or_write`
was red. It now takes `--contract-schema`, passes it through with
`entrypoint="kansas-fiscal-marker-handoff.py"`, and refuses by naming itself.

The list of callers is no longer written down anywhere as an assertion. Round
one listed one runner while a second ran unpinned; round two listed two while a
third ran unpinned. A hand-maintained list is the defect, not the remedy, so
`test_every_load_manifest_caller_enforces_the_pin` walks the tracked Python
source with `ast`, resolves every call to a function named `load_manifest` to
the FILE its callee actually lives in — following the importlib
`spec_from_file_location` target behind each module alias — and requires
`contractPin.enforcedAt` to equal the discovered set exactly, in both
directions, in all four declaring files. Name matching would be wrong here:
`scripts/release/kscourts-ingest.py` defines an unrelated function of the same
name, and `scripts/release/kscourts-decrypted-marker-retry.py` calls it.
That call site is excluded because its `ingest` alias resolves to
`scripts/release/kscourts-ingest.py`, which is not the fiscal consumer — by
resolution, not by any filename special case. A call site the walker cannot
resolve raises `Unclassified` and fails the test; a broken checker blocks.

**R-P22 — the walker is BOUNDED, not hardened.** Six QC rounds failed, and the
defect relocated every time, always to "a check whose scope is something
someone enumerated": which callers, then which spellings count as a call, then
which traversal feeds the exemption set, then flow-insensitive alias binding,
then which resolution paths the refusal was wired into. Hardening an unbounded
surface does not terminate; bounding it does. There is now ONE choke point,
`_Module._module_identity`, and every call site that becomes a module identity
passes through it and through nothing else — the precomputed factory table and
the `defines_consumer_function` flag, both of which answered resolution
questions at construction time away from the names being resolved, are deleted.
It accepts three forms and refuses every other program: a bare call resolving
through Python's scope chain to the module's own undecorated top-level `def`; an
alias bound to an undecorated module-scope factory with exactly one spec target;
and the inline `module_from_spec(spec_from_file_location(...))` spelling, which
`kansas-statute-rollout.py` uses and which has no factory function. Every name in
every chain must be bound exactly once under the R-P16 binding visitor, checked
at resolution time. The scope chain is now Python's: a class body is not part of
the chain a nested `def` searches, so a class attribute can neither resolve a
method's alias to the wrong module nor refuse one the language resolves cleanly.
Three defects of exactly the class R-P26 anticipates -- a program INSIDE an
accepted form resolving confidently and wrongly -- were found in-round by
executing the shape batteries against the new choke point, and closed: a
`global`/`nonlocal` rebinding declared in a nested scope, invisible to the
enclosing scope's binding visitor; a factory that builds one spec and RETURNS a
different module, so what it named and what it yielded came apart; and a
DECORATED top-level `def load_manifest`, where the name need not reach the body
written under it. Two of the three were executed in the unsafe direction, where
the call really does reach the fiscal consumer unpinned and the walker reported
another module and said nothing at all.

**Final QC found FOUR more, all closed in-round.** Every one was in the UNSAFE
direction: the walker named a non-fiscal module, the gate stayed GREEN, and the
program at runtime reached the fiscal consumer's `load_manifest` with no
`contract_schema` — proven each time by running it and catching
`FiscalIngestError: --contract-schema is required`.

* **F1 — the factory name was resolved against a fabricated scope chain.** The
  ALIAS binding was made flow-sensitive in round five; the FACTORY NAME it
  points at was not, because `_form_two` passed a hardcoded `self._module_scope()`
  instead of the `envs` it was handed. A local `_load_other = _load_fiscal`, or a
  parameter default `def run(_load_other=_load_fiscal)`, was invisible. Fixed by
  resolving the factory name through `envs`, which is what that function's own
  docstring had already claimed it did.
* **F2 — a lambda and a comprehension never went through `_push`.** Class scopes
  were dropped correctly for a `def` body and for nothing else, so inside a
  class body both kept resolving against the class attribute that Python skips.
  This also refutes `_scope_env`'s own argument that recording lambda parameters
  and comprehension targets in the enclosing scope can only OVER-count and
  therefore only refuse: inside a class body it UNDER-counted, hiding the module
  binding Python actually uses. Fixed by giving both their own scope through
  `_push`; the correct answer there is not a refusal but the fiscal consumer,
  which is what turns the gate red.
* **F3 — `from X import *` was never counted.** `_scope_env`'s ImportFrom arm
  binds `alias.asname or alias.name.split(".")[0]`, which for a star is the
  literal `"*"`, so a module that defines `load_manifest` and then star-imports
  over it still showed exactly one binding and was granted form 1. Fixed by
  treating a star import as unattributable, like an `exec` or a namespace-mapping
  write: the module resolves nothing. Zero tracked in-scope files use `import *`,
  so the false-positive cost is 0.
* **F4 — `Path.resolve()` does not canonicalise case.** This filesystem is
  case-insensitive, so `Kansas-Fiscal-Document-Ingest.py` and
  `kansas-fiscal-document-ingest.py` are one file that importlib loads
  identically, while `==` on the two `Path`s is False — and `is_fiscal_consumer`
  was a bare `==`. Fixed by comparing filesystem identity with
  `os.path.samefile`, falling back to path equality for a target that does not
  exist (a non-existent path cannot be the consumer, which does exist).

The three forms, and the shapes that are NOT detected, are listed in that test's
own docstring — a list of what the checker cannot see is a specification, not a
cache, and it changes only when the checker is deliberately strengthened.

**R-P26 — what this check is for.** The walker is an EARLY WARNING, not the
guard. The guard is the consumer's runtime refusal of a missing schema, executed
by `test_the_consumer_refuses_a_missing_schema_at_runtime`: a caller the walker
misses cannot ingest unverified, it dies on its first invocation. The residual
risk the three forms leave is therefore a new runner failing loudly on day one,
not an unverified ingestion.

The discovered set is not recorded here. It is enumerated by
`tests/test_statecivics_contract_pin.py::test_every_load_manifest_caller_enforces_the_pin`,
which walks the tracked source and fails if the declarations disagree with what
it finds. Run that test for the current set; a count written into this ticket
would be a second, unchecked copy of exactly the list this mechanism exists to
stop maintaining by hand.

R-P13. A five-row illustration of that output used to sit here, labelled as an
unchecked example whose line numbers would drift. A hand list that announces it
will drift has no value; it was deleted. The deriving test prints the live set
in its own failure message, and the paragraph above explains why the `kscourts`
sites are excluded by resolution rather than by name -- which needs no line
numbers.

**R-P8 — the rollout suite is workstation-bound, and stays that way.** No pin
and no INDEX hash was loosened. `tests/test_kansas_statute_rollout.py` requires
`SVS_STATUTE_EXPORT_ROOT`, `SVS_STATUTE_CORPUS_ROOT`, `SVS_STATUTE_CUSTODY_ROOT`
and `SVS_STATUTE_ROLLOUT_SEED`, all pointing at retained local corpora. Without
them `pytest -q tests/test_kansas_statute_rollout.py` is 3 failed / 27 errors,
zero skipped, by design — `required()` asserts "retained-input proof must not
skip" — because a skipped retained-input proof is indistinguishable from a
passing one on a machine that has no corpus. With the four variables set the
same command ran 30 passed, zero skipped here.

**R-P9 — "gate" is never a bare word.** Every claim below names the exact
command it came from. `./scripts/run_gate.sh statewide` is repo A's statewide
gate, takes no arguments, and returns 164 failed / 18 errors on A's `main`; it
is compared BY COUNT against the same command on a branch, never by exit code,
because its exit code is non-zero in both states. Anything narrower is named as
an explicit path, e.g.
`pytest -q tests/test_statecivics_contract_pin.py`. B has no `scripts/run_gate.sh`.


## Deliverables

- [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py) — Own v2 identity, evidence, relation, partition and manifest validation. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [packages/svs_common/svs_common/fiscal_graph_artifact.py](../packages/svs_common/svs_common/fiscal_graph_artifact.py) — Own KS-650 adapter and complete bounded manifest validation. Shared file owner: WAVE-133. Edit sequence: WAVE-133.
- [packages/svs_common/svs_common/schemas.py](../packages/svs_common/svs_common/schemas.py) — Own fiscal typed evidence/citation/entity-result/batch/manifest definitions. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-135.
- [apps/api/svs_api/main.py](../apps/api/svs_api/main.py) — Wire fiscal v2 validation to existing graph persistence. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [scripts/release/kansas-fiscal-graphrag.py](../scripts/release/kansas-fiscal-graphrag.py) — Extend existing build/validate dispatch. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-136.
- [tests/test_fiscal_graph.py](../tests/test_fiscal_graph.py) — Version/identity/typed relationship mechanics. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-135.
- [tests/test_fiscal_graph_artifact.py](../tests/test_fiscal_graph_artifact.py) — Second-kind and structured-only evidence proof. Shared file owner: WAVE-133. Edit sequence: WAVE-133.
- [tests/test_fiscal_graph_postgres.py](../tests/test_fiscal_graph_postgres.py) — Coexisting partitions and immutable replay. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [tickets/WAVE-133-fiscal-canonical-projection-contract.md](WAVE-133-fiscal-canonical-projection-contract.md) — NEW: typed projection/evidence follow-up. Shared file owner: WAVE-133. Edit sequence: WAVE-133.

Expected integrated output: WAVE-133 defines one v2 canonical-reference/evidence/citation/entity-result/batch/complete-manifest contract and consumes KS-650 through the existing fiscal graph adapter/validator/API. Multiple bill/FY partitions coexist, each bounded at 1000 nodes/2000 edges, with global counts/hashes/endpoint/replay checks; structured-only evidence needs no chunk. Typed run lineage preserves direction and excludes Cartesian correspondence. Contract and disposable PostgreSQL proof cover prior document compatibility and incomplete/conflicting partition rejection; historical v1 remains explicit audit/approved-rollback behavior.

## Acceptance Criteria

- Supersede SourceSpan-as-enacted-provision-ID in WAVE-130/CELL_GRAPH_PROFILES and the v1 requirement that every entity have a document/chunk binding. Mark these as historical implementation constraints and define migration/compatibility behavior without claiming the existing runtime is already corrected.
- Consume upstream canonical identity/revision and KS-600 provision references. Model structured CSV dimension/observation evidence separately from source/document spans, allowing structured-only entities with valid retained evidence. Preserve raw/parsed revisions, record/section locators, precise source bindings and observation/effective dates without inventing dates or PDFs.
- Preserve typed relationship direction, legal action role, agency/fund/account/FY scope, evidence, eligibility, revision and typed derivation references/run context. Support enacted provision to appropriation action to fiscal-year account to agency/fund with exact legal and supporting budget evidence. Represent joint derivation lineage without automatically materializing every input/output pair as one-to-one correspondence.
- Do not create edges from semantic similarity, section-number equality, unresolved statute History or normalized account labels. Stronger legal lineage or action/fact edges require explicit source-backed upstream correspondence.
- Define bounded partitions/batches and complete manifest accounting for multiple bills, years, and source revisions; reject incomplete/truncated activation. Loading another bill does not silently replace the first. Preserve immutable source/run/snapshot identity and a migration/rollback route for supported prior artifacts.
- Focused contract/persistence tests cover structured-only and document-span evidence, identity stability under re-extraction, separation across legal versions, joint-lineage edge rejection, typed path provenance/direction, multiple coexisting partitions, incomplete manifests, and valid prior document records.
- Resolve document locators against the pinned retained extraction, compare selected text with the exact quote/hash, and preserve raw-source derivation. Page/line type checks and a supplied quote/hash agreement alone are insufficient. Test wrong page/line bounds, truncated clauses, changed extraction bytes and incompatible locator conventions; never discard line fields to fit the legacy page-only adapter.
- Consume the upstream-owned locator-verification state and bound verification derivation once its contract is agreed. Missing legacy metadata or an unsupported resolver must not imply a verified exact citation. Keep this separate from confidence, evidence class and publication eligibility; preserve unverified candidate evidence without promoting it to verified fiscal support. Do not invent the upstream wire shape.

## Dependencies

- Canonical prerequisite: KS-600
- Canonical prerequisite: KS-650

Dependencies apply to the specific contracts, evidence and eligible records consumed here. Do not wait for unrelated payments/forecasts/outcomes or the full K.S.A. harvest. KS-613 keeps its existing scope; KS-651 owns the separate generalization benchmark.

## Verification

Run after implementation in the required test environment; these commands were not executed during ticket drafting.

```sh
pytest -q tests/test_fiscal_graph.py tests/test_fiscal_graph_artifact.py tests/test_fiscal_graph_postgres.py
```

Structured-only entities, independent legal identity, typed directed lineage, coexisting partitions and complete manifest accounting.

R-P9: name the exact command, never the word "gate" alone. StateCivics commands
must use `./scripts/run_gate.sh statewide` (repo A, no arguments; 164 failed / 18
errors on A's `main`, compared BY COUNT against the same command on the branch,
never by exit code). Narrower runs are named as explicit paths. No host
dependency installs.

R-P8: `pytest -q tests/test_kansas_statute_rollout.py` is workstation-bound. It
requires `SVS_STATUTE_EXPORT_ROOT`, `SVS_STATUTE_CORPUS_ROOT`,
`SVS_STATUTE_CUSTODY_ROOT` and `SVS_STATUTE_ROLLOUT_SEED`, and ERRORS without
them by design rather than skipping, because a skipped retained-input proof
reads identically to a passing one: 3 failed / 27 errors, zero skipped, unset;
30 passed, zero skipped with the four set.
No pin and no INDEX hash may be loosened to make it run elsewhere.

`pytest -q tests/test_statecivics_contract_pin.py` requires
`SVS_STATECIVICS_REPO` and likewise fails, never skips, without it. ExAIS pytest commands run inside its existing configured test/container environment; PostgreSQL proof needs explicitly disposable SVS_FISCAL_GRAPH_TEST_DATABASE_URL and cannot count skipped tests as passed. Real-source product acceptance is separate from synthetic tests.

## Risks

Conflating legal identity with evidence or treating derivation membership as pairwise proof creates false relationships. Incomplete manifest replacement can erase unrelated bill/year partitions. Validate identity, evidence and complete partition accounting independently.

## Rollback

Disable the fiscal projection/profile if validation fails. Preserve canonical source data and compatible document search; retain complete prior eligible generation manifests for diagnosis and a reviewed rollback.

## Implementation Log

2026-09-10: the owner authorized coder workers and independent quality review,
and confirmed that the StateCivics developer manager owns the KS tickets.
ExAIS implementation runs in the separate feature worktree
`/Users/mfrieson/Developer/exais-vector-store-law-money` on
`feat/statecivics-law-money-projection`, based on the preserved `3230b74` handoff.

The initial increment implements only independent offline typed evidence,
partition/manifest validation, and retained CSV evidence verification. It does
not define the KS-650 wire schema or a canonical provision identifier. The
existing runtime remains unchanged while these components are built and tested.

Read-only upstream inspection found no provision-reference contract or second
entity/relationship export implementation at planning `3650b8c5` or operational
`8ffabad9`. KS-600/650 remain integration prerequisites. The existing KanView
loader retains canonical observation identities but leaves source locators empty;
the ExAIS byte/record verifier cannot repair or publish those canonical records.

Full acceptance still requires the actual upstream contract and reviewed export,
adapter/API and disposable PostgreSQL integration, and the remaining acceptance
criteria above. WAVE-134 through WAVE-136 have not started.

The independent foundation is implemented: internal typed evidence/citations,
complete bounded manifests and retained-partition replay, source/extraction
revision hash consistency, and the offline CSV byte/record verifier. Root's
combined container check returned **272 passed, zero skipped**, including the
real source tests and existing API contracts. See
[the implementation proof](../.tranche/statecivics-semantic-graph/aligned/wave-133-offline-proof.md)
for commands, source coverage and deferred acceptance. Independent review found
and then verified the fix for a verifier/typed-locator composition defect;
[review 2](../.tranche/statecivics-semantic-graph/aligned/wave-133-offline-qc-2.md)
returned **PASS WITH NOTES** for this increment. No full-ticket completion or
activation is claimed.

Follow-up manager clarification: the next retained-source sample is KS-613's
SB 125 section 96(j) provision and lapse action. KS-600 must supply its legal
identity and persisted action; KS-597 supplies exact spans and KS-601 reviewed
crosswalks (or an explicit unresolved gap). KS-650 supplies the actual export
contract/records. Existing accounting identities and observations are reusable,
but neither ticket visibility nor K.S.A. harvest completion fills these gaps.
The [current handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md#current-implementation-handoff)
records the sequence and preserves StateCivics ownership of that work.

The manager subsequently located retained section 96(j) evidence and reported
starting KS-600's provision-reference contract. Consume the resulting upstream
identities/records when delivered; do not invent its wire schema. An unresolved
legal-account crosswalk does not prevent preserving or citing the lapse action,
but it must prevent asserting a reviewed composite join. The [retained-source
review](../instances/ks-state-civics/research/sb125-provision-handoff.md) supplies
the evidence locator and distinguishes the Chapter 128 amendment marker from
the scope actually checked. This update does not complete upstream persistence
or WAVE-133 integration.

Seven-book extraction follow-up: verified retained source/output hashes and
unique ordered page markers across 6,587 declared pages. The [readiness
audit](../instances/ks-state-civics/research/session-law-extraction-readiness.md)
corrects section 96(j)'s proposed character endpoint, documents producer-side
QA/registration exclusions and preserves the same owner boundary. These
machine-readable bytes are now available for evidence review; the canonical
schemas, reviewed derivation/records and adapter/API acceptance remain separate.

The page-local follow-up verified section 96(j) at page 358, inclusive lines
30–34 under an explicit marker/blank-line convention. Registration and current
offline ExAIS validation do not yet prove that a locator selects the supplied
quote. The [concrete integration handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md#concrete-input-needed-for-exais-integration)
lists the incoming records/evidence and remaining ExAIS implementation. This
clarifies existing evidence acceptance; no runtime completion is claimed.

The independent document verifier is now implemented in the existing artifact
module and `verify-document-evidence` CLI. It resolves actual retained Markdown
page/line text before accepting quote/hash consistency. The real section 96(j)
passes; wrong-page, neighboring-lapse and truncated selections fail. Root's
combined regression returned **370 passed, zero skipped**. See the
[document-evidence proof](../.tranche/statecivics-semantic-graph/aligned/wave-133-document-evidence-proof.md)
for commands, exact evidence, bounds and deferred acceptance. Independent
[QC](../.tranche/statecivics-semantic-graph/aligned/wave-133-document-evidence-qc.md)
returned **PASS WITH NOTES** for this increment, including 191 passing targeted
checks with zero skips. This is an offline primitive, not the upstream
first-write registration fix or live graph integration; WAVE-133 remains in
progress.

The next bounded increment adds the explicitly named marker-inclusive convention
used by upstream `668ca412`: page 358, lines 31–35. The prior after-marker-LF
convention remains unchanged at 30–34; both resolve the same quote and absolute
offsets, and swapped conventions/ranges are rejected. Root's regression returned
**379 passed, zero skipped**. See the [convention alignment proof](../.tranche/statecivics-semantic-graph/aligned/wave-133-locator-convention-alignment-proof.md).
Independent [QC](../.tranche/statecivics-semantic-graph/aligned/wave-133-locator-convention-alignment-qc.md)
returned **PASS WITH NOTES**, with 200 targeted tests passed and zero skipped.
This completes only the convention-alignment increment; no next ticket has started.

The [locator verification handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md#locator-verification-handoff)
records a proposed upstream-owned verification state, distinct from confidence,
publication and evidence class. The eventual adapter must preserve the agreed
state and its bound derivation; absent legacy metadata and unsupported resolvers
cannot imply an exact verified citation. No new upstream schema or production
registration behavior is implemented in this ExAIS increment.

Upstream follow-up `37f5b1c9` closes the three reviewed helper gaps from
`668ca412`: missing recorded text hash, duplicate page markers and empty
page/character selections. The [bounded recheck](../.tranche/statecivics-semantic-graph/aligned/wave-133-upstream-locator-recheck-proof.md)
records actual consumer-side verification separately from the manager-reported
453 passed / 66 skipped upstream gate. At that revision the remaining span tasks were
authoritative-text retrieval/passing in the fiscal-fact caller and bound
locator-verification metadata; broader canonical export and live integration
acceptance remain open. This follow-up changes documentation/proof only and
does not start another ticket or rerun the unchanged ExAIS runtime suite.
Independent [documentation/proof QC](../.tranche/statecivics-semantic-graph/aligned/wave-133-upstream-recheck-qc.md)
returned **PASS WITH NOTES**, including confirmation of the separately measured
Markdown-ingestion coordinate gap recorded for WAVE-134 planning. No runtime
files changed in this follow-up.

Subsequent read-only review confirms `06720d19` passes the existing lineage-bound
`context.text` into registration and repairs the page-marked fixtures. The caller
finding is closed in code. The manager reports 67 executed tests through the
PostgreSQL evidence gate after the JUnit fix at `3f975e79`; ExAIS has not
independently rerun that gate.
The [current attestation handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md#locator-verification-handoff)
now specifies append-only results bound to immutable spans, export of the
selected attestation/derivation references and snapshot-pinned applicability.
This remains upstream implementation, not a new ExAIS wire contract. The
[completed statute inventory](../instances/ks-state-civics/research/statute-harvest-handoff.md)
does not close canonical export or end-to-end acceptance; it corrects the size
filter and repeated-history denominators before any statute ingestion.
