#!/usr/bin/env python3
"""Build, validate, stage, and evaluate StateCivics fiscal GraphRAG artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit

from svs_common.fiscal_graph_artifact import (
    DOCUMENT_PAGE_LINES_CONVENTION,
    MAX_DOCUMENT_EXTRACTION_BYTES,
    MAX_DOCUMENT_QUOTE_CHARACTERS,
    MAX_INPUT_FILE_BYTES,
    MAX_STRUCTURED_SOURCE_BYTES,
    build_fiscal_graph_artifact,
    validate_built_artifact,
    validate_vector_store_id,
    verify_document_page_lines_evidence,
    verify_structured_csv_evidence,
)


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("authenticated API redirects are forbidden")


def _read(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_FILE_BYTES:
        raise ValueError(f"input JSON exceeds {MAX_INPUT_FILE_BYTES} bytes")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_FILE_BYTES:
        raise ValueError(f"input JSON exceeds {MAX_INPUT_FILE_BYTES} bytes")
    return json.loads(raw)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv_bytes(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size > MAX_STRUCTURED_SOURCE_BYTES:
        raise ValueError("CSV source must be a regular file no larger than 16 MiB")
    with path.open("rb") as handle:
        raw = handle.read(MAX_STRUCTURED_SOURCE_BYTES + 1)
    if len(raw) > MAX_STRUCTURED_SOURCE_BYTES:
        raise ValueError("CSV source exceeds 16 MiB")
    return raw


def _read_document_bytes(path: Path, maximum_bytes: int, label: str) -> bytes:
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ValueError(f"{label} must be a regular file no larger than {maximum_bytes} bytes")
    with path.open("rb") as handle:
        raw = handle.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ValueError(f"{label} exceeds {maximum_bytes} bytes")
    return raw


def _safe_api(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("API URL cannot contain credentials, path, query, or fragment")
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return value.rstrip("/")
    raise ValueError("API URL must use HTTPS, or HTTP on localhost")


def _call(method: str, url: str, payload: dict[str, Any], token_env: str, timeout: int) -> dict[str, Any]:
    token = os.getenv(token_env)
    if not token:
        raise ValueError(f"authentication token is required in environment variable {token_env}")
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    try:
        with request.build_opener(_NoRedirect).open(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"API request failed with HTTP {exc.code}") from exc
    return json.loads(raw) if raw else {}


def _relationship_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        candidate = value.get("relationship_id")
        if isinstance(candidate, str):
            found.add(candidate)
        for child in value.values():
            found.update(_relationship_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_relationship_ids(child))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify_csv = sub.add_parser("verify-structured-evidence", help="verify local CSV bytes and exact record hashes offline")
    verify_csv.add_argument("--source-csv", type=Path, required=True)
    verify_csv.add_argument("--source-sha256", required=True)
    verify_csv.add_argument("--records", type=Path, required=True,
                            help="JSON array of data_record_1based/raw_record_sha256 references")
    verify_document = sub.add_parser("verify-document-evidence", help="verify exact retained Markdown page/line evidence offline")
    verify_document.add_argument("--extraction-md", type=Path, required=True)
    verify_document.add_argument("--extraction-sha256", required=True)
    verify_document.add_argument("--declared-page-count", type=int, required=True)
    verify_document.add_argument("--page", type=int, required=True)
    verify_document.add_argument("--line-start", type=int, required=True)
    verify_document.add_argument("--line-end", type=int, required=True)
    verify_document.add_argument("--locator-convention", choices=[DOCUMENT_PAGE_LINES_CONVENTION], required=True)
    verify_document.add_argument("--quote-text", type=Path, required=True,
                                 help="exact UTF-8 quote file, including internal spaces/LFs; no added trailing LF")
    verify_document.add_argument("--quote-sha256", required=True)
    build = sub.add_parser("build")
    build.add_argument("--publisher", type=Path, required=True); build.add_argument("--chunks", type=Path, required=True)
    build.add_argument("--vector-store-id", required=True); build.add_argument("--output", type=Path, required=True)
    build.add_argument("--allow-fixture", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--artifact", type=Path, required=True); validate.add_argument("--allow-fixture", action="store_true")
    remote_commands = {}
    for name in ("load", "evaluate"):
        cmd = sub.add_parser(name); remote_commands[name] = cmd
        cmd.add_argument("--artifact", type=Path, required=True)
        cmd.add_argument("--api", required=True); cmd.add_argument("--token-env", default="SVS_OPERATOR_KEY")
        cmd.add_argument("--timeout", type=int, default=120); cmd.add_argument("--apply", action="store_true")
    evaluate = remote_commands["evaluate"]
    evaluate.add_argument("--query", required=True); evaluate.add_argument("--expected-relation-id", action="append", required=True)
    args = parser.parse_args()

    if args.command == "verify-document-evidence":
        try:
            extraction = _read_document_bytes(args.extraction_md, MAX_DOCUMENT_EXTRACTION_BYTES, "Markdown extraction")
            quote = _read_document_bytes(args.quote_text, MAX_DOCUMENT_QUOTE_CHARACTERS * 4, "Quote text")
            result = verify_document_page_lines_evidence(
                extraction_bytes=extraction, expected_extraction_sha256=args.extraction_sha256,
                declared_page_count=args.declared_page_count, page_1based=args.page,
                line_start_1based=args.line_start, line_end_1based=args.line_end,
                locator_convention=args.locator_convention, quoted_text=quote.decode("utf-8", errors="strict"),
                expected_quote_sha256=args.quote_sha256,
            )
        except UnicodeError:
            parser.error("document evidence files must contain valid UTF-8")
        except ValueError as exc:
            parser.error(str(exc))
        except OSError:
            parser.error("document evidence files could not be read")
        print(json.dumps(result, sort_keys=True)); return 0
    if args.command == "verify-structured-evidence":
        result = verify_structured_csv_evidence(
            source_bytes=_read_csv_bytes(args.source_csv), expected_source_sha256=args.source_sha256,
            records=_read(args.records),
        )
        print(json.dumps(result, sort_keys=True)); return 0
    if args.command == "build":
        chunks = _read(args.chunks)
        if not isinstance(chunks, list):
            raise ValueError("chunk inventory must be a JSON array")
        artifact = build_fiscal_graph_artifact(_read(args.publisher), chunks, args.vector_store_id,
                                               allow_fixture=args.allow_fixture)
        _write(args.output, artifact)
        print(json.dumps(artifact["validation"], sort_keys=True)); return 0
    artifact = _read(args.artifact)
    summary = validate_built_artifact(artifact, allow_fixture=getattr(args, "allow_fixture", False))
    validate_vector_store_id(artifact.get("vector_store_id"))
    if args.command == "validate":
        print(json.dumps(summary, sort_keys=True)); return 0
    if artifact["artifact_class"] == "fixture_only":
        raise ValueError("fixture_only artifacts cannot be uploaded or evaluated against runtime")
    if not args.apply:
        print(json.dumps({"dry_run": True, "command": args.command, "vector_store_id": artifact["vector_store_id"],
                          "derivation_run_id": artifact["derivation_run_id"], "validation": summary}, sort_keys=True)); return 0
    api = _safe_api(args.api)
    if args.command == "load":
        payload = dict(artifact["load_request"]); payload["dry_run"] = False; payload["replace"] = False
        result = _call("POST", f"{api}/v1/vector_stores/{artifact['vector_store_id']}/graph", payload, args.token_env, args.timeout)
    else:
        payload = {"query": args.query, "max_num_results": 10, "include_metadata": True, "include_content": True,
                   "lens": "fiscal_relationships", "inputs": {"relationship": "all", "derivation_run_id": artifact["derivation_run_id"]}}
        response = _call("POST", f"{api}/v1/vector_stores/{artifact['vector_store_id']}/search", payload, args.token_env, args.timeout)
        found = _relationship_ids(response); expected = set(args.expected_relation_id)
        result = {"passed": expected <= found, "expected_relation_ids": sorted(expected), "observed_relation_ids": sorted(found),
                  "derivation_run_id": artifact["derivation_run_id"]}
        if not result["passed"]:
            print(json.dumps(result, sort_keys=True)); return 1
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
