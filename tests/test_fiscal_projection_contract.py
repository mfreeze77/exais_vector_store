"""Synthetic adversarial mechanics for the WAVE-133 offline foundation.

Shape design comes from FISCAL_GRAPH_REAL_DATA.md's retained KanView CSV audit:
record != physical line, no supplied subunit, shared bytes != canonical identity.
These fabricated IDs/hashes are NOT reviewed Kansas facts or product acceptance.
Real retained-byte proof lives separately in test_fiscal_real_corpus.py and the
structured evidence verifier tests. No provider, upstream DB or runtime call.
"""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from svs_common.fiscal_graph import (
    fiscal_projection_content_hash,
    fiscal_projection_edge_id,
    fiscal_projection_node_id,
    validate_fiscal_partition_replay,
    validate_fiscal_projection_manifest,
)
from svs_common.schemas import (
    ContextCitation,
    FiscalCanonicalReference,
    FiscalDocumentSpanEvidence,
    FiscalEntityResult,
    FiscalEvidenceCitation,
    FiscalProjectionBatch,
    FiscalProjectionCounts,
    FiscalProjectionManifest,
    FiscalProjectionNode,
    FiscalProjectionPartition,
    FiscalProjectionScope,
    FiscalStructuredRecordEvidence,
    FiscalStructuredRecordLocator,
)


SCOPE = FiscalProjectionScope(tenant_id='fixture-tenant', business_instance_id='fixture-cell',
                              vector_store_id='vs_fixture_fiscal')
ZERO = '0' * 64


def reference(name='account-a', revision='supplied-revision-1', kind='budget_account'):
    return FiscalCanonicalReference(type=kind, id=name, revision_or_hash=revision)


def structured(record=384, revision='source-revision-2026'):
    return {
        'evidence_kind': 'structured_record', 'source_revision_id': revision,
        'source_content_hash_sha256': 'a' * 64,
        'locator': {'kind': 'csv_record', 'data_record_1based': record, 'header_records': 1,
                    'selected_columns': ['Business Unit', 'Budget Ref']},
        'raw_record_sha256': 'b' * 64,
    }


def document():
    return {
        'evidence_kind': 'document_span', 'source_revision_id': 'source-law-edition-2025',
        'source_content_hash_sha256': 'c' * 64, 'source_span_id': 'source-span-96-j',
        'span_type': 'text', 'locator_json': '{"section":"96(j)","text_start":100,"text_end":180}',
        'content_hash_sha256': 'd' * 64,
    }


def node(name='account-a', *, evidence=None, scope=SCOPE, revision='supplied-revision-1'):
    ref = reference(name, revision)
    return {
        'projection_id': fiscal_projection_node_id(scope, ref),
        'canonical_reference': ref.model_dump(), 'description': 'Source-supplied account label',
        'structured_fields_json': '{"fiscal_year":2026,"subunit":null,"effective_date":null}',
        'evidence': [evidence or structured()],
    }


def edge(source, target, *, name='assertion-a', evidence=None):
    ref = reference(name, kind='relationship')
    return {
        'projection_id': fiscal_projection_edge_id(SCOPE, ref), 'canonical_reference': ref.model_dump(),
        'relationship_type': 'supplied_relationship_type',
        'source_node_id': source['projection_id'], 'target_node_id': target['projection_id'],
        'context_json': '{"review_status":"unknown"}', 'evidence': [evidence or structured()],
    }


def batch(partition_id='partition-a', *, nodes=None, edges=None, scope=SCOPE):
    nodes = [node()] if nodes is None else nodes
    edges = [] if edges is None else edges
    value = FiscalProjectionBatch(
        scope=scope, partition_id=partition_id, content_hash=ZERO,
        expected_counts=FiscalProjectionCounts(nodes=len(nodes), edges=len(edges),
                                               descriptions=sum(n.get('description') is not None for n in nodes)),
        nodes=nodes, edges=edges,
    )
    return value.model_copy(update={'content_hash': fiscal_projection_content_hash(value)})


def descriptor(value):
    return FiscalProjectionPartition(partition_id=value.partition_id, content_hash=value.content_hash,
                                     expected_counts=value.expected_counts)


def manifest(batches, *, scope=SCOPE, manifest_id='manifest-a'):
    value = FiscalProjectionManifest(
        manifest_id=manifest_id, scope=scope,
        snapshot_reference=reference('snapshot-a', kind='intelligence_snapshot'),
        source_revision_set_hash_sha256='e' * 64, partitions=[descriptor(b) for b in batches],
        total_expected_counts=FiscalProjectionCounts(
            **{k: sum(getattr(b.expected_counts, k) for b in batches) for k in ('nodes', 'edges', 'descriptions')}),
        content_hash=ZERO,
    )
    return value.model_copy(update={'content_hash': fiscal_projection_content_hash(value)})


def validate(batches, *, value=None, retained=()):
    return validate_fiscal_projection_manifest(value or manifest(batches), iter(batches),
                                               expected_scope=SCOPE, retained_partitions=retained)


def rehash_manifest(value):
    return value.model_copy(update={'content_hash': fiscal_projection_content_hash(value)})


def test_structured_evidence_has_no_file_chunk_or_invented_subunit():
    value = FiscalProjectionNode.model_validate(node())
    citation = FiscalEvidenceCitation(canonical_reference=value.canonical_reference, evidence=value.evidence[0])
    assert isinstance(citation.evidence, FiscalStructuredRecordEvidence)
    assert citation.evidence.locator.data_record_1based == 384
    assert not hasattr(citation.evidence, 'document_id') and not hasattr(citation.evidence, 'chunk_id')
    assert json.loads(value.structured_fields_json)['subunit'] is None
    assert json.loads(value.structured_fields_json)['effective_date'] is None
    assert citation.evidence.extraction_revision_id is None
    result = validate([batch()])
    assert result['validation_kind'] == 'offline_structure_only'
    assert result['publication_eligibility'] == 'not_checked'
    assert result['source_coverage'] == 'not_checked'
    assert result['canonical_relationship_semantics'] == 'not_checked'


@pytest.mark.parametrize('field', ['document_id', 'chunk_id', 'page', 'source_span_id'])
def test_structured_evidence_refuses_fabricated_document_binding_fields(field):
    value = structured(); value[field] = 'invented'
    with pytest.raises(ValidationError):
        FiscalStructuredRecordEvidence.model_validate(value)


def test_document_evidence_preserves_exact_upstream_locator_without_requiring_page():
    value = FiscalDocumentSpanEvidence.model_validate(document())
    assert json.loads(value.locator_json)['section'] == '96(j)'
    assert value.document_id is None and value.chunk_id is None
    bound = FiscalDocumentSpanEvidence.model_validate({**document(), 'document_id': 'doc-a', 'chunk_id': 'chunk-a'})
    assert bound.chunk_id == 'chunk-a'
    with pytest.raises(ValidationError, match='requires its document'):
        FiscalDocumentSpanEvidence.model_validate({**document(), 'chunk_id': 'chunk-a'})
    with pytest.raises(ValidationError, match='nonempty exact locator'):
        FiscalDocumentSpanEvidence.model_validate({**document(), 'locator_json': '{}'})
    # This existing response type keeps its historical required file identities.
    assert ContextCitation(chunk_id='old-chunk', document_id='old-document').document_id == 'old-document'


def test_canonical_identity_is_independent_of_extraction_locator_and_source_bytes():
    original = node(evidence=document())
    reextracted = deepcopy(original)
    reextracted['evidence'][0].update(source_span_id='reextracted-span',
                                     locator_json='{"text_start":110,"text_end":190}',
                                     extraction_revision_id='parser-output-2', extraction_content_hash_sha256='f' * 64)
    assert batch(nodes=[original]).nodes[0].projection_id == batch(nodes=[reextracted]).nodes[0].projection_id
    assert batch(nodes=[original]).content_hash != batch(nodes=[reextracted]).content_hash
    assert node(revision='other-legal-version')['projection_id'] != original['projection_id']
    # Equal raw files in two years do not collapse their supplied canonical IDs.
    a, b = node('FY2025-account', evidence=structured(revision='source-revision-2025')), node('FY2026-account')
    assert a['evidence'][0]['source_content_hash_sha256'] == b['evidence'][0]['source_content_hash_sha256']
    assert a['projection_id'] != b['projection_id']
    assert validate([batch(nodes=[a, b])])['nodes'] == 2


def test_cross_partition_endpoint_direction_preserved_and_joint_context_never_generates_edges():
    a, b = node('a'), node('b')
    relation = edge(a, b)
    relation['context_json'] = '{"inputs":["a","other-input"],"outputs":["b","other-output"]}'
    first = batch(nodes=[a], edges=[relation])
    second = batch('partition-b', nodes=[b])
    report = validate([first, second])
    assert report['nodes'] == 2 and report['edges'] == 1
    assert first.edges[0].source_node_id == a['projection_id']
    assert first.edges[0].target_node_id == b['projection_id']
    # Shape-only validation never asserts that supplied relationship semantics or
    # joint input/output membership proves this edge; integration must check it.
    no_relation = batch(nodes=[a, b])
    assert validate([no_relation])['edges'] == 0


def test_new_bill_requires_explicit_retention_and_partition_content_is_manifest_independent():
    first = batch(nodes=[node('a')]); second = batch('partition-b', nodes=[node('b')])
    prior = descriptor(first)
    assert validate([first, second], retained=(prior,))['partitions'] == 2
    with pytest.raises(ValueError, match='omits a required retained'):
        validate([second], retained=(prior,))
    old_manifest = manifest([first])
    new_manifest = manifest([first, second], manifest_id='manifest-b')
    assert old_manifest.content_hash != new_manifest.content_hash
    assert new_manifest.partitions[0] == old_manifest.partitions[0]
    modified = node('a'); modified['description'] = 'changed'
    replacement = batch(nodes=[modified])
    with pytest.raises(ValueError, match='immutable retained partition replay conflicts'):
        validate([replacement, second], retained=(prior,))


def test_retention_parameter_cannot_be_accidentally_omitted_and_duplicates_fail():
    value = manifest([batch()])
    with pytest.raises(TypeError):
        validate_fiscal_projection_manifest(value, [batch()], expected_scope=SCOPE)
    with pytest.raises(ValueError, match='retained set repeats'):
        validate_fiscal_partition_replay(value, retained_partitions=(value.partitions[0], value.partitions[0]))
    with pytest.raises(ValueError, match='bounded tuple'):
        validate_fiscal_partition_replay(value, retained_partitions=list(value.partitions))


@pytest.mark.parametrize('count', [True, False, 1.0, '1', -1, 256001])
def test_counts_are_strict_bounded_integers(count):
    with pytest.raises(ValidationError):
        FiscalProjectionCounts(nodes=count, edges=0, descriptions=0)


@pytest.mark.parametrize('record', [True, False, 1.0, '1', 0, -1, 100001])
def test_csv_record_number_is_never_coerced(record):
    with pytest.raises(ValidationError):
        FiscalStructuredRecordLocator(data_record_1based=record)


@pytest.mark.parametrize('count', [True, False, 1.0, '1', 0, 2])
def test_header_count_is_one_strict_integer(count):
    with pytest.raises(ValidationError):
        FiscalStructuredRecordLocator(data_record_1based=1, header_records=count)


@pytest.mark.parametrize('line_end', [True, False, 2.0, '2', 0, -1, 1, 16 * 1024 * 1024 + 1])
def test_physical_line_diagnostic_rejects_coercion_impossible_and_excessive_values(line_end):
    with pytest.raises(ValidationError):
        FiscalStructuredRecordLocator(data_record_1based=1, physical_line_end_1based=line_end)


def test_physical_line_diagnostic_preserves_unknown_and_multiline_location():
    absent = FiscalStructuredRecordLocator(data_record_1based=384)
    explicit_unknown = FiscalStructuredRecordLocator(data_record_1based=384, physical_line_end_1based=None)
    assert absent.physical_line_end_1based is explicit_unknown.physical_line_end_1based is None
    exact = FiscalStructuredRecordLocator(data_record_1based=384, physical_line_end_1based=385)
    multiline = FiscalStructuredRecordLocator(data_record_1based=384, physical_line_end_1based=389)
    assert exact.data_record_1based == multiline.data_record_1based == 384
    assert multiline.model_dump()['physical_line_end_1based'] == 389
    with pytest.raises(ValidationError, match='cannot precede'):
        FiscalStructuredRecordLocator(data_record_1based=384, physical_line_end_1based=384)
    assert FiscalStructuredRecordLocator(data_record_1based=1, physical_line_end_1based=16 * 1024 * 1024)


@pytest.mark.parametrize('payload', [
    '{"amount":NaN}', '{"amount":Infinity}', '{"amount":-Infinity}', '{"amount":1e999}',
    '{"same":1,"same":2}', '[1,2]', '{"x":' * 10 + '0' + '}' * 10,
    '{"long":"' + 'x' * 16384 + '"}',
])
def test_opaque_upstream_json_is_finite_bounded_and_unambiguous(payload):
    with pytest.raises(ValidationError):
        FiscalProjectionNode.model_validate({**node(), 'structured_fields_json': payload})


def test_immutable_payloads_cannot_be_changed_after_validation():
    payload = node()
    value = FiscalProjectionNode.model_validate(payload)
    payload['evidence'][0]['raw_record_sha256'] = 'c' * 64
    assert value.evidence[0].raw_record_sha256 == 'b' * 64
    assert isinstance(value.evidence, tuple)
    with pytest.raises(ValidationError):
        value.evidence[0].raw_record_sha256 = 'c' * 64
    with pytest.raises(ValidationError):
        value.structured_fields_json = '{"subunit":"00"}'


def test_blank_descriptions_cannot_inflate_descriptor_counts():
    with pytest.raises(ValidationError, match='description must not be blank'):
        FiscalProjectionNode.model_validate({**node(), 'description': ' \n\t'})


def test_model_construct_and_model_copy_are_revalidated_including_nested_models():
    good = batch()
    bad_counts = good.expected_counts.model_copy(update={'nodes': True})
    bad_batch = good.model_copy(update={'expected_counts': bad_counts})
    with pytest.raises(ValidationError):
        fiscal_projection_content_hash(bad_batch)
    forged = FiscalProjectionBatch.model_construct(**{**good.model_dump(), 'nodes': 'not-an-array'})
    with pytest.raises(ValidationError):
        validate_fiscal_projection_manifest(manifest([good]), [forged], expected_scope=SCOPE, retained_partitions=())
    bad_evidence = good.nodes[0].evidence[0].model_copy(update={'raw_record_sha256': 'not-a-hash'})
    bad_node = good.nodes[0].model_copy(update={'evidence': (bad_evidence,)})
    with pytest.raises(ValidationError):
        fiscal_projection_content_hash(good.model_copy(update={'nodes': (bad_node,)}))


def test_citation_entity_subject_mismatch_fails_and_nonfinite_score_fails():
    ref = reference()
    citation = FiscalEvidenceCitation(canonical_reference=ref, evidence=structured())
    kwargs = dict(canonical_reference=ref, evidence=(citation,), snapshot_reference=reference('snapshot'), manifest_id='m')
    assert FiscalEntityResult(**kwargs).score is None
    with pytest.raises(ValidationError, match='subject does not match'):
        FiscalEntityResult(**{**kwargs, 'canonical_reference': reference('somebody-else')})
    for score in (float('nan'), float('inf'), float('-inf')):
        with pytest.raises(ValidationError):
            FiscalEntityResult(**kwargs, score=score)


@pytest.mark.parametrize('url', ['file:///private/data', 'ftp://example.test/file', 'https://u:p@example.test',
                                'https://example.test/a\nb', '//example.test/file'])
def test_citation_url_shape_rejects_nonpublic_schemes_credentials_and_controls(url):
    with pytest.raises(ValidationError):
        FiscalStructuredRecordEvidence.model_validate({**structured(), 'citation_url': url})


def test_parser_revision_hash_pair_required_and_source_hash_not_replaced():
    with pytest.raises(ValidationError, match='supplied together'):
        FiscalStructuredRecordEvidence.model_validate({**structured(), 'extraction_revision_id': 'parser-v2'})
    value = FiscalStructuredRecordEvidence.model_validate({**structured(), 'extraction_revision_id': 'parser-v2',
                                                           'extraction_content_hash_sha256': 'f' * 64})
    assert value.source_content_hash_sha256 != value.extraction_content_hash_sha256


def test_batch_node_and_edge_caps_remain_1000_and_2000():
    nodes = [node(f'node-{i}') for i in range(1000)]
    good = batch(nodes=nodes)
    assert validate([good])['nodes'] == 1000
    with pytest.raises(ValidationError):
        batch(nodes=nodes + [node('extra')])
    a, b = nodes[:2]
    edges = [edge(a, b, name=f'edge-{i}') for i in range(2000)]
    assert validate([batch(nodes=[a, b], edges=edges)])['edges'] == 2000
    with pytest.raises(ValidationError):
        batch(nodes=[a, b], edges=edges + [edge(a, b, name='extra')])


def test_two_full_node_batches_do_not_raise_per_batch_cap_or_silently_truncate():
    first = batch(nodes=[node(f'a-{i}') for i in range(1000)])
    second = batch('partition-b', nodes=[node(f'b-{i}') for i in range(1000)])
    assert validate([first, second])['nodes'] == 2000


def test_batch_bytes_and_total_stream_bytes_have_separate_hard_limits(monkeypatch):
    first, second = batch(), batch('partition-b', nodes=[node('b')])
    import svs_common.fiscal_graph as graph
    monkeypatch.setattr(graph, 'MAX_FISCAL_PROJECTION_TOTAL_BYTES', 1)
    with pytest.raises(ValueError, match='total byte limit'):
        validate([first, second])
    monkeypatch.setattr(graph, 'MAX_FISCAL_PROJECTION_BATCH_BYTES', 1)
    with pytest.raises(ValueError, match='byte limit'):
        fiscal_projection_content_hash(first)


def test_partition_descriptor_limit_is_finite():
    value = manifest([batch()]).model_dump()
    value['partitions'] *= 257
    with pytest.raises(ValidationError):
        FiscalProjectionManifest.model_validate(value)


def test_missing_extra_and_reordered_partition_streams_fail_without_reading_forever():
    a, b = batch(), batch('partition-b', nodes=[node('b')])
    full = manifest([a, b])
    with pytest.raises(ValueError, match='incomplete'):
        validate([a], value=full)
    with pytest.raises(ValueError, match='order or identity'):
        validate([b, a], value=full)
    consumed = []
    def stream():
        while True:
            consumed.append(len(consumed)); yield a
    with pytest.raises(ValueError, match='undeclared extra'):
        validate_fiscal_projection_manifest(manifest([a]), stream(), expected_scope=SCOPE, retained_partitions=())
    assert len(consumed) == 2


def test_manifest_partition_order_is_digest_bound():
    a, b = batch(), batch('partition-b', nodes=[node('b')])
    full = manifest([a, b])
    tampered = full.model_copy(update={'partitions': tuple(reversed(full.partitions))})
    with pytest.raises(ValueError, match='manifest content digest mismatch'):
        validate([b, a], value=tampered)


def test_counts_digests_duplicates_and_dangling_endpoints_are_independent_failures():
    a, b = node('a'), node('b')
    first = batch(nodes=[a])
    second = batch('partition-b', nodes=[b])
    value = manifest([first, second])
    counts = FiscalProjectionCounts(nodes=3, edges=0, descriptions=2)
    with pytest.raises(ValueError, match='total counts'):
        validate([first, second], value=rehash_manifest(value.model_copy(update={'total_expected_counts': counts})))
    corrupt = first.model_copy(update={'content_hash': 'f' * 64})
    with pytest.raises(ValueError, match='partition content digest'):
        validate([corrupt, second], value=manifest([corrupt, second]))
    duplicate = batch('partition-b', nodes=[a])
    with pytest.raises(ValueError, match='duplicate or conflicting fiscal identity'):
        validate([first, duplicate])
    with pytest.raises(ValueError, match='repeats a partition'):
        validate([first, first])
    missing = batch(nodes=[a], edges=[edge(a, b)])
    with pytest.raises(ValueError, match='unresolved cross-partition endpoints'):
        validate([missing])


def test_conflicting_record_or_span_binding_is_not_silently_reused():
    first = batch(nodes=[node('a')])
    bad_row = structured(); bad_row['raw_record_sha256'] = 'f' * 64
    second = batch('partition-b', nodes=[node('b', evidence=bad_row)])
    with pytest.raises(ValueError, match='conflicting fiscal structured row'):
        validate([first, second])
    first = batch(nodes=[node('a', evidence=document())])
    bad_span = document(); bad_span['source_revision_id'] = 'wrong-revision'
    second = batch('partition-b', nodes=[node('b', evidence=bad_span)])
    with pytest.raises(ValueError, match='conflicting fiscal source span'):
        validate([first, second])


def test_scope_and_scoped_identity_mismatch_rejected():
    other = FiscalProjectionScope(tenant_id='other', business_instance_id=SCOPE.business_instance_id,
                                 vector_store_id=SCOPE.vector_store_id)
    value = manifest([batch()], scope=other)
    with pytest.raises(ValueError, match='manifest scope'):
        validate([batch()], value=value)
    foreign_batch = batch(nodes=[node(scope=other)], scope=other)
    with pytest.raises(ValueError, match='partition scope'):
        validate([foreign_batch], value=manifest([foreign_batch]))
    wrong_id = node(); wrong_id['projection_id'] = fiscal_projection_node_id(other, reference())
    with pytest.raises(ValueError, match='scoped canonical reference'):
        validate([batch(nodes=[wrong_id])])


def test_empty_projection_can_only_be_an_explicit_offline_manifest_not_automatic_removal():
    empty = batch(nodes=[], edges=[])
    assert validate([empty])['nodes'] == 0
    prior = descriptor(batch())
    with pytest.raises(ValueError, match='immutable retained partition replay conflicts'):
        validate([empty], retained=(prior,))


@pytest.mark.parametrize('kind', ['structured_record', 'document_span'])
def test_one_source_revision_cannot_carry_conflicting_hashes_across_different_locators(kind):
    first_evidence = structured() if kind == 'structured_record' else document()
    second_evidence = deepcopy(first_evidence)
    second_evidence['source_content_hash_sha256'] = 'f' * 64
    if kind == 'structured_record':
        second_evidence['locator']['data_record_1based'] += 1
    else:
        second_evidence['source_span_id'] = 'other-span'
    with pytest.raises(ValueError, match='conflicting raw content hashes for one source revision'):
        validate([batch(nodes=[node('a', evidence=first_evidence), node('b', evidence=second_evidence)])])


def test_one_extraction_revision_cannot_have_two_content_hashes():
    first_evidence = {**structured(), 'extraction_revision_id': 'parser-output-a',
                      'extraction_content_hash_sha256': 'e' * 64}
    second_evidence = {**structured(record=385), 'extraction_revision_id': 'parser-output-a',
                       'extraction_content_hash_sha256': 'f' * 64}
    with pytest.raises(ValueError, match='conflicting content hashes for one extraction revision'):
        validate([batch(nodes=[node('a', evidence=first_evidence), node('b', evidence=second_evidence)])])


def test_repeated_logical_row_preserves_unknown_line_diagnostics_but_rejects_conflicting_known_values():
    unknown, known, conflicting = structured(), structured(), structured()
    known['locator']['physical_line_end_1based'] = 385
    conflicting['locator']['physical_line_end_1based'] = 386
    for evidence_order in ((unknown, known), (known, unknown)):
        nodes = [node(name, evidence=evidence) for name, evidence in zip(('a', 'b'), evidence_order)]
        assert validate([batch(nodes=nodes)])['nodes'] == 2
    with pytest.raises(ValueError, match='conflicting physical line diagnostics'):
        validate([batch(nodes=[node('a', evidence=known), node('b', evidence=conflicting)])])
    # Physical lines add evidence diagnostics, not a new canonical/projection ID.
    assert node(evidence=known)['projection_id'] == node(evidence=unknown)['projection_id']
