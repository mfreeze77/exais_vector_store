"""Exact statute preparation, including all retained files when explicitly mounted."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import pytest
from svs_common.statecivics_statutes import (
    parse_statute_markdown, statecivics_statute_markdown_chunks, preflight_statute_harvest,
    STATECIVICS_STATUTE_MARKDOWN_PROFILE, official_statute_url,
)
from svs_common.chunking import choose_chunker

MANIFEST_SHA = '17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2'
URL = 'https://ksrevisor.gov/statutes/chapters/ch02/002_003_0003.html'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rendered(body='(a) Café law.\n\n(b) A second paragraph.', tail='## History\n\nL. 1915, ch. 178, § 3.\n'):
    return '# K.S.A. 2-303 — Test mechanics\n\n**Chapter: AGRICULTURE**\n\n**Source:** ' + URL + '\n\n' + body + '\n\n' + tail


def small_harvest(tmp_path, body=None, duplicates=False):
    text = rendered() if body is None else rendered(body)
    root = tmp_path / 'corpus'
    data = root / 'data/ksa'
    data.mkdir(parents=True)
    (data / 'ksa_002_003_0003.md').write_bytes(text.encode('utf-8'))
    record = {'filename': 'ksa_002_003_0003.md', 'section_number': '2-303', 'source_url': URL,
              'rendered_sha256': sha(text.encode()), 'rendered_bytes': len(text.encode()),
              'response_sha256': 'f' * 64, 'response_bytes': 500, 'history_raw': 'L. 1915, ch. 178, § 3.',
              'history_events': [{'ordinal': 1, 'year': 1915, 'chapter': '178', 'section': '3',
                                  'citation_text': 'L. 1915, ch. 178, § 3', 'resolution_status': 'unresolved'}],
              'retained_from_previous_run': False, 'scraped_at_utc': '2026-09-11T00:00:00+00:00'}
    records = [record]
    if duplicates:
        records.append({**record, 'section_number': 'AGRICULTURE2-303', 'response_sha256': None,
                        'response_bytes': None, 'retained_from_previous_run': True})
    path = tmp_path / 'harvest.json'
    path.write_text(json.dumps({'operation': 'statute_scrape', 'files_written': 1, 'documents': records}))
    return path, root, records, text


@pytest.fixture(scope='module')
def corpus_root():
    configured = os.environ.get('SVS_STATUTE_CORPUS_ROOT')
    if not configured:
        pytest.skip('set SVS_STATUTE_CORPUS_ROOT for the required retained-corpus proof')
    root = Path(configured)
    assert root.is_dir(), 'explicitly required statute corpus is missing'
    return root


@pytest.fixture(scope='module')
def real_harvest(corpus_root):
    return preflight_statute_harvest(corpus_root / 'manifests/statute_scrape_20260911_030653.json',
                                   corpus_root, expected_manifest_sha256=MANIFEST_SHA)


def test_all_retained_files_hashes_slices_and_history_counts(real_harvest):
    proof = real_harvest.proof
    assert proof['files_verified'] == 31079 and proof['manifest_records'] == 31085
    assert proof['rendered_bytes_verified'] == 66750184
    assert proof['duplicate_group_count'] == 6
    assert proof['raw_unresolved_history_occurrences'] == 72753
    assert proof['deduplicated_unresolved_history_occurrences'] == 72733
    assert proof['classifications'] == {'empty_body': 2264, 'inline_history_only': 3, 'substantive_body': 28812,
                                       'structural_nonempty_body': 28815, 'structural_nonempty_body_at_most_400_bytes': 667}
    assert proof['chunks'] == 83258
    assert proof['publication_allowed'] is proof['custody_eligibility_verified'] is False
    assert all(d['response_sha256'] for d in real_harvest.documents.values() if len(d['capture_observations']) == 2)
    duplicate = next(d for d in real_harvest.documents.values() if d['filename'] == 'ksa_073_002_0001.md')
    assert duplicate['section_number'] == '73-201'
    assert duplicate['response_hash_basis'] == 'decoded_response_text_reencoded_utf8'
    assert duplicate['source_label_observations'] == ['73-201', 'PUBLIC SERVICE73-201']
    assert duplicate['response_sha256'] == 'c3b18b39b7218ebd49f9659663b21a700a278e039301bcccb82b5112d2a070ba'


@pytest.mark.parametrize('filename,digest,phrase', [
    ('ksa_002_003_0003.md', '5501388fc2e8da55cef32d49d15e7f5f14c0b20341d43e9f46d8c4cb381c7d02', 'paying premiums offered for speed'),
    ('ksa_002_009_0008.md', 'de412ef94af7c78fb678917ebedb1147401114f33274c7900fd4b28ffcd4e8ff', 'act'),
    ('ksa_002_009_0016.md', '88c78d7b91a96778ea1a027e05b61cf133ea9865ad093ee1b49cd4042d36a683', 'misdemeanor'),
])
def test_short_real_laws_survive_without_byte_filter(corpus_root, filename, digest, phrase):
    text = (corpus_root / 'data/ksa' / filename).read_bytes().decode('utf-8')
    chunks = statecivics_statute_markdown_chunks(text, expected_sha256=digest)
    assert len(text.encode()) < 400 and chunks
    assert any(phrase in c.text and c.metadata['statute_region'] == 'statute_body' for c in chunks)
    for c in chunks:
        assert text[c.char_start:c.char_end] == c.text
        assert c.page_start is c.page_end is None
        assert not {'provision_id', 'section_id', 'appropriation_action_id', 'effective_date'} & set(c.metadata)


@pytest.mark.parametrize('filename,classification', [
    ('ksa_060_034_0001.md', 'empty_body'), ('ksa_079_015_0064.md', 'empty_body'),
    ('ksa_041_002_0014.md', 'inline_history_only'), ('ksa_079_034_0160.md', 'inline_history_only'),
    ('ksa_079_034_0162.md', 'inline_history_only'),
])
def test_real_metadata_only_and_expiration_records_are_excluded(corpus_root, real_harvest, filename, classification):
    record = next(r for r in real_harvest.documents.values() if r['filename'] == filename)
    text = (corpus_root / 'data/ksa' / filename).read_bytes().decode('utf-8')
    assert parse_statute_markdown(text, expected_sha256=record['rendered_sha256']).classification == classification
    assert statecivics_statute_markdown_chunks(text, expected_sha256=record['rendered_sha256']) == []
    if classification == 'empty_body':
        assert len(text.encode()) > 400


def test_long_real_law_and_original_embedded_crlf_have_exact_unicode_and_lf_coordinates(corpus_root):
    for filename in ('ksa_079_036_0006.md', 'ksa_039_007_0010.md', 'ksa_079_032_0110b.md'):
        raw = (corpus_root / 'data/ksa' / filename).read_bytes()
        text = raw.decode('utf-8')
        chunks = statecivics_statute_markdown_chunks(text, expected_sha256=sha(raw))
        if filename == 'ksa_079_036_0006.md':
            assert len(chunks) > 30
        for c in chunks:
            assert 0 <= c.char_start < c.char_end <= len(text)
            assert c.text == text[c.char_start:c.char_end] and len(c.text) <= 4096
            assert c.metadata['line_start'] == text.count('\n', 0, c.char_start) + 1
            assert c.metadata['line_end'] == text.count('\n', 0, c.char_end - 1) + 1
            assert sha(c.text.encode()) == c.metadata['text_hash']
        if b'\r' in raw:
            assert any('\r' in c.text for c in chunks)


def test_long_unicode_subsections_and_overlap_never_rejoin_or_normalize():
    text = rendered('(a) ' + ('café\u2028word  ' * 1500) + '\n\n(b) A distinct provision.\n')
    chunks = statecivics_statute_markdown_chunks(text, expected_sha256=sha(text.encode()), max_tokens=64, overlap_tokens=12)
    body = [c for c in chunks if c.metadata['statute_region'] == 'statute_body']
    assert len(body) > 10 and any(b.char_start < a.char_end for a, b in zip(body, body[1:]))
    for c in chunks:
        assert c.text == text[c.char_start:c.char_end]
        assert c.metadata['line_start'] == text.count('\n', 0, c.char_start) + 1
        assert c.metadata['line_end'] == text.count('\n', 0, c.char_end - 1) + 1


@pytest.mark.parametrize('mutation', [
    lambda s: s.replace('**Source:**', '**Origin:**'),
    lambda s: s.replace('## History', '## Mystery'),
    lambda s: s.replace('**Chapter: AGRICULTURE**', 'unrecognized source preamble'),
    lambda s: s + '\n## History\nagain\n',
])
def test_unknown_renderer_layout_fails(mutation):
    text = mutation(rendered())
    with pytest.raises(ValueError, match='layout|preamble|headings'):
        parse_statute_markdown(text, expected_sha256=sha(text.encode()))


@pytest.mark.parametrize('url', [URL.replace('ksrevisor.gov', 'example.org'), URL+'?x=1', URL.replace('ch02', 'ch99'), URL.replace('https:', 'http:'), URL.replace('/002_', '/../002_')])
def test_url_must_be_exact_official_section(url):
    with pytest.raises(ValueError):
        official_statute_url(url)


def test_profile_scope_hash_and_ambiguity_are_rejected():
    text = rendered()
    attrs = {'source_text_chunking_profile': STATECIVICS_STATUTE_MARKDOWN_PROFILE,
             'source_collection': 'statecivics-kansas-statutes', 'extraction_content_hash_sha256': sha(text.encode())}
    assert choose_chunker('markdown_docs_v1', attributes=attrs)(text)
    for change in ({'source_text_chunking_profile': 'unknown'}, {'source_collection': 'other'},
                   {'source_page_chunking_profile': 'statecivics_page_markdown_v1'}, {'extraction_content_hash_sha256': '0' * 64}):
        with pytest.raises(ValueError):
            choose_chunker('markdown_docs_v1', attributes={**attrs, **change})(text)
    with pytest.raises(ValueError):
        choose_chunker('code_repo_v1', attributes=attrs)


@pytest.mark.parametrize('mutation', [
    lambda records: records[0].update(filename='../escape.md'),
    lambda records: records[0].update(rendered_sha256='0' * 64),
    lambda records: records[0].update(rendered_bytes=True),
    lambda records: records[0].update(source_url=URL.replace('ch02', 'ch99')),
    lambda records: records[0]['history_events'][0].update(resolution_status='resolved'),
    lambda records: records[1].update(rendered_bytes=99),
    lambda records: records[1].update(response_sha256='a' * 64, response_bytes=500),
    lambda records: records[1].update(section_number='9-999'),
])
def test_harvest_rejects_hash_path_url_history_and_duplicate_conflicts(tmp_path, mutation):
    path, root, records, _ = small_harvest(tmp_path, duplicates=True)
    mutation(records)
    path.write_text(json.dumps({'operation': 'statute_scrape', 'documents': records}))
    with pytest.raises(ValueError):
        preflight_statute_harvest(path, root, expected_manifest_sha256=sha(path.read_bytes()))


def test_harvest_requires_manifest_pin_and_rejects_symlink_escape(tmp_path):
    path, root, records, text = small_harvest(tmp_path)
    with pytest.raises(ValueError, match='manifest hash mismatch'):
        preflight_statute_harvest(path, root, expected_manifest_sha256='0' * 64)
    original = root / 'data/ksa' / records[0]['filename']
    outside = tmp_path / 'outside.md'
    outside.write_text(text)
    original.unlink()
    original.symlink_to(outside)
    with pytest.raises(ValueError, match='escapes'):
        preflight_statute_harvest(path, root, expected_manifest_sha256=sha(path.read_bytes()))


def test_preflight_cli_outputs_only_local_proof_and_refuses_input_overwrite(tmp_path):
    path, root, _, _ = small_harvest(tmp_path)
    script = Path(__file__).resolve().parents[1] / 'scripts/release/kansas-statute-preflight.py'
    command = [sys.executable, str(script), '--manifest', str(path), '--corpus-root', str(root),
               '--expected-manifest-sha256', sha(path.read_bytes())]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0
    proof = json.loads(result.stdout)
    assert proof['kind'] == 'statecivics-statute-local-preparation-proof-v1' and proof['publication_allowed'] is False
    result = subprocess.run(command + ['--proof', str(path)], text=True, capture_output=True)
    assert result.returncode == 2 and 'outside' in result.stderr


def test_history_prefixed_substantive_prose_is_not_silently_excluded():
    text = rendered('History: the law requires a report marked Expired, today.')
    with pytest.raises(ValueError, match='requires review'):
        parse_statute_markdown(text, expected_sha256=sha(text.encode()))


@pytest.mark.parametrize('maximum,overlap', [(True, 0), (15, 0), (2001, 0), (16, 16), (16, -1)])
def test_chunk_resource_bounds_are_explicit(maximum, overlap):
    text = rendered()
    with pytest.raises(ValueError, match='token bounds'):
        statecivics_statute_markdown_chunks(text, expected_sha256=sha(text.encode()), max_tokens=maximum, overlap_tokens=overlap)
