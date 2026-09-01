from __future__ import annotations
import hashlib, secrets, time
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from .config import get_settings
from .ids import new_id
from .schemas import Principal

PREFIX = "svs_live_"
DEFAULT_API_KEY_SCOPES = ["retrieval:read", "documents:write", "vector_stores:write"]

def generate_api_key() -> str:
    return PREFIX + secrets.token_urlsafe(32)

def api_key_hash(raw_key: str) -> str:
    pepper = get_settings().svs_api_key_pepper
    return hashlib.sha256((raw_key + ":" + pepper).encode("utf-8")).hexdigest()

def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()

def api_key_metadata_from_row(row) -> dict:
    payload = {
        "id": row["id"],
        "object": "api_key",
        "label": row["label"],
        "scopes": list(row["scopes"] or []),
        "max_security_level": row["max_security_level"],
        "user_id": row.get("user_id"),
        "status": row["status"],
        "created_at": row.get("created_at"),
        "last_used_at": row.get("last_used_at"),
        "expires_at": row.get("expires_at"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def openai_project_api_key_from_metadata(metadata: dict, *, owner_user_id: str | None = None) -> dict:
    key_id = str(metadata["id"])
    redacted_tail = key_id[-6:] if len(key_id) > 6 else key_id
    payload = {
        "object": "organization.project.api_key",
        "redacted_value": f"{PREFIX}...{redacted_tail}",
        "name": metadata.get("label") or key_id,
        "created_at": metadata.get("created_at"),
        "last_used_at": metadata.get("last_used_at"),
        "id": key_id,
        "owner": {
            "type": "user",
            "user": {
                "id": owner_user_id or "user_unknown",
            },
        },
    }
    return {key: value for key, value in payload.items() if value is not None}


def openai_admin_api_key_from_metadata(metadata: dict, *, owner_user_id: str | None = None) -> dict:
    key_id = str(metadata["id"])
    redacted_tail = key_id[-6:] if len(key_id) > 6 else key_id
    payload = {
        "object": "organization.admin_api_key",
        "id": key_id,
        "name": metadata.get("label") or key_id,
        "redacted_value": f"{PREFIX}...{redacted_tail}",
        "created_at": metadata.get("created_at"),
        "expires_at": metadata.get("expires_at"),
        "last_used_at": metadata.get("last_used_at"),
        "owner": {
            "type": "user",
            "object": "organization.user",
            "id": owner_user_id or "user_unknown",
            "role": "owner",
        },
    }
    return {key: value for key, value in payload.items() if value is not None}


def openai_admin_api_key_create_response(
    created: dict,
    *,
    created_at: int,
    owner_user_id: str | None = None,
) -> dict:
    payload = openai_admin_api_key_from_metadata(
        {
            "id": created["id"],
            "label": created.get("label"),
            "created_at": created_at,
            "expires_at": created.get("expires_at"),
        },
        owner_user_id=owner_user_id,
    )
    payload["value"] = created["api_key"]
    return payload


def _validate_api_key_expires_at(expires_at: int | None) -> int | None:
    if expires_at is None:
        return None
    if isinstance(expires_at, bool) or expires_at <= int(time.time()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="expires_at must be a future Unix timestamp")
    return int(expires_at)

def create_api_key(db: Session, principal: Principal, label: str, scopes: list[str] | None = None, max_security_level: int | None = None, expires_at: int | None = None, *, user_id: str | None = None) -> dict:
    """Mint a key. ``user_id`` binds the key to a caller-provisioned user (WAVE-125);
    otherwise the key inherits the creating principal's user binding. Callers are
    responsible for validating that ``user_id`` is in scope before calling."""
    effective_expires_at = _validate_api_key_expires_at(expires_at)
    raw = generate_api_key()
    key_id = new_id("key")
    effective_scopes = list(scopes) if scopes is not None else list(DEFAULT_API_KEY_SCOPES)
    effective_max_level = max_security_level if max_security_level is not None else principal.max_security_level
    effective_user_id = user_id if user_id is not None else principal.user_id
    db.execute(text("""
        INSERT INTO api_keys(id, tenant_id, business_instance_id, user_id, key_hash, label, scopes, max_security_level, expires_at, status)
        VALUES (:id, :tenant_id, :biz_id, :user_id, :key_hash, :label, :scopes, :max_level, to_timestamp(CAST(:expires_at AS double precision)), 'active')
    """), {
        "id": key_id,
        "tenant_id": principal.tenant_id,
        "biz_id": principal.business_instance_id,
        "user_id": effective_user_id,
        "key_hash": api_key_hash(raw),
        "label": label,
        "scopes": effective_scopes,
        "max_level": effective_max_level,
        "expires_at": effective_expires_at,
    })
    result = {"id": key_id, "api_key": raw, "label": label, "scopes": effective_scopes, "max_security_level": effective_max_level}
    if effective_expires_at is not None:
        result["expires_at"] = effective_expires_at
    if user_id is not None:
        result["user_id"] = effective_user_id
    return result

def list_api_keys(
    db: Session,
    principal: Principal,
    limit: int = 20,
    *,
    after: str | None = None,
    status: str | None = None,
    order: str = "desc",
    user_id: str | None = None,
) -> tuple[list[dict], bool]:
    limit = min(max(limit, 1), 100)
    order = "asc" if order == "asc" else "desc"
    params = {"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "limit": limit + 1}
    status_clause = ""
    if status is not None:
        status_clause = "AND status=:status"
        params["status"] = status
    if user_id is not None:
        status_clause += " AND user_id=:filter_user_id"
        params["filter_user_id"] = user_id
    after_clause = ""
    if after:
        after_row = db.execute(text("""
            SELECT id, created_at
            FROM api_keys
            WHERE id=:after AND tenant_id=:tenant_id AND business_instance_id IS NOT DISTINCT FROM :biz_id
              """ + status_clause + """
            LIMIT 1
        """), {**params, "after": after}).mappings().first()
        if after_row:
            after_op = ">" if order == "asc" else "<"
            after_clause = f"AND (created_at {after_op} :after_created_at OR (created_at=:after_created_at AND id {after_op} :after_id))"
            params["after_created_at"] = after_row["created_at"]
            params["after_id"] = after_row["id"]
    rows = db.execute(text("""
        SELECT id, label, scopes, max_security_level, user_id, status,
               extract(epoch from created_at)::bigint AS created_at,
               extract(epoch from last_used_at)::bigint AS last_used_at,
               extract(epoch from expires_at)::bigint AS expires_at
        FROM api_keys
        WHERE tenant_id=:tenant_id AND business_instance_id IS NOT DISTINCT FROM :biz_id
          """ + status_clause + """
          """ + after_clause + """
        ORDER BY created_at """ + order.upper() + """, id """ + order.upper() + """
        LIMIT :limit
    """), params).mappings().all()
    has_more = len(rows) > limit
    return [api_key_metadata_from_row(row) for row in rows[:limit]], has_more

def get_api_key(db: Session, principal: Principal, api_key_id: str, *, status: str | None = None) -> dict | None:
    params = {"id": api_key_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id}
    status_clause = ""
    if status is not None:
        status_clause = "AND status=:status"
        params["status"] = status
    row = db.execute(text("""
        SELECT id, label, scopes, max_security_level, user_id, status,
               extract(epoch from created_at)::bigint AS created_at,
               extract(epoch from last_used_at)::bigint AS last_used_at,
               extract(epoch from expires_at)::bigint AS expires_at
        FROM api_keys
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id IS NOT DISTINCT FROM :biz_id
          """ + status_clause + """
        LIMIT 1
    """), params).mappings().first()
    if not row:
        return None
    return api_key_metadata_from_row(row)

def revoke_api_key(db: Session, principal: Principal, api_key_id: str) -> dict | None:
    row = db.execute(text("""
        UPDATE api_keys
        SET status='revoked'
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id IS NOT DISTINCT FROM :biz_id
        RETURNING id, label, scopes, max_security_level, user_id, status,
                  extract(epoch from created_at)::bigint AS created_at,
                  extract(epoch from last_used_at)::bigint AS last_used_at,
                  extract(epoch from expires_at)::bigint AS expires_at
    """), {"id": api_key_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id}).mappings().first()
    if not row:
        return None
    return api_key_metadata_from_row(row)

def resolve_api_key_principal(db: Session, authorization: str | None) -> Principal:
    raw = bearer_token(authorization)
    key_hash = api_key_hash(raw)
    # FORCE RLS is enabled in production. Expose only the hashed presented key
    # to the policy so bootstrap lookup can happen before tenant context is known.
    db.execute(text("SELECT set_config('svs.api_key_hash', :key_hash, true)"), {"key_hash": key_hash})
    row = db.execute(text("""
        SELECT id, tenant_id, business_instance_id, user_id, scopes, max_security_level
        FROM api_keys
        WHERE key_hash=:key_hash AND status='active' AND (expires_at IS NULL OR expires_at > now())
    """), {"key_hash": key_hash}).mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired API key")
    db.execute(text("SELECT set_config('svs.tenant_id', :tenant_id, true)"), {"tenant_id": row["tenant_id"]})
    db.execute(text("SELECT set_config('svs.business_instance_id', :biz_id, true)"), {"biz_id": row["business_instance_id"] or ""})
    db.execute(text("SELECT set_config('svs.max_security_level', :lvl, true)"), {"lvl": str(row["max_security_level"])})
    db.execute(text("SELECT set_config('svs.api_key_id', :api_key_id, true)"), {"api_key_id": row["id"]})
    db.execute(text("SELECT set_config('svs.user_id', :user_id, true)"), {"user_id": row["user_id"] or ""})
    groups = []
    external_id = None
    if row["user_id"]:
        # WAVE-125: a key bound to a deactivated user fails closed even if the
        # key row itself was not revoked; the bound user's external_id rides on
        # the principal so expert routes can cross-check external_user_id.
        user_row = db.execute(text("""
            SELECT external_id, status
            FROM users
            WHERE id=:user_id AND tenant_id=:tenant_id
            LIMIT 1
        """), {"user_id": row["user_id"], "tenant_id": row["tenant_id"]}).mappings().first()
        if user_row:
            if user_row["status"] == "deactivated":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key user is deactivated")
            external_id = user_row["external_id"] or None
        group_rows = db.execute(text("""
            SELECT g.slug
            FROM group_memberships gm JOIN groups g ON g.id=gm.group_id
            WHERE gm.user_id=:user_id AND g.tenant_id=:tenant_id
              AND (g.business_instance_id IS NULL OR g.business_instance_id=:biz_id)
        """), {"user_id": row["user_id"], "tenant_id": row["tenant_id"], "biz_id": row["business_instance_id"]}).mappings().all()
        groups = [r["slug"] for r in group_rows]
    db.execute(text("UPDATE api_keys SET last_used_at=now() WHERE id=:id"), {"id": row["id"]})
    scopes = list(row["scopes"] or [])
    roles = [s.removeprefix("role:") for s in scopes if s.startswith("role:")]
    return Principal(
        tenant_id=row["tenant_id"],
        business_instance_id=row["business_instance_id"],
        user_id=row["user_id"],
        api_key_id=row["id"],
        groups=groups,
        roles=roles,
        max_security_level=row["max_security_level"],
        scopes=scopes,
        external_id=external_id,
    )


def principal_has_scope(principal: Principal, required: str | list[str], *, any_of: bool = False) -> bool:
    """Return True when the principal has the required scope(s).

    Scope rules are intentionally simple for the scaffold:
    - "*" or "system" grants everything.
    - Exact scope grants that action.
    - A namespace wildcard such as "documents:*" grants all documents actions.
    - When any_of=True, one matching scope is enough. Otherwise all are required.
    """
    required_scopes = [required] if isinstance(required, str) else list(required)
    granted = set(principal.scopes or [])
    if "*" in granted or "system" in granted:
        return True

    def one(scope: str) -> bool:
        if scope in granted:
            return True
        if ":" in scope:
            ns = scope.split(":", 1)[0]
            return f"{ns}:*" in granted
        return False

    checks = [one(scope) for scope in required_scopes]
    return any(checks) if any_of else all(checks)

def ensure_scope(principal: Principal, required: str | list[str], *, any_of: bool = False) -> None:
    if not principal_has_scope(principal, required, any_of=any_of):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "insufficient_scope",
                "required": [required] if isinstance(required, str) else list(required),
                "any_of": any_of,
            },
        )
