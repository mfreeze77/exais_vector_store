"""WAVE-125: caller-provisioned users bound to the principal's tenant and instance.

Every query here is scoped by ``tenant_id`` and ``business_instance_id`` from the
request principal so a cell admin key can only ever see or mutate the users it
provisioned. RLS on ``users`` is tenant-scoped; the business-instance fence is
enforced in SQL below.
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import jsonb_param
from .ids import new_id
from .schemas import Principal
from .sql import jsonb_text

USER_COLUMNS = """
    id, external_id, email, display_name, status, business_instance_id,
    extract(epoch from created_at)::bigint AS created_at,
    extract(epoch from deactivated_at)::bigint AS deactivated_at
"""


def user_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "object": "user",
        "external_id": row.get("external_id"),
        "email": row.get("email"),
        "display_name": row.get("display_name"),
        "status": row["status"],
        "business_instance_id": row.get("business_instance_id"),
        "created_at": row.get("created_at"),
        "deactivated_at": row.get("deactivated_at"),
    }


def _scope(principal: Principal) -> dict[str, Any]:
    return {"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id}


def get_user(db: Session, principal: Principal, user_id: str) -> dict[str, Any] | None:
    row = db.execute(text(f"""
        SELECT {USER_COLUMNS}
        FROM users
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        LIMIT 1
    """), {**_scope(principal), "id": user_id}).mappings().first()
    return user_from_row(row) if row else None


def get_user_by_external_id(db: Session, principal: Principal, external_id: str) -> dict[str, Any] | None:
    """Instance-fenced lookup: only users of the principal business instance are visible."""
    row = db.execute(text(f"""
        SELECT {USER_COLUMNS}
        FROM users
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND external_id=:external_id
        LIMIT 1
    """), {**_scope(principal), "external_id": external_id}).mappings().first()
    return user_from_row(row) if row else None


def _tenant_user_by_external_id(db: Session, principal: Principal, external_id: str) -> dict[str, Any] | None:
    """Tenant-wide lookup used only to detect a cross-instance external_id collision.

    The unique index is per tenant, so provisioning must see the other instance
    row to answer 409 instead of racing the index. Nothing from this row is
    returned to callers.
    """
    row = db.execute(text(f"""
        SELECT {USER_COLUMNS}
        FROM users
        WHERE tenant_id=:tenant_id AND external_id=:external_id
        LIMIT 1
    """), {"tenant_id": principal.tenant_id, "external_id": external_id}).mappings().first()
    return user_from_row(row) if row else None


def create_or_get_user(
    db: Session,
    principal: Principal,
    *,
    external_id: str,
    email: str | None = None,
    display_name: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Idempotent on (tenant_id, external_id). Returns (user, created).

    An existing user with the same external_id but a different business instance
    is a 409: external ids are unique per tenant and a cell must not silently
    adopt another instance's identity.
    """
    existing = _tenant_user_by_external_id(db, principal, external_id)
    if existing is not None:
        if existing["business_instance_id"] != principal.business_instance_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="external_id is already provisioned in another business instance",
            )
        return existing, False
    if email is not None:
        email_owner = db.execute(text("""
            SELECT id FROM users WHERE tenant_id=:tenant_id AND email=:email LIMIT 1
        """), {**_scope(principal), "email": email}).mappings().first()
        if email_owner:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email is already provisioned for another user")
    user_id = new_id("usr")
    row = db.execute(text(f"""
        INSERT INTO users(id, tenant_id, business_instance_id, external_id, email, display_name, status)
        VALUES (:id, :tenant_id, :biz_id, :external_id, :email, :display_name, 'active')
        ON CONFLICT DO NOTHING
        RETURNING {USER_COLUMNS}
    """), {
        **_scope(principal),
        "id": user_id,
        "external_id": external_id,
        "email": email,
        "display_name": display_name,
    }).mappings().first()
    if row:
        return user_from_row(row), True
    # Lost a race on the unique index: return the row the other writer created.
    raced = get_user_by_external_id(db, principal, external_id)
    if raced is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user could not be provisioned")
    return raced, False


def list_users(
    db: Session,
    principal: Principal,
    *,
    limit: int = 20,
    after: str | None = None,
    external_id: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    limit = min(max(limit, 1), 100)
    params: dict[str, Any] = {**_scope(principal), "limit": limit + 1}
    filters = ""
    if external_id is not None:
        filters += " AND external_id=:external_id"
        params["external_id"] = external_id
    if status_filter is not None:
        filters += " AND status=:status"
        params["status"] = status_filter
    after_clause = ""
    if after:
        anchor = db.execute(text("""
            SELECT id, created_at FROM users
            WHERE id=:after AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            LIMIT 1
        """), {**_scope(principal), "after": after}).mappings().first()
        if anchor:
            after_clause = " AND (created_at < :after_created_at OR (created_at=:after_created_at AND id < :after_id))"
            params["after_created_at"] = anchor["created_at"]
            params["after_id"] = anchor["id"]
    rows = db.execute(text(f"""
        SELECT {USER_COLUMNS}
        FROM users
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
          {filters}
          {after_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT :limit
    """), params).mappings().all()
    has_more = len(rows) > limit
    return [user_from_row(row) for row in rows[:limit]], has_more


def deactivate_user(db: Session, principal: Principal, user_id: str) -> tuple[dict[str, Any], list[str]] | None:
    """Mark the user deactivated and revoke its active keys. History is preserved.

    Idempotent: deactivating twice returns the user with an empty revoked list.
    """
    row = db.execute(text(f"""
        UPDATE users
        SET status='deactivated',
            deactivated_at=coalesce(deactivated_at, now()),
            updated_at=now()
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        RETURNING {USER_COLUMNS}
    """), {**_scope(principal), "id": user_id}).mappings().first()
    if not row:
        return None
    revoked_rows = db.execute(text("""
        UPDATE api_keys
        SET status='revoked'
        WHERE user_id=:user_id AND tenant_id=:tenant_id
          AND business_instance_id IS NOT DISTINCT FROM :biz_id
          AND status='active'
        RETURNING id
    """), {**_scope(principal), "user_id": user_id}).mappings().all()
    revoked_ids = [item["id"] for item in revoked_rows]
    db.execute(jsonb_text("""
        INSERT INTO audit_events(id, tenant_id, business_instance_id, user_id, api_key_id,
          event_type, action, resource_type, resource_id, metadata)
        VALUES (:id, :tenant_id, :biz_id, :actor_user_id, :actor_api_key_id,
          'admin', 'user.deactivate', 'user', :resource_id, CAST(:metadata AS jsonb))
    """, "metadata"), {
        **_scope(principal),
        "id": new_id("aud"),
        "actor_user_id": principal.user_id,
        "actor_api_key_id": principal.api_key_id,
        "resource_id": user_id,
        "metadata": jsonb_param({
            "external_id": row.get("external_id"),
            "revoked_api_key_ids": revoked_ids,
        }),
    })
    return user_from_row(row), revoked_ids
