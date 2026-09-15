# Topeka collection activation: prepared, not executed

Prepared 2026-09-15 for [WAVE-118](../tickets/WAVE-118-topeka-municipal-code-source-seeding.md)
assignments 3 and 4, under the manager handoff's instruction to "prepare a
concrete tested operation and rollback first" where authorization is required.

**No container was started, no vector store was created or mutated, no embedding
was purchased, and ExAIS routing is unchanged.** Every command below is an
existing entrypoint in this repository, not a proposed one.

One step *has* been executed, because it turned out to need nothing that is
gated: step 2's ingest dry-runs run entirely offline and write nothing. Their
receipts are recorded there. Every other step is prepared and unrun.

## Why it is not executed

| Blocker | State on this host, 2026-09-15 |
| --- | --- |
| Owner authorization for activation and spend | Not given. The handoff gates runtime activation and spend on existing owner policy. |
| A running `ks-state-civics` cell | None. `docker ps -a` shows no `ks-state-civics` container; other cells (ks-fiscal, grant-intelligence) are unrelated and must not be reused. |
| Embedding credentials | `.release/cells/ks-state-civics/.env.cell` exists and declares the provider keys. Ingesting the full corpus spends against them. |

`DECODO_API_TOKEN` is declared in `.env.example` but is **not populated** in the
cell env. It is needed only to re-crawl `topeka.municipal.codes`, which answers
403 to plain HTTP. The retained TMC corpus is complete and hash-verified
(2,702 of 2,702 captures), so no re-crawl is required for this work; report the
missing token rather than treating the code collection as unavailable.

## What is already prepared and verified offline

| Artifact | Path | Verified |
| --- | --- | --- |
| Store-split plan | `instances/.../releases/proofs/topeka-store-split-plan-20260915.json` | PASS — 3,066 records assigned, 0 unassigned |
| Per-record assignments | `instances/.../releases/proofs/topeka-store-split-assignments-20260915.jsonl` | one row per retained record |
| Discovery manifests | `instances/.../discovery/` | every declared group matches the publisher's own count |
| Acquisition worklist | `instances/.../discovery/worklist.jsonl` | every record in exactly one bucket |
| Document release contract | `contracts/jurisdiction-*.schema.json` | starter bundle validates, 0 errors |

The split reconciles against two independently derived numbers: `store.yaml`
records 3,066 / 2,702 / 364 from the actual 2026-08-28 ingestion run, and the
plan derived from the retained manifests produces 3,066 = 2,702 + 323 + 41. They
agree, which is why the plan is worth executing rather than re-deriving.

## Ordered operation

Each step's gate must pass before the next. A failing gate stops the run; it
does not downgrade to a warning.

### 1. Bring the cell up

```bash
python scripts/release/cell-up.py --cell ks-state-civics
python scripts/release/cell-smoke.py --cell ks-state-civics
```

Gate: smoke passes and the API reports healthy. Rollback:
`python scripts/release/cell-down.py --cell ks-state-civics`.

### 2. Count-only dry runs — no spend

```bash
python scripts/release/topeka-code-ingest.py --cell ks-state-civics --dry-run
python scripts/release/topeka-ordinance-pdf-ingest.py --cell ks-state-civics \
  --manifest instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-ordinances/seed/manifests/ordinances.jsonl \
  --dry-run
```

Gate: the printed payload counts equal the split plan's per-destination counts.

**This step has been run, 2026-09-15.** Both dry-runs execute offline (they skip
`ensure_vector_store` and every API call), and their receipts are committed:

| Receipt | `payload_count` | `submitted_count` |
| --- | --- | --- |
| `releases/proofs/topeka-code-ingest-dryrun-20260915.txt` | 2,702 | 0 |
| `releases/proofs/topeka-ordinance-ingest-dryrun-20260915.txt` | 364 | 0 |

Both agree with the split plan (2,702 code; 323 + 41 = 364 ordinance PDFs) and
both wrote nothing. `vector_store_id` reads `vs_topeka_municipal_code_pending`,
the placeholder the scripts use when no store is resolved — confirming no store
was contacted or created.

### 3. Create destination stores through the API

Three new stores, one per registered collection, created through the supported
ExAIS API. **No direct Postgres, Qdrant, MinIO or OpenSearch write.** Record the
returned IDs into each collection's `vector_store_id`, which is `null` today.

Gate: three store IDs exist and are distinct from `vs_d4185d1004604f08a55299fa`.

The three new WAVE-117 source packages belong to **this** step, not earlier.
`instance_source_packages.py` requires a non-empty `vectorStore.id`, so writing
`sources/topeka-resolutions/source.yaml` and its siblings before their stores
exist would either commit a placeholder ID or break
`validate-instance-source-packages.py` (currently PASS, 5 packages, 0 issues).
The collection registry, routing and per-collection acquisition roots are
already in place, so writing them is mechanical once the IDs are real.

### 4. Ingest each destination from its manifest slice

Gate, per store: the destination document count equals the plan's count, and
`ks:city:topeka:ordinances` contains the unnumbered Standard Traffic Ordinance
(`ks:city:topeka:ordinances:ordinance:sto`). The STO disappearing is a failure,
not a rounding difference.

### 5. Prove retrieval before switching anything

Gate: real semantic queries return source-specific citations from the correct
store; a charter-ordinance query does not return ordinary-ordinance documents or
vice versa; graph edges resolve to endpoints with evidence. An empty lens is
reported as empty, never as graph-backed retrieval.

### 6. Switch routing last

Only after every destination passes steps 4 and 5. Update
`instances/ks-state-civics/vector-stores/topeka-municipal-code/store.yaml`.

## Rollback

`vs_d4185d1004604f08a55299fa` is **not mutated at any point** and stays
queryable throughout, which is what makes rollback cheap:

1. Restore `store.yaml` `vectorStore.id` to `vs_d4185d1004604f08a55299fa`.
2. Delete the destination stores through the API.
3. No retained artifact is deleted at any stage. Raw corpora, manifests and the
   release bundle are untouched by the split.

`python scripts/release/cell-down.py --cell ks-state-civics` returns the host to
its current state.

## Assignment 4: update entrypoint

`scripts/release/instance-source-update.py` already requires exactly one of
`--dry-run` or `--execute`. The refresh loop for these collections is:

```bash
python scripts/release/topeka-collection-discover.py --listing all \
  --output-dir instances/ks-state-civics/vector-stores/topeka-municipal-code/discovery
python scripts/release/topeka-collection-acquire.py \
  --worklist instances/.../discovery/worklist.jsonl \
  --output-dir instances/.../acquisition --delay 0.35
python scripts/release/topeka-source-release-export.py --select ... \
  --previous-manifest <prior release-manifest.json> --output-dir <next bundle>
python scripts/release/jurisdiction-release-validate.py --bundle <next bundle>
```

Discovery and acquisition are already runnable and proven on live data.
Scheduling is **not** configured: do not report this as scheduled on the
strength of these commands existing. A scheduler entry plus an execution
receipt is what would make that claim true.

Re-running acquisition asks the publisher again by default, so changed bytes are
detected; `--trust-checkpoint` skips that re-check and is opt-in precisely
because it trades change detection for speed.

## What execution would still not establish

- StateCivics A-side acceptance (importer, Topeka reader, FTS, agent context,
  packet handling). That is KS-539/KS-540 work in the other repository.
- Complete collection coverage for the municipal code: the retained TMC corpus
  is a 2026-08-28 capture, and no fresh crawl has been run against it.
- Possession of codes the TMC adopts by reference; those are not retained.
