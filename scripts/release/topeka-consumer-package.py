#!/usr/bin/env python3
"""Wrap a self-contained release into a package a consumer can import and verify alone.

A release bundle is complete but producer-shaped: it assumes you know the
contract, and its `seed://` and `acquisition://` references only resolve on the
machine that made it. This turns one into a handoff:

  * every retained original travels inside it, so nothing points at a filesystem
    the consumer does not have;
  * a flat citation index, so the reader can resolve a citation without walking
    3,000 records;
  * the collection mapping, and what is deliberately NOT here -- documents still
    pending extraction, and documents held for review;
  * the two contract schemas, copied in;
  * verify.py, which needs only the Python standard library and the package
    itself. No checkout, no network, no dependencies.

    python scripts/release/topeka-consumer-package.py --bundle <release> --output-dir <package>

Offline. It reads a release and writes a package; it never mutates the release.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import (  # noqa: E402
    CONTRACTS,
    COLLECTIONS_BY_ID,
    ROOT,
    sha256_bytes,
    sha256_file,
)

INSTANCE = ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"

VERIFY_SCRIPT = '''#!/usr/bin/env python3
"""Verify this package. Standard library only; no checkout, network or install.

    python verify.py            # from inside the package directory
    python verify.py --package /path/to/package

Checks, in order:
  1. every file listed in package-manifest.json exists and hashes to its record;
  2. every document's own declared content hashes match its files;
  3. every citation in citations.jsonl resolves to a document that is here;
  4. every evidence reference with a quote matches the bytes at its offsets;
  5. the collection totals add up to the document count.

Exit status is 0 only if all of them pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    root = args.package

    manifest_path = root / "package-manifest.json"
    if not manifest_path.exists():
        print(f"FAIL package-manifest.json not found in {root}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    errors = []
    checked = 0

    # 1. every listed file is present and correct
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.exists():
            errors.append(f"missing file: {entry['path']}")
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            errors.append(f"hash mismatch: {entry['path']}")
        checked += 1

    # 2. each document's declared content matches what is here
    documents = {}
    for entry in manifest["documents"]:
        record_path = root / entry["record_path"]
        if not record_path.exists():
            errors.append(f"missing record: {entry['record_path']}")
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        documents[record["identity"]["source_document_id"]] = record
        folder = record_path.parent
        for role in ("verbatim", "normalized_text", "structured"):
            block = record["content"][role]
            artifact = folder / block["path"]
            if not artifact.exists():
                errors.append(f"{entry['source_document_id']}: missing {role}")
                continue
            if sha256_file(artifact) != block["sha256"]:
                errors.append(f"{entry['source_document_id']}: {role} hash mismatch")
        original = record["source"]["retained_original"]
        if not original.get("local_path"):
            errors.append(f"{entry['source_document_id']}: original does not travel in this package")
        else:
            artifact = folder / original["local_path"]
            if not artifact.exists():
                errors.append(f"{entry['source_document_id']}: missing original")
            elif sha256_file(artifact) != original["sha256"]:
                errors.append(f"{entry['source_document_id']}: original hash mismatch")

    # 3. citations resolve
    citations_path = root / "citations.jsonl"
    citation_count = 0
    if citations_path.exists():
        with citations_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                citation_count += 1
                if row["source_document_id"] not in documents:
                    errors.append(f"citation points at an absent document: {row['source_document_id']}")

    # 4. quoted evidence matches the bytes at its offsets
    spans = 0
    for doc_id, record in documents.items():
        folder = (root / manifest_index(manifest, doc_id)).parent
        text = None
        for reference in record["evidence"]["references"]:
            if reference["availability"] != "available":
                continue
            locator = reference.get("locator") or {}
            quote = reference.get("quote")
            if quote is None or reference["artifact"] != "normalized_text":
                continue
            if text is None:
                text = (folder / record["content"]["normalized_text"]["path"]).read_text(encoding="utf-8")
            start, end = locator.get("start"), locator.get("end")
            if start is None or end is None or text[start:end] != quote:
                errors.append(f"{doc_id}: evidence {reference['ref_id']} does not match its offsets")
            spans += 1

    # 5. collection totals add up
    collections = json.loads((root / "collections.json").read_text(encoding="utf-8"))
    total = sum(entry["document_count"] for entry in collections["collections"])
    if total != manifest["document_count"]:
        errors.append(f"collection totals {total} != document count {manifest['document_count']}")

    if not args.quiet:
        print(f"package            {root}")
        print(f"documents          {manifest['document_count']}")
        print(f"files verified     {checked}")
        print(f"citations resolved {citation_count}")
        print(f"evidence spans     {spans}")
        for message in errors[:20]:
            print(f"  ERROR {message}")
        print(f"result             {'PASS' if not errors else 'FAIL'} ({len(errors)} error(s))")
    return 0 if not errors else 1


def manifest_index(manifest, doc_id):
    for entry in manifest["documents"]:
        if entry["source_document_id"] == doc_id:
            return entry["record_path"]
    raise KeyError(doc_id)


if __name__ == "__main__":
    raise SystemExit(main())
'''


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_citations(documents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One flat row per citable thing, so a reader never walks every record."""
    rows: list[dict[str, Any]] = []
    for doc_id, record in sorted(documents.items()):
        meaning, source = record["meaning"], record["source"]
        for citation in meaning["citations"]:
            rows.append({
                "source_document_id": doc_id,
                "document_version_id": record["identity"]["document_version_id"],
                "collection_id": record["identity"]["collection_id"],
                "label": citation["label"],
                "url": citation["url"],
                "scope": citation.get("scope") or "document",
                "official_url": source["official_url"],
                "document_type": meaning["document_type"],
                "title": meaning.get("title"),
                "publisher_number": meaning.get("publisher_number"),
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selection-report", type=Path,
                        default=INSTANCE / "releases" / "proofs" / "release-selection.json")
    parser.add_argument("--holds", type=Path, default=INSTANCE / "destinations" / "review-holds.jsonl")
    parser.add_argument("--archive", action="store_true", help="also write a .tar.gz beside the package")
    args = parser.parse_args()

    manifest_path = args.bundle / "release-manifest.json"
    if not manifest_path.exists():
        print(f"FAIL {manifest_path} is absent")
        return 1
    release = json.loads(manifest_path.read_text(encoding="utf-8"))

    absent = [
        entry["source_document_id"]
        for entry in release["documents"]
        for file_entry in entry["files"]
        if not file_entry["present"]
    ]
    if absent:
        print(
            f"FAIL {len(absent)} document(s) reference files that do not travel in this release "
            f"(e.g. {absent[0]}). Export with originals included before packaging."
        )
        return 1

    package = args.output_dir
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)

    # Copy the release verbatim. The package adds to it; it never edits it.
    shutil.copytree(args.bundle / "documents", package / "documents")
    shutil.copy2(manifest_path, package / "release-manifest.json")
    (package / "contracts").mkdir()
    for schema in ("jurisdiction-document-release.schema.json", "jurisdiction-source-document.schema.json"):
        shutil.copy2(CONTRACTS / schema, package / "contracts" / schema)

    documents = {}
    for entry in release["documents"]:
        record = json.loads((package / entry["record_path"]).read_text(encoding="utf-8"))
        documents[record["identity"]["source_document_id"]] = record

    citations = build_citations(documents)
    (package / "citations.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in citations), encoding="utf-8"
    )

    by_collection = Counter(
        record["identity"]["collection_id"] for record in documents.values()
    )
    selection = {}
    if args.selection_report.exists():
        selection = json.loads(args.selection_report.read_text(encoding="utf-8"))
    holds = read_jsonl(args.holds)

    collections = {
        "jurisdiction_key": release["jurisdiction"]["key"],
        "jurisdiction_aliases": release["jurisdiction"]["aliases"],
        "release_id": release["release"]["release_id"],
        "collections": [
            {
                "collection_id": collection_id,
                "name": COLLECTIONS_BY_ID[collection_id].name if collection_id in COLLECTIONS_BY_ID else collection_id,
                "master_source_url": (
                    COLLECTIONS_BY_ID[collection_id].master_source_url
                    if collection_id in COLLECTIONS_BY_ID else None
                ),
                "document_count": count,
                "coverage": "partial",
            }
            for collection_id, count in sorted(by_collection.items())
        ],
        "not_in_this_package": {
            "pending_extraction": (selection.get("counts") or {}).get("pending_extraction"),
            "pending_extraction_by_collection": selection.get("pending_extraction_by_collection"),
            "pending_reason": (
                "acquired from the publisher but not yet through an extraction path; the paid PDF "
                "path is not authorized. These documents exist and are accounted for, they are not lost."
            ),
            "held_for_review": [
                {"source_document_id": row["source_document_id"], "review_flags": row["review_flags"]}
                for row in holds
            ],
            "held_reason": (
                "unresolved doubt about identity or membership. Withheld deliberately; clearing a "
                "hold needs a signed resolution, not another run."
            ),
        },
    }
    (package / "collections.json").write_text(
        json.dumps(collections, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    (package / "verify.py").write_text(VERIFY_SCRIPT, encoding="utf-8")
    (package / "IMPORT.md").write_text(import_instructions(release, collections, len(citations)), encoding="utf-8")

    files = []
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.name != "package-manifest.json":
            files.append({
                "path": path.relative_to(package).as_posix(),
                "sha256": sha256_file(path),
                "byte_count": path.stat().st_size,
            })

    package_manifest = {
        "artifact": "topeka_consumer_package",
        "schema_version": "1.0",
        "packaged_at": utc_now(),
        "release_id": release["release"]["release_id"],
        "jurisdiction_key": release["jurisdiction"]["key"],
        "document_count": release["inventory"]["document_count"],
        "citation_count": len(citations),
        "inventory_sha256": release["inventory"]["inventory_sha256"],
        "self_contained": True,
        "documents": [
            {
                "source_document_id": entry["source_document_id"],
                "document_version_id": entry["document_version_id"],
                "collection_id": entry["collection_id"],
                "record_path": entry["record_path"],
            }
            for entry in release["documents"]
        ],
        "files": files,
        "file_count": len(files),
        "byte_count": sum(entry["byte_count"] for entry in files),
        "verify_command": ["python", "verify.py"],
    }
    (package / "package-manifest.json").write_text(
        json.dumps(package_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    archive_info = None
    if args.archive:
        archive_path = package.parent / f"{package.name}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(package, arcname=package.name)
        archive_info = {
            "path": str(archive_path),
            "sha256": sha256_file(archive_path),
            "byte_count": archive_path.stat().st_size,
        }
        (package.parent / f"{package.name}.tar.gz.sha256").write_text(
            f"{archive_info['sha256']}  {archive_path.name}\n", encoding="utf-8"
        )

    print(f"package            {package}")
    print(f"documents          {package_manifest['document_count']:,}")
    print(f"citations          {package_manifest['citation_count']:,}")
    print(f"files              {package_manifest['file_count']:,}")
    print(f"bytes              {package_manifest['byte_count']:,}")
    for entry in collections["collections"]:
        print(f"  {entry['collection_id']:38s} {entry['document_count']:5d}")
    pending = collections["not_in_this_package"]["pending_extraction"]
    print(f"  {'(pending extraction, not included)':38s} {pending}")
    print(f"  {'(held for review, not included)':38s} {len(holds)}")
    if archive_info:
        print(f"archive            {archive_info['path']}")
        print(f"archive sha256     {archive_info['sha256']}")
    return 0


def import_instructions(release: dict[str, Any], collections: dict[str, Any], citation_count: int) -> str:
    rows = "\n".join(
        f"| `{entry['collection_id']}` | {entry['name']} | {entry['document_count']:,} |"
        for entry in collections["collections"]
    )
    held = "\n".join(
        f"| `{row['source_document_id']}` | {', '.join(row['review_flags'])} |"
        for row in collections["not_in_this_package"]["held_for_review"]
    ) or "| _none_ | |"
    return f"""# Topeka source documents — import guide

Release `{release['release']['release_id']}`, {release['inventory']['document_count']:,} documents,
jurisdiction `{release['jurisdiction']['key']}`.

This package is self-contained. Every original file travels inside it; nothing
points at the producing machine. Verify it before importing:

```bash
python verify.py
```

That needs only the Python standard library — no checkout, no network, no
install. It re-hashes every file, resolves every citation to a document that is
present, and checks every quoted evidence span against the bytes at its offsets.

## What is here

| Collection | Name | Documents |
| --- | --- | --- |
{rows}

`citations.jsonl` — {citation_count:,} rows, one per citable thing, so a reader
can resolve a citation without walking every record.

## Layout

```
package-manifest.json     every file with its hash; what verify.py checks
release-manifest.json     the release's own inventory and provenance
collections.json          collection mapping, and what is deliberately absent
citations.jsonl           flat citation index
contracts/                the two JSON Schemas these records conform to
documents/<id>/
  record.json             identity, source, content, evidence, meaning, readiness
  verbatim.*              untouched extractor output
  normalized.*            readable text — this is what a reader displays
  structured.json         blocks, tables, definitions, with component ids
  files/<original>        the publisher's own bytes
verify.py                 standalone verifier
```

## Importing

1. **Identity.** Key on `identity.source_document_id`; it is stable across
   versions. `identity.document_version_id` changes when the publisher's bytes
   change, so store both and compare the version to detect a stale copy.
2. **Readable text.** `content.normalized_text.path`. Its `normalizations` list
   says exactly what was done to it.
3. **Original download.** `source.retained_original.local_path` inside the
   document folder, with `sha256` and the publisher's `official_url`.
4. **Citations.** `meaning.citations`, or `citations.jsonl` for all of them.
5. **Evidence.** `evidence.references` carry `utf8_char_offset` spans into the
   normalized text, half-open `[start, end)`. A reference marked `unavailable`
   has no coordinate and a reason — most often that a PDF's page numbers are
   unknown. **Do not infer page numbers**; the producer refuses to, and so
   should the reader.
6. **Meaning is not fact.** `meaning.relationships` carry `resolved: true|false`.
   A `false` is a textual match, not an established link. `extraction_quality`
   and `review` are separate: successful extraction is not review.

## What is deliberately NOT here

- **{collections['not_in_this_package']['pending_extraction']} documents pending extraction.**
  {collections['not_in_this_package']['pending_reason']}
- **{len(collections['not_in_this_package']['held_for_review'])} documents held for review:**

| Document | Flags |
| --- | --- |
{held}

  {collections['not_in_this_package']['held_reason']}

Coverage is `partial` for every collection. This package is what is ready now,
not the complete Topeka corpus.

## Not included by design

Embeddings and graph relationships are separate capabilities and are not part of
this handoff. Nothing here has been vector-indexed; `readiness.vector_indexing`
and `readiness.graph` read `pending` on every document, and that is accurate.
"""


if __name__ == "__main__":
    raise SystemExit(main())
