from svs_common.schemas import ChunkRecord, RetrievalScope
from svs_common.security import chunk_allowed_by_scope

def test_security_level_blocks_high_chunk():
    chunk = ChunkRecord(id="c", document_id="d", ordinal=0, text="secret", security_level=4)
    scope = RetrievalScope(tenant_id="t", business_instance_id="b", max_security_level=3)
    assert not chunk_allowed_by_scope(chunk, scope)

def test_group_required():
    chunk = ChunkRecord(id="c", document_id="d", ordinal=0, text="team", security_level=2, allowed_groups=["eng"])
    scope = RetrievalScope(tenant_id="t", business_instance_id="b", max_security_level=2, groups=["sales"])
    assert not chunk_allowed_by_scope(chunk, scope)
    scope.groups = ["eng"]
    assert chunk_allowed_by_scope(chunk, scope)
