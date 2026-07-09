from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from release_common import (
    DEFAULT_REGISTRY_PREFIX,
    ROOT,
    api_base,
    compose_base,
    compose_network_name,
    env_file,
    printable_command,
    project_name,
    release_dir,
    run,
    wait_for_services,
)
from backup_common import BackupArtifact, sha256_file, write_backup_manifest as write_shared_backup_manifest
from scale_common import api_json, chunk_vector_store_where, job_vector_store_where, parse_int_row, psql


CORE_SERVICES = ["postgres", "redis", "qdrant", "minio", "model-gateway", "api", "worker", "admin-ui"]
INFRA_SERVICES = ["postgres", "redis", "qdrant", "minio"]
APP_SERVICES = ["model-gateway", "api", "worker", "admin-ui"]


def load_env_generator():
    path = Path(__file__).with_name("generate-cell-env.py")
    spec = importlib.util.spec_from_file_location("generate_cell_env", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def drill_env_values(cell: str, registry_prefix: str, port_base: int) -> dict[str, str]:
    generator = load_env_generator()
    values = generator.build_env(cell, registry_prefix, port_base)
    values.update(
        {
            "SVS_API_PORT": str(port_base),
            "SVS_MODEL_GATEWAY_PORT": str(port_base + 1),
            "SVS_ADMIN_UI_PORT": str(port_base + 2),
            "SVS_INSTANCE_AGENT_PORT": str(port_base + 3),
            "SVS_POSTGRES_PORT": str(port_base + 4),
            "SVS_REDIS_PORT": str(port_base + 5),
            "SVS_QDRANT_HTTP_PORT": str(port_base + 6),
            "SVS_QDRANT_GRPC_PORT": str(port_base + 7),
            "SVS_MINIO_PORT": str(port_base + 8),
            "SVS_MINIO_CONSOLE_PORT": str(port_base + 9),
            "SVS_ALLOWED_CORS_ORIGINS": f"http://localhost:{port_base + 2},http://localhost:{port_base}",
            "SVS_PUBLIC_API_BASE": f"http://localhost:{port_base}",
        }
    )
    return values


def write_drill_env(cell: str, registry_prefix: str, port_base: int) -> None:
    generator = load_env_generator()
    target = env_file(cell)
    generator.write_env(target, drill_env_values(cell, registry_prefix, port_base))
    print(f"Generated restore-drill env file: {target}")
    print("Variable names written:")
    for key in sorted(drill_env_values(cell, registry_prefix, port_base)):
        print(f"- {key}")
    print("No values printed.")


def curl_json_on_cell_network(cell: str, method: str, url: str, payload: dict | None = None, timeout: int = 120) -> tuple[int, dict]:
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
    body = ""
    if payload is not None:
        body = json.dumps(payload)
        args += ["--data-binary", "@-"]
    args.append(cell_url)
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
        raise subprocess.CalledProcessError(proc.returncode, args, output)
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    return status, json.loads(raw) if raw else {}


def qdrant_json(cell: str, method: str, path: str, payload: dict | None = None, timeout: int = 120) -> tuple[int, dict]:
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
        raise subprocess.CalledProcessError(proc.returncode, args, output)
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    if status >= 400:
        raise RuntimeError(f"Qdrant {method} {path} returned HTTP {status}: {raw}")
    return status, json.loads(raw) if raw else {}


def qdrant_vector_store_count(cell: str, collection: str, vector_store_id: str) -> int:
    _, body = qdrant_json(
        cell,
        "POST",
        f"/collections/{collection}/points/count",
        {"filter": {"must": [{"key": "vector_store_id", "match": {"value": vector_store_id}}]}, "exact": True},
    )
    return int((body.get("result") or {}).get("count") or 0)


def restore_doc(index: int, headings: int, token: str) -> dict:
    sections = []
    for heading in range(headings):
        sections.append(
            "\n".join(
                [
                    f"## Restore Section {heading + 1}",
                    f"Document {index} proves local restore drill search and rebuilt qdrant points.",
                    f"Unique restore token: {token} restore-proof-{index}-{heading}.",
                ]
            )
        )
    return {
        "title": f"ExAIS Restore Drill {index}",
        "filename": f"restore-drill-{index}.md",
        "mime_type": "text/markdown",
        "content": f"# ExAIS Restore Drill {index}\n" + "\n\n".join(sections),
        "mode": "markdown_docs_v1",
        "knowledge_base_id": "kb_dev",
        "security_level": 1,
        "attributes": {"restore_drill": True, "force_async": True, "doc_index": index},
    }


def boot_clean_cell(cell: str, worker_scale: int, timeout_seconds: int) -> None:
    base = compose_base(cell)
    run(base + ["down", "--volumes"], check=False)
    run(base + ["pull", *CORE_SERVICES])
    run(base + ["up", "-d", "--pull", "always", "--scale", f"worker={worker_scale}", *CORE_SERVICES])
    wait_for_services(cell, CORE_SERVICES, timeout_seconds)
    run(base + ["ps"])


def boot_restore_infra(cell: str, timeout_seconds: int) -> None:
    base = compose_base(cell)
    run(base + ["down", "--volumes"], check=False)
    run(base + ["pull", *CORE_SERVICES])
    run(base + ["up", "-d", "--pull", "always", *INFRA_SERVICES])
    wait_for_services(cell, INFRA_SERVICES, timeout_seconds)


def boot_restore_apps(cell: str, worker_scale: int, timeout_seconds: int) -> None:
    base = compose_base(cell)
    run(base + ["up", "-d", "--pull", "always", "--scale", f"worker={worker_scale}", *APP_SERVICES])
    wait_for_services(cell, CORE_SERVICES, timeout_seconds)
    run(base + ["ps"])


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
    return [line.strip() for line in output.splitlines() if line.strip() and not line.startswith("$") and not line.startswith("[exit")]


def backup_postgres(source_cell: str, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dump_path = backup_dir / "svs.dump"
    source_postgres = f"{project_name(source_cell)}-postgres-1"
    run(["docker", "exec", source_postgres, "pg_dump", "-U", "svs_owner", "-d", "svs", "--format=custom", "--file=/tmp/svs.restore-drill.dump"])
    run(["docker", "cp", f"{source_postgres}:/tmp/svs.restore-drill.dump", str(dump_path)])
    run(["docker", "exec", source_postgres, "rm", "-f", "/tmp/svs.restore-drill.dump"])
    print(f"BACKUP_ARTIFACT={dump_path}")
    return dump_path


def restore_postgres(restore_cell: str, dump_path: Path) -> None:
    restore_postgres_container = f"{project_name(restore_cell)}-postgres-1"
    run(["docker", "cp", str(dump_path), f"{restore_postgres_container}:/tmp/svs.restore-drill.dump"])
    run([
        "docker",
        "exec",
        restore_postgres_container,
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "-U",
        "svs_owner",
        "-d",
        "svs",
        "/tmp/svs.restore-drill.dump",
    ])
    run(["docker", "exec", restore_postgres_container, "rm", "-f", "/tmp/svs.restore-drill.dump"])


def write_json_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_restore_drill_marker(path: Path, kind: str, message: str, data: dict | None = None) -> None:
    payload = {
        "kind": kind,
        "capture_status": "restore_drill_marker",
        "message": message,
        "generated_at": int(time.time()),
    }
    if data:
        payload["metadata"] = data
    write_json_file(path, payload)


def write_restore_drill_checksums(path: Path) -> Path:
    checksum_path = path / "CHECKSUMS.sha256"
    files = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.name not in {"CHECKSUMS.sha256", "manifest.json"}
    )
    lines = [f"{sha256_file(candidate)}  ./{candidate.relative_to(path).as_posix()}\n" for candidate in files]
    checksum_path.write_text("".join(lines), encoding="utf-8")
    return checksum_path


def write_backup_manifest(path: Path, data: dict) -> None:
    manifest = path / "restore-drill-manifest.json"
    write_json_file(manifest, data)
    print(f"BACKUP_MANIFEST={manifest}")

    write_restore_drill_marker(
        path / "qdrant" / "rebuild-marker.json",
        "qdrant_vectors",
        "Local restore drill rebuilds Qdrant vectors from restored Postgres metadata through the maintenance reindex path.",
        {"collections": data.get("collections", [])},
    )
    write_restore_drill_marker(
        path / "opensearch" / "rebuild-marker.json",
        "opensearch_sparse",
        "Local restore drill rebuilds sparse indexes from restored Postgres metadata through the maintenance reindex path.",
    )
    write_restore_drill_marker(
        path / "object-store" / "restore-drill-object-marker.json",
        "object_store",
        "Local restore drill fixture stores source documents through API ingestion and validates restored retrieval, not an external object-store copy.",
    )
    write_restore_drill_marker(
        path / "config" / "restore-drill-config.json",
        "config_metadata",
        "Restore drill config metadata is represented by source/restore cell names and generated env file paths; secret values are not printed.",
        {"source_cell": data.get("source_cell"), "restore_cell": data.get("restore_cell")},
    )
    write_restore_drill_marker(
        path / "audit" / "restore-drill-audit-marker.json",
        "audit_export",
        "Local restore drill does not claim immutable external audit export proof.",
    )
    write_restore_drill_checksums(path)
    shared_manifest = write_shared_backup_manifest(
        path,
        [
            BackupArtifact(
                kind="postgres_metadata",
                relative_path="svs.dump",
                required=True,
                source="local_restore_drill_pg_dump",
                notes="Postgres metadata dump used by the local restore drill.",
                metadata={"capture_status": "captured"},
            ),
            BackupArtifact(
                kind="qdrant_vectors",
                relative_path="qdrant/rebuild-marker.json",
                required=True,
                source="maintenance_reindex_marker",
                notes="Vector indexes are rebuilt during the local restore drill.",
                metadata={"capture_status": "restore_drill_marker"},
            ),
            BackupArtifact(
                kind="opensearch_sparse",
                relative_path="opensearch/rebuild-marker.json",
                required=True,
                source="maintenance_reindex_marker",
                notes="Sparse indexes are rebuilt during the local restore drill.",
                metadata={"capture_status": "restore_drill_marker"},
            ),
            BackupArtifact(
                kind="object_store",
                relative_path="object-store/restore-drill-object-marker.json",
                required=True,
                source="restore_drill_marker",
                notes="Object-store proof remains external to the local restore drill.",
                metadata={"capture_status": "restore_drill_marker"},
            ),
            BackupArtifact(
                kind="config_metadata",
                relative_path="config/restore-drill-config.json",
                required=True,
                source="restore_drill_config_marker",
                notes="Restore drill config marker contains no secret values.",
                metadata={"capture_status": "restore_drill_marker"},
            ),
            BackupArtifact(
                kind="audit_export",
                relative_path="audit/restore-drill-audit-marker.json",
                required=True,
                source="restore_drill_marker",
                notes="External immutable audit export proof remains a later operator gate.",
                metadata={"capture_status": "restore_drill_marker"},
            ),
            BackupArtifact(
                kind="checksum_metadata",
                relative_path="CHECKSUMS.sha256",
                required=True,
                source="python_sha256",
                notes="Checksum metadata for restore drill backup files.",
                metadata={"capture_status": "captured"},
            ),
        ],
    )
    print(f"BACKUP_SHARED_MANIFEST={shared_manifest}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prove a local backup/restore drill with a rebuilt Qdrant index.")
    parser.add_argument("--source-cell", default="restore-src")
    parser.add_argument("--restore-cell", default="restore")
    parser.add_argument("--registry-prefix", default=DEFAULT_REGISTRY_PREFIX)
    parser.add_argument("--source-port-base", type=int, default=28080)
    parser.add_argument("--restore-port-base", type=int, default=28180)
    parser.add_argument("--documents", type=int, default=20)
    parser.add_argument("--headings-per-doc", type=int, default=3)
    parser.add_argument("--worker-scale", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--keep-cells", action="store_true")
    args = parser.parse_args()
    if args.source_cell == args.restore_cell:
        raise ValueError("--source-cell and --restore-cell must be distinct.")
    if abs(args.source_port_base - args.restore_port_base) < 20:
        raise ValueError("source and restore port bases must be at least 20 apart.")

    write_drill_env(args.source_cell, args.registry_prefix, args.source_port_base)
    write_drill_env(args.restore_cell, args.registry_prefix, args.restore_port_base)

    token = f"restore-drill-{int(time.time())}"
    expected_min_chunks = args.documents * args.headings_per_doc
    backup_dir = release_dir(args.restore_cell) / "restore-drill-backup"

    try:
        boot_clean_cell(args.source_cell, args.worker_scale, args.timeout_seconds)
        source_api = api_base(args.source_cell)
        store = api_json("POST", f"{source_api}/v1/vector_stores", {"name": f"Restore Drill {token}", "knowledge_base_id": "kb_dev"}, cell=args.source_cell)
        vector_store_id = store["id"]
        print(f"VECTOR_STORE_ID={vector_store_id}")
        files = [restore_doc(i, args.headings_per_doc, token) for i in range(args.documents)]
        api_json("POST", f"{source_api}/v1/vector_stores/{vector_store_id}/file_batches", {"files": files}, timeout=300, cell=args.source_cell)
        source_counts = wait_for_vector_store(args.source_cell, vector_store_id, expected_min_chunks, args.timeout_seconds)
        source_collections = vector_store_collections(args.source_cell, vector_store_id)
        source_qdrant_count = sum(qdrant_vector_store_count(args.source_cell, collection, vector_store_id) for collection in source_collections)
        print(f"source_sql_counts={json.dumps(source_counts, sort_keys=True)}")
        print(f"source_qdrant_count={source_qdrant_count}")

        dump_path = backup_postgres(args.source_cell, backup_dir)
        write_backup_manifest(
            backup_dir,
            {
                "source_cell": args.source_cell,
                "restore_cell": args.restore_cell,
                "vector_store_id": vector_store_id,
                "source_sql_counts": source_counts,
                "source_qdrant_count": source_qdrant_count,
                "collections": source_collections,
            },
        )

        boot_restore_infra(args.restore_cell, args.timeout_seconds)
        restore_postgres(args.restore_cell, dump_path)
        boot_restore_apps(args.restore_cell, args.worker_scale, args.timeout_seconds)
        restore_api = api_base(args.restore_cell)
        ready_status, ready_body = curl_json_on_cell_network(args.restore_cell, "GET", f"{restore_api}/readyz")
        print(f"restore_readyz={json.dumps(ready_body, sort_keys=True)}")
        print(f"restore_readyz_status={ready_status}")
        if ready_status != 200 or not ready_body.get("ready"):
            raise TimeoutError(f"Restore cell did not become ready: status={ready_status} body={ready_body}")

        restore_counts_before_reindex = wait_for_vector_store(args.restore_cell, vector_store_id, expected_min_chunks, args.timeout_seconds)
        print(f"restore_sql_counts_before_reindex={json.dumps(restore_counts_before_reindex, sort_keys=True)}")
        repair = api_json(
            "POST",
            f"{restore_api}/api/v1/maintenance/reindex",
            {"vector_store_id": vector_store_id, "batch_size": 1000, "force": True},
            timeout=300,
            cell=args.restore_cell,
        )
        print(f"restore_reindex_response={json.dumps(repair, sort_keys=True)}")
        if int(repair.get("processed") or 0) < source_counts["active_chunks"]:
            raise TimeoutError(f"Restore reindex processed too few chunks: {repair}")
        restore_collections = vector_store_collections(args.restore_cell, vector_store_id)
        restore_qdrant_count = sum(qdrant_vector_store_count(args.restore_cell, collection, vector_store_id) for collection in restore_collections)
        print(f"restore_qdrant_count={restore_qdrant_count}")
        if restore_qdrant_count != source_qdrant_count:
            raise TimeoutError(f"Restored Qdrant count mismatch: source={source_qdrant_count} restore={restore_qdrant_count}")

        search = api_json(
            "POST",
            f"{restore_api}/v1/vector_stores/{vector_store_id}/search",
            {"query": token, "top_k": 5, "include_content": True},
            timeout=120,
            cell=args.restore_cell,
        )
        result_count = len(search.get("data") or [])
        print(f"restore_search_results={result_count}")
        if result_count < 1:
            raise TimeoutError("Restore search returned no results.")

        final_counts = wait_for_vector_store(args.restore_cell, vector_store_id, expected_min_chunks, args.timeout_seconds)
        if final_counts != source_counts:
            raise TimeoutError(f"Restored SQL counts mismatch: source={source_counts} restore={final_counts}")
        print(f"restore_sql_counts_final={json.dumps(final_counts, sort_keys=True)}")
        print("Local restore drill complete.")
        print(f"VECTOR_STORE_ID={vector_store_id}")
    finally:
        if not args.keep_cells:
            run(compose_base(args.source_cell) + ["down", "--volumes"], check=False)
            run(compose_base(args.restore_cell) + ["down", "--volumes"], check=False)


if __name__ == "__main__":
    main()
