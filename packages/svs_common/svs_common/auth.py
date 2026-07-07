from __future__ import annotations
import hashlib, secrets
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from .config import get_settings
from .ids import new_id
from .schemas import Principal

PREFIX = "svs_live_"

def generate_api_key() -> str:
    return PREFIX + secrets.token_urlsafe(32)

def api_key_hash(raw_key: str) -> str:
    pepper = get_settings().svs_api_key_pepper
    return hashlib.sha256((raw_key + ":" + pepper).encode("utf-8")).hexdigest()

def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()

def create_api_key(db: Session, principal: Principal, label: str, scopes: list[str] | None = None, max_security_level: int | None = None) -> dict:
    raw = generate_api_key()
    key_id = new_id("key")
    db.execute(text("""
        INSERT INTO api_keys(id, tenant_id, business_instance_id, user_id, key_hash, label, scopes, max_security_level, status)
        VALUES (:id, :tenant_id, :biz_id, :user_id, :key_hash, :label, :scopes, :max_level, 'active')
    """), {
        "id": key_id,
        "tenant_id": principal.tenant_id,
        "biz_id": principal.business_instance_id,
        "user_id": principal.user_id,
        "key_hash": api_key_hash(raw),
        "label": label,
        "scopes": scopes or ["retrieval:read", "documents:write", "vector_stores:write"],
        "max_level": max_security_level if max_security_level is not None else principal.max_security_level,
    })
    return {"id": key_id, "api_key": raw, "label": label, "scopes": scopes or [], "max_security_level": max_security_level if max_security_level is not None else principal.max_security_level}

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
    groups = []
    if row["user_id"]:
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
