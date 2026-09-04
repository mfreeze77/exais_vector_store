#!/usr/bin/env python3
"""Export persisted one-pass Marker Markdown back to StateCivics.

This command never calls Marker. It reads the completed Kansas fiscal ingestion
state, fetches persisted vector-file metadata and Markdown through authenticated
ExAIS APIs, verifies every source and extraction hash, and writes a deterministic
handoff package for StateCivics candidate table/cell parsing.

Planning is the default and makes no API calls or writes. Append ``--apply``
with the exact producer commit after the plan is reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from svs_common.fiscal_marker_handoff import (
    MarkerHandoffArtifact,
    MarkerHandoffError,
    build_marker_handoff,
    render_handoff_manifest,
)
from topeka_pipeline_common import (
    DEFAULT_CELL,
    api_bytes,
    api_json,
    default_api_base,
    default_headers,
)

ROOT = Path(__file__).resolve().parents[2]
INGEST_COMMAND = ROOT / "scripts" / "release" / "kansas-fiscal-document-ingest.py"
STATECIVICS_CONTRACT_REVISION = "19e402cd59831fcc23125442270c4063dbf42a14"
STATECIVICS_CONTRACT_SHA256 = (
    "5e4dac393d0ee24d5fa37b2868e4d8ae1b8546d852c2414f128011379129a2c1"
)
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
_HANDOFF_CODE_PATHS = (
    "scripts/release/kansas-fiscal-marker-handoff.py",
    "scripts/release/topeka_pipeline_common.py",
    "packages/svs_common/svs_common/fiscal_marker_handoff.py",
)


def _load_ingest_command():
    spec = importlib.util.spec_from_file_location(
        "kansas_fiscal_document_ingest_for_handoff", INGEST_COMMAND
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_code_commit(supplied: str | None) -> str:
    if not supplied:
        raise MarkerHandoffError("--code-commit is required with --apply")
    candidate = supplied.strip()
    if not _COMMIT_RE.fullmatch(candidate):
        raise MarkerHandoffError("--code-commit must be a Git SHA")
    try:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MarkerHandoffError(
            f"commit {candidate} does not exist in this repository"
        ) from exc
    comparison = subprocess.run(
        ["git", "diff", "--quiet", resolved, "--", *_HANDOFF_CODE_PATHS],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if comparison.returncode == 1:
        raise MarkerHandoffError(
            "--code-commit does not match the Marker handoff implementation"
        )
    if comparison.returncode != 0:
        raise MarkerHandoffError("unable to compare --code-commit with this checkout")
    return resolved


def _state_vector_store_id(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarkerHandoffError(f"cannot read ingestion state {path}: {exc}") from exc
    vector_store_id = value.get("vector_store_id") if isinstance(value, dict) else None
    if not isinstance(vector_store_id, str) or not vector_store_id.strip():
        raise MarkerHandoffError("ingestion state has no vector_store_id")
    return vector_store_id


def eligible_pdf_records(manifest: Any) -> list[dict[str, Any]]:
    records = [
        record
        for record in manifest.records
        if record.get("mime_type") == "application/pdf"
        and isinstance(record.get("ingestion"), dict)
        and record["ingestion"].get("action") == "upsert"
    ]
    return sorted(records, key=lambda record: record["logical_document_id"])


def collect_handoff_artifacts(
    *,
    records: list[dict[str, Any]],
    state: dict[str, Any],
    vector_store_id: str,
    producer_commit: str,
    api_base: str,
    headers: dict[str, str],
    timeout: int,
    cell: str,
    transport: str,
    fetch_json: Callable[..., dict[str, Any]] = api_json,
    fetch_bytes: Callable[..., bytes] = api_bytes,
) -> list[MarkerHandoffArtifact]:
    artifacts: list[MarkerHandoffArtifact] = []
    for source_record in records:
        logical_id = source_record["logical_document_id"]
        state_entry = state["records"].get(logical_id)
        if not isinstance(state_entry, dict):
            raise MarkerHandoffError(
                f"ingestion state has no applied entry for {logical_id}"
            )
        file_id = state_entry.get("vector_store_file_id")
        document_id = state_entry.get("document_id")
        if not isinstance(file_id, str) or not isinstance(document_id, str):
            raise MarkerHandoffError(
                f"ingestion state has no persisted ExAIS ids for {logical_id}"
            )
        metadata_path = f"/v1/vector_stores/{vector_store_id}/files/{file_id}"
        content_path = f"/v1/files/{document_id}/content"
        metadata = fetch_json(
            "GET",
            api_base,
            metadata_path,
            None,
            headers=headers,
            timeout=timeout,
            cell=cell,
            transport=transport,
        )
        markdown = fetch_bytes(
            "GET",
            api_base,
            content_path,
            headers=headers,
            timeout=timeout,
            cell=cell,
            transport=transport,
        )
        artifacts.append(
            build_marker_handoff(
                source_record=source_record,
                state_entry=state_entry,
                file_metadata=metadata,
                markdown_bytes=markdown,
                vector_store_id=vector_store_id,
                producer_commit=producer_commit,
            )
        )
    return artifacts


def _write_bytes_atomic(path: Path, payload: bytes) -> bool:
    if path.is_file() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


def write_handoff_package(
    output_dir: Path,
    artifacts: list[MarkerHandoffArtifact],
    *,
    source_manifest_sha256: str,
    producer_commit: str,
) -> dict[str, Any]:
    root = output_dir.resolve()
    manifest = render_handoff_manifest(artifacts)
    for artifact in artifacts:
        relative = artifact.record["extracted_artifact"]["relative_path"]
        destination = (root / relative).resolve()
        if not destination.is_relative_to(root):
            raise MarkerHandoffError("extracted artifact path escapes output directory")
        _write_bytes_atomic(destination, artifact.markdown_bytes)
    manifest_path = root / "manifest.jsonl"
    _write_bytes_atomic(manifest_path, manifest)
    proof = {
        "schema_version": 1,
        "record_count": len(artifacts),
        "extracted_byte_count": sum(
            len(artifact.markdown_bytes) for artifact in artifacts
        ),
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "source_manifest_sha256": source_manifest_sha256,
        "producer_commit": producer_commit,
        "contract": {
            "repository": "operator-source://statecivics-recovered-local",
            "revision": STATECIVICS_CONTRACT_REVISION,
            "path": "contracts/civic-impact/marker-extraction-record.schema.json",
            "sha256": STATECIVICS_CONTRACT_SHA256,
        },
        "boundary": (
            "Persisted ExAIS Markdown only; this exporter made no Marker request."
        ),
    }
    _write_bytes_atomic(
        root / "handoff-proof.json",
        (json.dumps(proof, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return proof


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api")
    parser.add_argument("--auth-token-file", type=Path)
    parser.add_argument("--api-timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--api-transport",
        default="auto",
        choices=["auto", "host-curl", "api-container", "docker-network"],
    )
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ingest = _load_ingest_command()
        manifest = ingest.load_manifest(args.manifest)
        vector_store_id = _state_vector_store_id(args.state)
        state = ingest.load_state(args.state, vector_store_id=vector_store_id)
        records = eligible_pdf_records(manifest)
        plan = {
            "applied": args.apply,
            "eligible_pdf_records": len(records),
            "vector_store_id": vector_store_id,
            "source_manifest_sha256": manifest.sha256,
            "marker_requests": 0,
        }
        if not args.apply:
            print(json.dumps(plan, indent=2, sort_keys=True))
            print("\nplan only -- no API calls or files written")
            return 0

        producer_commit = _resolve_code_commit(args.code_commit)
        headers = default_headers(cell=args.cell, auth_token_file=args.auth_token_file)
        artifacts = collect_handoff_artifacts(
            records=records,
            state=state,
            vector_store_id=vector_store_id,
            producer_commit=producer_commit,
            api_base=args.api or default_api_base(args.cell),
            headers=headers,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
            transport=args.api_transport,
        )
        plan["result"] = write_handoff_package(
            args.output_dir,
            artifacts,
            source_manifest_sha256=manifest.sha256,
            producer_commit=producer_commit,
        )
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    except (MarkerHandoffError, OSError, ValueError, RuntimeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
