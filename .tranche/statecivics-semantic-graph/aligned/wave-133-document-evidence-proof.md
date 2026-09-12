# WAVE-133 retained document evidence — implementation proof

Date: 2026-09-10. Base: `3faf453`.
Worktree: `/Users/mfrieson/Developer/exais-vector-store-law-money`.
Scope: independent offline verification of retained Markdown page/line evidence.
WAVE-133 remains in progress; the upstream manager owns KS-597 registration and
KS-600/650 contracts/canonical records. This increment supplies no upstream wire
schema, graph/API integration, publication decision or deployment.

## Implementation

- `fiscal_graph_artifact.py`: `verify_document_page_lines_evidence` verifies
  expected extraction bytes/hash, strict UTF-8, the complete declared page-marker
  sequence, page/line bounds, selected quotation and quote hash. It returns exact
  Unicode/UTF-8 coordinates with no canonical identity or fuzzy correction.
- `kansas-fiscal-graphrag.py`: separate `verify-document-evidence` CLI with
  bounded file reads, explicit locator convention and nonzero failure exits.
- `test_fiscal_document_evidence.py`: 98 cases, including 11 retained-source
  cases plus bounded parser/CLI mechanics. The complete expected lapse quote
  is written independently in the test file with its fixed expected hash.
- Operator instructions and existing handoff/research notes distinguish this
  primitive from the still-unimplemented registration and live adapter paths.

The supported local convention is
`lf-after-page-marker-count-blank-lines-v1`: one-based inclusive lines beginning
after a page-marker line's LF, with blank lines counted and only the final
selected LF excluded. Internal whitespace and Unicode are preserved. Unknown
conventions and CR input are rejected; this is not an implicit locator repair.

## Real source and independent CLI proof

Retained Markdown: `statecivics-ks599-cpu-output/session-laws/markdown/2025-Session-Laws-Book-2.md`.
SHA-256: `3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7`.
The 1,072-page marker inventory and the PDF/Markdown byte relationship were
previously inspected in the [extraction audit](../../../instances/ks-state-civics/research/session-law-extraction-readiness.md).

Root independently wrote the expected complete quote into a temporary UTF-8
file from the previously reviewed literal text. Its fixed expected hash is
`3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6`;
314 Unicode code points, 316 bytes, with no final LF. Expected values were not
obtained by asking the new verifier to generate its own quotation.

All four CLI checks used the existing amd64 ExAIS API test image, no network,
2 GiB memory and two CPUs, with worktree/corpus/quote mounted read-only:

| CLI input | Observed result |
|---|---|
| Page 358, lines 30–34; actual extraction hash and fixed complete quote/hash | Exit 0; `quote_matches_locator=true`; exact 314-character/316-byte clause. |
| Same quote/hash, neighboring section 96(i), lines 25–29 | Exit 2; `document locator does not select quoted_text exactly`. |
| Same quote/hash, truncated lines 30–33 | Exit 2; same exact-selection failure. |
| Actual quote/locator with wrong expected extraction hash | Exit 2; `Markdown extraction hash mismatch`. |

Positive offsets: artifact code points `[986097,986411)` and UTF-8 bytes
`[992620,992936)`; page-body code points `[1589,1903)`. Bounds are zero-based
and end-exclusive. The result uses the existing page/line locator keys
`{page,line_start,line_end}` and reports `evidence_only=true`,
`publication_allowed=false`, `raw_source_derivation_verified=false`.

The reproducible CLI flags are in the [operator instructions](../../../docs/FISCAL_GRAPH_OPERATOR.md#offline-document-evidence-verification).
The temporary quote fixture is not a canonical upstream record or corpus copy.

## Regression and review

Coder's focused container command used the same image and mounts as below,
with only `/work` and `/session-laws` needed, and selected
`tests/test_fiscal_document_evidence.py tests/test_fiscal_graph_artifact.py`.
It returned **121 passed, zero skipped, 3.46 seconds**. This overlaps with the
combined run and is not an additional distinct-test count.

Root combined regression command:

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-kanview-corpus:/corpus:ro \
  -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro \
  -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  -e SVS_FISCAL_CORPUS_ROOT=/corpus -e SVS_FISCAL_CUSTODY_ROOT=/custody \
  -e SVS_FISCAL_SESSION_LAWS_ROOT=/session-laws \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 \
  python -m pytest -q -rs --tb=short -p no:cacheprovider \
  tests/test_fiscal_document_evidence.py tests/test_fiscal_projection_contract.py \
  tests/test_fiscal_structured_evidence.py tests/test_fiscal_graph.py \
  tests/test_fiscal_graph_artifact.py tests/test_fiscal_graph_routes.py \
  tests/test_fiscal_real_corpus.py tests/test_openapi_contract.py \
  tests/test_grant_cell_graph.py
```

Result: **370 passed, zero skipped, 3 existing deprecation warnings, 13.00
seconds**. The prior 272-test selection remains green with the 98 added cases.
Image ID: `sha256:181a0c365c2c056014c1366d772d69e815b36b8bbd486ee24bad1318b8d27f19`.
No project dependencies were installed on the host. An AST comparison against
`3faf453` confirmed all 13 pre-existing top-level function/class definitions in
`fiscal_graph_artifact.py` are unchanged.

The new helper bounds extraction bytes to 16 MiB, declared pages to 10,000,
document physical lines to 1,000,000, selected-page lines to 100,000, and the
quotation to 65,536 Unicode code points. Quote-file reads are bounded to four
bytes per maximum code point before strict decoding/character validation.

Independent review returned **PASS WITH NOTES** for this offline increment.
Its separate targeted container run returned **191 passed, zero skipped, 4.84
seconds**. A direct real-artifact/typed-evidence probe accepted the exact quote,
preserved page/line keys without fake document/chunk IDs, and rejected the
neighbor, truncation, wrong-revision and malformed-marker cases. Another 223
deterministic Unicode/LF offset cases passed. These checks are separate review
evidence, not additional end-to-end GraphRAG acceptance. See the
[QC report](wave-133-document-evidence-qc.md) for commands and remaining scope.

Local documentation links and `git diff --check` passed. Fiscal source and
graph profile declarations remain disabled.

## Remaining acceptance

Expected hashes/source selection must be anchored in the reviewed upstream
handoff. A successful byte/locator check does not establish raw-PDF parentage,
custody access, canonical provision/action identity, legal effect, publication
eligibility or an account crosswalk. The helper explicitly reports the missing
derivation check rather than implying the PDF-to-Markdown chain was verified.

KS-597 must perform retained-artifact resolution before the first reviewed
span write. WAVE-133 still needs the actual KS-600/650 handoff, adapter, raw-source
lineage and canonical semantics, API/persistence and disposable PostgreSQL proof.
WAVE-134–136 and the integrated activation gate remain uncompleted.
