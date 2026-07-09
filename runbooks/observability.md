# ExAIS Local Cell Observability

RM-007 adds local-cell observability wiring for the Docker cell. It proves that
Prometheus can scrape ExAIS metric names and that Grafana dashboards and
Prometheus alert rules reference those names. It does not prove external SLOs,
production-scale load behavior, customer-host deployment, or external backup
restore drills.

## Start The Stack

Run the observability overlay with the local cell:

```powershell
docker compose -f infra/docker/compose.cell.yml -f infra/docker/compose.observability.yml up -d
```

Default local ports:

- Prometheus: `http://localhost:19090`
- Grafana: `http://localhost:13000`
- Alertmanager: `http://localhost:19093`

Prometheus scrapes:

- `api:8080/metrics` for API, ingestion, worker, index, storage, security, cost, and backup visibility metrics.
- `model-gateway:8081/metrics` for model provider and cost-profile visibility metrics.

Worker metrics are intentionally derived from `ingestion_jobs` through the API
metric endpoint. RM-007 does not add an HTTP listener to the worker process.

## Smoke Proof

After the cell and observability overlay are healthy, collect local evidence:

```powershell
python scripts/release/observability-smoke.py --api-base http://localhost:18080 --prometheus-url http://localhost:19090 --cell local-cell
```

The command exits nonzero if any required metric category is missing from the
API metric text or from Prometheus query results. Required categories are API,
ingestion, worker, index, storage, security, cost, and backup.

## Metric Families

The API exports deterministic, cheap aggregate metrics. Database query failures
fall back to `0` to preserve the existing local-cell metrics behavior.

- API/build: `svs_api_build_info`, `svs_api_index_strict_enabled`
- Ingestion/worker: `svs_ingestion_jobs_queued`, `svs_ingestion_jobs_oldest_queued_age_seconds`, `svs_worker_jobs_completed_total`, `svs_worker_jobs_failed_total`
- Index: `svs_chunks_index_pending`, `svs_chunks_dense_index_pending`, `svs_chunks_sparse_index_pending`
- Storage/object: `svs_object_store_documents_tracked_total`, `svs_object_store_bytes_tracked`, `svs_storage_vector_store_usage_bytes`
- Security: `svs_security_audit_events_denied_total`, `svs_security_acl_denied_retrieval_total`
- Cost: `svs_usage_cost_estimate_usd_total`, `svs_cost_events_with_estimate_total`, `svs_model_gateway_priced_embedding_profiles`
- Backup: `svs_backup_bundle_last_success_timestamp_seconds`, `svs_backup_freshness_age_seconds`, `svs_backup_manifest_artifacts_total`

Backup metrics expose visibility into RM-006 backup bundle and manifest names.
They do not change backup creation, external target publication, or restore
implementation.
