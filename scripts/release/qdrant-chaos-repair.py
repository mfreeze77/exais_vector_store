from __future__ import annotations

import argparse
from collections import defaultdict
import json
import subprocess
import time

from release_common import DEFAULT_CELL, api_base, compose_base, compose_network_name, ensure_env, printable_command, project_name, run
from scale_common import api_json, chunk_vector_store_where, job_vector_store_where, parse_int_row, psql, scale_doc


def parse_point_rows(output: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in output.strip().splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 2 and parts[0] and parts[1]:
            rows.append((parts[0], parts[1]))
    return rows


def group_points_by_collection(rows: list[tuple[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for collection, point_id in rows:
        grouped[collection].append(point_id)
    return dict(grouped)


def vector_store_filter(vector_store_id: str) -> dict:
    return {"must": [{"key": "vector_store_id", "match": {"value": vector_store_id}}]}


def qdrant_json(cell: str, method: str, path: str, payload: dict | None = None, *, check: bool = True, timeout: int = 120) -> tuple[int, dict]:
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        compose_network_name(cell),
        "curlimages/curl:8.10.1",
        "-sS",
        "-w",
        "\n%{http_code}\n",
        "-X",
        method,
        "-H",
        "Content-Type: application/json",
    ]
    body = ""
    if payload is not None:
        body = json.dumps(payload)
        args += ["--data-binary", "@-"]
    args.append(f"http://qdrant:6333{path}")
    print("$ " + printable_command(args), flush=True)
    proc = subprocess.run(
        args,
        input=body,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = proc.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    print(f"[exit {proc.returncode}]", flush=True)
    if proc.returncode != 0:
        if check:
            raise subprocess.CalledProcessError(proc.returncode, args, output)
        return 0, {}
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    if check and status >= 400:
        raise RuntimeError(f"Qdrant {method} {path} returned HTTP {status}: {raw}")
    return status, json.loads(raw) if raw else {}


def qdrant_vector_store_count(cell: str, collection: str, vector_store_id: str) -> int:
    status, body = qdrant_json(
        cell,
        "POST",
        f"/collections/{collection}/points/count",
        {"filter": vector_store_filter(vector_store_id), "exact": True},
        check=False,
    )
    if status == 404:
        return 0
    if status == 0:
        raise RuntimeError(f"Qdrant count command failed for {collection}")
    if status >= 400:
        raise RuntimeError(f"Qdrant count failed for {collection}: HTTP {status}")
    return int((body.get("result") or {}).get("count") or 0)


def qdrant_vector_store_counts(cell: str, collections: list[str], vector_store_id: str) -> dict[str, int]:
    return {collection: qdrant_vector_store_count(cell, collection, vector_store_id) for collection in sorted(set(collections))}


def qdrant_delete_points(cell: str, collection: str, point_ids: list[str]) -> None:
    if not point_ids:
        return
    qdrant_json(cell, "POST", f"/collections/{collection}/points/delete?wait=true", {"points": point_ids})


def psql_capture(cell: str, sql: str, *, tuples_only: bool = False) -> str:
    flags = ["-At"] if tuples_only else []
    args = compose_base(cell) + ["exec", "-T", "postgres", "psql", *flags, "-U", "svs_owner", "-d", "svs", "-v", "ON_ERROR_STOP=1", "-c", sql]
    print("$ " + printable_command(args), flush=True)
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(f"[exit {proc.returncode}]", flush=True)
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
        raise subprocess.CalledProcessError(proc.returncode, args, proc.stdout)
    return proc.stdout or ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Kill Qdrant during queued ingest, restart, run reindex repair, and print SQL proof.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--documents", type=int, default=500)
    parser.add_argument("--headings-per-doc", type=int, default=8)
    parser.add_argument("--kill-delay-seconds", type=float, default=1.5)
    parser.add_argument("--outage-seconds", type=float, default=3.0)
    parser.add_argument("--repair-batch-size", type=int, default=1000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    ensure_env(args.cell)
    api = api_base(args.cell)
    base = compose_base(args.cell)

    store = api_json("POST", f"{api}/v1/vector_stores", {"name": f"Qdrant Chaos Gate {int(time.time())}", "knowledge_base_id": "kb_dev"}, cell=args.cell)
    vector_store_id = store["id"]
    print(f"VECTOR_STORE_ID={vector_store_id}")
    files = [scale_doc(1_000_000 + i, args.headings_per_doc) for i in range(args.documents)]
    for item in files:
        item["vector_store_id"] = vector_store_id
        item["knowledge_base_id"] = "kb_dev"
    api_json("POST", f"{api}/v1/vector_stores/{vector_store_id}/file_batches", {"files": files}, timeout=300, cell=args.cell)

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

    repair_batch = min(max(args.repair_batch_size, 1), 1000)
    selected_points = parse_point_rows(psql_capture(args.cell, f"""
SELECT e.vector_collection, e.vector_point_id
FROM chunks c
JOIN embeddings e ON e.chunk_id=c.id
WHERE {chunk_where} AND c.active=true
  AND e.vector_collection IS NOT NULL AND e.vector_point_id IS NOT NULL
ORDER BY c.created_at ASC, c.id ASC
LIMIT {repair_batch};
""", tuples_only=True))
    if not selected_points:
        raise TimeoutError("No Qdrant points were available for real reindex repair proof.")
    grouped_points = group_points_by_collection(selected_points)
    collections = list(grouped_points)
    print(f"selected_qdrant_points={len(selected_points)} collections={json.dumps(sorted(collections))}")
    before_delete_counts = qdrant_vector_store_counts(args.cell, collections, vector_store_id)
    before_delete_total = sum(before_delete_counts.values())
    print(f"qdrant_counts_before_delete={json.dumps(before_delete_counts, sort_keys=True)}")
    for collection, point_ids in grouped_points.items():
        qdrant_delete_points(args.cell, collection, point_ids)
    after_delete_counts = qdrant_vector_store_counts(args.cell, collections, vector_store_id)
    after_delete_total = sum(after_delete_counts.values())
    print(f"qdrant_counts_after_delete={json.dumps(after_delete_counts, sort_keys=True)}")
    expected_after_delete = before_delete_total - len(selected_points)
    if before_delete_total < len(selected_points) or after_delete_total != expected_after_delete:
        raise TimeoutError(
            f"Qdrant point deletion proof failed: before={before_delete_total} "
            f"deleted={len(selected_points)} after={after_delete_total}"
        )

    repair = api_json(
        "POST",
        f"{api}/api/v1/maintenance/reindex",
        {"vector_store_id": vector_store_id, "batch_size": len(selected_points), "force": True},
        cell=args.cell,
    )
    print(f"repair_response={json.dumps(repair, sort_keys=True)}")
    if int(repair.get("processed") or 0) != len(selected_points):
        raise TimeoutError(f"Repair did not process the deleted Qdrant points: selected={len(selected_points)} response={repair}")
    after_repair_counts = qdrant_vector_store_counts(args.cell, collections, vector_store_id)
    after_repair_total = sum(after_repair_counts.values())
    print(f"qdrant_counts_after_repair={json.dumps(after_repair_counts, sort_keys=True)}")
    if after_repair_total != before_delete_total:
        raise TimeoutError(f"Repair did not restore Qdrant point count: before={before_delete_total} after={after_repair_total}")

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
