# WAVE-138: Activate the approved statute canary in the local Kansas cell

Status: complete for the bounded local canary; independent QC PASS WITH NOTES.
Owner: ExAIS. Dependency: WAVE-137 offline implementation
and independent QC complete. Parent: WAVE-132.

## Authorization and outcome

The owner selected the existing local Kansas cell; OVH readiness is unknown.
Use physical cell `ks-fiscal-local`, canonical scope `ks-state-civics`, for the
approved six-document StateCivics export. Prove live Voyage-4 indexing, exact
retrieved evidence and replay before expanding the source. KS tickets remain
owned by the StateCivics manager.

## Prior art and anchors

Read WAVE-137 and its implementation/QC proof; the Kansas Statutes README,
registrar handoff, source.yaml and source.lock.json; the real-export input audit
and dry-run proof under `.tranche/statecivics-semantic-graph/aligned/`.
Reuse `scripts/release/kansas-fiscal-document-ingest.py`, normal vector-store
creation/preview/ingest/search APIs, and `infra/docker/compose.cell.yml`.
Read `docs/DOCKER_LOCAL_CELL_RELEASE.md`, API/worker Dockerfiles and the existing
cell's compose labels/config before deployment. No migration differs between
the running bb7e575 code and reviewed f0114e0 code.

## Bounded scope

- Inspect the existing cell, record baseline fiscal inventory, health, idle
  ingestion queue, original application images and a concrete rollback path.
- Build the reviewed application commit and upgrade API/worker only, preserving
  the existing cell environment, Marker timeout override, volumes and unrelated
  services. No database reset, schema change, global prune or secrets in proof.
  Record exact commit/image IDs and separate local activation from production
  release readiness. Prefer an immutable tracked-code build context.
- Create/reuse a Kansas Statutes vector store in tenant `ten_ks_state_civics`,
  business `biz_ks_state_civics`, knowledge base `kb_ks_civics` through the API.
- Apply only the approved 10,954-byte six-record export with SHA-256
  `c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7`,
  custody namespace `kansas_statutes`, and pinned harvest SHA-256
  `17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2`.
  Use the existing runner's mandatory preview and `voyage_4_docs_1024` profile.
- Expected indexed sections: 1-204 (2 chunks), 2-303 (2), 73-201 (7),
  79-3606 (51). Exclude empty-body 60-3401 and inline-History-only 41-214;
  preserve all upstream custody bytes. No full-corpus apply or synthetic data.
- Replay the same export and prove unchanged documents, versions and chunks.
  Run semantic recall on real indexed text; inspect profile/provider/index
  evidence and verify returned character slices against retained bytes.
- Update source pins and local proof with actual outcomes, retaining graph
  disabled and `productionReady: false`. Record physical local cell separately
  from logical instance. Do not claim canonical GraphRAG or OVH activation.

## Ownership and acceptance

One implementation worker owns application deployment, `.release/` operational
artifacts and `wave-138-local-canary-proof.md` / sanitized machine-readable
proof under `.tranche/statecivics-semantic-graph/aligned/`. Root owns this ticket,
tracker and source-package docs/pins after execution. No runtime code changes
without surfacing the concrete failure and agreeing the bounded correction.
Independent QC runs after implementation and declaration updates, serially.

Acceptance requires: actual healthy upgraded local API/worker; existing fiscal
inventory preserved; four live documents/62 chunks on Voyage-4 1024-d; two
document exclusions; exact-source retrieval evidence; unchanged replay;
recorded rollback commands and input/runtime pins; independent QC PASS or
PASS WITH NOTES. Report failures and incomplete boundaries precisely. Do not
replace these proofs with passing offline tests or provider doubles.

## Execution result

The local API/worker now run immutable tracked `f0114e0` builds. Four approved
documents produced 62 live Voyage-4/1024 chunks; two files were excluded for the
documented body-content reasons. Four dense paraphrases returned their expected
statute first. All 62 stored chunks and 20 native returned hits matched retained
source slices. Replay produced six noops and an unchanged index/ingestion-usage
snapshot. Fiscal inventory, schema and infrastructure identities were preserved.

See [implementation proof](../.tranche/statecivics-semantic-graph/aligned/wave-138-local-canary-proof.md)
and [input audit](../.tranche/statecivics-semantic-graph/aligned/statute-real-export-audit.md).
The source package validator exited 0 with one package and zero issues in the
new API image (`validate-instance-source-packages.py --instance ks-state-civics
--vector-store kansas-statutes --production --json`). That flag checks declaration
rules; `productionReady` remains false.

[Independent QC](../.tranche/statecivics-semantic-graph/aligned/wave-138-local-canary-qc.md)
returned PASS WITH NOTES after fresh live DB/Qdrant, custody/coordinate,
configuration, rollback and proof-hash checks. No blocking fixes remain.
Retain the ignored operational state and application overlays; include the
overlay in future local compose actions. WAVE-132 remains open.
