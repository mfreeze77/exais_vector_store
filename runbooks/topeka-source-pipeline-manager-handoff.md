# ExAIS manager handoff: Topeka source collections and clean artifact delivery

Owner direction: 2026-09-15. This assignment is for `exais_vector_store` only.
Implement the extension in [WAVE-118](../tickets/WAVE-118-topeka-municipal-code-source-seeding.md),
using [WAVE-117](../tickets/WAVE-117-instance-vector-store-source-package-contract.md)
and the [jurisdiction playbook](../docs/JURISDICTION_VECTOR_STORE_PLAYBOOK.md).

Deliver reusable source pipelines, structured document releases, collection-level
vector stores and cited graph retrieval. **Deliver the versioned schema and a
validated real-data bundle first.** The StateCivics developer needs that interface
to implement the local-jurisdiction consumer while the remaining ExAIS work proceeds.
Do not wait for every download, embedding or graph job to finish before that handoff.

## Ownership and starting state

- All implementation, tickets, tests, worker tasks and release changes assigned
  here belong in ExAIS. Do not modify the StateCivics repository, its database,
  importer, UI, search, transcript pipeline, worker jobs or deployment.
- StateCivics KS-539 and KS-540 are read-only consumer requirements. Report the
  contract and any consumer requirements to its developer; do not assign A-side
  implementation to an ExAIS worker. Overall cross-product acceptance remains
  open until that developer supplies the UI/search/context proof.
- At preparation, ExAIS is on `docs/topeka-jurisdiction-source-handoff`, with the
  preceding ticket changes at `a941eac620ff914620e76b9d720c130a2a8e15f8`;
  local main is `7759a8d11fff1a70c130f78990072c0c2e34b9e8`.
  Verify current Git state before work; these are starting references, not pins
  for a future release. The StateCivics reference read was `a08427dee`.
- Read the existing manager/worker instructions under `tickets/codex-agents/`
  and `.agents/skills/exais-ticket-orchestrator/`,
  `.agents/skills/exais-ticket-implementation/` and
  `.agents/skills/exais-quality-control/`. Use bounded specialist assignments
  and independent QC; the manager owns integration and closeout.
- Use the canonical ExAIS checkout. No linked worktrees or new coding roots under
  `~/Developer`; existing approved operator clones are only for their established
  execution purpose. Run project code/tests through the repository's Docker path.
  Preserve unrelated changes and branches. Serialize Git mutations and shared-file
  edits when workers share the checkout.
- [The fiscal pause](./civic-impact-pause.md) remains in force. This assignment does
  not resume Kansas appropriations or absorb the separate CI-repair branch.
  Check current hosted CI rather than repeating its historical status or counts.
  Missing external credentials must be reported without blocking independent
  offline schema, artifact and unit-test work.

## Settled collection boundaries

One logical vector store per registered master collection, never per PDF, URL,
year folder, page, download attempt or fragment. Shared connector code should
serve multiple source packages.

| Collection | Master source | Members |
| --- | --- | --- |
| Topeka Municipal Code | `https://topeka.municipal.codes/TMC` | Sections/subsections, including Title 18 and chapter 14.55 |
| Topeka Ordinances | `https://topeka.gov/community/ordinances/index.php`, Ordinances category | Ordinary ordinance PDFs |
| Topeka Charter Ordinances | Same listing, Charter Ordinances category | Charter ordinance PDFs |
| Topeka Resolutions | `https://topeka.gov/community/resolutions/index.php` | Resolution PDFs across all listed years |

Two categories on one listing still have separate stores. `#undefined` is a UI
fragment, not source identity. These owner examples must become routing tests:

- `https://s3.us-east-1.amazonaws.com/files.topeka.gov/community/resolutions/2026/Resolution09749.pdf`
  is one document in Topeka Resolutions.
- `https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf`
  is one document in Topeka Charter Ordinances.

The historical store `vs_d4185d1004604f08a55299fa` combines code and ordinances.
Prepare a manifest-driven split, reconcile every retained document, verify new
destination retrieval/citations and then update ExAIS routing. Keep the old store
available for rollback. Account explicitly for the unnumbered STO document;
do not discard it because it is outside numbered ordinances. A logical store
does not imply a separate database or a physical Qdrant collection per file.
Use the existing provider/profile and destination guards.

Register other source families with explicit master boundaries and availability:
meeting documents, budgets/CIP, plans, applications, GIS and adopted-code material.
Do not turn every outbound link into an active store. The first four collections
are the implementation scope; inventory additional families and their gaps under
WAVE-118 or normal linked tickets without claiming they are already complete.
An adoption/amendment in TMC is not possession of the complete incorporated code.

## Reuse the retained inputs

Re-measure before publishing. The 2026-09-15 audit established the following local
inputs; it did not establish current live-store contents or complete city coverage.

| Input | Existing location relative to this repo | Audit result |
| --- | --- | --- |
| Consolidated TMC | `.tmp/topeka-decodo-window-batches-20260827220454/combined-full-corpus-20260828-v2/` | `sections.jsonl`: 2,702 records, including 332 Title 18 and 64 chapter 14.55 records; August 28 captures |
| Ordinance seed | `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-ordinances/seed/` | 364 PDFs: 322 numbered ordinary ordinances, 41 charter ordinances, one STO |
| Seed inventories | Above seed's `manifests/ordinances.jsonl` and `manifests/ordinance-extractions.jsonl` | All 364 raw hashes matched; all Markdown files existed, 363 matched their extraction manifest |

The STO Markdown at `extracted/topeka-ordinance-b03282aaf10640134b3ac4a4.md`
has expected SHA-256
`308ea5ee2c321372eee3b1a793068c71d0f41e53619fb87c51253a8f44d25f30`
and observed SHA-256
`55f552ab7ce20248ce3d9f55ef3ba53a96e2808328a09b18debd738bc3520d8b`.
Trace and document the transformation or regenerate from the verified raw input;
changing the expected hash alone is not provenance repair.

Charter Ordinance 126 is already retained as
`topeka-ordinance:2b5f74ef0f50712246969e30`, with raw
`raw/pdfs/CharterOrdinance126.pdf` and extracted
`extracted/topeka-ordinance-2b5f74ef0f50712246969e30.md`.
Use the manifest's actual paths and digests, not a filename guessed from the number.
The named local-amendment ordinances 20648, 20344, 20407 and 20343 also have retained
originals and extractions.

The current city listing's displayed total of 350 ordinary ordinances does not
establish an exact missing-file delta against 322 retained records. Derive the
added/changed/removed worklist by document identity across the complete listing.
Full resolutions and separate IPMC/UPOC PDF coverage have not been established.

Preserve existing TMC blocks, tables, definitions, ordinance history and raw
captures. Inspect [WAVE-119's existing canonical projection](../tickets/WAVE-119-topeka-workbench-canonical-projection.md)
and `scripts/release/topeka-code-workbench-project.py` before designing another
component exporter. Reuse its supported structure and IDs, and document any
compatibility gaps; this task does not implement the StateCivics workbench.
Reuse verified extractions; only new, changed or defective PDFs need
the configured bounded remote extraction path. Do not install another Marker
service or re-extract all retained PDFs. `.tmp` is a recovery input, not a durable
release destination: promote verified artifacts and commit portable locks/pointers
under WAVE-117, keeping large raw corpora out of Git.

## First delivery: executable document-release contract

Produce the following before the bulk indexing work:

1. Versioned JSON Schemas for the release manifest and clean document records,
   with documented required, nullable and unknown semantics. Extend compatible
   existing schemas where appropriate; avoid a separate schema per jurisdiction.
2. A real exporter and independently callable validator. They must run without
   embeddings or a StateCivics database and validate the actual files being handed
   over, including source, content and evidence hashes/references.
3. A small real-data release containing a TMC section, an ordinary ordinance and
   Charter Ordinance 126 from the retained corpus. Add Resolution 9749 through the
   real resolutions pipeline as soon as it is ready; do not hold the initial
   three-document handoff for that collector.
4. Durable accessible artifacts, exact producer/validator commands, code commit,
   schema version/hash, manifest hash and validation result. No rolled-back or
   scratch-only evidence pointers. Small fixtures may be committed; large source
   artifacts use the established durable storage plus checksummed locks.

The contract must express these semantics; the implementer chooses compatible
field names and proves their behavior:

| Area | Required behavior |
| --- | --- |
| Identity | Stable jurisdiction, collection, source-document and component IDs; document versions separate from identity; map existing IDs rather than silently replacing them |
| Source | Official URL, retained original reference/hash, acquisition time, extractor/schema versions and transformation lineage |
| Content | Usable readable text and structured sections/blocks/tables, preserving verbatim source separately from normalized text; distinct hashes for each artifact |
| Evidence | Resolvable source revision/file and verified page/block/character references with explicit coordinate conventions; unavailable coordinates marked unavailable |
| Meaning | Document type, citations/references, known dates and precision, proposed/adopted/superseded status, extraction quality and review status kept distinct |
| Release | Immutable document inventory, per-file hashes, schema/code provenance, durable pointers and a release identity both consumers can record |
| Updates | Unchanged/new/changed/unavailable outcomes, prior-version retention and stale-consumer detection; disappearance from a listing is not a repeal |
| Readiness | Acquisition, extraction, validation/review, artifact publication, vector indexing and graph readiness reported separately |

Use `ks:city:topeka` as the canonical consumer jurisdiction mapping; record legacy
aliases explicitly. Do not derive document identity solely from checkout commit,
content text, chunk order or row position. Do not invent PDF page coordinates
from Markdown line numbers. Preserve tables and visual-content limitations.

Keep source facts separate from inferred relationships. Resolutions may contain
operative approvals or funding decisions. Extraction does not itself establish
adoption, legal completeness, membership at a meeting date or a final outcome.
Support evidenced links to cases/matters, meetings, bodies and related instruments;
unresolved links stay explicit. No fuzzy join may silently become authoritative.

StateCivics consumes these released source artifacts, not reconstructed vector
chunks or direct ExAIS database reads. It can publish validated documents while
vector or graph work remains pending. Deliver this contract and bundle immediately
after their checks pass, then continue the remaining ExAIS work.

## Bounded worker assignments and dependencies

Track work under WAVE-118 with its existing ticket format. If separate tickets are
needed, allocate normal WAVE IDs and link them; do not create a parallel JSON
ticket system. A worker implements a bounded ticket/subtask, not the whole vision.

| Assignment | Deliverable and dependency |
| --- | --- |
| 1. Contract and export | Schemas, real exporter/validator, retained-input audit and starter release. First priority; supplies the StateCivics interface. |
| 2. Collection discovery and acquisition | Complete ordinary/charter/resolution category discovery, versioned manifests, resumable acquisition, reuse/extraction worklists. Can start with disjoint files alongside 1; adapts to the agreed contract. |
| 3. Store split and retrieval | Four declared source/store packages, retained-record reconciliation, API ingestion and cited vector/graph retrieval. Depends on validated artifacts and stable collection IDs from 1/2. |
| 4. Updates and operational delivery | Wire actual supported command/scheduler entrypoints, incremental refresh, durable release publication, status/failure reporting and rerun proof. Builds on 1/2/3; functions tested only in isolation do not complete it. |
| 5. Independent QC | Validate fixed candidate commits/artifacts at real ExAIS entrypoints; check correctness, destination isolation, source citations and repeat/change behavior. Report remaining A-side proof separately. |

The manager resolves routine implementation choices and coordinates shared files.
Do not parallelize edits to contracts, instance routing or common ingestion code
without explicit file ownership. Use feature branches and the existing merge/QC
gates; no direct main commits. Check the final candidate after the last code change.
Repeat broad QC only for new substantive changes or unresolved failures, not for
every wording correction. Report measured baselines and the actual test regime.

This handoff is not a deployment or data-deletion receipt. Follow existing owner
authorization and release policy for runtime activation and spend. Where additional
approval is actually required, prepare a concrete tested operation and rollback
first; continue independent work instead of pausing the entire assignment.

## ExAIS acceptance: prove through real entrypoints

- **Collection completeness:** inventory all pages/year groups in each declared
  master list. Reconcile every discovered document to a retained/reused, changed,
  failed, unsupported or review-needed outcome. A parser failure is not an empty
  successful listing. Counts must come from retained manifests/run receipts.
- **Routing:** exercise both exact owner PDF examples and ordinary/code controls.
  Listing category determines membership; a mention of a charter ordinance inside
  another document does not change that document's collection. URL aliases and
  fragments do not create extra stores or duplicate active documents.
- **Content and evidence:** reject mismatched raw/payload hashes, empty extraction
  and dangling evidence from clean release/indexing. Prove positive controls too.
  Validate representative structured text/tables against originals, not just JSON
  shape. Record extraction limitations rather than claiming every page is usable.
- **Persistence and repeatability:** rerun the actual exporter/import path, reuse
  unchanged verified content, preserve changed-document history and reconcile
  destination IDs. A new or late-published document must be discoverable without
  re-extracting the unchanged corpus. Preserve the STO item and its audit trail.
- **Retrieval:** ingest through supported ExAIS APIs, never direct backend writes.
  Prove real semantic queries with source-specific citations and store isolation.
  Validate graph edges and their endpoint evidence; test cross-collection links
  through supported routing, and report any unavailable graph capability honestly.
  An empty lens is not GraphRAG proof. Record actual profiles/model dimensions.
- **Operational reachability:** show the actual command/scheduler caller and an
  execution receipt. Exercise failure/resume and quota handling. Deferred work
  stays pending; a successful index check is not proof of equal document bytes.
  Do not claim scheduling or activation based only on configuration files.
- **Portable delivery:** validate the final bundle at its delivered location and
  report resolvable source references, matching hashes and exact commands. A
  fixture-only demonstration is labeled as such, not a durable production release.

The joint Planning Commission/second-body story in WAVE-118 remains overall
product acceptance. StateCivics owns the importer, Topeka reader, FTS, fresh/repair
agent context and packet handling. ExAIS supplies the contract, content releases,
retrieval proofs and supported source relationships. Do not close those A-side
gaps by changing A or claim UI success from an ExAIS API response.

## Delivery reports

Send the early contract handoff when assignment 1 passes:

```text
ExAIS branch + commit:
Schema paths + versions + hashes:
Artifact location + manifest SHA-256:
Exact export and validation commands + measured result:
Real document IDs, versions, collection assignments and payload hashes:
Original/readable/structured content and citation reference examples:
Unknowns, review items and unavailable coordinates:
Consumer compatibility notes; ExAIS work continuing:
```

At ExAIS closeout, record this in WAVE-118 and linked implementation tickets:

```text
Delivered items + commits:
Collection/source/store IDs and actual target cell/API/profile:
Discovery/extraction/review counts and manifest receipts:
Durable release URI, hashes, locks and backup:
API ingestion, vector retrieval and graph proof:
Actual update entrypoint, schedule/activation status and rerun proof:
Tests/regime/baseline + independent QC result:
Hosted CI run URL/result, or exact unverified/blocked status:
Merge/release status; activation target and rollback if activated:
StateCivics handoff location; A-side acceptance still pending:
Could not verify / contradictions / remaining named work:
```

Do not carry forward historical counts as current proof. A pushed commit,
configured package, accepted manifest or passing fixture is not by itself a
running pipeline. Keep implementation complete, hosted validation, activation
and cross-product acceptance separate so the next developer knows what exists.
