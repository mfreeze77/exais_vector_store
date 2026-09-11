# WAVE-138 local statute canary proof

**Implementation verified; independent QC PASS WITH NOTES.** Executed 2026-09-11.
The [independent review](wave-138-local-canary-qc.md) accepts this bounded local run.
This is the existing local Kansas cell, not OVH or production activation.
[Sanitized machine-readable proof](wave-138-local-canary-proof.json) records
complete image, input, source, coordinate and operational-artifact hashes.
Raw responses and retained source text stay in ignored `.release/`.

## Actual result

The normal API created **Kansas Statutes**, `vs_daafbc5d7aa54b23b3f10392`, in
`ten_ks_state_civics` / `biz_ks_state_civics` / `kb_ks_civics`.
Physical cell: `ks-fiscal-local`; logical instance: `ks-state-civics`.
Requests used the existing `usr_ks_state_civics_admin` principal explicitly.
Host API: `http://127.0.0.1:28085`; runner network API: `http://api:8080`.

The approved six-record export produced **four completed files, four documents,
four indexed versions and 62 active chunks/embeddings**. Empty-body K.S.A. 60-3401
and inline-History-only 41-214 contributed no searchable document. Their retained
custody objects remain intact. Apply: four upserts, two noops, zero removals.

| K.S.A. | Live document | Live version | Chunks |
|---|---|---|---:|
| 1-204 | `doc_d1e8c84ff60840b782e7be7b` | `docv_ba32dfdef29942708361a210` | 2 |
| 2-303 | `doc_d9586930129a4e5cb87781a2` | `docv_fa51bc80390c4e20a34eecc9` | 2 |
| 73-201 | `doc_b68c91e8f15b4bfc83c9a508` | `docv_a0854ca4cd8b4270a78cfb09` | 7 |
| 79-3606 | `doc_d617f17950484ff7b2aaa702` | `docv_2f399342778e4bd090944cfd` | 51 |

All 62 embeddings report `voyage_4_docs_1024`, provider `voyage`, model `voyage-4`,
1024 dimensions. Four actual `api.voyageai.com/v1/embeddings` HTTP 200 responses
occur between the four successful server previews and ingest responses. Four
committed provider usage events sum to 62 indexed chunks. This is live provider
execution, not a profile-name assertion or test double.

Read-only Qdrant retrieval verified all 62 expected point IDs, finite nonzero
1024-element vectors and matching tenant/business/store/chunk payloads in
`svs_biz_ks_state_civics_voyage_4_docs_1024`. PostgreSQL marks every chunk dense
and sparse indexed, with an FTS vector present. The proof checks scoped points,
not the entire shared collection's total.

## Semantic recall and exact evidence

Four paraphrased questions each ranked the expected statute-body chunk first:

- Where do penalties collected by the accounting licensing board go, and what authorizes withdrawals?
- Can county fair money fund prizes for speed contests?
- Do military veterans receive a hiring preference for jobs in state or local government?
- Which farm equipment purchases escape retail sales tax, and are replacement parts included?

Both supported API surfaces were exercised. Compatibility search supplied
`ranking_options: {ranker: "none", hybrid_search: {embedding_weight: 1.0,
text_weight: 0.0}}`. Native search used the equivalent supported
`search_metadata.openai_compat` settings with `retrieval_profile_id:
"hybrid_rrf_secure_v2"`. Eight actual retrieval audit rows confirm dense weight
1, sparse weight 0, and disabled reranking. Sparse candidates may still be
computed internally, but they contribute no ranking weight. The normalized
compatibility score is not a probability or raw cosine score.

| Expected K.S.A. | Rank | Exact Unicode code-point range | Enclosing LF lines |
|---|---:|---|---|
| 1-204 | 1 | `[232, 1060)` | 7–9 |
| 2-303 | 1 | `[210, 326)` | 7–9 |
| 73-201 | 1 | `[5879, 7313)` | 44–61 |
| 79-3606 | 1 | `[17031, 20541)` | 46–53 |

The native `/api/v1/retrieval/search` response carries exact `text` and
`metadata.char_start`, `char_end`, `line_start`, `line_end`, hashes, source
revision, official URL and region label. Every one of the **20 native returned
hits**, plus **all 62 stored chunks**, was checked against the original retained
UTF-8 Markdown, its pinned whole-document hash and quote hash. Character ranges
are zero-based/end-exclusive Unicode code points; lines are one-based LF
positions. PDF pages and canonical provision/action IDs are absent. History
references remain unresolved; response hashes retain their decoded-text basis.

Compatibility `/v1/vector_stores/{id}/search` appends citation markers to text
and exposes document attributes, not the chunk-coordinate metadata. Its top
citation chunk IDs agree with the native results. A caller needing exact
coordinates must use the native metadata path; do not hash the decorated
compatibility string as original evidence.

Logs record **12 successful Voyage calls** overall: four document batches and
eight query requests across the two API surfaces. The replay below added no
provider calls. Source text responses and vector-hash checks remain in local operational
proof, with artifact hashes in the sanitized JSON.

## Replay and preservation

Reapplying the identical pinned export returns **six noops, zero upserts and
zero removals**. Complete before/after document, version, chunk, embedding,
Qdrant vector-hash and ingestion-usage snapshots compare equal. Their identical
serialized snapshot SHA-256 is
`8126c7ddba0dc892981c8542ae1d56eeb7972455f535593565de08d178b0f959`.
Consumer state contains four upserts and two content-exclusion removals/absences.
No document/version/point identity was duplicated and no extra ingestion usage
was recorded.

The fiscal store remained **69 documents, 69 versions, 69 files and 13,179
chunks**, with every captured identity/content/status fingerprint unchanged.
Its API file counts remain 68 completed and one pre-existing cancelled file.
These are measured local counts, not the earlier manager-reported 70/13,181
inventory. All infrastructure container IDs, application volume mounts and
ports stayed unchanged. The queue still has only three completed jobs.
Schema revision remains `004_wave125_caller_identity`; no migration ran.

## Application build and activation

Built only API/worker from immutable `git archive` content of
`f0114e0bd956f45214f9b3dd4135d1bd400f36af`. Archive: 7,925,760 bytes, SHA-256
`e05ba853c98db8118b73409d392ccb065e83817fff855d1b912bb82c14d948d3`.
The migration diff from running `bb7e575` is empty. The existing committed
Dockerfiles were used without modification, producing ARM64 images:

- API: `sha256:e7271b65b0554f29c5378a0f39a9a2e5e3e4f46fc710138328ef4cf8515627c5`
- Worker: `sha256:d66e0316f93ca4bc7493ec135063747b122e7dc8a8f321530066e3aa2bacc387`

The new API image itself passed **128 focused tests, zero skipped, 14.24s**,
with network disabled and the real corpus mounted read-only. The retained JUnit
report and exact build/test logs are hash-listed in the JSON. This test proof
is separate from the live execution above.

Activation uses the existing fiscal checkout's compose file, original
`.env.cell` and `.env.images`, and Marker timeout override, plus an application-only
image-ID overlay. Only `api worker` were recreated, using `--no-deps --pull never`.
Both are healthy; `/healthz` and `/readyz` pass. Configured environment values
were compared through hashes before and after activation; no secrets were printed
or placed in tracked proof.

One existing configuration drift was preserved deliberately: API runs
`MARKER_MAX_ATTEMPTS=1`; worker runs `2` although the existing override file says
`1`. Both retain `MARKER_TIMEOUT_SEC=14400`. The application overlay records
worker=2; all other environment values, ports and volumes match the captured
running configuration.

These locally built image IDs are not registry publication or clean
pull-by-digest release proof. Future local compose invocations must include the
retained application overlay to keep this canary image selection; the original
image env file was not rewritten.

## Reproduction and rollback

Operational directory:
`/Users/mfrieson/Developer/exais-vector-store-law-money/.release/cells/ks-fiscal-local/wave-138/`.
It retains `deploy.py`, `activate.sh`, `rollback.sh`, both overlays, exact build
logs/context pin, `apply-command.sh`, `replay-command.sh`, verification scripts,
state and response artifacts. All inputs were read-only container mounts;
`approved-export.jsonl` is an unchanged local copy bound to the approved SHA.

Exact successful apply command:

```sh
docker run --rm --platform linux/arm64 --network exais-vector-store-ks-fiscal-local_default --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money/.release/cells/ks-fiscal-local/wave-138/approved-export.jsonl:/handoff/kansas-statutes.jsonl:ro -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro -v /Users/mfrieson/Developer/exais-vector-store-law-money/.release/cells/ks-fiscal-local/wave-138:/proof -w /app -e PYTHONDONTWRITEBYTECODE=1 -e SVS_TENANT_ID=ten_ks_state_civics -e SVS_BUSINESS_INSTANCE_ID=biz_ks_state_civics -e SVS_USER_ID=usr_ks_state_civics_admin sha256:e7271b65b0554f29c5378a0f39a9a2e5e3e4f46fc710138328ef4cf8515627c5 python scripts/release/kansas-fiscal-document-ingest.py --cell ks-fiscal-local --api http://api:8080 --api-transport auto --source-family kansas-statutes --vector-store-slug kansas-statutes --vector-store-id vs_daafbc5d7aa54b23b3f10392 --vector-store-name 'Kansas Statutes' --knowledge-base-id kb_ks_civics --manifest /handoff/kansas-statutes.jsonl --custody-root /custody --harvest-manifest /statutes/manifests/statute_scrape_20260911_030653.json --harvest-root /statutes --harvest-manifest-sha256 17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2 --state /proof/statute-state.json --proof /proof/apply-proof.json --apply
```

The replay command uses the same parameters with output
`/proof/replay-proof.json`; no input/profile/state identity changed. Runner flag
is `--api`, not `--api-base`. Export: 10,954 bytes,
`c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7`;
harvest: `17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2`.

Concrete application rollback, prepared and configuration-checked but not needed
or exercised:

```sh
sh /Users/mfrieson/Developer/exais-vector-store-law-money/.release/cells/ks-fiscal-local/wave-138/rollback.sh
```

That script runs the same compose/environment/timeout configuration with
`rollback.override.yml`, restoring API
`sha256:965b02f21d310304f767cc9e34b24c22814089fb7e19d867d0286aac9e483895`
and worker
`sha256:051d7ee8c29476d61e361995956829766223759c1e2be181b9ea6d98b92dcd8d`
using `up -d --no-deps --pull never api worker`. Those original images remain
local. Rollback changes applications only; it does not delete the approved
statute data or alter databases/volumes.

## Boundaries

No runtime source code, upstream repository, custody bytes, schema, OVH service
or unrelated container changed. No broader statute export was applied.
`productionReady: false` and graph disabled remain explicit. This proves local
statute document ingestion and retrieval; canonical provision/action linkage,
verified source-span attestations and the full law-and-money GraphRAG remain
separate work. Independent QC passed; the updated source declarations also pass
`validate-instance-source-packages.py --instance ks-state-civics --vector-store
kansas-statutes --production --json` in the new API image (one package, zero
issues). That flag validates declaration rules; it does not change the explicit
non-production status.
