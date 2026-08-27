#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from argparse import Namespace
from io import BytesIO
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = ROOT / "scripts" / "release"
COMMON_PACKAGE = ROOT / "packages" / "svs_common"
sys.path.insert(0, str(RELEASE_DIR))
if COMMON_PACKAGE.exists():
    sys.path.insert(0, str(COMMON_PACKAGE))


def load_ingest_module():
    script = RELEASE_DIR / "kscourts-ingest.py"
    spec = importlib.util.spec_from_file_location("kscourts_ingest", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load ingest helper: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["kscourts_ingest"] = module
    spec.loader.exec_module(module)
    return module


def decrypted_pdf_bytes(path: Path) -> bytes:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError("Missing pypdf. Install pypdf[crypto] in the runtime container.") from exc

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        reader.decrypt("")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def headers_from_env() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-SVS-Tenant-Id": os.getenv("SVS_DEV_TENANT_ID", "ten_ks_state_civics"),
        "X-SVS-Business-Instance-Id": os.getenv("SVS_DEV_BUSINESS_INSTANCE_ID", "biz_ks_state_civics"),
        "X-SVS-User-Id": os.getenv("SVS_DEV_USER_ID", "usr_ks_state_civics_admin"),
        "X-SVS-Roles": os.getenv("SVS_DEV_ROLES", "owner,admin"),
        "X-SVS-Max-Security-Level": os.getenv("SVS_DEV_MAX_SECURITY_LEVEL", "5"),
    }


async def convert_with_marker(doc, ingest, args: argparse.Namespace):
    from svs_common.marker_client import MarkerRunpodClient

    job_ids: list[str] = []

    def log(line: str) -> None:
        print(f"marker_log row_key={doc.row_key} {line}", flush=True)

    pdf_bytes = decrypted_pdf_bytes(doc.pdf_path)
    print(
        f"decrypted_marker_fallback row_key={doc.row_key} "
        f"filename={doc.pdf_path.name} bytes={len(pdf_bytes)}",
        flush=True,
    )
    output = await MarkerRunpodClient().process_pdf_bytes(
        filename=doc.pdf_path.stem + ".decrypted.pdf",
        pdf_bytes=pdf_bytes,
        log_callback=log,
        job_id_callback=job_ids.append,
    )
    if output is None:
        raise RuntimeError("Marker RunPod PDF conversion failed")
    return ingest.marker_extraction_from_output(
        output,
        job_ids=job_ids,
        low_text_threshold=args.low_text_threshold,
    )


async def run(args: argparse.Namespace) -> None:
    ingest = load_ingest_module()
    docs = {
        doc.row_key: doc
        for doc in ingest.load_manifest(args.source_root.resolve(), args.manifest)
    }
    missing = sorted(set(args.row_key) - set(docs))
    if missing:
        raise RuntimeError(f"row_key not found in manifest: {missing}")

    payload_args = Namespace(
        knowledge_base_id=args.knowledge_base_id,
        security_level=args.security_level,
        force_async=True,
    )
    submitted = 0
    failed = 0
    async with httpx.AsyncClient(timeout=args.api_timeout_seconds) as client:
        for row_key in args.row_key:
            doc = docs[row_key]
            try:
                extraction = await convert_with_marker(doc, ingest, args)
                payload = ingest.document_payload(doc, extraction, payload_args, args.vector_store_id)
                request_headers = headers_from_env()
                request_headers["Idempotency-Key"] = ingest.idempotency_key(doc)
                resp = await client.post(args.api_base.rstrip("/") + "/api/v1/documents/ingest", json=payload, headers=request_headers)
                print(f"POST row_key={row_key} status={resp.status_code} body={resp.text[:500]}", flush=True)
                resp.raise_for_status()
                event = ingest.event_for_doc(
                    doc,
                    args.vector_store_id,
                    "submitted",
                    pdf_path=doc.pdf_path,
                    extraction=extraction,
                    response=resp.json(),
                )
                ingest.append_state(args.state, event)
                submitted += 1
            except Exception as exc:
                failed += 1
                event = ingest.event_for_doc(doc, args.vector_store_id, "marker_failed", error=str(exc), pdf_path=doc.pdf_path)
                ingest.append_state(args.state, event)
                print(f"decrypted_marker_failed row_key={row_key} error={exc}", flush=True)
    print(json.dumps({"attempted": len(args.row_key), "submitted": submitted, "failed": failed}, sort_keys=True), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retry encrypted Kansas court PDFs through decrypted Marker conversion.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--api-base", default="http://api:8080")
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--vector-store-id", required=True)
    parser.add_argument("--row-key", action="append", required=True)
    parser.add_argument("--security-level", type=int, default=1)
    parser.add_argument("--low-text-threshold", type=int, default=400)
    parser.add_argument("--api-timeout-seconds", type=int, default=300)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
