"""Authenticated API storage for candidate entity descriptors and their records.

The record remains a candidate. Money and citations are read from its structured
payload; only the producer's compact description is embedded.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import httpx
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from .config import get_settings
from .ids import point_uuid
from .model_registry import model_registry
from .qdrant_adapter import QdrantAdapter
from .statecivics_contract_pin import load_contract
from .statecivics_record_adapter import (
    adapt_records, admit_entity_records, resolve_staging_collection,
    stage_entity_descriptors,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / 'configs' / 'statecivics-contracts'
PAYLOAD_SCHEMAS = {
    'appropriation_action': 'appropriation-action.schema.json',
    'provision_reference': 'provision-reference.schema.json',
}


class CandidateStorageError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest_record(record: dict) -> str:
    copy = json.loads(canonical(record))
    copy.pop('record_digest_sha256', None)
    copy['exporter'].pop('exported_at', None)
    return hashlib.sha256(canonical(copy).encode()).hexdigest()


def validate_candidate_manifest(body: str, expected_sha256: str, *, path: str) -> tuple[dict, ...]:
    """Verify bytes, pins, complete payloads and eligibility before any service I/O."""
    if not body.endswith('\n') or hashlib.sha256(body.encode()).hexdigest() != expected_sha256:
        raise CandidateStorageError('manifest bytes do not match the declared SHA-256 or trailing newline')
    provenance = json.loads((CONTRACTS / 'provenance.json').read_text())
    for name, expected in provenance['files'].items():
        if hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest() != expected:
            raise CandidateStorageError(f'local source contract hash mismatch: {name}')
    schema = load_contract(CONTRACTS / 'retrieval-export-record.schema.json')
    try:
        lines = [(i, json.loads(line)) for i, line in enumerate(body.splitlines(), 1) if line.strip()]
    except ValueError as exc:
        raise CandidateStorageError('manifest is not valid JSONL') from exc
    adapted = adapt_records(lines, schema)
    if adapted.document_records or not adapted.entity_records:
        raise CandidateStorageError('candidate storage requires a nonempty entity-only manifest')
    records = admit_entity_records(adapted.entity_records, path=path)
    if path != 'candidate':
        raise CandidateStorageError('this storage API supports only the candidate path')
    checker = FormatChecker()
    if not {'date', 'date-time', 'uri'} <= set(checker.checkers):
        raise CandidateStorageError('required JSON Schema format checkers are unavailable')
    identities = set()
    for record in records:
        identity = (record['entity_type'], record['entity_logical_id'])
        if identity in identities:
            raise CandidateStorageError('manifest repeats an entity identity')
        identities.add(identity)
        if record.get('record_digest_algorithm') != 'statecivics-canonical-json-v1' or digest_record(record) != record['record_digest_sha256']:
            raise CandidateStorageError('record digest does not match its fields')
        payload_schema = json.loads((CONTRACTS / PAYLOAD_SCHEMAS[record['entity_type']]).read_text())
        errors = list(Draft202012Validator(payload_schema, format_checker=checker).iter_errors(record['entity']))
        if errors:
            raise CandidateStorageError('entity payload invalid: ' + '; '.join(e.message for e in errors))
        if record['ingestion']['mode'] != 'api_only':
            raise CandidateStorageError('entity ingestion requires api_only')
    return records


class CandidateEntityStore:
    def __init__(self, *, settings=None, adapter=None, embed=None):
        self.settings = settings or get_settings()
        self.policy = yaml.safe_load((ROOT / 'configs' / 'statecivics-candidates.yaml').read_text())
        self.adapter = adapter or QdrantAdapter()
        if not self.adapter.settings.svs_index_strict:
            raise CandidateStorageError('candidate storage requires strict index errors')
        self.registry = model_registry()
        self.profile_id = self.policy['embedding_profile']
        self.profile = self.registry['models'][self.profile_id]
        if self.profile['provider'] == 'hash_mock':
            raise CandidateStorageError('candidate retrieval requires a real embedding provider')
        self.dimensions = int(self.profile['dimensions'])
        self.embed = embed or self._embed

    def authorize(self, principal):
        if (principal.tenant_id, principal.business_instance_id) != (
            self.policy['tenant_id'], self.policy['business_instance_id']
        ):
            raise CandidateStorageError('candidate instance does not match the authenticated principal')

    def routing(self) -> dict:
        # Document ingestion calls embedding_profile_config, which refuses any
        # profile absent from this same runtime registry. Enumerating ALL keys
        # is a conservative bound including routing aliases and fallback models;
        # it does not guess which one an undeclared source happened to use.
        return {
            'path': 'candidate',
            'instance_root': ROOT / 'instances' / self.policy['instance_slug'],
            'entity_embedding_profile_id': self.policy['live_index_profile'],
            'candidate_embedding_profile_id': self.policy['candidate_index_profile'],
            'document_profile_catalog': tuple(sorted(self.registry['models'])),
        }

    def _embed(self, text: str, input_type='document') -> list[float]:
        response = httpx.post(
            self.settings.model_gateway_url.rstrip('/') + '/internal/models/embeddings',
            json={'input': [text], 'model_profile_id': self.profile_id,
                  'provider': self.profile['provider'], 'model': self.profile['model'],
                  'dimensions': self.dimensions, 'input_type': input_type, 'security_level': 1},
            timeout=120,
        )
        response.raise_for_status()
        value = response.json()
        if (value.get('provider'), value.get('model'), value.get('dimensions')) != (
            self.profile['provider'], self.profile['model'], self.dimensions
        ) or len(value.get('data', [])) != 1:
            raise CandidateStorageError('embedding response does not match the configured real model')
        vector = value['data'][0]['embedding']
        if len(vector) != self.dimensions or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector) or not any(vector):
            raise CandidateStorageError('embedding response has an invalid vector')
        return vector

    def point_id(self, record):
        return point_uuid(canonical([
            'statecivics-candidate', self.policy['tenant_id'], self.policy['business_instance_id'],
            record['entity_type'], record['entity_logical_id'],
        ]))

    def ingest(self, records, *, principal, manifest_sha256: str, apply: bool):
        self.authorize(principal)
        records = admit_entity_records(records, path='candidate')
        for record in records:
            if record['ingestion'].get('target_instance_slug') not in (None, self.policy['instance_slug']):
                raise CandidateStorageError('manifest target instance differs from the API instance')
        collection = resolve_staging_collection(self.adapter, **self.routing())
        result = {'applied': False, 'entity_path': 'candidate', 'collection': collection,
                  'manifest_sha256': manifest_sha256, 'record_count': len(records),
                  'embedded': 0, 'written': 0, 'unchanged': 0, 'point_ids': [self.point_id(r) for r in records]}
        if not apply:
            return result
        client = self.adapter.client
        if client is None:
            raise CandidateStorageError('candidate index client is unavailable')
        names = {c.name for c in client.get_collections().collections}
        existing = {} if collection not in names else {
            str(p.id): p.payload for p in client.retrieve(collection_name=collection, ids=result['point_ids'], with_payload=True)
        }
        changed = []
        for record in records:
            previous = existing.get(self.point_id(record))
            if previous:
                old = previous['entity_record']
                if old['entity_revision'] > record['entity_revision']:
                    raise CandidateStorageError('refusing a revision older than the stored candidate')
                if old['entity_revision'] == record['entity_revision'] and old['entity'] != record['entity']:
                    raise CandidateStorageError('the same entity revision has contradictory payloads')
                if old['record_digest_sha256'] == record['record_digest_sha256']:
                    result['unchanged'] += 1
                    continue
            changed.append(record)

        def write(resolved, pairs):
            if not pairs:
                return
            from qdrant_client.http.models import PointStruct
            self.adapter.ensure_collection(resolved, self.dimensions)
            points = [PointStruct(id=self.point_id(record), vector=vector, payload={
                'tenant_id': principal.tenant_id, 'business_instance_id': principal.business_instance_id,
                'entity_path': 'candidate', 'manifest_sha256': manifest_sha256,
                'embedding_profile': self.profile_id, 'entity_record': record,
            }) for record, vector in pairs]
            client.upsert(collection_name=resolved, points=points, wait=True)
            # A successful request alone is insufficient: read back every full
            # record and compare it with the exact submitted artifact.
            readback = {str(p.id): p.payload for p in client.retrieve(
                collection_name=resolved, ids=[p.id for p in points], with_payload=True
            )}
            if any(readback.get(str(p.id)) != p.payload for p in points):
                raise CandidateStorageError('candidate index readback differs from the submitted records')

        staged = stage_entity_descriptors(
            changed, adapter=self.adapter, embed=self.embed, index_write=write, **self.routing()
        )
        result.update(applied=True, embedded=staged.embedded, written=len(changed))
        return result

    def search(self, query: str, *, principal, limit: int = 5):
        self.authorize(principal)
        collection = resolve_staging_collection(self.adapter, **self.routing())
        if self.adapter.client is None:
            raise CandidateStorageError('candidate index client is unavailable')
        if collection not in {c.name for c in self.adapter.client.get_collections().collections}:
            return {'entity_path': 'candidate', 'collection': collection, 'results': []}
        vector = self.embed(query, input_type='query')
        hits = self.adapter.search(collection, vector, {'must': [
            {'key': 'tenant_id', 'match': {'value': principal.tenant_id}},
            {'key': 'business_instance_id', 'match': {'value': principal.business_instance_id}},
            {'key': 'entity_path', 'match': {'value': 'candidate'}},
        ]}, limit=limit)
        return {'entity_path': 'candidate', 'collection': collection, 'results': [
            {'point_id': str(hit['id']), 'score': hit['score'], 'record': hit['payload']['entity_record']}
            for hit in hits
        ]}
