# Grant Intelligence — dedicated local cell

Provisioned 2026-09-05 from ExAIS `11eebf7`. Local API:
`http://127.0.0.1:28080`. Store: `vs_ae6d7d036f604b36ad0d81d0`.
Tenant `public`, business instance `grant-intelligence`; neither is shared with
the law/civics cell. Header-only development authentication is disabled.

Runtime configuration, Compose definition, bootstrap and scoped application keys,
and connection evidence are in the owner-only directory outside Dropbox:

`/Users/mfrieson/Library/Application Support/ExAIS/grant-intelligence/`

Do not commit this private directory or expose resolved environment values.
Grant Intelligence's ignored `.env` holds only its own scoped ExAIS caller keys,
store ID, and connection settings. Provider credentials and the admin key remain
server-side. The server reuses the existing OpenAI embedding integration; a real,
synthetic-only ingest/search test verified 1536-dimensional
`text-embedding-3-small` vectors and removed the canary from retrieval afterward.

Operational instructions and exact permission checks are recorded in the sibling
Grant Intelligence repo's `docs/operations/EXAIS_LOCAL_INSTANCE.md`. No production
release, real grant corpus, tagging graph, backup qualification, or hosted TLS
readiness is implied. Follow `docs/JURISDICTION_VECTOR_STORE_PLAYBOOK.md` and create
reviewable source packages before collected publisher data is ingested.

## Cell-owned graph profile (WAVE-126)

`graph/profile.yaml` binds the Grant-specific canonical-evidence handler to this
cell and store, checked in disabled. It reuses the generic ExAIS graph loader
and retrieval ACL/citation machinery, not the Kansas court/municipal ontology.
The existing live image has **not** been rebuilt or activated with this profile.
See `docs/CELL_GRAPH_PROFILES.md` and the WAVE-126 ticket for the exact artifact
contract, SQL/RLS tests, explicit activation steps and pending canonical exporter.
