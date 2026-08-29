# WAVE-124 Jurisdiction Knowledge Packages And Expert Onboarding Compiler

Status: In progress  
Priority: P0  
Base: `main @ 29c79fcb6ba5cb12372df5c4736fd636981e80c7`  
Tranche: `.tranche/jurisdiction-knowledge-packages/`

## Canonical Goal

Deliver a governed declarative jurisdiction knowledge package lifecycle that
compiles corpus-backed jurisdiction experts into the existing ExAIS runtime
registry with fail-closed validation, operator promotion, reference migrations,
and reproducible proof.

## Product Decision

ExAIS is the governed knowledge runtime. A jurisdiction knowledge package is the
versioned, reviewable description of how one jurisdiction corpus is acquired,
normalized, chunked, represented semantically, graphed, searched, explained,
cited, evaluated, and exposed through named experts.

Court decisions, statutes, municipal codes and ordinances, administrative
regulations, legislative materials, and meeting records share package contracts
but may use different connectors, metadata schemas, graph ontologies,
extractors, search lenses, planner profiles, caveats, and eval families.

Package manifests are declarative source inputs. They compile into the existing
shared ExAIS expert and search-lens registries; they must not create a second
runtime registry.

## Intended Package Layout

```text
instances/<instance>/vector-stores/<store>/
  store.yaml
  package.yaml
  sources/
  expert/
    corpus-card.md
    instructions.md
  evals/
```

The exact generated/scaffolded files remain schema-controlled. Existing source
packages, graph artifacts, citation maps, store proof, and retrieval behavior
remain owned by their current paths.

## Non-Negotiable Boundaries

- Generated content is always an inactive draft until explicit operator
  promotion.
- Generated or declarative content cannot grant or change tenancy, RLS, API-key
  scopes, citation authority, provider/security routing, memory authority,
  output guards, or runtime tool ceilings.
- Draft generation uses the internal provider-agnostic ExAIS model-gateway
  contract. Package code must not import a provider SDK.
- The existing expert profile registry and search-lens registry remain the only
  runtime registries.
- Package graph/search descriptors reference existing graph, query-planner, and
  search-lens implementations. They do not duplicate those implementations.
- Corpus evidence and generated artifacts are digest-linked. Drift is reported,
  never silently repaired or auto-promoted.
- Promotion, rollback, and deactivation are explicit, auditable operator
  actions.
- Kansas Court Decisions and Topeka Municipal Code retain their existing expert
  IDs, vector-store IDs, routes, graph-lens IDs, citation behavior, and caller
  contracts.
- The StateCivics vendor implementation is reference-only. ExAIS must not import,
  vendor, or depend on it.

## Build Contract

The validated build contract and addressable index are authoritative for shared
ownership and anti-duplication:

- `.tranche/jurisdiction-knowledge-packages/build-contract.json`
- `.tranche/jurisdiction-knowledge-packages/stack.index.json`

Before changing an unplanned symbol or file, query the stack index. If repository
truth contradicts the contract, stop at that boundary rather than adding a
second implementation.

## Ticket Order

### T-001 Define Jurisdiction Package Schema

Goal: Define typed package identity, versioning, corpus cards, acquisition,
normalization/chunking, semantic, graph, search, citation, eval, and expert
declarations.

Acceptance:

- [ ] The schema expresses court decisions, statutes, municipal codes,
  administrative regulations, legislative materials, and meeting records.
- [ ] Corpus-type required sections produce typed, machine-readable validation
  errors.
- [ ] A typed loader is the only package manifest loading path.

Primary files:

- `contracts/jurisdiction-knowledge-package.schema.json`
- `packages/jurisdiction_knowledge_packages/schema.py`
- `packages/jurisdiction_knowledge_packages/validation.py`
- `tests/test_jurisdiction_knowledge_packages.py`

### T-002 Add Version And Evidence Digests

Depends on: T-001.

Acceptance:

- [ ] Validation emits package version, evidence identifiers, source digests,
  generated artifact digests, and a stable canonical package digest.
- [ ] Declaration or evidence changes alter the canonical digest.
- [ ] Existing source-package digest behavior remains compatible.

Primary files:

- `packages/jurisdiction_knowledge_packages/digests.py`
- `packages/svs_common/svs_common/hashing.py`
- `scripts/release/instance_source_packages.py`
- `tests/test_jurisdiction_knowledge_packages.py`

### T-003 Implement Package Compiler

Depends on: T-001.

Acceptance:

- [ ] Valid expert declarations compile into
  `ExpertProfileDefinition`-compatible entries.
- [ ] Compiled definitions are consumed through the existing expert registry.
- [ ] No parallel runtime registry or caller-ID change is introduced.

Primary files:

- `packages/jurisdiction_knowledge_packages/compiler.py`
- `packages/svs_common/svs_common/expert_profiles.py`
- `tests/test_expert_profiles.py`

### T-004 Enforce Fail-Closed Governance Boundaries

Depends on: T-001 and T-003.

Acceptance:

- [ ] Manifests and generated drafts containing protected runtime controls fail
  validation before compilation or activation.
- [ ] Runtime scopes, RLS, provider routing, citation authority, memory
  authority, output guards, and tool ceilings remain owned by existing ExAIS
  enforcement paths.
- [ ] Adversarial tests cover every protected-control family.

Primary files:

- `packages/jurisdiction_knowledge_packages/validation.py`
- `packages/jurisdiction_knowledge_packages/compiler.py`
- `tests/test_jurisdiction_knowledge_packages.py`

### T-005 Model Corpus-Type Extension Contracts

Depends on: T-001.

Acceptance:

- [ ] Typed descriptors cover connectors, metadata, chunking, graph, search,
  caveats, planner references, and eval families.
- [ ] Supported corpus families use descriptors without per-jurisdiction
  compiler branches.
- [ ] Provider/security routing remains outside package control.

Primary files:

- `contracts/jurisdiction-knowledge-package.schema.json`
- `packages/jurisdiction_knowledge_packages/schema.py`
- `packages/jurisdiction_knowledge_packages/compiler.py`

### T-006 Add Graph And Search Descriptor Contracts

Depends on: T-003 and T-005.

Acceptance:

- [ ] Packages can declare semantic behavior and supported specialized graph
  lenses/tools.
- [ ] Compiled descriptors compose with existing lens, planner, API, and graph
  expansion paths.
- [ ] No graph expansion, query planning, or search behavior is duplicated in
  package code.

Primary files:

- `packages/jurisdiction_knowledge_packages/compiler.py`
- `packages/svs_common/svs_common/search_lenses.py`
- `packages/svs_common/svs_common/query_planner.py`
- `tests/test_jurisdiction_knowledge_packages.py`

### T-007 Implement Scaffold CLI

Depends on: T-001 and T-004.

Acceptance:

- [ ] A command scaffolds a package manifest, corpus card, instructions, and
  eval placeholders beside a selected vector store.
- [ ] Scaffold output passes structural validation and remains inactive.
- [ ] Existing files are not overwritten without an explicit flag.

Primary files:

- `packages/jurisdiction_knowledge_packages/cli.py`
- `scripts/release/jurisdiction-package.py`
- `tests/test_jurisdiction_knowledge_packages.py`

### T-008 Build Provider-Agnostic Drafting Workflow

Depends on: T-004, T-005, and T-006.

Acceptance:

- [ ] Draft input is bounded to server-owned store metadata, capability
  descriptors, and representative current retrieval evidence.
- [ ] Draft output includes provenance and only corpus cards, tool descriptions,
  expert instructions, and eval candidates.
- [ ] Drafting goes through the internal expert/model-gateway client and never
  imports a provider SDK or activates output.

Primary files:

- `packages/jurisdiction_knowledge_packages/drafting.py`
- `packages/svs_common/svs_common/expert_llm.py`
- `tests/test_jurisdiction_knowledge_packages.py`
- `tests/test_expert_llm_client.py`

### T-009 Add Diff And Validation Commands

Depends on: T-002, T-004, and T-007.

Acceptance:

- [ ] Validate and diff commands produce deterministic machine-readable output.
- [ ] Invalid packages return nonzero without mutation.
- [ ] Output reports schema errors, protected-control violations, digest
  changes, and compile readiness.

Primary files:

- `packages/jurisdiction_knowledge_packages/cli.py`
- `packages/jurisdiction_knowledge_packages/digests.py`
- `packages/jurisdiction_knowledge_packages/validation.py`

### T-010 Add Operator Promotion Lifecycle

Depends on: T-002, T-004, and T-009.

Acceptance:

- [ ] Promote, rollback, and deactivate require explicit commands and a valid
  package digest.
- [ ] Every transition records operator, prior/current digest, timestamp, and
  outcome through the single lifecycle owner.
- [ ] Generated drafts never autoactivate.

Primary files:

- `packages/jurisdiction_knowledge_packages/lifecycle.py`
- `packages/jurisdiction_knowledge_packages/audit.py`
- `packages/jurisdiction_knowledge_packages/cli.py`
- `tests/test_jurisdiction_package_lifecycle.py`

### T-011 Implement Package Drift Detection

Depends on: T-002 and T-010.

Acceptance:

- [ ] Drift compares promoted state, current package/evidence digests, compiler
  output, and server-owned store evidence.
- [ ] Reports distinguish unchanged, changed, missing, and stale states.
- [ ] Exit behavior is deterministic for operator, scheduler, and CI use and
  never mutates or promotes.

Primary files:

- `packages/jurisdiction_knowledge_packages/digests.py`
- `packages/jurisdiction_knowledge_packages/lifecycle.py`
- `packages/jurisdiction_knowledge_packages/cli.py`

### T-012 Migrate Kansas Court Decisions

Depends on: T-003 through T-011.

Acceptance:

- [ ] A Kansas package manifest becomes the single declarative source for the
  existing Kansas expert definition.
- [ ] Expert ID, vector-store ID, planner profile, graph lenses, caveats, and
  citations remain compatible.
- [ ] Semantic, graph, expert, session follow-up, and citation regressions pass.

Primary files:

- `instances/ks-state-civics/vector-stores/kansas-court-decisions/package.yaml`
- `instances/ks-state-civics/vector-stores/kansas-court-decisions/store.yaml`
- `packages/svs_common/svs_common/expert_profiles.py`
- `tests/test_expert_profiles.py`

### T-013 Migrate Topeka Municipal Code

Depends on: T-003 through T-011.

Acceptance:

- [ ] A Topeka package manifest becomes the single declarative source for the
  existing Topeka expert definition.
- [ ] Expert ID, vector-store ID, municipal graph lenses, caveats, codified-code
  and ordinance-history citation behavior remain compatible.
- [ ] Semantic, graph, expert, session follow-up, and citation regressions pass.

Primary files:

- `instances/ks-state-civics/vector-stores/topeka-municipal-code/package.yaml`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/store.yaml`
- `packages/svs_common/svs_common/expert_profiles.py`
- `tests/test_topeka_graphrag.py`

### T-014 Add Integrated Deterministic Proof

Depends on: T-001 through T-013.

Acceptance:

- [ ] Focused tests cover schema validation, stable digests, protected-control
  rejection, compiler output, explicit lifecycle transitions, drift states, and
  both reference migrations.
- [ ] Existing expert, retrieval, graph, provider, tenant, source-package, and
  API regressions remain green.
- [ ] Proof notes name exact commands and results.

Primary files:

- `tests/test_jurisdiction_knowledge_packages.py`
- `tests/test_jurisdiction_package_lifecycle.py`
- Existing expert/search/graph/provider/source-package tests named by the build
  contract.

### T-015 Add Docker And Live Behavior Proof

Depends on: T-012 through T-014.

Acceptance:

- [ ] Docker/live commands exercise Kansas and Topeka semantic retrieval,
  specialized graph lenses, search tools, expert routing, referential follow-up,
  and citation support.
- [ ] Proof captures provider/model metadata, package digest, retrieval traces,
  citations, and source support without exposing secrets.
- [ ] Docker-network and host/public reachability claims remain separate.

Primary files:

- `scripts/release/jurisdiction-package.py`
- `scripts/release/local-proof.py`
- `scripts/release/cell-smoke.py`
- `runbooks/customer-cell-launch.md`

### T-016 Update Setup And Operator Runbooks

Depends on: T-007 through T-015.

Acceptance:

- [ ] An operator can scaffold, generate, validate, diff, promote, roll back,
  deactivate, inspect drift, and run proof without undocumented steps.
- [ ] The runbooks distinguish infrastructure readiness from trustworthy expert
  answer proof.
- [ ] Protected-control, provider, secret, activation, and rollback boundaries
  are explicit.

Primary files:

- `README.md`
- `docs/JURISDICTION_VECTOR_STORE_PLAYBOOK.md`
- `docs/CALLER_AGENT_INTEGRATION.md`
- `runbooks/customer-cell-launch.md`
- `runbooks/ks-state-civics-hetzner-vps-launch.md`

## Execution Contract

Run one implementation ticket at a time in the order above. Each worker must
read this tracker, the build contract, the stack index, and every primary file
named by its ticket. Implement only the assigned ticket and record proof here.

After each implementation, independent QC must review the ticket, changed files,
verification output, proof notes, package/runtime registry ownership, protected
controls, tenancy, provider routing, retrieval behavior, graph behavior,
citation integrity, activation state, and absence of fake proof. Continue only
on `PASS` or `PASS WITH NOTES`.

## Final Verification

At minimum:

```powershell
python scripts/release/jurisdiction-package.py validate --instance ks-state-civics --all
python scripts/release/jurisdiction-package.py drift --instance ks-state-civics --all
python scripts/release/jurisdiction-package.py proof --instance ks-state-civics
python scripts/release/local-proof.py --cell ks-state-civics
```

Final live proof must use a scoped caller key from inside the Docker network and
verify supported claims against current-run source citations. Host-loopback,
public DNS/TLS, and external customer deployment remain separate proof gates.

## Proof Notes

Pending implementation. Record each ticket's implementation and independent QC
decision before advancing.
