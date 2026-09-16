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
    sha256_file,
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


def load_holds(path: Path) -> dict[str, set[str]]:
    """Review holds recorded by earlier runs, still unresolved."""
    holds: dict[str, set[str]] = {}
    for row in read_jsonl(path):
        holds.setdefault(row["source_document_id"], set()).update(row.get("review_flags") or [])
    return holds


def load_resolutions(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Explicit resolutions: the only thing that clears a hold.

    A resolution is a human act recorded in a file, naming the document, the
    flag, who resolved it and why. An observation that simply arrives without
    the flag is not a resolution -- it usually means the run did not look.
    """
    resolved: dict[str, dict[str, dict[str, Any]]] = {}
    for row in read_jsonl(path):
        if not row.get("resolved_by") or not row.get("reason"):
            continue
        resolved.setdefault(row["source_document_id"], {})[row["review_flag"]] = row
    return resolved


def build(
    assignments: Path,
    checkpoint: Path,
    worklist: Path,
    *,
    holds_path: Path | None = None,
    resolutions_path: Path | None = None,
) -> dict[str, Any]:
    # Identities the current discovery run actually knows about. The checkpoint
    # is run state and can still hold documents under an identity a later
    # discovery superseded; those must not reach a destination manifest.
    current = {row["source_document_id"] for row in read_jsonl(worklist)}
    prior_holds = load_holds(holds_path) if holds_path else {}
    resolutions = load_resolutions(resolutions_path) if resolutions_path else {}
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

        incoming_flags = list(row.get("review_flags") or [])

        existing = by_id.get(row["source_document_id"])
        if existing is not None and existing["sha256"] == row["sha256"]:
            # Same bytes from both sides. That settles the CONTENT question and
            # nothing else: uncertainty discovered at this run's discovery (a
            # membership question, an ambiguous identity) is about the document,
            # not about its bytes, and unchanged bytes are no reason to drop it.
            # Clearing a flag needs an explicit resolution, never hash equality.
            existing["reconfirmed_by_acquisition"] = True
            merged = sorted(set(existing.get("review_flags") or []) | set(incoming_flags))
            existing["review_flags"] = merged
            existing["review_status"] = "review_needed" if merged else "clear"
            if row.get("identity_conflict"):
                existing["identity_conflict"] = row["identity_conflict"]
            if row.get("url_resolution"):
                existing["listing_url"] = row.get("listing_url")
                existing["url_resolution"] = row.get("url_resolution")
                existing["correction_evidence"] = row.get("correction_evidence")
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
            "review_flags": incoming_flags,
            "review_status": "review_needed" if incoming_flags else (row.get("review_status") or "clear"),
            "identity_conflict": row.get("identity_conflict"),
        }

    # Carry forward every unresolved hold from earlier runs. A flag observed once
    # stays until a resolution clears it; otherwise a run that simply did not
    # re-observe the condition would silently release a held document.
    carried_holds: list[dict[str, Any]] = []
    cleared: list[dict[str, Any]] = []
    for record in by_id.values():
        doc_id = record["source_document_id"]
        flags = set(record.get("review_flags") or []) | prior_holds.get(doc_id, set())
        for flag in sorted(flags & set(resolutions.get(doc_id, {}))):
            entry = resolutions[doc_id][flag]
            cleared.append({
                "source_document_id": doc_id, "review_flag": flag,
                "resolved_by": entry["resolved_by"], "reason": entry["reason"],
            })
        flags -= set(resolutions.get(doc_id, {}))
        if flags - set(record.get("review_flags") or []):
            carried_holds.append({
                "source_document_id": doc_id,
                "carried_flags": sorted(flags - set(record.get("review_flags") or [])),
                "detail": "recorded by an earlier run and still unresolved",
            })
        record["review_flags"] = sorted(flags)
        record["review_status"] = "review_needed" if flags else "clear"

    surviving_holds: dict[str, list[str]] = {}
    for doc_id, flags in prior_holds.items():
        remaining = sorted(flags - set(resolutions.get(doc_id, {})))
        if remaining:
            surviving_holds[doc_id] = remaining
    absent_holds = [
        {"source_document_id": doc_id, "review_flags": flags,
         "detail": "held, and not present in this run's inputs; the hold is kept"}
        for doc_id, flags in sorted(surviving_holds.items())
        if doc_id not in by_id
    ]
    for record in by_id.values():
        if record["review_flags"]:
            surviving_holds[record["source_document_id"]] = sorted(record["review_flags"])
        else:
            surviving_holds.pop(record["source_document_id"], None)

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
        "carried_holds": carried_holds,
        "holds_on_absent_documents": absent_holds,
        "cleared_by_resolution": cleared,
        # The holds ledger is the record of unresolved doubt, not a snapshot of
        # this run's inputs. A document can drop out of a worklist for a run --
        # a listing hiccup, a narrowed --collection, a discovery failure -- and
        # rebuilding the ledger from only what is present deletes its hold, so
        # the next run that sees it again releases it. Absent documents keep
        # their holds; only a signed resolution removes one.
        "holds": surviving_holds,
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
    parser.add_argument("--holds", type=Path, default=None,
                        help="ledger of unresolved review holds (default: <output-dir>/review-holds.jsonl)")
    parser.add_argument("--resolutions", type=Path, default=None,
                        help="explicit hold resolutions (default: <output-dir>/review-resolutions.jsonl)")
    args = parser.parse_args()

    holds_path = args.holds or (args.output_dir / "review-holds.jsonl")
    resolutions_path = args.resolutions or (args.output_dir / "review-resolutions.jsonl")
    result = build(
        args.assignments, args.checkpoint, args.worklist,
        holds_path=holds_path, resolutions_path=resolutions_path,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # The existing ordinance ingest path consumes ordinances.jsonl rows. Slicing
    # per destination is what lets each store be dry-run on its own, instead of
    # one combined batch that proves nothing about where each document lands.
    #
    # The slice is built from the SELECTED revision, not from the legacy seed
    # row. Copying the seed row is how the destination manifest ended up naming
    # new bytes while the thing actually fed to ingestion named the old ones.
    seed_rows = {row["id"]: row for row in read_jsonl(args.ordinance_seed / "manifests" / "ordinances.jsonl")}
    legacy_by_doc = {}
    for row in read_jsonl(args.assignments):
        if row.get("source_document_id") and row.get("legacy_id") in seed_rows:
            legacy_by_doc[row["source_document_id"]] = seed_rows[row["legacy_id"]]

    def ingest_row(record: dict[str, Any]) -> dict[str, Any] | None:
        """One ordinances.jsonl-shaped row describing the selected revision.

        Returns None when the selected bytes have no retained extraction, because
        feeding the legacy row in its place would hand ingestion a different
        document from the one the destination manifest names.
        """
        legacy = legacy_by_doc.get(record["source_document_id"])
        if legacy is None or legacy.get("sha256") != record["sha256"]:
            return None
        return {
            **legacy,
            "sha256": record["sha256"],
            "pdf_url": record["source_uri"],
            "exais_source_document_id": record["source_document_id"],
            "exais_collection_id": record["collection_id"],
        }

    issues_local: list[dict[str, Any]] = []
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

        slice_rows = []
        slice_gaps = []
        for row in rows:
            built = ingest_row(row)
            if built is None:
                if row["source_document_id"] in legacy_by_doc:
                    slice_gaps.append({
                        "source_document_id": row["source_document_id"],
                        "destination_sha256": row["sha256"],
                        "retained_extraction_sha256": legacy_by_doc[row["source_document_id"]].get("sha256"),
                        "reason": (
                            "the selected revision has no retained extraction; it is excluded from the "
                            "ingestion slice rather than substituted with the superseded one"
                        ),
                    })
                continue
            slice_rows.append(built)
        slice_path = args.output_dir / f"{spec.slug}.ingest-slice.jsonl"
        if slice_rows:
            slice_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in slice_rows), encoding="utf-8"
            )
        elif slice_path.exists():
            # Writing only when there is something to write leaves the previous
            # run's file in place, so a report saying "0 slice rows" sits beside
            # a file still offering the superseded revision to ingestion.
            slice_path.unlink()

        # Destination record, ingestion payload and source artifact must agree.
        by_doc = {row["source_document_id"]: row for row in rows}
        for built in slice_rows:
            doc_id = built["exais_source_document_id"]
            if by_doc[doc_id]["sha256"] != built["sha256"]:
                issues_local.append({
                    "code": "SLICE_HASH_DISAGREEMENT", "record": doc_id,
                    "detail": f"destination {by_doc[doc_id]['sha256']} vs slice {built['sha256']}",
                })
            artifact = args.ordinance_seed / built["saved_path"]
            if artifact.exists() and sha256_file(artifact) != built["sha256"]:
                issues_local.append({
                    "code": "SLICE_ARTIFACT_DISAGREEMENT", "record": doc_id,
                    "detail": f"{built['saved_path']} does not hash to {built['sha256']}",
                })

        destinations.append({
            "ingest_slice_gaps": slice_gaps,
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

    # Persist the holds so the next run starts from them, not from whatever this
    # run happened to observe.
    holds_path.parent.mkdir(parents=True, exist_ok=True)
    holds_path.write_text(
        "".join(
            json.dumps({"source_document_id": doc_id, "review_flags": flags}, sort_keys=True) + "\n"
            for doc_id, flags in sorted(result["holds"].items())
        ),
        encoding="utf-8",
    )

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
        "review_holds_ledger": str(holds_path),
        "review_resolutions_ledger": str(resolutions_path),
        "holds_carried_from_earlier_runs": result["carried_holds"],
        "holds_on_documents_absent_this_run": result["holds_on_absent_documents"],
        "holds_cleared_by_resolution": result["cleared_by_resolution"],
        "superseded_identities": result["superseded"],
        "acquired_revisions_superseding_retained": result["replaced"],
        "review_lane_note": (
            "records carrying unresolved doubt are written to <slug>.review.jsonl and excluded from "
            "<slug>.manifest.jsonl, so the clean ingestion lane holds only settled documents"
        ),
        "issues": result["issues"] + issues_local,
        "passed": not (result["issues"] + issues_local),
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
    for row in result["holds_on_absent_documents"][:10]:
        print(f"  HOLD-KEPT    {row['source_document_id']}: {row['review_flags']} (absent this run)")
    for row in result["carried_holds"][:10]:
        print(f"  HOLD-CARRIED {row['source_document_id']}: {row['carried_flags']}")
    for row in result["cleared_by_resolution"][:10]:
        print(f"  HOLD-CLEARED {row['source_document_id']}: {row['review_flag']} by {row['resolved_by']}")
    for row in result["replaced"][:10]:
        print(f"  SUPERSEDED-HASH {row['source_document_id']}: retained {row['retained_sha256'][:12]} "
              f"-> acquired {row['acquired_sha256'][:12]}")
    for row in result["superseded"][:10]:
        print(f"  SUPERSEDED {row['record']} (excluded)")
    for issue in (result["issues"] + issues_local)[:10]:
        print(f"  ISSUE {issue['code']} {issue['record']}: {issue['detail']}")
    print(f"result                 {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
