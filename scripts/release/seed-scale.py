from __future__ import annotations

import argparse
import time

from release_common import DEFAULT_CELL, api_base, compose_base, ensure_env, run
from scale_common import api_json, chunk_vector_store_where, job_vector_store_where, parse_int_row, psql, scale_doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the scale gate through the real queue path and print SQL counts.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--documents", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--headings-per-doc", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--vector-store-id", help="Reuse an existing vector store for resume/proof-only runs.")
    parser.add_argument("--skip-submit", action="store_true", help="Only poll and prove counts for --vector-store-id.")
    args = parser.parse_args()
    ensure_env(args.cell)
    api = api_base(args.cell)

    if args.skip_submit and not args.vector_store_id:
        raise ValueError("--skip-submit requires --vector-store-id")
    if args.vector_store_id:
        vector_store_id = args.vector_store_id
    else:
        store = api_json("POST", f"{api}/v1/vector_stores", {"name": f"Scale Gate {int(time.time())}", "knowledge_base_id": "kb_dev"}, cell=args.cell)
        vector_store_id = store["id"]
    print(f"VECTOR_STORE_ID={vector_store_id}")

    if args.skip_submit:
        print("Skipping document submission; proving existing vector store counts.")
    else:
        submitted = 0
        for start in range(0, args.documents, args.batch_size):
            end = min(start + args.batch_size, args.documents)
            files = [scale_doc(i, args.headings_per_doc) for i in range(start, end)]
            api_json("POST", f"{api}/v1/vector_stores/{vector_store_id}/file_batches", {"files": files}, timeout=300, cell=args.cell)
            submitted = end
            print(f"Submitted queued docs: {submitted}/{args.documents}")

    job_where = job_vector_store_where(vector_store_id)
    chunk_where = chunk_vector_store_where(vector_store_id)
    deadline = time.time() + args.timeout_seconds
    last_counts = ""
    while time.time() < deadline:
        last_counts = psql(args.cell, f"""
SELECT status, count(*) FROM ingestion_jobs WHERE {job_where} GROUP BY status ORDER BY status;
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed') AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running')) AS active_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true) AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed') AS indexed_chunks;
""")
        rows = psql(args.cell, f"""
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed')::int AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running'))::int AS active_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true)::int AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed')::int AS indexed_chunks;
""", tuples_only=True)
        fields = parse_int_row(rows)
        if len(fields) == 4:
            failed_jobs, active_jobs, active_chunks, indexed_chunks = fields
            if failed_jobs == 0 and active_jobs == 0 and active_chunks >= args.documents * args.headings_per_doc and indexed_chunks >= args.documents * args.headings_per_doc:
                print("Scale seed complete.")
                print(f"VECTOR_STORE_ID={vector_store_id}")
                return
        time.sleep(10)
    print(last_counts)
    raise TimeoutError("Scale seed did not reach required counts before timeout.")


if __name__ == "__main__":
    main()
