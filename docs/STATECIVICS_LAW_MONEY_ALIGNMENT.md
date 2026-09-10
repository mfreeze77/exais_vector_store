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
