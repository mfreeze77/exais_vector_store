# CI repair after 8c7eecc

Scope: restore the GitHub Python gate's required inputs, explicitly account for
workstation corpus coverage, complete candidate response contracts and record
the deployed candidate embedding decision. No test assertion or data hash is
relaxed. Branch: `ci-repair-post-8c7eecc`.

## Item 1 — history

The Python checkout now fetches full history. The four setup errors were in
`tests/test_kansas_fiscal_entity_ingest_integration.py`, whose `pre_change`
fixture reads the consumer at its declared `PRE_CHANGE_COMMIT`. They were not
four historical-digest tests in the two files named by the brief.

The affected tests are:

- `test_the_document_path_produces_the_identical_loaded_manifest`
- `test_the_document_path_refuses_identically`
- `test_the_missing_schema_refusal_is_unchanged`
- `test_load_manifest_keeps_its_signature`

CI evidence is pending; no passing run is implied by this configuration edit.


## Item 2 — upstream

The workflow derives the entity checkout commit from `PINNED_BRANCH_COMMIT` in
the implementation imported by the contract-pin test. The current value is
`24c9d3ded35405054094a1280c7ea1f074fad5d5`; document and dispatch declare a different
commit, so there is no single common branch-pin SHA. Both checkouts have full
history. `vector-store` and `statecivics` are siblings inside GITHUB_WORKSPACE,
as actions/checkout requires; SVS_STATECIVICS_REPO points at the latter.

The fetched upstream `origin/main` is materialized as local `main` for the
existing ancestry test. The detached working tree remains at the declared entity
pin. Later payload and durable-manifest commits are read with git show from the
full history, as their tests already require.

`upstream_proof.py` discovers the four history consumers and three upstream
consumers from their tests, executes them with the upstream set, then executes
the fixture-provenance test with it unset. The latter must fail exactly once for
the missing variable, with no setup error or skip. Both lines and test names go
to the CI summary and JSON proof. No assertion in those tests is changed.

B is public and A is private. At inspection, B had no Actions secrets. The owner
has been asked to provide STATECIVICS_READ_TOKEN with repository-scoped,
read-only Contents access. CI fails explicitly if it is absent; a broad local
credential is not copied into the workflow. CI execution remains pending.
