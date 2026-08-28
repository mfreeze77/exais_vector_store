#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from svs_common.marker_client import MarkerRunpodClient, extract_markdown
from topeka_pipeline_common import ORDINANCE_SEED, read_jsonl, safe_filename, sha256_bytes, sha256_text, utc_now, write_json, write_jsonl


def seed_base_for_manifest(manifest_path: Path) -> Path:
    return manifest_path.parent.parent if manifest_path.parent.name == "manifests" else manifest_path.parent


def first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def find_pdf(row: dict[str, Any], *, manifest_path: Path, pdf_dir: Path | None) -> Path | None:
    base = seed_base_for_manifest(manifest_path)
    candidates: list[Path] = []
    saved_path = first_text(row, "saved_path")
    if saved_path:
        saved = Path(saved_path)
        candidates.append(saved if saved.is_absolute() else base / saved)
        if pdf_dir:
            candidates.append(pdf_dir / saved.name)
    default_pdf_dir = pdf_dir or base / "raw" / "pdfs"
    for value in (first_text(row, "ordinance_number"), first_text(row, "id"), Path(saved_path).stem if saved_path else ""):
        if value:
            candidates.append(default_pdf_dir / safe_filename(value, suffix=".pdf"))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def markdown_path_for(row: dict[str, Any], *, extracted_dir: Path, pdf_path: Path | None = None) -> Path:
    stem = first_text(row, "ordinance_number", "id")
    if first_text(row, "category") == "charter_ordinance" and first_text(row, "ordinance_number"):
        stem = f"CharterOrdinance{first_text(row, 'ordinance_number')}"
    if not stem and pdf_path:
        stem = pdf_path.stem
    return extracted_dir / safe_filename(stem or "topeka-ordinance", suffix=".md")


def relative_to_base(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def with_source_header(row: dict[str, Any], markdown: str) -> str:
    title = first_text(row, "title") or first_text(row, "ordinance_number") or "Topeka ordinance"
    pdf_url = first_text(row, "pdf_url")
    ordinance_number = first_text(row, "ordinance_number")
    header = [
        f"# {title}",
        "",
        "Source collection: Topeka ordinance PDFs",
    ]
    if ordinance_number:
        header.append(f"Ordinance number: {ordinance_number}")
    if pdf_url:
        header.append(f"Official PDF: {pdf_url}")
    header += ["", markdown.strip()]
    return "\n".join(header).strip() + "\n"


def existing_markdown_result(
    row: dict[str, Any],
    *,
    target_path: Path,
    base: Path,
    min_markdown_chars: int,
) -> dict[str, Any] | None:
    if not target_path.exists() or not target_path.is_file():
        return None
    markdown = target_path.read_text(encoding="utf-8").strip()
    if len(markdown) < min_markdown_chars:
        return None
    return {
        "id": first_text(row, "id"),
        "ordinance_number": first_text(row, "ordinance_number"),
        "pdf_url": first_text(row, "pdf_url"),
        "status": "skipped_existing",
        "markdown_path": relative_to_base(target_path, base),
        "markdown_chars": len(markdown),
        "markdown_sha256": sha256_text(markdown),
        "extracted_at": "",
    }


async def extract_one(
    index: int,
    total: int,
    row: dict[str, Any],
    *,
    manifest_path: Path,
    extracted_dir: Path,
    pdf_dir: Path | None,
    client: MarkerRunpodClient,
    force: bool,
    dry_run: bool,
    min_markdown_chars: int,
    poll_interval_sec: int | None,
    timeout_seconds: int | None,
    attempts: int | None,
) -> dict[str, Any]:
    base = seed_base_for_manifest(manifest_path)
    pdf_path = find_pdf(row, manifest_path=manifest_path, pdf_dir=pdf_dir)
    target_path = markdown_path_for(row, extracted_dir=extracted_dir, pdf_path=pdf_path)
    row_id = first_text(row, "id") or first_text(row, "ordinance_number") or f"row-{index}"

    if not force:
        existing = existing_markdown_result(row, target_path=target_path, base=base, min_markdown_chars=min_markdown_chars)
        if existing:
            existing["index"] = index
            return existing

    if not pdf_path:
        return {
            "index": index,
            "id": row_id,
            "ordinance_number": first_text(row, "ordinance_number"),
            "pdf_url": first_text(row, "pdf_url"),
            "status": "failed",
            "reason": "missing_pdf",
        }

    pdf_bytes = pdf_path.read_bytes()
    actual_pdf_sha256 = sha256_bytes(pdf_bytes)
    expected_pdf_sha256 = first_text(row, "sha256")
    if expected_pdf_sha256 and expected_pdf_sha256 != actual_pdf_sha256:
        return {
            "index": index,
            "id": row_id,
            "ordinance_number": first_text(row, "ordinance_number"),
            "pdf_url": first_text(row, "pdf_url"),
            "status": "failed",
            "reason": "pdf_sha256_mismatch",
            "expected_sha256": expected_pdf_sha256,
            "actual_sha256": actual_pdf_sha256,
            "pdf_path": relative_to_base(pdf_path, base),
        }

    if dry_run:
        return {
            "index": index,
            "id": row_id,
            "ordinance_number": first_text(row, "ordinance_number"),
            "pdf_url": first_text(row, "pdf_url"),
            "status": "pending",
            "pdf_path": relative_to_base(pdf_path, base),
            "markdown_path": relative_to_base(target_path, base),
            "pdf_bytes": len(pdf_bytes),
            "pdf_sha256": actual_pdf_sha256,
        }

    log_lines: list[str] = []
    job_ids: list[str] = []

    def log(line: str) -> None:
        log_lines.append(line)

    def job_id(job: str) -> None:
        job_ids.append(job)

    print(f"extracting {index}/{total} id={row_id} pdf={pdf_path.name}", flush=True)
    result = await client.process_pdf_bytes(
        filename=pdf_path.name,
        pdf_bytes=pdf_bytes,
        poll_interval_sec=poll_interval_sec,
        max_poll_sec=timeout_seconds,
        max_attempts=attempts,
        log_callback=log,
        job_id_callback=job_id,
    )
    if result is None:
        return {
            "index": index,
            "id": row_id,
            "ordinance_number": first_text(row, "ordinance_number"),
            "pdf_url": first_text(row, "pdf_url"),
            "status": "failed",
            "reason": "marker_no_result",
            "pdf_path": relative_to_base(pdf_path, base),
            "pdf_bytes": len(pdf_bytes),
            "pdf_sha256": actual_pdf_sha256,
            "marker_logs": log_lines[-20:],
            "marker_job_ids": job_ids,
        }
    try:
        markdown = extract_markdown(result)
    except Exception as exc:
        return {
            "index": index,
            "id": row_id,
            "ordinance_number": first_text(row, "ordinance_number"),
            "pdf_url": first_text(row, "pdf_url"),
            "status": "failed",
            "reason": "marker_empty_markdown",
            "error": str(exc),
            "pdf_path": relative_to_base(pdf_path, base),
            "pdf_bytes": len(pdf_bytes),
            "pdf_sha256": actual_pdf_sha256,
            "marker_logs": log_lines[-20:],
            "marker_job_ids": job_ids,
        }
    rendered = with_source_header(row, markdown)
    if len(rendered.strip()) < min_markdown_chars:
        return {
            "index": index,
            "id": row_id,
            "ordinance_number": first_text(row, "ordinance_number"),
            "pdf_url": first_text(row, "pdf_url"),
            "status": "failed",
            "reason": "markdown_below_min_chars",
            "markdown_chars": len(rendered.strip()),
            "pdf_path": relative_to_base(pdf_path, base),
            "pdf_bytes": len(pdf_bytes),
            "pdf_sha256": actual_pdf_sha256,
            "marker_logs": log_lines[-20:],
            "marker_job_ids": job_ids,
        }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(rendered, encoding="utf-8", newline="\n")
    return {
        "index": index,
        "id": row_id,
        "ordinance_number": first_text(row, "ordinance_number"),
        "pdf_url": first_text(row, "pdf_url"),
        "status": "extracted",
        "pdf_path": relative_to_base(pdf_path, base),
        "markdown_path": relative_to_base(target_path, base),
        "pdf_bytes": len(pdf_bytes),
        "pdf_sha256": actual_pdf_sha256,
        "markdown_chars": len(rendered),
        "markdown_sha256": sha256_text(rendered),
        "marker_job_ids": job_ids,
        "marker_output_keys": sorted(result.keys()),
        "extracted_at": utc_now(),
    }


def build_report(
    *,
    manifest_path: Path,
    extracted_dir: Path,
    selected_count: int,
    results: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for result in results:
        status = str(result.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    failed = [result for result in results if result.get("status") == "failed"]
    complete = len(results) == selected_count and not failed
    return {
        "schema_version": "1.0",
        "artifact": "topeka_ordinance_pdf_extraction",
        "dry_run": dry_run,
        "status": "complete" if complete else "pending" if dry_run else "incomplete",
        "manifest": str(manifest_path),
        "extracted_dir": str(extracted_dir),
        "selected_count": selected_count,
        "result_count": len(results),
        "status_counts": by_status,
        "failure_count": len(failed),
        "failures": failed[:25],
        "updated_at": utc_now(),
    }


def write_checkpoint(
    *,
    output_manifest: Path,
    report_path: Path,
    manifest_path: Path,
    extracted_dir: Path,
    selected_count: int,
    results: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    ordered = sorted(results, key=lambda item: int(item.get("index") or 0))
    write_jsonl(output_manifest, ordered)
    write_json(
        report_path,
        build_report(
            manifest_path=manifest_path,
            extracted_dir=extracted_dir,
            selected_count=selected_count,
            results=ordered,
            dry_run=dry_run,
        ),
    )


async def extract_rows(
    rows: list[dict[str, Any]],
    *,
    manifest_path: Path,
    extracted_dir: Path,
    pdf_dir: Path | None,
    output_manifest: Path,
    report_path: Path,
    offset: int,
    limit: int,
    concurrency: int,
    client: MarkerRunpodClient,
    force: bool = False,
    dry_run: bool = False,
    allow_failures: bool = False,
    min_markdown_chars: int = 50,
    poll_interval_sec: int | None = None,
    timeout_seconds: int | None = None,
    attempts: int | None = None,
) -> dict[str, Any]:
    selected = rows[offset : offset + limit if limit > 0 else None]
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[dict[str, Any]] = []

    async def guarded(index: int, row: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await extract_one(
                index,
                len(rows),
                row,
                manifest_path=manifest_path,
                extracted_dir=extracted_dir,
                pdf_dir=pdf_dir,
                client=client,
                force=force,
                dry_run=dry_run,
                min_markdown_chars=min_markdown_chars,
                poll_interval_sec=poll_interval_sec,
                timeout_seconds=timeout_seconds,
                attempts=attempts,
            )

    tasks = [asyncio.create_task(guarded(offset + i + 1, row)) for i, row in enumerate(selected)]
    if not tasks:
        write_checkpoint(
            output_manifest=output_manifest,
            report_path=report_path,
            manifest_path=manifest_path,
            extracted_dir=extracted_dir,
            selected_count=0,
            results=[],
            dry_run=dry_run,
        )
        return build_report(manifest_path=manifest_path, extracted_dir=extracted_dir, selected_count=0, results=[], dry_run=dry_run)

    for completed in asyncio.as_completed(tasks):
        result = await completed
        results.append(result)
        print(f"{result.get('status')} id={result.get('id')} markdown={result.get('markdown_path', '')}", flush=True)
        write_checkpoint(
            output_manifest=output_manifest,
            report_path=report_path,
            manifest_path=manifest_path,
            extracted_dir=extracted_dir,
            selected_count=len(selected),
            results=results,
            dry_run=dry_run,
        )

    report = build_report(
        manifest_path=manifest_path,
        extracted_dir=extracted_dir,
        selected_count=len(selected),
        results=results,
        dry_run=dry_run,
    )
    if report["failure_count"] and not allow_failures:
        raise SystemExit(2)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract downloaded Topeka ordinance PDFs to Markdown through RunPod Marker.")
    parser.add_argument("--manifest", type=Path, default=ORDINANCE_SEED / "manifests" / "ordinances.jsonl")
    parser.add_argument("--pdf-dir", type=Path)
    parser.add_argument("--extracted-dir", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--min-markdown-chars", type=int, default=50)
    parser.add_argument("--attempts", type=int)
    parser.add_argument("--retry-backoff-seconds", type=int)
    parser.add_argument("--poll-interval-sec", type=int)
    parser.add_argument("--timeout-seconds", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest
    base = seed_base_for_manifest(manifest_path)
    extracted_dir = args.extracted_dir or base / "extracted"
    output_manifest = args.output_manifest or base / "manifests" / "ordinance-extractions.jsonl"
    report_path = args.report or base / "manifests" / "ordinance-extraction-report.json"
    rows = read_jsonl(manifest_path)
    client = MarkerRunpodClient(
        poll_interval_sec=args.poll_interval_sec,
        timeout_sec=args.timeout_seconds,
        max_attempts=args.attempts,
        retry_backoff_sec=args.retry_backoff_seconds,
    )
    report = asyncio.run(
        extract_rows(
            rows,
            manifest_path=manifest_path,
            extracted_dir=extracted_dir,
            pdf_dir=args.pdf_dir,
            output_manifest=output_manifest,
            report_path=report_path,
            offset=args.offset,
            limit=args.limit,
            concurrency=args.concurrency,
            client=client,
            force=args.force,
            dry_run=args.dry_run,
            allow_failures=args.allow_failures,
            min_markdown_chars=args.min_markdown_chars,
            poll_interval_sec=args.poll_interval_sec,
            timeout_seconds=args.timeout_seconds,
            attempts=args.attempts,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
