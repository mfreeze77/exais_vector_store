# Planning edit record

This turn changes tickets, documentation and planning artifacts only. New
implementation work has not been executed or deployed. Existing uncommitted
WAVE-132 runtime work remains in the ExAIS worktree.

Upstream authoring worktree:
`/Users/mfrieson/Developer/statecivics-fiscal-graph-plan` (planning branch,
fast-forwarded to current main before edits). The operational checkout and
running K.S.A. harvest are untouched.

Root has updated the existing KS-600 scope/acceptance, owner pointers in
KS-595/597/601/605/613, architecture/fiscal-engine references, and added
`docs/specs/civic-impact-intelligence/LAW_AND_MONEY_RETRIEVAL_HANDOFF.md`.
The scope of KS-613 and existing ticket statuses are preserved.

ExAIS edits update WAVE-130's historical status, WAVE-132's corrected acceptance,
CELL_GRAPH_PROFILES, fiscal operator/real-data docs, fiscal store README, and
the earlier tranche's entry points. The controlling consumer doc is
`docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md`.

The user's current Dropbox ExAIS workspace also has the updated instance
README and `instances/ks-state-civics/research/law-and-money-backbone.md`, with
links to the active worktree handoff. Downloaded upstream code is unchanged.

Verified corrections to manager shorthand are documented in manager-alignment:
derivation outputs use optional/nullable `hash_sha256`, not `revision_or_hash`;
publication-record.subject_type excludes fiscal entities today. The agreed
reuse approach is unchanged; KS-600/650 own the bounded implementation work.

Preliminary static verification passed: 300 upstream tickets (KS-350 through
KS-649) parse as YAML with unique contiguous IDs; 21 authored documents have
36 resolving local Markdown links. These counts precede new ticket materialization.
Re-run final metadata/index/link checks after all six new tickets are written.

All three deterministic and independent critic gates passed. Stage 2's first
review caught stale output-reference shorthand; stage 3's first review caught
the missing root discovery-index mapping. Both findings were corrected and the
reruns passed. Original review findings are retained alongside the passing runs.

Root materialized six new canonical tickets (KS-650/651 and WAVE-133–136) and
updated both indexes after those gates. A separate materialization review caught
overstated SB125 proof and shared-file descriptions that blurred ticket ownership;
both were corrected, and `materialization-review-rerun-1.json` records PASS.

The upstream index now contains 302 unique, contiguous IDs (KS-350 through
KS-651). Final document/link/requirement results are in `planning-validation.json`.
The JSON artifacts describe future implementation; do not treat their shared
function signatures or expected outputs as code already written. No runtime
tests, source ingestion, harvest mutation or deployment occurred in this turn.
