# Removed worktree paths referenced by tranche artifacts

Filed 2026-09-12 (WAVE-133).

Two absolute paths appear throughout `.tranche/` and a few planning documents.
Both were git worktrees that were removed on 2026-09-11. Nothing at runtime
reads them — `git worktree list` in this repository prints exactly one line, and
must keep doing so.

| Path in the artifacts | Status | Live equivalent today |
|---|---|---|
| `/Users/mfrieson/Developer/statecivics-fiscal-graph-plan` | removed 2026-09-11 | `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai` (StateCivics, repo A) |
| `/Users/mfrieson/Developer/exais-vector-store-law-money` | removed 2026-09-11 | `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/exais_vector_store` (this repository, repo B) |

Occurrence counts at filing: 275 and 96 respectively, across 11 and 22 files.

## Why they are not rewritten

Most occurrences sit inside recorded proof artifacts — `docker run` command
blocks and their `-v ...:ro` mounts — which state what actually ran at the time.
Rewriting them would make the record claim a run that never happened. They are
therefore **retired in place**: read them as historical, and translate through
the table above.

The exceptions are the forward-looking pointers, which tell a future implementer
where to look and so must be correct now. Those are repointed:

- `docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md` — upstream ticket directory.

Still carrying the dead paths as *planning* input, not history, and flagged for
the owner rather than rewritten unilaterally:

- `.tranche/statecivics-semantic-graph/aligned/build-contract.json` (`owner_file`
  and `file` keys) and `stack.index.json`. WAVE-133 and WAVE-134 both instruct
  implementers to use these as the shared-owner map, so their paths are
  load-bearing for planning. They are also machine-readable, so a mechanical
  rewrite is cheap — but it changes a recorded artifact, which is an owner call.
  Both tickets already state: *"Runtime must not depend on worktree paths or
  these planning files."*
