# Kansas fiscal GraphRAG plan

**Superseded for implementation by the [owner-approved law-and-money scope](scope-decision.md).**
The current target is enacted provision → appropriation → agency/fund/account →
supporting budget documents. Use [WAVE-130](../../tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md)
and its fiscal contract for the first step. The earlier plan and gate results
below are preserved for audit; their ontology-only first release and broader
payment/outcome destination are no longer this cell's approved scope.

**Current runtime implementation: [WAVE-132](../../tickets/WAVE-132-fiscal-law-money-graphrag-runtime.md),
complete with independent QC PASS WITH NOTES.** The approved law-and-money
handler, explicit lens, source binding, operator adapter and isolated database
proof are implemented. See [runtime proof](wave-132-proof.md) and
[independent QC](wave-132-qc.md). The checked-in fiscal profile remains disabled
pending the actual reviewed StateCivics publisher export and store activation.

This plan applies the StateCivics Civic Impact Intelligence specification to the ExAIS retrieval cell. It does not activate a graph or approve canonical source records.

## Product direction

StateCivics is building four connected capabilities: the civic record, claims and evidence, fiscal/policy impact, and forecast reconciliation. The first complete reference case is SB 125 Supplemental State Aid, from exact enacted language through reviewed account identity to KSDE district payment evidence. Later, immutable snapshots carry that intelligence into Workbench drafting and preserve what was known when a forecast was made.

ExAIS contributes document retrieval and bounded expansion through cited canonical relationships. PostgreSQL remains the graph store; Qdrant supplies retrieval candidates. Structured payment totals and review decisions stay with StateCivics.

## Work sequence

| Ticket | Deliverable |
| --- | --- |
| T-001 | Reconcile WAVE-130 in place and define the fiscal artifact, source identity, eligibility, citation, generation, and lifecycle contract. |
| T-002 | Implement the small cited ontology projection and bounded validator/expander using existing PostgreSQL graph tables. |
| T-003 | Register the fiscal profile and an explicitly selected fiscal relationship search lens. |
| T-004 | Add read-only store identification and artifact eligibility checks; keep activation disabled until real export proof exists. |
| T-005 | Verify replacement, withdrawal, citation access, generation binding, and isolation from ordinary fiscal search and other graph domains. |

The initial runtime vocabulary covers cited document-to-dimension and parent-dimension relationships. The complete bill/version → action → account → reviewed crosswalk → payment → outcome chain remains the product destination. Its later relation types require their own explicit upstream structured exports and evidence bindings; an SB 125 fixture does not establish live availability.

## Activation boundary

The existing StateCivics exporter produces narrative document manifests. A citation-bound canonical relationship export is an additional dependency. Exact source revisions and spans must resolve to current documents accessible to the caller. ExAIS can validate exported assertions and identity consistency, but cannot independently certify upstream human review.

Ontology and crosswalk decisions have different publication fields. Candidate or ambiguous mappings must not be collapsed into approved positive joins; a published `not_same` decision is negative evidence. No transaction CSV is converted into narrative chunks to bridge this gap, and no payment amount is computed by summing retrieved excerpts.

Local document/chunk counts are diagnostic snapshots, not fixed activation thresholds. Resolve the intended store by its ID, tenant/business, corpus, source package, and document attributes before any later load.

## Reading and artifacts

- [Project alignment and source precedence](project-alignment.md) records the user-directed package, current repository corrections, and concrete upstream findings.
- [Original goal](intent.md) and [base tickets](tickets.base.json) retain the planning intent.
- [Verified ticket detail](tickets.enriched.json) contains code references and activation dependencies.
- [Build contract](build-contract.json) and [file/symbol index](stack.index.json) are the final worker inputs. Start with T-001 and resolve shared code through the index.

Historical planning verification: all three stages passed deterministic and independent critic gates. Stages 2 and 3 each needed one corrective rerun, resolving upstream eligibility/export assumptions and actual API/profile interfaces respectively. See [verification record](verification.json) for artifact hashes and gate commands. That original planning run performed no runtime implementation or live activation; WAVE-132 above records the subsequent approved implementation.
