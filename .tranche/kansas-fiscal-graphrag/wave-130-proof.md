# WAVE-130 documentation proof

Scope: owner-approved law-and-money chain contract only. Root ExAIS base
`bb7e575016ed398a6f9379d6bddf4bda0ca8639f`; upstream StateCivics read at
`4cc4c262e3bf736c2140c833e55b3b13a8730aa5`. No runtime or upstream mutations.

Changed files for this step:

- `docs/CELL_GRAPH_PROFILES.md` — appended fiscal design contract.
- `tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md` — reconciled scope, acceptance, dependencies, proof.
- `.tranche/kansas-fiscal-graphrag/README.md` — supersession banner on the earlier planning artifacts.
- `.tranche/kansas-fiscal-graphrag/scope-decision.md` — owner's approved boundary and current implementation anchor.
- This proof record. Independent QC will add `wave-130-qc.md`.

The earlier JSON planning artifacts and gate records are historical and were not rewritten or presented as proof of this scope.

## Commands and observed results

Workdir: `/Users/mfrieson/Developer/exais-vector-store-ovh`.

`git diff --check` — no whitespace errors.

`git diff --stat` — only the contract document and WAVE-130 are tracked modifications. The local tranche was already untracked before this step.

The following check ran successfully using host standard-library Python only:

```python
from pathlib import Path
import subprocess
p = Path('docs/CELL_GRAPH_PROFILES.md')
base = subprocess.run(['git', 'show', 'HEAD:docs/CELL_GRAPH_PROFILES.md'], check=True, capture_output=True, text=True).stdout
current = p.read_text()
marker = '## Kansas fiscal law-and-money artifact contract v1'
assert current.split(marker, 1)[0].rstrip() == base.rstrip(), 'Existing graph profile contracts changed'
changed = set(subprocess.run(['git', 'diff', '--name-only'], check=True, capture_output=True, text=True).stdout.splitlines())
assert changed == {'docs/CELL_GRAPH_PROFILES.md', 'tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md'}, changed
for relative in ['../../tickets/WAVE-130-fiscal-graph-artifact-attribute-contract.md', '../../docs/CELL_GRAPH_PROFILES.md']:
    assert (Path('.tranche/kansas-fiscal-graphrag') / relative).resolve().is_file(), relative
assert (Path('tickets') / '../docs/CELL_GRAPH_PROFILES.md').resolve().is_file()
print('PASS: existing Grant/profile documentation unchanged; tracked diff restricted to WAVE-130 and appended fiscal contract; new local handoff links resolve.')
```

Observed output:

```text
PASS: existing Grant/profile documentation unchanged; tracked diff restricted to WAVE-130 and appended fiscal contract; new local handoff links resolve.
```

This verifies documentation scope and links, not runtime behavior. No application tests, graph loads, source publication changes, or deployment commands ran for this step.

Independent QC: **PASS**, recorded in [wave-130-qc.md](wave-130-qc.md), with all acceptance criteria passing and no required fixes. WAVE-130 is complete as a documentation contract only. The next implementation remains runtime handler/export/fixture work for the approved chain.
