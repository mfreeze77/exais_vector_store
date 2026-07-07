from __future__ import annotations

import argparse
import json
import time

from release_common import DEFAULT_CELL, api_base, compose_base, ensure_env, project_name, run
from scale_common import api_json, chunk_vector_store_where, job_vector_store_where, parse_int_row, psql, scale_doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Kill Qdrant during queued ingest, restart, run reindex repair, and print SQL proof.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--documents", type=int, default=500)
    parser.add_argument("--headings-per-doc", type=int, default=8)
    parser.add_argument("--kill-delay-seconds", type=float, default=1.5)
    parser.add_argument("--outage-seconds", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    ensure_env(args.cell)
    api = api_base(args.cell)
    base = compose_base(args.cell)

    store = api_json("POST", f"{api}/v1/vector_stores", {"name": f"Qdrant Chaos Gate {int(time.time())}", "knowledge_base_id": "kb_dev"})
    vector_store_id = store["id"]
    print(f"VECTOR_STORE_ID={vector_store_id}")
    files = [scale_doc(1_000_000 + i, args.headings_per_doc) for i in range(args.documents)]
    for item in files:
        item["vector_store_id"] = vector_store_id
        item["knowledge_base_id"] = "kb_dev"
    api_json("POST", f"{api}/v1/vector_stores/{vector_store_id}/file_batches", {"files": files}, timeout=300)

    time.sleep(args.kill_delay_seconds)
    qdrant_container = f"{project_name(args.cell)}-qdrant-1"
    run(["docker", "kill", qdrant_container], check=False)
    time.sleep(args.outage_seconds)
    run(base + ["up", "-d", "qdrant"])

    job_where = job_vector_store_where(vector_store_id)
    chunk_where = chunk_vector_store_where(vector_store_id)
    deadline = time.time() + args.timeout_seconds
    while time.time() < deadline:
        counts = psql(args.cell, f"""
SELECT status, count(*) FROM ingestion_jobs WHERE {job_where} GROUP BY status ORDER BY status;
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed') AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running')) AS active_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND (dense_index_status <> 'indexed' OR sparse_index_status <> 'indexed')) AS active_unindexed_chunks;
""")
        machine = psql(args.cell, f"""
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed')::int AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running'))::int AS active_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND (dense_index_status <> 'indexed' OR sparse_index_status <> 'indexed'))::int AS active_unindexed_chunks;
""", tuples_only=True)
        fields = parse_int_row(machine)
        if fields == [0, 0, 0]:
            break
        time.sleep(5)
    repair = api_json("POST", f"{api}/api/v1/maintenance/reindex", {"vector_store_id": vector_store_id, "batch_size": 1000})
    print(f"repair_response={json.dumps(repair, sort_keys=True)}")
    final_counts = psql(args.cell, f"""
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed') AS failed_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status IN ('pending','failed')) AS active_dense_pending_or_failed,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND sparse_index_status IN ('pending','failed')) AS active_sparse_pending_or_failed,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND (dense_index_status <> 'indexed' OR sparse_index_status <> 'indexed')) AS active_unindexed_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true) AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed') AS indexed_chunks;
""")
    machine = psql(args.cell, f"""
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed')::int AS failed_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status IN ('pending','failed'))::int AS active_dense_pending_or_failed,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND sparse_index_status IN ('pending','failed'))::int AS active_sparse_pending_or_failed,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND (dense_index_status <> 'indexed' OR sparse_index_status <> 'indexed'))::int AS active_unindexed_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true)::int AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed')::int AS indexed_chunks;
""", tuples_only=True)
    fields = parse_int_row(machine)
    expected_min_chunks = args.documents * args.headings_per_doc
    if len(fields) != 6 or fields[:4] != [0, 0, 0, 0] or fields[4] < expected_min_chunks or fields[5] < expected_min_chunks:
        print(final_counts)
        raise TimeoutError("Qdrant chaos repair did not reach required clean index state.")
    print("Qdrant chaos repair complete.")
    print(f"VECTOR_STORE_ID={vector_store_id}")


if __name__ == "__main__":
    main()
