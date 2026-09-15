#!/usr/bin/env python3
"""Re-measure the retained Topeka inputs before anything is published from them.

Counts and hashes are derived here, not carried forward from an earlier audit.
Every retained record is reconciled to exactly one outcome, and the outcome set
is closed: a record that matches no outcome fails the audit rather than being
dropped from the totals.

    python scripts/release/topeka-retained-input-audit.py --output <report.json>

Offline. Reads the retained corpus and seed only; no network, no API, no
database. Exit status is 0 only when every retained record reconciles.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import (  # noqa: E402
    ROOT,
    RoutingError,
    capture_index,
    route_document,
    sha256_bytes,
    sha256_file,
)

DEFAULT_TMC_CORPUS = (
    ROOT / ".tmp" / "topeka-decodo-window-batches-20260827220454" / "combined-full-corpus-20260828-v2"
)
DEFAULT_ORDINANCE_SEED = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "sources" / "topeka-ordinances" / "seed"
)

# Outcomes a retained PDF extraction can reconcile to. The audit fails if any
# record falls outside this set, so the set cannot silently under-report.
EXTRACTION_OUTCOMES = (
    "matched",
    "terminal_newline_appended",
    "hash_unexplained",
    "file_missing",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def audit_code_corpus(corpus: Path) -> dict[str, Any]:
    sections_path = corpus / "sections.jsonl"
    if not sections_path.exists():
        return {"available": False, "reason": f"{sections_path} is absent", "path": str(corpus)}

    sections = read_jsonl(sections_path)
    raw_dir = corpus / "raw"
    # Resolve by content hash, not by rebuilding the crawler's filename: citations
    # such as "AxB Art. III § 1" are sanitised into names no rule here reproduces.
    index = capture_index(raw_dir)
    captures_ok = captures_missing = captures_mismatched = 0
    missing: list[str] = []
    mismatched: list[str] = []
    for section in sections:
        html_hash = section.get("source_html_hash") or ""
        candidates = index.get(html_hash[:12], [])
        if not candidates:
            captures_missing += 1
            missing.append(section["citation"])
        elif any(sha256_file(candidate) == html_hash for candidate in candidates):
            captures_ok += 1
        else:
            captures_mismatched += 1
            mismatched.append(section["citation"])

    # Grouping is derived from the citation itself, not from a hand-written list
    # of the titles and chapters someone remembered to check.
    titles = Counter(section["citation"].split(".")[0] for section in sections)
    chapters = Counter(".".join(section["citation"].split(".")[:2]) for section in sections)

    return {
        "available": True,
        "path": str(corpus),
        "section_record_count": len(sections),
        "page_types": dict(Counter(section.get("page_type") for section in sections)),
        "distinct_citations": len({section["citation"] for section in sections}),
        "title_18_sections": titles.get("18", 0),
        "chapter_14_55_sections": chapters.get("14.55", 0),
        "title_counts": dict(sorted(titles.items(), key=lambda item: item[0])),
        "captures": {
            "indexed_files": sum(len(paths) for paths in index.values()),
            "verified": captures_ok,
            "missing": captures_missing,
            "mismatched": captures_mismatched,
            "missing_citations": sorted(missing)[:20],
            "mismatched_citations": sorted(mismatched)[:20],
        },
    }


def audit_ordinance_seed(seed: Path) -> dict[str, Any]:
    manifest_path = seed / "manifests" / "ordinances.jsonl"
    extraction_path = seed / "manifests" / "ordinance-extractions.jsonl"
    if not manifest_path.exists() or not extraction_path.exists():
        return {"available": False, "reason": f"{seed} has no ordinance manifests", "path": str(seed)}

    rows = read_jsonl(manifest_path)
    extractions = {row["id"]: row for row in read_jsonl(extraction_path)}

    raw_outcomes: Counter[str] = Counter()
    raw_problems: list[dict[str, str]] = []
    for row in rows:
        path = seed / row["saved_path"]
        if not path.exists():
            raw_outcomes["file_missing"] += 1
            raw_problems.append({"id": row["id"], "outcome": "file_missing", "path": row["saved_path"]})
            continue
        if sha256_file(path) == row["sha256"]:
            raw_outcomes["matched"] += 1
        else:
            raw_outcomes["hash_unexplained"] += 1
            raw_problems.append({"id": row["id"], "outcome": "hash_unexplained", "path": row["saved_path"]})

    extraction_outcomes: Counter[str] = Counter()
    extraction_notes: list[dict[str, Any]] = []
    for row in rows:
        extraction = extractions.get(row["id"])
        if extraction is None:
            extraction_outcomes["file_missing"] += 1
            extraction_notes.append({"id": row["id"], "outcome": "file_missing", "detail": "no extraction record"})
            continue
        path = seed / extraction["markdown_path"]
        if not path.exists():
            extraction_outcomes["file_missing"] += 1
            extraction_notes.append({"id": row["id"], "outcome": "file_missing", "path": extraction["markdown_path"]})
            continue
        payload = path.read_bytes()
        actual = sha256_bytes(payload)
        expected = extraction["markdown_sha256"]
        if actual == expected:
            extraction_outcomes["matched"] += 1
            continue
        if payload.endswith(b"\n") and sha256_bytes(payload[:-1]) == expected:
            extraction_outcomes["terminal_newline_appended"] += 1
            extraction_notes.append({
                "id": row["id"],
                "outcome": "terminal_newline_appended",
                "path": extraction["markdown_path"],
                "manifest_sha256": expected,
                "on_disk_sha256": actual,
                "resolution": (
                    "content is byte-identical to the extractor output apart from one appended terminal LF; "
                    "proven by re-hashing the file without its final byte. Both hashes are retained and the "
                    "step is published as source.lineage[terminal_newline_appended]."
                ),
            })
            continue
        extraction_outcomes["hash_unexplained"] += 1
        extraction_notes.append({
            "id": row["id"],
            "outcome": "hash_unexplained",
            "path": extraction["markdown_path"],
            "manifest_sha256": expected,
            "on_disk_sha256": actual,
            "resolution": "not the known terminal-newline transformation; must not be released",
        })

    categories = Counter(row.get("category") for row in rows)
    numbered = Counter(
        "numbered" if str(row.get("ordinance_number") or "").strip() else "unnumbered" for row in rows
    )
    unnumbered = [
        {"id": row["id"], "title": row.get("title"), "category": row.get("category"), "pdf_url": row["pdf_url"]}
        for row in rows
        if not str(row.get("ordinance_number") or "").strip()
    ]

    routing: Counter[str] = Counter()
    routing_failures: list[dict[str, str]] = []
    for row in rows:
        try:
            spec = route_document(official_url=row["pdf_url"], listing_category=row.get("category"))
        except RoutingError as error:
            routing_failures.append({"id": row["id"], "pdf_url": row["pdf_url"], "error": str(error)})
            continue
        routing[spec.collection_id] += 1

    return {
        "available": True,
        "path": str(seed),
        "record_count": len(rows),
        "extraction_record_count": len(extractions),
        "listing_categories": dict(categories),
        "numbering": dict(numbered),
        "unnumbered_records": unnumbered,
        "raw_outcomes": {outcome: raw_outcomes.get(outcome, 0) for outcome in EXTRACTION_OUTCOMES},
        "raw_problems": raw_problems,
        "extraction_outcomes": {outcome: extraction_outcomes.get(outcome, 0) for outcome in EXTRACTION_OUTCOMES},
        "extraction_notes": extraction_notes,
        "routing": dict(sorted(routing.items())),
        "routing_failures": routing_failures,
    }


def evaluate(report: dict[str, Any]) -> list[str]:
    """Blocking findings. An audit that cannot measure something blocks too."""
    failures: list[str] = []
    code = report["code_corpus"]
    seed = report["ordinance_seed"]

    if not code["available"]:
        failures.append(f"code corpus not measurable: {code['reason']}")
    else:
        if code["captures"]["mismatched"]:
            failures.append(f"{code['captures']['mismatched']} TMC capture(s) do not match their recorded hash")
        if code["captures"]["missing"]:
            # Not "no problem found" -- the verification could not be run at all,
            # so these sections are unreleasable until a capture is restored.
            failures.append(
                f"{code['captures']['missing']} TMC section(s) have no retained capture to verify against"
            )
        if code["section_record_count"] != code["distinct_citations"]:
            failures.append("TMC section records contain duplicate citations")

    if not seed["available"]:
        failures.append(f"ordinance seed not measurable: {seed['reason']}")
    else:
        reconciled = sum(seed["raw_outcomes"].values())
        if reconciled != seed["record_count"]:
            failures.append(f"{seed['record_count'] - reconciled} retained PDF(s) reconciled to no outcome")
        reconciled_extractions = sum(seed["extraction_outcomes"].values())
        if reconciled_extractions != seed["record_count"]:
            failures.append(
                f"{seed['record_count'] - reconciled_extractions} extraction(s) reconciled to no outcome"
            )
        for key in ("raw_outcomes", "extraction_outcomes"):
            for outcome in ("hash_unexplained", "file_missing"):
                count = seed[key].get(outcome, 0)
                if count:
                    failures.append(f"{count} record(s) in {key} have outcome {outcome}")
        if seed["routing_failures"]:
            failures.append(f"{len(seed['routing_failures'])} retained record(s) route to no master collection")
        if sum(seed["routing"].values()) != seed["record_count"]:
            failures.append("routing did not account for every retained record")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tmc-corpus", type=Path, default=DEFAULT_TMC_CORPUS)
    parser.add_argument("--ordinance-seed", type=Path, default=DEFAULT_ORDINANCE_SEED)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "artifact": "topeka_retained_input_audit",
        "schema_version": "1.0",
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_corpus": audit_code_corpus(args.tmc_corpus),
        "ordinance_seed": audit_ordinance_seed(args.ordinance_seed),
    }
    failures = evaluate(report)
    report["failures"] = failures
    report["passed"] = not failures

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    code, seed = report["code_corpus"], report["ordinance_seed"]
    if code["available"]:
        print(f"TMC sections           {code['section_record_count']} "
              f"(title 18: {code['title_18_sections']}, chapter 14.55: {code['chapter_14_55_sections']})")
        print(f"TMC captures verified  {code['captures']['verified']} of "
              f"{code['captures']['indexed_files']} indexed"
              f"  missing {code['captures']['missing']}  mismatched {code['captures']['mismatched']}")
    else:
        print(f"TMC corpus             UNAVAILABLE: {code['reason']}")
    if seed["available"]:
        print(f"retained PDFs          {seed['record_count']}  categories {seed['listing_categories']}")
        print(f"numbering              {seed['numbering']}")
        print(f"raw hash outcomes      {seed['raw_outcomes']}")
        print(f"extraction outcomes    {seed['extraction_outcomes']}")
        print(f"routing                {seed['routing']}")
        for note in seed["extraction_notes"]:
            print(f"  {note['outcome']}: {note['id']} {note.get('path', '')}")
    else:
        print(f"ordinance seed         UNAVAILABLE: {seed['reason']}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"result                 {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
