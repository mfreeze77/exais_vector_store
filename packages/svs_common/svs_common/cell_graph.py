"""Trusted deployment selection of a cell's versioned graph handler.

No request attribute, model output, or YAML import can install executable code.
New domains register reviewed handlers here; cells explicitly bind a profile to
their own tenant, business instance and stores. Existing civics routing is kept.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .grant_graph import GRANT_CORPUS_KIND, GRANT_GRAPH_HANDLER_ID
from .fiscal_graph import FISCAL_CORPUS_KIND, FISCAL_GRAPH_HANDLER_ID
from .schemas import Principal


class GraphBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    tenant_id: str = Field(min_length=1, max_length=128)
    business_instance_id: str = Field(min_length=1, max_length=128)
    vector_store_ids: list[str] = Field(min_length=1, max_length=100)


class CellGraphProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["svs.cell-graph.v1"]
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    handler_id: str
    corpus_kind: str
    binding: GraphBinding
    enabled: bool = False
    max_expansions: int = Field(default=3, ge=0, le=10)
    max_hops: Literal[1] = 1


# Deliberately an allowlist, not a dynamic Python/module-path plugin loader.
GRAPH_HANDLERS = {
    GRANT_GRAPH_HANDLER_ID: GRANT_CORPUS_KIND,
    FISCAL_GRAPH_HANDLER_ID: FISCAL_CORPUS_KIND,
}


def configured_cell_graph_profile() -> CellGraphProfile | None:
    """Read a small operator-owned, read-only-mounted manifest; fail closed.

    An unset path disables new cell profiles. No fallback to another cell or
    handler is allowed when a configured manifest is invalid or unavailable.
    """
    path_value = os.getenv("SVS_CELL_GRAPH_PROFILE_PATH", "")
    if not path_value:
        return None
    try:
        path = Path(path_value)
        if not path.is_absolute():
            raise ValueError("absolute path required")
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("manifest too large")
        profile = CellGraphProfile.model_validate(yaml.safe_load(raw))
        if GRAPH_HANDLERS.get(profile.handler_id) != profile.corpus_kind:
            raise ValueError("unregistered graph handler or corpus")
        stores = profile.binding.vector_store_ids
        if len(set(stores)) != len(stores) or any(
            not value.startswith("vs_") or len(value) > 128 for value in stores
        ):
            raise ValueError("invalid store identities")
        return profile
    except (OSError, ValueError, TypeError, yaml.YAMLError, ValidationError) as exc:
        # Do not expose local paths, YAML contents or credential-like values.
        raise ValueError(
            "Cell graph profile configuration is invalid or unavailable"
        ) from exc


def cell_graph_profile_for_store(
    principal: Principal,
    vector_store_id: str,
    attributes: dict,
) -> CellGraphProfile | None:
    profile = configured_cell_graph_profile()
    if profile is None:
        return None
    binding = profile.binding
    if (
        binding.tenant_id != principal.tenant_id
        or binding.business_instance_id != principal.business_instance_id
        or vector_store_id not in binding.vector_store_ids
        or attributes.get("corpus") != profile.corpus_kind
        or attributes.get("graph_profile_id") != profile.profile_id
    ):
        return None
    return profile
