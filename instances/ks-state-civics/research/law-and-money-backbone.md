# Law-and-money backbone: open-source research

Research date: **2026-09-10**. Scope: **Kansas State Civics instance**.

Status: the owner accepted the research direction and requested that it be
recorded here. The architecture is already committed upstream. Classification
and aggregation rules below remain decisions to specify and verify before
population; this is research documentation, not an implementation or activation
report. The developer-manager handoff on 2026-09-10 settled ownership and reuse;
ticket correction has resumed. The implementation rules still need to be
specified and verified by their assigned owners, not decided again in ExAIS.

## Finding

Keep the existing separation between legal operations, fiscal values, their
context, and their evidence. Public legal and fiscal repositories provide
strong precedents for those components. None of the inspected repositories
establishes the exact Kansas legal-operation vocabulary or implements the
complete enacted-provision-to-KanView GraphRAG chain.

The focused path remains:

**Enacted provision → appropriation action → fiscal-year account → agency/fund**,
with exact legal and supporting budget evidence attached to the relevant
records and relationships.

## Existing architecture and prior art take precedence

StateCivics owns the canonical graph and civic facts in its statewide PostgreSQL
database. Its custody/source ledger owns retained source revisions, hashes,
spans, and derivations. ExAIS serves scoped, rebuildable retrieval indexes and
derived graph projections through versioned contracts.

This implements the existing ADR-CII-001 and ADR-CII-011 boundary. It does not
require another canonical database or a new architecture decision. The upstream
review recorded PASS on 2026-09-09 in:

`docs/specs/civic-impact-intelligence/ARCHITECTURE_REVIEW_SINGLE_CANONICAL_STORE.md`

The upstream source is `operator-source://statecivics-ai`. Read these existing
contracts and implementations before specifying new work:

| Upstream path | Existing responsibility |
|---|---|
| `contracts/civic-impact/appropriation-action.schema.json` | Legal operation, directional account references, period, bill version, source, derivation, status, and supersession. |
| `contracts/civic-impact/fiscal-fact.schema.json` | Fiscal value/estimate, stage, metric, legal and accounting identities, field evidence, and separate publication/resolution/lifecycle states. |
| `contracts/civic-impact/methodology-enums.yaml` | Evidence-class definitions and separate source tiers. |
| `contracts/civic-impact/source-span.schema.json` | Revision-bound evidence coordinates and content hash. |
| `contracts/civic-impact/derivation.schema.json` | Typed, revision-bound input/output references and set hashes; the agreed action-to-fact linkage. |
| `contracts/civic-impact/retrieval-export-record.schema.json` | Existing document/custody export, redistribution eligibility, and lifecycle/removal signals. |
| `contracts/civic-impact/publication-record.schema.json` | Existing entity publication/correction contract; do not duplicate it in a graph exporter. |
| `contracts/civic-impact/intelligence-snapshot.schema.json` | As-of source/dataset/methodology context for reproducibility. |
| `src/kansas_accountability/models/fiscal_intelligence.py` | Existing `FiscalFact` and field-to-span evidence persistence. |
| `src/kansas_accountability/models/source_artifacts.py` | Existing source revisions, `SourceSpan`, and derivation records. |
| `src/kansas_accountability/services/civic_impact/source_artifact_service.py` | Existing source/span registration service. |
| `src/kansas_accountability/etl/ksleg/bill_rest.py` | Existing `RestMeasureTextSection` parsing where the upstream API supplies section data. |
| `src/kansas_accountability/etl/ksleg/sos_session_laws.py` | Existing official session-law chapter-to-bill lookup. |

KS-600 remains the owner of appropriation reconciliation, and KS-601 of account
crosswalks. At inspection, KS-600 explicitly listed the appropriation-action
ledger itself as an implementation gap. A contracted vocabulary must not be
mistaken for a populated, functioning reconciler.

The manager clarified the remaining ownership: KS-595 owns span infrastructure
and the retrieval exporter; KS-597 owns exact fiscal-field span population;
KS-600 will define the missing version-specific provision reference within its
existing provision-linkage scope. A new exporter follow-up will extend KS-595
with a second entity/relationship record type. KS-613 remains the school-finance
slice; broader generalization belongs in a sibling acceptance ticket.

## Public repositories inspected

The comparison used primary repository schemas/code and project documentation,
including an independent fiscal-model review. Links identify the inspected
interfaces; branch URLs can change and are research references, not dependency
pins. The lessons below are design conclusions for StateCivics.

| Repository and inspected source | Verified pattern | Application and limits |
|---|---|---|
| [USAspending API — appropriation account balances](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/accounts/models/appropriation_account_balances.py) | Separate decimal-valued authority, obligations, outlays, balances, reporting periods, and submission identity. The model documents cumulative fiscal-year submissions; `final_of_fy` selects the latest submission per Treasury account/year. | Keep monetary measures distinct and select the applicable snapshot. This code is an accounting precedent, not a Kansas legal-action reconciler. |
| [OpenBudgets — components](https://github.com/openbudgets/data-model/blob/master/components.ttl) and [code lists](https://github.com/openbudgets/data-model/blob/master/code_lists.ttl) | Separate `budgetPhase`, `paymentPhase`, `operationCharacter`, fiscal period, and monetary `amount`. Budget phases include draft/approved/revised/executed; payment phases include allocated/certified/paid. | Supports separating fiscal context from the measured value. Its operation character means revenue/expenditure; it is not equivalent to appropriate/veto/override. Treat this older ontology as a reference design. |
| [Laws.Africa Indigo — amendments](https://github.com/laws-africa/indigo/blob/main/indigo_api/models/amendments.py) and [works/commencements](https://github.com/laws-africa/indigo/blob/main/indigo_api/models/works.py) | `Amendment` links amending and amended works with an effective date. `AmendmentInstruction` distinguishes provision identifiers, names, pages, resulting documents, and application state. Commencements can identify specific provisions. | Strong precedent for legal events tied to identified provisions and versions. It does not supply fiscal-account semantics. |
| [GPO USLM — user guide, attribute groups](https://github.com/usgpo/uslm/blob/main/USLM-User-Guide.md#45-attribute-groups) | Separate element identification, amendment action, references, normalized values, and temporal status. Immutable `id` differs from evolving numbering-based identifiers. | Keep provision identity, displayed section number, evidence location, and effective time distinct. USLM amendment actions concern legal-text changes; they do not validate our fiscal enum verbatim. |
| [Nanopublication Python](https://github.com/Nanopublication/nanopub-py) and [provenance examples](https://nanopublication.github.io/nanopub-py/publishing/setting-subgraphs/) | Assertions carry separate provenance and publication information; provenance can identify source derivation and attribution. | Supports source/derivation/publication separation. It does not prescribe StateCivics' five evidence classes or require replacing PostgreSQL with RDF. |

Two additional fiscal references help bound the comparison:

- [Frictionless Fiscal Data Package v1](https://github.com/frictionlessdata/datapackage/tree/v1/fiscal-data-package)
  is labeled 1.0-rc.1. Its discussion identifies limitations in the older
  measure-column/four-phase assumptions; the
  [budget taxonomy](https://github.com/frictionlessdata/datapackage/blob/v1/taxonomies/fiscal/budgets.json)
  supports explicit fiscal concepts and source mappings. Do not cite the
  [OpenSpending 0.3 specification](https://github.com/openspending/fiscal-data-package/blob/master/0.3/index.md)
  as the latest modelling recommendation.
- [OCDS Budgets and Spend extension](https://github.com/open-contracting-extensions/ocds_budget_and_spend_extension/blob/master/release-schema.json)
  separates measures, classifications, periods, breakdowns, and financial
  progress. Its `totalSpend` definition requires publisher-specific
  interpretation, such as invoiced amounts versus payments. This is useful
  downstream prior art; procurement expansion is outside this fiscal milestone.

These are references for design and validation. The seven repositories were
[downloaded as ordinary local files](upstream-code/README.md) on 2026-09-10,
including source, schemas, tests, examples, and documentation. No upstream code
was installed or integrated, and no new graph engine is required by the findings.

## Field responsibilities to preserve

| Field | Intended responsibility | Population rule to settle |
|---|---|---|
| `appropriation_action.action_type` | What the legal provision does. | Use the existing legal-action vocabulary and retain direction, conditions, effective period, and exact provision evidence. |
| `fiscal_fact.stage` | The fiscal/legislative context in which the value applies. | Define the meaning of each existing stage and its allowed combinations with metric/action; do not copy `action_type` automatically. |
| `fiscal_fact.metric` | What the value measures. | Distinguish authority, expenditure, transfer, lapse, and other measures; identify compatible scope and aggregation semantics. |
| `fiscal_fact.evidence_class` | The evidentiary character of this particular assertion under StateCivics methodology. | Define precedence for overlapping cases, while preserving publisher authority separately in source metadata. |

The existing action vocabulary is:

`appropriate`, `increase`, `decrease`, `lapse`, `transfer`, `reappropriate`,
`limit`, `veto`, `override`, `technical_correction`.

`action_type=transfer` and `metric=transfer` may coexist: one identifies a legal
operation and the other describes the value reported about it. Their records
need an explicit, source-backed relationship. ExAIS must consume that upstream
relationship rather than independently reclassifying the action.

### Resolve the stage overlap

The current enum combines legislative contexts such as `introduced_bill`,
`enrolled_bill`, and `final_authority` with `transfer`, `lapse`, and
`reappropriation`. Before population, specify:

- which contexts use those operation-like stage labels;
- whether `final_authority` refers to a particular enacted or reconciled
  snapshot, and the time/scope of that snapshot;
- how `actual_expenditure` stage relates to `expenditure` metric;
- allowed and invalid `stage × metric × action_type` combinations, including
  fiscal facts that have no corresponding appropriation action.

This research does not select a replacement enum. Preserve the contracted
values while settling their interpretation and validation rules.

### Resolve evidence-class precedence

The existing classes are `OFFICIAL`, `CALCULATED`, `MODELED`, `OBSERVED`, and
`CAUSAL`. The master specification requires exactly one class for each public
number or conclusion, and already maintains source tiers separately.

The definitions overlap in practice: an observed expenditure may be reported
in an official dataset; an official report may contain modeled estimates.
The classification policy must explain these cases. An official publisher
alone cannot settle the methodological character of every resulting assertion.
Preserve the source's statement, derivation method, assumptions, and review
record so the chosen class is explainable. None of the inspected fiscal
schemas establishes the exact five-way taxonomy for us.

## Monetary aggregation rules

Use a defined fiscal-fact query as the monetary aggregation surface, with
explicitly compatible measures, periods, accounts, source versions, and
accounting boundaries. Legal actions supply the authority and change lineage.

- An action amount and a linked fiscal fact describing that amount are two
  representations of the same event; never union them into a total.
- Distinguish a change amount, a cumulative balance, and a flow during a
  reporting period. Preserve their source meaning before defining arithmetic.
- Repeated cumulative reports and superseded snapshots are not additional
  spending. Snapshot selection must be explicit and reproducible.
- Transfer source/destination entries require a defined consolidation
  boundary; both legs cannot automatically be counted as spending.
- Preserve null/unknown/no-limit semantics. Missing records and incomplete
  coverage do not establish zero spending.
- A resulting authority balance is a reconciled derivation. It is not obtained
  by summing all retrieved amounts or all graph neighbours.

The agreed action-to-fact link uses the existing derivation contract: typed
`inputs` referencing `appropriation_action` and typed `outputs` referencing
`fiscal_fact`, plus input/output set hashes. Verified contract detail: inputs use
`{type, id, revision_or_hash}`; outputs use `{type, id, hash_sha256}`, with the
output hash currently optional/nullable. KS-600 must supply it for reviewed
lineage; the two reference shapes are not identical.
Do not add `appropriation_action_id` to the fiscal-fact contract. A derivation
with several inputs and outputs establishes their joint provenance; it does not
justify every possible one-to-one pairing. Preserve the derivation context and
require supported correspondence before projecting a stronger relationship.

KS-600 owns the allowed-combinations table, evidence-class interpretation,
snapshot selection, and reconciliation rules described above. ExAIS consumes
their versioned results and preserves the meanings of the supplied values.

## Provision identity and exact evidence

A dedicated shared provision identity is not present in the inspected civic
contracts. Existing `SourceSpan.locator` can carry section coordinates, and
appropriation actions already accept `source_span_id`. The focused gap is a
validated provision-reference definition, a legal-locator convention, and
populated evidence, rather than absence of all section-level infrastructure.
KS-600 will define the reference; KS-595 supplies span infrastructure and KS-597
populates exact fiscal-field spans. No provision ID exists yet, so changing the
ExAIS SourceSpan-as-provision-ID rule requires upstream implementation first.

Keep two concepts separate:

1. A version-specific provision reference identifies the legal instrument,
   version, and structured section/subsection path.
2. A source span identifies the retained source revision and exact page/text
   coordinates, quotation, and hash supporting that provision or extracted field.

A section label such as `96(j)` is not globally unique. Re-extraction can change
evidence coordinates without changing legal identity. Renumbering or amendment
across versions needs an explicit lineage relationship; matching section labels
alone cannot prove continuity. Indigo and USLM provide the relevant precedents.

Statute History entries supply cited year/chapter/section references. Resolving
them to retained session-law provisions and then to bills requires separate
source-backed resolution. A history reference does not establish an
appropriation-to-account relationship.

## Alignment with the ongoing K.S.A. harvest

The StateCivics developer-manager handoff confirms that the fiscal classification
rules are downstream of source acquisition. The statute harvest can continue
while these rules, provision identity, and exact-span contracts are settled.
This research does not require the scraper to emit fiscal facts or populate
`action_type`, `metric`, or `evidence_class`.

Two retained corpus samples were inspected after that handoff:

- [K.S.A. 1-204](https://ksrevisor.gov/statutes/chapters/ch01/001_002_0004.html)
  establishes the board of accountancy fee fund and requires its expenditures
  to follow appropriation acts.
- [K.S.A. 2-1904(g)](https://ksrevisor.gov/statutes/chapters/ch02/002_019_0004.html)
  establishes the compensatory mitigation fund, identifies its administration,
  and likewise ties expenditure to appropriation acts.

These illustrate the source boundary: K.S.A. can establish a fund and standing
authority; a separate Session Law supplies the particular fiscal action.
SB125 section 96(j), below, belongs to the retained Session Laws corpus, not
the current K.S.A. harvest. Fund names and statutory references still require
reviewed crosswalks to KanView identities; matching prose does not prove a join.
This is a source-role distinction, not a blanket rule that statutes contain no
quantitative provisions or that every Session Law passage is an appropriation.

The current committed `statute_parsers.py:parse_history_events` was rechecked:
it emits ordered references with `resolution_status: unresolved`, and the
scraper's provenance record carries both raw History and parsed events. This
supersedes the earlier read-only observation that structured History output was
absent. Retaining an unresolved reference does not assert a resolved graph edge.
No completed harvest or custody-registration result was inferred from this
bounded code/sample inspection.

Number-derived filenames remain acquisition addresses. The provision-locator
contract must distinguish section number, version-specific legal identity,
cross-version lineage, and evidence location. `scraped_at_utc` records capture
or processing observation time; it does not establish legal effective time or
temporal status. A later renumbering must not silently become an unrelated law,
and equal numbering across editions must not imply unchanged text. Preserve
unknown effective dates until supported by evidence. These are downstream
identity requirements, not instructions to interrupt or alter the running
harvest.

## Real Kansas example

[2025 SB125, Chapter 117, section 96(j)](https://sos.ks.gov/publications/sessionlaws/2025/Chapter-117-SB-125.html)
directs a **$4,000,000 lapse** on July 1, 2025, against the FY2026 supplemental
state aid appropriation, citing section 3(a) of Chapter 111 of the 2024 Session
Laws and account `652-00-1000-0840`.

This supports a lapse action and a fiscal fact about its amount, linked to the
same exact evidence. Remaining authority requires reconciliation with applicable
actions; actual expenditure requires separate fiscal evidence. The source does
not turn an action record and its linked value into two monetary events.

This is a source example for design, not a claim that a reviewed canonical
record or live graph edge has been populated. The example does not assign a
stage before the classification rules above are settled.

## Agreed ticket corrections

See [the corrected ticket map](ticket-alignment.md) for canonical ticket links,
implementation ownership and the active planning artifacts.

- Under KS-600, define allowed field combinations and evidence-class precedence using real
  enacted provisions, budget reports, and KanView observations.
- Under KS-600, define the shared provision reference and its exact-span binding, reusing the
  existing source registration service and legal parsers.
- Use typed derivation inputs/outputs for action-to-fact linkage; specify snapshot
  selection and aggregation under KS-600, and reviewed crosswalks under KS-601.
- Extend KS-595's existing exporter with a second versioned record type for
  canonical entities, relationships and source-derived semantic descriptions.
  Preserve document-record compatibility and existing lifecycle/removal semantics;
  reuse publication-record and intelligence-snapshot contracts.
- The publication contract currently omits fiscal entities from `subject_type`;
  the exporter follow-up must define a compatible extension/mapping coordinated
  with KS-605, rather than assume every entity is already representable.
- Support structured CSV evidence without invented PDF pages or text chunks.
- Add a sibling to KS-613 to verify the process across multiple bills, agencies, fiscal years, and
  action types, with a positive held-back bill/agency case. Adding a bill should
  require source/configuration/review, not a bill-specific parser branch.
- Keep semantic search as candidate retrieval over passages and source-derived
  descriptions. Canonical identities and evidenced relationships govern joins.

The initial manager handoff reported 2,062 of 31,085 sections, chapter 9 of 91,
with no failures. That dated progress report is now superseded by the
[completed retained-corpus audit](statute-harvest-handoff.md): 31,079 files after
six repeated document groups. Its size-filter and history-denominator corrections
govern ingestion planning. No restart is needed, and acquisition completion is
not evidence that these sections are registered, indexed or published.

The current ExAIS v1 mechanics still require corrections to provision identity,
structured evidence, and the provisional publisher envelope. Earlier tests
remain historical mechanics proof. See the
[unified implementation handoff](/Users/mfrieson/Developer/exais-vector-store-ovh/docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md)
for the corrected ownership and ticket map.

Return to the [instance index](../README.md) or the
[fiscal store documentation](../vector-stores/kansas-fiscal-documents/README.md).
