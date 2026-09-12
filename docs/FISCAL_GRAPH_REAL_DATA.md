# State Civics graph: correction from retained source data

The [2026-09-10 unified handoff](STATECIVICS_LAW_MONEY_ALIGNMENT.md) assigns the
corrections below to existing upstream owners and WAVE-133 through WAVE-136.
It replaces the universal PDF-binding assumption with typed structured/document
evidence, and SourceSpan-based provision identity with a reference to be defined
under KS-600. Source-corpus measurements below remain dated audit evidence;
they do not establish published canonical relationships or completed retrieval.

Measured 2026-09-10. This is the design basis for WAVE-132's reopened acceptance,
not a claim that a reviewed fiscal graph is deployed. The implemented v1 runtime
and its synthetic mechanics tests do not satisfy this basis yet.

## The graph has two evidence sources

The existing StateCivics fiscal ontology supplies the agency, fund and budget
account identities. ExAIS supplies retrieval over legal and fiscal narrative
documents. KanView CSVs stay in StateCivics custody and relational storage;
embedding the bulk CSV corpus is not a prerequisite for graph use.

| Evidence | Use in the agreed law-and-money scope | Required citation |
|---|---|---|
| Published enacted law, exact version and effective period | Provision and appropriation action, including increases, lapses and reappropriations | Source revision and legal span; distinguish base amounts from action amounts |
| KanView agency Exp/Rev extracts and existing fiscal ontology | Agency, fund and budget-account context, scoped by fiscal year | Source revision/hash, CSV record locator, raw observation and canonical identity |
| Comparison reports, GBR/GBA and other fiscal narratives | Supporting explanation and separately identified budget figures | Exact document version, passage/table context, year and units |

The missing implementation is a bounded projection of these **existing structured
records** into the State Civics graph and their reviewed links to enacted law and
documents. It is not a new statewide accounting database. Vendor, recipient,
payroll, outcomes and forecasts remain outside this increment.

## Concrete account evidence

Source directory: `/Users/mfrieson/Developer/statecivics-kanview-corpus`.
Custody: `/Users/mfrieson/Developer/statecivics-custody`.
The audit reads only `data/kanview/FY<year>/ExpData_<agency>_<year>.csv` and its
manifest, plus the matching custody object when requested. It never visits the
vendor or employee directories. Bulk source files and the detailed generated
evidence remain outside Git.

The law account reference under investigation is `652-00-1000-0840`.
It is a search input, not a declaration that a legal crosswalk has been reviewed.

| Real source field | FY2025 | FY2026 |
|---|---|---|
| Business unit | 652 — Department of Education | 652 — Department of Education |
| Fund | 1000 — STATE GENERAL FUND | 1000 — STATE GENERAL FUND |
| Budget reference | 0840 | 840 |
| Budget description | SUPPLEMENTAL GENERAL STATE AID | SUPPLEMENTAL GENERAL STATE AID |
| Program | 40600 — Financial Aid | 40600 — Financial Aid |
| Detail account | 551100 — STATE AID TO LOCAL GOVERNMENT | 551100 — STATE AID TO LOCAL GOVERNMENT |
| Matching data-record numbers, excluding header | 987, 2568, 3742 | 384, 2671 |
| Observed quarters | 1, 3, 4 | 1, 4 |
| Subunit | Not supplied | Not supplied |

The audit reads 75,746 source records across all 16 agency expenditure extracts
and retains 44 matching records. Fifteen fiscal years have matching
agency/fund/budget-reference observations. FY2016 has no match for this key in
the selected extract; that does not establish zero spending or the program's
absence from other accounts. FY2023 also uses `840`; padding does not simply
change once at FY2026. The upstream `kanview-1` rule strips leading zeroes only
from budget references and preserves the other codes.

Every matched source record retains its exact parsed headers/values, a digest of
that representation, a one-based data-record locator and the full CSV hash. CSV
record number is not assumed to equal PDF page or physical line number.
The audit computes no expenditure sums or growth rates. Observed quarters do
not certify that a year is complete, and a CSV expenditure observation is a
different measure from enacted appropriation authority or an approved estimate.

The FY2026 source SHA-256 is
`ea386136d6135334aa71f84331ec8ab68b2d5c83d9b992efe72b41e1a569eaed`.
A read-only check of the local StateCivics ledger found the identical hash on
retained revision `01a089bc-3323-7aa3-b086-d33deb935bed`. Its observation already
points to budget account `01a089bd-bd57-7555-8c25-adc9639ac677`, displayed as
`652-1000-840`, with normalized subunit null.

At that check, the account is `candidate/unresolved`; its agency, fund and
budget-unit dimensions are `candidate/resolved`. Their observation locators are
empty and their SourceSpan IDs are null. These records exist and are useful;
that is separate from publishing a reviewed legal-account relationship. The
audit does not change those statuses, create IDs, or insert source spans.

## Corrections required before real graph acceptance

1. **Structured evidence must be supported.** The implemented v1 requires every
   node to carry a current ExAIS chunk and a PDF page locator. A budget-account
   observation from KanView cannot satisfy that contract. The revised contract
   must distinguish document spans from structured observations, bind the latter
   to canonical IDs plus retained source revision/hash/record locator, and allow
   traversal through structured account/agency/fund nodes to cited documents.
   Do not manufacture PDF chunks or pages to make these records load.
2. **Use the existing upstream exporter boundary.** StateCivics owns the
   canonical records, source revisions, currentness and review decisions; ExAIS
   consumes a scoped, versioned projection. Product code must not read the
   StateCivics database directly. The manual SQL inspection was diagnosis only.
   Any CSV-reference projection needs replacement/withdrawal and source-currentness
   checks equivalent to those used for document evidence.
3. **Preserve both identity and missing information.** Account joins use fiscal
   year, agency, fund, budget reference and explicit subunit evidence. A hash of
   source bytes alone is not an identity: different agency/year selectors can
   legitimately return identical files. Null subunit cannot silently become
   `00`. Do not infer legal continuity across fiscal years or fill FY2016's gap.
4. **Preserve money semantics.** A lapse, base appropriation, reappropriation,
   approved budget estimate and recorded expenditure must remain distinguishable
   with year, units and source version. Do not turn a supporting-document edge
   into a claim that those figures reconcile. The earlier SB125 pilot arithmetic
   is not the answer oracle.
5. **Repair document citations using real extraction outputs.** The inspected
   active fiscal chunks have no populated page fields, and some PDF revisions
   have multiple extraction versions. Recover source locations from verified
   extraction artifacts or exact source text, retaining the selected extraction
   version. A fabricated page number or arbitrary first matching chunk is invalid.

## Reproduce the real-data audit

Run with read-only mounts; no provider calls or live mutations occur:

```sh
docker run --rm --network none --memory 256m --cpus 1 \
  -v /Users/mfrieson/Developer/exais-vector-store-ovh:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-kanview-corpus:/corpus:ro \
  -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro \
  python:3.11-slim python /work/scripts/release/kansas-fiscal-corpus-audit.py \
  --corpus-root /corpus --custody-root /custody \
  --legal-account 652-00-1000-0840 \
  --fiscal-years 2011 2012 2013 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026
```

Detailed output:
`/Users/mfrieson/Developer/statecivics-fiscal-exports/graphrag-audit/sb125-kanview-account-evidence.json`.
Its deterministic evidence digest is
`93547e91765a974358f1bbc002077d99ff74e223e479214f9b16d56af6ffaffc`.
This output is an audit artifact and cannot be loaded as `reviewed_public`.

```sh
docker run --rm --network none --memory 256m --cpus 1 \
  -v /Users/mfrieson/Developer/exais-vector-store-ovh:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-kanview-corpus:/corpus:ro \
  -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e SVS_FISCAL_CORPUS_ROOT=/corpus -e SVS_FISCAL_CUSTODY_ROOT=/custody \
  -w /work python:3.11-slim python tests/test_fiscal_real_corpus.py -v
```

Result: **8 tests passed, 0 skipped** against the real corpus. Checks include
all 16 source/custody hashes, pinned FY2025/2026 revisions, CSV locator and row
hash round trips, the real FY2016 gap, unknown subunit, rejection of a modified
copy of real source bytes and a wrong-agency manifest, and deterministic replay.
The default suite skips these tests if real-data mounts are absent; such a run
does not count as real-data acceptance. These checks establish source evidence,
not end-to-end graph retrieval or generated-answer quality.

No live graph activation, upstream publication, corpus copy into ExAIS, source
deletion, or probe cleanup was performed. WAVE-132 remains open until the revised
structured/document projection and real law-to-money answer path are implemented
and verified. Rollback of this increment is removal of the audit script/tests
and restoration of the documentation; no database rollback is involved.
