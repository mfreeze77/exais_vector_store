#!/usr/bin/env python3
"""Pinned, serial Kansas statute rollout using the existing document consumer.

Dry-run is the default. No provider or API calls occur until every input passes.
Stop with SIGTERM; resume with the identical command and operator directory.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import uuid

from svs_common import chunking, statecivics_statutes

_RUNNER_PATH = Path(__file__).with_name('kansas-fiscal-document-ingest.py')
_spec = importlib.util.spec_from_file_location('statute_rollout_document_consumer', _RUNNER_PATH)
consumer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = consumer
_spec.loader.exec_module(consumer)

INDEX_SHA256 = '65d2424709bb1e54ab7fad9142ceffb6c00f961d463ca78b5dc7c277194f63e0'
HARVEST_SHA256 = '17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2'
SEED_SHA256 = 'b64003f370c161c45c6dc5384951ea787242cba56be6446b12327099755d5c2d'
IMAGE_SHA256 = 'e7271b65b0554f29c5378a0f39a9a2e5e3e4f46fc710138328ef4cf8515627c5'
STORE = 'vs_daafbc5d7aa54b23b3f10392'
CELL = 'ks-fiscal-local'
KB = 'kb_ks_civics'
TENANT = 'ten_ks_state_civics'
BUSINESS = 'biz_ks_state_civics'
PACING_POLICY = {'kind': 'monotonic_serial_upsert_starts_v1', 'max_upserts_per_minute': 110,
                 'minimum_interval_seconds': 0.55, 'stop_poll_seconds': 0.1, 'catch_up': False}
TOTALS = {'tranches': 85, 'records': 31079, 'bytes': 57034050,
          'indexable_documents': 28812, 'chunks': 83258, 'chunk_chars': 62206966}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bounded(path: Path, limit: int) -> bytes:
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'input exceeds byte bound')
    return raw


def load_index(path: Path, expected_sha256: str) -> tuple[dict, list]:
    raw = bounded(path, 1024 * 1024)
    require(sha(raw) == expected_sha256 == INDEX_SHA256, 'unapproved INDEX hash')
    index = json.loads(raw)
    require(all(index.get(k) == v for k, v in {
        'instance_slug': 'ks-state-civics', 'vector_store_slug': 'kansas-statutes',
        'source_family': 'ks_revisor_statutes', 'artifact_type': 'statute',
        'custody_namespace': 'kansas_statutes', 'harvest_manifest_sha256': HARVEST_SHA256,
    }.items()), 'INDEX source scope mismatch')
    require(index.get('totals') == TOTALS, 'INDEX totals mismatch')
    entries = index.get('chapters')
    require(isinstance(entries, list) and len(entries) == TOTALS['tranches'], 'INDEX chapter count mismatch')
    chapters, identities = set(), {k: set() for k in ('logical_document_id', 'source_revision_id', 'export_record_id')}
    manifests = []
    for entry in entries:
        chapter = entry.get('chapter')
        require(isinstance(chapter, str) and re.fullmatch(r'\d{3}[a-z]?', chapter) and chapter not in chapters, 'duplicate or invalid chapter')
        chapters.add(chapter)
        require(entry.get('file') == f'ksa-ch{chapter}.jsonl', 'invalid chapter path')
        source = (path.parent / entry['file']).resolve()
        require(source.parent == path.parent.resolve(), 'chapter path escapes INDEX directory')
        raw = bounded(source, 32 * 1024 * 1024)
        require(sha(raw) == entry.get('sha256') and len(raw) == entry.get('bytes'), 'chapter hash/size mismatch')
        manifest = consumer.load_manifest(source, vector_store_slug='kansas-statutes', source_family='kansas-statutes')
        require(manifest.sha256 == sha(raw) and len(manifest.records) == entry.get('records'), 'chapter changed or count mismatch')
        for record in manifest.records:
            for key, seen in identities.items():
                require(record[key] not in seen, f'duplicate global {key}')
                seen.add(record[key])
            match = re.fullmatch(r'https://ksrevisor\.gov/statutes/chapters/ch(\d{2}[a-z]?)/\d{3}[a-z]?_\d{3}[a-z]?_\d{4}[a-z]?\.html', record['citation_url'])
            require(match is not None and match[1].lstrip('0') == chapter.lstrip('0'), 'record belongs to a different chapter')
            require(record['custody_uri'].startswith('civic-custody://kansas_statutes/'), 'wrong custody namespace')
            require(record['ingestion']['action'] == 'upsert', 'this pinned rollout contains no legal withdrawal records')
        manifests.append((entry, manifest))
    for key in TOTALS:
        if key != 'tranches':
            require(sum(e[key] for e, _ in manifests) == TOTALS[key], f'chapter total mismatch: {key}')
    return index, sorted(manifests, key=lambda item: item[0]['chapter'])


def partition_seed(seed_path: Path, expected_sha256: str, manifests: list) -> dict[str, dict]:
    raw = bounded(seed_path, 1024 * 1024)
    require(sha(raw) == expected_sha256 == SEED_SHA256, 'unapproved seed hash')
    seed = consumer.load_state(seed_path, vector_store_id=STORE)
    require(sha(bounded(seed_path, 1024 * 1024)) == expected_sha256, 'seed changed during preparation')
    require(len(seed['records']) == 20, 'seed must preserve the WAVE-139 twenty records')
    owners = {r['logical_document_id']: entry['chapter'] for entry, m in manifests for r in m.records}
    require(set(seed['records']) <= owners.keys(), 'seed identity absent from approved exports')
    states = {entry['chapter']: {'schema_version': 1, 'vector_store_id': STORE, 'records': {}} for entry, _ in manifests}
    for identity, value in seed['records'].items():
        require(isinstance(value, dict) and value.get('action') in ('upsert', 'remove'), 'invalid seed record')
        states[owners[identity]]['records'][identity] = copy.deepcopy(value)
    return states


def code_pins() -> dict[str, str]:
    files = {'coordinator': Path(__file__), 'document_consumer': _RUNNER_PATH,
             'pipeline_common': _RUNNER_PATH.with_name('topeka_pipeline_common.py'),
             'statute_parser': Path(statecivics_statutes.__file__), 'chunker': Path(chunking.__file__)}
    return {key: sha(path.read_bytes()) for key, path in files.items()}


def chapter_state(root: Path, chapter: str, seed: dict, manifest) -> dict:
    path = root / 'states' / f'ch{chapter}.json'
    if not path.exists():
        return copy.deepcopy(seed)
    require(path.resolve().is_relative_to(root.resolve()), 'chapter state escapes operator directory')
    state = consumer.load_state(path, vector_store_id=STORE)
    allowed = {r['logical_document_id'] for r in manifest.records}
    require(set(state['records']) <= allowed and seed['records'].keys() <= state['records'].keys(), 'chapter state identity mismatch')
    return state


@dataclass
class Prepared:
    manifests: list
    harvest: statecivics_statutes.StatuteHarvest
    seeds: dict
    pins: dict
    plan: dict


def prepare(args) -> Prepared:
    require(args.api in ('http://api:8080', 'http://127.0.0.1:28085'), 'unapproved API target')
    require(args.harvest_manifest_sha256 == HARVEST_SHA256, 'unapproved harvest hash')
    _, manifests = load_index(args.index, args.index_sha256)
    seeds = partition_seed(args.seed_state, args.seed_state_sha256, manifests)
    pins = {'schema_version': 1, 'index_sha256': args.index_sha256,
            'harvest_sha256': args.harvest_manifest_sha256, 'seed_sha256': args.seed_state_sha256,
            'api': args.api, 'cell': CELL, 'vector_store_id': STORE, 'knowledge_base_id': KB,
            'tenant_id': TENANT, 'business_instance_id': BUSINESS, 'pacing_policy': dict(PACING_POLICY),
            'required_runtime_image_sha256': IMAGE_SHA256, 'consumer_files': code_pins(),
            'chapters': {e['chapter']: m.sha256 for e, m in manifests}}
    pin_path = args.operator_root / 'inputs.lock.json'
    if pin_path.exists():
        require(json.loads(pin_path.read_text()) == pins, 'resume input/consumer/target pins changed')
    harvest = statecivics_statutes.preflight_statute_harvest(args.harvest_manifest, args.harvest_root,
                                                         expected_manifest_sha256=args.harvest_manifest_sha256)
    plan = {'status': 'preflight_pass', 'api_calls': 0, 'bulk_applied': False, 'pins': pins,
            'chapters': [], 'planned': {'upsert': 0, 'noop': 0, 'remove': 0}}
    for entry, manifest in manifests:
        chapter = entry['chapter']
        state = chapter_state(args.operator_root, chapter, seeds[chapter], manifest)
        operations = consumer.plan_operations(manifest, custody_root=args.custody_root, state=state,
                                             source_family='kansas-statutes', statute_harvest=harvest)
        counts = {'indexable_documents': 0, 'chunks': 0, 'chunk_chars': 0}
        for record in manifest.records:
            raw = consumer.read_custody_object(args.custody_root, record, max_bytes=statecivics_statutes.MAX_DOCUMENT_BYTES)
            evidence = consumer._statute_evidence(record, raw, harvest)
            chunks = statecivics_statutes.statecivics_statute_markdown_chunks(raw.decode('utf-8'), expected_sha256=record['content_hash_sha256'])
            counts['indexable_documents'] += int(evidence['classification'] == 'substantive_body')
            counts['chunks'] += len(chunks)
            counts['chunk_chars'] += sum(len(c.text) for c in chunks)
        require(all(counts[k] == entry[k] for k in counts), 'retained chapter classification/chunk counts differ from INDEX')
        actions = {a: sum(o.action == a for o in operations) for a in plan['planned']}
        require(actions['remove'] == 0, 'unexpected indexed exclusion/removal; inspect before rollout')
        for action, count in actions.items():
            plan['planned'][action] += count
        plan['chapters'].append({'chapter': chapter, **counts, 'records': len(manifest.records), 'planned': actions})
    return Prepared(manifests, harvest, seeds, pins, plan)


@contextmanager
def exclusive_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'rollout.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another rollout writer holds the lock') from exc
        yield


def validate_output_paths(args) -> None:
    root = args.operator_root.resolve()
    for directory in (args.index.parent, args.harvest_root, args.custody_root):
        directory = directory.resolve()
        require(not root.is_relative_to(directory) and not directory.is_relative_to(root), 'operator output overlaps retained input')
    require(not args.seed_state.resolve().is_relative_to(root), 'seed must remain outside rollout output')
    require(not any((p / '.git').exists() for p in (root, *root.parents)), 'operator output must be outside every checkout')
    for child in ('states', 'attempts', 'rollout.lock', 'inputs.lock.json', 'progress.json'):
        require((root / child).resolve().is_relative_to(root), 'operator output symlink escapes root')


class UpsertPacer:
    """Space serial upsert starts; elapsed slow work never earns burst credits."""
    def __init__(self, *, clock=None, sleep=None):
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.next_start: float | None = None

    def wait(self, stop_requested) -> None:
        while True:
            if stop_requested():
                raise InterruptedError('stop requested while pacing')
            current = self.clock()
            remaining = 0 if self.next_start is None else self.next_start - current
            if remaining <= 0:
                # Anchor to actual admission time, never an overdue schedule.
                self.next_start = current + PACING_POLICY['minimum_interval_seconds']
                return
            self.sleep(min(remaining, PACING_POLICY['stop_poll_seconds']))


def apply_prepared(args, prepared: Prepared, stop_requested=lambda: False) -> dict:
    headers = consumer.default_headers(cell=CELL)
    require(headers.get('X-SVS-Tenant-Id') == TENANT and headers.get('X-SVS-Business-Instance-Id') == BUSINESS, 'caller scope is not the approved Kansas cell')
    consumer.ensure_vector_store(api_base=args.api, headers=headers, vector_store_id=STORE,
        vector_store_name='Kansas Statutes', knowledge_base_id=KB, allow_create=False,
        timeout=args.api_timeout_seconds, cell=CELL, transport='auto')
    pin_path = args.operator_root / 'inputs.lock.json'
    if not pin_path.exists():
        consumer.write_json_atomic(pin_path, prepared.pins)
    attempt = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    progress = {'status': 'running', 'attempt': attempt, 'started_at': now(),
                'chapter': None, 'logical_document_id': None, 'completed_chapters': [],
                'processed_this_attempt': 0, 'pacing_policy': dict(PACING_POLICY), 'results': {'upserted': 0, 'removed': 0, 'unchanged': 0}}
    def checkpoint():
        progress['updated_at'] = now()
        consumer.write_json_atomic(args.operator_root / 'attempts' / f'{attempt}.json', progress)
        consumer.write_json_atomic(args.operator_root / 'progress.json', progress)
    pacer = UpsertPacer()
    try:
        checkpoint()
        for entry, manifest in prepared.manifests:
            chapter = entry['chapter']; progress['chapter'] = chapter
            state = chapter_state(args.operator_root, chapter, prepared.seeds[chapter], manifest)
            state_path = args.operator_root / 'states' / f'ch{chapter}.json'
            if not state_path.exists():
                consumer.write_json_atomic(state_path, state)
            operations = consumer.plan_operations(manifest, custody_root=args.custody_root, state=state,
                source_family='kansas-statutes', statute_harvest=prepared.harvest)
            for operation in operations:
                progress['logical_document_id'] = operation.logical_document_id
                if stop_requested():
                    raise InterruptedError('stop requested')
                require(operation.action != 'remove', 'unexpected removal')
                if operation.action == 'upsert':
                    pacer.wait(stop_requested)
                if stop_requested():
                    raise InterruptedError('stop requested before operation')
                result = consumer.apply_operations([operation], state=state, state_path=state_path,
                    api_base=args.api, headers=headers, vector_store_id=STORE, knowledge_base_id=KB,
                    timeout=args.api_timeout_seconds, cell=CELL, transport='auto')
                progress['processed_this_attempt'] += 1
                for key, count in result.items():
                    progress['results'][key] += count
                checkpoint()
            progress['completed_chapters'].append(chapter)
            checkpoint()
        progress.update(status='completed', chapter=None, logical_document_id=None)
        checkpoint()
        return progress
    except BaseException as exc:
        progress['status'] = 'stopped' if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 'failed'
        progress['error_type'] = type(exc).__name__  # Never persist API bodies, credentials, or source text.
        checkpoint()
        raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('index', 'harvest-manifest', 'harvest-root', 'custody-root', 'seed-state', 'operator-root'):
        parser.add_argument('--' + flag, required=True, type=Path)
    for flag in ('index-sha256', 'harvest-manifest-sha256', 'seed-state-sha256'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--api', required=True)
    parser.add_argument('--api-timeout-seconds', type=int, default=1800)
    parser.add_argument('--apply', action='store_true')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        require(1 <= args.api_timeout_seconds <= 1800, 'timeout outside approved bound')
        validate_output_paths(args)
        with exclusive_lock(args.operator_root):
            prepared = prepare(args)
            plan_path = args.operator_root / ('plan-' + uuid.uuid4().hex + '.json')
            consumer.write_json_atomic(plan_path, prepared.plan)
            if stopped:
                raise InterruptedError('stopped during preflight; no API effects')
            if args.apply:
                result = apply_prepared(args, prepared, lambda: stopped)
                print(json.dumps(result, sort_keys=True))
            else:
                print(json.dumps({'status': 'plan_only', 'plan': str(plan_path), 'planned': prepared.plan['planned'], 'api_calls': 0}, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'status': 'stopped' if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 'failed',
                          'error_type': type(exc).__name__, 'message': 'Rollout stopped; inspect durable progress. No automatic retry.'}), file=sys.stderr)
        return 130 if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 2


if __name__ == '__main__':
    raise SystemExit(main())
