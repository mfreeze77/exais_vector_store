from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from svs_common.marker_client import (
    FISCAL_TABLES_PAGE_AWARE_PROFILE,
    MarkerRunpodClient,
    MarkerRunpodError,
    extract_markdown,
    marker_options_for_profile,
)
from svs_common.marker_quality import evaluate_profile, extract_page_markers


def load_profile(path: Path, expected_sha256: str) -> dict[str, Any]:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValueError("quality profile SHA-256 does not match --profile-sha256")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise TypeError("quality profile must be a JSON object")
    return value


def validate_source(pdf_path: Path, profile: dict[str, Any]) -> tuple[bytes, str]:
    content = pdf_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    document = profile.get("document") or {}
    if not isinstance(document, dict):
        raise TypeError("quality profile document must be an object")
    if document.get("filename") != pdf_path.name:
        raise ValueError(
            f"profile expects filename {document.get('filename')!r}, got {pdf_path.name!r}"
        )
    if document.get("sha256") != digest:
        raise ValueError("profile source SHA-256 does not match the supplied PDF")
    if b"%PDF-" not in content[:1024]:
        raise ValueError("supplied source has no PDF header")
    return content, digest


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-marker-quality-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


async def run_quality(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    pdf_path = Path(args.pdf).resolve()
    profile_path = Path(args.profile).resolve()
    profile = load_profile(profile_path, args.profile_sha256)
    content, source_digest = validate_source(pdf_path, profile)
    job_ids: list[str] = []

    result = await MarkerRunpodClient(
        poll_interval_sec=args.poll_interval_sec,
        timeout_sec=args.timeout_seconds,
        max_attempts=args.attempts,
        retry_backoff_sec=args.retry_backoff_seconds,
    ).process_pdf_bytes(
        filename=pdf_path.name,
        pdf_bytes=content,
        job_id_callback=job_ids.append,
        **marker_options_for_profile(FISCAL_TABLES_PAGE_AWARE_PROFILE),
    )
    observed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if result is None:
        proof = {
            "schema_version": 1,
            "observed_at": observed_at,
            "passed": False,
            "source_filename": pdf_path.name,
            "source_sha256": source_digest,
            "source_bytes": len(content),
            "marker_job_count": len(job_ids),
            "failure": "Marker returned no completed output",
        }
        return 1, proof

    markdown = extract_markdown(result)
    assessment = evaluate_profile(markdown, profile)
    page_markers = extract_page_markers(markdown)
    pagination_check = {
        "id": "profile:zero_based_page_markers",
        "passed": bool(page_markers) and page_markers == list(range(len(page_markers))),
        "marker_count": len(page_markers),
        "first_page": page_markers[0] if page_markers else None,
        "last_page": page_markers[-1] if page_markers else None,
    }
    assessment["checks"].append(pagination_check)
    assessment["passed"] = assessment["passed"] and pagination_check["passed"]
    images = result.get("images")
    assessment["metrics"]["marker_image_count"] = (
        len(images) if isinstance(images, dict | list) else 0
    )
    proof = {
        "schema_version": 1,
        "observed_at": observed_at,
        "passed": assessment["passed"],
        "source_filename": pdf_path.name,
        "source_sha256": source_digest,
        "source_bytes": len(content),
        "marker_job_count": len(job_ids),
        "marker_job_id": job_ids[-1] if job_ids else None,
        "marker_profile": FISCAL_TABLES_PAGE_AWARE_PROFILE,
        "marker_options": marker_options_for_profile(FISCAL_TABLES_PAGE_AWARE_PROFILE),
        "marker_output_fields": sorted(result),
        "assessment": assessment,
    }
    return (0 if assessment["passed"] else 1), proof


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one Marker extraction and score fiscal-table fidelity without printing text."
    )
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--output")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=int, default=5)
    parser.add_argument("--poll-interval-sec", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result, proof = asyncio.run(run_quality(args))
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        MarkerRunpodError,
    ) as exc:
        print(json.dumps({"passed": False, "failure": str(exc)}, sort_keys=True))
        return 1
    if args.output:
        write_json_atomic(Path(args.output).resolve(), proof)
    print(json.dumps(proof, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
