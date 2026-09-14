"""Candidate-only routes, registered on the normal authenticated API."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from svs_common.auth import ensure_scope
from svs_common.config import get_settings
from svs_common.statecivics_entity_store import (
    CandidateEntityStore, validate_candidate_manifest,
)


class CandidateIngestRequest(BaseModel):
    manifest: str = Field(min_length=1, max_length=2_000_000)
    manifest_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    path: Literal['live', 'candidate'] = 'live'
    apply: bool = False


class CandidateSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


def candidate_router(get_principal, get_db):
    router = APIRouter(prefix='/api/v1/statecivics/entities', tags=['StateCivics candidates'])

    def enabled():
        if not get_settings().svs_entity_candidate_enabled:
            raise HTTPException(503, detail='candidate entity storage is disabled')

    @router.post('/ingest')
    def ingest(req: CandidateIngestRequest, principal=Depends(get_principal), db=Depends(get_db)):
        ensure_scope(principal, 'documents:write')
        enabled()
        try:
            records = validate_candidate_manifest(req.manifest, req.manifest_sha256, path=req.path)
            store = CandidateEntityStore()
            store.authorize(principal)
            if req.apply:
                # Serialize writes for this instance so a competing older
                # revision cannot win between the index read and the upsert.
                db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {
                    'key': f'statecivics-candidate:{principal.tenant_id}:{principal.business_instance_id}'
                })
            result = store.ingest(records, principal=principal, manifest_sha256=req.manifest_sha256, apply=req.apply)
            db.commit()
            return result
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, detail={'error': type(exc).__name__, 'message': str(exc)}) from exc

    @router.post('/candidate/search')
    def search(req: CandidateSearchRequest, principal=Depends(get_principal)):
        ensure_scope(principal, 'retrieval:read')
        enabled()
        try:
            return CandidateEntityStore().search(req.query, principal=principal, limit=req.limit)
        except ValueError as exc:
            raise HTTPException(422, detail={'error': type(exc).__name__, 'message': str(exc)}) from exc

    return router
