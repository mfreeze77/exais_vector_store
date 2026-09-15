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

### 2. Per-destination dry runs — no spend, no network

Each destination is proved on **its own** manifest slice. A combined batch shows
that documents exist; it shows nothing about where each one lands.

```bash
python scripts/release/topeka-destination-manifests.py \
  --output-dir instances/ks-state-civics/vector-stores/topeka-municipal-code/destinations

python scripts/release/topeka-code-ingest.py --cell ks-state-civics \
  --source-output .tmp/topeka-decodo-window-batches-20260827220454/combined-full-corpus-20260828-v2 --dry-run
python scripts/release/topeka-ordinance-pdf-ingest.py --cell ks-state-civics \
  --manifest instances/.../destinations/ordinances.ingest-slice.jsonl \
  --extracted-dir instances/.../sources/topeka-ordinances/seed/extracted --dry-run
python scripts/release/topeka-ordinance-pdf-ingest.py --cell ks-state-civics \
  --manifest instances/.../destinations/charter-ordinances.ingest-slice.jsonl \
  --extracted-dir instances/.../sources/topeka-ordinances/seed/extracted --dry-run
```

**These have been run, 2026-09-15, under `docker run --network none`.** Receipt:
`releases/proofs/topeka-destination-dryruns-20260915.txt`.

| Destination | `payload_count` | `skipped_count` | `submitted_count` |
| --- | --- | --- | --- |
| `ks:city:topeka:municipal-code` | 2,702 | — | 0 |
| `ks:city:topeka:ordinances` | 323 | 0 | 0 |
| `ks:city:topeka:charter-ordinances` | 41 | 0 | 0 |
| `ks:city:topeka:resolutions` | no ingest path yet — 542 acquired and routed, none extracted | — | — |

Routing is proved separately and offline: `topeka-destination-manifests.py`
re-derives every record's destination from the registry **and** sweeps all four
registered collections to confirm none of them also claims it. 3,635 records,
0 issues, networking disabled.

Gate: each destination's count equals its manifest, and `submitted_count` is 0.

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

## Assignment 4: the wired refresh runner

`scripts/release/topeka-collection-refresh.py` is a single entrypoint that runs
the loop in order — discover, acquire, destination manifests with the routing
proof, export, validate — and, like `instance-source-update.py`, requires
exactly one of `--dry-run` or `--execute`.

```bash
python scripts/release/topeka-collection-refresh.py --dry-run
python scripts/release/topeka-collection-refresh.py --execute --offline
python scripts/release/topeka-collection-refresh.py --execute --trust-checkpoint
```

Every command it emits is fully formed; there are no placeholders to fill in.
`--offline` skips the two stages that contact the publisher and runs the rest,
which is how the routing and validation proofs run with external calls disabled.

**Executed 2026-09-15 under `--network none`** with `--execute --offline`: the
destination, export and validate stages all passed, and the export correctly
reported all three documents `unchanged` against the prior release manifest.
Receipt: `releases/proofs/refresh-run.json`.

Scheduling is **not** configured: do not report this as scheduled on the
strength of the runner existing. A scheduler entry plus an execution receipt is
what would make that claim true.

Re-running acquisition asks the publisher again by default, so changed bytes are
detected; `--trust-checkpoint` skips that re-check and is opt-in precisely
because it trades change detection for speed.

## Extraction, by actual format

Not every acquired document needs the paid path.

| Format | Documents held | Path | Cost |
| --- | --- | --- | --- |
| `.docx` | 23 | `topeka-docx-extract.py`, local, stdlib | **none** |
| `.pdf` | 913 | bounded remote Marker | billable |

**The DOCX path is implemented and already run**, offline, at zero cost: a DOCX
is a ZIP holding `word/document.xml`. 23 documents, 84,739 characters, 1,233
blocks including 10 structured tables, 0 failures. It declares page coordinates
unavailable (a DOCX has no fixed pagination) and reports tracked changes rather
than flattening them — the defect already recorded against the Marker output.

Of the 913 held PDFs, 364 already have retained Marker extractions reused by
hash. That leaves **549 documents, ~2,647 estimated pages** as the only billable
work. `topeka-extraction-plan.py` sizes it and refuses to invent a unit price:

```bash
python scripts/release/topeka-extraction-plan.py --unit-price-per-page <operator rate>
```

| Stage | Documents | Pages | At an illustrative $0.004/page |
| --- | --- | --- | --- |
| Pilot | 10, starting with Resolution 9749 | 11 | $0.04 |
| Bulk | 539 | 2,636 | $10.54 |
| Hard cap | 549 | 2,647 | $10.59 |

The pilot starts with Resolution 9749 because it is the owner's named example
and the one document the starter release is waiting on, then takes the smallest
remaining documents so a quality problem surfaces cheaply. Its extracted text
must validate through the document release contract before any further spend,
and stage 2 needs its own authorization even after the pilot passes.

The page figure is an **estimate, not a measurement**: 99 documents by
authoritative page-tree `/Count`, 448 by page-object scan (which undercounts
compressed files), 2 by byte-size heuristic. Reconcile against the pilot's
actual billed pages before authorizing stage 2. The caps are stated but **not
yet enforced in code**.

## What execution would still not establish

- StateCivics A-side acceptance (importer, Topeka reader, FTS, agent context,
  packet handling). That is KS-539/KS-540 work in the other repository.
- Complete collection coverage for the municipal code: the retained TMC corpus
  is a 2026-08-28 capture, and no fresh crawl has been run against it.
- Possession of codes the TMC adopts by reference; those are not retained.
