#!/usr/bin/env python3
"""Plan the split of the combined Topeka store into its registered collections.

``vs_d4185d1004604f08a55299fa`` holds the codified code and the ordinance PDFs
together. This produces the manifest-driven plan for separating them: every
retained record is assigned to exactly one destination collection, the totals
are reconciled against the combined store's recorded document count, and the
rollback is stated alongside the move.

    python scripts/release/topeka-store-split-plan.py --output <plan.json>

Plan only. It starts no container, calls no API, writes to no vector store and
changes no routing. Producing the plan is safe; executing it is a separate,
authorized step.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import (  # noqa: E402
    COLLECTIONS_BY_SLUG,
    ROOT,
    RoutingError,
    canonical_source_url,
    capture_index,
    route_document,
    sha256_file,
    source_document_id,
)

COMBINED_STORE_ID = "vs_d4185d1004604f08a55299fa"
STORE_YAML = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code" / "store.yaml"
)
DEFAULT_TMC_CORPUS = (
    ROOT / ".tmp" / "topeka-decodo-window-batches-20260827220454" / "combined-full-corpus-20260828-v2"
)
DEFAULT_ORDINANCE_SEED = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "sources" / "topeka-ordinances" / "seed"
)

# Every destination a retained record can be assigned to. A record that reaches
# none of these fails the plan; the split may not quietly drop anything.
DESTINATIONS = ("municipal-code", "ordinances", "charter-ordinances", "unassigned")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def plan_code_records(corpus: Path) -> tuple[list[dict[str, Any]], list[str]]:
    problems: list[str] = []
    sections_path = corpus / "sections.jsonl"
    if not sections_path.exists():
        return [], [f"{sections_path} is absent; code records cannot be planned"]

    spec = COLLECTIONS_BY_SLUG["municipal-code"]
    index = capture_index(corpus / "raw")
    rows: list[dict[str, Any]] = []
    for section in read_jsonl(sections_path):
        html_hash = section.get("source_html_hash") or ""
        capture = next(
            (path for path in index.get(html_hash[:12], []) if sha256_file(path) == html_hash), None
        )
        if capture is None:
            problems.append(f"{section['citation']}: no retained capture verifies against {html_hash[:12]}")
        rows.append({
            "destination": spec.slug,
            "collection_id": spec.collection_id,
            "source_document_id": source_document_id(spec, section["citation"]),
            "legacy_id": section["id"],
            "source_uri": canonical_source_url(section["source_url"]),
            "content_sha256": html_hash,
            "retained_artifact": capture.name if capture else None,
            "record_kind": "code_section",
        })
    return rows, problems


def plan_ordinance_records(seed: Path) -> tuple[list[dict[str, Any]], list[str]]:
    problems: list[str] = []
    manifest = seed / "manifests" / "ordinances.jsonl"
    if not manifest.exists():
        return [], [f"{manifest} is absent; ordinance records cannot be planned"]

    rows: list[dict[str, Any]] = []
    for record in read_jsonl(manifest):
        try:
            spec = route_document(
                official_url=record["pdf_url"], listing_category=record.get("category")
            )
        except RoutingError as exc:
            problems.append(f"{record['id']}: {exc}")
            rows.append({
                "destination": "unassigned",
                "collection_id": None,
                "source_document_id": None,
                "legacy_id": record["id"],
                "source_uri": record["pdf_url"],
                "content_sha256": record["sha256"],
                "retained_artifact": record["saved_path"],
                "record_kind": "ordinance_pdf",
            })
            continue
        key = str(record.get("ordinance_number") or "").strip() or \
            Path(urlsplit(canonical_source_url(record["pdf_url"])).path).stem
        path = seed / record["saved_path"]
        if not path.exists():
            problems.append(f"{record['id']}: retained original {record['saved_path']} is absent")
        elif sha256_file(path) != record["sha256"]:
            problems.append(f"{record['id']}: retained original does not match its recorded hash")
        rows.append({
            "destination": spec.slug,
            "collection_id": spec.collection_id,
            "source_document_id": source_document_id(spec, key),
            "legacy_id": record["id"],
            "source_uri": canonical_source_url(record["pdf_url"]),
            "content_sha256": record["sha256"],
            "retained_artifact": record["saved_path"],
            "record_kind": "ordinance_pdf",
            "listing_category": record.get("category"),
            "unnumbered": not str(record.get("ordinance_number") or "").strip(),
        })
    return rows, problems


def recorded_combined_counts() -> dict[str, Any]:
    """The counts store.yaml records for the combined store, read as text.

    Parsed without a YAML dependency so the plan runs on a bare checkout; only
    the few integer fields that the reconciliation needs are read.
    """
    wanted = {"documentCount", "codifiedDocumentCount", "ordinancePdfDocumentCount"}
    found: dict[str, Any] = {}
    if not STORE_YAML.exists():
        return found
    for line in STORE_YAML.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition(":")
        if key in wanted and value.strip().isdigit() and key not in found:
            found[key] = int(value.strip())
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tmc-corpus", type=Path, default=DEFAULT_TMC_CORPUS)
    parser.add_argument("--ordinance-seed", type=Path, default=DEFAULT_ORDINANCE_SEED)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--assignments", type=Path, default=None,
                        help="also write the per-record assignment table as JSONL")
    args = parser.parse_args()

    code_rows, code_problems = plan_code_records(args.tmc_corpus)
    ordinance_rows, ordinance_problems = plan_ordinance_records(args.ordinance_seed)
    rows = code_rows + ordinance_rows
    problems = code_problems + ordinance_problems

    by_destination = Counter(row["destination"] for row in rows)
    identities = [row["source_document_id"] for row in rows if row["source_document_id"]]
    duplicates = sorted({key for key, count in Counter(identities).items() if count > 1})
    if duplicates:
        problems.append(f"{len(duplicates)} identity collision(s) across the split: {duplicates[:5]}")
    if by_destination.get("unassigned"):
        problems.append(f"{by_destination['unassigned']} retained record(s) reached no destination")

    recorded = recorded_combined_counts()
    reconciliation: list[dict[str, Any]] = []
    checks = [
        ("documentCount", len(rows)),
        ("codifiedDocumentCount", len(code_rows)),
        ("ordinancePdfDocumentCount", len(ordinance_rows)),
    ]
    for field, planned in checks:
        expected = recorded.get(field)
        agrees = expected == planned
        reconciliation.append({
            "field": field,
            "recorded_in_store_yaml": expected,
            "planned_from_manifests": planned,
            "agrees": agrees,
        })
        if expected is None:
            problems.append(f"store.yaml records no {field}; the split cannot be reconciled against it")
        elif not agrees:
            problems.append(
                f"{field}: store.yaml records {expected} but the manifests plan {planned}"
            )

    plan = {
        "artifact": "topeka_store_split_plan",
        "schema_version": "1.0",
        "planned_at": utc_now(),
        "executed": False,
        "source_store": {
            "vector_store_id": COMBINED_STORE_ID,
            "role": "combined code and ordinance store, retained for rollback",
            "mutated_by_this_plan": False,
        },
        "destinations": [
            {
                "destination": slug,
                "collection_id": COLLECTIONS_BY_SLUG[slug].collection_id,
                "name": COLLECTIONS_BY_SLUG[slug].name,
                "vector_store_id": COLLECTIONS_BY_SLUG[slug].vector_store_id,
                "planned_document_count": by_destination.get(slug, 0),
            }
            for slug in DESTINATIONS
            if slug != "unassigned"
        ],
        "unassigned_count": by_destination.get("unassigned", 0),
        "reconciliation": reconciliation,
        "unnumbered_records": [
            {
                "source_document_id": row["source_document_id"],
                "legacy_id": row["legacy_id"],
                "destination": row["destination"],
                "source_uri": row["source_uri"],
                "note": "unnumbered instrument; it has a destination and is not dropped from the split",
            }
            for row in ordinance_rows if row.get("unnumbered")
        ],
        "execution": {
            "status": "not_executed",
            "blocked_on": [
                "owner authorization for cell activation and embedding spend",
                "a running ks-state-civics cell (none is up on this host)",
            ],
            "ordered_steps": [
                "python scripts/release/cell-up.py --cell ks-state-civics",
                "python scripts/release/topeka-code-ingest.py --cell ks-state-civics --dry-run  # counts only",
                "create the three destination stores through the supported API, never by direct DB write",
                "ingest each destination from its manifest slice and verify per-store document counts",
                "run retrieval and citation checks against each destination store",
                "switch ExAIS routing only after every destination verifies",
            ],
            "rollback": [
                f"{COMBINED_STORE_ID} is not mutated by the split and stays queryable throughout",
                "routing reverts to the combined store by restoring store.yaml vectorStore.id",
                "destination stores are deleted through the API; no retained artifact is removed",
            ],
        },
        "problems": problems,
        "passed": not problems,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.assignments:
        args.assignments.parent.mkdir(parents=True, exist_ok=True)
        args.assignments.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )

    print(f"combined store      {COMBINED_STORE_ID} (not mutated)")
    for destination in plan["destinations"]:
        print(f"  {destination['destination']:20s} {destination['planned_document_count']:5d}"
              f"  -> {destination['collection_id']}")
    print(f"  {'unassigned':20s} {plan['unassigned_count']:5d}")
    for row in reconciliation:
        mark = "ok" if row["agrees"] else "DIFFERS"
        print(f"  reconcile {row['field']:28s} store.yaml={row['recorded_in_store_yaml']} "
              f"planned={row['planned_from_manifests']}  {mark}")
    for record in plan["unnumbered_records"]:
        print(f"  unnumbered kept: {record['source_document_id']} -> {record['destination']}")
    for problem in problems[:10]:
        print(f"  PROBLEM {problem}")
    print(f"result              {'PASS' if plan['passed'] else 'FAIL'}")
    return 0 if plan["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
