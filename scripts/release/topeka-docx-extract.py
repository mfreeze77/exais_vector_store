#!/usr/bin/env python3
"""Extract text and structure from the DOCX instruments the city publishes.

Topeka publishes some recent ordinances and resolutions only as ``.docx``. They
do not need the bounded remote PDF path: a DOCX is a ZIP holding
``word/document.xml``, so this reads them with the standard library and costs
nothing per document.

    python scripts/release/topeka-docx-extract.py --acquisition-dir <dir> --output-dir <dir>

Offline: no network, no remote service, no API, no database. Safe to run with
external calls disabled.

Two things this deliberately does NOT do:

* **It does not invent page coordinates.** A DOCX carries no fixed pagination;
  pages are a rendering decision. Character offsets into the extracted text are
  the coordinate space, exactly as for the Marker-extracted PDFs.
* **It does not resolve tracked changes.** Where the publisher left revision
  markup in the file, the inserted and deleted runs are reported rather than
  silently flattened into one reading -- which is the defect already recorded
  for the PDF path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import ROOT, sha256_bytes, sha256_text  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

DEFAULT_ACQUISITION = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code" / "acquisition"
)
DEFAULT_OUTPUT = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code" / "extraction"
)

EXTRACTOR_NAME = "exais-docx-extract"
EXTRACTOR_VERSION = "1.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _paragraph_text(node: ET.Element) -> tuple[str, dict[str, int]]:
    """Visible text of one paragraph, plus counts of revision markup found.

    ``w:ins`` and ``w:del`` are tracked insertions and deletions. Deleted text
    lives in ``w:delText`` and is excluded from the reading text, but its
    presence is counted so the document can be marked as carrying unresolved
    revisions rather than passing as clean.
    """
    parts: list[str] = []
    marks = {"insertions": 0, "deletions": 0}
    for element in node.iter():
        tag = element.tag
        if tag == f"{W}ins":
            marks["insertions"] += 1
        elif tag == f"{W}del":
            marks["deletions"] += 1
        elif tag == f"{W}t":
            parts.append(element.text or "")
        elif tag == f"{W}tab":
            parts.append("\t")
        elif tag in {f"{W}br", f"{W}cr"}:
            parts.append("\n")
    return "".join(parts), marks


def _style(node: ET.Element) -> str:
    style = node.find(f"{W}pPr/{W}pStyle")
    return (style.get(f"{W}val") or "") if style is not None else ""


def extract_docx(payload: bytes) -> dict[str, Any]:
    """Reading text, block structure and tables from one DOCX."""
    with zipfile.ZipFile(__import__("io").BytesIO(payload)) as archive:
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            raise ValueError("not a Word document: word/document.xml is absent")
        document = ET.fromstring(archive.read("word/document.xml"))
        has_media = any(name.startswith("word/media/") for name in names)

    body = document.find(f"{W}body")
    if body is None:
        raise ValueError("DOCX has no body element")

    blocks: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    revisions = {"insertions": 0, "deletions": 0}

    for child in body:
        if child.tag == f"{W}p":
            text, marks = _paragraph_text(child)
            revisions["insertions"] += marks["insertions"]
            revisions["deletions"] += marks["deletions"]
            if not text.strip():
                continue
            style = _style(child)
            blocks.append({
                "kind": "heading" if style.lower().startswith("heading") else "paragraph",
                "order": len(blocks),
                "text": " ".join(text.split()),
                "style": style or None,
            })
        elif child.tag == f"{W}tbl":
            rows: list[list[str]] = []
            for row in child.findall(f"{W}tr"):
                cells = []
                for cell in row.findall(f"{W}tc"):
                    cell_text = " ".join(
                        " ".join(_paragraph_text(p)[0].split())
                        for p in cell.findall(f"{W}p")
                    ).strip()
                    cells.append(cell_text)
                rows.append(cells)
            if rows:
                index = len(tables)
                tables.append({"order": index, "rows": rows, "row_count": len(rows)})
                blocks.append({
                    "kind": "table",
                    "order": len(blocks),
                    "text": "\n".join("\t".join(row) for row in rows),
                    "table_index": index,
                })

    text = "\n\n".join(block["text"] for block in blocks)
    normalized = (text.strip() + "\n") if text.strip() else ""

    limitations: list[dict[str, str]] = []
    if revisions["insertions"] or revisions["deletions"]:
        limitations.append({
            "code": "unresolved_tracked_changes",
            "description": (
                f"the file carries {revisions['insertions']} tracked insertion(s) and "
                f"{revisions['deletions']} deletion(s). Deleted runs are excluded from the reading "
                "text and the document needs review against the publisher's own rendering."
            ),
            "affects": "readable_text",
        })
    limitations.append({
        "code": "no_page_coordinates",
        "description": (
            "a DOCX has no fixed pagination, so page-level citation is unavailable. Character "
            "offsets into the extracted text are the coordinate space."
        ),
        "affects": "evidence",
    })
    if has_media:
        limitations.append({
            "code": "embedded_media_not_extracted",
            "description": "the document embeds images or objects whose content is not extracted here.",
            "affects": "completeness",
        })

    return {
        "normalized_text": normalized,
        "blocks": blocks,
        "tables": tables,
        "revisions": revisions,
        "limitations": limitations,
        "usable_text": bool(normalized.strip()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--acquisition-dir", type=Path, default=DEFAULT_ACQUISITION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    sources = sorted(args.acquisition_dir.glob("*/raw/*/*.docx"))
    if args.limit:
        sources = sources[: args.limit]

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for path in sources:
        payload = path.read_bytes()
        collection = path.relative_to(args.acquisition_dir).parts[0]
        document_key = path.parent.name
        try:
            extracted = extract_docx(payload)
        except Exception as exc:  # a malformed file must be visible, not skipped
            failures.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not extracted["usable_text"]:
            failures.append({"path": str(path), "error": "extraction produced no usable text"})
            continue

        target = args.output_dir / collection / document_key
        target.mkdir(parents=True, exist_ok=True)
        text_path = target / "normalized.txt"
        structured_path = target / "structured.json"
        text_path.write_text(extracted["normalized_text"], encoding="utf-8")
        structured_path.write_text(
            json.dumps(
                {"blocks": extracted["blocks"], "tables": extracted["tables"]},
                indent=2, sort_keys=True, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        results.append({
            "collection": collection,
            "document_key": document_key,
            "source_path": str(path),
            "source_sha256": sha256_bytes(payload),
            "normalized_path": str(text_path),
            "normalized_sha256": sha256_text(extracted["normalized_text"]),
            "char_count": len(extracted["normalized_text"]),
            "block_count": len(extracted["blocks"]),
            "table_count": len(extracted["tables"]),
            "limitations": [item["code"] for item in extracted["limitations"]],
            "extractor": {"name": EXTRACTOR_NAME, "version": EXTRACTOR_VERSION, "mode": "local_docx_xml"},
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "artifact": "topeka_docx_extraction",
        "schema_version": "1.0",
        "observed_at": utc_now(),
        "offline": True,
        "remote_service_used": False,
        "cost_incurred": 0,
        "selected": len(sources),
        "extracted": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
        "passed": bool(sources) and not failures,
    }
    (args.output_dir / "docx-extraction-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"docx files found   {len(sources)}")
    print(f"extracted          {len(results)}")
    print(f"failed             {len(failures)}")
    for failure in failures[:10]:
        print(f"  FAILED {failure['path']}: {failure['error']}")
    if results:
        chars = sum(row["char_count"] for row in results)
        print(f"characters         {chars:,} across {sum(r['block_count'] for r in results)} blocks")
        needing_review = [r for r in results if "unresolved_tracked_changes" in r["limitations"]]
        print(f"tracked changes    {len(needing_review)} document(s) need review")
    print(f"remote cost        0 (local extraction)")
    print(f"result             {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
