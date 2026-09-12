# Kansas Statutes source

This declares the Kansas StateCivics statute document path. The first approved
batch has been applied to the existing local Kansas cell: four documents indexed
and two content exclusions, yielding 62 live Voyage-4/1024 chunks. Four dense
paraphrase queries returned the expected statute first. All stored chunks and
20 native returned hits resolved exactly to retained text, and export replay
left the persisted index unchanged. See the
[WAVE-138 local proof](../../../../.tranche/statecivics-semantic-graph/aligned/wave-138-local-canary-proof.md).
[Independent QC](../../../../.tranche/statecivics-semantic-graph/aligned/wave-138-local-canary-qc.md)
passed with notes on the local scope and retention of operational state/overlays.
The store remains `productionReady: false`; this six-record run does not establish
full-corpus coverage, canonical graph integration or an OVH deployment.
[Source package](sources/statecivics-statute-ledger/source.yaml) and
[source lock](sources/statecivics-statute-ledger/source.lock.json) reuse the
StateCivics document retrieval-export contract. Corpus bytes remain outside Git.

The retained harvest and approved chapter exports are available for rollout. See the
[full inventory and filter corrections](../../research/statute-harvest-handoff.md).
The separate [WAVE-137 implementation](../../../../tickets/WAVE-137-kansas-statute-document-ingestion.md)
adds statute-specific exact-coordinate parsing and extends the existing API runner.

## Prepare retained documents

Run these commands inside the project's container runtime with `svs_common`
available. `/statutes` and `/custody` are read-only mounts; `/proof` and `/state`
are separate writable output directories. The implementation proof records the
complete Docker invocation used against the retained corpus.

```sh
python scripts/release/kansas-statute-preflight.py \
  --manifest /statutes/manifests/statute_scrape_20260911_030653.json \
  --expected-manifest-sha256 17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2 \
  --corpus-root /statutes \
  --proof /proof/statute-preflight.json
```

Preparation verifies each retained Markdown hash, size and official URL, reconciles
exact duplicate harvest records and counts ordered unresolved history occurrences.
It preserves short substantive body regions. Empty regions and misplaced
History-only text are classified separately; byte length never decides eligibility.
Natural section/subsection boundaries retain exact source slices and document-local
line/character positions. Web-derived statutes have no invented PDF pages.
Character ranges select the exact original text; enclosing line ranges count LF
delimiters from one. Embedded carriage returns are preserved as source characters.
Body, History and annotation chunks have separate region labels so a retrieved
annotation is not presented as statutory text.

Preparation output is not a custody registration or retrieval-export record.
It supplies no canonical provision identity, resolved statute-to-bill edges,
publication permission or current-law determination. Historical metadata remains
available even when a source contributes no statute-body embedding.

## Plan an approved custody export

The [registrar handoff](registrar-handoff.md) identifies the shared upstream
services, six real source files and the first export/replay checks.

```sh
python scripts/release/kansas-fiscal-document-ingest.py \
  --source-family kansas-statutes \
  --cell "$STATECIVICS_RUNTIME_CELL" \
  --api "$STATECIVICS_API_BASE" \
  --vector-store-slug kansas-statutes \
  --vector-store-name "Kansas Statutes" \
  --vector-store-id "$KANSAS_STATUTES_VECTOR_STORE_ID" \
  --knowledge-base-id kb_ks_civics \
  --manifest /handoff/kansas-statutes.jsonl \
  --custody-root /custody \
  --harvest-manifest /statutes/manifests/statute_scrape_20260911_030653.json \
  --harvest-manifest-sha256 17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2 \
  --harvest-root /statutes \
  --state /state/kansas-statutes.json \
  --proof /proof/statute-ingest-plan.json
```

The logical instance remains `ks-state-civics`. The owner selected physical local
cell `ks-fiscal-local` for the first live batch; OVH is unknown. In a runner
container joined to `exais-vector-store-ks-fiscal-local_default`, use
`STATECIVICS_RUNTIME_CELL=ks-fiscal-local` and
`STATECIVICS_API_BASE=http://api:8080`. The host-facing API is
`http://127.0.0.1:28085`. Supply the existing Kansas tenant/business/user scope,
not the cell's generic development defaults. The package command also requires
`STATECIVICS_STATUTE_STATE` and `STATECIVICS_STATUTE_PROOF` pointing at writable
mounted paths. Keep state across replay; it is separate from source evidence.

The shared runner retains its fiscal default; the explicit family selects statute
validation and the dedicated source collection. Upstream records must target
`ks-state-civics/kansas-statutes` and agree with the retained harvest and custody
bytes. The raw harvest JSON must never be passed off as the approved export.

The statute profile requires existing `voyage_4_docs_1024` (Voyage-4, 1024
dimensions) through the normal provider/router. It does not change global or
fiscal defaults and must not silently fall back to another model. Before an
explicit apply, nonpersistent server preview must confirm the actual parser and
embedding profile. The normal API records usage and performs indexing; this
source adds no direct storage writes.

Removal/replay follows source identity, record digest, parser profile and bound
evidence context. A changed source/citation cannot silently reuse old chunk
provenance. A document newly excluded from the statute-body index must not leave
its older text searchable.

The reviewed first export and local consumer have now passed the bounded live
application and recall checks. The original replay state is retained at
`.release/cells/ks-fiscal-local/wave-138/statute-state.json`; current chapter state
is `/Users/mfrieson/Developer/statecivics-statute-ingestion/ks-fiscal-local-kansas-statutes.json`. A wider batch requires its own reviewed custody-backed export and
coverage proof. Migration 111's verification attestations are
independent of ordinary eligible document search; graph integration continues
under KS-600/650 and WAVE-133–136.

## Chapter rollout

The complete upstream delivery is now independently verified: 85 partial
chapter exports, 31,079 records, 28,812 indexable documents and 83,258 chunks.
See the [full input audit](../../../../.tranche/statecivics-semantic-graph/aligned/statute-chapter-export-audit.md)
and [WAVE-139 staging gate](../../../../tickets/WAVE-139-kansas-statute-chapter-handoff.md).
Chapters 007 and 011 have now added 11 documents and 37 chunks: the live store
contains **15 documents / 99 chunks**. Both replays were unchanged, every stored
chunk matched custody, and two dense queries returned the expected statute first.
See the [staging proof](../../../../.tranche/statecivics-semantic-graph/aligned/wave-139-tranche-proof.md); [independent QC](../../../../.tranche/statecivics-semantic-graph/aligned/wave-139-tranche-qc.md) passed with notes.
The unchanged first six-record manifest remains a separate historical pin.
Each chapter file describes only its own incoming records. The runner preserves
omitted state; only explicit incoming removal records or supported content
exclusions cause removal. Serialize writers to a shared state file, and retain
operator state outside disposable worktrees.

Running the actual provider batch planner over every retained chunk yielded
**28,812 planned embedding requests for 83,258 chunks**, before deducting
already indexed documents. This is one document request per substantive file
for this corpus, with multiple chunks in most requests. It excludes retries,
cap-triggered splits and query embeddings; chunk count is not request count.

Vectorization cost is not a rollout gate, per the owner. The retained
[request-planning measurement](../../../../.tranche/statecivics-semantic-graph/aligned/statute-chapter-request-estimate.json)
records the full-corpus workload; its token/cost numbers are heuristic planning
values, not billed usage. Rollout gates are source integrity, safe partial-batch
semantics, resumability and verified search results. The owner has directed the
[full local rollout](../../../../tickets/WAVE-140-kansas-statute-full-rollout.md);
its [coordinator review](../../../../.tranche/statecivics-semantic-graph/aligned/wave-140-coordinator-qc.md)
passed with notes. The first full run stopped at the existing API rate limit after 575 checkpointed
records. [WAVE-141](../../../../tickets/WAVE-141-kansas-statute-rollout-pacing.md)
added reviewed caller pacing at up to 110 upserts/minute;
the verified paused inventory contains 579 documents and 1,518 chunks;
the paced run completed 2026-09-11T22:34:29Z in `exais-kansas-statute-rollout-wave140-paced` (exit 0, 85/85 chapters, nine attempts).
The store holds **28,812 documents / 83,258 chunks / 83,258 embeddings**, every
chapter exact against `INDEX.json`; acceptance PASS (48/53, 0 blocking, 530 slices
re-verified against custody with 0 failures).
Progress is retained at `/Users/mfrieson/Developer/statecivics-statute-ingestion/wave-140/rollout-paced/progress.json`.
Full live verification is still required before reporting corpus completion.

## Evidence versus search

Use the native `/api/v1/retrieval/search` response's `ChunkRecord.metadata` for
source-coordinate evidence. The compatibility vector-store search endpoint
returns document attributes and citation-decorated content; it does not expose
the same chunk-coordinate fields, and its decorated text is not itself the
original retained slice. Preserve the returned chunk/document references when
moving between these interfaces. The local proof records which endpoint was
used for semantic ranking and which for exact-source verification.

Chunks preserve original text and coordinates. Section labels, official URLs,
source/extraction hashes and unresolved ordered History references are metadata.
A search hit is a candidate passage; canonical graph relationships and exact
verified legal support come from their upstream contracts and attestations.
This package leaves graph activation disabled. Semantic matches and unresolved
History metadata do not establish canonical fiscal or legal relationships.
