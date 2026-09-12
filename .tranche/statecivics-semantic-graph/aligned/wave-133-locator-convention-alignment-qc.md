Decision: PASS WITH NOTES

Ticket reviewed:
- `tickets/WAVE-133-fiscal-canonical-projection-contract.md`, base `28c3b95`.
- Review scope is only the bounded offline locator-convention alignment. WAVE-133 remains in progress; this is not full-ticket acceptance.
- Shared ownership/tracker inputs: `.tranche/statecivics-semantic-graph/aligned/build-contract.json` and `stack.index.json`, T-004 / WAVE-133.

Evidence reviewed:
- Runtime diffs in `packages/svs_common/svs_common/fiscal_graph_artifact.py` and `scripts/release/kansas-fiscal-graphrag.py`.
- Added cases in `tests/test_fiscal_document_evidence.py`; existing literal real-source quote/hash and prior cases remain unchanged.
- `docs/FISCAL_GRAPH_OPERATOR.md`, `docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md`, `instances/ks-state-civics/research/session-law-extraction-readiness.md`, ticket and `wave-133-locator-convention-alignment-proof.md`.
- Read-only upstream `span_locator.py` and `source_artifact_service.py`, byte-identical to StateCivics `668ca412`; also inspected the fiscal span caller, derivation validation and table-cell handoff.
- Independent tests, helper probes and static checks below. Root's 379-pass combined run is reviewed author/root evidence; QC independently ran 200 overlapping tests rather than claiming another full run.

Acceptance criteria:
- [pass] Explicit `lf-page-marker-is-line-one-v1` resolves page 358, inclusive lines 31–35, to the complete real SB 125 section 96(j) quote. Existing `lf-after-page-marker-count-blank-lines-v1` still resolves lines 30–34 to exactly the same content and absolute offsets.
- [pass] The result explicitly distinguishes `page_marker_start` from `after_page_marker_lf`. No automatic convention selection, line adjustment, normalization or fuzzy fallback was added.
- [pass] Swapped convention/range combinations and the neighboring different-account lapse are rejected. Unknown/omitted CLI conventions still fail. Whole-extraction digest, exact quote digest, strict UTF-8, unique contiguous page markers, nonempty selection and EOF bounds remain required.
- [pass] Real-source positive checks reproduce the fixed quote hash, 314 Unicode code points / 316 UTF-8 bytes and absolute UTF-8 interval `[992620,992936)`. Generated parser cases remain mechanical proof, not legal product acceptance.
- [pass] The existing verifier remains evidence-only and nonpublishable, without raw-parent derivation or canonical identity claims. Upstream schemas, registration, API, database, provider, indexing, deployment and harvest were not changed by this increment.
- [pass] File/symbol edits stay within WAVE-133 anchors. AST comparison shows only the intended verifier and CLI `main` changed among prior definitions; all 29 existing test/helper definitions remain identical. No later ticket started.
- [pass] Documentation distinguishes committed upstream behavior, manager-reported upstream gate results and independently executed helper probes. Suggested locator-verification state is explicitly a proposal under upstream owners; no competing wire schema is implemented. Table cells are unsupported by this text resolver, not inherently unverifiable.
- [deferred] Upstream source-text retrieval, first-write trust/bounds repairs, agreed verification-state contract and bound derivation, KS-600/650 canonical records/export, raw-source/QA linkage and eligibility.
- [deferred] WAVE-133 adapter/API/disposable PostgreSQL integration and complete real-answer acceptance; dependent WAVE-134–136 work and activation remain unfinished.

Findings:
- No blocking defect found in the reviewed increment.
- One minor documentation inconsistency called the now-committed upstream resolver a draft. Root corrected those new references during review; runtime code did not change.
- Independent execution reproduced the documented upstream helper limitations: missing recorded text hash bypasses its hash comparison, duplicate page markers keep the last entry, and a terminal LF can yield an accepted empty selection. These are upstream helper characterizations, not executions of full registration or claims about its entire test gate. They remain integration prerequisites under the StateCivics manager.
- The local convention name captures the observed upstream marker origin for the retained LF artifact. It does not claim the two implementations have identical malformed-input behavior or establish an upstream canonical convention contract.

Required fixes before next ticket:
- None before accepting/committing this bounded offline increment.
- Keep WAVE-133 open and satisfy its deferred upstream contract, verification provenance and integration criteria before full-ticket completion or dependent runtime activation. No acceptance of canonical publication or working GraphRAG follows from this QC decision.

## Independent verification

Date: 2026-09-10. Existing offline image:
`localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575`.
All runtime checks used read-only mounts, no network, a 2 GiB memory bound and two CPUs. No host dependency installation or upstream gate was run.

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  -e SVS_FISCAL_SESSION_LAWS_ROOT=/session-laws \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 \
  python -m pytest -q -rs --tb=short -p no:cacheprovider \
  tests/test_fiscal_document_evidence.py tests/test_fiscal_graph_artifact.py \
  tests/test_fiscal_projection_contract.py
```

Observed: **200 passed, zero skipped, 5.15 seconds**, exit 0. The explicit retained-corpus mount ensured real-source tests executed.

Independent convention/trust-boundary probe:

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
from svs_common.fiscal_graph_artifact import DOCUMENT_PAGE_LINES_CONVENTION, DOCUMENT_PAGE_MARKER_LINES_CONVENTION, FiscalGraphArtifactError, verify_document_page_lines_evidence
sha=lambda b:hashlib.sha256(b).hexdigest()
for name,expected in [('span_locator.py','7c20205633b3b495a6ab0e0eb79179d9039259575a184a63760c9013ef9d8ed7'),('source_artifact_service.py','b5d38b4eb948fb144e3dca9bfaf6a58632212ae1f07b2ef15e5cf43c9b85c696')]:
 assert sha((Path('/upstream')/name).read_bytes())==expected
spec=importlib.util.spec_from_file_location('upstream_locator','/upstream/span_locator.py')
up=importlib.util.module_from_spec(spec);spec.loader.exec_module(up)
raw=Path('/session-laws/markdown/2025-Session-Laws-Book-2.md').read_bytes();text=raw.decode()
expected='3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6'
# Independent source slice, with fixed expected quote hash preventing arbitrary agreement.
quote=text[986097:986411];assert sha(quote.encode())==expected
base=dict(extraction_bytes=raw,expected_extraction_sha256='3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7',declared_page_count=1072,page_1based=358,quoted_text=quote,expected_quote_sha256=expected)
old=verify_document_page_lines_evidence(**base,line_start_1based=30,line_end_1based=34,locator_convention=DOCUMENT_PAGE_LINES_CONVENTION)
new=verify_document_page_lines_evidence(**base,line_start_1based=31,line_end_1based=35,locator_convention=DOCUMENT_PAGE_MARKER_LINES_CONVENTION)
assert up.resolve('page_lines',{'page':358,'line_start':31,'line_end':35},text)==quote
assert old['resolved_offsets']['artifact_utf8_bytes']==new['resolved_offsets']['artifact_utf8_bytes']=={'start':992620,'end':992936}
assert old['resolved_offsets']['page_local_origin']=='after_page_marker_lf'
assert new['resolved_offsets']['page_local_origin']=='page_marker_start'
assert new['publication_allowed'] is False and new['raw_source_derivation_verified'] is False
for convention,start,end in [(DOCUMENT_PAGE_MARKER_LINES_CONVENTION,30,34),(DOCUMENT_PAGE_LINES_CONVENTION,31,35),(DOCUMENT_PAGE_MARKER_LINES_CONVENTION,26,30)]:
 try:verify_document_page_lines_evidence(**base,line_start_1based=start,line_end_1based=end,locator_convention=convention)
 except FiscalGraphArtifactError:pass
 else:raise AssertionError('wrong range accepted')
source=ast.parse(Path('/upstream/source_artifact_service.py').read_text())
helper=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='_verify_locator_selection')
module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),helper],type_ignores=[])
ns={'TEXT_RESOLVABLE':up.TEXT_RESOLVABLE,'sha256_bytes':sha,'resolve_locator':up.resolve,'LocatorResolutionError':up.LocatorResolutionError}
exec(compile(ast.fix_missing_locations(module),'<reviewed upstream helper>','exec'),ns)
check=ns['_verify_locator_selection']
foreign='<!-- page 1 -->\nchosen\n'
reg=SimpleNamespace(span_type='page_lines',locator={'page':1,'line_start':2,'line_end':2},quoted_text='chosen')
check(None,revision=SimpleNamespace(text_hash_sha256=None),registration=reg,artifact_text=foreign)
duplicate='<!-- page 1 -->\nfirst\n<!-- page 1 -->\nsecond\n'
assert up.resolve('page_lines',reg.locator,duplicate)=='second'
reg.locator={'page':1,'line_start':3,'line_end':3};reg.quoted_text=''
assert up.resolve('page_lines',reg.locator,foreign)==''
check(None,revision=SimpleNamespace(text_hash_sha256=sha(foreign.encode())),registration=reg,artifact_text=foreign)
print(json.dumps({'two_conventions_same_real_quote':True,'upstream_marker_origin_matched':True,'swapped_and_neighbor_ranges_rejected':3,'upstream_missing_hash_bypass_reproduced':True,'upstream_duplicate_overwrite_reproduced':True,'upstream_phantom_empty_selection_reproduced':True,'upstream_registration_or_database_executed':False},sort_keys=True))
PY
```

Observed exit 0:

```json
{"swapped_and_neighbor_ranges_rejected": 3, "two_conventions_same_real_quote": true, "upstream_duplicate_overwrite_reproduced": true, "upstream_marker_origin_matched": true, "upstream_missing_hash_bypass_reproduced": true, "upstream_phantom_empty_selection_reproduced": true, "upstream_registration_or_database_executed": false}
```

This imports the pure upstream locator and executes only its reviewed service helper AST with lightweight inputs. It does not execute application startup, `register_span`, a database or the upstream test gate. Read-only Git inspection separately confirmed both inspected source files match commit `668ca412` exactly.

Static scope command:

```sh
python3 - <<'PY'
import ast,subprocess
from pathlib import Path
for p,expected in [('packages/svs_common/svs_common/fiscal_graph_artifact.py',{'verify_document_page_lines_evidence'}),('scripts/release/kansas-fiscal-graphrag.py',{'main'}),('tests/test_fiscal_document_evidence.py',set())]:
 def defs(t):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(t).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
 old=defs(subprocess.check_output(['git','show','28c3b95:'+p],text=True));new=defs(Path(p).read_text())
 changed={k for k,v in old.items() if new.get(k)!=v}
 assert changed==expected,(p,changed)
 print(p, {'unchanged_prior_definitions':len(old)-len(changed),'changed':sorted(changed),'added':sorted(set(new)-set(old))})
PY
git diff --check
```

Observed exit 0 for each: 13 prior artifact definitions and eight prior CLI definitions unchanged; only the verifier and `main` changed. All 29 prior test/helper definitions unchanged, with six added test functions representing nine collected cases. No whitespace errors.

All local inline Markdown links and explicit heading fragments in the five changed documents/proof were checked: **49 targets, zero missing paths or headings**. The new ticket acceptance paragraph was also reviewed as deferred upstream-contract consumption, not implemented behavior.

The reviewer wrote only this QC artifact and made no commit or runtime/upstream mutation.
