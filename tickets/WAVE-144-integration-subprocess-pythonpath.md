# WAVE-144 The Integration Suite's Spawned Subprocess Has No PYTHONPATH

Status: proposed. Priority: P2. Owner: ExAIS. Dependency: none.

Not a blocker for WAVE-133. Filed from WAVE-133 round-six QC because the defect
was reproduced, not because WAVE-133 introduced it: it is pre-existing on `main`.

## Problem

`tests/integration/test_statecivics_fiscal_export_compat.py::test_real_statecivics_export_is_accepted_by_fiscal_adapter_cli`
spawns the fiscal adapter as a child process:

```python
completed = subprocess.run(
    [sys.executable, str(ADAPTER), "--manifest", ..., "--vector-store-id", "vs_contract_proof"],
    cwd=ROOT, capture_output=True, text=True, check=False,
)
assert completed.returncode == 0, completed.stderr
```

The child dies before it parses an argument:

```
File "scripts/release/kansas-fiscal-document-ingest.py", line 25, in <module>
  from svs_common.marker_client import FISCAL_TABLES_PAGE_AWARE_PROFILE
ModuleNotFoundError: No module named 'svs_common'
```

This is a **PYTHONPATH problem, not an environment-variable-name problem.** The
suite's own `STATECIVICS_REPO` gate is satisfied; the test runs, and the other
test in the file passes. `pyproject.toml` declares

```toml
pythonpath = ["packages/svs_common", "apps/api", "apps/worker", "apps/model_gateway", "apps/instance_agent"]
```

which pytest applies to **its own** interpreter by mutating `sys.path`. A child
started with `sys.executable` inherits the process environment, and `PYTHONPATH`
is not in it, so the package layout that makes `svs_common` importable in-process
is invisible to every subprocess the suite spawns. Any future test that shells out
to a `scripts/release/*.py` entrypoint will hit the same wall.

## Reproduction, on `main`

Confirmed at `main` = `5387d52c81c30f4bb35de5f76acf3f86bec6ab64`. Exact command:

```bash
git checkout main
STATECIVICS_REPO=/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai \
  python -m pytest \
  tests/integration/test_statecivics_fiscal_export_compat.py::test_real_statecivics_export_is_accepted_by_fiscal_adapter_cli \
  -q
```

Observed: `1 failed`, with the `ModuleNotFoundError` above in the assertion
message. Without `STATECIVICS_REPO` the whole file skips, which is why the defect
has stayed invisible: the default local and CI invocation never runs the test.

The cause is confirmed by the complement — the identical command with the package
directory exported passes:

```bash
STATECIVICS_REPO=/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai \
PYTHONPATH=$PWD/packages/svs_common \
  python -m pytest tests/integration/test_statecivics_fiscal_export_compat.py -q
# 2 passed
```

## Scope

1. Decide where the fix belongs. Exporting `PYTHONPATH` from a `conftest.py`
   fixture repairs this test; making the `scripts/release/*.py` entrypoints
   locate `packages/svs_common` themselves repairs every operator invocation,
   which is the larger and more honest fix, since an operator running the adapter
   by hand hits exactly this error.
2. Whichever is chosen, the fix must be derived, not enumerated: a test that
   spawns any tracked `scripts/release` entrypoint and asserts it reaches
   argument parsing, rather than a list of the entrypoints known today.
3. Decide whether a suite that skips its only real-contract test by default is
   acceptable. The skip is why a `main`-red test went unnoticed.

## Out of scope

Zero embedding or API spend. The failing test is a dry run (`"applied": false`,
no state file written) and must stay one.
