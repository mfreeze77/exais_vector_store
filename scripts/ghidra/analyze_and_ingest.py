#!/usr/bin/env python3
"""Analyze/import a binary research export into an EXAIS binary vector store.

Examples:
  python scripts/ghidra/analyze_and_ingest.py --binary ./app.exe
  python scripts/ghidra/analyze_and_ingest.py --export-file ./app.ghidra.json

Required environment:
  EXAIS_API_BASE
  EXAIS_BEARER_KEY
  EXAIS_VECTOR_STORE_ID

The target vector store must be bound by an enabled
ghidra_binary_graph_v1 cell graph profile before graph loading.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BINARY_CORPUS = "binary_analysis"
BINARY_PROFILE = "binary-analysis.ghidra.v1"
SOURCE_COLLECTION = "ghidra-binary-analysis"


class ApiError(RuntimeError):
    pass


def api_json(
    base: str,
    key: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 300,
) -> dict[str, Any]:
    url = f"{base.rstrip('/')}{path}"
    data = None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"{method} {path} failed with HTTP {exc.code}: {body[:4000]}") from exc
    except URLError as exc:
        raise ApiError(f"{method} {path} failed: {exc}") from exc
    if not raw:
        return {}
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ApiError(f"{method} {path} returned a non-object JSON value")
    return value


def run_exporter(args: argparse.Namespace, output: Path) -> None:
    exporter = Path(__file__).with_name("export_binary.py")
    command = [
        sys.executable,
        str(exporter),
        str(args.binary),
        "--output",
        str(output),
        "--decompile-timeout",
        str(args.decompile_timeout),
    ]
    if args.ghidra_install_dir:
        command.extend(["--ghidra-install-dir", str(args.ghidra_install_dir)])
    if args.ghidra_project_dir:
        command.extend(["--project-dir", str(args.ghidra_project_dir)])
    subprocess.run(command, check=True)


def load_export(path: Path) -> tuple[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Ghidra export must be a JSON object")
    if value.get("schema_version") != "exais.ghidra-export.v1":
        raise ValueError("unsupported Ghidra export schema")
    binary = value.get("binary")
    if not isinstance(binary, dict) or not binary.get("sha256") or not binary.get("name"):
        raise ValueError("Ghidra export is missing binary identity")
    return raw, value


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze and ingest a binary into EXAIS")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--binary", type=Path)
    source.add_argument("--export-file", type=Path)
    parser.add_argument("--api-base", default=os.getenv("EXAIS_API_BASE"))
    parser.add_argument("--api-key", default=os.getenv("EXAIS_BEARER_KEY"))
    parser.add_argument("--vector-store-id", default=os.getenv("EXAIS_VECTOR_STORE_ID"))
    parser.add_argument("--security-level", type=int, default=3)
    parser.add_argument("--classification", default="tenant_private")
    parser.add_argument("--ghidra-install-dir", type=Path, default=None)
    parser.add_argument("--ghidra-project-dir", type=Path, default=None)
    parser.add_argument("--decompile-timeout", type=int, default=60)
    parser.add_argument("--keep-export", type=Path, default=None)
    parser.add_argument("--replace-graph", action="store_true")
    parser.add_argument("--dry-run-graph", action="store_true")
    args = parser.parse_args()

    if not args.api_base or not args.api_key or not args.vector_store_id:
        parser.error("EXAIS_API_BASE, EXAIS_BEARER_KEY, and EXAIS_VECTOR_STORE_ID are required")
    if not 0 <= args.security_level <= 5:
        parser.error("--security-level must be 0..5")
    if args.binary and not args.binary.is_file():
        parser.error(f"binary not found: {args.binary}")
    if args.export_file and not args.export_file.is_file():
        parser.error(f"export not found: {args.export_file}")

    with tempfile.TemporaryDirectory(prefix="exais-ghidra-") as temp:
        generated = Path(temp) / "ghidra-export.json"
        export_path = args.export_file
        if args.binary:
            run_exporter(args, generated)
            export_path = generated
        assert export_path is not None

        raw, export = load_export(export_path)
        binary = export["binary"]
        binary_sha = str(binary["sha256"])
        binary_name = str(binary["name"])
        ghidra_version = str(export.get("ghidra_version") or "unknown")
        content_hash = sha256(raw.encode("utf-8")).hexdigest()

        # Prove that this deployment exposes the binary-research plane and that
        # the supplied key has enough rights to continue.
        capabilities = api_json(args.api_base, args.api_key, "GET", "/api/v1/binary/capabilities")
        if capabilities.get("semantic_mode") != "ghidra_binary_v1":
            raise ApiError("server does not report ghidra_binary_v1 capability")

        # Keep the vector-store corpus identity explicit. The graph profile is
        # separately operator-bound and fail-closed in cell_graph.py.
        api_json(
            args.api_base,
            args.api_key,
            "POST",
            f"/v1/vector_stores/{args.vector_store_id}",
            {
                "attributes": {
                    "corpus": BINARY_CORPUS,
                    "source_collection": SOURCE_COLLECTION,
                    "graph_profile_id": BINARY_PROFILE,
                }
            },
        )

        ingest = api_json(
            args.api_base,
            args.api_key,
            "POST",
            f"/v1/vector_stores/{args.vector_store_id}/files",
            {
                "title": f"Ghidra analysis: {binary_name}",
                "filename": f"{binary_name}.{binary_sha[:12]}.ghidra.json",
                "mime_type": "application/json",
                "content": raw,
                "mode": "ghidra_binary_v1",
                "source_uri": f"ghidra://sha256/{binary_sha}",
                "source_identity": f"ghidra-binary:{binary_sha}",
                "attributes": {
                    "corpus": BINARY_CORPUS,
                    "source_collection": SOURCE_COLLECTION,
                    "graph_profile_id": BINARY_PROFILE,
                    "binary_sha256": binary_sha,
                    "binary_name": binary_name,
                    "ghidra_version": ghidra_version,
                    "ghidra_export_sha256": content_hash,
                    "force_sync": True,
                },
                "security_level": args.security_level,
                "classification": args.classification,
                "source_trust": "ghidra_static_analysis",
            },
        )

        graph = api_json(
            args.api_base,
            args.api_key,
            "POST",
            "/api/v1/binary/graph/build",
            {
                "vector_store_id": args.vector_store_id,
                "export": export,
                "replace": args.replace_graph,
                "dry_run": args.dry_run_graph,
            },
        )
        graph_load = api_json(
            args.api_base,
            args.api_key,
            "POST",
            f"/v1/vector_stores/{args.vector_store_id}/graph",
            graph,
        )
        lenses = api_json(
            args.api_base,
            args.api_key,
            "GET",
            f"/v1/vector_stores/{args.vector_store_id}/search_lenses",
        )

        if args.keep_export:
            args.keep_export.parent.mkdir(parents=True, exist_ok=True)
            args.keep_export.write_text(raw, encoding="utf-8")

        print(json.dumps({
            "ok": True,
            "vector_store_id": args.vector_store_id,
            "binary_name": binary_name,
            "binary_sha256": binary_sha,
            "function_count": len(export.get("functions") or []),
            "ingestion": ingest,
            "graph_load": graph_load,
            "search_lenses": lenses,
            "kept_export": str(args.keep_export) if args.keep_export else None,
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
