# Topeka source documents — import guide

Release `topeka-portable-2026-09-16`, 3,088 documents,
jurisdiction `ks:city:topeka`.

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
| `ks:city:topeka:charter-ordinances` | Topeka Charter Ordinances | 41 |
| `ks:city:topeka:municipal-code` | Topeka Municipal Code | 2,702 |
| `ks:city:topeka:ordinances` | Topeka Ordinances | 335 |
| `ks:city:topeka:resolutions` | Topeka Resolutions | 10 |

`citations.jsonl` — 3,088 rows, one per citable thing, so a reader
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

- **544 documents pending extraction.**
  acquired from the publisher but not yet through an extraction path; the paid PDF path is not authorized. These documents exist and are accounted for, they are not lost.
- **3 documents held for review:**

| Document | Flags |
| --- | --- |
| `ks:city:topeka:ordinances:ordinance:20520` | identity_ambiguous |
| `ks:city:topeka:ordinances:ordinance:20610` | identity_ambiguous |
| `ks:city:topeka:ordinances:ordinance:sto` | membership_review_needed |

  unresolved doubt about identity or membership. Withheld deliberately; clearing a hold needs a signed resolution, not another run.

Coverage is `partial` for every collection. This package is what is ready now,
not the complete Topeka corpus.

## Not included by design

Embeddings and graph relationships are separate capabilities and are not part of
this handoff. Nothing here has been vector-indexed; `readiness.vector_indexing`
and `readiness.graph` read `pending` on every document, and that is accurate.
