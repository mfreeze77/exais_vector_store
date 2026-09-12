# WAVE-138 independent local canary QC

Decision: PASS WITH NOTES

Reviewed 2026-09-11 after implementation and declaration updates. This accepts
exactly the six-record **local Kansas statute document canary**, not WAVE-132
GraphRAG completion, full-harvest coverage, upstream suite health or OVH readiness.

Ticket reviewed:

- `tickets/WAVE-138-kansas-statute-local-canary.md`; parent WAVE-132 and
  `build-contract.json` → `statute_local_canary_increment`.

Evidence reviewed:

- All 11 tracked-file diffs and the five new ticket/input/proof files present at
  handoff. Changes are source declarations, documentation, tracker and proof;
  no runtime source, migration or infrastructure template was edited.
- `wave-138-local-canary-proof.md` / `.json`, independent
  `statute-real-export-audit.md`, and `statute-real-export-plan.json`.
- Local operational artifacts under
  `.release/cells/ks-fiscal-local/wave-138/`: baseline/upgraded/final snapshots,
  immutable build context, image pins, compose configuration, activation and
  rollback scripts, apply/replay commands and outputs, persisted-state
  snapshots, recall responses, coordinates, retrieval audits, provider evidence
  and image-test JUnit.
- Independent read-only execution against the actual running API, PostgreSQL
  and Qdrant, plus offline retained-evidence verification in the new API image.
  No deployment, ingestion, replay, schema/configuration change or provider
  query was performed by QC. Existing replay and query results were checked
  against current persisted state and actual running-container logs.

Acceptance criteria:

- [pass] **Authorized target and scope.** Physical cell is `ks-fiscal-local`,
  logical instance `ks-state-civics`. Store `vs_daafbc5d7aa54b23b3f10392` belongs
  to the Kansas scope; its metadata retains `graph_enabled=false` and
  `production_ready=false`. GET checks used explicit Kansas tenant/business/
  admin headers. No OVH or wider export was applied.
- [pass] **Exact healthy application builds.** Current API image
  `sha256:e7271b65b0554f29c5378a0f39a9a2e5e3e4f46fc710138328ef4cf8515627c5`
  and worker image
  `sha256:d66e0316f93ca4bc7493ec135063747b122e7dc8a8f321530066e3aa2bacc387`
  match the proof and carry revision
  `f0114e0bd956f45214f9b3dd4135d1bd400f36af`. Both containers are healthy;
  `/healthz` and `/readyz` succeed. The 7,925,760-byte build archive matches
  a fresh `git archive` byte for byte and its recorded SHA-256.
- [pass] **Four live documents and 62 actual vectors.** Independently executed
  the read-only DB/Qdrant verification in the running API. Four documents,
  four indexed versions, 62 active chunks and 62 active embeddings use
  `voyage_4_docs_1024`, provider `voyage`, model `voyage-4`, 1024 dimensions.
  All scoped Qdrant point IDs exist with finite, nonzero 1024-element vectors
  and matching tenant/business/store/chunk payloads. Dense/sparse index status
  and PostgreSQL FTS presence pass. Per-document counts are 2, 2, 7 and 51.
- [pass] **Real provider execution.** Current API logs independently contain
  12 successful Voyage embeddings HTTP responses, four previews and four
  native searches, agreeing with the retained proof. Four committed ingestion
  usage records total 62 chunks. This is not established solely by model labels.
- [pass] **Content exclusions and custody.** All six custody objects still
  match approved export hashes and sizes. Running the actual parser in the
  new image classifies 60-3401 as `empty_body` and 41-214 as
  `inline_history_only`; neither has an indexed chunk. Short substantive
  2-303 is retained. No byte-size cutoff substituted for body classification.
- [pass] **Recall and exact source evidence.** Independently verified all 62
  stored slices and all 20 native returned hits against retained UTF-8 Markdown,
  whole-document hashes, quote hashes, exact Unicode character ranges,
  enclosing LF line ranges, source revision/logical IDs and official URLs.
  Four expected sections rank first and match compatibility citation chunk IDs.
  Eight recorded audit rows confirm dense weight 1, sparse weight 0 and disabled
  reranking. History remains unresolved and response hashes retain the decoded
  text basis. No PDF pages or canonical provision/action bindings are invented.
- [pass] **Unchanged replay.** Apply reports four upserts/two noops; replay
  reports six noops. Both retained complete snapshots compare equal, and a
  fresh live DB/Qdrant snapshot equals them exactly, including document/version/
  chunk/embedding identities, vector hashes and ingestion usage. Identical
  retained snapshot SHA-256:
  `8126c7ddba0dc892981c8542ae1d56eeb7972455f535593565de08d178b0f959`.
- [pass] **Existing cell preserved.** Fresh fiscal queries reproduce the
  baseline's 69 document, 69 version, 69 file and 13,179 chunk fingerprints.
  API counts remain 68 completed and one previously cancelled fiscal file.
  Schema remains `004_wave125_caller_identity`; the queue has only three
  completed jobs. Infrastructure container/image identities are unchanged.
  Baseline-to-final and final-to-current comparisons preserve environment
  hashes, ports and mounts. The documented API/worker Marker-attempt drift
  (1 versus 2) is preserved.
- [pass] **Rollback and proof integrity.** Both original application images
  remain locally available. Independently rendered both activation and rollback
  compose configurations: environment hashes, ports and volumes match the
  captured running configuration. Rollback is application-only and has the
  concrete `--no-deps --pull never api worker` command. It was not executed.
  All 33 hash-listed operational artifacts recompute exactly. JUnit contains
  128 executed test cases, zero skipped/failures/errors. `git diff --check`
  exits 0. The root-reported source-package validation is a declaration check,
  correctly distinguished from production readiness.

Findings:

- No blocking defects found in this ticket's implementation or proof.
- The compatibility search response decorates text and exposes document
  attributes. Exact evidence coordinates require the native metadata path;
  the docs state this limitation correctly. A compatibility string must not
  be hashed as an original source slice.
- Retain the local operational directory, state and application overlays.
  Future compose actions must include the overlay to preserve these image
  choices. The original image environment file remains unchanged. Local image
  IDs and tested rollback configuration do not constitute registry publication,
  pull-by-digest release proof or an exercised rollback.
- This canary does not resolve canonical law-and-money relationships,
  verification attestations, upstream repeat-observation persistence or the
  producer's reported pre-existing full-suite failures. Those boundaries are
  explicit and do not block this bounded document-search acceptance.

Required fixes before next ticket:

- None. Root may record this decision, complete WAVE-138's status links and
  commit the scoped files. WAVE-132 remains open.

## Executed verification and reproduction

From `/Users/mfrieson/Developer/exais-vector-store-law-money`, QC executed the
following current-state check, capturing its JSON and comparing the entire
parsed result to both retained apply/replay snapshots:

```sh
docker exec -i exais-vector-store-ks-fiscal-local-api-1 \
  python - vs_daafbc5d7aa54b23b3f10392 \
  < .release/cells/ks-fiscal-local/wave-138/statute-db-check.py
```

That script was read before execution: SQL explicitly sets `TRANSACTION READ
ONLY`, scope settings are transaction-local, and Qdrant uses collection info
and point retrieval only. It asserts all provider, count, status, dimension,
finite-vector and scoped payload requirements before returning the snapshot.

QC separately executed the `sql_script` literal from `snapshot.py` through
`docker exec ... python -c`, without executing its file-writing wrapper, and
compared the result to `baseline.json`. Docker inspect data was captured and
compared in memory; environment values were hashed, never printed. Both overlay
configurations were rendered via the recorded `compose-command.json` arguments
plus `-f <overlay> config --format json`, with output compared in memory.

For offline exact-evidence checks, QC used the pinned new API image with
`--network none --memory 1g --cpus 1`, `PYTHONDONTWRITEBYTECODE=1`, and read-only
mounts of operational proof, statute corpus and custody. The independent
assertions verified every stored/returned slice as `source[char_start:char_end]`,
its UTF-8 hash, full source hash, source IDs/URL, line counts and unresolved
History status; the same run checked exclusions through
`parse_statute_markdown`. Result: **62 stored + 20 returned exact slices,
four matching top hits, six retained custody objects, two correct exclusions,
eight dense-only audit records**. No corpus or proof artifact was rewritten.

The separate metadata audit recomputed all 33 artifact hashes and the build
archive, read the JUnit XML directly, compared current running image revisions
and health, and confirmed old rollback image availability. Only this QC report
was written by the reviewer.

> **Correction (2026-09-12):** the fiscal chunk count above is a miscount. The store measures **13,180** chunks by three independent methods — via `documents`, via `chunks.vector_store_id`, and via `embeddings` — and its newest `updated_at` is still 2026-09-10T08:50:57Z, so nothing has written to it since before this document was produced. Treat **13,180** as the baseline. Nothing was added and nothing is to be restored; the original figure is left in place above as the point-in-time record.
