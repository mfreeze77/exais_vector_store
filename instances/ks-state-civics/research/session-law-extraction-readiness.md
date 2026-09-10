# Session Laws extraction: measured handoff readiness

Read-only audit, 2026-09-10. StateCivics retains ownership of acquisition,
custody, canonical spans/actions and KS-600/650 contracts. This report records
what ExAIS verified; it is not an upstream export, registration receipt or
end-to-end GraphRAG acceptance result.

## Verified artifact inventory

Root: `/Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws`.
Manifest: `session_laws_extraction_manifest.json`, generated
`2026-09-10T23:49:11Z`; inspected manifest SHA-256:
`3c5cf2f3b693b51be135ce7b19098af2289ba1ac678d2de486d9ea6b910b6154`.

All seven retained PDF hashes and Markdown hashes match their extraction
records. Source/output byte counts and decoded UTF-8 character counts match.
Each Markdown has exactly the unique, ordered page markers `1..pages` declared
for its book. Declared pages total **6,587**; characters total **18,264,381**.
This proves the measured inventory and byte relationships, not lossless text
extraction or the correctness of every legal assertion.

| Book | Declared pages / matching page markers |
|---|---:|
| 2023 Book 1 | 891 |
| 2023 Book 2 | 938 |
| 2024 Book 1 | 894 |
| 2024 Book 2 | 894 |
| 2024 Book 3 | 830 |
| 2025 Book 1 | 1,068 |
| 2025 Book 2 | 1,072 |

## Corrected complete clause

Artifact: `markdown/2025-Session-Laws-Book-2.md`.
Output SHA-256:
`3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7`.
The retained PDF hash is recorded in the [provision review](sb125-provision-handoff.md).

For section 96(j), PDF page **358**, printed page **1406**:

- **Unicode code-point offsets, zero-based, end-exclusive:** `[986097, 986411)`.
- **UTF-8 byte offsets, zero-based, end-exclusive:** `[992620, 992936)`.
- Exact selected text: 314 code points, 316 UTF-8 bytes, starting at `(j)` and
  ending with the period after `lapsed.`; trailing whitespace is excluded.
- Selected text SHA-256 over UTF-8:
  `3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6`.

The manager's reported `[986097, 986383)` range stops **before** the phrase
`$4,000,000 is hereby lapsed`. That phrase begins at code-point offset 986383.
The shorter range cannot support the lapse amount or operation. Including the
endpoint as one character would still not capture the clause.

Coordinates apply to the exact UTF-8-decoded output bytes, with no whitespace,
newline, Unicode or dehyphenation normalization. A future extraction needs its
own evidence coordinates/hash; legal provision identity remains separate.
The section heading supplies agency context on page 351. Its evidence must be
linked separately rather than pretending this subsection names the agency.

## Quality workflow: what the current code actually does

Upstream paths below are relative to `operator-source://statecivics-ai`, inspected
on main `1649b8ad`. No upstream commands or code were changed during this review.

| Finding | Existing owner / code anchor |
|---|---|
| All three named QA fields are absent from all seven sidecars and manifest records, rather than explicit JSON nulls. `extract_doc` does not emit them. | `scripts/operator/extract_fiscal_corpus_cpu.py:495` |
| Probe excludes Session Laws through the default corpus selector and has no explicit `--only` option; extraction has an override. Probe writes a separate JSON, never enriches the Markdown sidecars/manifest. | same file, `:37`, `:65`, `:117`, `:542`, `:597` |
| Numeric validation also excludes Session Laws and lacks explicit selection. Empty selection reaches an empty-list summary; missing numbers do not themselves cause a nonzero exit. Output JSON is separate from the extraction manifest. | `scripts/operator/validate_fiscal_extraction_numbers.py:39`, `:88`, `:115`, `:124` |
| Raw fiscal registration excludes Session Laws, accepts download records, and sets raw-PDF extraction status to pending. It does not register these Markdown extractions. | `scripts/operator/register_fiscal_document_corpus.py:159`, `:298`, `:447` |
| Re-registering the same artifact and hash returns the existing revision unchanged, without backfilling extraction metadata. | `src/kansas_accountability/services/civic_impact/source_artifact_service.py:177` |

The older fiscal slim manifest has enriched QA fields, but the code review found
no tracked enrichment implementation for those field names. Running the existing
probe alone will not populate them for the seven books.

Probe scans every page but classifies the document in aggregate; isolated poor
pages can be hidden by the aggregate. Numeric validation compares per-page
multisets of thousands-separated integer strings. It does not establish account
codes, dates, signs, decimal fractions, uncommaed values or their relationship to
a clause. Character retention is a document aggregate and can be inflated by
headings, markers or duplicate text. Even a clean numeric result would not catch
the truncated evidence selection above. Preserve actual page coverage, counts,
denominators and findings instead of treating exit zero as QA acceptance.

## Recommended bounded upstream work

1. Under the existing extraction/span owner, add explicit selection for probe
   and numeric validation while preserving their budget-only defaults. Require
   the expected seven books; reject empty, missing, duplicate or unexpected
   selections. Validate the existing Markdown; this audit supplies no reason
   to re-extract it.
2. Retain a reproducible QA result bound to both source and extraction hashes,
   tool/version, coverage, findings and review outcome. If summary fields are
   enriched, derive them from that result without rewriting Markdown bytes.
   Review all material fields and the complete subsection against the retained
   source; aggregate metrics do not approve an appropriation assertion.
3. Resolve raw artifact/revision identity plus hash before registration; reuse
   existing records when present. Missing raw sources need a bounded Session
   Law registration path with the correct source family/type. Register the
   Markdown as a derived extraction with its raw-source/derivation linkage,
   rather than making a duplicate raw revision merely to attach QA metadata.
4. Persist the exact span and source-bound action using the reviewed output
   and coordinate convention. Preserve the unresolved composite account link.
   KS-600/650 schema implementation can proceed alongside QA and registration.

Raw custody may be established before quality review; custody alone does not
mean reviewed or publishable. The recommendation is to validate before treating
the derived extraction as reviewed. Rerunning the current raw registrar is not
a supported metadata-backfill workflow.

The SourceSpan contract already supports PDF `page_region` and `page_lines` as
well as `text_offsets`. Bulk Markdown extraction is not an intrinsic prerequisite
for every possible PDF span or for defining provision identity. **Markdown
character offsets do require the exact retained text and its hash.** The CPU
inventory's retrieval-only status does not automatically become Marker handoff
acceptance; this prose-span use needs its own validated derivation/review under
the existing upstream owners.

This review does not establish that section 96(j) was never amended by any later
instrument. The earlier Chapter 128 check remains limited to that chapter.

Verification used Python standard-library hashing/JSON/regex for the measured
artifacts and a separate read-only agent for producer-code review. No probe,
extraction, registration, database query or runtime integration was executed.
Independent review of the authored report and related documentation returned
**PASS**; local link checks and `git diff --check` also passed.
