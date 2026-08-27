from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib import error, request

import psycopg


DEFAULT_VECTOR_STORE_ID = "vs_a0d3ac76893e4f6f83bf2992"
DEFAULT_TENANT_ID = "ten_ks_state_civics"
DEFAULT_BUSINESS_INSTANCE_ID = "biz_ks_state_civics"
DEFAULT_USER_ID = "usr_ks_state_civics_admin"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Kansas court decision title+docket recall.")
    parser.add_argument("--api", default=os.getenv("SVS_RECALL_API", "http://127.0.0.1:8080"))
    parser.add_argument("--vector-store-id", default=os.getenv("SVS_KSCOURTS_VECTOR_STORE_ID", DEFAULT_VECTOR_STORE_ID))
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--tenant-id", default=os.getenv("SVS_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--business-instance-id", default=os.getenv("SVS_BUSINESS_INSTANCE_ID", DEFAULT_BUSINESS_INSTANCE_ID))
    parser.add_argument("--user-id", default=os.getenv("SVS_USER_ID", DEFAULT_USER_ID))
    parser.add_argument("--roles", default="admin")
    parser.add_argument("--max-security-level", default="9")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def normalize_conninfo() -> str:
    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        conninfo = "postgresql://svs_app:svs_app_dev_password@postgres:5432/svs"
    return conninfo.replace("postgresql+psycopg://", "postgresql://")


def post_json(api: str, headers: dict[str, str], path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(f"{api.rstrip('/')}{path}", data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {response_body}") from exc


def sample_cases(args: argparse.Namespace) -> list[tuple[str, str, str, str | None, str | None, str | None, str | None]]:
    with psycopg.connect(normalize_conninfo()) as conn:
        conn.execute("select set_config('svs.tenant_id', %s, true)", (args.tenant_id,))
        conn.execute("select set_config('svs.business_instance_id', %s, true)", (args.business_instance_id,))
        conn.execute("select set_config('svs.max_security_level', %s, true)", (str(args.max_security_level),))
        return conn.execute(
            """
            select document_id,
                   attributes->>'title' as title,
                   attributes->>'docket_number' as docket_number,
                   attributes->>'court' as court,
                   attributes->>'status' as status,
                   attributes->>'decision_year' as decision_year,
                   attributes->>'source_pdf_filename' as source_pdf_filename
            from vector_store_files
            where vector_store_id = %s
              and status = 'completed'
              and attributes ? 'docket_number'
              and attributes ? 'title'
            order by md5(document_id)
            limit %s
            """,
            (args.vector_store_id, args.limit),
        ).fetchall()


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "x-svs-tenant-id": args.tenant_id,
        "x-svs-business-instance-id": args.business_instance_id,
        "x-svs-user-id": args.user_id,
        "x-svs-roles": args.roles,
        "x-svs-max-security-level": str(args.max_security_level),
    }
    rows = sample_cases(args)
    stats = {
        "cases": 0,
        "title_docket_recall_at_1": 0,
        "title_docket_recall_at_3": 0,
        "title_docket_recall_at_10": 0,
    }
    misses: list[dict[str, Any]] = []
    metadata_samples: list[dict[str, Any]] = []
    latencies: list[float] = []

    for document_id, title, docket, court, status, year, filename in rows:
        query = f"{title} docket {docket}"
        started = time.perf_counter()
        page = post_json(
            args.api,
            headers,
            f"/v1/vector_stores/{args.vector_store_id}/search",
            {"query": query, "max_num_results": 10, "include_metadata": True},
        )
        latencies.append((time.perf_counter() - started) * 1000)
        file_ids = [item.get("file_id") for item in page.get("data", [])]

        stats["cases"] += 1
        if document_id in file_ids[:1]:
            stats["title_docket_recall_at_1"] += 1
        if document_id in file_ids[:3]:
            stats["title_docket_recall_at_3"] += 1
        if document_id in file_ids[:10]:
            stats["title_docket_recall_at_10"] += 1
        if len(metadata_samples) < 3:
            metadata_samples.append({
                "query": query,
                "search_query": page.get("search_query"),
                "expected": document_id,
                "top_file_ids": file_ids[:3],
            })
        if document_id not in file_ids[:3] and len(misses) < 10:
            misses.append({
                "query": query,
                "expected": document_id,
                "top_file_ids": file_ids[:3],
                "filename": filename,
                "court": court,
                "status": status,
                "year": year,
            })

    if stats["cases"] == 0:
        raise SystemExit("No completed Kansas court decision files matched the eval sample query.")

    latencies_sorted = sorted(latencies)
    p95_index = max(0, int(len(latencies_sorted) * 0.95) - 1)
    return {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "vector_store_id": args.vector_store_id,
        "planner_profile": os.getenv("SVS_QUERY_PLANNER_PROFILE_ID"),
        "sample_order": f"order by md5(document_id) limit {args.limit}",
        "stats": stats,
        "rates": {
            key: (value / stats["cases"] if key != "cases" else value)
            for key, value in stats.items()
        },
        "p95_ms": round(latencies_sorted[p95_index], 3),
        "metadata_samples": metadata_samples,
        "misses": misses,
    }


def main() -> None:
    args = parse_args()
    result = evaluate(args)
    output = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
