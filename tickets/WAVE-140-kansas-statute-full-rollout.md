# WAVE-140: Index the approved full Kansas statute corpus

Status: in progress; coordinator QC PASS WITH NOTES; bulk paused after a 429 at 575 checkpointed records; WAVE-141 owns caller pacing before continuation. Dependency: WAVE-139 complete (ab86356, QC PASS WITH NOTES). Owner: ExAIS. Parent: WAVE-132.

## Outcome

The owner directs proceeding with the full corpus in the existing local Kansas
cell; vectorization cost is not a gate. Consume the 85 verified chapter exports
and finish with 28,812 indexable documents / 83,258 active chunks, preserving
the 2,267 non-indexable source records in custody and unresolved History evidence.
Use store `vs_daafbc5d7aa54b23b3f10392` in `ks-fiscal-local`; no new cell,
OVH preparation, deployment, provider default, migration or canonical graph.

## Read first / reuse

Read WAVE-139, its tests/proof/QC and full export audit, source package, existing
runner `load_manifest`, `load_state`, `plan_operations`, `apply_operations`,
`ensure_vector_store`, and `preflight_statute_harvest`. Existing API/provider
batching and source identity/dedupe remain authoritative. WAVE-138/139 capture
the live IDs, configuration and fiscal preservation baseline.

## Scope

- Add a small operational coordinator only if needed, reusing the existing
  Python runner functions. Do not create another ingestion/data path. Verify
  the required INDEX SHA-256, target, all chapter paths/hashes/counts and unique
  logical identities before live effects. Pin the unchanged harvest once.
- Use durable `/Users/mfrieson/Developer/statecivics-statute-ingestion/` state
  outside every checkout. Seed from the verified WAVE-139 state. Keep independent
  chapter state to avoid rewriting a 31,079-row state file after every document;
  preserve logical identity across the existing canaries and new chapter exports.
- Apply serially with an exclusive process lock, stable idempotency keys and
  atomic state/progress updates. Never infer removals from omitted identities.
  A failure stops the run with a nonzero status and exact failed chapter;
  completed documents remain resumable. Do not claim running/interrupted work
  complete. No untested parallel writes or unbounded retry loop.
- Retain immutable input/consumer pins, command, progress, error and final proof.
  Use the deployed API image and existing API, with no secrets in output.
  A long job may run in a named container with durable mounts, but must remain
  monitored and have a concrete stop/resume command.
- Verify existing exporter-only changes do not create extra document versions
  or vectors. Preserve the original six-record export and prior stage state.
- Final live verification: exact expected document/version/chunk counts and
  per-chapter counts, all dense/sparse statuses and source revision/hash bindings,
  scoped Qdrant points/model/dimensions, no indexed exclusions, intact fiscal
  inventory and application/infra state. Check exact stored text against custody
  and execute real dense recall across multiple chapters, retaining honest ranks.
- Record all completion/failure counts and remaining gaps; keep GraphRAG and
  production readiness separate. Finish with independent QC and source-lock,
  ticket/tracker and handoff updates. No source bytes or large responses in Git.

## File ownership and gates

One worker may own `scripts/release/kansas-statute-rollout.py` and
`tests/test_kansas_statute_rollout.py` if orchestration code is required, plus
`wave-140-rollout-proof.md` / compact `.json` under the aligned proof directory.
Root owns ticket/source/operator documentation. Characterize actual retained
inputs, interrupted resume, wrong index/path/hash/scope/duplicate IDs, lock
exclusion, seed partitioning and omission preservation before any new coordinator
is used live. Provider/API doubles must remain explicitly labeled.

Independent coordinator QC must pass before bulk activation if code is added;
final live QC must pass before the ticket is complete. Do not broaden API,
schema, transaction or provider code to improve throughput inside this ticket.
If a concrete service defect prevents completion, record it and isolate the
necessary fix rather than weakening evidence or silently skipping records.
