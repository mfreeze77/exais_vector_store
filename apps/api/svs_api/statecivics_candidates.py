"""Candidate-only routes, registered on the normal authenticated API."""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
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


class CandidateIngestResponse(BaseModel):
    """Candidate ingestion acknowledgement; counters describe this request only."""

    model_config = ConfigDict(extra='forbid')
    applied: bool = Field(description='True after this request completed application; false for a plan.')
    entity_path: Literal['candidate']
    collection: str = Field(description='Candidate collection resolved through the deployment guards.')
    manifest_sha256: str = Field(pattern=r'^[0-9a-f]{64}$', description='SHA-256 of the exact submitted manifest bytes.')
    record_count: int = Field(ge=0)
    embedded: int = Field(ge=0, description='Descriptors embedded by the successfully completed request.')
    written: int = Field(ge=0, description='Records written and verified by full-record readback.')
    unchanged: int = Field(ge=0, description='Records skipped because their stored digests already match.')
    point_ids: list[str] = Field(description='Deterministic point identities for every submitted record.')


class CandidateSearchHit(BaseModel):
    """A scored candidate with the complete producer-validated entity envelope."""

    model_config = ConfigDict(extra='forbid')
    point_id: str
    score: float = Field(allow_inf_nan=False)
    record: dict[str, Any] = Field(description='Complete StateCivics record, including eligibility, amount and durable source citation; its payload is validated by the pinned KS contracts on ingestion.')


class CandidateSearchResponse(BaseModel):
    """Candidate-only search results; no publication or review promotion is implied."""

    model_config = ConfigDict(extra='forbid')
    entity_path: Literal['candidate']
    collection: str
    results: list[CandidateSearchHit]


def candidate_router(get_principal, get_db):
    router = APIRouter(prefix='/api/v1/statecivics/entities', tags=['StateCivics candidates'])

    def enabled():
        if not get_settings().svs_entity_candidate_enabled:
            raise HTTPException(503, detail='candidate entity storage is disabled')

    @router.post('/ingest', response_model=CandidateIngestResponse)
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

    @router.post('/candidate/search', response_model=CandidateSearchResponse)
    def search(req: CandidateSearchRequest, principal=Depends(get_principal)):
        ensure_scope(principal, 'retrieval:read')
        enabled()
        try:
            return CandidateEntityStore().search(req.query, principal=principal, limit=req.limit)
        except ValueError as exc:
            raise HTTPException(422, detail={'error': type(exc).__name__, 'message': str(exc)}) from exc

    return router
