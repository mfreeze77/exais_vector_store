from __future__ import annotations
import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any
from .hashing import sha256_text

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

def choose_chunker(mode: str):
    if mode == 'pdf_markdown_external_v1':
        return pdf_markdown_external_chunks
    if mode == 'code_repo_v1':
        return code_symbol_chunks
    if mode in {'tables_csv_json_v1', 'structured_json_v1'}:
        return structured_record_chunks
    if mode == 'logs_errors_v1':
        return log_event_chunks
    return markdown_heading_chunks
