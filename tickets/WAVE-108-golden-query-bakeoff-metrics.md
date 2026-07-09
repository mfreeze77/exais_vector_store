# WAVE-108 Golden Query Bakeoff Metrics

## Goal

Advance the eval/bakeoff lane from a deterministic proxy ledger to real
golden-query metric computation. State-of-art retrieval changes need reliable
measurement; this ticket lets the existing bakeoff API compare model profile
candidates with recall, precision, MRR, NDCG, and leakage metrics whenever a
runner or fixture supplies candidate result IDs.

## Scope

- Extend shared eval helpers with precision@k, reciprocal rank, NDCG@k, and
  aggregate golden-query metrics.
- Support chunk-level and document-level expected/forbidden IDs.
- Allow query fixtures to provide per-candidate results through
  `results_by_model_profile_id` or `result_ids_by_model_profile_id`.
- Use golden metrics in `BakeoffService.create_run` when judged results are
  present.
- Preserve the existing deterministic proxy fallback when no candidate results
  are supplied.
- Bound bakeoff `top_k` so metric calculations receive a positive window.
- Add focused unit tests for metric computation, persisted bakeoff result
  payloads, proxy fallback, and `top_k` validation.

## Out of scope

- Running live retrieval inside `BakeoffService`.
- Provider API fan-out, background jobs, queue workers, UI dashboards, or
  scheduled eval execution.
- Changing retrieval ranking, indexing, tenant isolation, API-key behavior,
  model registry contents, or OpenAI-compatible response/citation shapes.

## Acceptance criteria

- [x] Golden metrics compute recall@k, precision@k, MRR, NDCG@k, and leakage
  counts from per-candidate result IDs.
- [x] Document-level expected IDs score correctly when result rows carry
  `document_id`.
- [x] Bakeoff result rows use golden metrics when judged results are present.
- [x] Bakeoff result rows retain proxy metrics when judged results are absent.
- [x] `BakeoffRunRequest.top_k` rejects invalid zero/negative windows.
- [x] Focused bakeoff/eval tests pass.

## Changed files

- `packages/svs_common/svs_common/evals.py`
- `packages/svs_common/svs_common/bakeoff.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_bakeoff.py`
- `docs/API.md`
- `docs/COMPLETION_MATRIX.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-108-golden-query-bakeoff-metrics.md`

## Verification

Focused bakeoff/eval verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_bakeoff.py tests/test_openai_file_search_parity_eval.py
```

Result: `7 passed in 0.94s`.
Rerun result: `7 passed in 1.06s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `428 passed, 2 warnings in 7.01s`.

## Quality control

Acceptance criteria:

- [pass] Golden metrics compute recall@k, precision@k, MRR, NDCG@k, and leakage
  counts from per-candidate result IDs.
- [pass] Document-level expected IDs score correctly when result rows carry
  `document_id`.
- [pass] Bakeoff result rows use golden metrics when judged results are present.
- [pass] Bakeoff result rows retain proxy metrics when judged results are absent.
- [pass] `BakeoffRunRequest.top_k` rejects invalid zero/negative windows.
- [pass] Compile, broad non-integration, and whitespace verification passed.

Findings:

- None.

Required fixes before next ticket:

- None.

Whitespace verification:

```powershell
git diff --check
```

Result: pass.
