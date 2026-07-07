from __future__ import annotations

import argparse
import time
from pathlib import Path

from release_common import DEFAULT_CELL, api_base, ensure_env
from scale_common import api_json, chunk_vector_store_where, job_vector_store_where, parse_int_row, psql


def title_for(path: Path, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.stem
    return path.stem


def load_documents(root: Path, pattern: str, knowledge_base_id: str, force_async: bool) -> list[dict]:
    docs: list[dict] = []
    for path in sorted(root.rglob(pattern)):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        docs.append(
            {
                "title": title_for(path, content),
                "filename": rel,
                "mime_type": "text/markdown",
                "content": content,
                "mode": "markdown_docs_v1",
                "knowledge_base_id": knowledge_base_id,
                "security_level": 1,
                "attributes": {
                    "source_folder": root.as_posix(),
                    "source_path": rel,
                    "force_async": force_async,
                },
            }
        )
    return docs


def poll_counts(cell: str, vector_store_id: str, expected_docs: int, timeout_seconds: int) -> None:
    job_where = job_vector_store_where(vector_store_id)
    chunk_where = chunk_vector_store_where(vector_store_id)
    deadline = time.time() + timeout_seconds
    last_counts = ""
    while time.time() < deadline:
        last_counts = psql(
            cell,
            f"""
SELECT status, count(*) FROM ingestion_jobs WHERE {job_where} GROUP BY status ORDER BY status;
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed') AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running')) AS active_jobs,
  (SELECT count(*) FROM documents WHERE vector_store_id={chunk_where.removeprefix('vector_store_id = ')}) AS documents,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true) AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed') AS indexed_chunks;
""",
        )
        rows = psql(
            cell,
            f"""
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed')::int AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running'))::int AS active_jobs,
  (SELECT count(*) FROM documents WHERE vector_store_id={chunk_where.removeprefix('vector_store_id = ')})::int AS documents,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true)::int AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed')::int AS indexed_chunks;
""",
            tuples_only=True,
        )
        fields = parse_int_row(rows)
        if len(fields) == 5:
            failed_jobs, active_jobs, documents, active_chunks, indexed_chunks = fields
            if failed_jobs == 0 and active_jobs == 0 and documents >= expected_docs and active_chunks == indexed_chunks and indexed_chunks > 0:
                print("Folder vectorization complete.")
                return
        time.sleep(5)
    print(last_counts)
    raise TimeoutError("Folder vectorization did not complete before timeout.")


def print_embedding_provider_counts(cell: str, vector_store_id: str) -> None:
    chunk_where = chunk_vector_store_where(vector_store_id)
    psql(
        cell,
        f"""
SELECT e.embedding_profile_id, e.model_provider, e.model_name, e.dimensions, count(*)
FROM embeddings e
JOIN chunks c
  ON c.id=e.chunk_id
 AND c.tenant_id=e.tenant_id
 AND c.business_instance_id=e.business_instance_id
WHERE {chunk_where} AND c.active=true
GROUP BY 1,2,3,4
ORDER BY 5 DESC, 1,2,3,4;
""",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Vectorize a local Markdown folder through the real cell API and print SQL proof.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--pattern", default="*.md")
    parser.add_argument("--knowledge-base-id", default="kb_dev")
    parser.add_argument("--name", default=None)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--force-sync", action="store_true")
    args = parser.parse_args()
    ensure_env(args.cell)
    folder = args.folder.resolve()
    docs = load_documents(folder, args.pattern, args.knowledge_base_id, not args.force_sync)
    if not docs:
        raise ValueError(f"No files matched {args.pattern} under {folder}")

    api = api_base(args.cell)
    store = api_json(
        "POST",
        f"{api}/v1/vector_stores",
        {"name": args.name or f"Folder Vectorization {folder.name} {int(time.time())}", "knowledge_base_id": args.knowledge_base_id},
        cell=args.cell,
    )
    vector_store_id = store["id"]
    print(f"FOLDER={folder}")
    print(f"FILES={len(docs)}")
    print(f"VECTOR_STORE_ID={vector_store_id}")

    for start in range(0, len(docs), args.batch_size):
        batch = docs[start : start + args.batch_size]
        api_json("POST", f"{api}/v1/vector_stores/{vector_store_id}/file_batches", {"files": batch}, timeout=300, cell=args.cell)
        print(f"Submitted files: {min(start + len(batch), len(docs))}/{len(docs)}")

    poll_counts(args.cell, vector_store_id, len(docs), args.timeout_seconds)
    print(f"VECTOR_STORE_ID={vector_store_id}")
    print_embedding_provider_counts(args.cell, vector_store_id)


if __name__ == "__main__":
    main()
