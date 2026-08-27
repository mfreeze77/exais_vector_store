# WAVE-110 Customer Private VPS Operator Console

## Goal

Turn the current scaffolded admin UI into a serious operator console for the
commercial deployment model: one isolated Hetzner VPS and Docker Compose cell
per onboarded customer, exposing only customer-scoped OpenAI-compatible API
endpoints to that customer's agents.

## Background

The product goal is not a shared public vector database. ExAIS is intended to
recreate the useful OpenAI vector-store workflow in a self-hosted form that can
be deployed per customer. Each customer should receive a private stack with its
own Docker volumes, secrets, API keys, data stores, backups, and upgrade window.

The backend already has the stronger product surface: OpenAI-compatible
`/v1/vector_stores`, `/v1/files`, `/v1/responses`, scoped API keys, tenant and
business-instance isolation, persisted ingestion, retrieval, audit, and fleet
version primitives. The UI currently exposes these pieces as a thin technical
scaffold. This ticket promotes the UI into the daily operator surface for
standing up, managing, testing, and handing off a private customer instance.

## Scope

- Redesign `apps/admin_ui` around an operator workflow, not raw API testing.
- Add a customer-instance overview with customer name, environment, API base
  URL, business instance ID, current release digest, health, and backup status.
- Add a guided onboarding workflow for a private customer cell:
  customer profile, endpoint hostname, initial vector store, ingestion mode,
  agent read-only key, admin key handoff state, and deployment notes.
- Add vector-store management views for create/list/detail, file counts,
  expiration, metadata, attached files, ingestion status, and delete/retire
  actions.
- Add a document ingestion workspace that supports upload/paste, mode preview,
  async job status, errors, retry visibility, and completion counts.
- Add an agent handoff panel that shows OpenAI-compatible endpoint examples for
  `POST /v1/responses` with `file_search` and direct
  `POST /v1/vector_stores/{id}/search`, with credentials redacted.
- Add an API-key management view for creating/revoking scoped keys, clearly
  separating agent `retrieval:read` keys from admin/ingestion keys.
- Add a retrieval test bench that displays cited results as readable evidence
  cards before raw JSON, while keeping a collapsible JSON inspector.
- Add deployment/fleet status views that surface compose service health,
  release image digests, version drift, and last known deployment record.
- Add backup/restore readiness visibility: last backup, artifact manifest
  presence, restore-preflight status, and warnings when proof is missing.
- Replace the current single-page card dump with a polished responsive app
  shell: sidebar or tabs, dense operational tables, clear status badges,
  stable forms, empty states, error states, loading states, and mobile-safe
  layout.
- Keep the UI private/operator-focused. It should be useful to Expert AI
  Services during onboarding and support; customer agents should consume the API
  directly.

## Out Of Scope

- Implementing GraphRAG.
- Building a public SaaS tenant portal.
- Sharing one database/vector backend across multiple unrelated customers.
- Exposing Postgres, Redis, Qdrant, MinIO, model-gateway, or worker ports.
- Replacing the OpenAI-compatible route contracts.
- Changing embedding, chunking, ranking, or citation behavior except where the
  UI needs to display existing API results.
- Automating Hetzner account creation, DNS provider changes, or external
  payment/customer billing.

## Deliverables

- Redesigned `apps/admin_ui/src/main.tsx` or extracted route/component structure
  for the operator console.
- Updated `apps/admin_ui/src/styles.css` with a production-grade visual system
  suitable for dense operations work.
- Any small typed client helpers needed for admin session, vector stores, files,
  responses/search, API keys, fleet status, and backup status.
- Documentation note showing the intended per-customer VPS handoff flow and the
  API endpoints an agent should call.
- Focused admin UI build proof and at least one browser/screenshot verification
  against a running local cell.

## Acceptance Criteria

- [x] The first screen reads as an operator console for a customer-private ExAIS
  instance, not a demo form or landing page.
- [x] A new operator can identify the selected customer instance, API hostname,
  release/version status, service health, vector-store count, file count, and
  backup readiness without opening raw JSON.
- [x] The UI supports creating or selecting a vector store, adding files,
  previewing ingestion mode, triggering ingest, and seeing job/file status.
- [x] The UI supports creating a read-only agent API key with retrieval/file
  search scopes and displays the raw key exactly once with clear handoff state.
- [x] The UI provides copyable redacted examples for customer agents using
  OpenAI-compatible `/v1/responses` file search and direct vector-store search.
- [x] Retrieval results render readable citation/evidence cards with source
  filename, score/rank where available, citation marker, and excerpt.
- [x] Raw API payloads remain available in collapsible inspectors but are not
  the primary UI.
- [x] Admin-only or destructive actions are visually distinct and require an
  intentional confirmation.
- [x] The app is responsive at narrow desktop/tablet/mobile widths with no
  horizontal overflow, overlapping text, or unstable tool/form sizing.
- [x] Admin auth uses bearer credentials only in production mode; dev headers do
  not appear as a customer-facing workflow.
- [x] Existing OpenAI-compatible and native API behavior remains unchanged.

## Dependencies

- Existing OpenAI-compatible vector-store, file, file-batch, search, and
  Responses routes.
- Existing admin API-key routes and project/admin API-key aliases.
- Existing fleet/version dashboard APIs.
- Existing backup/restore artifact and restore-preflight scripts or APIs.
- A running local Docker cell for final visual and API workflow proof.

## Verification

```powershell
npm --prefix apps/admin_ui run build
```

```powershell
docker-compose --env-file .release\cells\local\.env.cell --env-file .release\cells\local\.env.images -f infra\docker\compose.cell.yml -p exais-vector-store-local ps
```

Browser proof against the running local cell:

- Open `http://localhost:13080/`.
- Verify the dashboard loads with no console errors.
- Verify the customer-instance overview, vector-store workflow, ingestion
  workflow, API-key handoff, retrieval test bench, fleet status, and backup
  readiness surfaces are visible.
- Verify the UI does not expose raw secrets in screenshots, logs, or raw JSON
  inspectors.
- Capture desktop and narrow mobile screenshots and inspect for overflow,
  overlap, unreadable controls, or clipped text.

Focused API proof, using a redacted bearer credential:

- `GET /api/v1/admin/session`
- `GET /v1/vector_stores`
- `POST /v1/vector_stores`
- `POST /v1/files`
- `POST /v1/vector_stores/{vector_store_id}/files`
- `POST /v1/vector_stores/{vector_store_id}/search`
- `POST /v1/responses` with `file_search`
- `GET /api/v1/admin/fleet/versions`

## Implementation Proof

Completed on 2026-08-07.

Changed source:

- `apps/admin_ui/src/main.tsx`
- `apps/admin_ui/src/styles.css`
- `apps/api/svs_api/main.py`
- `tests/test_fleet_version_contract.py`
- `docs/FRONTEND_ADMIN_UI.md`

Verification:

- Clean admin UI container build passed with `node:22-bookworm`,
  `npm install --no-package-lock`, and `npm run build`.
- Host admin UI build is blocked by missing local `apps/admin_ui/node_modules`;
  `npm --prefix apps/admin_ui ls --depth=0` reports unmet React/Vite/TypeScript
  dependencies.
- Focused backend regression passed:
  `python -m pytest -q -rs tests/test_fleet_version_contract.py`
  inside the rebuilt API image, result `5 passed`.
- Rebuilt and published local app images; local cell recreated with preserved
  volumes. Running API/UI images:
  `api@sha256:dbd2df1eeefc6b0cfc3d1409324daa73e3dc79f5ed45f9e09ff8bea3d19f49d2`,
  `admin-ui@sha256:c9a002b6e1356295b2c403255cd6b71b165cbb6820d0d1ed285d17bb18b5c9be`.
- Docker Compose local cell reported all services healthy after recreate.
- Focused API proof passed from inside `exais-vector-store-local_default`:
  `/readyz`, temporary scoped API key creation, `/api/v1/admin/session`,
  `/v1/vector_stores`, `/v1/files`,
  `/v1/vector_stores/{vector_store_id}/files`,
  `/v1/vector_stores/{vector_store_id}/search`, `/v1/responses` with
  `file_search`, and `/api/v1/admin/fleet/versions`.
- API proof cleanup succeeded: temporary vector store deleted, temporary file
  deleted, temporary API key revoked.
- Browser proof against `http://localhost:13080/` passed on the deployed admin
  container: title `exai_vector_store Admin`, H1
  `Customer Private VPS Operator Console`, all eight operator tabs rendered
  expected headings, zero console errors, no desktop horizontal overflow.
- Mobile browser proof at 390px width passed with eight nav controls visible,
  H1 present, no horizontal overflow, and screenshot inspected for obvious
  overlap.

## Notes

- This ticket should optimize for the one-VPS-per-customer sales story:
  "private vector-store instance, private data plane, private keys, private
  backup boundary."
- Prefer making existing backend state legible before adding new backend APIs.
- If a missing backend endpoint blocks a required UI panel, add a small follow-up
  ticket rather than hiding the gap behind placeholder UI.
- The current UI anchors are `apps/admin_ui/src/main.tsx`,
  `apps/admin_ui/src/auth.ts`, `apps/admin_ui/src/fleet.ts`, and
  `apps/admin_ui/src/styles.css`.
