# StateCivics fiscal GraphRAG operator path

**Acceptance reopened after real-corpus inspection (2026-09-10).** The v1 path
below assumes PDF-backed evidence for every entity. The retained KanView corpus
shows that assumption is wrong for account/agency/fund observations, and the
current narrative chunks lack the assumed page fields. See
[the real-data correction and reproducible audit](FISCAL_GRAPH_REAL_DATA.md).
The legacy build/load/evaluate commands describe the implemented v1 mechanics; they are not a ready
activation path for the real State Civics fiscal graph.

The [agreed StateCivics handoff](STATECIVICS_LAW_MONEY_ALIGNMENT.md) supersedes
those design assumptions. WAVE-133/134 must consume KS-650's extension of the
existing upstream exporter, including typed structured evidence, provision
references from KS-600, and action/fact lineage through derivation records.
WAVE-135/136 must prove useful real-source paths and answers before WAVE-132's
integrated activation gate can pass. Legacy build/load/evaluate remain v1
mechanics, not the corrected contract or a request to activate it.

## Offline structured evidence verification

WAVE-133's independent foundation adds `verify-structured-evidence` to the
existing CLI. It verifies local UTF-8 CSV bytes against an expected source hash
and exact one-based data-record hashes. Run it inside the existing ExAIS test or
operator container with the source and reference files mounted read-only:

```console
python scripts/release/kansas-fiscal-graphrag.py verify-structured-evidence \
  --source-csv /corpus/data/kanview/FY2026/ExpData_652_2026.csv \
  --source-sha256 ea386136d6135334aa71f84331ec8ab68b2d5c83d9b992efe72b41e1a569eaed \
  --records /evidence/record-references.json
```

The reference file is a JSON array of `data_record_1based` and
`raw_record_sha256` pairs from the retained-source audit or upstream evidence.
The record digest covers canonical JSON `{"headers": [...], "values": [...]}`,
preserving parsed strings, leading zeroes, empty fields, and quoted newlines.
The source digest covers the original bytes. A data-record number excludes the
header and is not a PDF page or physical line number.

The command checks the whole CSV structure and all requested records, returns
only hashes, locators and counts, and makes no API/provider calls. It requires
no graph profile or authentication token. It explicitly returns
`evidence_only: true` and `publication_allowed: false`. A matching byte/record
digest establishes neither canonical source selection, custody, reviewed account
identity nor publication eligibility; those remain upstream responsibilities.
Its output is not accepted as a graph artifact by the legacy load path.

## Offline document evidence verification

`verify-document-evidence` resolves page-local lines from a retained Markdown
extraction before accepting the supplied quotation. Run in the existing ExAIS
operator/test container with the extraction and reviewed quote file mounted
read-only:

```console
python scripts/release/kansas-fiscal-graphrag.py verify-document-evidence \
  --extraction-md /session-laws/markdown/2025-Session-Laws-Book-2.md \
  --extraction-sha256 3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7 \
  --declared-page-count 1072 --page 358 --line-start 30 --line-end 34 \
  --locator-convention lf-after-page-marker-count-blank-lines-v1 \
  --quote-text /evidence/sb125-96j.quote.utf8 \
  --quote-sha256 3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6
```

The quote file contains the exact complete section 96(j) quotation from the
[retained-source review](../instances/ks-state-civics/research/session-law-extraction-readiness.md#corrected-complete-clause):
314 Unicode code points / 316 UTF-8 bytes, with no trailing LF. Preserve the
internal line breaks, trailing spaces on internal lines, and Unicode spacing.
Expected hashes and locators must come from the reviewed artifact handoff;
computing expectations from arbitrary new input is not evidence of its identity.

The named offline convention starts line 1 immediately after a page-marker
line's LF, counts blank lines, and selects one-based inclusive line bounds.
It excludes only the final selected LF. This is an explicit convention for the
retained CPU output, not a replacement for KS-597/650 locator definitions.
Unknown conventions are rejected; extraction changes require a fresh binding.

The verifier checks the whole extraction hash, page-marker sequence/count,
locator bounds, selected text and quote hash. It performs no fuzzy repair or
normalization. A quote/hash pair from the neighboring lapse cannot pass for
these lines. The result is evidence-only and nonpublishable; it does not verify
raw-PDF parent derivation, canonical source selection, custody, legal identity,
publication eligibility or a working graph/API. The legacy loader rejects it.

## Legacy v1 build, load and evaluation

This path activates only the Kansas StateCivics fiscal document store. It does
not enable graph expansion for other projects or stores.

The legacy adapter accepts `statecivics.fiscal-graph-publisher.v1`, a provisional
ExAIS envelope. Do not implement it as a parallel upstream contract: KS-650 owns
the second record kind in the existing StateCivics exporter, and WAVE-133/134
will adapt that output. The legacy adapter does not validate every semantic
invariant in the upstream ORM models. StateCivics does not produce this envelope. Its legacy records
must contain canonical record bodies and hashes, a completed relationship-export
run with exporter commit and input/output set hashes, explicit review/publication assertions, source revision and SourceSpan
identities, canonical locator and quote hashes, and the exact quoted text. ExAIS
checks their shape, declared canonical-body hashes, and document bindings. It
does not validate the full meaning of opaque canonical records or certify that
a human review occurred.

Build with a current chunk inventory exported from the target store. Each row
must include `chunk_id`, `content`, integer `page_start`/`page_end`,
`current: true`, `active: true`, and the
existing file identities `logical_document_id`, `source_revision_id`, and
`source_content_hash_sha256`. The initial adapter supports PDF locators with
either `page` or `page_start`/`page_end`. Every quoted span must occur exactly
once in exactly one chunk whose page bounds contain the declared span and with
the exact document/revision/hash tuple. Missing, ambiguous, stale, withdrawn,
uppercase/malformed hash, quote/span-content hash, locator hash/page, and source
mismatches fail. This position guarantee combines publisher-supplied span truth
with exact quote presence and chunk page bounds; it is not independent review
of the original source or the publisher's canonical decision.

Inputs are bounded before record scanning: at most 1,000 publisher nodes, 2,000
relationships, 5,000 chunk inventory rows, and 16 MiB per JSON input file.
Relationship `eligibility.source_refs` must be distinct and exactly equal the
SourceSpan citations emitted from `evidence_record_ids`; no reviewed source
reference is silently discarded.

```console
python scripts/release/kansas-fiscal-graphrag.py build \
  --publisher publisher.json --chunks current-chunks.json \
  --vector-store-id vs_actual --output fiscal-artifact.json
python scripts/release/kansas-fiscal-graphrag.py validate --artifact fiscal-artifact.json
python scripts/release/kansas-fiscal-graphrag.py load \
  --artifact fiscal-artifact.json --api https://cell.example --token-env SVS_OPERATOR_KEY
```

`load` is offline dry-run by default and makes no request. Review its output,
the binding report, both artifact digests, upstream evidence, and the resolved
store/profile scope. `--apply` performs the authenticated load. The token is
read only from the named environment variable and is never printed. URLs must
use HTTPS, except localhost HTTP, and cannot contain credentials, paths,
queries, or fragments. Store IDs are validated before URL construction.
Authenticated redirects are rejected, and HTTP error bodies are not printed.
Loads always stage with `replace=false`.
`fixture_only` is accepted only by offline `build --allow-fixture` and
`validate --allow-fixture`; it is rejected by load and evaluation.

Evaluate the explicit lens after an authorized load:

```console
python scripts/release/kansas-fiscal-graphrag.py evaluate \
  --artifact fiscal-artifact.json --api https://cell.example \
  --query "Trace the enacted appropriation to its supporting budget document" \
  --expected-relation-id RELATION_ID --apply
```

Evaluation sends `lens=fiscal_relationships`, the artifact's separate
`inputs.derivation_run_id`, and `relationship=all`. It passes only when every
operator-supplied expected relationship ID is returned. The run selector never
enters ordinary file filters. Before serving, the operator must bind the same
run in the fiscal store attribute and use a separate, strict fiscal profile
manifest selected by `SVS_CELL_GRAPH_PROFILE_PATH`. Disable that profile to
roll back expansion; ordinary document search remains available.

The artifact may contain only the six contract node types and five directed
relations. It never sums chunks into fiscal totals. A real activation requires
the actual reviewed publisher envelope, custody and current-source proof,
read-only store identity proof, dry-run/load/read/ACL/correction evidence, and
complete expected relationship IDs. Fixture output or open ticket status is not
publication evidence.
