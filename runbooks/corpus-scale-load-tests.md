# Corpus-Scale Load Test Runbook

RM-016 is an operator proof gate. The repo provides deterministic local scale
scripts and this proof package, but the roadmap item is not closed until the
selected corpus or a documented production-scale surrogate runs against the
target cell and reports the required metrics.

## Proof Boundary

Use a real selected corpus when possible. If that corpus is not available, use a
documented production-scale surrogate and state exactly why it represents the
target workload. The existing local Docker scale gate in
`docs/DOCKER_LOCAL_CELL_RELEASE.md` is useful for readiness, but it is not
production corpus proof by itself.

## Inputs

Record these values before running load:

| Input | Required evidence |
|---|---|
| Cell | Cell id, host topology, worker count, backend choices, registry image version, and API base |
| Corpus | Source, size in bytes, document count, file type mix, expected chunk count, and sensitivity classification |
| Surrogate, if used | Generation method, target size, document count, headings/chunks per document, and gaps from the real corpus |
| Providers | Embedding/rerank provider names, endpoint type, model id, rate limits, and whether calls are warm or cold |
| SLO targets | Search p95 <= 500 ms, context-pack p95 <= 2000 ms, normal freshness <= 5 minutes, priority freshness <= 30 seconds |
| Failure budget | Expected retry, provider throttle, queue backlog, index unavailable, and object-store failure behavior |

The repo-local config template is `load-tests/corpus-scale.yml`.

## Baseline Readiness

Validate the cell, env, access path, and metric visibility:

```bash
python scripts/release/prod-env-preflight.py --env-file <cell-env>
python scripts/release/cell-access-proof.py --cell <cell-id>
python scripts/release/observability-smoke.py --cell <cell-id> --api-base <api-base> --prometheus-url <prometheus-url>
```

Keep the `observability-smoke.py` JSON because it proves ingestion, worker,
index, storage/object, provider/cost, security, and backup metric visibility for
the run.

## Ingestion Load

For the deterministic surrogate path, seed through the real API queue:

```bash
python scripts/release/seed-scale.py --cell <cell-id> --documents <documents> --headings-per-doc <headings-per-doc> --batch-size <batch-size> --timeout-seconds <seconds>
```

For a real corpus, use the same API ingestion path or the approved corpus
ingestion adapter. The proof must report:

- ingestion throughput in documents/minute and chunks/minute;
- p95 search latency against the retrieval SLO;
- queue freshness as oldest queued age and total queued/running jobs;
- failed, retried, and dead-lettered job counts;
- active chunk count and indexed chunk count;
- object-store bytes written and index growth;
- provider latency, error, throttle, and cost observations.

The current `seed-scale.py` output gives vector store id and SQL counts. For
full RM-016 proof, also capture Prometheus/Grafana or SQL evidence for queue age,
provider latency, and backend index growth.

## Retrieval And Context-Pack Load

Measure search p95 with the existing benchmark:

```bash
python scripts/release/search-bench.py --cell <cell-id> --vector-store-id <vector-store-id> --queries <queries> --warmup-queries <warmup> --p95-ms 500 --pace-ms <pace-ms>
```

Measure context-pack p95 separately. Until a dedicated benchmark script exists,
use timed POST requests to the supported endpoint and record p50, p95, average,
errors, and result sizes:

```bash
curl -fsS -w '\ntime_total=%{time_total}\nhttp_code=%{http_code}\n' \
  -H 'Content-Type: application/json' \
  -X POST <api-base>/api/v1/retrieval/context-pack \
  --data '{"vector_store_id":"<vector-store-id>","query":"<representative-query>","top_k":5,"max_context_tokens":4000}'
```

The context-pack proof must include p95 context-pack latency, not only search
latency. A search-only run is incomplete for RM-016.

## Failure Modes

Run or simulate each failure mode in the selected cell and record expected
system behavior. The final packet must list all failure modes exercised and all
failure modes not exercised:

| Failure mode | Required proof |
|---|---|
| Provider throttle or transient 5xx | Retry/backoff evidence, final job state, provider latency/error metrics |
| Provider unavailable | Fail-closed or approved fallback behavior with no silent hash/mock fallback for real providers |
| Queue backlog | Oldest queued age, drain time, worker scale, and freshness SLO pass/fail |
| Qdrant unavailable | Search/index error evidence or degraded behavior, plus recovery/reindex command |
| OpenSearch unavailable | Sparse/BM25 degradation or fail-closed evidence for the configured backend |
| Object store write failure | Failed job/audit evidence and no false indexed-success claim |
| Rate limiting | `search-bench.py --pace-ms` or API 429 evidence showing the test respects configured limits |

## Result Packet

Attach a machine-readable summary with these fields:

```text
cell_id
api_base
corpus_name
corpus_type
documents_total
bytes_total
chunks_total
vector_store_id
ingestion_throughput_docs_per_min
ingestion_throughput_chunks_per_min
queue_freshness_oldest_age_seconds
index_growth_qdrant_points
index_growth_opensearch_docs
object_store_bytes_written
provider_latency_p95_ms
p95_search_latency_ms
p95_context_pack_latency_ms
failure_modes_exercised
failure_modes_not_exercised
operator_verdict
```

RM-016 remains packaged but operator-dependent until this packet is complete for
the selected corpus or documented surrogate.
