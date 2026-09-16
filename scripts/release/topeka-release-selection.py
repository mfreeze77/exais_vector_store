#!/usr/bin/env python3
"""Decide which documents are eligible to release, and account for the rest.

Joins the destination manifests to the extraction results and to the previous
release, then sorts every document into exactly one bucket:

    eligible_new | eligible_changed | unchanged | pending_extraction | held_for_review

Nothing is dropped. A release that silently omits documents is
indistinguishable from one that has them, so the pending and held counts travel
with the selection and are reported whether or not anything is released.

    python scripts/release/topeka-release-selection.py --output <selection.jsonl>

Offline: reads local manifests and writes files. No publisher, no API, no
database, no extraction service.
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

from jurisdiction_release_contract import COLLECTIONS_BY_ID, ROOT  # noqa: E402

INSTANCE = ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
DEFAULT_DESTINATIONS = INSTANCE / "destinations"
DEFAULT_EXTRACTION = INSTANCE / "extraction"
DEFAULT_CHECKPOINT = INSTANCE / "acquisition" / "acquisition-checkpoint.jsonl"
DEFAULT_SEED = INSTANCE / "sources" / "topeka-ordinances" / "seed"
DEFAULT_TMC_CORPUS = (
    ROOT / ".tmp" / "topeka-decodo-window-batches-20260827220454" / "combined-full-corpus-20260828-v2"
)

BUCKETS = (
    "eligible_new",
    "eligible_changed",
    "unchanged",
    "pending_extraction",
    "held_for_review",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def extraction_index(
    extraction_dir: Path, tmc_corpus: Path, ordinance_seed: Path
) -> dict[str, dict[str, Any]]:
    """Every extraction this project holds, keyed by the source hash it came from.

    One index over all three sources, because "is this document extracted?" has
    one answer regardless of which pipeline produced it. An index that knew only
    about DOCX reported 2,702 retained TMC sections and 364 retained Marker
    extractions as pending, which is the opposite of true.

    Keying on the source hash, not the document key, is what makes a changed
    document's old extraction unusable for its new bytes: the lookup simply
    misses, and the document lands in pending_extraction instead of being
    released with stale text.
    """
    index: dict[str, dict[str, Any]] = {}

    # 1. Retained TMC sections. The parser record in sections.jsonl is the
    #    extraction, and the destination record's hash is the captured HTML hash.
    sections = tmc_corpus / "sections.jsonl"
    if sections.exists():
        for row in read_jsonl(sections):
            if row.get("source_html_hash"):
                index[row["source_html_hash"]] = {
                    "builder": "tmc_section",
                    "citation": row["citation"],
                    "extractor": {"name": "topeka-code-scraper", "version": "0.1.1",
                                  "mode": "playwright_html_parse"},
                    "limitations": [],
                }

    # 2. Retained ordinance and charter Marker extractions, joined to the PDF
    #    hash through the ordinance manifest.
    pdf_sha_by_id = {
        row["id"]: row["sha256"]
        for row in read_jsonl(ordinance_seed / "manifests" / "ordinances.jsonl")
    }
    for row in read_jsonl(ordinance_seed / "manifests" / "ordinance-extractions.jsonl"):
        pdf_sha = pdf_sha_by_id.get(row["id"])
        if not pdf_sha or not (ordinance_seed / row["markdown_path"]).exists():
            continue
        index[pdf_sha] = {
            "builder": "retained_ordinance",
            "legacy_id": row["id"],
            "extractor": {"name": "marker", "version": "runpod-hosted-2026-08",
                          "mode": "remote_pdf_to_markdown"},
            "limitations": [],
        }

    # 3. Documents this pipeline extracted locally.
    report = extraction_dir / "docx-extraction-report.json"
    if report.exists():
        payload = json.loads(report.read_text(encoding="utf-8"))
        for row in payload.get("results", []):
            index[row["source_sha256"]] = {**row, "builder": "acquired_document"}
    return index


def limitation_descriptions() -> dict[str, str]:
    return {
        "unresolved_tracked_changes": (
            "the source carries tracked insertions or deletions; deleted runs are excluded from the "
            "reading text and the document needs review against the publisher's own rendering"
        ),
        "no_page_coordinates": (
            "the source format carries no fixed pagination, so page-level citation is unavailable"
        ),
        "embedded_media_not_extracted": (
            "the source embeds images or objects whose content is not extracted"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destinations-dir", type=Path, default=DEFAULT_DESTINATIONS)
    parser.add_argument("--extraction-dir", type=Path, default=DEFAULT_EXTRACTION)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--tmc-corpus", type=Path, default=DEFAULT_TMC_CORPUS)
    parser.add_argument("--ordinance-seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--previous-manifest", type=Path, default=None,
                        help="a single prior manifest; use --released-state for cumulative state")
    parser.add_argument("--released-state", type=Path, default=None,
                        help="cumulative ledger from topeka-release-ledger.py. Preferred: a single "
                             "prior manifest makes documents released earlier look new again")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="cap the eligible set (0 = no cap)")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    extractions = extraction_index(args.extraction_dir, args.tmc_corpus, args.ordinance_seed)
    receipts = {row["source_document_id"]: row for row in read_jsonl(args.checkpoint)}
    descriptions = limitation_descriptions()

    # Cumulative released state first. A document published in an earlier release
    # and not republished since is still published; comparing against only the
    # most recent manifest would classify it as new and re-release it.
    previous_versions: dict[str, str] = {}
    baseline = "none"
    if args.previous_manifest and args.previous_manifest.exists():
        payload = json.loads(args.previous_manifest.read_text(encoding="utf-8"))
        previous_versions = {
            entry["source_document_id"]: entry["document_version_id"]
            for entry in payload.get("documents", [])
        }
        baseline = "previous_manifest"
    if args.released_state and args.released_state.exists():
        for row in read_jsonl(args.released_state):
            previous_versions[row["source_document_id"]] = row["document_version_id"]
        baseline = "released_state_ledger" if baseline == "none" else "ledger_over_manifest"

    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in BUCKETS}

    for spec_id, spec in sorted(COLLECTIONS_BY_ID.items()):
        for lane, flagged in (("manifest", False), ("review", True)):
            path = args.destinations_dir / f"{spec.slug}.{lane}.jsonl"
            for record in read_jsonl(path):
                doc_id = record["source_document_id"]
                entry = {
                    "source_document_id": doc_id,
                    "collection_id": record["collection_id"],
                    "source_uri": record["source_uri"],
                    "listing_url": record.get("listing_url"),
                    "url_resolution": record.get("url_resolution"),
                    "sha256": record["sha256"],
                    "retained_artifact": record.get("retained_artifact"),
                    "publisher_key": doc_id.rsplit(":", 1)[-1],
                    "review_flags": record.get("review_flags") or [],
                }
                if flagged or entry["review_flags"]:
                    buckets["held_for_review"].append({
                        **entry,
                        "reason": "unresolved review flags; not eligible for the clean release lane",
                    })
                    continue

                extraction = extractions.get(record["sha256"])
                if extraction is None:
                    buckets["pending_extraction"].append({
                        **entry,
                        "reason": (
                            "no extraction exists for these exact bytes; the remote PDF path has not "
                            "been authorized" if record.get("retained_artifact", "").endswith(".pdf")
                            else "no extraction exists for these exact bytes"
                        ),
                    })
                    continue

                receipt = receipts.get(doc_id, {})
                version_id = f"{doc_id}@{record['sha256'][:16]}"
                selection = {
                    **entry,
                    "builder": extraction["builder"],
                    "media_type": receipt.get("content_type") or "application/octet-stream",
                    "observed_at": receipt.get("observed_at") or utc_now(),
                    "run_id": receipt.get("run_id"),
                    "extractor": extraction["extractor"],
                    "limitations": extraction.get("limitations", []),
                    "limitation_descriptions": descriptions,
                }
                if extraction["builder"] == "tmc_section":
                    selection["citation"] = extraction["citation"]
                elif extraction["builder"] == "retained_ordinance":
                    selection["legacy_id"] = extraction["legacy_id"]
                else:
                    selection["normalized_path"] = extraction["normalized_path"]
                    selection["structured_path"] = str(
                        Path(extraction["normalized_path"]).with_name("structured.json")
                    )
                    selection["page_unavailable_reason"] = (
                        "a DOCX has no fixed pagination, so no page coordinate is known for any span"
                    )
                prior = previous_versions.get(doc_id)
                if prior is None:
                    buckets["eligible_new"].append(selection)
                elif prior == version_id:
                    buckets["unchanged"].append({**entry, "reason": "already released at this version"})
                else:
                    buckets["eligible_changed"].append({**selection, "prior_version_id": prior})

    eligible = buckets["eligible_new"] + buckets["eligible_changed"]
    eligible.sort(key=lambda row: row["source_document_id"])
    if args.limit:
        eligible = eligible[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in eligible), encoding="utf-8"
    )

    total = sum(len(rows) for rows in buckets.values())
    report = {
        "artifact": "topeka_release_selection",
        "schema_version": "1.0",
        "selected_at": utc_now(),
        "offline": True,
        "previous_manifest": str(args.previous_manifest) if args.previous_manifest else None,
        "released_state": str(args.released_state) if args.released_state else None,
        "baseline": baseline,
        "documents_known_released": len(previous_versions),
        "counts": {name: len(buckets[name]) for name in BUCKETS},
        "documents_accounted_for": total,
        "selection_written": len(eligible),
        "selection_capped": bool(args.limit) and len(eligible) < len(buckets["eligible_new"]) + len(buckets["eligible_changed"]),
        "eligible_by_builder": dict(Counter(row["builder"] for row in eligible)),
        "pending_extraction_by_collection": dict(Counter(
            row["collection_id"] for row in buckets["pending_extraction"]
        )),
        "held_for_review_by_flag": dict(Counter(
            flag for row in buckets["held_for_review"] for flag in row["review_flags"]
        )),
        "note": (
            "every document in the destination manifests lands in exactly one bucket. Pending and "
            "held documents are not released and are not silently omitted either"
        ),
    }
    destination = args.report or (INSTANCE / "releases" / "proofs" / "release-selection.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for name in BUCKETS:
        print(f"  {name:22s} {len(buckets[name]):5d}")
    print(f"  {'accounted for':22s} {total:5d}")
    print(f"selection written        {len(eligible)} -> {args.output}")
    if buckets["pending_extraction"]:
        print(f"pending extraction by    {report['pending_extraction_by_collection']}")
    if buckets["held_for_review"]:
        print(f"held for review by flag  {report['held_for_review_by_flag']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
