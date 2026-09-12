Decision: PASS WITH NOTES

Ticket reviewed:
- `tickets/WAVE-133-fiscal-canonical-projection-contract.md`, base `3faf453`.
- Review is limited to the independent offline retained-document-evidence increment. WAVE-133 remains in progress; this decision does not complete the ticket or authorize activation.
- Tracker: `.tranche/statecivics-semantic-graph/aligned/build-contract.json`, T-004 / WAVE-133 ownership and integration boundaries.

Evidence reviewed:
- `packages/svs_common/svs_common/fiscal_graph_artifact.py`: additive document verifier and bounds.
- `scripts/release/kansas-fiscal-graphrag.py`: bounded file reader and separate offline CLI dispatch.
- New `tests/test_fiscal_document_evidence.py`, including fixed real-source expectations and rejection cases.
- `docs/FISCAL_GRAPH_OPERATOR.md`, `docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md`, `instances/ks-state-civics/research/session-law-extraction-readiness.md`, ticket implementation log and `wave-133-document-evidence-proof.md`.
- Independently executed commands and results recorded below. The proof's 370-pass combined run is author/root evidence; QC independently reran 191 overlapping tests and additional direct probes, not another 370-test run.

Acceptance criteria:
- [pass] Actual selected text must equal the exact supplied quote, then match the quote digest; caller quote/hash self-consistency alone cannot satisfy the verifier.
- [pass] Whole extraction bytes must match the independently supplied expected digest. Strict UTF-8, page inventory, ordering, bounds and the explicit LF convention are checked. Unknown conventions, malformed or missing marker cases, quote truncation and extraction drift fail closed.
- [pass] The real SB 125 section 96(j) selection is page 358, inclusive lines 30–34, with the complete $4M lapse clause: 314 Unicode code points / 316 UTF-8 bytes and the independently fixed expected hash. The nearby different-account lapse cannot satisfy this same locator/quote pair.
- [pass] Blank lines count; Unicode separators and form feeds do not create LF lines. Internal whitespace and Unicode remain unchanged. Independent generated mechanical cases verified both code-point and byte offsets.
- [pass] Identical text at distinct locators remains distinct evidence location; no quote digest, line number or SourceSpan becomes provision identity. The result supplies no canonical identities or fabricated document/chunk binding.
- [pass] Locator keys compose with the existing internal `FiscalDocumentSpanEvidence` model without discarding `line_start` or `line_end`. This model-composition probe is not an upstream export or canonical record.
- [pass] CLI validation failures return nonzero with no success output; successful output is evidence-only and nonpublishable. Existing builder/validator rejection tests prevent treating this result as a loadable graph artifact. No API, database, provider, indexing, deployment, harvest or upstream code changes were introduced.
- [pass] The two edited runtime files are existing WAVE-133 anchors, with no later-ticket work. All 13 pre-existing top-level function/class definitions in the artifact module are AST-identical to the base.
- [deferred] Full ticket consumption of actual KS-600 provision identity and KS-650 records, canonical source selection, retained raw-PDF/extraction derivation, reviewed publication semantics and source access.
- [deferred] Live adapter/API/persistence, disposable PostgreSQL proof, complete integrated partition behavior and real end-to-end answer acceptance. The upstream first-write span registration fix remains manager-owned. WAVE-134–136 are not completed by this increment.

Findings:
- No blocking defect found in the reviewed increment.
- The trust boundary is explicit and correct: successful verification proves exact selection within supplied, hash-matching Markdown. It does not independently authenticate the expected hash, identify a legal instrument, prove raw-PDF parentage or grant publication eligibility. Result fields and documentation preserve that distinction.
- The locator convention is deliberately bounded to retained LF Markdown and must be bound explicitly by the eventual upstream adapter. It is not a new canonical locator contract and does not repair or normalize unsupported inputs.
- Passing mechanical and retained-source checks demonstrates the new verification primitive, not a working law-to-money answer through the deployed system.

Required fixes before next ticket:
- None for accepting/committing this offline increment.
- Keep WAVE-133 open. Before completing it or advancing dependent runtime work, satisfy the deferred upstream/export, raw-source, eligibility and integration criteria listed above. Do not reinterpret this review as full-ticket PASS.

## Independent execution evidence

Review date: 2026-09-10. Existing image identity was inspected and matched the author's proof:

```sh
docker image inspect --format '{{.Id}}' localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575
```

Result: `sha256:181a0c365c2c056014c1366d772d69e815b36b8bbd486ee24bad1318b8d27f19`.

The following container command used read-only worktree/corpus mounts, no network, two CPUs and a 2 GiB memory limit:

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

Observed: **191 passed, zero skipped, 4.84 seconds**, exit 0. Explicit corpus configuration ensured real-source tests ran; a missing configured artifact would fail.

Additional independently written direct probe, with literal expected quotation rather than a quote generated by the verifier:

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
import hashlib, json, random
from pathlib import Path
from svs_common.fiscal_graph_artifact import DOCUMENT_PAGE_LINES_CONVENTION, FiscalGraphArtifactError, verify_document_page_lines_evidence
from svs_common.schemas import FiscalDocumentSpanEvidence
sha=lambda b: hashlib.sha256(b).hexdigest()
raw=Path('/session-laws/markdown/2025-Session-Laws-Book-2.md').read_bytes()
quote=('(j)\u2003 On July 1, 2025, of the $601,800,000 appropriated for the above \n'
       'agency for the fiscal year ending June 30, 2026, by section 3(a) of chap-\n'
       'ter 111 of the 2024 Session Laws of Kansas from the state general fund \n'
       'in the supplemental state aid account (652-00-1000-0840), the sum of \n'
       '$4,000,000 is hereby lapsed.')
a=dict(extraction_bytes=raw, expected_extraction_sha256='3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7', declared_page_count=1072, page_1based=358, line_start_1based=30, line_end_1based=34, locator_convention=DOCUMENT_PAGE_LINES_CONVENTION, quoted_text=quote, expected_quote_sha256='3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6')
r=verify_document_page_lines_evidence(**a)
assert (r['quote_unicode_characters'],r['quote_utf8_bytes'])==(314,316)
for key,unit in [('artifact_unicode_codepoints',raw.decode()),('artifact_utf8_bytes',raw)]:
 p=r['resolved_offsets'][key]
 assert unit[p['start']:p['end']]==(quote if isinstance(unit,str) else quote.encode())
assert r['raw_source_derivation_verified'] is False and r['publication_allowed'] is False
# Mechanical model composition only: these local placeholder IDs are not canonical evidence.
m=FiscalDocumentSpanEvidence(source_revision_id='qc-placeholder-source',source_content_hash_sha256='a'*64,extraction_revision_id='qc-placeholder-extraction',extraction_content_hash_sha256=r['extraction_content_hash_sha256'],source_span_id='qc-placeholder-span',span_type=r['span_type'],locator_json=json.dumps(r['locator']),content_hash_sha256=r['quote_sha256'])
assert json.loads(m.locator_json)=={'page':358,'line_start':30,'line_end':34}
assert m.chunk_id is None and m.document_id is None
rejected=[]
for name,changes in [('neighbor',{'line_start_1based':25,'line_end_1based':29}),('truncated',{'line_end_1based':33}),('wrong_revision',{'expected_extraction_sha256':'0'*64}),('malformed_marker',{'extraction_bytes':raw+b'\n<!-- PAGE 1073 -->\n','expected_extraction_sha256':sha(raw+b'\n<!-- PAGE 1073 -->\n')})]:
 try: verify_document_page_lines_evidence(**(a|changes))
 except FiscalGraphArtifactError: rejected.append(name)
 else: raise AssertionError(name+' incorrectly accepted')
# Deterministic generated line/Unicode cases test offsets, not legal acceptance.
rng=random.Random(133)
count=0
for case in range(240):
 pages=[[rng.choice(['', 'ascii ', '\u2003café', '文\u2028x', 'form\fy\x85z', 'chap-']) for _ in range(rng.randint(2,8))] for _ in range(3)]
 n=rng.randrange(3); lo=rng.randrange(len(pages[n])); hi=rng.randrange(lo+1,len(pages[n])+1)
 q='\n'.join(pages[n][lo:hi])
 if not q: continue
 # Final LF permits a truly blank final physical line when present.
 t='Préface文\n'+''.join('<!-- page '+str(i+1)+' -->\n'+'\n'.join(lines)+'\n' for i,lines in enumerate(pages))
 b=t.encode(); result=verify_document_page_lines_evidence(extraction_bytes=b,expected_extraction_sha256=sha(b),declared_page_count=3,page_1based=n+1,line_start_1based=lo+1,line_end_1based=hi,locator_convention=DOCUMENT_PAGE_LINES_CONVENTION,quoted_text=q,expected_quote_sha256=sha(q.encode()))
 for key,u,expected in [('artifact_unicode_codepoints',t,q),('artifact_utf8_bytes',b,q.encode())]:
  p=result['resolved_offsets'][key]; assert u[p['start']:p['end']]==expected
 count+=1
print(json.dumps({'real_quote_verified':True,'typed_locator_keys_preserved':True,'independent_negative_cases':rejected,'generated_offset_cases_passed':count,'canonical_or_raw_parent_verification_claimed':False},sort_keys=True))
PY
```

Observed exit 0:

```json
{"canonical_or_raw_parent_verification_claimed": false, "generated_offset_cases_passed": 223, "independent_negative_cases": ["neighbor", "truncated", "wrong_revision", "malformed_marker"], "real_quote_verified": true, "typed_locator_keys_preserved": true}
```

Of 240 generated attempts, 17 had empty selected text and were excluded from the positive offset probe because the helper intentionally requires a nonempty quote. The committed test suite separately exercises empty-quote rejection. These mechanical strings are not corpus or product-acceptance evidence.

Static scope checks were also independently executed from the worktree:

```sh
git diff --check
python3 - <<'PY'
import ast, subprocess
from pathlib import Path
p='packages/svs_common/svs_common/fiscal_graph_artifact.py'
def defs(text):
 return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
a=defs(subprocess.check_output(['git','show','3faf453:'+p],text=True));b=defs(Path(p).read_text())
assert all(b.get(k)==v for k,v in a.items())
print(str(len(a))+' pre-existing top-level definitions unchanged; added: '+','.join(sorted(set(b)-set(a))))
PY
```

Both exited 0. AST result: `13 pre-existing top-level definitions unchanged; added: verify_document_page_lines_evidence`.

This reviewer changed only this QC artifact. No code, corpus, upstream registration, runtime state or git commit was changed by the review.
