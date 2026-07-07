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
        try:
            reader = csv.DictReader(io.StringIO(content))
            records = [dict(row) for row in reader]
        except Exception:
            records = []
    if not records:
        return markdown_heading_chunks(content)
    keys = sorted({k for r in records for k in r.keys()})
    chunks: list[ParsedChunk] = []
    ordinal = 0
    for start in range(0, len(records), max_records_per_chunk):
        group = records[start:start + max_records_per_chunk]
        lines = [f'Schema fields: {", ".join(keys)}', f'Record range: {start + 1}-{start + len(group)}']
        for idx, record in enumerate(group, start=start + 1):
            items = '; '.join(f'{k}: {record.get(k)}' for k in keys if k in record)
            lines.append(f'Record {idx}: {items}')
        text = '\n'.join(lines)
        chunks.append(ParsedChunk(ordinal=ordinal, text=text, heading_path=['structured_records'], token_count=estimate_tokens(text), metadata={'chunker': 'structured_record_chunks', 'record_start': start + 1, 'record_end': start + len(group), 'schema_fields': keys, 'text_hash': sha256_text(text)}))
        ordinal += 1
    return chunks

def log_event_chunks(content: str, max_lines: int = 80, overlap_lines: int = 10) -> list[ParsedChunk]:
    lines = content.splitlines()
    if not lines:
        return []
    chunks: list[ParsedChunk] = []
    ordinal = 0
    start = 0
    ts_re = re.compile(r'(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}|\b(?:ERROR|WARN|INFO|DEBUG|TRACE|FATAL)\b)')
    while start < len(lines):
        end = min(len(lines), start + max_lines)
        block = '\n'.join(lines[start:end]).strip()
        if block:
            sev = None
            for token in ('FATAL', 'ERROR', 'WARN', 'INFO', 'DEBUG', 'TRACE'):
                if token in block:
                    sev = token
                    break
            chunks.append(ParsedChunk(ordinal=ordinal, text=block, heading_path=['logs', sev or 'events'], token_count=estimate_tokens(block), metadata={'chunker': 'log_event_chunks', 'line_start': start + 1, 'line_end': end, 'severity': sev, 'timestamp_or_level_detected': bool(ts_re.search(block)), 'text_hash': sha256_text(block)}))
            ordinal += 1
        if end == len(lines):
            break
        start = max(end - overlap_lines, start + 1)
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
