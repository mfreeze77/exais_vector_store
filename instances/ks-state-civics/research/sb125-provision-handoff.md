# SB 125 retained-provision handoff review

Read-only evidence review, 2026-09-10. Scope: the Kansas State Civics cell's
law-and-money handoff. This records retained-source findings for the upstream
KS-600/597/650 implementation; it creates no canonical IDs, SourceSpans, ledger
actions, account crosswalks or published graph records.

Follow-up: all seven books now have retained machine-readable extractions.
The [extraction readiness audit](session-law-extraction-readiness.md) verifies
their hashes/page markers, corrects the proposed subsection endpoint to include
the lapse amount, and records the remaining quality/registration work.

## Retained source and verification

Source: [2025 Session Laws of Kansas, Book 2](https://www.sos.ks.gov/publications/sessionlaws/2025/2025-Session-Laws-Book-2.pdf).
The local copy is under the StateCivics operational checkout at
`docs/existinglawexpert/pipeline/input_pdfs/2025-Session-Laws-Book-2.pdf`.
Manifest: `docs/existinglawexpert/pipeline/manifests/download_manifest_20260301_045737.json`,
with recorded retrieval date `2026-03-01`.

- SHA-256: `a1f85adfbac7da37bb9412e0e495587cd976bd3acea6dba4f1c2e2222e201009`.
- Retained bytes: `6,181,614`; file hash and size match the manifest.
- Review used `pdftotext -layout`, Python standard-library hashing, and
  `pdftoppm` rendering/visual inspection of PDF pages 351, 358, 818 and 827.
- PDF page numbers below are **one-based**. Printed page labels are separate.
  An exported locator must follow the actual SourceSpan contract's convention.

## Corrected legal locators

| Evidence | PDF page | Printed page |
|---|---:|---:|
| Chapter 117 heading, Senate Bill No. 125; amendment marker for Chapter 128 | 157 | 1205 |
| Section 96 begins: Department of Education | 351 | 1399 |
| **Section 96(j): $4,000,000 lapse** | **358** | **1406** |
| Section 96 ends and section 97 begins | 360 | 1408 |
| **Section 95(c): FY2025 $130,628,717 lapse** | **351** | **1399** |
| Chapter 128 begins | 818 | 1866 |
| Chapter 128 sections 7–8, explicit SB 125 section 204 reference | 827 | 1875 |

Two manager-handoff references need correction before span population: page 351
locates the start of section 96, not subsection (j); the parallel FY2025 lapse
is section **95(c)**, not section 96(d). Preserve the two page-number systems
rather than treating either as a provision identifier.

Section 96(j) supports a lapse of **$4,000,000 on July 1, 2025**, for the fiscal
year ending **June 30, 2026**, from the state general fund's supplemental state
aid account **652-00-1000-0840**. It cites **$601,800,000** previously appropriated
by **2024 Session Laws Chapter 111 section 3(a)**. Department of Education is
the section's agency context; field evidence for that identity should include
the heading, not assume that the subsection itself supplies the agency name.

Section 95(c) identifies account **652-00-1000-0820**, FY ending **June 30, 2025**,
and a lapse on the effective date of the act. This review did not determine that
act-wide effective date; do not copy section 96(j)'s July 1, 2025 date onto it.

This verifies what the retained lapse provision says. It does not independently
verify the cited 2024 original appropriation or establish reconciled final
authority. KS-600 must retain those inputs and any applicable intervening
actions before publishing a derived remaining-authority figure.

## Amendment scope

Chapter 117's chapter-level amendment marker does not establish which provision
changed. Review of the complete retained Chapter 128 text, PDF pages 818–828,
found its section 7 amends K.S.A. 79-2989 as amended by SB 125 section 204;
section 8 repeats the relevant repeal/re-enactment reference. Those provisions
concern taxpayer-notification cost reimbursements. No amendment to section
96(j) was shown in this chapter.

Do not supersede every Chapter 117 provision from a chapter-level marker.
This finding is limited to Chapter 128; it is not a complete subsequent-law or
veto-history review and does not replace KS-600's reconciliation work.

## Integration implications

- KS-600 defines the canonical version-specific provision reference. Kansas,
  enactment year, legal instrument/version and provision path supply its legal
  context. Displayed section numbering and source-page coordinates are distinct
  from canonical identity; renumbering across legal versions needs evidenced
  lineage. Re-extraction alone does not create a new legal provision.
- The manager reports no SB 125 bill-version row yet. Resolve required upstream
  bill/version references through canonical records; ExAIS must not fabricate
  them to satisfy the existing appropriation-action contract.
- The earlier [retained KanView audit](../../../docs/FISCAL_GRAPH_REAL_DATA.md#concrete-account-evidence)
  found candidate account `652-1000-840` with a null subunit. That does not prove
  the full legal reference `652-00-1000-0840`. Preserve the literal legal account,
  candidate accounting context and unresolved composite crosswalk separately.
  Recording the source-backed lapse does not require inventing a positive join.
- Section 95(c) adds a second real account/fiscal-year example from the same bill
  and agency. It helps fixture coverage but cannot satisfy KS-651's distinct
  bills, sessions, agencies and reviewer-controlled held-back case by itself.
- Allowed classification combinations and interpretation of observed values
  from official sources remain KS-600's work. They do not block schema design or
  evidence retention; they gate reviewed classification and reconciliation.
- The K.S.A. harvest is independent. ExAIS adapts the delivered KS-650 export;
  this research note is neither an upstream wire contract nor an export fixture.

See the [current implementation handoff](../../../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md#current-implementation-handoff).

Independent read-only review of this note and the corresponding handoff/ticket
updates returned **PASS**. Local documentation links and `git diff --check`
also passed. No runtime code changed or runtime tests were rerun for this update.
