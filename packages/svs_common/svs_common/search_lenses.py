from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal

from .query_planner import KANSAS_CIVICS_LEGAL_PROFILE_ID


SearchLensKind = Literal["semantic", "graph"]

DEFAULT_SEARCH_LENS_ID = "semantic"
KSCOURTS_GRAPH_HANDLER_ID = "kscourts_postgres_graph_v1"
TOPEKA_GRAPH_HANDLER_ID = "topeka_municipal_code_postgres_graph_v1"
KSCOURTS_CORPUS_KIND = "kansas_court_decisions"
TOPEKA_CORPUS_KIND = "topeka_municipal_code"


@dataclass(frozen=True)
class SearchLensDefinition:
    id: str
    label: str
    description: str
    kind: SearchLensKind
    corpus_kinds: tuple[str, ...] = ("*",)
    requires_graph: bool = False
    graph_profile_id: str | None = None
    handler_id: str | None = None
    relation_types: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    caveats: tuple[str, ...] = ()


def _object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required),
    }


SEARCH_LENS_REGISTRY: tuple[SearchLensDefinition, ...] = (
    SearchLensDefinition(
        id=DEFAULT_SEARCH_LENS_ID,
        label="Semantic Search",
        description="Default hybrid semantic and sparse text search with source citations.",
        kind="semantic",
        input_schema=_object_schema({}),
    ),
    SearchLensDefinition(
        id="court_citator",
        label="Court Citator",
        description="Expands from Kansas court opinions to cited authority, citing opinions, same-docket opinions, and related-party opinions.",
        kind="graph",
        corpus_kinds=(KSCOURTS_CORPUS_KIND,),
        requires_graph=True,
        graph_profile_id=KSCOURTS_GRAPH_HANDLER_ID,
        handler_id=KSCOURTS_GRAPH_HANDLER_ID,
        relation_types=("cited_by", "cited_authority", "same_docket", "related_party"),
        input_schema=_object_schema({
            "case_title": {"type": "string", "description": "Canonical or common case title, for example State v. Harris."},
            "docket_number": {"type": "string", "description": "Kansas appellate docket number when known."},
            "court": {"type": "string", "description": "Optional court filter text."},
            "decision_year": {"type": "string", "description": "Optional decision year when known."},
            "relationship": {
                "type": "string",
                "enum": ["all", "cited_by", "cites", "cited_authority", "same_docket", "related_party"],
                "description": "Optional graph relationship focus.",
            },
        }),
        caveats=(
            "This is graph-backed relationship evidence, not legal advice.",
            "Do not treat this lens as a complete citator unless coverage.full_corpus_citator is true.",
        ),
    ),
    SearchLensDefinition(
        id="court_procedural_history",
        label="Court Procedural History",
        description="Focuses Kansas court GraphRAG expansion on same-docket opinion relationships.",
        kind="graph",
        corpus_kinds=(KSCOURTS_CORPUS_KIND,),
        requires_graph=True,
        graph_profile_id=KSCOURTS_GRAPH_HANDLER_ID,
        handler_id=KSCOURTS_GRAPH_HANDLER_ID,
        relation_types=("same_docket",),
        input_schema=_object_schema({
            "case_title": {"type": "string", "description": "Canonical or common case title."},
            "docket_number": {"type": "string", "description": "Kansas appellate docket number when known."},
            "decision_year": {"type": "string", "description": "Optional decision year when known."},
        }),
        caveats=(
            "Same-docket graph links depend on the loaded graph artifact and may not include every procedural event.",
        ),
    ),
    SearchLensDefinition(
        id="municipal_code_structure",
        label="Municipal Code Structure",
        description="Expands Topeka code results through title, chapter, article, appendix, and section hierarchy.",
        kind="graph",
        corpus_kinds=(TOPEKA_CORPUS_KIND,),
        requires_graph=True,
        graph_profile_id=TOPEKA_GRAPH_HANDLER_ID,
        handler_id=TOPEKA_GRAPH_HANDLER_ID,
        relation_types=("CONTAINS",),
        input_schema=_object_schema({
            "citation": {"type": "string", "description": "Municipal code citation, for example TMC 8.60.150."},
            "title": {"type": "string", "description": "Optional title identifier."},
            "chapter": {"type": "string", "description": "Optional chapter identifier."},
            "section": {"type": "string", "description": "Optional section identifier."},
        }),
        caveats=("This lens uses the loaded Topeka municipal-code graph artifact and only reports relationships present in that artifact.",),
    ),
    SearchLensDefinition(
        id="municipal_code_cross_reference",
        label="Municipal Code Cross Reference",
        description="Expands Topeka code results through referenced sections, definitions, penalties, and see-also relationships.",
        kind="graph",
        corpus_kinds=(TOPEKA_CORPUS_KIND,),
        requires_graph=True,
        graph_profile_id=TOPEKA_GRAPH_HANDLER_ID,
        handler_id=TOPEKA_GRAPH_HANDLER_ID,
        relation_types=("REFERENCES", "DEFINES"),
        input_schema=_object_schema({
            "citation": {"type": "string", "description": "Municipal code citation, for example TMC 8.60.150."},
            "term": {"type": "string", "description": "Optional defined term or topic."},
        }),
        caveats=("This lens uses extracted internal code references and definitions; it is not a full outside-law citator.",),
    ),
    SearchLensDefinition(
        id="municipal_code_history",
        label="Municipal Code History",
        description="Expands Topeka code results through ordinance adoption and amendment history.",
        kind="graph",
        corpus_kinds=(TOPEKA_CORPUS_KIND,),
        requires_graph=True,
        graph_profile_id=TOPEKA_GRAPH_HANDLER_ID,
        handler_id=TOPEKA_GRAPH_HANDLER_ID,
        relation_types=("HAS_ORDINANCE_HISTORY", "ORDINANCE_AMENDS_SECTION"),
        input_schema=_object_schema({
            "citation": {"type": "string", "description": "Municipal code citation, for example TMC 8.60.150."},
            "ordinance_number": {"type": "string", "description": "Optional ordinance number."},
        }),
        caveats=("This lens links codified section history to official ordinance PDFs where the artifact contains a matching ordinance number.",),
    ),
)


SEARCH_LENS_ALIASES = {
    "default": DEFAULT_SEARCH_LENS_ID,
    "vector": DEFAULT_SEARCH_LENS_ID,
    "hybrid": DEFAULT_SEARCH_LENS_ID,
    "ks_court_citator": "court_citator",
    "legal_citator": "court_citator",
}


def normalize_search_lens_id(value: str | None) -> str:
    if value is None:
        return DEFAULT_SEARCH_LENS_ID
    normalized = value.strip().lower().replace("-", "_")
    return SEARCH_LENS_ALIASES.get(normalized, normalized)


def infer_expert_search_lens_id(query: str, allowed_lens_ids: list[str] | tuple[str, ...]) -> str | None:
    """Infer only an explicitly profile-authorized graph lens from natural language."""

    allowed = {normalize_search_lens_id(value) for value in allowed_lens_ids}
    text = " ".join(str(query or "").lower().split())
    candidates: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("court_citator", ("cited by", "cites ", "citation history", "citator", "precedent", "related authority")),
        ("court_procedural_history", ("procedural history", "same docket", "earlier opinion", "later opinion")),
        ("municipal_code_history", ("ordinance history", "amendment history", "amended by", "adopted by", "ordinance number")),
        ("municipal_code_cross_reference", ("cross reference", "cross-reference", "defined term", "definition of", "references section")),
        ("municipal_code_structure", ("code structure", "contained in", "parent chapter", "parent title", "section hierarchy")),
    )
    for lens_id, phrases in candidates:
        if lens_id in allowed and any(phrase in text for phrase in phrases):
            return lens_id
    return None


def corpus_kind_for_vector_store(attributes: dict[str, Any] | None, query_planner_profile_id: str | None) -> str | None:
    attrs = attributes or {}
    source_collection = str(attrs.get("source_collection") or "").strip().lower()
    corpus = str(attrs.get("corpus") or "").strip().lower()
    if (
        source_collection == "kscourts-decisions"
        or corpus in {"kscourts_decisions", "kansas_court_decisions", "ks_courts"}
    ):
        return KSCOURTS_CORPUS_KIND
    if (
        source_collection in {"topeka-municipal-code", "topeka-codified-code"}
        or corpus in {"topeka_municipal_code", "topeka-code", "topeka_code"}
    ):
        return TOPEKA_CORPUS_KIND
    if query_planner_profile_id == KANSAS_CIVICS_LEGAL_PROFILE_ID:
        return None
    return None


def _lens_applies(definition: SearchLensDefinition, corpus_kind: str | None) -> bool:
    return "*" in definition.corpus_kinds or (corpus_kind is not None and corpus_kind in definition.corpus_kinds)


def search_lens_definitions_for_vector_store(
    attributes: dict[str, Any] | None,
    *,
    query_planner_profile_id: str | None,
) -> tuple[SearchLensDefinition, ...]:
    """Return the single registry's ordered, store-supported lens definitions."""

    corpus_kind = corpus_kind_for_vector_store(attributes, query_planner_profile_id)
    return tuple(
        definition
        for definition in SEARCH_LENS_REGISTRY
        if _lens_applies(definition, corpus_kind)
    )


def _graph_count(coverage: dict[str, Any], key: str) -> int:
    value = coverage.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def _normalized_coverage(attributes: dict[str, Any] | None, graph_coverage: dict[str, Any] | None) -> dict[str, Any]:
    attrs = attributes or {}
    coverage = dict(graph_coverage or {})
    coverage.setdefault("documents_indexed", 0)
    coverage.setdefault("active_chunks", 0)
    coverage.setdefault("node_count", 0)
    coverage.setdefault("edge_count", 0)
    coverage.setdefault("node_type_counts", {})
    coverage.setdefault("edge_type_counts", {})
    if "full_corpus_citator" not in coverage:
        coverage["full_corpus_citator"] = bool(
            attrs.get("full_corpus_citator")
            or attrs.get("graph_full_corpus_citator")
            or attrs.get("graph_full_corpus")
        )
    for attr_key in ("graph_built_at", "graph_loaded_at", "graph_artifact_built_at"):
        if attr_key in attrs and attrs[attr_key] and "last_built_at" not in coverage:
            coverage["last_built_at"] = attrs[attr_key]
    return coverage


def _lens_status(definition: SearchLensDefinition, graph_enabled: bool, coverage: dict[str, Any]) -> str:
    if not definition.requires_graph:
        return "available"
    if not definition.handler_id:
        return "planned"
    if not graph_enabled:
        return "disabled"
    if _graph_count(coverage, "node_count") <= 0 or _graph_count(coverage, "edge_count") <= 0:
        return "empty"
    return "available"


def _lens_warnings(definition: SearchLensDefinition, status: str, coverage: dict[str, Any]) -> list[str]:
    warnings = list(definition.caveats)
    if status == "disabled":
        warnings.append("GraphRAG is disabled for this vector store runtime.")
    elif status == "empty":
        warnings.append("GraphRAG tables contain no loaded graph coverage for this vector store.")
    elif status == "planned":
        warnings.append("This graph lens is declared for the corpus but does not have an API search handler yet.")
    if definition.id == "court_citator" and not coverage.get("full_corpus_citator"):
        warnings.append("Coverage is the loaded citation graph artifact, not a proven full-corpus Kansas citator.")
    return warnings


def search_lens_payload(
    definition: SearchLensDefinition,
    *,
    attributes: dict[str, Any] | None = None,
    graph_enabled: bool = False,
    graph_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = _normalized_coverage(attributes, graph_coverage) if definition.requires_graph else {}
    status = _lens_status(definition, graph_enabled, coverage)
    return {
        "id": definition.id,
        "label": definition.label,
        "description": definition.description,
        "kind": definition.kind,
        "status": status,
        "requires_graph": definition.requires_graph,
        "graph_profile_id": definition.graph_profile_id,
        "relation_types": list(definition.relation_types),
        "input_schema": copy.deepcopy(definition.input_schema),
        "coverage": coverage,
        "warnings": _lens_warnings(definition, status, coverage),
    }


def search_lenses_for_vector_store(
    attributes: dict[str, Any] | None,
    *,
    query_planner_profile_id: str | None,
    graph_enabled: bool,
    graph_coverage: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [
        search_lens_payload(
            definition,
            attributes=attributes,
            graph_enabled=graph_enabled,
            graph_coverage=graph_coverage,
        )
        for definition in search_lens_definitions_for_vector_store(
            attributes,
            query_planner_profile_id=query_planner_profile_id,
        )
    ]


def search_lens_definition(lens_id: str | None) -> SearchLensDefinition | None:
    normalized = normalize_search_lens_id(lens_id)
    return next((definition for definition in SEARCH_LENS_REGISTRY if definition.id == normalized), None)


def resolve_search_lens(
    lens_id: str | None,
    attributes: dict[str, Any] | None,
    *,
    query_planner_profile_id: str | None,
    graph_enabled: bool,
    graph_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_search_lens_id(lens_id)
    lenses = search_lenses_for_vector_store(
        attributes,
        query_planner_profile_id=query_planner_profile_id,
        graph_enabled=graph_enabled,
        graph_coverage=graph_coverage,
    )
    for lens in lenses:
        if lens["id"] != normalized:
            continue
        if lens["status"] != "available":
            raise ValueError(f"search lens {normalized!r} is {lens['status']} for this vector store")
        return lens
    raise ValueError(f"search lens {normalized!r} is not supported for this vector store")


def search_lens_relation_types(lens_id: str | None, inputs: dict[str, Any] | None = None) -> tuple[str, ...]:
    definition = search_lens_definition(lens_id)
    if definition is None:
        return ()
    relation_types = definition.relation_types
    relationship = (inputs or {}).get("relationship")
    if relationship is None or str(relationship).strip().lower() == "all":
        return relation_types
    requested = str(relationship).strip().lower()
    if requested == "cites":
        requested = "cited_authority"
    if requested not in relation_types:
        raise ValueError(f"relationship {requested!r} is not supported by search lens {definition.id!r}")
    return (requested,)


def search_query_with_lens_inputs(
    query: str | list[str],
    lens_id: str | None,
    inputs: dict[str, Any] | None = None,
) -> str | list[str]:
    if not inputs:
        return query
    definition = search_lens_definition(lens_id)
    if definition is None:
        return query
    additions: list[str] = []
    if definition.id.startswith("court_"):
        for key in ("case_title", "docket_number", "court", "decision_year"):
            value = inputs.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            additions.append(f"docket {value.strip()}" if key == "docket_number" else value.strip())
    elif definition.id.startswith("municipal_code_"):
        for key in ("citation", "title", "chapter", "section", "ordinance_number", "term"):
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                additions.append(value.strip())

    if not additions:
        return query

    def extend_one(value: str) -> str:
        text = value
        lowered = text.lower()
        for addition in additions:
            if addition.lower() not in lowered:
                text = f"{text} {addition}".strip()
                lowered = text.lower()
        return text

    if isinstance(query, list):
        return [extend_one(query[0]), *query[1:]]
    return extend_one(query)
