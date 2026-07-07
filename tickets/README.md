# Tickets

This folder contains the ExAIS Vector Store roadmap and implementation tickets.

Use `WAVE-*` tickets for release or production-hardening waves. Use
`TEMPLATE.md` for narrower follow-up tickets that need a standard shape.

## Current Ticket Index

- [WAVE-001 Security and Correctness Hardening](./WAVE-001-security-correctness-hardening.md)
- [WAVE-002 Ingestion Repair Expiration](./WAVE-002-ingestion-repair-expiration.md)
- [WAVE-003 Router Bakeoff Control Plane](./WAVE-003-router-bakeoff-control-plane.md)
- [WAVE-004 v0.9.6 Security Production Gate](./WAVE-004-v0.9.6-security-production-gate.md)
- [WAVE-005 v0.9.7 Live Postgres JSONB Portability](./WAVE-005-v0.9.7-live-postgres-jsonb-portability.md)
- [WAVE-005 v0.9.7 Live Postgres Portability](./WAVE-005-v0.9.7-live-postgres-portability.md)
- [WAVE-006 v0.9.8 Worker Attempt Atomicity](./WAVE-006-v0.9.8-worker-attempt-atomicity.md)
- [WAVE-007 Docker-First Local Cell Release Gate](./WAVE-007-docker-first-local-cell-release-gate.md)
- [WAVE-008 Operations Bug Hardening](./WAVE-008-operations-bug-hardening.md)

## Execution Model

The reusable Codex ticket execution model lives in
[codex-agents/README.md](./codex-agents/README.md).

Short discoverable skills live under `.agents/skills`:

- `.agents/skills/exais-ticket-orchestrator/SKILL.md`
- `.agents/skills/exais-ticket-implementation/SKILL.md`
- `.agents/skills/exais-quality-control/SKILL.md`
- `.agents/skills/exais-test-proof/SKILL.md`
- `.agents/skills/exais-ui-refactor-extraction/SKILL.md`
- `.agents/skills/exais-registry-contract/SKILL.md`

The tranche-generation skill lives at `.codex/skills/ticket-tranche`.

## Proof Expectations

Tickets should name the commands or proof needed for completion. Use the narrowest
proof that validates the ticket, then escalate only when the blast radius requires
it.

Common ExAIS proof commands:

```bash
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
  python -m compileall -f -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
  pytest -q -rs
npm --prefix apps/admin_ui run build
docker compose config
```

Use `./scripts/smoke-test.sh`, migrations, Docker services, or live integration
proof only when the ticket requires those surfaces.
