"""Exact-coordinate parser proof; real retained books are opt-in, read-only."""
import hashlib
import os
from pathlib import Path
import re

import pytest

from svs_common.chunking import (
    STATECIVICS_PAGE_MARKDOWN_PROFILE,
    choose_chunker,
    markdown_heading_chunks,
    statecivics_page_markdown_chunks,
)

BOOKS = [
    ('2023-Session-Laws-Book-1.md', 891, '67741c21f25417d84b50623f1d3ef53f478e442ab061fea5ee12f4dededc796f'),
    ('2023-Session-Laws-Book-2.md', 938, '7ee034aac2ce0f377f2feac8bbe465812f3269c99c12c0730580fd716101d75a'),
    ('2024-Session-Laws-Book-1.md', 894, '9604ea82cd71fcf5c22526cb754c3de346ca4e2104540883c1cc9b3234b7eab5'),
    ('2024-Session-Laws-Book-2.md', 894, 'b2b05716990cfd09ea9543ed7f8f25123d3747365a408caed9989500a2ec5c0e'),
    ('2024-Session-Laws-Book-3.md', 830, '9dcc0173cb4fe0d447eb4d2d7dc7095eb1ac0ebacf056aea3c381659f474e266'),
    ('2025-Session-Laws-Book-1.md', 1068, '48bd4e217399c3cb7fb89493868d2ed69ed34d926f6ca309a0bfa000134ecbac'),
    ('2025-Session-Laws-Book-2.md', 1072, '3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7'),
]


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _chunks(text, **kwargs):
    return statecivics_page_markdown_chunks(text, expected_sha256=_hash(text), **kwargs)


def _assert_exact(text, chunks):
    marks = list(re.finditer(r'^<!-- page ([0-9]+) -->\n', text, re.M))
    digest = _hash(text)
    for ordinal, chunk in enumerate(chunks):
        assert chunk.ordinal == ordinal
        assert chunk.text == text[chunk.char_start:chunk.char_end]
        assert chunk.metadata['text_hash'] == _hash(chunk.text)
        assert chunk.metadata['extraction_content_hash_sha256'] == digest
        assert chunk.metadata['char_start'] == chunk.char_start
        assert chunk.metadata['char_end'] == chunk.char_end
        assert chunk.metadata['parsed_page_count'] == len(marks)
        assert len(chunk.text) <= 4096
        assert chunk.page_start == chunk.page_end
        assert not {'provision_id', 'action_id', 'bill_id', 'appropriation_action_id'} & set(chunk.metadata)
        if chunk.page_start is None:
            assert chunk.metadata['unpaginated_preamble'] is True
            assert chunk.char_end <= marks[0].start()
            assert chunk.heading_path == []
            continue
        marker = marks[chunk.page_start - 1]
        page_end = marks[chunk.page_start].start() if chunk.page_start < len(marks) else len(text)
        assert marker.end() <= chunk.char_start < chunk.char_end <= page_end
        assert chunk.metadata['line_coordinate_convention'] == 'lf-page-marker-is-line-one-v1'
        assert chunk.metadata['line_start'] == text[marker.start():chunk.char_start].count('\n') + 1
        assert chunk.metadata['line_end'] == text[marker.start():chunk.char_end - 1].count('\n') + 1


def test_exact_slices_preserve_blank_lines_unicode_and_meaningful_prefix():
    text = '# Generated-File-Name\n\nMeaningful unpaginated introduction.\n<!-- page 1 -->\n\n  café\u2028same line \n\nend\n<!-- page 2 -->\nnext\n'
    chunks = _chunks(text, declared_page_count=2)
    _assert_exact(text, chunks)
    assert len(chunks) == 3 and chunks[0].page_start is None
    assert chunks[1].metadata['line_start'] == 2
    assert chunks[1].heading_path == []
    assert chunks[1].text.startswith('\n  café\u2028same line ')
    assert chunks[0].metadata['page_count_basis'] == 'declared'
    assert _chunks(text)[0].metadata['page_count_basis'] == 'parsed_marker_inventory'


def test_genuine_headings_are_boundaries_without_filename_heading_inheritance():
    text = '# Filename\n\n<!-- page 1 -->\n# Actual heading\nfirst body\n## Second heading\nsecond body\n'
    chunks = _chunks(text)
    assert [c.heading_path for c in chunks] == [[], ['Actual heading'], ['Actual heading', 'Second heading']]
    _assert_exact(text, chunks)


def test_long_pages_and_unbroken_lines_have_exact_overlap_and_bounded_progress():
    text = '<!-- page 1 -->\n' + 'é' * 10000 + '\n' + ('word \n' * 1000) + '<!-- page 2 -->\nlast\n'
    chunks = _chunks(text, max_tokens=200, overlap_tokens=30)
    _assert_exact(text, chunks)
    page = [c for c in chunks if c.page_start == 1]
    assert len(page) > 3
    assert all(b.char_start > a.char_start and b.char_start <= a.char_end for a, b in zip(page, page[1:]))
    assert any(b.char_start < a.char_end for a, b in zip(page, page[1:]))
    assert page[0].metadata['line_start'] == page[0].metadata['line_end'] == 2
    assert page[-1].char_end == text.index('<!-- page 2 -->')


@pytest.mark.parametrize('text,kwargs', [
    ('no marker', {}),
    ('<!-- page 1 -->\ntext\n<!-- page 1 -->\nother\n', {}),
    ('<!-- page 2 -->\ntext\n', {}),
    ('<!-- page 1 -->\ntext\n inline <!-- page 2 -->\n', {}),
    ('<!-- page 1 -->\r\ntext\n', {}),
    ('<!-- page 1 -->\ntext\n', {'declared_page_count': 2}),
    ('<!-- page 1 -->\ntext\n', {'declared_page_count': True}),
    ('<!-- page 1 -->\ntext\n', {'declared_page_count': 0}),
    ('<!-- page 1 -->\ntext\n', {'max_tokens': True}),
    ('<!-- page 1 -->\ntext\n', {'max_tokens': 10}),
    ('<!-- page 1 -->\ntext\n', {'overlap_tokens': -1}),
    ('<!-- page 1 -->\ntext\n', {'overlap_tokens': 800}),
])
def test_invalid_markers_counts_and_split_bounds_fail(text, kwargs):
    with pytest.raises(ValueError):
        _chunks(text, **kwargs)


@pytest.mark.parametrize('digest', [None, 'bad', 'A' * 64, '0' * 64])
def test_extraction_hash_is_required_and_must_match(digest):
    with pytest.raises(ValueError, match='SHA-256|hash mismatch'):
        statecivics_page_markdown_chunks('<!-- page 1 -->\ntext\n', expected_sha256=digest)


def test_oversized_extraction_and_invalid_utf8_fail_before_parsing():
    with pytest.raises(ValueError, match='16 MiB'):
        statecivics_page_markdown_chunks('é' * (9 * 1024 * 1024), expected_sha256='a' * 64)
    with pytest.raises(ValueError, match='valid UTF-8'):
        statecivics_page_markdown_chunks('\ud800', expected_sha256='a' * 64)


def test_dense_page_word_inventory_is_bounded_before_chunk_materialization():
    with pytest.raises(ValueError, match='region exceeds 100000 words'):
        _chunks('<!-- page 1 -->\n' + 'x ' * 100001)


def test_opt_in_is_explicit_scoped_and_preserves_generic_chunker():
    assert choose_chunker('markdown_docs_v1') is markdown_heading_chunks
    assert choose_chunker('markdown_docs_v1', attributes={'unrelated': True}) is markdown_heading_chunks
    text = '<!-- page 1 -->\ntext\n'
    attrs = {'source_page_chunking_profile': STATECIVICS_PAGE_MARKDOWN_PROFILE,
             'source_collection': 'statecivics-kansas-fiscal-documents', 'extraction_content_hash_sha256': _hash(text)}
    assert choose_chunker('markdown_docs_v1', attributes=attrs)(text)[0].page_start == 1
    for mode, changes in [('pdf_markdown_external_v1', {}), ('markdown_docs_v1', {'source_collection': 'other'}),
                          ('markdown_docs_v1', {'source_page_chunking_profile': 'guess'})]:
        with pytest.raises(ValueError):
            choose_chunker(mode, attributes={**attrs, **changes})


@pytest.mark.parametrize('filename,pages,digest', BOOKS)
def test_all_retained_books_preserve_every_chunk_slice_page_and_hash(filename, pages, digest):
    corpus = os.environ.get('SVS_FISCAL_SESSION_LAWS_ROOT')
    if not corpus:
        pytest.skip('requires read-only retained Session Laws corpus')
    path = Path(corpus) / 'markdown' / filename
    assert path.is_file(), 'explicitly configured retained book is missing'
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    text = raw.decode('utf-8')
    chunks = statecivics_page_markdown_chunks(text, expected_sha256=digest, declared_page_count=pages)
    _assert_exact(text, chunks)
    markers = list(re.finditer(r'^<!-- page ([0-9]+) -->\n', text, re.M))
    nonempty_pages = set()
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        if text[marker.end():end].strip():
            nonempty_pages.add(index + 1)
        cursor = marker.end()
        for chunk in (c for c in chunks if c.page_start == index + 1):
            assert not text[cursor:chunk.char_start].strip(), 'meaningful source text omitted between chunks'
            cursor = max(cursor, chunk.char_end)
        assert not text[cursor:end].strip(), 'meaningful source text omitted at page end'
    # Empty retained pages have markers and verified inventory, not fake chunks.
    assert set(c.page_start for c in chunks if c.page_start) == nonempty_pages
    assert all(c.token_count <= 800 for c in chunks)
    if filename == '2025-Session-Laws-Book-2.md':
        matches = [c for c in chunks if '$4,000,000 is hereby lapsed.' in c.text]
        assert len(matches) == 1
        hit = matches[0]
        assert hit.page_start == 358 and hit.char_start <= 986097 < 986411 <= hit.char_end
        assert '$156,085,651 is hereby lapsed.' in hit.text
        # Chunk membership is broader than the fixed, independently hashed legal clause.
        quote = text[986097:986411]
        assert _hash(quote) == '3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6'
        assert hit.text != quote and hit.metadata['text_hash'] != _hash(quote)
        assert hit.heading_path == []
