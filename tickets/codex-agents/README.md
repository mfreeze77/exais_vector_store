# Codex Ticket Agent Pack

Status: reusable agent instructions
Owner: ticket execution orchestration
Primary orchestrator: [MAIN_ORCHESTRATOR_AGENT.md](./MAIN_ORCHESTRATOR_AGENT.md)

## Purpose

This folder contains markdown agent briefs for running ExAIS Vector Store ticket
trains with a main Codex orchestrator and focused specialist agents.

The model is intentionally simple:

1. The main orchestrator reads a tracker, ticket, or ticket range.
2. The orchestrator builds a dependency graph and chooses the right specialist.
3. A specialist executes only the assigned scope.
4. A proof agent runs or records verification when proof is the main work.
5. A quality-control agent reviews acceptance criteria, scope, and proof before
   anything is marked complete.

If the runtime cannot spawn subagents, the orchestrator should emit the exact
specialist prompt to run next and stop.

## Agent Files

- [MAIN_ORCHESTRATOR_AGENT.md](./MAIN_ORCHESTRATOR_AGENT.md) - reads trackers and tickets, selects agents, batches safely, and enforces stop rules.
- [TICKET_IMPLEMENTATION_AGENT.md](./TICKET_IMPLEMENTATION_AGENT.md) - general single-ticket implementation agent.
- [UI_REFACTOR_EXTRACTION_AGENT.md](./UI_REFACTOR_EXTRACTION_AGENT.md) - behavior-preserving React admin UI extraction agent.
- [REGISTRY_CONTRACT_AGENT.md](./REGISTRY_CONTRACT_AGENT.md) - typed registries, descriptors, and small composition contracts.
- [TEST_PROOF_AGENT.md](./TEST_PROOF_AGENT.md) - characterization tests, verification commands, and proof notes.
- [QUALITY_CONTROL_AGENT.md](./QUALITY_CONTROL_AGENT.md) - independent review against acceptance criteria, scope, and proof.

## Discoverable Repo Skills

- `.agents/skills/exais-ticket-orchestrator/SKILL.md`
- `.agents/skills/exais-ticket-implementation/SKILL.md`
- `.agents/skills/exais-ui-refactor-extraction/SKILL.md`
- `.agents/skills/exais-registry-contract/SKILL.md`
- `.agents/skills/exais-test-proof/SKILL.md`
- `.agents/skills/exais-quality-control/SKILL.md`

Invoke explicitly with skill names such as `$exais-ticket-orchestrator` or
`$exais-quality-control`, or let Codex pick implicitly from the skill
descriptions.

## Recommended Pilot Pattern

Use the existing `WAVE-*` tickets as the first production-hardening trains:

1. Baseline or invariant ticket.
2. Scoped API, worker, router, database, or admin UI implementation tickets.
3. Registry or contract consolidation when shared descriptors appear.
4. Proof/readiness ticket with explicit verification commands.

The important pattern is not the ticket number format. It is the sequence:
baseline, scoped changes, shared-contract cleanup, then independent proof.

## Operating Rules

- The orchestrator does not implement code directly unless the assigned ticket is documentation-only.
- One ticket per specialist run is the default.
- Tickets may be batched only when they do not touch the same files and do not depend on each other.
- Every implementation run must be followed by quality control.
- Completion requires changed-file summary, verification proof, and ticket proof notes.
- If tests cannot be run, state why and provide exact commands for the operator.
