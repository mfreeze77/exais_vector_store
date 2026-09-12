from __future__ import annotations
import csv
import io
import json
import re
from bisect import bisect_right
from functools import partial
from dataclasses import dataclass, field
from typing import Any
from .hashing import sha256_text
from .statecivics_statutes import (STATECIVICS_STATUTE_MARKDOWN_PROFILE, SOURCE_TEXT_CHUNKING_PROFILE_ATTRIBUTE,
                                  STATUTE_SOURCE_COLLECTION, statecivics_statute_markdown_chunks)

STATECIVICS_PAGE_MARKDOWN_PROFILE = 'statecivics_page_markdown_v1'
SOURCE_PAGE_CHUNKING_PROFILE_ATTRIBUTE = 'source_page_chunking_profile'
_PAGE_MARKDOWN_MAX_BYTES = 16 * 1024 * 1024
_PAGE_MARKDOWN_MAX_PAGES = 10000
_PAGE_MARKDOWN_MAX_CHUNKS = 20000
_PAGE_MARKDOWN_MAX_CHARACTERS = 4096
_PAGE_MARKDOWN_MAX_REGION_WORDS = 100000

@dataclass
class ParsedChunk:
    ordinal: int
    text: str
    heading_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()) * 4 // 3)

def split_oversized(text: str, max_tokens: int = 800, overlap_tokens: int = 120) -> list[str]:
    words = text.split()
    approx_words = max(80, max_tokens * 3 // 4)
    overlap_words = max(0, overlap_tokens * 3 // 4)
    if len(words) <= approx_words:
        return [text]
    chunks, start = [], 0
    while start < len(words):
        end = min(len(words), start + approx_words)
        chunks.append(' '.join(words[start:end]))
        if end == len(words):
            break
        start = max(end - overlap_words, start + 1)
    return chunks

def markdown_heading_chunks(md: str, max_tokens: int = 800, overlap_tokens: int = 120) -> list[ParsedChunk]:
    lines = md.splitlines()
    sections: list[tuple[list[str], int, int, list[str]]] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    section_start = 0

    def flush(end_line: int):
        nonlocal current_lines, section_start
        body = '\n'.join(current_lines).strip()
        if body:
            sections.append((heading_stack.copy(), section_start, end_line, current_lines.copy()))
        current_lines = []
        section_start = end_line + 1

    for i, line in enumerate(lines):
        match = re.match(r'^(#{1,6})\s+(.*)$', line)
        if match:
            flush(i - 1)
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack = heading_stack[: level - 1] + [title]
            current_lines = [line]
            section_start = i
        else:
            current_lines.append(line)
    flush(len(lines) - 1)

    chunks, ordinal = [], 0
    if not sections and md.strip():
        sections = [([], 0, len(lines) - 1, lines)]
    for headings, start_line, end_line, body_lines in sections:
        text = '\n'.join(body_lines).strip()
        if not text:
            continue
        for part in split_oversized(text, max_tokens=max_tokens, overlap_tokens=overlap_tokens):
            chunks.append(ParsedChunk(
                ordinal=ordinal,
                text=part,
                heading_path=headings,
                token_count=estimate_tokens(part),
                metadata={'chunker': 'markdown_heading_chunks', 'line_start': start_line + 1, 'line_end': end_line + 1, 'text_hash': sha256_text(part)}
            ))
            ordinal += 1
    return chunks

def pdf_markdown_external_chunks(md: str, max_tokens: int = 900, overlap_tokens: int = 160) -> list[ParsedChunk]:
    # Consumes the user's existing PDF->Markdown output. It does not parse PDFs.
    chunks = markdown_heading_chunks(md, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
    current_page = None
    for ch in chunks:
        marker = re.search(r'(?:<!--\s*page[:=]\s*(\d+)\s*-->|^\s*Page\s+(\d+)\b)', ch.text, re.I | re.M)
        if marker:
            current_page = int(marker.group(1) or marker.group(2))
        ch.page_start = current_page
        ch.page_end = current_page
        ch.metadata['pdf_markdown_external'] = True
        ch.metadata['chunker'] = 'pdf_markdown_external_chunks'
    return chunks

def _record_group_chunks(
    records: list[dict[str, Any]],
    keys: list[str],
    *,
    max_records_per_chunk: int = 25,
    chunker: str,
    heading_path: list[str],
    base_metadata: dict[str, Any] | None = None,
    ordinal_start: int = 0,
    prefix_lines: list[str] | None = None,
    metadata_factory: Any | None = None,
) -> list[ParsedChunk]:
    ordered_keys = list(dict.fromkeys(keys))
    chunks: list[ParsedChunk] = []
    ordinal = ordinal_start
    for start in range(0, len(records), max_records_per_chunk):
        group = records[start:start + max_records_per_chunk]
        lines = list(prefix_lines or [])
        lines.extend([
            f'Schema fields: {", ".join(ordered_keys)}',
            f'Record range: {start + 1}-{start + len(group)}',
        ])
        for idx, record in enumerate(group, start=start + 1):
            items = ' | '.join(f'{k}: {record.get(k, "")}' for k in ordered_keys if k in record)
            lines.append(f'Record {idx}: {items}')
        text = '\n'.join(lines)
        metadata = {
            'chunker': chunker,
            'record_start': start + 1,
            'record_end': start + len(group),
            'record_count': len(group),
            'schema_fields': ordered_keys,
            'text_hash': sha256_text(text),
        }
        metadata.update(base_metadata or {})
        if metadata_factory:
            metadata.update(metadata_factory(start, group))
        chunks.append(ParsedChunk(
            ordinal=ordinal,
            text=text,
            heading_path=heading_path,
            token_count=estimate_tokens(text),
            metadata=metadata,
        ))
        ordinal += 1
    return chunks

def _split_markdown_table_row(line: str) -> list[str]:
    raw = line.strip()
    if '|' not in raw:
        return []
    if raw.startswith('|'):
        raw = raw[1:]
    if raw.endswith('|'):
        raw = raw[:-1]
    cells = [re.sub(r'\s+', ' ', cell.strip()) for cell in raw.split('|')]
    return cells if len(cells) > 1 else []

def _is_markdown_table_separator(line: str) -> bool:
    cells = _split_markdown_table_row(line)
    if len(cells) < 2:
        return False
    return all(re.match(r'^:?-{3,}:?$', cell.replace(' ', '')) for cell in cells)

def _markdown_table_caption(lines: list[str], header_index: int) -> str | None:
    idx = header_index - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1
    if idx < 0:
        return None
    candidate = lines[idx].strip().strip('#').strip()
    if not candidate or '|' in candidate or _is_markdown_table_separator(candidate):
        return None
    return candidate

def _markdown_table_blocks(content: str) -> list[dict[str, Any]]:
    lines = content.splitlines()
    fenced = [False for _ in lines]
    in_fence = False
    for idx, line in enumerate(lines):
        if re.match(r'^\s*(```|~~~)', line):
            fenced[idx] = True
            in_fence = not in_fence
            continue
        fenced[idx] = in_fence

    tables: list[dict[str, Any]] = []
    idx = 0
    while idx < len(lines) - 1:
        if fenced[idx] or fenced[idx + 1] or not _is_markdown_table_separator(lines[idx + 1]):
            idx += 1
            continue
        headers = _split_markdown_table_row(lines[idx])
        if len(headers) < 2:
            idx += 1
            continue
        row_start = idx + 2
        row_idx = row_start
        rows: list[dict[str, str]] = []
        while row_idx < len(lines) and not fenced[row_idx] and lines[row_idx].strip() and '|' in lines[row_idx]:
            cells = _split_markdown_table_row(lines[row_idx])
            if len(cells) < 2 or _is_markdown_table_separator(lines[row_idx]):
                break
            record = {headers[col]: cells[col] if col < len(cells) else '' for col in range(len(headers))}
            rows.append(record)
            row_idx += 1
        if rows:
            tables.append({
                'headers': headers,
                'rows': rows,
                'caption': _markdown_table_caption(lines, idx),
                'table_start_line': idx + 1,
                'row_start_line': row_start + 1,
                'table_end_line': row_idx,
            })
            idx = row_idx
            continue
        idx += 1
    return tables

def _delimited_records(content: str) -> list[dict[str, Any]]:
    nonblank = [line for line in content.splitlines() if line.strip()]
    if len(nonblank) < 2:
        return []
    header = nonblank[0]
    delimiter = '\t' if '\t' in header else ',' if ',' in header else ';' if ';' in header else None
    if delimiter is None:
        return []
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    fieldnames = [name for name in (reader.fieldnames or []) if name]
    if len(fieldnames) < 2:
        return []
    records = [dict(row) for row in reader if any(value not in (None, '') for value in row.values())]
    return records

def code_symbol_chunks(code: str, max_tokens: int = 900, overlap_tokens: int = 80) -> list[ParsedChunk]:
    """Dependency-free symbol-aware code chunker.

    The production extension point is tree-sitter, but this already chunks by
    symbols for Python/JS/TS/Go/Rust/JVM-ish code and preserves line metadata.
    """
    lines = code.splitlines()
    symbol_re = re.compile(
        r'^\s*(?:'
        r'(?P<py>async\s+def|def|class)\s+(?P<pyname>[A-Za-z_][\w]*)|'
        r'(?P<js>export\s+)?(?:(?:async\s+)?function\s+(?P<jsfn>[A-Za-z_$][\w$]*)|class\s+(?P<jsclass>[A-Za-z_$][\w$]*)|(?:const|let|var)\s+(?P<jsconst>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>)|'
        r'(?P<go>func)\s+(?:\([^)]*\)\s*)?(?P<goname>[A-Za-z_][\w]*)|'
        r'(?P<rust>pub\s+)?(?:async\s+)?(?:fn|struct|enum|trait|impl)\s+(?P<rustname>[A-Za-z_][\w]*)|'
        r'(?P<jvm>public|private|protected|internal|static|final|abstract|sealed|open|override|async|virtual|class|interface|enum)\b.*\b(?P<jvmname>[A-Za-z_][\w]*)\s*(?:\(|\{|:)'
        r')'
    )
    starts: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        m = symbol_re.match(line)
        if not m:
            continue
        name = m.group('pyname') or m.group('jsfn') or m.group('jsclass') or m.group('jsconst') or m.group('goname') or m.group('rustname') or m.group('jvmname') or 'symbol'
        starts.append((idx, name))
    if not starts:
        chunks, ordinal = [], 0
        for part in split_oversized(code, max_tokens=max_tokens, overlap_tokens=overlap_tokens):
            chunks.append(ParsedChunk(ordinal=ordinal, text=part, heading_path=['code'], token_count=estimate_tokens(part), metadata={'chunker': 'code_symbol_chunks', 'symbol_fallback': True, 'text_hash': sha256_text(part)}))
            ordinal += 1
        return chunks
    chunks, ordinal = [], 0
    if starts[0][0] > 0:
        preamble = '\n'.join(lines[:starts[0][0]]).strip()
        if preamble:
            chunks.append(ParsedChunk(ordinal=ordinal, text=preamble, heading_path=['module_preamble'], char_start=0, char_end=len(preamble), token_count=estimate_tokens(preamble), metadata={'chunker': 'code_symbol_chunks', 'symbol': 'module_preamble', 'text_hash': sha256_text(preamble)}))
            ordinal += 1
    for i, (start, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(lines)
        body = '\n'.join(lines[start:end]).strip()
        if not body:
            continue
        for part in split_oversized(body, max_tokens=max_tokens, overlap_tokens=overlap_tokens):
            chunks.append(ParsedChunk(
                ordinal=ordinal,
                text=part,
                heading_path=[name],
                char_start=sum(len(x) + 1 for x in lines[:start]),
                char_end=sum(len(x) + 1 for x in lines[:end]),
                token_count=estimate_tokens(part),
                metadata={'chunker': 'code_symbol_chunks', 'symbol': name, 'line_start': start + 1, 'line_end': end, 'text_hash': sha256_text(part)},
            ))
            ordinal += 1
    return chunks

def structured_record_chunks(content: str, max_records_per_chunk: int = 25) -> list[ParsedChunk]:
    """Object/row-aware chunker for JSON, JSONL, and CSV.

    It converts records to stable text blocks so semantic retrieval can answer
    natural-language questions while sparse filters can still use schema fields.
    """
    records: list[dict[str, Any]] = []
    stripped = content.strip()
    if not stripped:
        return []
    content_type = 'json'
    try:
        obj = json.loads(stripped)
        if isinstance(obj, list):
            records = [r if isinstance(r, dict) else {'value': r} for r in obj]
        elif isinstance(obj, dict):
            if all(isinstance(v, (str, int, float, bool, type(None))) for v in obj.values()):
                records = [obj]
            else:
                for key, value in obj.items():
                    if isinstance(value, list):
                        for item in value:
                            records.append({'_collection': key, **(item if isinstance(item, dict) else {'value': item})})
                    elif isinstance(value, dict):
                        records.append({'_key': key, **value})
                    else:
                        records.append({'_key': key, 'value': value})
        else:
            records = [{'value': obj}]
    except Exception:
        tables = _markdown_table_blocks(content)
        if tables:
            chunks: list[ParsedChunk] = []
            for table_index, table in enumerate(tables, start=1):
                caption = table.get('caption') or f'table_{table_index}'
                prefix = [f'Markdown table {table_index}: {caption}']
                chunks.extend(_record_group_chunks(
                    table['rows'],
                    table['headers'],
                    max_records_per_chunk=max_records_per_chunk,
                    chunker='markdown_table_record_chunks',
                    heading_path=['markdown_table', str(caption)],
                    base_metadata={
                        'content_type': 'markdown_table',
                        'table_index': table_index,
                        'table_caption': table.get('caption'),
                        'table_start_line': table['table_start_line'],
                        'table_end_line': table['table_end_line'],
                    },
                    ordinal_start=len(chunks),
                    prefix_lines=prefix,
                    metadata_factory=lambda start, group, table=table: {
                        'row_start': start + 1,
                        'row_end': start + len(group),
                        'line_start': table['row_start_line'] + start,
                        'line_end': table['row_start_line'] + start + len(group) - 1,
                    },
                ))
            return chunks
        records = _delimited_records(content)
        content_type = 'csv'
    if not records:
        return markdown_heading_chunks(content)
    keys = sorted({k for r in records for k in r.keys()})
    return _record_group_chunks(
        records,
        keys,
        max_records_per_chunk=max_records_per_chunk,
        chunker='structured_record_chunks',
        heading_path=['structured_records'],
        base_metadata={'content_type': content_type},
    )

def _severity_from_text(text: str) -> str | None:
    for token in ('FATAL', 'ERROR', 'WARN', 'INFO', 'DEBUG', 'TRACE'):
        if re.search(rf'\b{token}\b', text):
            return token
    return None

def _fixed_log_window_chunks(lines: list[str], max_lines: int, overlap_lines: int) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []
    ordinal = 0
    start = 0
    ts_re = re.compile(r'(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}|\b(?:ERROR|WARN|INFO|DEBUG|TRACE|FATAL)\b)')
    while start < len(lines):
        end = min(len(lines), start + max_lines)
        block = '\n'.join(lines[start:end]).strip()
        if block:
            sev = _severity_from_text(block)
            chunks.append(ParsedChunk(ordinal=ordinal, text=block, heading_path=['logs', sev or 'events'], token_count=estimate_tokens(block), metadata={'chunker': 'log_event_chunks', 'line_start': start + 1, 'line_end': end, 'severity': sev, 'timestamp_or_level_detected': bool(ts_re.search(block)), 'text_hash': sha256_text(block)}))
            ordinal += 1
        if end == len(lines):
            break
        start = max(end - overlap_lines, start + 1)
    return chunks

def log_event_chunks(content: str, max_lines: int = 80, overlap_lines: int = 10) -> list[ParsedChunk]:
    lines = content.splitlines()
    if not lines:
        return []
    event_start_re = re.compile(r'^\s*(?:\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b|\[(?:ERROR|WARN|INFO|DEBUG|TRACE|FATAL)\]\b|(?:ERROR|WARN|INFO|DEBUG|TRACE|FATAL)\b)')
    starts = [idx for idx, line in enumerate(lines) if event_start_re.search(line)]
    if not starts:
        return _fixed_log_window_chunks(lines, max_lines=max_lines, overlap_lines=overlap_lines)

    events: list[tuple[int, int, str | None]] = []
    for event_idx, start_line in enumerate(starts):
        end_line = starts[event_idx + 1] if event_idx + 1 < len(starts) else len(lines)
        block = '\n'.join(lines[start_line:end_line])
        events.append((start_line, end_line, _severity_from_text(block)))

    chunks: list[ParsedChunk] = []
    ordinal = 0
    event_index = 0
    while event_index < len(events):
        chunk_start_event = event_index
        chunk_end_event = event_index
        line_total = 0
        while chunk_end_event < len(events):
            event_lines = events[chunk_end_event][1] - events[chunk_end_event][0]
            if line_total and line_total + event_lines > max_lines:
                break
            line_total += event_lines
            chunk_end_event += 1
            if event_lines >= max_lines:
                break
        start_line = events[chunk_start_event][0]
        end_line = events[chunk_end_event - 1][1]
        block = '\n'.join(lines[start_line:end_line]).strip()
        if block:
            sev = _severity_from_text(block)
            chunks.append(ParsedChunk(ordinal=ordinal, text=block, heading_path=['logs', sev or 'events'], token_count=estimate_tokens(block), metadata={'chunker': 'log_event_chunks', 'line_start': start_line + 1, 'line_end': end_line, 'event_start': chunk_start_event + 1, 'event_end': chunk_end_event, 'event_count': chunk_end_event - chunk_start_event, 'severity': sev, 'timestamp_or_level_detected': True, 'text_hash': sha256_text(block)}))
            ordinal += 1
        if chunk_end_event >= len(events):
            break
        overlap_start = chunk_end_event
        remaining = overlap_lines
        while overlap_start > chunk_start_event + 1 and remaining > 0:
            overlap_start -= 1
            remaining -= events[overlap_start][1] - events[overlap_start][0]
        event_index = max(overlap_start, chunk_start_event + 1)
    return chunks

def source_page_chunking_profile(mode: str, attributes: dict[str, Any] | None = None) -> str | None:
    """Explicit source-specific override; never changes mode or model selection."""
    if ((attributes or {}).get(SOURCE_PAGE_CHUNKING_PROFILE_ATTRIBUTE) is not None
            and (attributes or {}).get(SOURCE_TEXT_CHUNKING_PROFILE_ATTRIBUTE) is not None):
        raise ValueError('simultaneous page/text chunking profiles are ambiguous')
    value = (attributes or {}).get(SOURCE_PAGE_CHUNKING_PROFILE_ATTRIBUTE)
    if value is None:
        return None
    if value != STATECIVICS_PAGE_MARKDOWN_PROFILE or not isinstance(value, str):
        raise ValueError('unsupported source_page_chunking_profile')
    if mode != 'markdown_docs_v1':
        raise ValueError('source page chunking requires markdown_docs_v1 mode')
    if (attributes or {}).get('source_collection') != 'statecivics-kansas-fiscal-documents':
        raise ValueError('source page chunking requires the StateCivics fiscal source collection')
    return value


def source_text_chunking_profile(mode: str, attributes: dict[str, Any] | None = None) -> str | None:
    source_page_chunking_profile(mode, attributes)
    value = (attributes or {}).get(SOURCE_TEXT_CHUNKING_PROFILE_ATTRIBUTE)
    if value is None:
        return None
    if value != STATECIVICS_STATUTE_MARKDOWN_PROFILE or not isinstance(value, str):
        raise ValueError('unsupported source_text_chunking_profile')
    if mode != 'markdown_docs_v1' or (attributes or {}).get('source_collection') != STATUTE_SOURCE_COLLECTION:
        raise ValueError('statute text chunking requires markdown_docs_v1 and the StateCivics statute source collection')
    return value


def source_coordinate_chunking_profile(mode: str, attributes: dict[str, Any] | None = None) -> str | None:
    return source_text_chunking_profile(mode, attributes) or source_page_chunking_profile(mode, attributes)


def statecivics_page_markdown_chunks(
    md: str, max_tokens: int = 800, overlap_tokens: int = 120, *,
    expected_sha256: str, declared_page_count: int | None = None,
) -> list[ParsedChunk]:
    """Exact source slices, bounded to one declared physical page at a time.

    This preserves extraction coordinates, not canonical legal identities or
    raw-PDF provenance. LF markers are line 1; Unicode codepoint character
    ranges are authoritative when a bounded window splits inside a source line.
    The token budget uses the existing approximate word estimator plus a hard
    4096-character ceiling. Overlap retains original characters, never rejoins
    words. Meaningful pre-marker text remains explicitly unpaginated.
    """
    if not isinstance(md, str) or len(md) > _PAGE_MARKDOWN_MAX_BYTES:
        raise ValueError('page Markdown must be bounded Unicode text (maximum 16 MiB UTF-8)')
    try:
        raw = md.encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise ValueError('page Markdown must be valid UTF-8') from exc
    if len(raw) > _PAGE_MARKDOWN_MAX_BYTES:
        raise ValueError('page Markdown exceeds 16 MiB UTF-8')
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise ValueError('page Markdown requires an exact extraction SHA-256')
    if sha256_text(md) != expected_sha256:
        raise ValueError('page Markdown extraction hash mismatch')
    if '\r' in md or md.count('\n') > 1000000:
        raise ValueError('page Markdown requires LF-only line endings and at most 1000000 lines')
    if (type(max_tokens) is not int or not 16 <= max_tokens <= 2000
            or type(overlap_tokens) is not int or not 0 <= overlap_tokens < max_tokens):
        raise ValueError('page Markdown token bounds require 16..2000 with 0 <= overlap < maximum')
    if declared_page_count is not None and (
        type(declared_page_count) is not int or not 1 <= declared_page_count <= _PAGE_MARKDOWN_MAX_PAGES
    ):
        raise ValueError('declared page count must be an integer in 1..10000')
    markers = []
    for marker in re.finditer(r'^<!-- page ([1-9][0-9]{0,4}) -->\n', md, re.MULTILINE):
        if len(markers) >= _PAGE_MARKDOWN_MAX_PAGES or int(marker.group(1)) != len(markers) + 1:
            raise ValueError('page markers must be unique and contiguous from 1')
        markers.append(marker)
    if not markers or (declared_page_count is not None and len(markers) != declared_page_count):
        raise ValueError('page marker count is missing or differs from declared page count')
    if sum(1 for _ in re.finditer(r'<!--\s*page\b', md, re.IGNORECASE)) != len(markers):
        raise ValueError('malformed or non-line page marker')

    regions = [(None, 0, 0, markers[0].start())]
    regions.extend((index + 1, marker.start(), marker.end(),
                    markers[index + 1].start() if index + 1 < len(markers) else len(md))
                   for index, marker in enumerate(markers))
    chunks: list[ParsedChunk] = []
    max_words = max_tokens * 3 // 4
    overlap_words = overlap_tokens * 3 // 4
    for page, origin, region_start, region_end in regions:
        body = md[region_start:region_end]
        if not body.strip():
            continue
        line_starts = [origin] + [origin + match.end() for match in re.finditer('\n', md[origin:region_end])]
        words = []
        for word in re.finditer(r'\S+', body):
            if len(words) >= _PAGE_MARKDOWN_MAX_REGION_WORDS:
                raise ValueError('page Markdown region exceeds 100000 words')
            words.append(word)
        word_starts = [match.start() for match in words]
        word_ends = [match.end() for match in words]
        paragraph_ends = [match.end() for match in re.finditer(r'\n[ \t]*\n', body)]
        headings = list(re.finditer(r'^(#{1,6})[ \t]+([^\n]+)', body, re.MULTILINE)) if page else []
        boundaries = sorted(set(paragraph_ends + [match.start() for match in headings]))
        start = 0
        while start < len(body):
            first_word = bisect_right(word_ends, start)
            end = min(len(body), start + _PAGE_MARKDOWN_MAX_CHARACTERS)
            if first_word + max_words < len(words):
                end = min(end, word_starts[first_word + max_words])
            next_heading = next((heading.start() for heading in headings if start < heading.start() < end), None)
            if next_heading is not None:
                end = next_heading
            if end < len(body):
                natural = bisect_right(boundaries, end) - 1
                if natural >= 0 and boundaries[natural] >= start + max(1, (end - start) // 2):
                    end = boundaries[natural]
            if end <= start:
                raise ValueError('page Markdown splitter failed to advance')
            text = body[start:end]
            char_start, char_end = region_start + start, region_start + end
            if text.strip():
                if len(chunks) >= _PAGE_MARKDOWN_MAX_CHUNKS:
                    raise ValueError('page Markdown exceeds 20000 chunks')
                heading_path: list[str] = []
                for heading in headings:
                    if heading.start() > start:
                        break
                    level = len(heading.group(1))
                    heading_path = heading_path[:level - 1] + [heading.group(2).strip()]
                metadata = {
                    'chunker': STATECIVICS_PAGE_MARKDOWN_PROFILE,
                    'text_hash': sha256_text(text), 'extraction_content_hash_sha256': expected_sha256,
                    'parsed_page_count': len(markers), 'page_count_basis': 'declared' if declared_page_count is not None else 'parsed_marker_inventory',
                    'char_start': char_start, 'char_end': char_end,
                    'character_coordinate_convention': 'unicode-codepoints-zero-based-end-exclusive-v1',
                    'line_coordinate_convention': 'lf-page-marker-is-line-one-v1' if page else 'lf-document-lines-one-based-inclusive-v1',
                    'line_start': bisect_right(line_starts, char_start),
                    'line_end': bisect_right(line_starts, char_end - 1),
                    'line_range_is_enclosing': True, 'unpaginated_preamble': page is None,
                }
                chunks.append(ParsedChunk(ordinal=len(chunks), text=text, heading_path=heading_path,
                                          page_start=page, page_end=page, char_start=char_start, char_end=char_end,
                                          token_count=estimate_tokens(text), metadata=metadata))
            if end == len(body):
                break
            if any(heading.start() == end for heading in headings):
                start = end
                continue
            last_word = bisect_right(word_starts, end - 1)
            overlap_start = word_starts[max(first_word, last_word - overlap_words)] if overlap_words and last_word else end
            start = max(end - (end - start) // 2, min(end, overlap_start))
    return chunks


def choose_chunker(mode: str, *, attributes: dict[str, Any] | None = None):
    if source_text_chunking_profile(mode, attributes):
        attrs = attributes or {}
        return partial(statecivics_statute_markdown_chunks,
                       expected_sha256=attrs.get('extraction_content_hash_sha256'),
                       expected_source_url=attrs.get('citation_url'))
    if source_page_chunking_profile(mode, attributes):
        attrs = attributes or {}
        return partial(statecivics_page_markdown_chunks,
                       expected_sha256=attrs.get('extraction_content_hash_sha256'),
                       declared_page_count=attrs.get('source_page_count'))
    if mode == 'pdf_markdown_external_v1':
        return pdf_markdown_external_chunks
    if mode == 'code_repo_v1':
        return code_symbol_chunks
    if mode in {'tables_csv_json_v1', 'structured_json_v1'}:
        return structured_record_chunks
    if mode == 'logs_errors_v1':
        return log_event_chunks
    return markdown_heading_chunks
