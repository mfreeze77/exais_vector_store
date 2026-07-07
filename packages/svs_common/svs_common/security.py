from __future__ import annotations
from fastapi import Header, HTTPException, status
from .openai_compat import file_attribute_payload_key
from .config import get_settings
from .schemas import Principal, RetrievalScope, ChunkRecord

def principal_from_dev_headers(
    x_svs_tenant_id: str | None = None,
    x_svs_business_instance_id: str | None = None,
    x_svs_user_id: str | None = None,
    x_svs_groups: str | None = None,
    x_svs_roles: str | None = None,
    x_svs_max_security_level: int | None = None,
) -> Principal:
    s = get_settings()
    groups = [v.strip() for v in (x_svs_groups or s.svs_dev_groups).split(",") if v.strip()]
    roles = [v.strip() for v in (x_svs_roles or s.svs_dev_roles).split(",") if v.strip()]
    return Principal(
        tenant_id=x_svs_tenant_id or s.svs_dev_tenant_id,
        business_instance_id=x_svs_business_instance_id or s.svs_dev_business_instance_id,
        user_id=x_svs_user_id or s.svs_dev_user_id,
        groups=groups,
        roles=roles,
        max_security_level=x_svs_max_security_level or s.svs_dev_max_security_level,
        scopes=["*"],
    )

def get_current_principal(
    authorization: str | None = Header(default=None),
    x_svs_tenant_id: str | None = Header(default=None),
    x_svs_business_instance_id: str | None = Header(default=None),
    x_svs_user_id: str | None = Header(default=None),
    x_svs_groups: str | None = Header(default=None),
    x_svs_roles: str | None = Header(default=None),
    x_svs_max_security_level: int | None = Header(default=None),
) -> Principal:
    s = get_settings()
    if s.svs_dev_mode:
        return principal_from_dev_headers(x_svs_tenant_id, x_svs_business_instance_id, x_svs_user_id, x_svs_groups, x_svs_roles, x_svs_max_security_level)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Production requires a bearer API key")

def build_retrieval_scope(principal: Principal) -> RetrievalScope:
    return RetrievalScope(
        tenant_id=principal.tenant_id,
        business_instance_id=principal.business_instance_id,
        user_id=principal.user_id,
        groups=principal.groups,
        roles=principal.roles,
        max_security_level=principal.max_security_level,
    )

def chunk_allowed_by_scope(chunk: ChunkRecord, scope: RetrievalScope) -> bool:
    if chunk.security_level > scope.max_security_level:
        return False
    if chunk.allowed_roles and not set(chunk.allowed_roles).intersection(scope.roles):
        return False
    if chunk.allowed_groups and not set(chunk.allowed_groups).intersection(scope.groups):
        return False
    return True

def build_qdrant_filter(scope: RetrievalScope, filters: dict | None = None) -> dict:
    must = [
        {"key": "tenant_id", "match": {"value": scope.tenant_id}},
        {"key": "business_instance_id", "match": {"value": scope.business_instance_id}},
        {"key": "active", "match": {"value": True}},
        {"key": "security_level", "range": {"lte": scope.max_security_level}},
    ]
    filters = filters or {}
    for key in ["knowledge_base_id", "vector_store_id", "document_id", "classification", "acl_bucket"]:
        if filters.get(key):
            must.append({"key": key, "match": {"value": filters[key]}})
    for key, value in (filters.get("file_attribute_filters") or {}).items():
        must.append({"key": file_attribute_payload_key(key), "match": {"value": value}})
    return {"must": must}
