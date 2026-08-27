from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Iterator
import json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from .config import get_settings
from .schemas import Principal

_engine = None
_SessionLocal = None


def jsonb_param(value: Any) -> str | None:
    """Return JSON text for ``CAST(:param AS jsonb)`` binds.

    Use this with SQL ``CAST(:name AS jsonb)`` binds. Do not bind JSONB
    SQLAlchemy types to already-serialized JSON strings; that can turn JSON
    objects into JSON string scalars.
    """
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def jsonb_text(sql: str, *json_params: str):
    """Return ``text(sql)`` for JSONB CAST statements.

    ``json_params`` is accepted for call-site readability/auditing. The actual
    adaptation strategy is JSON text + ``CAST(:name AS jsonb)``.
    """
    return text(sql)

def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine

def get_session() -> Iterator[Session]:
    get_engine()
    db = _SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        try:
            if db.in_transaction():
                db.rollback()
        finally:
            db.close()

@contextmanager
def scoped_session(principal: Principal | None = None) -> Iterator[Session]:
    get_engine()
    db = _SessionLocal()
    try:
        if principal:
            set_rls_context(db, principal)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def set_rls_context(db: Session, principal: Principal) -> None:
    db.execute(text("SELECT set_config('svs.tenant_id', :tenant_id, true)"), {"tenant_id": principal.tenant_id})
    db.execute(text("SELECT set_config('svs.business_instance_id', :biz_id, true)"), {"biz_id": principal.business_instance_id})
    db.execute(text("SELECT set_config('svs.max_security_level', :lvl, true)"), {"lvl": str(principal.max_security_level)})
