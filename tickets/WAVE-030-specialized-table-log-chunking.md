# WAVE-030 Specialized Table And Log Chunking

## Summary

Complete the practical `SVS-033` parser lane by hardening the dependency-free
specialized chunkers already present in the repo. Code chunking exists; this
ticket closes the remaining table/log gaps that directly affect retrieval
quality without requiring provider credentials.

## Background

`README.md` already lists code-symbol, structured JSON/CSV, and logs/errors
chunkers as implemented. The active ticket trail still marks `SVS-033
Code/table/log specialized parsers` as ready-to-build, and inspection shows two
real gaps: Markdown tables embedded in text are not converted into
schema/record-aware chunks, and log chunking can split multi-line events or stack
traces on fixed line windows.

## Scope

- Add Markdown table-aware record chunks to `tables_csv_json_v1`.
- Preserve log events and stack traces as event-boundary chunks for
  `logs_errors_v1`.
- Extend mode auto-detection for common table/log filenames and MIME types.
- Add focused tests and update `SVS-033` tracker status with proof.

## Out Of Scope

- Tree-sitter symbol graphs.
- External PDF/OCR parsing.
- New provider credentials, reranker providers, indexes, or migrations.
- Tenant isolation, API-key behavior, vector-store API behavior, or deployment
  changes.

## Acceptance Criteria

- [x] Markdown table input produces schema-aware chunks with table/row metadata
  and a stable text shape useful for semantic and sparse retrieval.
- [x] JSON/CSV structured chunk behavior remains available.
- [x] Log chunking keeps multi-line events/stack traces together and records
  line, event, severity, and detection metadata.
- [x] `auto_detect_v1` routes `.tsv`/table MIME inputs to
  `tables_csv_json_v1` and `.log`/log MIME inputs to `logs_errors_v1`.
- [x] Focused tests and broad non-integration verification pass.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_structured_and_logs_chunkers.py tests/test_code_chunker.py tests/test_chunking.py tests/test_router.py tests/test_vectorization_plan.py
22 passed in 1.09s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
166 passed, 2 warnings in 4.36s

git diff --check
<exit 0>
```

## Notes

This ticket advances retrieval quality through parser/chunker metadata only. It
does not change the storage schema or index semantics.
