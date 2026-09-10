# StateCivics law-and-money implementation handoff

Agreed with the StateCivics developer manager through the owner on 2026-09-10.
Scope: Kansas State Civics fiscal retrieval. This is the corrected implementation
direction, not evidence that the revised runtime or public graph is complete.

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
here. The local planning handoff uses
`/Users/mfrieson/Developer/statecivics-fiscal-graph-plan/tickets/` for upstream
edits. Its canonical operational repository is `operator-source://statecivics-ai`.
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

Compare exact/lexical, document semantic, entity semantic, hybrid and hybrid with
graph. Record path and amount/year/source correctness, useful positive answers,
gap/ambiguity refusals, isolation/lifecycle leakage, latency and cost. A run that
only refuses cannot establish success. Synthetic tests remain useful mechanics
and security checks, independently labeled from real-source acceptance.

The separate K.S.A. harvest is already underway. The latest manager handoff
reported 2,062 of 31,085 sections, chapter 9 of 91, with no failures; this is a
dated inventory report, not a completion or custody-registration check. Do not
restart it or add a pre-harvest canary. Current statutes supply standing authority,
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
