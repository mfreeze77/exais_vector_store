from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Any
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .config import get_settings
from .ids import new_id
from .schemas import Principal

def stable_hash(obj: Any) -> str:
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode('utf-8')).hexdigest()

def check_idempotency(db: Session, principal: Principal, key: str | None, request_fingerprint: str) -> dict | None:
    if not key:
        return None
    row = db.execute(text('''
        SELECT response, request_fingerprint, status_code
        FROM idempotency_keys
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND idempotency_key=:key
          AND expires_at > now()
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'key': key}).mappings().first()
    if not row:
        return None
    if row['request_fingerprint'] != request_fingerprint:
        raise HTTPException(status_code=409, detail='Idempotency key already used with a different request body')
    return dict(row['response'] or {})

def store_idempotency(db: Session, principal: Principal, key: str | None, request_fingerprint: str, response: dict, status_code: int = 200) -> None:
    if not key:
        return
    ttl = get_settings().svs_idempotency_ttl_hours
    db.execute(jsonb_text('''
        INSERT INTO idempotency_keys(id, tenant_id, business_instance_id, user_id, api_key_id, idempotency_key,
          request_fingerprint, response, status_code, expires_at)
        VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, :key, :fp, CAST(:response AS jsonb), :status_code, now() + (:ttl || ' hours')::interval)
        ON CONFLICT (tenant_id, business_instance_id, idempotency_key) DO UPDATE
        SET response=excluded.response, status_code=excluded.status_code, updated_at=now()
    ''', 'response'), {'id': new_id('idem'), 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id,
          'user_id': principal.user_id, 'api_key_id': principal.api_key_id, 'key': key, 'fp': request_fingerprint,
          'response': jsonb_param(response), 'status_code': status_code, 'ttl': ttl})

def enforce_rate_limit(db: Session, principal: Principal, bucket: str, limit_per_minute: int | None = None) -> None:
    s = get_settings()
    limit = limit_per_minute or (s.svs_admin_rate_limit_per_minute if bucket.startswith('admin') else s.svs_default_rate_limit_per_minute)
    # Wildcard API keys/dev principals still consume rate-limit budget. Only
    # internal system workers bypass request-rate accounting.
    if 'system' in principal.scopes:
        return
    subject = principal.api_key_id or principal.user_id or 'anonymous'
    _enforce_rate_limit_for_subject(db, principal, subject, bucket, limit, detail=f'Rate limit exceeded for {bucket}: {limit}/minute')


def enforce_resource_rate_limit(
    db: Session,
    principal: Principal,
    *,
    resource_id: str,
    bucket: str,
    limit_per_minute: int,
    resource_label: str,
) -> None:
    if 'system' in principal.scopes:
        return
    subject = f'resource:{resource_id}'
    _enforce_rate_limit_for_subject(
        db,
        principal,
        subject,
        bucket,
        limit_per_minute,
        detail=f'Rate limit exceeded for {resource_label} {resource_id}: {limit_per_minute}/minute',
    )


def _enforce_rate_limit_for_subject(
    db: Session,
    principal: Principal,
    subject: str,
    bucket: str,
    limit: int,
    *,
    detail: str,
) -> None:
    minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    row = db.execute(text('''
        INSERT INTO rate_limit_counters(id, tenant_id, business_instance_id, subject_id, bucket, window_start, count, api_key_id, user_id)
        VALUES (:id, :tenant_id, :biz_id, :subject_id, :bucket, :window_start, 1, :api_key_id, :user_id)
        ON CONFLICT (tenant_id, business_instance_id, subject_id, bucket, window_start)
        DO UPDATE SET count=rate_limit_counters.count + 1, updated_at=now()
        RETURNING count
    '''), {'id': new_id('rl'), 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id,
          'subject_id': subject, 'bucket': bucket, 'window_start': minute,
          'api_key_id': principal.api_key_id, 'user_id': principal.user_id}).mappings().first()
    if row and int(row['count']) > limit:
        raise HTTPException(status_code=429, detail=detail)
