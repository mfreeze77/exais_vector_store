from __future__ import annotations
import re
from typing import Any
from fastapi import Header, HTTPException, status
from .openai_compat import OUTPUT_GUARD_ID, file_attribute_payload_key, output_guard_text
from .config import get_settings
from .schemas import Principal, RetrievalScope, ChunkRecord

QDRANT_RANGE_OPERATORS = {"gt": "gt", "gte": "gte", "lt": "lt", "lte": "lte"}
EXPERT_INTERACTION_MAX_DEPTH = 8
EXPERT_INTERACTION_MAX_ITEMS = 100
_SENSITIVE_INTERACTION_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "password",
    "passwd",
    "private_key",
    "pwd",
    "refresh_token",
    "secret",
    "token",
    "access_token",
}
_SENSITIVE_INTERACTION_KEY_FRAGMENTS = (
    "accesskey",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "passwd",
    "privatekey",
    "refreshtoken",
    "secret",
    "sessiontoken",
)


class ExpertInteractionSensitiveDataError(ValueError):
    """Raised when governed feedback or memory cannot be stored safely."""


def _normalized_interaction_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _interaction_key_is_sensitive(value: str) -> bool:
    _, key_guard = output_guard_text(value)
    if key_guard:
        return True
    normalized = _normalized_interaction_key(value)
    compact = normalized.replace("_", "")
    if normalized in _SENSITIVE_INTERACTION_KEYS:
        return True
    if any(fragment in compact for fragment in _SENSITIVE_INTERACTION_KEY_FRAGMENTS):
        return True
    parts = {part for part in normalized.split("_") if part}
    return bool(parts.intersection({"token", "pwd"}))


def _merge_interaction_guards(guards: list[dict[str, Any]]) -> dict[str, Any] | None:
    totals: dict[str, int] = {}
    for guard in guards:
        for redaction in guard.get("redactions") or []:
            kind = redaction.get("type")
            count = redaction.get("count")
            if isinstance(kind, str) and isinstance(count, int):
                totals[kind] = totals.get(kind, 0) + count
    if not totals:
        return None
    return {
        "id": OUTPUT_GUARD_ID,
        "redactions": [{"type": kind, "count": totals[kind]} for kind in sorted(totals)],
    }


def sanitize_expert_interaction_data(value: Any) -> tuple[Any, dict[str, Any] | None]:
    """Redact obvious PII/secrets and reject secret-bearing structured keys before persistence."""

    guards: list[dict[str, Any]] = []

    def sanitize(item: Any, depth: int) -> Any:
        if depth > EXPERT_INTERACTION_MAX_DEPTH:
            raise ExpertInteractionSensitiveDataError("expert interaction payload is too deeply nested")
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            guarded, metadata = output_guard_text(item)
            if metadata:
                guards.append(metadata)
            return guarded
        if isinstance(item, list):
            if len(item) > EXPERT_INTERACTION_MAX_ITEMS:
                raise ExpertInteractionSensitiveDataError("expert interaction payload has too many items")
            return [sanitize(child, depth + 1) for child in item]
        if isinstance(item, dict):
            if len(item) > EXPERT_INTERACTION_MAX_ITEMS:
                raise ExpertInteractionSensitiveDataError("expert interaction payload has too many fields")
            sanitized: dict[str, Any] = {}
            for raw_key, child in item.items():
                if not isinstance(raw_key, str):
                    raise ExpertInteractionSensitiveDataError("expert interaction payload keys must be strings")
                if _interaction_key_is_sensitive(raw_key):
                    raise ExpertInteractionSensitiveDataError("expert interaction payload contains a sensitive field")
                sanitized[raw_key] = sanitize(child, depth + 1)
            return sanitized
        raise ExpertInteractionSensitiveDataError("expert interaction payload contains an unsupported value")

    sanitized_value = sanitize(value, 0)
    return sanitized_value, _merge_interaction_guards(guards)

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
    must_not = []
    for not_filter in filters.get("file_attribute_not_filters") or []:
        must_not.append({
            "key": file_attribute_payload_key(str(not_filter["key"])),
            "match": {"value": not_filter["value"]},
        })
    for not_any_filter in filters.get("file_attribute_not_any") or []:
        attr_key = file_attribute_payload_key(str(not_any_filter["key"]))
        for value in not_any_filter.get("values") or []:
            must_not.append({"key": attr_key, "match": {"value": value}})
    for range_filter in filters.get("file_attribute_ranges") or []:
        value = range_filter.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            must.append({
                "key": file_attribute_payload_key(str(range_filter["key"])),
                "range": {QDRANT_RANGE_OPERATORS[str(range_filter["op"])]: value},
            })
    result = {"must": must}
    if must_not:
        result["must_not"] = must_not
    file_attr_any = filters.get("file_attribute_filter_any") or []
    if file_attr_any:
        result["should"] = [
            {
                "must": [
                    {"key": file_attribute_payload_key(key), "match": {"value": value}}
                    for key, value in option.items()
                ]
            }
            for option in file_attr_any
            if option
        ]
    return result
