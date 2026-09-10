Decision: PASS WITH NOTES

Ticket reviewed:
- `tickets/WAVE-132-fiscal-law-money-graphrag-runtime.md` (reopened real-data acceptance)

Increment reviewed:
- `scripts/release/kansas-fiscal-corpus-audit.py`
- `tests/test_fiscal_real_corpus.py`
- `docs/FISCAL_GRAPH_REAL_DATA.md`
- Updated notices in `docs/FISCAL_GRAPH_OPERATOR.md` and `docs/CELL_GRAPH_PROFILES.md`
- Updated WAVE-132 ticket and `.tranche/kansas-fiscal-graphrag/wave-132-proof.md`
- Real audit artifact: `/Users/mfrieson/Developer/statecivics-fiscal-exports/graphrag-audit/sb125-kanview-account-evidence.json`

Evidence reviewed:
- Independent bounded audit command against the read-only KanView corpus and custody roots.
- Independent real-corpus test command: `SVS_FISCAL_CORPUS_ROOT=... SVS_FISCAL_CUSTODY_ROOT=... python tests/test_fiscal_real_corpus.py -v` — 8 tests passed, 0 skipped.
- Independent audit result: 16 fiscal-year sources, 75,746 source rows, 44 candidate matches across 15 years, FY2016 no match, all custody checks true, evidence digest `93547e91765a974358f1bbc002077d99ff74e223e479214f9b16d56af6ffaffc`.
- Source and custody paths were read only; no StateCivics database, vendor/payroll data, graph load, publication, or activation was performed.

Acceptance criteria for this corrective increment:
- [pass] The audit is scoped to the Department of Education KanView expenditure extracts, verifies each harvest manifest and matching custody object, and preserves raw record headers/values, record locators, hashes, year, quarters, and source identities.
- [pass] Budget-reference normalization follows the documented `kanview-1` rule; the missing subunit remains null, including for the alternate legal subunit test, and no canonical IDs, SourceSpans, reviews, totals, or legal joins are invented.
- [pass] The FY2016 gap is represented as `no_source_match` with zero records and `publication_allowed=false`, without treating it as zero spending or a published relationship.
- [pass] Corrupted source bytes and wrong-agency manifest requests are rejected; replay is deterministic and the pinned FY2025/FY2026 hashes and record locators round-trip to the retained real files.
- [pass] Documentation distinguishes completed source audit evidence from graph runtime acceptance and explicitly records that the current PDF/page/chunk contract is incompatible with KanView structured observations and current chunk metadata.
- [pass] The increment does not claim a real graph, reviewed publisher envelope, source publication, end-to-end answer, or live activation.

Findings:
- The audit itself is correct and adequately scoped. It confirms a blocking WAVE-132 implementation gap: the current runtime requires every fiscal node to bind to an ExAIS PDF page/span/chunk, while real KanView agency/fund/budget-account observations are structured CSV records with record locators, no canonical SourceSpans/review, and no subunit field. The runtime cannot be accepted for this corpus until it adds a distinct structured-observation evidence path, preserves source revision/hash/record locator and missing subunit, and supports reviewed links to legal/supporting documents without manufacturing PDF chunks or canonical joins.

Required fixes before WAVE-132 acceptance:
- Implement and test the structured observation projection and its source-currentness/replacement/withdrawal semantics through the existing StateCivics publisher boundary; keep the audit output non-publishable.
- Add real-source citation recovery for legal/supporting documents using verified extraction outputs and selected extraction versions; do not fabricate page numbers or choose an arbitrary first chunk.
- Demonstrate the approved law-to-money chain and real retrieval/gap behavior after the revised projection exists. Do not mark the overall ticket complete based on this audit alone.

No unrelated runtime, security, database, deployment, upstream, or live-cell mutation was introduced by this corrective increment.
