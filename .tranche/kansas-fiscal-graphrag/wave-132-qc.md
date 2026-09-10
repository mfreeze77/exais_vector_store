Decision: PASS WITH NOTES

Ticket reviewed:
- `tickets/WAVE-132-fiscal-law-money-graphrag-runtime.md`

Evidence reviewed:
- `packages/svs_common/svs_common/fiscal_graph.py`
- `packages/svs_common/svs_common/fiscal_graph_artifact.py`
- `packages/svs_common/svs_common/cell_graph.py`
- `packages/svs_common/svs_common/search_lenses.py`
- `apps/api/svs_api/main.py`
- `scripts/release/kansas-fiscal-graphrag.py`
- `docs/CELL_GRAPH_PROFILES.md`
- `docs/FISCAL_GRAPH_OPERATOR.md`
- Fiscal store README, source package, and disabled profile template
- `tests/fiscal_graph_test_support.py`, `tests/test_fiscal_graph.py`, `tests/test_fiscal_graph_artifact.py`, `tests/test_fiscal_graph_postgres.py`, `tests/test_fiscal_graph_routes.py`
- `.tranche/kansas-fiscal-graphrag/wave-132-proof.md`
- `.tranche/kansas-fiscal-graphrag/wave-132-test-output.txt`
- Commands/results: full pinned-container suite `1127 passed, 10 skipped, 3 warnings in 16.57s`; fiscal and Grant PostgreSQL tests enabled against the disposable `svs_app` restricted-RLS database; focused adapter tests `23 passed`; host AST syntax check passed for all 11 changed/new Python files; `git diff --check` passed

Acceptance criteria:
- [pass] Six fiscal node types and five directed relations have strict schema, identity, FY, citation, artifact-class, publication, and 1,000/2,000 bounds.
- [pass] One completed relationship-export run binds each artifact; generation replay is immutable, distinct runs can be staged, and replacement is guarded by profile state.
- [pass] Exact source revision/span/chunk and current document/file bindings are checked at build, load, and expansion time; stale, withdrawn, wrong-source, inactive/private, ambiguous, and inaccessible evidence is suppressed.
- [pass] Expansion preserves Principal tenant/business/group/role ACLs, caller result filters, authorized hydration, original chunk citations, directed relationship metadata, supporting-citation access checks, same-document chunks, and same-chunk relationships.
- [pass] Fiscal routing requires the exact cell/store/corpus/profile binding and served derivation run; the run selector remains outside ordinary file filters and semantic search does not auto-expand.
- [pass] Existing Grant, court, Topeka, and ordinary fiscal search paths remain covered by the full regression suite and fiscal lens exposure is corpus-specific.
- [pass] Runtime load rejects fixture-only artifacts, malformed payloads, mismatched scope/run/profile, non-identical replay, and invalid source bindings before graph writes; the CLI defaults to offline dry-run, rejects unsafe URLs/redirects, and reads tokens only from the named environment variable.
- [pass] Operator adapter/load/evaluation and disabled fiscal profile are documented, with reproducible synthetic complete-chain fixtures and no live activation or fabricated StateCivics review.

Findings:
- The StateCivics producer for the new reviewed publisher envelope is still missing. This is a documented upstream activation dependency, not an ExAIS runtime defect: the adapter validates the declared envelope but does not certify canonical review, and the fiscal profile remains disabled until a real reviewed artifact and matching store/run proof exist.

Required fixes before next ticket:
- None for WAVE-132 completion. Before real-corpus activation, obtain the StateCivics publisher envelope producer and its reviewed/custody/legal-status evidence, then run the documented dry-run, load, read, ACL, correction, and rollback proof against the resolved fiscal store.

No unrelated provider, deployment, upstream, or live-cell mutation was observed. The QC decision covers the implemented StateCivics fiscal-cell runtime only and does not claim real-corpus publication or activation.
