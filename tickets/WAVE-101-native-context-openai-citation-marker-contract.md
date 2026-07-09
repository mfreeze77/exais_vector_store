# WAVE-101 Native Context OpenAI Citation Marker Contract

## Goal

Make native context packs and retrieval answers mimic OpenAI citation behavior
for downstream prompt/rendering pipelines, not just completed Responses payloads.

## OpenAI references

Official OpenAI references checked on 2026-07-09:

- File search guide: Responses file search returns a `file_search_call` output
  item plus an assistant message with strict `output_text.annotations`
  `file_citation` objects:
  https://developers.openai.com/api/docs/guides/tools-file-search
- Citation Formatting guide: recommends model-facing `\ue200` / `\ue202` /
  `\ue201` citation markers, `cite` as the citation family, `turn0file0`-style
  source IDs, optional line locators, and parsing/stripping helpers:
  https://developers.openai.com/api/docs/guides/citation-formatting

## Scope

- Add `model_source_id`, `model_marker`, and optional `model_locator` fields to
  native `ContextCitation`.
- Emit a `Citation Marker: \ue200cite...` line beside each source in native
  `/api/v1/retrieval/context-pack` output.
- Preserve or synthesize the same model citation fields on native
  `/api/v1/retrieval/answer` citations.
- Keep OpenAI-facing `file_citation` annotation objects strict:
  `type`, `index`, `file_id`, and `filename` only.

## Out of scope

- Changing Responses API `output_text.annotations` fields.
- Removing existing visible `【n†source】` markers or native `annotation` proof.
- Changing retrieval ranking, filters, API-key behavior, vector-store routes,
  indexing, provider routing, or tenant/security policy.

## Acceptance criteria

- [x] Native context-pack citations return stable `model_source_id` values such
  as `turn0file0`.
- [x] Native context-pack context text includes matching `Citation Marker:`
  lines using OpenAI's recommended model-facing marker format.
- [x] Chunk line metadata is converted to optional line locators such as
  `L8-L13` when available.
- [x] Native retrieval answers preserve or synthesize model citation fields while
  keeping visible marker offsets and strict OpenAI annotations valid.
- [x] Docs distinguish native model citation fields from OpenAI-facing
  `file_citation` annotations.

## Changed files

- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `README.md`
- `tickets/README.md`
- `tickets/WAVE-101-native-context-openai-citation-marker-contract.md`

## Verification

Focused native retrieval/OpenAI citation verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_retrieval_answer_routes.py tests/test_openai_compat_search.py
```

Result: `131 passed, 2 warnings in 3.85s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

## Quality control

Acceptance criteria:

- [pass] Native context-pack citations return stable `model_source_id` values.
- [pass] Native context text includes matching OpenAI-recommended
  `Citation Marker:` lines.
- [pass] Chunk line metadata is exposed as optional `model_locator` values and
  encoded into `model_marker` when available.
- [pass] Native retrieval answers preserve or synthesize model citation fields
  while strict OpenAI `file_citation` annotations and visible marker offsets
  remain valid.
- [pass] Focused, compile, broad non-integration, and whitespace verification
  passed.

Findings:

- None.

Required fixes before next ticket:

- None.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `412 passed, 2 warnings in 6.00s`.

Whitespace verification:

```powershell
git diff --check
```

Result: pass.
