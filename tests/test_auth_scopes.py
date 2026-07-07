import pytest
from fastapi import HTTPException
from svs_common.auth import principal_has_scope, ensure_scope
from svs_common.schemas import Principal


def p(scopes):
    return Principal(tenant_id="t", business_instance_id="b", scopes=scopes)


def test_exact_scope_required():
    assert principal_has_scope(p(["documents:write"]), "documents:write")
    assert not principal_has_scope(p(["documents:read"]), "documents:write")


def test_namespace_wildcard_scope():
    assert principal_has_scope(p(["vector_stores:*"]), "vector_stores:write")


def test_ensure_scope_blocks_missing():
    with pytest.raises(HTTPException):
        ensure_scope(p(["retrieval:read"]), "documents:write")
