from svs_common.chunking import structured_record_chunks, log_event_chunks, choose_chunker


def test_structured_json_chunks_records():
    chunks = structured_record_chunks('[{"id":1,"name":"Alpha"},{"id":2,"name":"Beta"}]', max_records_per_chunk=1)
    assert len(chunks) == 2
    assert 'Schema fields' in chunks[0].text
    assert chunks[0].metadata['record_start'] == 1


def test_log_event_chunks_detects_error():
    chunks = log_event_chunks('2026-01-01T00:00:00 INFO ok\n2026-01-01T00:00:01 ERROR broken')
    assert chunks
    assert chunks[0].metadata['timestamp_or_level_detected'] is True


def test_choose_structured_and_logs():
    assert choose_chunker('tables_csv_json_v1').__name__ == 'structured_record_chunks'
    assert choose_chunker('logs_errors_v1').__name__ == 'log_event_chunks'
