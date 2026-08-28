#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from topeka_pipeline_common import (
    DEFAULT_CELL,
    DEFAULT_KNOWLEDGE_BASE_ID,
    DEFAULT_VECTOR_STORE_NAME,
    ORDINANCE_SEED,
    default_api_base,
    default_headers,
    ensure_vector_store,
    public_url,
    read_jsonl,
    safe_filename,
    sha256_text,
    submit_document,
)


def markdown_candidates(row: dict[str, Any], manifest_path: Path, extracted_dir: Path | None) -> list[Path]:
    base = manifest_path.parent.parent if manifest_path.parent.name == "manifests" else manifest_path.parent
    candidates: list[Path] = []
    for key in ("markdown_path", "extracted_path", "saved_markdown_path"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value)
            candidates.append(path if path.is_absolute() else base / path)
    seed = extracted_dir or base / "extracted"
    for value in (row.get("id"), row.get("ordinance_number"), Path(str(row.get("saved_path") or "")).stem):
        if value:
            candidates.append(seed / safe_filename(str(value), suffix=".md"))
    return candidates


def find_markdown(row: dict[str, Any], manifest_path: Path, extracted_dir: Path | None = None) -> Path | None:
    for candidate in markdown_candidates(row, manifest_path, extracted_dir):
        if candidate.exists():
            return candidate
    return None


def ordinance_document_filename(row: dict[str, Any]) -> str:
    ordinance_number = str(row.get("ordinance_number") or "")
    category = str(row.get("category") or "")
    if category == "charter_ordinance" and ordinance_number:
        return safe_filename(f"CharterOrdinance{ordinance_number}", suffix=".md")
    saved_path = str(row.get("saved_path") or "")
    return safe_filename(ordinance_number or Path(saved_path).stem or str(row.get("title") or row.get("id") or "Topeka ordinance"), suffix=".md")


def build_payload(
    row: dict[str, Any],
    markdown: str,
    *,
    markdown_path: Path,
    vector_store_id: str,
    knowledge_base_id: str,
    security_level: int,
) -> dict[str, Any]:
    pdf_url = str(row.get("pdf_url") or "")
    if not public_url(pdf_url):
        raise ValueError(f"Ordinance {row.get('id')} does not have a public pdf_url")
    ordinance_number = str(row.get("ordinance_number") or "")
    source_record_id = str(row.get("id") or "")
    title = str(row.get("title") or ordinance_number or source_record_id or "Topeka ordinance")
    attributes = {
        "source_collection": "topeka-ordinances",
        "source_record_id": source_record_id,
        "jurisdiction": "City of Topeka, Kansas",
        "jurisdiction_id": row.get("jurisdiction_id") or "ks-topeka",
        "category": row.get("category") or "",
        "ordinance_number": ordinance_number,
        "title": title,
        "year": row.get("year") or "",
        "pdf_url": pdf_url,
        "citation_url": pdf_url,
        "saved_path": row.get("saved_path") or "",
        "markdown_path": str(markdown_path),
        "sha256": row.get("sha256") or "",
        "pdf_sha256": row.get("sha256") or "",
        "byte_count": row.get("byte_count") or 0,
        "retrieved_at": row.get("retrieved_at") or "",
        "extraction_parser": row.get("extraction_parser") or row.get("marker_parser") or "external_marker_or_operator",
        "extraction_source": "precomputed_markdown",
    }
    return {
        "vector_store_id": vector_store_id,
        "knowledge_base_id": knowledge_base_id,
        "title": title,
        "filename": ordinance_document_filename(row),
        "mime_type": "text/markdown",
        "content": markdown,
        "mode": "pdf_markdown_external_v1",
        "source_uri": pdf_url,
        "attributes": attributes,
        "security_level": security_level,
        "source_trust": "external_pdf_parser",
    }


def load_ordinance_payloads(
    manifest_path: Path,
    *,
    extracted_dir: Path | None,
    vector_store_id: str,
    knowledge_base_id: str,
    security_level: int,
    allow_missing_markdown: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    payloads: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row in read_jsonl(manifest_path):
        markdown_path = find_markdown(row, manifest_path, extracted_dir)
        if not markdown_path:
            skipped.append({"id": str(row.get("id") or ""), "reason": "missing_extracted_markdown"})
            continue
        markdown = markdown_path.read_text(encoding="utf-8").strip()
        if not markdown:
            skipped.append({"id": str(row.get("id") or ""), "reason": "empty_extracted_markdown"})
            continue
        payloads.append(build_payload(row, markdown, markdown_path=markdown_path, vector_store_id=vector_store_id, knowledge_base_id=knowledge_base_id, security_level=security_level))
    if skipped and not allow_missing_markdown:
        raise ValueError(
            "Missing extracted markdown for ordinance PDFs. Run the external RunPod Marker/operator extraction path first; "
            f"skipped={skipped[:5]}"
        )
    return payloads, skipped


def ingest_idempotency_key(payload: dict[str, Any]) -> str:
    fingerprint = {
        "vector_store_id": payload["vector_store_id"],
        "source_uri": payload["source_uri"],
        "title": payload["title"],
        "filename": payload["filename"],
        "attributes": payload["attributes"],
    }
    return "topeka-ordinance-ingest-" + sha256_text(json.dumps(fingerprint, sort_keys=True, separators=(",", ":")))[:48]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest Topeka ordinance PDFs using precomputed markdown. This script does not run Marker locally; "
            "hard PDFs must be converted by the external RunPod Marker/operator extraction path before ingestion."
        )
    )
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api", default=None)
    parser.add_argument("--manifest", type=Path, default=ORDINANCE_SEED / "manifests" / "ordinances.jsonl")
    parser.add_argument("--extracted-dir", type=Path, default=None)
    parser.add_argument("--vector-store-id")
    parser.add_argument("--vector-store-name", default=DEFAULT_VECTOR_STORE_NAME)
    parser.add_argument("--knowledge-base-id", default=DEFAULT_KNOWLEDGE_BASE_ID)
    parser.add_argument("--security-level", type=int, default=1)
    parser.add_argument("--allow-create-vector-store", action="store_true")
    parser.add_argument("--allow-missing-markdown", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--api-timeout-seconds", type=int, default=180)
    parser.add_argument("--auth-token-file", type=Path)
    parser.add_argument("--api-transport", default="auto", choices=["auto", "host-curl", "api-container", "docker-network"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_base = args.api or default_api_base(args.cell)
    headers = default_headers(cell=args.cell, auth_token_file=args.auth_token_file)
    vector_store_id = args.vector_store_id or "vs_topeka_municipal_code_pending"
    if not args.dry_run:
        vector_store_id = ensure_vector_store(
            api_base=api_base,
            headers=headers,
            vector_store_id=args.vector_store_id,
            vector_store_name=args.vector_store_name,
            knowledge_base_id=args.knowledge_base_id,
            allow_create=args.allow_create_vector_store,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
            transport=args.api_transport,
        )
    payloads, skipped = load_ordinance_payloads(
        args.manifest,
        extracted_dir=args.extracted_dir,
        vector_store_id=vector_store_id,
        knowledge_base_id=args.knowledge_base_id,
        security_level=args.security_level,
        allow_missing_markdown=args.allow_missing_markdown or args.dry_run,
    )
    if args.limit > 0:
        payloads = payloads[: args.limit]
    submitted: list[dict[str, Any]] = []
    if not args.dry_run:
        for payload in payloads:
            key = ingest_idempotency_key(payload)
            response = submit_document(
                api_base=api_base,
                headers=headers,
                payload=payload,
                idempotency_key=key,
                timeout=args.api_timeout_seconds,
                cell=args.cell,
                transport=args.api_transport,
            )
            submitted.append({"source_uri": payload["source_uri"], "response": response})
    result = {
        "dry_run": args.dry_run,
        "vector_store_id": vector_store_id,
        "manifest": str(args.manifest),
        "payload_count": len(payloads),
        "submitted_count": len(submitted),
        "skipped_count": len(skipped),
        "skipped": skipped[:10],
        "marker_note": "This script only consumes precomputed markdown; RunPod Marker/operator extraction remains external.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
