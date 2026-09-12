# WAVE-133: bounded upstream locator repair recheck

Decision: **PASS for the three previously characterized helper defects**.
Reviewed 2026-09-10 against StateCivics commit
`37f5b1c9b8d0a6ad500da560223bd004c4f31344`.
This closes those findings in the earlier
[convention QC](wave-133-locator-convention-alignment-qc.md); that historical proof
remains unchanged. WAVE-133 is still in progress.

## Inputs and scope

Read-only Git comparison confirmed these upstream files exactly match that
commit; SHA-256 values:

| File | SHA-256 |
|---|---|
| `span_locator.py` | `e93a8e766217b98c67761988a6ab4c2dcb52ff8054699d59a01393fe35bc46fd` |
| `source_artifact_service.py` | `68cfaaec6b5f633165f3a3458be8c14935bd6f2db5913e84f5dd5c740ebcf497` |
| `fiscal_fact_service.py` (static review only) | `c1fb7651deef02985b8d3dc49268a267bb2a79b36172b6ca9fff02d84839da31` |
| `2025-Session-Laws-Book-2.md` | `3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7` |

The upstream Python paths are under
`src/kansas_accountability/services/civic_impact/`.
ExAIS runtime files were unchanged from local HEAD
`0456b7484059c77cb4e5cafad4e87eb8966275e6`:
`fiscal_graph_artifact.py` SHA-256
`84cd932830bc03b01b32cb503a8c799cde37b515f16659a6d46d7f3d4c431956`;
`schemas.py` SHA-256
`69f360a04c968f679132d261c62e37c68ffdfa199494ece238f514acad45284c`,
both under `packages/svs_common/svs_common/`.

The probe imports the actual pure upstream resolver and executes only the actual
`_verify_locator_selection` method isolated from its AST, with lightweight
revision/registration inputs. It does not execute full registration, Pydantic
registration validation, application startup, PostgreSQL, custody acquisition,
upstream gates, deployment or GraphRAG integration. The revision IDs in the
probe are explicit offline placeholders, not claims of persisted records.

The manager's **453 passed / 66 skipped** upstream result is separately reported
evidence; this review did not rerun or independently establish those counts.

## Observed result

One Docker probe, exit **0**, approximately **0.93 seconds**, with network
disabled, read-only mounts, 2 GiB memory and two CPUs:

- Actual upstream page 358, inclusive lines 31–35, resolves the complete real
  section 96(j) quotation; the isolated service helper accepts it only with its
  recorded extraction hash and exact quote.
- ExAIS's explicit after-marker lines 30–34 and marker-as-line-one lines 31–35
  reproduce the same 314 code points / 316 UTF-8 bytes and absolute byte range
  `[992620, 992936)`. Quote SHA-256:
  `3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6`.
- All **14 negative controls reject**. Missing/empty recorded text hashes reject
  with `revision.id` present, duplicate markers reject in both resolver/helper,
  and terminal empty lines reject in both. Empty/whitespace text-offset
  selections, wrong recorded hash, wrong quote, missing artifact text and an
  incorrect ExAIS expected quote digest also reject.
- Zero-width offsets are direct pure-function controls; the unchanged upstream
  Pydantic shape validator already rejects them separately. The ExAIS wrong
  quote-digest control does not claim execution of upstream `register_span`'s
  separate quote/hash check.

## Remaining producer integration

Static review at the same commit found `fiscal_fact_service.py:183`
(`_validate_text_derivation`) still checks a complete derivation, its source
input, and existence of a `DerivationOutput.id` matching the text-output hash
(lines 199–205). It does not retrieve the actual text. Its `register_span`
call at lines 261–264 still omits `artifact_text`. The new helper therefore
fails closed for a text-resolvable span through that unadapted call; this
read-only inspection is not a full caller/DB execution.

No locator-verification metadata contract/model was added by this repair.
The four-file commit changes two service files and two test files. Inspection of
`SourceSpanRegistration`, `SourceSpan`, `source-span.schema.json` and
`register_span` found no persisted/exported verification state, verified
extraction binding or verifier result. Searches for
`verification_state|locator_verification|verified_extraction|verified_locator|locator_verified|verification_result`
across upstream source, Civic Impact contracts and migrations returned no hits.
The helper still returns without a text check for non-text-resolvable span
types; this is not proof that table cells or media were verified.

Source-text retrieval/passing, retained raw-to-extraction derivation, agreed
verification provenance, canonical schemas/records/export and ExAIS runtime
acceptance remain with their existing owners. No competing wire schema was
written; no publication or provision identity follows from these hashes.

## Exact reproducible probe

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro \
  -v /Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai/src/kansas_accountability/services/civic_impact/span_locator.py:/upstream/span_locator.py:ro \
  -v /Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai/src/kansas_accountability/services/civic_impact/source_artifact_service.py:/upstream/source_artifact_service.py:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
import ast, hashlib, importlib.util, json
from pathlib import Path
from types import SimpleNamespace
from svs_common.fiscal_graph_artifact import (
    DOCUMENT_PAGE_LINES_CONVENTION, DOCUMENT_PAGE_MARKER_LINES_CONVENTION,
    FiscalGraphArtifactError, verify_document_page_lines_evidence,
)
sha = lambda data: hashlib.sha256(data).hexdigest()
files = {
    'span_locator.py': 'e93a8e766217b98c67761988a6ab4c2dcb52ff8054699d59a01393fe35bc46fd',
    'source_artifact_service.py': '68cfaaec6b5f633165f3a3458be8c14935bd6f2db5913e84f5dd5c740ebcf497',
}
for name, expected in files.items():
    assert sha((Path('/upstream') / name).read_bytes()) == expected
spec = importlib.util.spec_from_file_location('upstream_locator', '/upstream/span_locator.py')
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)
source = ast.parse(Path('/upstream/source_artifact_service.py').read_text())
helper = next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == '_verify_locator_selection')
module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), helper], type_ignores=[])
ns = {'TEXT_RESOLVABLE': up.TEXT_RESOLVABLE, 'sha256_bytes': sha,
      'resolve_locator': up.resolve, 'LocatorResolutionError': up.LocatorResolutionError}
exec(compile(ast.fix_missing_locations(module), '<actual upstream helper AST>', 'exec'), ns)
check = ns['_verify_locator_selection']
raw = Path('/session-laws/markdown/2025-Session-Laws-Book-2.md').read_bytes()
text = raw.decode('utf-8', errors='strict')
extraction_hash = '3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7'
quote_hash = '3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6'
assert sha(raw) == extraction_hash
quote = text[986097:986411]
assert sha(quote.encode()) == quote_hash and len(quote) == 314 and len(quote.encode()) == 316
locator = {'page': 358, 'line_start': 31, 'line_end': 35}
revision = SimpleNamespace(id='offline-existing-revision-input', text_hash_sha256=extraction_hash)
reg = SimpleNamespace(span_type='page_lines', locator=locator, quoted_text=quote)
assert up.resolve('page_lines', locator, text) == quote
check(None, revision=revision, registration=reg, artifact_text=text)
base = dict(extraction_bytes=raw, expected_extraction_sha256=extraction_hash,
            declared_page_count=1072, page_1based=358, quoted_text=quote,
            expected_quote_sha256=quote_hash)
old = verify_document_page_lines_evidence(**base, line_start_1based=30, line_end_1based=34,
                                        locator_convention=DOCUMENT_PAGE_LINES_CONVENTION)
new = verify_document_page_lines_evidence(**base, line_start_1based=31, line_end_1based=35,
                                        locator_convention=DOCUMENT_PAGE_MARKER_LINES_CONVENTION)
assert old['resolved_offsets']['artifact_utf8_bytes'] == new['resolved_offsets']['artifact_utf8_bytes'] == {'start': 992620, 'end': 992936}
assert old['resolved_offsets']['page_local_origin'] == 'after_page_marker_lf'
assert new['resolved_offsets']['page_local_origin'] == 'page_marker_start'
assert old['publication_allowed'] is False and new['raw_source_derivation_verified'] is False
rejected = {}
def reject(name, operation, expected_type, message):
    try:
        operation()
    except expected_type as exc:
        assert message in str(exc), (name, str(exc))
        rejected[name] = str(exc)
    else:
        raise AssertionError(name + ' was accepted')
reject('missing_recorded_text_hash', lambda: check(None, revision=SimpleNamespace(id='missing-hash-revision', text_hash_sha256=None), registration=reg, artifact_text=text), ValueError, 'records no text_hash_sha256')
reject('empty_recorded_text_hash', lambda: check(None, revision=SimpleNamespace(id='empty-hash-revision', text_hash_sha256=''), registration=reg, artifact_text=text), ValueError, 'records no text_hash_sha256')
reject('wrong_recorded_text_hash', lambda: check(None, revision=SimpleNamespace(id='wrong-hash-revision', text_hash_sha256='0' * 64), registration=reg, artifact_text=text), ValueError, 'does not match')
reject('wrong_quote', lambda: check(None, revision=revision, registration=SimpleNamespace(span_type='page_lines', locator=locator, quoted_text=quote + 'x'), artifact_text=text), ValueError, 'selects different text')
reject('missing_artifact_text', lambda: check(None, revision=revision, registration=reg, artifact_text=None), ValueError, 'require artifact_text')
foreign = '<!-- page 1 -->\nchosen\n'
duplicate = '<!-- page 1 -->\nfirst\n<!-- page 1 -->\nsecond\n'
simple_locator = {'page': 1, 'line_start': 2, 'line_end': 2}
reject('duplicate_markers_resolver', lambda: up.resolve('page_lines', simple_locator, duplicate), up.LocatorResolutionError, 'marked more than once')
reject('duplicate_markers_helper', lambda: check(None, revision=SimpleNamespace(id='duplicate-revision', text_hash_sha256=sha(duplicate.encode())), registration=SimpleNamespace(span_type='page_lines', locator=simple_locator, quoted_text='second'), artifact_text=duplicate), ValueError, 'marked more than once')
terminal_locator = {'page': 1, 'line_start': 3, 'line_end': 3}
reject('terminal_empty_line_resolver', lambda: up.resolve('page_lines', terminal_locator, foreign), up.LocatorResolutionError, 'select no text')
reject('terminal_empty_line_helper', lambda: check(None, revision=SimpleNamespace(id='terminal-revision', text_hash_sha256=sha(foreign.encode())), registration=SimpleNamespace(span_type='page_lines', locator=terminal_locator, quoted_text=''), artifact_text=foreign), ValueError, 'select no text')
# Direct pure-function controls; Pydantic separately rejects zero-width offsets.
for label, content, loc in [('empty_offsets', '', {'start_char': 0, 'end_char': 0}),
                            ('whitespace_offsets', ' \t\nchosen', {'start_char': 0, 'end_char': 3})]:
    reject(label + '_resolver', lambda content=content, loc=loc: up.resolve('text_offsets', loc, content), up.LocatorResolutionError, 'selects no text')
    reject(label + '_helper', lambda content=content, loc=loc: check(None, revision=SimpleNamespace(id=label, text_hash_sha256=sha(content.encode())), registration=SimpleNamespace(span_type='text_offsets', locator=loc, quoted_text=content[:loc['end_char']]), artifact_text=content), ValueError, 'selects no text')
reject('wrong_quote_digest_exais', lambda: verify_document_page_lines_evidence(**{**base, 'expected_quote_sha256': '0' * 64}, line_start_1based=31, line_end_1based=35, locator_convention=DOCUMENT_PAGE_MARKER_LINES_CONVENTION), FiscalGraphArtifactError, 'quote')
print(json.dumps({'commit': '37f5b1c9b8d0a6ad500da560223bd004c4f31344',
                  'input_sha256': {**files, '2025-Session-Laws-Book-2.md': extraction_hash},
                  'upstream_real_quote_and_helper': True, 'two_exais_conventions_same_quote': True,
                  'quote_sha256': quote_hash, 'rejected_controls': len(rejected),
                  'rejections': rejected, 'registration_database_or_gate_executed': False}, sort_keys=True, indent=2))
PY
```

Observed output:

```json
{
  "commit": "37f5b1c9b8d0a6ad500da560223bd004c4f31344",
  "input_sha256": {
    "2025-Session-Laws-Book-2.md": "3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7",
    "source_artifact_service.py": "68cfaaec6b5f633165f3a3458be8c14935bd6f2db5913e84f5dd5c740ebcf497",
    "span_locator.py": "e93a8e766217b98c67761988a6ab4c2dcb52ff8054699d59a01393fe35bc46fd"
  },
  "quote_sha256": "3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6",
  "registration_database_or_gate_executed": false,
  "rejected_controls": 14,
  "rejections": {
    "duplicate_markers_helper": "locator does not address this artifact: page 1 is marked more than once; page numbering is ambiguous in this artifact and no locator for it can be resolved",
    "duplicate_markers_resolver": "page 1 is marked more than once; page numbering is ambiguous in this artifact and no locator for it can be resolved",
    "empty_offsets_helper": "locator does not address this artifact: text_offsets [0, 0) selects no text; a span cannot cite an empty selection",
    "empty_offsets_resolver": "text_offsets [0, 0) selects no text; a span cannot cite an empty selection",
    "empty_recorded_text_hash": "revision empty-hash-revision records no text_hash_sha256, so supplied artifact_text cannot be bound to it; register the extraction's text hash before registering spans against it",
    "missing_artifact_text": "page_lines spans require artifact_text so the locator can be verified; registering one without it would record an unproven citation",
    "missing_recorded_text_hash": "revision missing-hash-revision records no text_hash_sha256, so supplied artifact_text cannot be bound to it; register the extraction's text hash before registering spans against it",
    "terminal_empty_line_helper": "locator does not address this artifact: page 1 lines 3-3 select no text; a span cannot cite an empty selection",
    "terminal_empty_line_resolver": "page 1 lines 3-3 select no text; a span cannot cite an empty selection",
    "whitespace_offsets_helper": "locator does not address this artifact: text_offsets [0, 3) selects no text; a span cannot cite an empty selection",
    "whitespace_offsets_resolver": "text_offsets [0, 3) selects no text; a span cannot cite an empty selection",
    "wrong_quote": "the locator selects different text than quoted_text (selected 314 chars, quoted 315 chars); a citation whose locator and quote disagree cannot be trusted to point at the right provision",
    "wrong_quote_digest_exais": "selected document quote hash mismatch",
    "wrong_recorded_text_hash": "artifact_text does not match the revision's recorded text_hash_sha256 (supplied 3c336e663f4f\u2026, recorded 000000000000\u2026); the extraction changed or the wrong artifact was supplied"
  },
  "two_exais_conventions_same_quote": true,
  "upstream_real_quote_and_helper": true
}
```

Only this proof file was written by the reviewing agent; no commit or upstream
file change was made.
