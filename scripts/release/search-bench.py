from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
import urllib.request

DEFAULT_CELL = "local"


def post_json(url: str, payload: dict, timeout: int = 60) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return elapsed_ms, json.loads(raw)


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run hybrid search latency proof against the cell API.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--vector-store-id", required=True)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--p95-ms", type=int, default=500)
    parser.add_argument("--inside-container", action="store_true")
    args = parser.parse_args()
    api = args.api_base or "http://localhost:18080"
    if not args.inside_container:
        try:
            with urllib.request.urlopen(f"{api}/readyz", timeout=5) as resp:
                print(f"readyz probe {api}/readyz -> {resp.status}")
        except URLError as exc:
            print(f"Host loopback benchmark probe failed: {exc}")
            script = Path(__file__).read_text(encoding="utf-8")
            cmd = [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "exais-vector-store-local_default",
                "python:3.12-slim",
                "python",
                "-",
                "--inside-container",
                "--api-base",
                "http://api:8080",
                "--vector-store-id",
                args.vector_store_id,
                "--queries",
                str(args.queries),
                "--p95-ms",
                str(args.p95_ms),
            ]
            print("$ " + " ".join(cmd))
            proc = subprocess.run(cmd, input=script.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = (proc.stdout or b"").decode("utf-8", errors="replace")
            print(output, end="" if output.endswith("\n") else "\n")
            print(f"[exit {proc.returncode}]")
            if proc.returncode != 0:
                raise SystemExit(proc.returncode)
            return
    latencies: list[int] = []
    errors = 0
    for i in range(args.queries):
        query = f"qdrant proof repairable index state document {i % 100}"
        try:
            elapsed_ms, body = post_json(
                f"{api}/api/v1/retrieval/search",
                {
                    "vector_store_id": args.vector_store_id,
                    "query": query,
                    "top_k": 5,
                    "mode": "markdown_docs_v1",
                },
            )
            result_count = len(body.get("results", []))
            latencies.append(elapsed_ms)
            print(f"search {i + 1}/{args.queries}: {elapsed_ms}ms results={result_count}")
        except Exception as exc:
            errors += 1
            print(f"search {i + 1}/{args.queries}: ERROR {type(exc).__name__}: {exc}")
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    avg = int(statistics.mean(latencies)) if latencies else 0
    print(f"queries={args.queries}")
    print(f"errors={errors}")
    print(f"p50_ms={p50}")
    print(f"p95_ms={p95}")
    print(f"avg_ms={avg}")
    if errors or p95 > args.p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
