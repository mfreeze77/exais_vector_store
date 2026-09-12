# WAVE-133 offline foundation — independent review 1

Reviewer: `wave133_qc`. Date: 2026-09-10.
Decision: **FAIL** for this increment pending the composition fix below.

Reviewed all changed code, documentation and tests against `3230b74`, the root
256-pass proof, and an independent network-disabled, read-only Docker run of
the 105 new tests: **105 passed, zero skipped, 2.19 seconds**. Independent
composition and extraction consistency probes followed; `git diff --check`
passed. Passing the existing tests did not establish component composition.

## Required fix

The CSV verifier emits `locator.physical_line_end_1based`, but the strict
`FiscalStructuredRecordLocator` model rejects that field. Passing verifier
output into `FiscalStructuredRecordEvidence` fails with `extra_forbidden`,
including for the real retained records.

Preserve the field as an optional, strictly bounded physical-line diagnostic or
provide a lossless mapping. Keep it distinct from logical record identity.
Add composition regressions for multiline CSV, all five retained Education
records and invalid diagnostic values; obtain independent re-review.

## Other findings and boundaries

Strict immutable models and nested revalidation, distinct identities, bounded
complete manifests, endpoint/replay checks, retained CSV proof and unchanged v1
behavior passed review. No publication, API, provider, database or deployment
implementation was introduced.

The extraction probe showed that the structural types do not prove an
extraction's parent-source relationship. This is explicitly deferred to the
upstream adapter and is not a blocker for this offline increment. A consistent
extraction ID/hash alone must not become proof of parent provenance later.

Full WAVE-133 remains incomplete pending KS-600/650 and reviewed records,
legal/derivation semantics, eligibility, adapter/API integration and disposable
PostgreSQL proof. Those dependencies do not require widening this increment.
