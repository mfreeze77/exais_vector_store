# Owner-provided legal assets: verified alignment

Read 2026-09-10 after the owner paused drafting to identify existing law sources.
This supplements the intent and research-notes files for all three waves.

## Reuse first

Canonical operational PDF directory:
`/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai/docs/existinglawexpert/pipeline/input_pdfs/`.
Root counted 70 PDFs and verified all seven `*-Session-Laws-Book-*.pdf` files
against the March 1 manifest. 2023 has2books,2024has3,2025has2. The remaining
eight-file legal exclusion includes the Constitution, not an eighth session-law
volume. Exact inventory matters because the folder was always mixed legal/fiscal.

Manifest in the planning worktree:
`docs/existinglawexpert/pipeline/manifests/download_manifest_20260301_045737.json`.
The seven validated hashes:

- 2025book1: 282a06a250996223a92b967bd34a51585c8aef8e0dc5bdc59b5d8aac09078c98
- 2025book2: a1f85adfbac7da37bb9412e0e495587cd976bd3acea6dba4f1c2e2222e201009
- 2024book1: 9597f3b75be4801d045f874161cccc99c1d03c5031429db84f0459d842ca6d02
- 2024book2: f07b25e5d12669e55ed7e0498fde7d641c1ee8b5ff8ca288e6e8efcd7e4b0827
- 2024book3: 0b4212c41933e784267ed32dc9798e11be6fbad16c1da4fb69715b0324c25b0b
- 2023book1: 4b3b066915b221a23b70b5dcd2eae5e5fe73a856244f681affd86de5000fc833
- 2023book2: e0a7ceb151c47960a7fadaf6893ca2cb05b1e8e29ae775369050dbd9bea12cef

`marker_output_md` currently contains zero `.md` files. That proves only the
local derived output is absent. It does not establish remote OpenAI store state
or require re-running paid Marker over all70 PDFs. September CPU extraction
manifest documents62 fiscal outputs but excludes the7 session books+Constitution;
probe retained legal PDF text layers and recover existing derived artifacts
before selecting extraction. Preserve raw and parsed hashes, page/section
locators, extraction version and actual citation fidelity. CPU fiscal output
explicitly is retrieval material, not canonical monetary fact evidence.

The existing OpenAI `kansas-current-law` expert is a separate consumer. Its
PLAN.md and ops/update_runbook.md document MCP service and overwrite capability.
Do not overwrite, rebuild, migrate or reconfigure it during this planning task.
A future inventory task may resolve the live store ID/files read-only through
the existing authorized service, but local config `[]` is not proof of absence.
Source custody remains authoritative for the new graph; an OpenAI hit without
revision/span binding does not automatically become graph evidence.

## Committed source code takes priority over old unversioned code

StateCivics already has:

- `scripts/existinglaw_scrape_statutes.py` (scrape and REST source switches).
- `src/kansas_accountability/etl/existinglaw/statute_scraper.py:StatuteScraper`.
- `statute_parsers.py:ParsedStatuteSection` with history, source_or_prior_law,
  body and references; `normalize_ksa_citation`, `statute_to_markdown`.
- `statute_rest.py` with typed REST adapters and the same renderer. Its module
  documents historical coverage differences: numeric chapters only in the REST
  index, no annotations, single-paragraph text. Verify live coverage by a small
  canary before making a provider choice or estimating a full run.

The older directory is
`/Users/mfrieson/Dropbox/AI_Projects/exai_projects/ksa-diff-collector-main`.
There are TWO relevant implementations there: legacy `collector/...` and newer
unmerged `src/kansas_accountability/etl/statute_lineage/...` overlay modules.
Use `.../history.py:parse_history` and citations/revisor modules as prior art,
with provenance/code hash and tests, not as already adopted mainline APIs.
`collector/sources/ksrevisor.py:get_revisor_url` is not evidence that the newer
mainline parser lacks those abilities. Reconcile duplicated normalization APIs
before porting anything. Never copy the overlay wholesale.

`alembic/versions/085_statute_lineage.py` conflicts with mainline085. The five
overlay tables are NOT a requirement for this tranche; no migration number is
reserved and no automatic111+ allocation is justified. Any later adoption needs
its own current-Alembic design and disposable-database proof.

ExAIS court source.yaml already declares operator-source://ksa-diff-collector-main
and a Windows localProofOnly path. This is an existing portability gap, not an
authorization to move/reindex the court corpus in a fiscal ticket. Record it as
separate deferred work; preserve the court store and its citation policy.

## Ownership and store alignment

- StateCivics: committed acquisition/parsing, durable raw corpus outside Git,
  custody/source revision registration, canonical history/action/crosswalk
  evidence and publication decisions. ExAIS must not gain direct DB authority.
- ExAIS: source declarations/locks/API ingestion, semantic descriptions,
  document retrieval, derived graph projections, scope/ACL/currentness checks.
- Proposed `kansas-statutes`: separate subsection-aware citation/update policy,
  within ks-state-civics. Its intake/source-package work is an optional connected
  lane; full capture is NOT a dependency for first fiscal graphs based on already
  retained session laws. Session-law artifacts and fiscal narratives retain
  their own source identities even if a bounded legal-evidence projection is
  served alongside the fiscal store. Specify an explicit allowlist/snapshot for
  any cross-store traversal; same tenant alone does not authorize federation.
- Existing OpenAI expert: preserved consumer; any refresh is separately scoped.
- Corpus bytes stay outside Git. A proposed durable statute root is
  `/Users/mfrieson/Developer/statecivics-statute-corpus`; resumability must compare
  source identities/hashes, not silently trust filename existence.

## Correct the embedding and harvest assumptions

ExAIS `RetrievalService._embedding_profiles_for_search` discovers up to8 active
profiles; `search` creates the matching query vector per profile and fuses their
ranked result lists; `QdrantAdapter.collection_name` separates profiles. Different
embedding models/dimensions need compatible per-index queries, not identical
models across all stores. Never compare their raw vectors/cosine scores. Graph
joins use canonical IDs, independent of vector dimension. Cross-store fiscal
graph authorization/joins still require implementation and proof; existing
multi-profile search is not evidence those joins already work.

Choose/benchmark within the existing provider registry and budget. Same model
can simplify operations but is an option, not a prerequisite for graph validity.
No new API key, paid provider run or bulk embedding is part of ticket writing.

The later developer-manager handoff supersedes the pre-harvest recommendation:
the K.S.A. harvest is already running, retains provenance and ordered unresolved
History references, and must not be restarted for another canary. Check retained
records and actual status when preparing a future statute intake; do not infer
completion, custody registration, legal effective time or public eligibility
from download counts. Current statutes remain a separate connected source lane,
not a prerequisite for the retained Session Laws fiscal milestone. See
[manager-alignment.md](manager-alignment.md).

KSA history references are statute↔session-law lineage, not appropriation↔account
proof. Many fiscal appropriations are session-law provisions and need no codified
KSA section. Preserve unknown links and effective scope, and do not grow this
tranche into a universal statute-lineage or court graph project.
