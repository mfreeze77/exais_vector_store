"""Retained K.S.A. Markdown preparation. No custody eligibility or legal graph claims."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

STATECIVICS_STATUTE_MARKDOWN_PROFILE = 'statecivics_statute_markdown_v1'
SOURCE_TEXT_CHUNKING_PROFILE_ATTRIBUTE = 'source_text_chunking_profile'
STATUTE_SOURCE_COLLECTION = 'statecivics-kansas-statutes'
STATUTE_EMBEDDING_PROFILE = 'voyage_4_docs_1024'
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_DOCUMENTS = 50000
MAX_CORPUS_BYTES = 256 * 1024 * 1024
TRAILING_HEADINGS = ('History', 'Source or Prior Law', "Revisor's Note", 'Case Annotations',
                     'Attorney General Opinions', 'Law Review References')
_SHA = re.compile(r'[0-9a-f]{64}')
_FILENAME = re.compile(r'ksa_([0-9]{3}[a-z]?)_([0-9]{3}[a-z]?)_([0-9]{4}[a-z]?)\.md')
_URL = re.compile(r'https://ksrevisor\.gov/statutes/chapters/ch[0-9]{2}[a-z]?/([0-9]{3}[a-z]?_[0-9]{3}[a-z]?_[0-9]{4}[a-z]?)\.html')


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    return _hash(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f'{field} must be a lowercase SHA-256')
    return value


def official_statute_url(value: Any) -> str:
    if not isinstance(value, str) or _URL.fullmatch(value) is None:
        raise ValueError('statute source URL must be an exact official ksrevisor.gov section URL')
    chapter = value.split('/chapters/ch', 1)[1].split('/', 1)[0]
    component = _URL.fullmatch(value).group(1).split('_', 1)[0]
    if chapter.lstrip('0') != component.lstrip('0'):
        raise ValueError('statute URL chapter directory differs from the section path')
    return value


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'{path.name} exceeds the byte bound')
    return raw


@dataclass(frozen=True)
class StatuteDocument:
    title: str
    section_label: str
    source_url: str
    body_start: int
    body_end: int
    classification: str
    metadata_regions: tuple[tuple[str, int, int], ...]


def parse_statute_markdown(md: str, *, expected_sha256: str, expected_source_url: str | None = None) -> StatuteDocument:
    if not isinstance(md, str) or len(md) > MAX_DOCUMENT_BYTES:
        raise ValueError('statute Markdown must be bounded Unicode text')
    raw = md.encode('utf-8', errors='strict')
    if len(raw) > MAX_DOCUMENT_BYTES or '\x00' in md:
        raise ValueError('statute Markdown requires bounded UTF-8 without NUL')
    if _hash(raw) != _sha(expected_sha256, 'rendered hash'):
        raise ValueError('statute rendered hash mismatch')
    title = re.match(r'# K\.S\.A\. ([^\n]+?) — ([^\n]*)\n\n', md)
    sources = list(re.finditer(r'^\*\*Source:\*\* ([^\n]+)\n', md, re.MULTILINE))
    if title is None or len(sources) != 1:
        raise ValueError('unsupported statute renderer title/source layout')
    source = sources[0]
    prefix = md[title.end():source.start()]
    if source.start() < title.end() or any(line and not re.fullmatch(r'\*\*[^\n]+\*\*', line) for line in prefix.split('\n')):
        raise ValueError('unsupported statute renderer preamble')
    url = official_statute_url(source.group(1))
    if expected_source_url is not None and url != official_statute_url(expected_source_url):
        raise ValueError('statute source URL differs from the declared source')
    headings = list(re.finditer(r'^## ([^\n]+)\n', md[source.end():], re.MULTILINE))
    names = [h.group(1) for h in headings]
    if (any(name not in TRAILING_HEADINGS for name in names) or len(set(names)) != len(names)
            or names != sorted(names, key=TRAILING_HEADINGS.index)):
        raise ValueError('unsupported or reordered statute metadata headings')
    positions = [(h.group(1), source.end() + h.start()) for h in headings]
    body_start = source.end()
    body_end = positions[0][1] if positions else len(md)
    body = md[body_start:body_end].strip()
    classification = 'empty_body' if not body else 'substantive_body'
    if body.startswith('History:'):
        if not re.fullmatch(r'History: (?:L\. [0-9]{4}, ch\. [0-9]+, § [0-9]+; )+Expired, [A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}\.', body):
            raise ValueError('unsupported inline History body; requires review')
        classification = 'inline_history_only'
    regions = tuple((name, start, positions[i + 1][1] if i + 1 < len(positions) else len(md))
                    for i, (name, start) in enumerate(positions))
    return StatuteDocument(title.group(0).split('\n')[0][2:], title.group(1), url,
                           body_start, body_end, classification, regions)


def statecivics_statute_markdown_chunks(md: str, max_tokens: int = 800, overlap_tokens: int = 120, *,
                                       expected_sha256: str, expected_source_url: str | None = None):
    from .chunking import ParsedChunk, estimate_tokens
    parsed = parse_statute_markdown(md, expected_sha256=expected_sha256, expected_source_url=expected_source_url)
    if (type(max_tokens) is not int or not 16 <= max_tokens <= 2000
            or type(overlap_tokens) is not int or not 0 <= overlap_tokens < max_tokens):
        raise ValueError('statute token bounds require 16..2000 and 0 <= overlap < maximum')
    if parsed.classification != 'substantive_body':
        return []
    # Title/source remain exact retained evidence; semantic chunks carry their
    # context as metadata and separate the statutory body from trailing material.
    regions = [('statute_body', parsed.body_start, parsed.body_end), *parsed.metadata_regions]
    line_starts = [0] + [m.end() for m in re.finditer('\n', md)]
    chunks = []
    for role, region_start, region_end in regions:
        body = md[region_start:region_end]
        words = list(re.finditer(r'\S+', body))
        starts, ends = [m.start() for m in words], [m.end() for m in words]
        boundaries = sorted({m.end() for m in re.finditer(r'\n[ \t]*\n', body)} |
                            {m.start() for m in re.finditer(r'^\([a-z0-9]+\)[ \t]', body, re.MULTILINE)})
        start = 0
        while start < len(body):
            first_word = bisect_right(ends, start)
            end = min(len(body), start + 4096)
            if first_word + max_tokens * 3 // 4 < len(words):
                end = min(end, starts[first_word + max_tokens * 3 // 4])
            if end < len(body):
                boundary = bisect_right(boundaries, end) - 1
                if boundary >= 0 and boundaries[boundary] >= start + max(1, (end - start) // 2):
                    end = boundaries[boundary]
            if end <= start:
                raise ValueError('statute splitter failed to advance')
            text = body[start:end]
            absolute_start, absolute_end = region_start + start, region_start + end
            if text.strip():
                if len(chunks) >= 20000:
                    raise ValueError('statute exceeds 20000 chunks')
                metadata = {
                    'chunker': STATECIVICS_STATUTE_MARKDOWN_PROFILE,
                    'text_hash': _hash(text.encode('utf-8')),
                    'extraction_content_hash_sha256': expected_sha256,
                    'statute_section_label': parsed.section_label,
                    'statute_source_url': parsed.source_url,
                    'statute_body_classification': parsed.classification,
                    'statute_region': role,
                    'char_start': absolute_start, 'char_end': absolute_end,
                    'character_coordinate_convention': 'unicode-codepoints-zero-based-end-exclusive-v1',
                    'line_coordinate_convention': 'lf-document-lines-one-based-inclusive-v1',
                    'line_start': bisect_right(line_starts, absolute_start),
                    'line_end': bisect_right(line_starts, absolute_end - 1),
                    'line_range_is_enclosing': True,
                }
                chunks.append(ParsedChunk(ordinal=len(chunks), text=text, heading_path=[parsed.title, role],
                                          char_start=absolute_start, char_end=absolute_end,
                                          token_count=estimate_tokens(text), metadata=metadata))
            if end == len(body):
                break
            last_word = bisect_right(starts, end - 1)
            overlap = overlap_tokens * 3 // 4
            overlap_start = starts[max(first_word, last_word - overlap)] if overlap and last_word else end
            start = max(end - (end - start) // 2, min(end, overlap_start))
    return chunks


@dataclass(frozen=True)
class StatuteHarvest:
    manifest_sha256: str
    documents: dict[tuple[str, str], dict[str, Any]]
    proof: dict[str, Any]


def _validate_history(events: Any) -> None:
    if not isinstance(events, list) or len(events) > 2000:
        raise ValueError('history events must be a bounded ordered list')
    for index, event in enumerate(events, 1):
        if (not isinstance(event, dict) or event.get('ordinal') != index or type(event.get('ordinal')) is not int
                or event.get('resolution_status') != 'unresolved' or type(event.get('year')) is not int
                or not 1800 <= event['year'] <= 2200
                or not isinstance(event.get('citation_text'), str) or not event['citation_text']
                or any(event.get(k) is not None and (not isinstance(event[k], str) or not event[k]) for k in ('chapter', 'section'))):
            raise ValueError('invalid ordered unresolved history event')


def preflight_statute_harvest(manifest: Path, corpus_root: Path, *, expected_manifest_sha256: str) -> StatuteHarvest:
    raw_manifest = _read_bounded(manifest, MAX_MANIFEST_BYTES)
    digest = _hash(raw_manifest)
    if digest != _sha(expected_manifest_sha256, 'manifest hash'):
        raise ValueError('statute harvest manifest hash mismatch')
    payload = json.loads(raw_manifest.decode('utf-8'))
    records = payload.get('documents') if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get('operation') != 'statute_scrape' or not isinstance(records, list) or not 1 <= len(records) <= MAX_DOCUMENTS:
        raise ValueError('unsupported statute harvest manifest')
    root = corpus_root.resolve()
    data_root = (root / 'data' / 'ksa').resolve()
    if not data_root.is_relative_to(root):
        raise ValueError('statute data path escapes corpus root')
    grouped: dict[str, list[dict]] = {}
    raw_events = 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('statute manifest record must be an object')
        filename = record.get('filename')
        match = _FILENAME.fullmatch(filename) if isinstance(filename, str) else None
        url = official_statute_url(record.get('source_url'))
        if match is None or _URL.fullmatch(url).group(1) != filename[4:-3]:
            raise ValueError('statute filename/path does not match official source URL')
        if not isinstance(record.get('section_number'), str) or not record['section_number']:
            raise ValueError('statute section label is missing')
        _sha(record.get('rendered_sha256'), 'rendered hash')
        if type(record.get('rendered_bytes')) is not int or not 1 <= record['rendered_bytes'] <= MAX_DOCUMENT_BYTES:
            raise ValueError('statute rendered byte count out of bounds')
        response_hash, response_bytes = record.get('response_sha256'), record.get('response_bytes')
        if response_hash is not None:
            _sha(response_hash, 'response-text capture hash')
            if type(response_bytes) is not int or not 1 <= response_bytes <= 32 * 1024 * 1024:
                raise ValueError('response-text capture byte count out of bounds')
        elif response_bytes is not None:
            raise ValueError('response-text byte count has no hash')
        observed = record.get('scraped_at_utc')
        if not isinstance(observed, str) or datetime.fromisoformat(observed).tzinfo is None:
            raise ValueError('scraped_at_utc requires a timezone-aware observation timestamp')
        if type(record.get('retained_from_previous_run')) is not bool:
            raise ValueError('retained_from_previous_run must be boolean')
        if record.get('history_raw') is not None and not isinstance(record['history_raw'], str):
            raise ValueError('history_raw must be text or null')
        _validate_history(record.get('history_events'))
        raw_events += len(record['history_events'])
        grouped.setdefault(filename, []).append(record)
    documents = {}
    counts: Counter = Counter()
    duplicate_groups = []
    total_bytes = 0
    chunk_count = 0
    history_count = 0
    for filename in sorted(grouped):
        group = grouped[filename]
        first = group[0]
        for other in group[1:]:
            if any(other.get(k) != first.get(k) for k in ('source_url', 'rendered_sha256', 'rendered_bytes', 'history_raw', 'history_events')):
                raise ValueError(f'conflicting duplicate statute record: {filename}')
        captures = {(r.get('response_sha256'), r.get('response_bytes')) for r in group if r.get('response_sha256') is not None}
        if len(captures) > 1:
            raise ValueError(f'conflicting response-text captures: {filename}')
        path = (data_root / filename).resolve()
        if not path.is_relative_to(data_root):
            raise ValueError('statute file path escapes data root')
        raw = _read_bounded(path, MAX_DOCUMENT_BYTES)
        total_bytes += len(raw)
        if total_bytes > MAX_CORPUS_BYTES or len(raw) != first['rendered_bytes']:
            raise ValueError('statute corpus or rendered byte count mismatch')
        md = raw.decode('utf-8', errors='strict')
        parsed = parse_statute_markdown(md, expected_sha256=first['rendered_sha256'], expected_source_url=first['source_url'])
        # Numbering is a source label, not persistent identity. The renderer title
        # may represent a range; duplicate TOC contamination is reconciled only
        # when an explicit clean manifest label is present in the same group.
        selected = next((r for r in group if r['section_number'] == parsed.section_label), None)
        if selected is None:
            if len(group) > 1:
                raise ValueError('duplicate statute records have no clean rendered section label')
            selected = first
        if len(group) > 1 and any(r['section_number'] != selected['section_number'] and
                not re.fullmatch(r'[A-Z ,’\x27-]+' + re.escape(selected['section_number']), r['section_number']) for r in group):
            raise ValueError('conflicting duplicate statute section labels')
        if len(group) > 1:
            duplicate_groups.append({'filename': filename, 'record_count': len(group), 'section_label': selected['section_number']})
        chosen = dict(selected)
        captured = next((r for r in group if r.get('response_sha256') is not None), None)
        if captured:
            chosen.update({k: captured[k] for k in ('response_sha256', 'response_bytes', 'scraped_at_utc', 'retained_from_previous_run')})
        chosen['source_label_observations'] = sorted({r['section_number'] for r in group})
        chosen['response_hash_basis'] = 'decoded_response_text_reencoded_utf8'
        chosen['classification'] = parsed.classification
        chosen['rendered_section_label'] = parsed.section_label
        chosen['capture_observations'] = sorted([{k: r[k] for k in ('scraped_at_utc', 'retained_from_previous_run', 'response_sha256', 'response_bytes')}
                                                 for r in group], key=lambda r: (r['scraped_at_utc'], str(r['response_sha256'])))
        chosen['evidence_context_sha256'] = _digest(chosen)
        key = (first['source_url'], first['rendered_sha256'])
        if key in documents:
            raise ValueError('duplicate URL/hash has conflicting filenames')
        documents[key] = chosen
        counts[parsed.classification] += 1
        if parsed.classification != 'empty_body':
            counts['structural_nonempty_body'] += 1
            if len(raw) <= 400:
                counts['structural_nonempty_body_at_most_400_bytes'] += 1
        chunks = statecivics_statute_markdown_chunks(md, expected_sha256=first['rendered_sha256'], expected_source_url=first['source_url'])
        chunk_count += len(chunks)
        history_count += len(chosen['history_events'])
        for chunk in chunks:
            if (md[chunk.char_start:chunk.char_end] != chunk.text
                    or _hash(chunk.text.encode('utf-8')) != chunk.metadata['text_hash']):
                raise ValueError('statute chunk coordinates do not select their exact bytes')
    if 'files_written' in payload and (type(payload['files_written']) is not int or payload['files_written'] != len(documents)):
        raise ValueError('manifest files_written differs from unique verified files')
    proof = {
        'kind': 'statecivics-statute-local-preparation-proof-v1', 'publication_allowed': False,
        'custody_eligibility_verified': False, 'canonical_relationships_created': False,
        'response_capture_basis': 'upstream UTF-8 re-encoded response text; raw HTTP bytes not retained here',
        'manifest_sha256': digest, 'manifest_bytes': len(raw_manifest), 'manifest_records': len(records),
        'files_verified': len(documents), 'rendered_bytes_verified': total_bytes,
        'duplicate_groups': duplicate_groups, 'duplicate_group_count': len(duplicate_groups),
        'classifications': dict(sorted(counts.items())), 'chunks': chunk_count,
        'raw_unresolved_history_occurrences': raw_events, 'deduplicated_unresolved_history_occurrences': history_count,
        'chunking_profile': STATECIVICS_STATUTE_MARKDOWN_PROFILE,
        'embedding_profile_required_for_ingestion': STATUTE_EMBEDDING_PROFILE,
    }
    return StatuteHarvest(digest, documents, proof)
