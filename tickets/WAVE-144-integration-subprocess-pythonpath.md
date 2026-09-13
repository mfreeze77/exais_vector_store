# WAVE-144 Spawned Subprocesses Have No PYTHONPATH

Status: proposed. Priority: P2. Owner: ExAIS. Dependency: none.

Not a blocker for WAVE-133. Filed from WAVE-133 round-six QC because the defect
was reproduced, not because WAVE-133 introduced it: it is pre-existing on `main`.

## Scope correction (WAVE-133 round seven)

Round six filed this as one gated integration test. That understated it by a
factor of five. A bare `python -m pytest -q` on `main` -- no environment gates,
the invocation any developer runs -- is red in **seven** places, and **five of
the seven are this defect**, in the TOP-LEVEL suite. Named in full, split by
cause:

### Cause A -- this defect: `ModuleNotFoundError: No module named 'svs_common'` in a spawned child (5 of 7)

1. `tests/test_fiscal_document_evidence.py::test_cli_errors_exit_nonzero_and_emit_no_success_or_quote[wrong_lines]`
2. `tests/test_fiscal_document_evidence.py::test_cli_errors_exit_nonzero_and_emit_no_success_or_quote[trailing_lf]`
3. `tests/test_fiscal_document_evidence.py::test_cli_errors_exit_nonzero_and_emit_no_success_or_quote[invalid_utf8]`
4. `tests/test_fiscal_document_evidence.py::test_cli_errors_exit_nonzero_and_emit_no_success_or_quote[unknown_convention]`
5. `tests/test_statecivics_statutes.py::test_preflight_cli_outputs_only_local_proof_and_refuses_input_overwrite`

Items 1-4 die in the child on `from svs_common.fiscal_graph_artifact import (...)`;
item 5 on `from svs_common.statecivics_statutes import preflight_statute_harvest`.
Each is a `subprocess.run([sys.executable, <a scripts/release entrypoint>, ...])`
whose child inherits no `PYTHONPATH` -- the identical mechanism described below.

### Cause B -- NOT this defect: `ModuleNotFoundError: No module named 'psycopg'` (2 of 7)

6. `tests/test_kscourts_graphrag_load.py::test_graphrag_loader_prepares_tenant_scoped_rows_and_skips_dangling_edges`
7. `tests/test_kscourts_graphrag_load.py::test_graphrag_loader_dry_run_reports_replacement_counts`

Both fail **in-process** at `scripts/release/kscourts-graphrag-load.py:10`
importing `psycopg`. That is a dependency missing from the test environment, not
a path a child failed to inherit. Exporting `PYTHONPATH` does not fix these, and
they must not be counted as evidence that this ticket's fix worked. They are out
of scope here and need their own ticket.

### The eighth, and why it hid the other five

The test this ticket was originally filed against --

* `tests/integration/test_statecivics_fiscal_export_compat.py::test_real_statecivics_export_is_accepted_by_fiscal_adapter_cli`
  (dies on `from svs_common.marker_client import FISCAL_TABLES_PAGE_AWARE_PROFILE`)

-- is cause A as well, but it SKIPS unless `STATECIVICS_REPO` is set, so it
appears only in a gated run (`8 failed` with the variable, `7 failed` without).
Filing from that one test is what made this look like an integration-directory
problem. It is not. The scope is the process boundary, and cause A has six
instances in total.

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
message. A bare full-suite run at the same commit --

```bash
python -m pytest -q
```

-- reports `7 failed, 1376 passed, 140 skipped`: cause A items 1-5 and cause B
items 6-7. With `STATECIVICS_REPO` exported it reports `8 failed, 1422 passed,
124 skipped`, the eighth being the integration test above. Without the variable
that file skips entirely, which is why this defect stayed invisible in the
integration suite -- but items 1-5 were red on every bare run regardless.

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
   argument parsing, rather than a list of the entrypoints known today. The six
   cause-A instances named above are evidence of the defect's reach, not the
   acceptance criterion; a fix that repairs exactly those six and nothing else
   has reproduced the defect this ticket describes.
3. Decide whether a suite that skips its only real-contract test by default is
   acceptable. The skip is why a `main`-red test went unnoticed.

## Out of scope

Zero embedding or API spend. The failing test is a dry run (`"applied": false`,
no state file written) and must stay one.
