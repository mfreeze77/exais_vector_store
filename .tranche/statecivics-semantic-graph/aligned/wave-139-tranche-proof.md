# WAVE-139 chapter ingestion proof

Implementation proof passes; independent QC is pending. Executed 2026-09-11
against the existing local Kansas cell. Chapters 007 and 011 added 11 documents
and 37 chunks. The statute store now contains 15 completed documents, 15 indexed
versions and 99 active Voyage-4/1024 embeddings. No production code or deployment
changed in this ticket.

The [independent input audit](statute-chapter-export-audit.md) covers all 85
tranches and their 31,079 records: 28,812 substantive documents, 2,264 empty bodies,
3 inline-History-only exclusions and 83,258 exact chunks. This is input validation,
not a claim that the full corpus is indexed. The complete audit, per-chapter
pins, returned chunk IDs/coordinates and hashes of every operational artifact are
recorded in [the machine-readable proof](wave-139-tranche-proof.json).

## Characterization and live boundaries

Four new tests in `tests/test_kansas_statute_tranches.py` exercise retained
exports with explicitly isolated HTTP doubles:

- Applying chapter A followed by B preserves omitted canary and A state and emits
  no omission DELETE; replay B performs no HTTP requests.
- A test-only explicit withdrawal removes only its named document. That altered
  record never entered a live export or request.
- The six original canary records differ from their full-chapter reexports only
  in exporter metadata and record digest. Canonical logical/revision/content/
  custody/export identities remain unchanged.
- A changed exporter digest plans an upsert, while the server can deduplicate
  unchanged source evidence. An acknowledged `upserted` operation is not proof
  of a newly created document/version.

The live database additionally executed `IngestionService._find_exact_duplicate`
in a read-only transaction using the actual new 1-204 reexport attributes and
its unchanged, already verified source hash/context. It returned existing
`doc_d1e8c84ff60840b782e7be7b` / `docv_ba32dfdef29942708361a210`.
This selector proof made no provider or ingestion call and did not apply
chapter 001. The isolated test separately covers advancing the operator digest.

## Actual local application

Store: `vs_daafbc5d7aa54b23b3f10392`; physical cell: `ks-fiscal-local`.
Application code remains `f0114e0`; the proof/test checkout starts at `872f7e2`.
Runner transport uses `--api http://api:8080` on the existing local Docker
network and explicit Kansas tenant/business/user scope. Each upsert passed the
existing nonpersisting server preview before normal ingestion.

| Stage | Upserts | Exclusions/noops | Resulting documents/chunks | Seconds | Actual Voyage embedding requests |
| --- | ---: | ---: | ---: | ---: | ---: |
| Chapter 007 | 5 | 1 | 9 / 84 | 13.13 | 5 |
| Chapter 011 | 6 | 2 | 15 / 99 | 13.72 | 6 |
| Replay 007 | 0 | 6 | 15 / 99 | 11.06 | 0 |
| Replay 011 | 0 | 8 | 15 / 99 | 11.04 | 0 |

The 26.85-second apply time includes repeated full-harvest preflight. Eleven
successful cloud HTTP requests embedded 37 chunks; requests are document batches,
not one request per chunk. Two subsequent semantic queries made two additional
Voyage requests. Billed tokens are not exposed by the retained application proof;
no price calculation or spending gate was introduced.

The durable state is
`/Users/mfrieson/Developer/statecivics-statute-ingestion/ks-fiscal-local-kansas-statutes.json`.
It contains 20 source records, including the original six and three newly excluded
records. It was seeded from the original WAVE-138 state without changing that
file. The sibling `.lock` file serializes the operational wrapper using
`flock(LOCK_EX | LOCK_NB)`.

The executed wrapper permits only chapters 007/011, checks the pinned INDEX and
chapter bytes, and invokes the unchanged runner with `--apply`. Each full command
is retained in the execution JSON under the operational directory. Commands run:

```bash
python3 /Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/run-chapter.py 007 apply
python3 /Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/run-chapter.py 011 apply
python3 /Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/run-chapter.py 007 replay
python3 /Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/run-chapter.py 011 replay
python3 /Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/verify-evidence.py
python3 /Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/snapshot.py final
```

Do not rerun the bounded apply wrapper as a continuation plan: it intentionally
rejects overwriting existing proof outputs. WAVE-140 owns the next rollout.

## Evidence and preservation

SQL checks confirm every document version uses
`statecivics_statute_markdown_v1` / `voyage_4_docs_1024`; all 99 chunks have indexed
dense and sparse states. Qdrant checks verify all 99 nonzero finite 1024-dimensional
vectors and their scoped payloads. All prior document, version, chunk and embedding
IDs and vector hashes survived both chapter applications. The post-replay SQL and
Qdrant snapshot is byte-identical to the post-011 snapshot. Both replays also
preserved the operator-state bytes and made zero embedding requests.

All 99 stored chunks and ten returned native-search results match exact retained
Markdown slices, text/source hashes, source revision/URL and LF line coordinates.
Coordinates are zero-based, end-exclusive Unicode code points and one-based,
inclusive LF-delimited lines; no PDF page or provision identity was invented.
History remains unresolved metadata.

Two semantic paraphrases returned the expected statute body first:

- “Can the highest state court require would-be lawyers to provide fingerprints
  for a nationwide criminal background check?” → K.S.A. 7-127, chars `[266, 2118)`.
- “When a local government seeks a grant, is it restricted to one official
  population count or can it use any available census figures?” → K.S.A. 11-210,
  chars `[208, 479)`.

These used native `/api/v1/retrieval/search`, with the compatibility ranking
configuration inside `search_metadata`: dense weight 1, sparse weight 0 and ranker
`none`. Stored retrieval audit rows independently confirm those settings. These
are dense semantic results; no compatibility citation-decorated text is treated
as exact evidence.

Before/after snapshots show identical container IDs, image IDs, environment
fingerprints, mounts, ports, network membership, health, schema and queue state.
The fiscal store remains 69 files/documents, 69 versions and 13,179 chunks with
identical recorded fingerprints. The statute store remains graph-disabled and
`production_ready=false`.

## Verification command

The three focused files passed: **39 tests, zero skips, 11.62 seconds**.
Required real-export/harvest/custody mounts fail if absent; they do not skip.

```bash
docker run --rm --platform linux/arm64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro \
  -v /Users/mfrieson/Developer/statecivics-statute-exports:/exports:ro \
  -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money/.release/cells/ks-fiscal-local/wave-138/statute-state.json:/canary-state.json:ro \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money/.release/cells/ks-fiscal-local/wave-139:/proof \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  -e SVS_STATUTE_CORPUS_ROOT=/statutes -e SVS_STATUTE_EXPORT_ROOT=/exports \
  -e SVS_STATUTE_CUSTODY_ROOT=/custody -e SVS_STATUTE_CANARY_STATE=/canary-state.json \
  exais-ks-fiscal/api:wave138-f0114e0 \
  python -m pytest -q -rs --tb=short -p no:cacheprovider \
  --junit-xml=/proof/tranche-tests.xml \
  tests/test_kansas_statute_tranches.py tests/test_kansas_statute_ingest.py \
  tests/test_ingestion_metadata_refresh.py
```

`git diff --check` passes. Worker-owned tracked changes are this proof, its JSON
and the one new test file. Raw source text, full responses, snapshots and scripts
remain outside Git in the durable operator directory.

## Remaining scope

Independent QC is required before continuation. WAVE-140 owns application of the
remaining 83 tranches: 28,797 substantive documents / 83,159 chunks are not yet
indexed; 31,059 records are not in shared state. No canonical legal graph,
current-law adjudication or appropriation edge is claimed. The input auditor's
latent upstream substring-label guard finding remains manager-owned; all delivered
custody/corpus joins in this pinned batch passed exact verification.
