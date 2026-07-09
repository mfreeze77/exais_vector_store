from svs_common.chunking import structured_record_chunks, log_event_chunks, choose_chunker


def test_structured_json_chunks_records():
    chunks = structured_record_chunks('[{"id":1,"name":"Alpha"},{"id":2,"name":"Beta"}]', max_records_per_chunk=1)
    assert len(chunks) == 2
    assert 'Schema fields' in chunks[0].text
    assert chunks[0].metadata['record_start'] == 1
    assert chunks[0].metadata['content_type'] == 'json'


def test_structured_csv_chunks_records():
    chunks = structured_record_chunks('id,name\n1,Alpha\n2,Beta', max_records_per_chunk=2)

    assert len(chunks) == 1
    assert 'Record 1: id: 1 | name: Alpha' in chunks[0].text
    assert chunks[0].metadata['content_type'] == 'csv'


def test_markdown_table_chunks_records_with_line_metadata():
    chunks = structured_record_chunks(
        'Panel Schedule\n\n'
        '| Circuit | Load | Breaker |\n'
        '| --- | --- | --- |\n'
        '| 1 | HVAC | 20A |\n'
        '| 2 | Lighting | 15A |\n',
        max_records_per_chunk=1,
    )

    assert len(chunks) == 2
    assert chunks[0].heading_path == ['markdown_table', 'Panel Schedule']
    assert 'Markdown table 1: Panel Schedule' in chunks[0].text
    assert 'Schema fields: Circuit, Load, Breaker' in chunks[0].text
    assert 'Record 1: Circuit: 1 | Load: HVAC | Breaker: 20A' in chunks[0].text
    assert chunks[0].metadata['chunker'] == 'markdown_table_record_chunks'
    assert chunks[0].metadata['content_type'] == 'markdown_table'
    assert chunks[0].metadata['table_start_line'] == 3
    assert chunks[0].metadata['line_start'] == 5
    assert chunks[0].metadata['line_end'] == 5
    assert chunks[1].metadata['row_start'] == 2


def test_log_event_chunks_detects_error():
    chunks = log_event_chunks('2026-01-01T00:00:00 INFO ok\n2026-01-01T00:00:01 ERROR broken')
    assert chunks
    assert chunks[0].metadata['timestamp_or_level_detected'] is True


def test_log_event_chunks_preserve_multiline_stacktrace_events():
    chunks = log_event_chunks(
        '2026-01-01T00:00:00 INFO booted\n'
        '2026-01-01T00:00:01 ERROR failed request\n'
        'Traceback (most recent call last):\n'
        '  File "app.py", line 10, in handler\n'
        'ValueError: broken\n'
        '2026-01-01T00:00:02 INFO recovered\n',
        max_lines=2,
        overlap_lines=0,
    )

    assert [chunk.metadata['event_count'] for chunk in chunks] == [1, 1, 1]
    assert 'Traceback (most recent call last):' in chunks[1].text
    assert 'ValueError: broken' in chunks[1].text
    assert chunks[1].metadata['line_start'] == 2
    assert chunks[1].metadata['line_end'] == 5
    assert chunks[1].metadata['severity'] == 'ERROR'


def test_choose_structured_and_logs():
    assert choose_chunker('tables_csv_json_v1').__name__ == 'structured_record_chunks'
    assert choose_chunker('logs_errors_v1').__name__ == 'log_event_chunks'
