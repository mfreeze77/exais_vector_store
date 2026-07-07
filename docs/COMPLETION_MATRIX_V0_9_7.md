# Completion Matrix — v0.9.7

| Area | v0.9.6 state | v0.9.7 state |
|---|---|---|
| Runtime RLS role | Structurally fixed | Kept; role scripts now managed-Postgres portable |
| Dev-mode guardrails | Fixed | Kept |
| Stale vector cleanup | Fixed | Kept |
| Live integration proof | Added but exposed JSONB failure | Suite expanded with real worker-ingest success path |
| JSONB writes | Broken against live psycopg3/text() paths | Fixed with serialized JSON + explicit casts |
| Managed/hardened Postgres portability | Blocked by unconditional role attributes | Fixed with conditional superuser-only hardening |
| First production micro-cell readiness | Blocked | Ready for live compose/VPS validation pass |
