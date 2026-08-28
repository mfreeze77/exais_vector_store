#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from topeka_pipeline_common import (
    CODIFIED_SEED,
    DEFAULT_CELL,
    DEFAULT_KNOWLEDGE_BASE_ID,
    DEFAULT_VECTOR_STORE_NAME,
    citation_map_by_id,
    default_api_base,
    default_headers,
    ensure_vector_store,
    public_url,
    read_jsonl,
    safe_filename,
    sha256_text,
    submit_document,
)


def section_markdown(row: dict[str, Any]) -> str:
    title = " ".join(str(part or "").strip() for part in [row.get("citation"), row.get("title")] if str(part or "").strip())
    text = str(row.get("text") or "").strip()
    return f"# {title}\n\n{text}\n".strip() + "\n"


def build_payload(row: dict[str, Any], citation_row: dict[str, Any], *, vector_store_id: str, knowledge_base_id: str, security_level: int) -> dict[str, Any]:
    citation_url = str(citation_row.get("citation_url") or citation_row.get("source_url") or row.get("source_url") or "")
    if not public_url(citation_url):
        raise ValueError(f"Section {row.get('id')} does not have a public citation_url/source_url")
    version = row.get("version") if isinstance(row.get("version"), dict) else {}
    citation = str(row.get("citation") or citation_row.get("citation") or row.get("id") or "")
    title = str(row.get("title") or citation_row.get("title") or citation)
    content_hash = str(row.get("content_hash") or citation_row.get("content_hash") or sha256_text(section_markdown(row)))
    attributes = {
        "source_collection": "topeka-codified-code",
        "jurisdiction": "City of Topeka, Kansas",
        "jurisdiction_id": row.get("jurisdiction_id") or "ks-topeka",
        "code": row.get("code") or "TMC",
        "citation": citation,
        "title": title,
        "section_id": row.get("id") or "",
        "source_url": row.get("source_url") or citation_url,
        "citation_url": citation_url,
        "content_hash": content_hash,
        "source_html_hash": row.get("source_html_hash") or citation_row.get("source_html_hash") or "",
        "version_ordinance": version.get("ordinance") or "",
        "version_passed_date": version.get("passed_date") or "",
        "retrieved_at": row.get("retrieved_at") or citation_row.get("retrieved_at") or "",
    }
    return {
        "vector_store_id": vector_store_id,
        "knowledge_base_id": knowledge_base_id,
        "title": f"{citation} {title}".strip(),
        "filename": safe_filename(f"TMC-{citation}", suffix=".md"),
        "mime_type": "text/markdown",
        "content": section_markdown(row),
        "mode": "markdown_docs_v1",
        "source_uri": citation_url,
        "attributes": attributes,
        "security_level": security_level,
        "source_trust": "official_public_code",
    }


def load_section_payloads(source_output: Path, *, vector_store_id: str, knowledge_base_id: str, security_level: int) -> list[dict[str, Any]]:
    sections = read_jsonl(source_output / "sections.jsonl")
    citations = citation_map_by_id(source_output / "citation-url-map.jsonl")
    payloads: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in sections:
        section_id = str(row.get("id") or "")
        citation_row = citations.get(section_id)
        if not citation_row:
            missing.append(section_id or "<missing id>")
            continue
        payloads.append(build_payload(row, citation_row, vector_store_id=vector_store_id, knowledge_base_id=knowledge_base_id, security_level=security_level))
    if missing:
        raise ValueError(f"citation-url-map.jsonl is missing section rows for {len(missing)} sections: {missing[:5]}")
    return payloads


def ingest_idempotency_key(payload: dict[str, Any]) -> str:
    return "topeka-code-ingest-" + sha256_text(
        f"{payload['vector_store_id']}|{payload['source_uri']}|{payload['attributes']['content_hash']}"
    )[:48]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Topeka codified-code sections through the ExAIS API.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api", default=None)
    parser.add_argument("--source-output", type=Path, default=CODIFIED_SEED)
    parser.add_argument("--vector-store-id")
    parser.add_argument("--vector-store-name", default=DEFAULT_VECTOR_STORE_NAME)
    parser.add_argument("--knowledge-base-id", default=DEFAULT_KNOWLEDGE_BASE_ID)
    parser.add_argument("--security-level", type=int, default=1)
    parser.add_argument("--allow-create-vector-store", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--api-timeout-seconds", type=int, default=180)
    parser.add_argument("--submit-max-attempts", type=int, default=3)
    parser.add_argument("--submit-retry-delay-seconds", type=float, default=2.0)
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
    payloads = load_section_payloads(
        args.source_output,
        vector_store_id=vector_store_id,
        knowledge_base_id=args.knowledge_base_id,
        security_level=args.security_level,
    )
    if args.limit > 0:
        payloads = payloads[: args.limit]
    submitted: list[dict[str, Any]] = []
    if not args.dry_run:
        for payload in payloads:
            key = ingest_idempotency_key(payload)
            response = None
            for attempt in range(1, max(args.submit_max_attempts, 1) + 1):
                try:
                    response = submit_document(
                        api_base=api_base,
                        headers=headers,
                        payload=payload,
                        idempotency_key=key,
                        timeout=args.api_timeout_seconds,
                        cell=args.cell,
                        transport=args.api_transport,
                    )
                    break
                except Exception as exc:
                    if attempt >= max(args.submit_max_attempts, 1):
                        raise
                    print(json.dumps({
                        "event": "topeka_ingest_retry",
                        "attempt": attempt + 1,
                        "source_uri": payload["source_uri"],
                        "error": str(exc)[:500],
                    }, sort_keys=True), flush=True)
                    time.sleep(max(args.submit_retry_delay_seconds, 0.0) * attempt)
            submitted.append({"source_uri": payload["source_uri"], "response": response})
    result = {
        "dry_run": args.dry_run,
        "vector_store_id": vector_store_id,
        "source_output": str(args.source_output),
        "payload_count": len(payloads),
        "submitted_count": len(submitted),
        "sample_source_uris": [payload["source_uri"] for payload in payloads[:3]],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
