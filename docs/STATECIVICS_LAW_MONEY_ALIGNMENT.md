# StateCivics law-and-money implementation handoff

Agreed with the StateCivics developer manager through the owner on 2026-09-10.
Scope: Kansas State Civics fiscal retrieval. This is the corrected implementation
direction, not evidence that the revised runtime or public graph is complete.

## Current implementation handoff

The K.S.A. harvest is independent of this milestone. The first appropriation
sample uses retained bill/Session Laws evidence; current codified statutes
supply supporting definitions and authority. Finishing that harvest supplies
none of the missing contracts, legal spans or appropriation-action persistence.

The StateCivics manager owns the upstream KS implementation. The next handoff is:

1. KS-600's provision-reference contract and KS-650's versioned entity/relationship
   export contract, including the existing publication-subject compatibility
   decision. Planning tickets alone do not provide those schemas.
2. A first retained-source slice from KS-613: SB 125 section 96(j), its exact
   provision/span evidence and the specified $4 million lapse action, persisted
   through the KS-600 ledger. Verify the values and locator against retained
   evidence before producing the reviewed export.
3. Existing account/agency/fund identities and recovered exact CSV record
   evidence attached through supported upstream references. KS-601 must review
   any legal-account crosswalk before a positive join is published; if still
   unresolved, export that gap explicitly. Loaded observations alone do not
   establish that join, and missing subunit must remain unknown.

The manager reports legal spans and account crosswalks unpopulated, and the
appropriation-action contract without a backing model/table/migration. That
is the minimum data-path work; a new statute corpus is not its prerequisite.
These are reported data states, not fresh ExAIS queries of the operational DB.

The manager has now located the retained SB 125 provision and started the
KS-600 provision-reference contract. This is active upstream implementation,
not a harvest wait. The action and span can be recorded with the legal account
reference unresolved; a positive crosswalk is not required to preserve the
source-backed lapse. The existing candidate KanView account `652-1000-840`
does not resolve the full legal reference `652-00-1000-0840`: missing subunit
must remain unknown. See the [retained-source handoff review](../instances/ks-state-civics/research/sb125-provision-handoff.md)
for exact page coordinates and the chapter-amendment check.

The subsequent seven-book Session Laws extraction is present and hash-verified
(6,587 declared pages with matching unique ordered Markdown page markers).
Its proposed section 96(j) character range omitted the lapse phrase; the exact
complete range and producer QA/registration gaps are recorded in the
[extraction readiness audit](../instances/ks-state-civics/research/session-law-extraction-readiness.md).
Existing probe, numeric validation and raw fiscal registration exclude Session
Laws, so they need explicit bounded support before being used for this handoff.
This is upstream QA/registration work alongside the schemas, not a reason to
wait for the K.S.A. harvest or to rerun a hash-verified extraction by default.

KS-600 still owns the allowed `stage` / `metric` / `action_type` combinations
and the treatment of observed values from official sources. Those rules gate
reviewed fiscal classification and reconciliation, not writing the schemas or
retaining the legal evidence. ExAIS will consume the upstream interpretation.

ExAIS could already read the planning branch. The agreed planning documents are
now merged and pushed to StateCivics `main` at `1649b8ad` (2026-09-10), making
KS-650 and KS-651 visible in the shared repository. The merge changes only 12
Markdown files and preserves main's later inventory correction; it adds no
contracts or runtime implementation. Independent review passed, as did all 19
checks in `tests/ops/test_civic_spec_ticket_dependencies.py`, run through
`KS_GATE_NO_LEDGER=1 ./scripts/run_gate.sh statewide` with `-q -p no:cacheprovider`.

The completed ExAIS work at `e9a713b` is the independent offline foundation;
WAVE-133 remains in progress until the actual upstream handoff and adapter/API
acceptance arrive. See [its proof](../.tranche/statecivics-semantic-graph/aligned/wave-133-offline-proof.md).

The subsequent [offline document-verification increment](../.tranche/statecivics-semantic-graph/aligned/wave-133-document-evidence-proof.md)
resolves page/line selections from retained Markdown and checks exact quote
content/hash. It rejects the real neighboring lapse and truncated section 96(j)
selection. This supplies a separate verification primitive; upstream first-write
registration, raw-source derivation and live adapter/API integration remain
required.

The upstream first-write resolver landed at `668ca412` and its three reviewed
trust/bounds fixes at `37f5b1c9` (2026-09-10). The manager reports 453 passed,
66 skipped and zero failures for the latter; ExAIS did not rerun that upstream
gate. Its page-local
origin includes the marker as line 1: the worked section 96(j) is therefore
page 358, lines 31–35. ExAIS explicitly supports this origin alongside its prior
after-marker-LF convention (30–34); both reproduce the same retained quote/hash.
Do not silently reinterpret older locators. The
[convention alignment proof](../.tranche/statecivics-semantic-graph/aligned/wave-133-locator-convention-alignment-proof.md)
records the original findings against `668ca412`. The [upstream recheck](../.tranche/statecivics-semantic-graph/aligned/wave-133-upstream-locator-recheck-proof.md)
covers their closure at `37f5b1c9`: reject missing recorded text hashes,
duplicate page markers and empty page/character selections. These helper fixes
do not establish real-span persistence or completed integration. Authoritative
text retrieval and bound locator-verification metadata remain upstream work,
alongside the canonical contracts, records and export.

### Locator verification handoff

Record whether the locator was verified against the retained artifact, separately
from `evidence_class`, locator confidence, legal identity and publication status.
This requirement is agreed with the manager and belongs to the existing
KS-595/597 span owners, carried by KS-650's export; the exact wire shape still
belongs upstream. ExAIS must consume it rather than create a competing contract.
Suggested representation: `locator_verification`,
with `status` (`verified` or `unverified`), a verification derivation reference
for a successful check, and a reason when no supported check ran. Missing legacy
metadata means unverified, never implicitly verified. A real mismatch rejects
the write; a failed attempt belongs in the existing derivation/audit path.

Reuse `derivation.schema.json` for method/version, parameters, typed references
and input/output hashes. Bind the result to the exact source/extraction revision
and retained bytes, locator including its convention, and selected quote hash.
Neither `status=complete` on a general extraction run nor the span's existence
proves that this particular selection was checked. Re-extraction, locator changes
or changed quote bytes require a new bound check, preserving prior evidence.
The producer must set the result from execution, not trust a caller's flag.

Table cells are **unverified by the text resolver**, not inherently unverifiable.
The current `CandidateTableCell.source_span_registration` carries page, table,
row/column, row/column spans and exact `raw_text`, using
`marker_paginated_markdown_table_v1`. A table-aware resolver can verify these
against hash-bound retained table/layout output and extraction lineage; geometry
alone does not prove the cell's text. Preserve candidate evidence while that
check is absent, but do not present it as a verified exact fiscal citation.
This does not ban ordinary eligible document search or delete legacy spans.

At `37f5b1c9`, `fiscal_fact_service._validate_text_derivation` checks that a
`DerivationOutput` records the expected hash; it does not load the text bytes.
Its `register_span` call still omits `artifact_text`. Retrieve the authoritative
output through the existing retained-source/derivation path, verify its hash,
then pass the exact text to the resolver. Passing that verified text is an
implementation detail; caller-chosen unanchored text is the trust defect.
The missing-hash, duplicate-marker and empty-selection helper fixes are now
present; they should not remain on the open-work list. The authoritative-text
caller wiring and bound verification metadata remain with the StateCivics manager.

## Backbone and authority

**Enacted provision → appropriation action → fiscal-year account → agency/fund**,
with exact legal and supporting budget evidence. Statewide StateCivics PostgreSQL
is the canonical civic graph under ADR-CII-001 and ADR-CII-011. Custody and the
source ledger retain evidence and derivations. ExAIS indexes scoped projections.

| Responsibility | Owner | Required handoff |
|---|---|---|
| Source revisions and span infrastructure | KS-595 | Retained bytes, revision identities, validated locators and evidence hashes. |
| Fiscal-field span population | KS-597 | Exact field evidence; existing document eligibility rules remain in force. |
| Provision definition and appropriation reconciliation | KS-600 | Version-specific provision reference, legal actions, typed derivation links, period/classification/arithmetic rules. |
| Accounting ontology and observations | KS-598 | Existing canonical identities and source observations, scoped by agency, fiscal year and code system. |
| Account crosswalk decisions | KS-601 | Reviewed effective-dated decisions; ambiguity and absent join keys remain explicit. |
| Entity/relationship export | KS-650, extending KS-595 | Second versioned record type in the existing exporter; document records remain compatible. |
| Publication and as-of context | Existing KS-605 publication and intelligence-snapshot contracts | Reuse their semantics; contract existence alone does not establish eligible records or a working producer. |
| School-finance slice | KS-613 | Existing SB125 slice stays intact, including its separate payment/outcome deliverables. |
| Generalization benchmark | KS-651, sibling to KS-613 | Reviewed real cases across bills/agencies/years, including an unseen positive case. |
| Derived evidence graph | WAVE-133 | Consume provision IDs and structured/document evidence without inventing PDF bindings. |
| Projection ingestion and lifecycle | WAVE-134 | Scoped semantic/graph visibility, corrections and withdrawal, including ordinary search. |
| Exact/semantic retrieval and traversal | WAVE-135 | Provider-free exact baseline and bounded typed paths using canonical identities. |
| Comparative real-answer proof | WAVE-136 | Baselines versus hybrid/graph; cited positive answers and correct refusals. |
| Integrated acceptance and activation | WAVE-132 | Remains reopened until real evidence and revised runtime pass; activation is a separately evidenced operator action. |

KS tickets are authored in the StateCivics repository; WAVE tickets are authored
here. The planning handoff originated at
`/Users/mfrieson/Developer/statecivics-fiscal-graph-plan/tickets/`; its canonical
operational repository is `operator-source://statecivics-ai` at
`/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai`.
New tickets are planned work, not claims of implementation completion.

## Contract decisions

`appropriation_action.action_type` expresses the legal operation. Fiscal-fact
`stage` supplies context, `metric` identifies the value measured, and
`evidence_class` describes the assertion. Preserve existing enums. KS-600 must
specify their allowed combinations and evidence-class interpretation using real
sources; ExAIS must not independently reclassify values.

KS-600 defines provision identity separately from section numbering, source-span
coordinates and legal effective time. A source span locates evidence; its ID is
not a provision ID. Re-extraction need not change legal identity, and matching
section labels across editions do not prove continuity. Preserve unknown dates.
For the worked case, the citation must include Kansas, the 2025 Session Laws,
Chapter 117 and section 96(j), bound to the actual legal instrument/version.
That citation identifies the provision in context; it is not, by itself, the
canonical identifier. Re-extraction preserves legal identity. A different legal
version or renumbering requires explicit lineage rather than blindly reusing a
version-specific reference. Required bill/version references must resolve to
retained canonical records; the manager-reported absence of an SB 125 bill
version is not permission to fabricate one in the ExAIS adapter.

Page-local lines are useful evidence locators, but require a versioned convention
and exact extraction binding. A quote hash is not a canonical provision ID, and
checking a supplied quote against its hash does not prove that a locator selects
it. Both absolute and local offsets are exact within immutable artifacts; old
locators must fail verification against changed extraction bytes. The
[measured locator review](../instances/ks-state-civics/research/session-law-extraction-readiness.md#page-local-convention-checked-against-the-same-artifact)
records the supported example and current verification gap.

Chunk boundaries are retrieval boundaries, not provision boundaries. Attach
canonical action references through reviewed exact span-to-action bindings,
preserving their source revision and locator. A chunk may contain both section
96(i) and 96(j); citing either requires resolving that specific supporting span.
Never infer the binding from shared words, an agency name or a chunk-level tag.
The existing chunk page/character columns should be populated first; the bounded
WAVE-134 document-coordinate increment can proceed without inventing Tier 3 IDs.

Use `derivation.schema.json` typed `inputs` and `outputs` and input/output set
hashes for action-to-fact lineage. Inputs require `{type, id, revision_or_hash}`;
outputs use `{type, id, hash_sha256}`. The current output hash is optional/nullable;
KS-600 must populate it for the reviewed lineage rather than assume symmetric
reference fields. Do not add a parallel link field or ledger. A multi-input/multi-output
run proves joint derivation, not a Cartesian set of individual action/fact links.
Keep its context and require evidence for any stronger projected relation.

KS-600 supplies authority arithmetic and snapshot selection. An action and a
fact about its amount must not be counted twice. Distinguish changes, balances,
flows, transfers and expenditure. Missing evidence is not zero, an estimate is
not authority, and a law-to-account path does not establish a payment.

## One exporter, two record kinds

Extend `scripts/operator/export_retrieval_manifest.py` and the existing
`retrieval_exporter.py` service under KS-650. The current
`retrieval-export-record.schema.json` remains the document/custody record:
redistribution, license_profile, custody_status and lifecycle/removal already
exist. Do not add graph fields incompatibly to old document records.

The second versioned record kind carries canonical entity/relationship revisions,
typed evidence and derivation references, publication/correction context and
deterministic semantic descriptions. Reuse `publication-record.schema.json` and
`intelligence-snapshot.schema.json`. Validate eligibility per record and required
dependencies; an open ticket is neither proof of eligibility nor an automatic
ban on already eligible records.

The existing publication `subject_type` enum does not include fiscal entities.
KS-650 must define the bounded compatible extension/mapping with KS-605, preserve
existing subjects and correction semantics, and test it. Contract reuse does not
mean the current schema can already represent every new entity.

CSV dimensions/observations use retained structured evidence with reproducible
record locators. Legal and narrative claims use appropriate exact source spans.
Do not invent a PDF, a page number, or a text chunk for a structured entity.
If evidence is absent, preserve the gap rather than manufacturing a citation.

The ExAIS-specific `statecivics.fiscal-graph-publisher.v1` is a provisional legacy
adapter envelope. It is not the upstream contract StateCivics must implement.
WAVE-133/134 must adapt the agreed KS-650 output through existing scoped APIs.

Descriptions for semantic retrieval derive from sourced labels, aliases and
context; decimals and accounting observations stay structured. Vector similarity
finds candidates and never proves a legal/account join. Each embedding index
requires compatible query embeddings; graph joins use canonical IDs. This
milestone does not enable new cross-store traversal or change provider policy.

Keep retained text and quoted evidence unchanged. A separately versioned,
rebuildable search representation may join line-break hyphenation and normalize
whitespace, with mapping or canonical references back to exact evidence. Query
normalization alone may not match an index that retains split words. Preserve
legal/account identifiers and meaningful hyphens; never hash normalized search
text as though it were the retained quotation.

## Concrete input needed for ExAIS integration

The [semantic/graph metadata handoff](../instances/ks-state-civics/research/semantic-graph-metadata.md)
specifies how eligible Markdown search and canonical graph retrieval combine,
which metadata belongs on sources versus passages/entities, and the measured
page-coordinate gap in the current ingestion chunkers. Document search need
not wait for the complete graph, but bulk ingestion must preserve exact source
mapping; generic chunk metadata currently does not meet that requirement.

The next incoming bundle is produced by StateCivics; it is not another contract
authored by ExAIS. Its record-level eligibility may be established before all
upstream tickets close.

| Incoming item | What it must supply |
|---|---|
| KS-600/650 schemas and producer version | Actual provision-reference and second export-record schemas, required referenced schemas, dispatch/version semantics and compatible document records. |
| Small real canonical export | SB 125 legal instrument/version, section 96(j), persisted lapse action, supporting spans/derivations and accounting context; preserve the literal account and unresolved composite link. Include publication, resolution, lifecycle and as-of context. |
| Resolvable evidence bundle | Registered raw PDF and derived Markdown references/hashes, derivation and QA evidence, full locator convention, exact quote/hash and official PDF citation. Use deployable custody/approved evidence access, not only a workstation path. |
| Replay/correction example | Deterministic record/snapshot/source-set identity plus a reviewed correction or withdrawal example, preserving the existing document contract's removal semantics. |

The ExAIS repository needs the following implementation around that bundle:

1. Update the State Civics source declarations/locks from the delivered contract
   and supported Session Laws scope. Preserve the existing fiscal-document path;
   CPU-derived Markdown must keep its actual extractor provenance rather than
   be described as Marker output. Corpus bytes stay in custody or approved
   deployment storage; source declarations, bounded real fixtures and proof
   belong in this repository.
2. Finish WAVE-133's upstream adapter, exact evidence resolution, canonical
   projection persistence and API integration. Resolve full page/line locators
   against pinned text and compare the selected quote/hash. Reject wrong bounds,
   missing derivations, mismatched source/extraction revisions and truncated
   evidence; preserve CSV record evidence without fabricated document bindings.
3. WAVE-134 ingests eligible source text/entity descriptions with scoped
   correction/removal handling; WAVE-135 combines provider-free exact retrieval,
   semantic candidates and typed traversal with native citations. Use configured
   store embedding profiles; similarity never proves an account join.
4. WAVE-136 verifies real answers, failures and correction handling, including
   the KS-651 diverse and separately held-back cases. The first integration
   answer should report the $4M lapse, its date/fiscal year and exact citation,
   while stating that the composite KanView account mapping is unresolved.
   This useful partial path does not complete the reviewed full-chain benchmark.

Schemas permit adapter work to begin; the small real export and evidence permit
integration proof. Full statute harvest, bulk CSV embedding and a new graph
database are not prerequisites. These are remaining implementation requirements,
not capabilities established by the existing offline checks.

## Real-data acceptance and ongoing acquisition

KS-613's original authority, lapse, derived adjusted authority and independently
evidenced expenditure remain separate records. Its payment/forecast/outcome
deliverables are not prerequisites for the narrower ExAIS law-and-money path.
KS-651 supplies at least three bills, two legislative sessions, two fiscal years,
three agencies and multiple operations, with a reviewer-controlled positive
held-back bill/agency case. Freeze answer labels, coverage, denominators and
thresholds before tuning. Numerical answers require retained-source derivations;
the older pilot's constants alone do not qualify as ground truth.
The parallel lapse is section **95(c)**, correcting the manager's section 96(d)
reference after retained-source review. It is a useful second account/fiscal-year
example in the same bill; it does not replace KS-651's distinct-bill/session/
agency coverage or reviewer-controlled held-back case.

Compare exact/lexical, document semantic, entity semantic, hybrid and hybrid with
graph. Record path and amount/year/source correctness, useful positive answers,
gap/ambiguity refusals, isolation/lifecycle leakage, latency and cost. A run that
only refuses cannot establish success. Synthetic tests remain useful mechanics
and security checks, independently labeled from real-source acceptance.

The separate K.S.A. harvest continues on its own track; its completion is not a
gate for this handoff. Do not restart it or add a pre-harvest canary. Current
statutes supply standing authority,
definitions and unresolved history references. Retained Session Laws supply the
uncodified appropriation provisions; full statute completion does not block them.

## Historical implementation and corrected work

WAVE-130's v1 design and WAVE-132's existing mechanics assumed PDF/chunk evidence
for every node and used SourceSpan as provision identity. Those assumptions are
superseded. The existing source code still needs WAVE-133 through WAVE-136;
documentation changes do not make that runtime ready.

Read [WAVE-132](../tickets/WAVE-132-fiscal-law-money-graphrag-runtime.md),
[the operator path](FISCAL_GRAPH_OPERATOR.md), and
[the real-corpus audit](FISCAL_GRAPH_REAL_DATA.md) with this distinction.
The corrected planning artifacts and owner index are in
`../.tranche/statecivics-semantic-graph/aligned/`. Earlier ungated drafts are
superseded reference material, not a worker input.
