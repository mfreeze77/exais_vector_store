"""The operator handles full manifests without exceeding the candidate API limit."""
import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def command(monkeypatch):
    release=ROOT/'scripts/release'
    monkeypatch.syspath_prepend(str(release))
    spec=importlib.util.spec_from_file_location('bulk_candidate_command',release/'kansas-fiscal-document-ingest.py')
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,'default_headers',lambda **kw:{})
    return module


def make_case(command,tmp_path,ending='\n'):
    original=gzip.decompress((ROOT/'tests/fixtures/statecivics-hb2513-bulk-durable.c49d7105.jsonl.gz').read_bytes())
    assert hashlib.sha256(original).hexdigest()=='5155056a4b2d411896787ff6e681d90a8cd58655cf3ddf6805849ca9dccc791b'
    # Real distinct records exercise payload validation and global duplicate checks.
    raw=(ending.join(original.decode().splitlines()[:101])+ending).encode()
    path=tmp_path/'manifest.jsonl';path.write_bytes(raw)
    loaded=command.load_entity_manifest(path,contract_schema=ROOT/'configs/statecivics-contracts/retrieval-export-record.schema.json',entity_path='candidate')
    args=SimpleNamespace(api='http://test',cell='ks-fiscal-local',auth_token_file=None,api_timeout_seconds=600,api_transport='direct',proof=tmp_path/'proof.json')
    return raw,loaded,args


def answer(payload):
    records=[json.loads(l) for l in payload['manifest'].splitlines() if l.strip()]
    assert hashlib.sha256(payload['manifest'].encode()).hexdigest()==payload['manifest_sha256']
    return dict(applied=True,manifest_sha256=payload['manifest_sha256'],record_count=len(records),collection='candidate-test',embedded=0,written=0,unchanged=len(records),point_ids=[r['export_record_id'] for r in records])


@pytest.mark.parametrize('ending',['\n','\r\n'])
def test_batches_preserve_exact_bytes_and_aggregate_all_confirmed_records(command,tmp_path,monkeypatch,ending):
    raw,loaded,args=make_case(command,tmp_path,ending)
    calls=[]
    def api(method,base,path,payload,**kw):
        calls.append(payload['manifest'].encode())
        assert len(calls[-1])<=1_500_000
        return answer(payload)
    monkeypatch.setattr(command,'api_json',api)
    result=command.apply_entity_manifest(loaded,args)
    assert b''.join(calls)==raw
    assert len(calls)==2
    assert result['applied'] and result['completed_batches']==2
    assert result['record_count']==result['unchanged']==101
    assert result['embedded']==result['written']==0
    assert result['manifest_sha256']==hashlib.sha256(raw).hexdigest()


def test_later_failure_leaves_an_explicit_partial_receipt(command,tmp_path,monkeypatch):
    _,loaded,args=make_case(command,tmp_path)
    calls=[]
    def api(method,base,path,payload,**kw):
        calls.append(payload)
        if len(calls)==2:raise RuntimeError('second request failed')
        return answer(payload)
    monkeypatch.setattr(command,'api_json',api)
    with pytest.raises(RuntimeError,match='second request failed'):command.apply_entity_manifest(loaded,args)
    proof=json.loads(args.proof.read_text())
    assert proof['completed_batches']==1 and not proof['applied']
    assert proof['unchanged']==100


def test_changed_file_refuses_before_any_request(command,tmp_path,monkeypatch):
    _,loaded,args=make_case(command,tmp_path)
    loaded.path.write_bytes(b'changed')
    def forbidden(*a,**kw):raise AssertionError('API called before change refusal')
    monkeypatch.setattr(command,'api_json',forbidden)
    with pytest.raises(command.FiscalIngestError,match='changed after admission'):command.apply_entity_manifest(loaded,args)
