# Owner-approved first-release scope

Recorded 2026-09-10 after the owner approved:

**Enacted provision → appropriation → agency/fund/account → supporting budget documents.**

This supersedes the earlier tranche's broader product destination and its ontology-only first-release vocabulary. The chain itself is the first-release target, using SB 125 Supplemental State Aid as the initial curated reference. Payments, recipient/outcome records, forecasts, claim adjudication, district-impact models, and drafting simulation stay outside this ExAIS release.

The canonical implementation anchor for the first step is [WAVE-130](../../tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md), with the fiscal contract in [CELL_GRAPH_PROFILES.md](../../docs/CELL_GRAPH_PROFILES.md). This owner decision approves product scope, not source publication, live data loading, or operational activation.

Existing `tickets.base.json`, `tickets.enriched.json`, `build-contract.json`, `stack.index.json`, critic results, and `verification.json` are preserved as historical planning artifacts. Their checks describe the earlier scope and do not certify this change. Do not implement their ontology-only vocabulary or later payment/outcome fixtures as the current build target. Follow-up implementation planning must derive from WAVE-130 and the approved five-link contract before those tickets are used.

Current work implements WAVE-130 documentation only, using the single-ticket implementation and independent QC workflow. The user has supplied the necessary product choice; source/export/runtime gaps are engineering dependencies, not missing user preferences.
