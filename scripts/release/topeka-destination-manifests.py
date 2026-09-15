#!/usr/bin/env python3
"""Build one ingestion manifest per destination collection, and prove the routing.

The combined store's contents and the newly acquired corpus are split into four
destination manifests -- municipal code, ordinances, charter ordinances and
resolutions -- in the shape the existing ingest scripts already consume, so each
destination can be dry-run separately instead of as one undifferentiated batch.

    python scripts/release/topeka-destination-manifests.py --output-dir <dir>

Fully offline and safe to run with external calls disabled (``--network none``).
It reads local manifests, re-derives each record's destination from the
registered collection registry, and writes files. It contacts no publisher, no
API and no database.

The routing proof is the point: for every record it asserts the destination is
the one the registry derives AND that no other registered collection also claims
it. A record claimed by two collections, or by none, fails the run.
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
    COLLECTIONS_BY_ID,
    COLLECTIONS_BY_SLUG,
    ROOT,
    TOPEKA_COLLECTIONS,
    RoutingError,
    canonical_source_url,
    route_document,
    source_document_id,
)

DEFAULT_ASSIGNMENTS = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "releases" / "proofs" / "topeka-store-split-assignments-20260915.jsonl"
)
DEFAULT_CHECKPOINT = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "acquisition" / "acquisition-checkpoint.jsonl"
)
DEFAULT_WORKLIST = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "discovery" / "worklist.jsonl"
)
DEFAULT_SEED = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "sources" / "topeka-ordinances" / "seed"
)
DEFAULT_OUTPUT = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code" / "destinations"
)

# Outcomes that mean bytes are held and the record is ingestable.
HELD_OUTCOMES = frozenset({
    "reused_verified", "downloaded_new", "downloaded_changed",
    "unchanged_remote", "downloaded_corrected_url",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def prove_routing(record: dict[str, Any]) -> tuple[str | None, list[str]]:
    """The destination the registry derives, plus every collection that claims it.

    Derived twice from different inputs on purpose: ``route_document`` answers
    from the URL rules, and the claim sweep asks every registered collection
    independently. Agreement is corroboration; disagreement is a routing defect.
    """
    url = record["source_uri"]
    try:
        derived = route_document(official_url=url).collection_id
    except RoutingError:
        derived = None

    claimants: list[str] = []
    parts = urlsplit(canonical_source_url(url))
    for spec in TOPEKA_COLLECTIONS:
        on_legacy = any(
            parts.netloc == host and parts.path.startswith(prefix)
            for host, prefix in spec.legacy_locations
        )
        on_primary = parts.netloc in spec.hosts and any(
            parts.path.startswith(prefix) for prefix in spec.path_prefixes
        ) and not any(parts.path.startswith(x) for x in spec.excluded_path_prefixes)
        if on_legacy or on_primary:
            claimants.append(spec.collection_id)
    return derived, claimants


def build(assignments: Path, checkpoint: Path, worklist: Path) -> dict[str, Any]:
    # Identities the current discovery run actually knows about. The checkpoint
    # is run state and can still hold documents under an identity a later
    # discovery superseded; those must not reach a destination manifest.
    current = {row["source_document_id"] for row in read_jsonl(worklist)}
    by_id: dict[str, dict[str, Any]] = {}
    replaced: list[dict[str, Any]] = []

    for row in read_jsonl(assignments):
        if not row.get("collection_id"):
            continue
        by_id[row["source_document_id"]] = {
            "source_document_id": row["source_document_id"],
            "collection_id": row["collection_id"],
            "source_uri": row["source_uri"],
            "sha256": row["content_sha256"],
            "retained_artifact": row["retained_artifact"],
            "record_kind": row["record_kind"],
            "origin": "retained_split",
            "review_flags": [],
            "review_status": "clear",
        }

    superseded: list[dict[str, Any]] = []
    for row in read_jsonl(checkpoint):
        if row.get("outcome") not in HELD_OUTCOMES:
            continue
        if current and row["source_document_id"] not in current:
            superseded.append({
                "code": "SUPERSEDED_IDENTITY",
                "record": row["source_document_id"],
                "detail": (
                    "held in the acquisition checkpoint but absent from the current worklist; the "
                    "identity was superseded by a later discovery run and is excluded from ingestion"
                ),
            })
            continue

        existing = by_id.get(row["source_document_id"])
        if existing is not None and existing["sha256"] == row["sha256"]:
            # Same bytes from both sides: keep the retained-split record, but note
            # that acquisition re-confirmed it against the publisher.
            existing["reconfirmed_by_acquisition"] = True
            continue
        if existing is not None:
            # The publisher now serves different bytes from the ones the combined
            # store holds. Selecting the retained hash here is how a refresh
            # silently ingests stale content, so the acquired revision wins and
            # the superseded hash is recorded rather than dropped.
            replaced.append({
                "source_document_id": row["source_document_id"],
                "retained_sha256": existing["sha256"],
                "acquired_sha256": row["sha256"],
                "detail": "acquired revision supersedes the retained-split hash for ingestion",
            })

        by_id[row["source_document_id"]] = {
            "source_document_id": row["source_document_id"],
            "collection_id": row["collection_id"],
            # The URL that actually served the bytes, with the listed one kept
            # beside it when a correction was needed.
            "source_uri": row.get("fetched_url") or row["official_url"],
            "listing_url": row.get("listing_url"),
            "url_resolution": row.get("url_resolution"),
            "correction_evidence": row.get("correction_evidence"),
            "sha256": row["sha256"],
            "retained_artifact": row.get("saved_path"),
            "record_kind": "acquired_document",
            "origin": "acquisition",
            "supersedes_sha256": existing["sha256"] if existing else None,
            "review_flags": list(row.get("review_flags") or []),
            "review_status": row.get("review_status") or "clear",
            "identity_conflict": row.get("identity_conflict"),
        }

    records = list(by_id.values())
    issues: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for record in records:
        derived, claimants = prove_routing(record)
        location = record["source_document_id"]
        if derived is None:
            issues.append({"code": "UNROUTABLE", "record": location, "detail": record["source_uri"]})
        elif derived != record["collection_id"]:
            issues.append({
                "code": "ROUTING_DISAGREEMENT", "record": location,
                "detail": f"assigned {record['collection_id']}, the URL routes to {derived}",
            })
        if len(claimants) > 1:
            issues.append({
                "code": "CLAIMED_BY_TWO_COLLECTIONS", "record": location,
                "detail": f"{record['source_uri']} is claimed by {claimants}",
            })
        if not claimants:
            issues.append({"code": "CLAIMED_BY_NONE", "record": location, "detail": record["source_uri"]})
        if location in seen:
            issues.append({
                "code": "DUPLICATE_IDENTITY", "record": location,
                "detail": "the same document id appears in two destinations",
            })
        seen[location] = record["collection_id"]

    # Two lanes per destination. A record carrying unresolved doubt is held out
    # of the clean ingestion lane rather than ingested with a flag nobody reads.
    by_destination: dict[str, list[dict[str, Any]]] = {}
    review_lane: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        target = review_lane if record.get("review_flags") else by_destination
        target.setdefault(record["collection_id"], []).append(record)
    return {
        "records": records,
        "review_lane": review_lane,
        "replaced": replaced,
        "by_destination": by_destination,
        "issues": issues,
        "superseded": superseded,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--assignments", type=Path, default=DEFAULT_ASSIGNMENTS)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ordinance-seed", type=Path, default=DEFAULT_SEED)
    args = parser.parse_args()

    result = build(args.assignments, args.checkpoint, args.worklist)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # The existing ordinance ingest path consumes ordinances.jsonl rows. Slicing
    # that manifest per destination is what lets each store be dry-run on its
    # own, instead of one combined 364-document batch that proves nothing about
    # where each document lands.
    seed_rows = {}
    for row in read_jsonl(args.ordinance_seed / "manifests" / "ordinances.jsonl"):
        seed_rows[row["id"]] = row
    legacy_by_doc = {}
    for row in read_jsonl(args.assignments):
        if row.get("source_document_id") and row.get("legacy_id") in seed_rows:
            legacy_by_doc[row["source_document_id"]] = seed_rows[row["legacy_id"]]

    destinations = []
    for spec in TOPEKA_COLLECTIONS:
        rows = sorted(
            result["by_destination"].get(spec.collection_id, []),
            key=lambda row: row["source_document_id"],
        )
        path = args.output_dir / f"{spec.slug}.manifest.jsonl"
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        review_rows = sorted(
            result["review_lane"].get(spec.collection_id, []),
            key=lambda row: row["source_document_id"],
        )
        review_path = args.output_dir / f"{spec.slug}.review.jsonl"
        review_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in review_rows), encoding="utf-8"
        )

        slice_rows = [
            legacy_by_doc[row["source_document_id"]]
            for row in rows if row["source_document_id"] in legacy_by_doc
        ]
        slice_path = args.output_dir / f"{spec.slug}.ingest-slice.jsonl"
        if slice_rows:
            slice_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in slice_rows), encoding="utf-8"
            )

        destinations.append({
            "review_manifest": str(review_path),
            "held_for_review": len(review_rows),
            "review_reasons": dict(Counter(
                flag for row in review_rows for flag in row.get("review_flags", [])
            )),
            "ingest_slice": str(slice_path) if slice_rows else None,
            "ingest_slice_rows": len(slice_rows),
            "ingest_path_available": bool(slice_rows),
            "collection_id": spec.collection_id,
            "slug": spec.slug,
            "name": spec.name,
            "vector_store_id": spec.vector_store_id,
            "manifest": str(path),
            "document_count": len(rows),
            "origins": dict(Counter(row["origin"] for row in rows)),
            "corrected_urls": sum(1 for row in rows if row.get("url_resolution")),
        })

    report = {
        "artifact": "topeka_destination_manifests",
        "schema_version": "1.0",
        "built_at": utc_now(),
        "offline": True,
        "network_used": False,
        "destinations": destinations,
        "total_records": len(result["records"]),
        "routing_checks": {
            "records_checked": len(result["records"]),
            "derived_from_url_rules": True,
            "claim_sweep_across_all_registered_collections": True,
        },
        "superseded_identities": result["superseded"],
        "acquired_revisions_superseding_retained": result["replaced"],
        "review_lane_note": (
            "records carrying unresolved doubt are written to <slug>.review.jsonl and excluded from "
            "<slug>.manifest.jsonl, so the clean ingestion lane holds only settled documents"
        ),
        "issues": result["issues"],
        "passed": not result["issues"],
    }
    (args.output_dir / "destination-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for destination in destinations:
        held = destination["held_for_review"]
        print(f"  {destination['slug']:20s} {destination['document_count']:5d} clean  "
              f"{held:3d} held for review  {destination['origins']}")
        if held:
            print(f"  {'':20s}       review reasons: {destination['review_reasons']}")
    print(f"  {'total':20s} {report['total_records']:5d}")
    for row in result["replaced"][:10]:
        print(f"  SUPERSEDED-HASH {row['source_document_id']}: retained {row['retained_sha256'][:12]} "
              f"-> acquired {row['acquired_sha256'][:12]}")
    for row in result["superseded"][:10]:
        print(f"  SUPERSEDED {row['record']} (excluded)")
    for issue in result["issues"][:10]:
        print(f"  ISSUE {issue['code']} {issue['record']}: {issue['detail']}")
    print(f"result                 {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
