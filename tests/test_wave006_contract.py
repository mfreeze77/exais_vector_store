from __future__ import annotations
import inspect

from svs_common.ingestion import IngestionService


def test_dedupe_requires_fully_indexed_current_version():
    source = inspect.getsource(IngestionService._find_exact_duplicate)
    assert "dv.status='indexed'" in source
    assert "c.dense_index_status='indexed'" in source
    assert "c.sparse_index_status='indexed'" in source
    assert "NOT EXISTS" in source


def test_worker_wraps_job_attempt_in_savepoint():
    from svs_worker import main as worker_main
    source = inspect.getsource(worker_main.process_once)
    assert "with db.begin_nested()" in source
    assert "preserving attempts" in source
