# Topeka Public Law Access Packet

## Purpose

The goal is to obtain the current Topeka Municipal Code in a complete, searchable, auditable format before vectorization. Residents and businesses should be able to inspect the rules they are expected to follow. ExAIS will not mark the source production-ready until the text, citations, graph rows, and coverage pass the JSON artifact quality gate.

## Current Request

Request a complete current export of the Topeka Municipal Code with stable citations and source URLs. Acceptable formats include HTML, XML, JSON, Markdown, or another structured export that can be mapped into the ExAIS artifact contract.

Minimum requested fields per section:

- section citation;
- section title;
- full current section text;
- canonical public source URL;
- current-through ordinance number and date when available;
- internal code references when available;
- ordinance history when available.

Also request a table of contents or hierarchy export that maps code, title, division, chapter, article, section, and subsection relationships.

## Worklist Attachments

Run the artifact quality gate with `--worklist-dir` and attach:

- `missing-required-urls.jsonl` for every section/subsection URL still needed;
- `failed-crawl-urls.jsonl` for URLs that returned publisher challenge or fetch failures;
- `section-quality-issues.jsonl` for captured sections with missing text or citation fields;
- `unexpected-section-urls.jsonl` for records that do not match the expected URL manifest.

These files are generated from source artifacts only. They do not require embeddings, vectorization, Qdrant writes, or ExAIS document ingestion.

## Suggested Request Language

To whom it may concern:

We are requesting access to a complete, machine-readable copy of the current Topeka Municipal Code for public search, citation, and accessibility purposes. The requested data is the text of the rules and ordinances that residents and businesses are expected to follow.

Please provide the current Topeka Municipal Code as HTML, XML, JSON, Markdown, or another structured export, including section citations, section titles, full section text, canonical public URLs, current-through metadata, internal code references, ordinance history, and the table-of-contents hierarchy.

If a complete export is not available, please provide guidance on the approved method for obtaining the full current code without triggering publisher challenge pages, rate limits, or incomplete captures.

We are not requesting credentials, private data, or non-public administrative systems. The intended use is public access, search, and citation of municipal law.

## ExAIS Acceptance Boundary

The source can proceed to vectorization only after:

- every expected section/subsection URL is represented in `sections.jsonl`;
- every section has nonempty text;
- every section has a citation URL;
- graph artifacts contain hierarchy edges;
- crawl/import failures are zero;
- `scripts/release/topeka-code-artifact-quality.py` reports `passed: true` and `vectorization_allowed: true`.

Until then, Topeka codified-code remains JSON-only and `productionReady: false`.
