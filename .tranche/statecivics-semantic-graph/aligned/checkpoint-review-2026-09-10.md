# Git preservation review — 2026-09-10

Independent reviewer: `checkpoint_qc`, applying `exais-quality-control`.
Decision: **PASS WITH NOTES**, limited to preserving the existing work in Git.
This is not WAVE-132 acceptance or authorization to activate the graph.

## Evidence reviewed

- Git status/diff, runtime integration, fiscal source/profile configuration,
  WAVE-132 through WAVE-136, tracker and alignment/operator documents.
- Historical runtime proof: 1,127 passed, 10 skipped; separate real-corpus
  audit: eight tests passed. The runtime suite was not rerun for this checkpoint.
- Planning gates, independent critic reruns and materialization review.
- Independent static checks: all 13 Python files and 26 JSON artifacts parsed;
  69 candidate files totaled approximately 1.05 MB, none exceeding 1 MiB.
- Upstream planning worktree verified clean at `3650b8c5`.

## Findings

No preservation blocker. WAVE-132 remains explicitly reopened; WAVE-133 through
WAVE-136 are proposed. The source and profile both keep graph service disabled.
Plans preserve StateCivics canonical ownership, the existing exporter extension,
KS-600 provision identity ownership and typed derivation lineage. Structured
evidence, lifecycle enforcement and real-answer generalization have explicit
follow-up owners.

Historical QC retains its original completion wording, superseded by current
ticket/proof/operator notices. WAVE-132 still requires canonical provision/export
prerequisites, structured evidence support, lifecycle and typed retrieval, and
reviewed real-source acceptance. This checkpoint establishes none of those.

## Commit hygiene

The instance research commit tracks authored write-ups and the source index;
its narrow ignore rule excludes downloaded upstream projects. No repository
revision pins are introduced. Existing source downloads remain on disk.

The staged diff check found trailing whitespace in the retained pytest
transcript. It was normalized without changing output tokens, and the historical
proof now discloses that formatting change. No runtime code changed in this
preservation pass; the fiscal README was clarified to name the agreed exporter
and outstanding correction tickets.
