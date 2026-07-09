from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .chunking import estimate_tokens, choose_chunker
from .ids import new_id
from .config import get_settings
from .model_registry import resolve_vectorization_profile, vectorization_modes, model_registry, resolve_embedding_profile, estimate_embedding_cost
from .providers import provider_config_status
from .schemas import DocumentIngestRequest, IngestionPlanResponse, ModelCandidate, Principal

@dataclass
class RouterPolicy:
    deny_external_above_security_level: int = 3
    require_private_provider_above_security_level: int = 4
    fallback_private_embedding_profile: str = 'bge_m3_local'
    fallback_dev_embedding_profile: str = 'hash_mock_1536'

def _privacy_allowed(privacy: str, security_level: int, policy: RouterPolicy) -> tuple[bool, str | None]:
    if security_level >= policy.require_private_provider_above_security_level and privacy != 'private_gpu':
        return False, f'security_level {security_level} requires private provider'
    if security_level > policy.deny_external_above_security_level and privacy == 'external_api':
        return False, f'external provider denied above security level {policy.deny_external_above_security_level}'
    return True, None

def _settings_is_local(settings) -> bool:
    prop = getattr(settings, "is_local_env", None)
    if isinstance(prop, bool):
        return prop
    env = str(getattr(settings, "svs_env", "local") or "").strip().lower()
    return env in {"local", "dev", "development", "test", "testing", "ci"}

def _mock_embedding_allowed(settings) -> bool:
    default_provider = str(getattr(settings, "default_embedding_provider", "") or "").strip().lower()
    return _settings_is_local(settings) and default_provider == "hash_mock"

def _expand_profile_candidates(profile_id: str, registry: dict) -> list[str]:
    profiles = registry.get('models', {})
    seen: list[str] = []
    def add(pid: str):
        if pid and pid not in seen:
            seen.append(pid)
    p = profiles.get(profile_id, {})
    if p.get('provider') == 'routing_alias':
        for cand in p.get('candidates', []):
            add(cand)
    else:
        add(profile_id)
    return seen

def build_ingestion_plan(principal: Principal, req: DocumentIngestRequest, settings=None) -> IngestionPlanResponse:
    settings = settings or get_settings()
    mode_id, mode = resolve_vectorization_profile(req.filename, req.mime_type, req.mode, req.attributes)
    registry = model_registry()
    policy_cfg = registry.get('policies', {})
    policy = RouterPolicy(
        deny_external_above_security_level=int(policy_cfg.get('deny_external_above_security_level', 3)),
        require_private_provider_above_security_level=int(policy_cfg.get('require_private_provider_above_security_level', 4)),
        fallback_private_embedding_profile=policy_cfg.get('fallback_private_embedding_profile', 'bge_m3_local'),
        fallback_dev_embedding_profile=policy_cfg.get('fallback_dev_embedding_profile', 'hash_mock_1536'),
    )
    preferred = mode.get('embedding_profile') or resolve_embedding_profile(mode_id, req.security_level)
    candidate_ids = _expand_profile_candidates(preferred, registry)
    if policy.fallback_private_embedding_profile not in candidate_ids:
        candidate_ids.append(policy.fallback_private_embedding_profile)
    if policy.fallback_dev_embedding_profile not in candidate_ids:
        candidate_ids.append(policy.fallback_dev_embedding_profile)
    profiles = registry.get('models', {})
    candidates: list[ModelCandidate] = []
    estimated_tokens = estimate_tokens(req.content)
    for idx, candidate_id in enumerate(candidate_ids):
        p = profiles.get(candidate_id, {})
        provider = p.get('provider', 'hash_mock')
        privacy = p.get('privacy', 'unknown')
        allowed, reason = _privacy_allowed(privacy, req.security_level, policy)
        provider_status = provider_config_status(provider, settings)
        cost = estimate_embedding_cost(candidate_id, estimated_tokens, registry=registry)
        score = 100.0 - (idx * 7.5)
        reasons = []
        if candidate_id == preferred:
            reasons.append('mode preferred embedding profile')
            score += 15
        if privacy == 'private_gpu' and req.security_level >= 3:
            reasons.append('private GPU preferred for high-security content')
            score += 10
        if provider == 'hash_mock':
            reasons.append('development fallback only')
            score -= 30
            if not _mock_embedding_allowed(settings):
                allowed = False
                reasons.append('hash_mock allowed only when local DEFAULT_EMBEDDING_PROVIDER=hash_mock')
                score -= 100
        if not provider_status.configured:
            allowed = False
            if provider_status.reason:
                reasons.append(provider_status.reason)
            score -= 100
        if not allowed and reason:
            reasons.append(reason)
            score -= 100
        candidates.append(ModelCandidate(
            model_profile_id=candidate_id,
            provider=provider,
            model=p.get('model'),
            dimensions=p.get('dimensions'),
            privacy=privacy,
            configured=provider_status.configured,
            required_env=list(provider_status.required_env),
            score=round(score, 3),
            allowed=allowed,
            reasons=reasons,
            estimated_input_tokens=cost.get('estimated_tokens'),
            estimated_cost_usd=cost.get('estimated_cost_usd'),
            cost_currency=cost.get('currency'),
            cost_unit=cost.get('unit'),
            cost_per_1m_tokens_usd=cost.get('input_per_1m_tokens_usd'),
            cost_reason=cost.get('reason'),
        ))
    candidates.sort(key=lambda c: (c.allowed, c.score), reverse=True)
    chosen_candidate = next((c for c in candidates if c.allowed), None)
    chosen = chosen_candidate.model_profile_id if chosen_candidate else preferred
    chunker = choose_chunker(mode_id)
    sample_chunks = chunker(req.content)
    warnings = []
    if mode.get('status') == 'research':
        warnings.append(f'mode {mode_id} is research; use external parser/bakeoff before production')
    if mode_id == 'raw_pdf_research_v1':
        warnings.append('raw PDF JSON ingestion is not implemented; use multipart upload with RunPod Marker or pdf_markdown_external_v1')
    if req.security_level >= 4 and chosen == policy.fallback_dev_embedding_profile:
        warnings.append('high-security content fell back to dev model; configure private RunPod/TEI endpoint')
    if not chosen_candidate:
        warnings.append('no configured embedding provider candidate is allowed; ingestion will fail until provider env is configured')
    return IngestionPlanResponse(
        mode=mode_id,
        parser=mode.get('parser') or ','.join(mode.get('parser_candidates', [])) or None,
        chunker=mode.get('chunker'),
        embedding_profile_id=chosen,
        retrieval_profile_id=mode.get('retrieval_profile', 'hybrid_rrf_secure_v2'),
        candidates=candidates,
        estimated_tokens=estimated_tokens,
        estimated_chunks=len(sample_chunks),
        warnings=warnings,
    )

def persist_ingestion_plan(db: Session, principal: Principal, req: DocumentIngestRequest, plan: IngestionPlanResponse) -> IngestionPlanResponse:
    plan_id = new_id('plan')
    db.execute(jsonb_text('''
        INSERT INTO ingestion_plans(id, tenant_id, business_instance_id, user_id, vector_store_id, knowledge_base_id,
          mode, parser_profile_id, chunking_profile_id, embedding_profile_id, retrieval_profile_id, request, plan, status)
        VALUES (:id, :tenant_id, :biz_id, :user_id, :vs_id, :kb_id, :mode, :parser, :chunker, :embedding, :retrieval,
          CAST(:request AS jsonb), CAST(:plan AS jsonb), 'planned')
    ''', 'request', 'plan'), {
        'id': plan_id,
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
        'user_id': principal.user_id,
        'vs_id': req.vector_store_id,
        'kb_id': req.knowledge_base_id,
        'mode': plan.mode,
        'parser': plan.parser,
        'chunker': plan.chunker,
        'embedding': plan.embedding_profile_id,
        'retrieval': plan.retrieval_profile_id,
        'request': jsonb_param(req.model_dump()),
        'plan': jsonb_param(plan.model_dump()),
    })
    return plan.model_copy(update={'id': plan_id, 'persisted': True})
