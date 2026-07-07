from __future__ import annotations

import argparse
from collections import defaultdict
import json
import subprocess
import time

from release_common import DEFAULT_CELL, api_base, compose_network_name, ensure_env, printable_command
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


def wait_for_vector_store(cell: str, vector_store_id: str, expected_chunks: int, timeout_seconds: int) -> dict[str, int]:
    job_where = job_vector_store_where(vector_store_id)
    chunk_where = chunk_vector_store_where(vector_store_id)
    deadline = time.time() + timeout_seconds
    last_fields: list[int] = []
    while time.time() < deadline:
        psql(
            cell,
            f"""
SELECT status, count(*) FROM ingestion_jobs WHERE {job_where} GROUP BY status ORDER BY status;
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed') AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running')) AS active_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true) AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed') AS indexed_chunks;
""",
        )
        machine = psql(
            cell,
            f"""
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed')::int AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running'))::int AS active_jobs,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true)::int AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed')::int AS indexed_chunks;
""",
            tuples_only=True,
        )
        last_fields = parse_int_row(machine)
        if len(last_fields) == 4 and last_fields[0] == 0 and last_fields[1] == 0 and last_fields[2] >= expected_chunks and last_fields[3] >= expected_chunks:
            return {
                "failed_jobs": last_fields[0],
                "active_jobs": last_fields[1],
                "active_chunks": last_fields[2],
                "indexed_chunks": last_fields[3],
            }
        time.sleep(5)
    raise TimeoutError(f"Vector store did not settle in {cell}: expected>={expected_chunks} last={last_fields}")


def vector_store_collections(cell: str, vector_store_id: str) -> list[str]:
    output = psql(
        cell,
        f"""
SELECT DISTINCT e.vector_collection
FROM chunks c JOIN embeddings e ON e.chunk_id=c.id
WHERE {chunk_vector_store_where(vector_store_id)}
  AND c.active=true
  AND e.vector_collection IS NOT NULL
ORDER BY e.vector_collection;
""",
        tuples_only=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def selected_point_rows(cell: str, vector_store_id: str, limit: int) -> list[tuple[str, str]]:
    output = psql(
        cell,
        f"""
SELECT e.vector_collection, e.vector_point_id
FROM chunks c
JOIN embeddings e ON e.chunk_id=c.id
WHERE {chunk_vector_store_where(vector_store_id)}
  AND c.active=true
  AND e.vector_collection IS NOT NULL
  AND e.vector_point_id IS NOT NULL
ORDER BY c.created_at ASC, c.id ASC
LIMIT {limit};
""",
        tuples_only=True,
    )
    return parse_point_rows(output)


def seed_proof_vector_store(cell: str, api: str, documents: int, headings_per_doc: int, timeout_seconds: int) -> tuple[str, str, dict[str, int]]:
    token = f"repairall{int(time.time())}"
    store = api_json("POST", f"{api}/v1/vector_stores", {"name": f"Repair All Proof {token}", "knowledge_base_id": "kb_dev"}, cell=cell)
    vector_store_id = store["id"]
    print(f"VECTOR_STORE_ID={vector_store_id}")
    files = [scale_doc(2_000_000 + i, headings_per_doc) for i in range(documents)]
    for item in files:
        item["vector_store_id"] = vector_store_id
        item["knowledge_base_id"] = "kb_dev"
        item["content"] += f"\n\nRepair-all token: {token}."
    api_json("POST", f"{api}/v1/vector_stores/{vector_store_id}/file_batches", {"files": files}, timeout=300, cell=cell)
    expected_min_chunks = documents * headings_per_doc
    counts = wait_for_vector_store(cell, vector_store_id, expected_min_chunks, timeout_seconds)
    print(f"repair_all_seed_sql_counts={json.dumps(counts, sort_keys=True)}")
    return vector_store_id, token, counts


def repair_all(cell: str, api: str, vector_store_id: str, batch_size: int, timeout_seconds: int) -> tuple[int, int]:
    cursor: str | None = None
    total_processed = 0
    iterations = 0
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload: dict[str, object] = {"vector_store_id": vector_store_id, "batch_size": batch_size, "force": True}
        if cursor:
            payload["after_chunk_id"] = cursor
        response = api_json("POST", f"{api}/api/v1/maintenance/reindex", payload, timeout=300, cell=cell)
        details = response.get("details") or {}
        processed = int(response.get("processed") or 0)
        has_more = bool(details.get("has_more"))
        last_chunk_id = details.get("last_chunk_id")
        iterations += 1
        total_processed += processed
        print(
            "repair_all_iteration="
            f"{iterations} processed={processed} has_more={str(has_more).lower()} last_chunk_id={last_chunk_id}",
            flush=True,
        )
        if processed == 0 and has_more:
            raise TimeoutError(f"Repair-all cursor stopped while API still reported more rows: {response}")
        if not has_more:
            break
        if not last_chunk_id or last_chunk_id == cursor:
            raise TimeoutError(f"Repair-all cursor did not advance: previous={cursor} response={response}")
        cursor = str(last_chunk_id)
    else:
        raise TimeoutError("Repair-all did not finish before timeout.")
    print(f"repair_all_iterations={iterations}")
    print(f"repair_all_total_processed={total_processed}")
    return iterations, total_processed


def search_result_count(cell: str, api: str, vector_store_id: str, query: str) -> int:
    search = api_json(
        "POST",
        f"{api}/v1/vector_stores/{vector_store_id}/search",
        {"query": query, "top_k": 5, "include_content": True},
        timeout=120,
        cell=cell,
    )
    count = len(search.get("data") or [])
    print(f"repair_all_search_results={count}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Force-reindex a full vector store with cursor pagination and optional drift proof.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--vector-store-id")
    parser.add_argument("--proof", action="store_true", help="Seed a proof store, delete more than one repair batch of Qdrant points, then repair all.")
    parser.add_argument("--documents", type=int, default=40)
    parser.add_argument("--headings-per-doc", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--delete-count", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--search-query")
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 1000:
        raise ValueError("--batch-size must be between 1 and 1000.")
    if args.proof and args.vector_store_id:
        raise ValueError("--proof creates its own vector store; do not pass --vector-store-id.")
    if not args.proof and not args.vector_store_id:
        raise ValueError("Pass --vector-store-id for operator repair or --proof for a deliberate drift drill.")
    if args.delete_count > 0 and not args.proof:
        raise ValueError("--delete-count is only allowed with --proof.")

    ensure_env(args.cell)
    api = api_base(args.cell)
    vector_store_id = args.vector_store_id
    token = args.search_query
    source_counts: dict[str, int] | None = None

    if args.proof:
        vector_store_id, token, source_counts = seed_proof_vector_store(
            args.cell,
            api,
            args.documents,
            args.headings_per_doc,
            args.timeout_seconds,
        )

    assert vector_store_id
    collections = vector_store_collections(args.cell, vector_store_id)
    if not collections:
        raise TimeoutError(f"No Qdrant collections found for vector store {vector_store_id}.")
    before_counts = qdrant_vector_store_counts(args.cell, collections, vector_store_id)
    before_total = sum(before_counts.values())
    print(f"qdrant_counts_before_repair={json.dumps(before_counts, sort_keys=True)}")
    print(f"qdrant_total_before_repair={before_total}")

    if args.proof:
        delete_count = args.delete_count or args.batch_size + 1
        if delete_count <= args.batch_size:
            raise ValueError("--delete-count must exceed --batch-size in --proof mode.")
        selected_points = selected_point_rows(args.cell, vector_store_id, delete_count)
        if len(selected_points) <= args.batch_size:
            raise TimeoutError(
                f"Proof drift did not select more than one batch: selected={len(selected_points)} batch_size={args.batch_size}"
            )
        grouped = group_points_by_collection(selected_points)
        for collection, point_ids in grouped.items():
            qdrant_delete_points(args.cell, collection, point_ids)
        after_delete_counts = qdrant_vector_store_counts(args.cell, collections, vector_store_id)
        after_delete_total = sum(after_delete_counts.values())
        print(f"repair_all_deleted_points={len(selected_points)}")
        print(f"qdrant_counts_after_delete={json.dumps(after_delete_counts, sort_keys=True)}")
        print(f"qdrant_total_after_delete={after_delete_total}")
        if after_delete_total != before_total - len(selected_points):
            raise TimeoutError(
                f"Deliberate drift count mismatch: before={before_total} deleted={len(selected_points)} after={after_delete_total}"
            )

    iterations, total_processed = repair_all(args.cell, api, vector_store_id, args.batch_size, args.timeout_seconds)
    if args.proof and iterations < 2:
        raise TimeoutError(f"Repair-all did not prove multi-batch repair: iterations={iterations}")

    after_counts = qdrant_vector_store_counts(args.cell, collections, vector_store_id)
    after_total = sum(after_counts.values())
    print(f"qdrant_counts_after_repair_all={json.dumps(after_counts, sort_keys=True)}")
    print(f"qdrant_total_after_repair_all={after_total}")
    if args.proof and after_total != before_total:
        raise TimeoutError(f"Repair-all did not restore Qdrant point count: before={before_total} after={after_total}")

    if token and search_result_count(args.cell, api, vector_store_id, token) < 1:
        raise TimeoutError("Repair-all search returned no results.")

    final_counts = wait_for_vector_store(args.cell, vector_store_id, 1, args.timeout_seconds)
    print(f"repair_all_sql_counts_final={json.dumps(final_counts, sort_keys=True)}")
    if source_counts and final_counts != source_counts:
        raise TimeoutError(f"Repair-all SQL counts changed unexpectedly: source={source_counts} final={final_counts}")
    if total_processed < final_counts["active_chunks"]:
        raise TimeoutError(f"Repair-all processed fewer chunks than active SQL rows: processed={total_processed} sql={final_counts}")
    print("Qdrant repair-all complete.")
    print(f"VECTOR_STORE_ID={vector_store_id}")


if __name__ == "__main__":
    main()
