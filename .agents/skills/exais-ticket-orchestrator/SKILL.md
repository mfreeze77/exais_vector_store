---
name: exais-ticket-orchestrator
description: Use when Codex should run an ExAIS Vector Store ticket train, read tracker or WAVE markdown, choose specialist skills, batch safely, and enforce quality-control gates before continuing.
---

# ExAIS Ticket Orchestrator Skill

Orchestrate ticket trains in the ExAIS Vector Store repository. Read trackers
and tickets, route work to the right specialist skill, and require quality
control before any ticket is considered complete.

## Read First

If a tracker or wave is provided, read it in full. If only a ticket is provided,
read that ticket and every dependency or code anchor it names.

For existing wave tickets, start with the named `tickets/WAVE-*` file and the
project validation notes in `README.md`.

## Routing

- Use `$exais-ticket-implementation` for general one-ticket implementation.
- Use `$exais-ui-refactor-extraction` for React admin UI extraction.
- Use `$exais-registry-contract` for typed registries, descriptors, route tables, provider/model metadata, and small shared contracts.
- Use `$exais-test-proof` for baseline tests, characterization, verification, and proof tickets.
- Use `$exais-quality-control` after every implementation before moving to the next ticket.

If the runtime cannot spawn a subagent or invoke another skill, output the exact
specialist prompt to run next and stop.

## Dependency and Batching Rules

- Default to one ticket per specialist run.
- Do not run a ticket before its dependencies are complete.
- Do not batch tickets that touch the same high-risk file.
- Do not batch implementation and quality-control work.
- Treat RLS, API key, tenant isolation, migrations, indexing, worker atomicity, provider routing, and deployment changes as serial unless the tracker proves separation.

## Quality Gate

After implementation, invoke `$exais-quality-control` with:

- tracker or wave path,
- ticket path,
- changed files,
- verification commands and results,
- proof notes.

Only continue on PASS or PASS WITH NOTES.

## Stop Rules

Stop when:

- quality control returns FAIL or BLOCKED,
- a ticket needs product or operator judgment,
- verification cannot be run for a proof-required ticket,
- implementation would exceed the assigned ticket scope.

## Reference Briefs

Long-form reference instructions are in:

- `tickets/codex-agents/MAIN_ORCHESTRATOR_AGENT.md`
- `tickets/codex-agents/README.md`
