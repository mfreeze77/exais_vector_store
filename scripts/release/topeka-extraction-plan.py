"""Plan extraction by actual file format, with a bounded pilot and a spend cap.

Not every acquired document needs the paid remote path. This measures the held
corpus by media type, routes each format to the path that actually handles it,
and sizes only the remainder as remote PDF work.

    python scripts/release/topeka-extraction-plan.py --unit-price-per-page 0.004

Offline: it reads held bytes and writes a plan. It calls no extraction service
and spends nothing. The unit price is an operator input with no default,
because this repository records no rate card -- a cost estimate with an invented
unit price would be worse than none.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extraction_budget import pdf_page_estimate  # noqa: E402
from jurisdiction_release_contract import ROOT  # noqa: E402

INSTANCE = ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
DEFAULT_ACQUISITION = INSTANCE / "acquisition"
DEFAULT_EXTRACTION = INSTANCE / "extraction"
DEFAULT_SEED = INSTANCE / "sources" / "topeka-ordinances" / "seed"

# Which path actually handles which format. A format with no path is reported as
# unsupported rather than quietly assigned to the PDF pipeline.
FORMAT_PATHS: dict[str, dict[str, Any]] = {
    ".pdf": {
        "path": "bounded_remote_marker",
        "entrypoint": "scripts/release/topeka-ordinance-pdf-extract.py",
        "billable": True,
        "note": "external RunPod Marker; the only path in this plan that costs money",
    },
    ".docx": {
        "path": "local_docx_xml",
        "entrypoint": "scripts/release/topeka-docx-extract.py",
        "billable": False,
        "note": "a DOCX is a ZIP holding word/document.xml; extracted locally with the standard library",
    },
}




def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def already_extracted(seed: Path, extraction: Path) -> set[str]:
    """Documents whose extraction already exists and needs no re-spend."""
    done: set[str] = set()
    for row in read_jsonl(seed / "manifests" / "ordinance-extractions.jsonl"):
        if (seed / row["markdown_path"]).exists():
            done.add(row["markdown_sha256"])
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--acquisition-dir", type=Path, default=DEFAULT_ACQUISITION)
    parser.add_argument("--extraction-dir", type=Path, default=DEFAULT_EXTRACTION)
    parser.add_argument("--ordinance-seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--unit-price-per-page", type=float, default=None,
                        help="operator's Marker rate per page; omit to size the workload without a total")
    parser.add_argument("--pilot-size", type=int, default=10,
                        help="documents in the bounded pilot after Resolution 9749")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    checkpoint = {
        row["source_document_id"]: row
        for row in read_jsonl(args.acquisition_dir / "acquisition-checkpoint.jsonl")
    }
    report_path = args.extraction_dir / "docx-extraction-report.json"
    extracted_locally: set[tuple[str, str]] = set()
    if report_path.exists():
        extracted_locally = {
            (row["collection"], row["document_key"])
            for row in json.loads(report_path.read_text(encoding="utf-8")).get("results", [])
        }

    by_format: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unsupported: list[dict[str, Any]] = []

    for doc_id, row in sorted(checkpoint.items()):
        saved = row.get("saved_path")
        if not saved:
            continue
        path = Path(saved)
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        handler = FORMAT_PATHS.get(suffix)
        entry = {
            "source_document_id": doc_id,
            "collection_id": row["collection_id"],
            "path": str(path),
            "byte_count": row.get("byte_count") or path.stat().st_size,
            "suffix": suffix,
        }
        if handler is None:
            unsupported.append(entry)
            continue
        by_format[suffix].append(entry)

    # Ordinance and charter PDFs already have retained Marker output; they are
    # excluded from the billable workload rather than paid for twice.
    retained_extractions = len(read_jsonl(args.ordinance_seed / "manifests" / "ordinance-extractions.jsonl"))

    pdf_entries = by_format.get(".pdf", [])
    billable: list[dict[str, Any]] = []
    for entry in pdf_entries:
        collection = entry["collection_id"].rsplit(":", 1)[-1]
        key = Path(entry["path"]).parent.name
        if (collection, key) in extracted_locally:
            continue
        # Only documents acquired here need extraction; the retained ordinance
        # corpus was extracted in August and is reused by hash.
        if "/acquisition/" not in entry["path"]:
            continue
        payload = Path(entry["path"]).read_bytes()
        pages, basis = pdf_page_estimate(payload)
        billable.append({**entry, "page_estimate": pages, "page_estimate_basis": basis})

    total_pages = sum(entry["page_estimate"] for entry in billable)
    pilot_first = next(
        (entry for entry in billable if entry["source_document_id"].endswith(":09749")), None
    )
    remaining = [entry for entry in billable if entry is not pilot_first]
    remaining.sort(key=lambda entry: entry["page_estimate"])
    pilot = ([pilot_first] if pilot_first else []) + remaining[: max(args.pilot_size - 1, 0)]
    pilot_pages = sum(entry["page_estimate"] for entry in pilot)

    def money(pages: int) -> float | None:
        if args.unit_price_per_page is None:
            return None
        return round(pages * args.unit_price_per_page, 2)

    plan = {
        "artifact": "topeka_extraction_plan",
        "schema_version": "1.0",
        "planned_at": utc_now(),
        "offline": True,
        "extraction_service_called": False,
        "spend_incurred": 0,
        "unit_price_per_page": args.unit_price_per_page,
        "unit_price_source": (
            "operator input" if args.unit_price_per_page is not None
            else "NOT SUPPLIED - this repository records no Marker rate card, so no total is estimated"
        ),
        "by_format": [
            {
                "suffix": suffix,
                "documents": len(entries),
                "byte_count": sum(entry["byte_count"] for entry in entries),
                **FORMAT_PATHS[suffix],
            }
            for suffix, entries in sorted(by_format.items())
        ],
        "unsupported_formats": [
            {"suffix": suffix, "documents": count}
            for suffix, count in sorted(Counter(entry["suffix"] for entry in unsupported).items())
        ],
        "already_done": {
            "local_docx_extractions": len(extracted_locally),
            "retained_marker_extractions": retained_extractions,
            "note": "neither is re-extracted; retained Marker output is reused by hash",
        },
        "billable_remote_workload": {
            "documents": len(billable),
            "page_estimate": total_pages,
            "page_estimate_basis": dict(Counter(entry["page_estimate_basis"] for entry in billable)),
            "page_estimate_caveat": (
                "an estimate, not a measurement: page_tree_count is authoritative, page_object_scan "
                "undercounts compressed files, byte_size_heuristic is a size proxy. Reconcile against "
                "the pilot's actual billed pages before authorizing stage 2"
            ),
            "estimated_cost": money(total_pages),
        },
        "bounded_pilot": {
            "rationale": (
                "Resolution 9749 first because it is the owner's named example and the one document "
                "the starter release is waiting on; then the smallest remaining documents, so a "
                "quality problem surfaces cheaply before the bulk run"
            ),
            "documents": [
                {
                    "source_document_id": entry["source_document_id"],
                    "page_estimate": entry["page_estimate"],
                    "byte_count": entry["byte_count"],
                }
                for entry in pilot
            ],
            "document_count": len(pilot),
            "page_estimate": pilot_pages,
            "estimated_cost": money(pilot_pages),
            "gate": (
                "the pilot's extracted text must validate through the document release contract "
                "before any further spend; a degraded result stops the run"
            ),
        },
        "remaining_after_pilot": {
            "documents": len(billable) - len(pilot),
            "page_estimate": total_pages - pilot_pages,
            "estimated_cost": money(total_pages - pilot_pages),
        },
        "spending_cap": {
            "structure": "two-stage, each stage separately authorized",
            "stage_1_pilot_cap_pages": pilot_pages,
            "stage_2_bulk_cap_pages": total_pages - pilot_pages,
            "hard_cap_pages": total_pages,
            "enforcement": (
                "MARKER_MAX_ATTEMPTS bounds retries per document. A run that would exceed its stage's "
                "page cap stops rather than continuing, and stage 2 needs its own authorization even "
                "after the pilot passes"
            ),
            "not_enforced_in_code_yet": True,
        },
        "notes": [
            "No TMC re-crawl is required: the retained corpus is complete and hash-verified, so no "
            "Decodo token is needed for this work.",
            "The DOCX path costs nothing and is already run; it is not part of any cap.",
        ],
    }

    destination = args.output or (INSTANCE / "releases" / "proofs" / "topeka-extraction-plan.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("held documents by format")
    for row in plan["by_format"]:
        cost = "billable" if row["billable"] else "free (local)"
        print(f"  {row['suffix']:6s} {row['documents']:5d} docs  {row['byte_count']:>12,} bytes  {cost}")
    for row in plan["unsupported_formats"]:
        print(f"  {row['suffix']:6s} {row['documents']:5d} docs  NO EXTRACTION PATH")
    print(f"already extracted    local docx {plan['already_done']['local_docx_extractions']}, "
          f"retained marker {plan['already_done']['retained_marker_extractions']}")
    billable_block = plan["billable_remote_workload"]
    print(f"billable remote      {billable_block['documents']} documents, "
          f"~{billable_block['page_estimate']} pages")
    pilot_block = plan["bounded_pilot"]
    print(f"bounded pilot        {pilot_block['document_count']} documents, "
          f"~{pilot_block['page_estimate']} pages")
    if pilot_block["documents"]:
        print(f"  first: {pilot_block['documents'][0]['source_document_id']}")
    if args.unit_price_per_page is None:
        print("estimated cost       NOT ESTIMATED - supply --unit-price-per-page from the RunPod account")
    else:
        print(f"estimated cost       pilot ${pilot_block['estimated_cost']}, "
              f"bulk ${plan['remaining_after_pilot']['estimated_cost']}, "
              f"cap ${billable_block['estimated_cost']}")
    print(f"plan                 {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
