from __future__ import annotations
import json
from svs_common.db import jsonb_param
from svs_common.sql import jsonb_text


def test_jsonb_param_serializes_for_explicit_casts():
    payload = {'b': 2, 'a': {'nested': True}}
    encoded = jsonb_param(payload)
    assert isinstance(encoded, str)
    assert json.loads(encoded) == payload
    assert encoded.startswith('{') and encoded.endswith('}')


def test_jsonb_text_keeps_cast_based_sql_contract():
    stmt = jsonb_text('INSERT INTO ingestion_jobs(payload) VALUES (CAST(:payload AS jsonb))', 'payload')
    assert 'CAST(:payload AS jsonb)' in str(stmt)
