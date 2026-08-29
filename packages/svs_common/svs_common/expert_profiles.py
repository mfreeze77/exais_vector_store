from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .schemas import (
    ExpertCitationPolicy,
    ExpertGraphLens,
    ExpertGraphLensPolicy,
    ExpertModelPolicy,
    ExpertProfile,
    ExpertProfileListResponse,
    ExpertToolLimits,
    ExpertVectorStoreBinding,
    Principal,
)
from .search_lenses import search_lens_definitions_for_vector_store
from .vector_store_repo import (
    VectorStoreRepository,
    VectorStoreUnavailableError,
    require_active_vector_store,
)


KS_STATE_CIVICS_TENANT_ID = "ten_ks_state_civics"
KS_STATE_CIVICS_BUSINESS_INSTANCE_ID = "biz_ks_state_civics"
KANSAS_COURT_DECISIONS_VECTOR_STORE_ID = "vs_a0d3ac76893e4f6f83bf2992"
TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID = "vs_d4185d1004604f08a55299fa"


class ExpertProfileNotFoundError(LookupError):
    """The expert does not exist or is not visible to the request principal."""


class ExpertProfileConfigurationError(RuntimeError):
    """A registered expert has an invalid store or lens binding."""


@dataclass(frozen=True)
class ExpertVectorStoreBindingDefinition:
    vector_store_id: str
    tenant_id: str
    business_instance_id: str
    allowed_graph_lens_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpertProfileDefinition:
    id: str
    label: str
    description: str
    system_prompt: str
    vector_store_bindings: tuple[ExpertVectorStoreBindingDefinition, ...]
    citation_policy: ExpertCitationPolicy
    caveats: tuple[str, ...]
    model_policy: ExpertModelPolicy
    tool_limits: ExpertToolLimits
    allow_automatic_graph_lens_selection: bool = True


_RETRIEVED_CORPUS_CITATION_POLICY = ExpertCitationPolicy(
    required=True,
    authority="retrieved_corpus_only",
    preserve_source_urls=True,
    preserve_graph_relationships=True,
    memory_is_authority=False,
)

_DEFAULT_MODEL_POLICY = ExpertModelPolicy(
    policy_id="default_expert_chat_v1",
    gateway="model_gateway",
    allow_fallback=True,
)

_DEFAULT_TOOL_LIMITS = ExpertToolLimits(
    max_retrieval_runs=4,
    max_results_per_run=20,
    max_graph_expansions=6,
    max_context_tokens=12_000,
)


EXPERT_PROFILE_REGISTRY: tuple[ExpertProfileDefinition, ...] = (
    ExpertProfileDefinition(
        id="kansas-court-decisions",
        label="Kansas Court Decisions Expert",
        description="Answers questions from the Kansas appellate court-decision corpus with citation and relationship evidence.",
        system_prompt=(
            "You are the ExAIS Kansas court-decisions expert. Answer only from material retrieved from the bound "
            "Kansas court-decision vector store. Preserve source citations and distinguish graph relationship evidence "
            "from substantive legal authority. If the corpus does not support a claim, say so."
        ),
        vector_store_bindings=(
            ExpertVectorStoreBindingDefinition(
                vector_store_id=KANSAS_COURT_DECISIONS_VECTOR_STORE_ID,
                tenant_id=KS_STATE_CIVICS_TENANT_ID,
                business_instance_id=KS_STATE_CIVICS_BUSINESS_INSTANCE_ID,
                allowed_graph_lens_ids=("court_citator", "court_procedural_history"),
            ),
        ),
        citation_policy=_RETRIEVED_CORPUS_CITATION_POLICY,
        caveats=(
            "Graph relationships reflect the loaded artifact and are not a proven full-corpus legal citator.",
            "Answers are retrieval-grounded research assistance, not legal advice.",
        ),
        model_policy=_DEFAULT_MODEL_POLICY,
        tool_limits=_DEFAULT_TOOL_LIMITS,
    ),
    ExpertProfileDefinition(
        id="topeka-municipal-code",
        label="Topeka Municipal Code Expert",
        description="Answers questions from the codified Topeka Municipal Code and linked ordinance-history corpus.",
        system_prompt=(
            "You are the ExAIS Topeka municipal-code expert. Answer only from material retrieved from the bound "
            "municipal-code vector store. Preserve the returned document citation URL and label hierarchy, "
            "cross-reference, definition, and ordinance-history relationships accurately."
        ),
        vector_store_bindings=(
            ExpertVectorStoreBindingDefinition(
                vector_store_id=TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID,
                tenant_id=KS_STATE_CIVICS_TENANT_ID,
                business_instance_id=KS_STATE_CIVICS_BUSINESS_INSTANCE_ID,
                allowed_graph_lens_ids=(
                    "municipal_code_structure",
                    "municipal_code_cross_reference",
                    "municipal_code_history",
                ),
            ),
        ),
        citation_policy=_RETRIEVED_CORPUS_CITATION_POLICY,
        caveats=(
            "Graph relationships are limited to the loaded Topeka source artifact.",
            "Ordinance-history links do not by themselves establish the current legal effect of an ordinance.",
        ),
        model_policy=_DEFAULT_MODEL_POLICY,
        tool_limits=_DEFAULT_TOOL_LIMITS,
    ),
)


def expert_profile_definition(expert_id: str) -> ExpertProfileDefinition | None:
    normalized = str(expert_id or "").strip().lower()
    return next((profile for profile in EXPERT_PROFILE_REGISTRY if profile.id == normalized), None)


def _binding_is_in_principal_scope(binding: ExpertVectorStoreBindingDefinition, principal: Principal) -> bool:
    return (
        binding.tenant_id == principal.tenant_id
        and binding.business_instance_id == principal.business_instance_id
    )


def _resolved_graph_lenses(
    definition: ExpertProfileDefinition,
    binding: ExpertVectorStoreBindingDefinition,
    attributes: dict,
) -> list[ExpertGraphLens]:
    supported = {
        lens.id: lens
        for lens in search_lens_definitions_for_vector_store(attributes, query_planner_profile_id=None)
        if lens.kind == "graph"
    }
    unsupported = [lens_id for lens_id in binding.allowed_graph_lens_ids if lens_id not in supported]
    if unsupported:
        raise ExpertProfileConfigurationError(
            f"expert profile {definition.id!r} has graph lenses unsupported by its bound vector store"
        )
    return [
        ExpertGraphLens(
            id=supported[lens_id].id,
            label=supported[lens_id].label,
            description=supported[lens_id].description,
            graph_profile_id=supported[lens_id].graph_profile_id,
            relation_types=list(supported[lens_id].relation_types),
            input_schema=supported[lens_id].input_schema,
            caveats=list(supported[lens_id].caveats),
        )
        for lens_id in binding.allowed_graph_lens_ids
    ]


def resolve_expert_profile(db: Session, principal: Principal, expert_id: str) -> ExpertProfile:
    """Resolve an expert only when every registered store binding is in principal scope and active."""

    definition = expert_profile_definition(expert_id)
    if definition is None:
        raise ExpertProfileNotFoundError("Expert profile not found")

    if not definition.vector_store_bindings or any(
        not _binding_is_in_principal_scope(binding, principal)
        for binding in definition.vector_store_bindings
    ):
        raise ExpertProfileNotFoundError("Expert profile not found")

    vector_stores: list[ExpertVectorStoreBinding] = []
    repository = VectorStoreRepository()
    for binding in definition.vector_store_bindings:
        try:
            require_active_vector_store(db, principal, binding.vector_store_id)
        except VectorStoreUnavailableError as exc:
            raise ExpertProfileNotFoundError("Expert profile not found") from exc
        store = repository.get(db, principal, binding.vector_store_id)
        if store is None:
            raise ExpertProfileNotFoundError("Expert profile not found")
        graph_lenses = _resolved_graph_lenses(definition, binding, store.attributes)
        vector_stores.append(
            ExpertVectorStoreBinding(
                vector_store_id=store.id,
                name=store.name or store.id,
                corpus_kind=(
                    str(store.attributes.get("corpus") or store.attributes.get("source_collection") or "").strip()
                    or None
                ),
                graph_lenses=graph_lenses,
            )
        )

    return ExpertProfile(
        id=definition.id,
        label=definition.label,
        description=definition.description,
        system_prompt=definition.system_prompt,
        vector_stores=vector_stores,
        graph_lens_policy=ExpertGraphLensPolicy(
            allow_automatic_selection=definition.allow_automatic_graph_lens_selection,
            allowed_lens_ids=[
                lens.id
                for vector_store in vector_stores
                for lens in vector_store.graph_lenses
            ],
        ),
        citation_policy=definition.citation_policy.model_copy(deep=True),
        caveats=list(definition.caveats),
        model_policy=definition.model_policy.model_copy(deep=True),
        tool_limits=definition.tool_limits.model_copy(deep=True),
    )


def list_expert_profiles(db: Session, principal: Principal) -> ExpertProfileListResponse:
    """List only profiles whose complete binding set is visible to the principal."""

    profiles: list[ExpertProfile] = []
    for definition in EXPERT_PROFILE_REGISTRY:
        try:
            profiles.append(resolve_expert_profile(db, principal, definition.id))
        except ExpertProfileNotFoundError:
            continue
    return ExpertProfileListResponse(
        data=profiles,
        first_id=profiles[0].id if profiles else None,
        last_id=profiles[-1].id if profiles else None,
    )
