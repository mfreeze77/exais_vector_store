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
