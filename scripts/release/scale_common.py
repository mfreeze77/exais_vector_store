from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from release_common import DEFAULT_CELL, compose_base, compose_network_name, run


def api_json(method: str, url: str, payload: dict | None = None, timeout: int = 120, *, cell: str = DEFAULT_CELL) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            print(f"{method} {url} -> {resp.status}")
            if raw:
                print(raw[:1000])
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        print(f"{method} {url} -> {exc.code}")
        print(raw)
        raise
    except urllib.error.URLError as exc:
        print(f"{method} {url} -> host request failed: {exc}")
        return api_json_via_cell_network(method, url, body, timeout, cell=cell)


def api_json_via_cell_network(method: str, url: str, body: bytes | None, timeout: int, *, cell: str = DEFAULT_CELL) -> dict:
    parts = urlsplit(url)
    cell_url = urlunsplit((parts.scheme, "api:8080", parts.path, parts.query, parts.fragment))
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        compose_network_name(cell),
        "curlimages/curl:8.10.1",
        "-fsS",
        "-w",
        "\n%{http_code}\n",
        "-X",
        method,
        "-H",
        "Content-Type: application/json",
    ]
    if body is not None:
        args += ["--data-binary", "@-"]
    args.append(cell_url)
    print("$ " + " ".join(args))
    proc = subprocess.run(
        args,
        input=body or b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = (proc.stdout or b"").decode("utf-8", errors="replace")
    print(output, end="" if output.endswith("\n") else "\n")
    print(f"[exit {proc.returncode}]")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, output)
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    print(f"{method} {cell_url} -> {status}")
    return json.loads(raw) if raw else {}


def scale_doc(index: int, headings: int) -> dict:
    sections = []
    for h in range(headings):
        sections.append(
            "\n".join(
                [
                    f"## Scale Section {h + 1}",
                    f"Document {index} section {h + 1} proves queue ingestion, dense qdrant indexing, postgres sparse search, and hybrid retrieval.",
                    f"Unique terms: exais-scale-{index} qdrant-proof-{h} repairable-index-state docker-cell.",
                ]
            )
        )
    content = f"# ExAIS Scale Proof {index}\n" + "\n\n".join(sections)
    return {
        "title": f"ExAIS Scale Proof {index}",
        "filename": f"scale-proof-{index}.md",
        "mime_type": "text/markdown",
        "content": content,
        "mode": "markdown_docs_v1",
        "knowledge_base_id": "kb_dev",
        "security_level": 1,
        "attributes": {"scale_gate": True, "force_async": True, "doc_index": index},
    }


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def job_vector_store_where(vector_store_id: str) -> str:
    return f"COALESCE(payload->'document'->>'vector_store_id', payload->>'vector_store_id') = {sql_literal(vector_store_id)}"


def chunk_vector_store_where(vector_store_id: str) -> str:
    return f"vector_store_id = {sql_literal(vector_store_id)}"


def parse_int_row(output: str) -> list[int]:
    for line in reversed(output.strip().splitlines()):
        fields = [part.strip() for part in line.split("|")]
        if fields and all(re.fullmatch(r"-?\d+", field) for field in fields):
            return [int(field) for field in fields]
    return []


def psql(cell: str, sql: str, *, tuples_only: bool = False) -> str:
    flags = ["-At"] if tuples_only else []
    proc = run(compose_base(cell) + ["exec", "-T", "postgres", "psql", *flags, "-U", "svs_owner", "-d", "svs", "-v", "ON_ERROR_STOP=1", "-c", sql])
    return proc.stdout or ""
