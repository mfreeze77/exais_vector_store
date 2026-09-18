"""Agent-facing binary-analysis helpers layered on the shared EXAIS graph tables."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from svs_common.auth import ensure_scope
from svs_common.binary_graph import binary_graph_neighborhood, binary_graph_path
from svs_common.binary_records import (
    BINARY_FUNCTION_RELATIONS,
    BINARY_RELATIONS,
    BinarySimilarityMatch,
    GhidraProgramExport,
    build_binary_diff_graph,
    build_binary_graph,
)
from svs_common.schemas import VectorStoreGraphLoadRequest


class BinaryCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["binary.capabilities"] = "binary.capabilities"
    semantic_mode: str
    graph_profile: str
    semantic_graph_relations: list[str]
    neighborhood_relations: list[str]
    max_path_hops: int
    notes: list[str]


class BinaryGraphPathResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    object: Literal["binary.graph_path"] = "binary.graph_path"
    vector_store_id: str
    found: bool
    hops: int | None = None
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class BinaryNeighborhoodResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    object: Literal["binary.graph_neighborhood"] = "binary.graph_neighborhood"
    vector_store_id: str
    seed: str
    data: list[dict] = Field(default_factory=list)


class BinaryGraphBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vector_store_id: str = Field(min_length=1, max_length=128)
    export: GhidraProgramExport
    replace: bool = False
    dry_run: bool = False


class BinaryGraphDiffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vector_store_id: str = Field(min_length=1, max_length=128)
    old_export: GhidraProgramExport
    new_export: GhidraProgramExport
    bsim_matches: list[BinarySimilarityMatch] = Field(default_factory=list, max_length=100_000)
    replace: bool = False
    dry_run: bool = False


class BinaryGraphPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vector_store_id: str = Field(min_length=1, max_length=128)
    source_binary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_function_id: str = Field(min_length=1, max_length=512)
    target_binary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_function_id: str = Field(min_length=1, max_length=512)
    relation_types: list[str] = Field(default_factory=lambda: list(BINARY_FUNCTION_RELATIONS), min_length=1, max_length=9)
    max_hops: int = Field(default=3, ge=1, le=3)
    direction: Literal["outbound", "inbound", "both"] = "both"


class BinaryNeighborhoodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vector_store_id: str = Field(min_length=1, max_length=128)
    binary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    function_id: str = Field(min_length=1, max_length=512)
    relation_types: list[str] = Field(default_factory=lambda: list(BINARY_RELATIONS), min_length=1, max_length=9)
    limit: int = Field(default=100, ge=1, le=500)


def binary_analysis_router(get_principal, get_db):
    router = APIRouter(prefix="/api/v1/binary", tags=["Binary research"])

    @router.get("/capabilities", response_model=BinaryCapabilitiesResponse)
    def capabilities(principal=Depends(get_principal)):
        ensure_scope(principal, ["retrieval:read", "vector_stores:write"], any_of=True)
        return {
            "object": "binary.capabilities",
            "semantic_mode": "ghidra_binary_v1",
            "graph_profile": "ghidra_binary_graph_v1",
            "semantic_graph_relations": list(BINARY_FUNCTION_RELATIONS),
            "neighborhood_relations": list(BINARY_RELATIONS),
            "max_path_hops": 3,
            "notes": [
                "Normal retrieval graph expansion is one hop by design.",
                "Use /path for explicit two- or three-hop function paths.",
                "Use /neighborhood for strings, imports, globals, and type evidence.",
            ],
        }

    @router.post("/graph/build", response_model=VectorStoreGraphLoadRequest)
    def graph_build(req: BinaryGraphBuildRequest, principal=Depends(get_principal)):
        ensure_scope(principal, "vector_stores:write")
        try:
            return build_binary_graph(req.export, req.vector_store_id, replace=req.replace, dry_run=req.dry_run)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/graph/diff", response_model=VectorStoreGraphLoadRequest)
    def graph_diff(req: BinaryGraphDiffRequest, principal=Depends(get_principal)):
        ensure_scope(principal, "vector_stores:write")
        try:
            return build_binary_diff_graph(
                req.old_export,
                req.new_export,
                req.vector_store_id,
                bsim_matches=req.bsim_matches,
                replace=req.replace,
                dry_run=req.dry_run,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/path", response_model=BinaryGraphPathResponse)
    def path(req: BinaryGraphPathRequest, principal=Depends(get_principal), db=Depends(get_db)):
        ensure_scope(principal, "retrieval:read")
        try:
            return binary_graph_path(
                db,
                principal,
                req.vector_store_id,
                source_binary_sha256=req.source_binary_sha256,
                source_function_id=req.source_function_id,
                target_binary_sha256=req.target_binary_sha256,
                target_function_id=req.target_function_id,
                relation_types=tuple(req.relation_types),
                max_hops=req.max_hops,
                direction=req.direction,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/neighborhood", response_model=BinaryNeighborhoodResponse)
    def neighborhood(req: BinaryNeighborhoodRequest, principal=Depends(get_principal), db=Depends(get_db)):
        ensure_scope(principal, "retrieval:read")
        try:
            return binary_graph_neighborhood(
                db,
                principal,
                req.vector_store_id,
                binary_sha256=req.binary_sha256,
                function_id=req.function_id,
                relation_types=tuple(req.relation_types),
                limit=req.limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
