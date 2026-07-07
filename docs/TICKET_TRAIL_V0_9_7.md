# Ticket Trail — v0.9.7 Live-Postgres Production Gate

## WAVE-005

| Ticket | Owner | Status | Acceptance |
|---|---|---:|---|
| W5-001 JSONB parameter sweep | Data-plane agent | Done | No raw dict/list is bound to a JSONB column through untyped `text()` SQL; JSONB writes use `jsonb_param()` + `CAST(:param AS jsonb)`. |
| W5-002 Portable role scripts | Infra/security agent | Done | Role bootstrap/grant scripts do not require true superuser privileges except for conditional compose hardening. |
| W5-003 GUC-aware fixtures | Test/security agent | Done | Integration fixtures set RLS GUCs before tenant-scoped owner writes. |
| W5-004 Live ingest proof | Integration agent | Done | Integration suite includes a successful worker ingest against live Postgres and a strict Qdrant-outage failure proof. |

## Release note

v0.9.7 is the patch that turns Wave-004 from structurally implemented into
live-Postgres-operable for the compose topology.
