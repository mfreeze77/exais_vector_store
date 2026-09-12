# StateCivics law-and-money ticket alignment

Updated 2026-09-10 from the owner/developer-manager agreement. This is the local
entry point for the corrected tickets in the active planning worktrees.
Implementation and activation remain outstanding. All three planning gates and
the independent materialized-ticket review passed. The corrected six new tickets
are proposed implementation work, not completed capabilities.

## Corrected work and owners

| Ticket | Responsibility | Planning disposition |
|---|---|---|
| [KS-600](/Users/mfrieson/Developer/statecivics-fiscal-graph-plan/tickets/KS-600-reconcile-appropriations-from-bill-versions-through-final-law-and-vetoes.md) | Provision-reference definition, legal actions, typed derivation linkage, classification and authority arithmetic. | Existing proposed ticket amended; no rival provision or reconciliation ticket. |
| [KS-650](/Users/mfrieson/Developer/statecivics-fiscal-graph-plan/tickets/KS-650-extend-retrieval-export-with-canonical-entity-records.md) | Extend KS-595's exporter with a second versioned canonical entity/relationship record kind and deterministic descriptions. | New proposed follow-up; preserve existing document export and lifecycle semantics. |
| [KS-651](/Users/mfrieson/Developer/statecivics-fiscal-graph-plan/tickets/KS-651-freeze-real-source-law-money-generalization-benchmark.md) | Reviewed cross-bill/agency/year benchmark with a positive held-back case. | New proposed sibling; KS-613's school-finance scope stays intact. |
| [WAVE-133](/Users/mfrieson/Developer/exais-vector-store-ovh/tickets/WAVE-133-fiscal-canonical-projection-contract.md) | Canonical provision/entity identities, typed structured/document evidence, complete graph manifests. | New proposed correction to the v1 PDF/chunk assumptions. |
| [WAVE-134](/Users/mfrieson/Developer/exais-vector-store-ovh/tickets/WAVE-134-fiscal-projection-ingestion-lifecycle.md) | Scoped ingestion and shared eligibility, correction, withdrawal and removal behavior. | New proposed follow-up covering ordinary semantic search as well as graph retrieval. |
| [WAVE-135](/Users/mfrieson/Developer/exais-vector-store-ovh/tickets/WAVE-135-fiscal-hybrid-retrieval-and-typed-traversal.md) | Exact/lexical and semantic retrieval, bounded typed paths and truthful structured citations. | New proposed follow-up; reuse existing services and canonical upstream decisions. |
| [WAVE-136](/Users/mfrieson/Developer/exais-vector-store-ovh/tickets/WAVE-136-fiscal-real-source-generalization-evaluation.md) | Compare real answer/path/value/citation quality across five retrieval modes. | New proposed acceptance proof; synthetic and all-refusal results cannot pass. |
| [WAVE-132](/Users/mfrieson/Developer/exais-vector-store-ovh/tickets/WAVE-132-fiscal-law-money-graphrag-runtime.md) | Integrated real-source acceptance and scoped operator handoff. | Existing parent remains reopened; historical mechanics tests are preserved. |

KS-595 keeps source/span infrastructure, KS-597 exact fiscal-field span
population, KS-598 the accounting ontology/observations, KS-601 reviewed account
crosswalks, and KS-605 publication/correction semantics. Their relevant ticket
notes point to the shared handoff; this planning pass does not claim those
implementations or records are complete.

## Two verified contract details

The manager's reuse direction stands, with the actual schema shapes recorded:

- Derivation inputs use `revision_or_hash`; outputs use `hash_sha256`. The JSON
  output hash is optional/nullable, while the output model requires it. KS-600
  supplies complete reviewed lineage and set hashes without adding a new action
  field to fiscal facts. A many-input/many-output run is not pairwise join proof.
- The existing publication `subject_type` enum omits fiscal entities. KS-650
  owns the bounded compatible extension/mapping with KS-605 instead of inventing
  a separate publication policy or mislabeling subjects.

The K.S.A. harvest is complete; the [retained-corpus audit](statute-harvest-handoff.md)
records corrected filter and history-count denominators. The old pre-harvest
canary draft stays superseded. Retained Session Laws support the appropriation
milestone; current statutes contribute standing authority, definitions and
unresolved lineage. Acquisition does not complete the canonical export.

## Handoff and verification

- [Planning validation](/Users/mfrieson/Developer/exais-vector-store-ovh/.tranche/statecivics-semantic-graph/aligned/planning-validation.json)
- [Independent ticket review](/Users/mfrieson/Developer/exais-vector-store-ovh/.tranche/statecivics-semantic-graph/aligned/materialization-review-rerun-1.json)
- [Upstream owner handoff](/Users/mfrieson/Developer/statecivics-fiscal-graph-plan/docs/specs/civic-impact-intelligence/LAW_AND_MONEY_RETRIEVAL_HANDOFF.md)
- [ExAIS consumer handoff](/Users/mfrieson/Developer/exais-vector-store-ovh/docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md)
- [Build contract](/Users/mfrieson/Developer/exais-vector-store-ovh/.tranche/statecivics-semantic-graph/aligned/build-contract.json)
- [File and symbol index](/Users/mfrieson/Developer/exais-vector-store-ovh/.tranche/statecivics-semantic-graph/aligned/stack.index.json)
- [Research and downloaded reference code](law-and-money-backbone.md)

These are authoring-worktree links, not production dependencies. Read the
canonical ticket before implementation; use the index to find shared owners.
No runtime implementation, ingestion, harvest mutation or deployment is performed
by this ticket/documentation alignment.
