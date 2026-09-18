"""Canonical Ghidra export records and deterministic binary graph projection.

This module deliberately separates semantic retrieval payloads from structural
program relationships.  Ghidra is the source of binary-analysis facts; ExAIS
stores a bounded, deterministic projection that agents can retrieve and audit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import VectorStoreGraphLoadRequest

GHIDRA_EXPORT_SCHEMA_VERSION = "exais.ghidra-export.v1"
BINARY_CORPUS_KIND = "binary_analysis"
BINARY_GRAPH_HANDLER_ID = "ghidra_binary_graph_v1"
BINARY_PROFILE_ID = "binary-analysis.ghidra.v1"

BINARY_RELATIONS = (
    "CONTAINS",
    "CALLS",
    "REFERENCES_STRING",
    "IMPORTS_API",
    "READS_GLOBAL",
    "WRITES_GLOBAL",
    "USES_TYPE",
    "SIMILAR_TO",
    "CHANGED_TO",
)
BINARY_FUNCTION_RELATIONS = ("CALLS", "SIMILAR_TO", "CHANGED_TO")
BINARY_NODE_TYPES = frozenset({"binary", "function", "string", "import", "global", "datatype"})
MAX_BINARY_GRAPH_NODES = 100_000
MAX_BINARY_GRAPH_EDGES = 500_000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS_RE = re.compile(r"^(?:0x)?[0-9A-Fa-f]+$")
_ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,512}$")


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _bounded_text(value: Any, *, limit: int = 16_384) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[:limit]
    return text


def _normalized_list(values: list[str], *, limit: int = 10_000) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values[:limit]:
        text = _bounded_text(value, limit=2048)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


class GhidraBinaryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    path: str | None = Field(default=None, max_length=4096)
    executable_format: str | None = Field(default=None, max_length=1024)
    language_id: str | None = Field(default=None, max_length=1024)
    compiler_spec_id: str | None = Field(default=None, max_length=1024)
    image_base: str | None = Field(default=None, max_length=128)
    min_address: str | None = Field(default=None, max_length=128)
    max_address: str | None = Field(default=None, max_length=128)


class GhidraStringReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str = Field(min_length=1, max_length=16_384)
    address: str | None = Field(default=None, max_length=128)


class GhidraFunctionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=2048)
    address: str = Field(min_length=1, max_length=128)
    namespace: str | None = Field(default=None, max_length=2048)
    signature: str | None = Field(default=None, max_length=8192)
    calling_convention: str | None = Field(default=None, max_length=256)
    size: int = Field(default=0, ge=0)
    instruction_count: int = Field(default=0, ge=0)
    callers: list[str] = Field(default_factory=list, max_length=10_000)
    callees: list[str] = Field(default_factory=list, max_length=10_000)
    strings: list[GhidraStringReference] = Field(default_factory=list, max_length=10_000)
    imports: list[str] = Field(default_factory=list, max_length=10_000)
    reads_globals: list[str] = Field(default_factory=list, max_length=10_000)
    writes_globals: list[str] = Field(default_factory=list, max_length=10_000)
    types: list[str] = Field(default_factory=list, max_length=10_000)
    decompilation: str | None = Field(default=None, max_length=2_000_000)
    decompilation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    decompile_error: str | None = Field(default=None, max_length=4096)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        value = value.strip()
        if not _ID_RE.fullmatch(value):
            raise ValueError("function id contains control characters or is too long")
        return value

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        value = value.strip()
        if not _ADDRESS_RE.fullmatch(value):
            raise ValueError("function address must be hexadecimal")
        return value.lower() if value.lower().startswith("0x") else f"0x{value.lower()}"

    @field_validator("callers", "callees", "imports", "reads_globals", "writes_globals", "types")
    @classmethod
    def normalize_string_lists(cls, value: list[str]) -> list[str]:
        return _normalized_list(value)

    @model_validator(mode="after")
    def bind_decompilation_hash(self):
        if self.decompilation:
            digest = sha256(self.decompilation.encode("utf-8")).hexdigest()
            if self.decompilation_sha256 and self.decompilation_sha256 != digest:
                raise ValueError("decompilation_sha256 does not match decompilation")
            self.decompilation_sha256 = digest
        return self


class GhidraProgramExport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[GHIDRA_EXPORT_SCHEMA_VERSION]
    ghidra_version: str = Field(min_length=1, max_length=256)
    generated_at: str = Field(min_length=1, max_length=128)
    binary: GhidraBinaryInfo
    functions: list[GhidraFunctionRecord] = Field(default_factory=list, max_length=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        normalized = value.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("generated_at must be ISO-8601") from exc
        return value

    @model_validator(mode="after")
    def validate_function_id_uniqueness(self):
        ids = [function.id for function in self.functions]
        if len(ids) != len(set(ids)):
            raise ValueError("Ghidra export contains duplicate function ids")
        return self


class BinarySimilarityMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    old_function_id: str = Field(min_length=1, max_length=512)
    new_function_id: str = Field(min_length=1, max_length=512)
    score: float = Field(ge=0.0, le=1.0)
    method: str = Field(default="bsim", min_length=1, max_length=128)


def parse_ghidra_export(value: str | bytes | dict[str, Any] | GhidraProgramExport) -> GhidraProgramExport:
    if isinstance(value, GhidraProgramExport):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    if isinstance(value, str):
        parsed = json.loads(value)
    elif isinstance(value, dict):
        parsed = value
    else:
        raise TypeError("Ghidra export must be JSON text, bytes, mapping, or GhidraProgramExport")
    return GhidraProgramExport.model_validate(parsed)


def canonical_export_json(value: str | bytes | dict[str, Any] | GhidraProgramExport) -> str:
    export = parse_ghidra_export(value)
    return json.dumps(export.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def function_semantic_text(binary: GhidraBinaryInfo, function: GhidraFunctionRecord) -> str:
    """Render one function as an embedding/search document while retaining exact identity."""
    lines = [
        f"Binary: {binary.name}",
        f"Binary SHA-256: {binary.sha256}",
        f"Function ID: {function.id}",
        f"Function: {function.name}",
        f"Address: {function.address}",
    ]
    if function.namespace:
        lines.append(f"Namespace: {function.namespace}")
    if function.signature:
        lines.append(f"Signature: {function.signature}")
    if function.calling_convention:
        lines.append(f"Calling convention: {function.calling_convention}")
    lines.extend([
        f"Size: {function.size} bytes",
        f"Instruction count: {function.instruction_count}",
    ])
    if function.callers:
        lines.append("Callers: " + ", ".join(function.callers))
    if function.callees:
        lines.append("Callees: " + ", ".join(function.callees))
    if function.imports:
        lines.append("Imported APIs: " + ", ".join(function.imports))
    if function.reads_globals:
        lines.append("Reads globals: " + ", ".join(function.reads_globals))
    if function.writes_globals:
        lines.append("Writes globals: " + ", ".join(function.writes_globals))
    if function.types:
        lines.append("Data types: " + ", ".join(function.types))
    if function.strings:
        lines.append("Referenced strings:")
        for item in function.strings[:200]:
            address = f" @ {item.address}" if item.address else ""
            lines.append(f"- {item.value}{address}")
    if function.decompile_error:
        lines.append(f"Decompiler status: {function.decompile_error}")
    if function.decompilation:
        lines.extend(["", "Decompiled function:", function.decompilation])
    return "\n".join(lines).strip()


def binary_node_id(vector_store_id: str, binary_sha256: str) -> str:
    return f"ghidra:binary:{binary_sha256}"


def function_node_id(vector_store_id: str, binary_sha256: str, function_id: str) -> str:
    digest = _sha(f"{binary_sha256}\x00{function_id}")[:40]
    return f"ghidra:function:{digest}"


def value_node_id(node_type: str, binary_sha256: str, value: str) -> str:
    digest = _sha(f"{binary_sha256}\x00{node_type}\x00{value}")[:40]
    return f"ghidra:{node_type}:{digest}"


def edge_id(edge_type: str, source: str, target: str, discriminator: str = "") -> str:
    digest = _sha(f"{edge_type}\x00{source}\x00{target}\x00{discriminator}")[:48]
    return f"ghidra:edge:{digest}"


def _node(node_id: str, node_type: str, label: str, attributes: dict[str, Any]) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "label": _bounded_text(label, limit=4096), "attributes": attributes}


def _edge(edge_type: str, source: str, target: str, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    attrs = dict(attributes or {})
    attrs.setdefault("schema_version", GHIDRA_EXPORT_SCHEMA_VERSION)
    return {
        "id": edge_id(edge_type, source, target, json.dumps(attrs, sort_keys=True, default=str)),
        "type": edge_type,
        "source": source,
        "target": target,
        "attributes": attrs,
    }


def build_binary_graph(
    value: str | bytes | dict[str, Any] | GhidraProgramExport,
    vector_store_id: str,
    *,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    export = parse_ghidra_export(value)
    binary_sha = export.binary.sha256
    bin_id = binary_node_id(vector_store_id, binary_sha)
    nodes: list[dict[str, Any]] = [
        _node(
            bin_id,
            "binary",
            export.binary.name,
            {
                "schema_version": GHIDRA_EXPORT_SCHEMA_VERSION,
                "binary_sha256": binary_sha,
                "binary_name": export.binary.name,
                "size_bytes": export.binary.size_bytes,
                "ghidra_version": export.ghidra_version,
                "language_id": export.binary.language_id,
                "compiler_spec_id": export.binary.compiler_spec_id,
                "executable_format": export.binary.executable_format,
            },
        )
    ]
    edges: list[dict[str, Any]] = []
    function_ids = {function.id for function in export.functions}
    fn_node_ids = {
        function.id: function_node_id(vector_store_id, binary_sha, function.id)
        for function in export.functions
    }

    value_nodes: dict[str, dict[str, Any]] = {}

    def ensure_value_node(
        node_type: str,
        identity_value: str,
        *,
        label: str | None = None,
        value: str | None = None,
        address: str | None = None,
    ) -> str:
        node_id = value_node_id(node_type, binary_sha, identity_value)
        if node_id not in value_nodes:
            attrs: dict[str, Any] = {
                "schema_version": GHIDRA_EXPORT_SCHEMA_VERSION,
                "binary_sha256": binary_sha,
                "value": value if value is not None else identity_value,
            }
            if address is not None:
                attrs["address"] = address
            value_nodes[node_id] = _node(node_id, node_type, label or attrs["value"], attrs)
        return node_id

    for function in export.functions:
        fn_id = fn_node_ids[function.id]
        nodes.append(
            _node(
                fn_id,
                "function",
                function.name,
                {
                    "schema_version": GHIDRA_EXPORT_SCHEMA_VERSION,
                    "binary_sha256": binary_sha,
                    "binary_function_id": function.id,
                    "function_name": function.name,
                    "address": function.address,
                    "signature": function.signature,
                    "namespace": function.namespace,
                    "size": function.size,
                    "instruction_count": function.instruction_count,
                    "decompilation_sha256": function.decompilation_sha256,
                },
            )
        )
        edges.append(_edge("CONTAINS", bin_id, fn_id, {"binary_sha256": binary_sha}))

        for callee in function.callees:
            if callee in function_ids:
                edges.append(
                    _edge(
                        "CALLS",
                        fn_id,
                        fn_node_ids[callee],
                        {"binary_sha256": binary_sha, "source_function_id": function.id, "target_function_id": callee},
                    )
                )
        for ref in function.strings:
            key = f"{ref.address or ''}|{ref.value}"
            target = ensure_value_node(
                "string", key, label=ref.value, value=ref.value, address=ref.address
            )
            edges.append(
                _edge(
                    "REFERENCES_STRING",
                    fn_id,
                    target,
                    {"binary_sha256": binary_sha, "value": ref.value, "address": ref.address},
                )
            )
        for imported in function.imports:
            target = ensure_value_node("import", imported)
            edges.append(_edge("IMPORTS_API", fn_id, target, {"binary_sha256": binary_sha, "value": imported}))
        for global_value in function.reads_globals:
            target = ensure_value_node("global", global_value)
            edges.append(_edge("READS_GLOBAL", fn_id, target, {"binary_sha256": binary_sha, "value": global_value}))
        for global_value in function.writes_globals:
            target = ensure_value_node("global", global_value)
            edges.append(_edge("WRITES_GLOBAL", fn_id, target, {"binary_sha256": binary_sha, "value": global_value}))
        for datatype in function.types:
            target = ensure_value_node("datatype", datatype)
            edges.append(_edge("USES_TYPE", fn_id, target, {"binary_sha256": binary_sha, "value": datatype}))

    nodes.extend(value_nodes.values())
    node_by_id = {node["id"]: node for node in nodes}
    edge_by_id = {edge["id"]: edge for edge in edges}
    return {
        "nodes": list(node_by_id.values()),
        "edges": list(edge_by_id.values()),
        "replace": replace,
        "dry_run": dry_run,
    }


def build_binary_diff_graph(
    old_value: str | bytes | dict[str, Any] | GhidraProgramExport,
    new_value: str | bytes | dict[str, Any] | GhidraProgramExport,
    vector_store_id: str,
    *,
    bsim_matches: list[BinarySimilarityMatch | dict[str, Any]] | None = None,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    old = parse_ghidra_export(old_value)
    new = parse_ghidra_export(new_value)
    combined = build_binary_graph(old, vector_store_id, replace=replace, dry_run=dry_run)
    new_graph = build_binary_graph(new, vector_store_id, replace=False, dry_run=dry_run)
    nodes = {node["id"]: node for node in [*combined["nodes"], *new_graph["nodes"]]}
    edges = {edge["id"]: edge for edge in [*combined["edges"], *new_graph["edges"]]}

    old_by_id = {function.id: function for function in old.functions}
    new_by_id = {function.id: function for function in new.functions}

    old_names = Counter(function.name for function in old.functions)
    new_names = Counter(function.name for function in new.functions)
    new_by_name = {function.name: function for function in new.functions if new_names[function.name] == 1}
    for old_function in old.functions:
        if old_names[old_function.name] != 1 or old_function.name not in new_by_name:
            continue
        new_function = new_by_name[old_function.name]
        source = function_node_id(vector_store_id, old.binary.sha256, old_function.id)
        target = function_node_id(vector_store_id, new.binary.sha256, new_function.id)
        change = _edge(
            "CHANGED_TO",
            source,
            target,
            {
                "schema_version": GHIDRA_EXPORT_SCHEMA_VERSION,
                "old_binary_sha256": old.binary.sha256,
                "new_binary_sha256": new.binary.sha256,
                "match_method": "unique_symbol_name",
                "symbol": old_function.name,
                "decompilation_changed": old_function.decompilation_sha256 != new_function.decompilation_sha256,
            },
        )
        edges[change["id"]] = change

    old_hashes: dict[str, list[GhidraFunctionRecord]] = defaultdict(list)
    new_hashes: dict[str, list[GhidraFunctionRecord]] = defaultdict(list)
    for function in old.functions:
        if function.decompilation_sha256:
            old_hashes[function.decompilation_sha256].append(function)
    for function in new.functions:
        if function.decompilation_sha256:
            new_hashes[function.decompilation_sha256].append(function)
    for digest, old_functions in old_hashes.items():
        new_functions = new_hashes.get(digest, [])
        if len(old_functions) != 1 or len(new_functions) != 1:
            continue
        old_function, new_function = old_functions[0], new_functions[0]
        source = function_node_id(vector_store_id, old.binary.sha256, old_function.id)
        target = function_node_id(vector_store_id, new.binary.sha256, new_function.id)
        similarity = _edge(
            "SIMILAR_TO",
            source,
            target,
            {
                "schema_version": GHIDRA_EXPORT_SCHEMA_VERSION,
                "old_binary_sha256": old.binary.sha256,
                "new_binary_sha256": new.binary.sha256,
                "method": "exact_decompilation_sha256",
                "score": 1.0,
            },
        )
        edges[similarity["id"]] = similarity

    for raw_match in bsim_matches or []:
        match = raw_match if isinstance(raw_match, BinarySimilarityMatch) else BinarySimilarityMatch.model_validate(raw_match)
        if match.old_function_id not in old_by_id or match.new_function_id not in new_by_id:
            raise ValueError("BSim match references a function absent from the supplied exports")
        source = function_node_id(vector_store_id, old.binary.sha256, match.old_function_id)
        target = function_node_id(vector_store_id, new.binary.sha256, match.new_function_id)
        similarity = _edge(
            "SIMILAR_TO",
            source,
            target,
            {
                "schema_version": GHIDRA_EXPORT_SCHEMA_VERSION,
                "old_binary_sha256": old.binary.sha256,
                "new_binary_sha256": new.binary.sha256,
                "method": match.method,
                "score": match.score,
            },
        )
        edges[similarity["id"]] = similarity

    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "replace": replace,
        "dry_run": dry_run,
    }


def validate_binary_graph(req: VectorStoreGraphLoadRequest, vector_store_id: str) -> None:
    if len(req.nodes) > MAX_BINARY_GRAPH_NODES or len(req.edges) > MAX_BINARY_GRAPH_EDGES:
        raise ValueError("Binary graph exceeds bounded load limits")
    if not req.nodes:
        raise ValueError("Binary graph requires at least one node")

    nodes: dict[str, Any] = {}
    for node in req.nodes:
        if node.model_extra or node.properties:
            raise ValueError("Binary graph nodes do not allow uncontrolled fields or properties")
        if node.provenance not in (None, {}, []):
            raise ValueError("Binary graph provenance must be encoded in the canonical attributes")
        if node.id in nodes:
            raise ValueError("Binary graph contains duplicate node ids")
        if node.type not in BINARY_NODE_TYPES:
            raise ValueError("Binary graph contains an unsupported node type")
        attrs = dict(node.attributes or {})
        if attrs.get("schema_version") != GHIDRA_EXPORT_SCHEMA_VERSION:
            raise ValueError("Binary graph node schema version is missing or unsupported")
        binary_sha = attrs.get("binary_sha256")
        if not isinstance(binary_sha, str) or not _SHA256_RE.fullmatch(binary_sha):
            raise ValueError("Binary graph node requires exact binary_sha256")
        if node.type == "binary":
            if node.id != binary_node_id(vector_store_id, binary_sha):
                raise ValueError("Binary graph binary node identity is not canonical")
        elif node.type == "function":
            function_id = attrs.get("binary_function_id")
            if not isinstance(function_id, str) or not _ID_RE.fullmatch(function_id):
                raise ValueError("Binary function node requires a bounded binary_function_id")
            if node.id != function_node_id(vector_store_id, binary_sha, function_id):
                raise ValueError("Binary function node identity is not canonical")
        else:
            value = attrs.get("value")
            if not isinstance(value, str) or not value:
                raise ValueError(f"Binary {node.type} node requires a value")
            identity_value = value
            if node.type == "string":
                address = attrs.get("address")
                if address is not None and not isinstance(address, str):
                    raise ValueError("Binary string address must be text when present")
                identity_value = f"{address or ''}|{value}"
            expected = value_node_id(node.type, binary_sha, identity_value)
            if node.id != expected:
                raise ValueError(f"Binary {node.type} node identity is not canonical")
        nodes[node.id] = node

    relation_matrix = {
        "CONTAINS": {("binary", "function")},
        "CALLS": {("function", "function")},
        "REFERENCES_STRING": {("function", "string")},
        "IMPORTS_API": {("function", "import")},
        "READS_GLOBAL": {("function", "global")},
        "WRITES_GLOBAL": {("function", "global")},
        "USES_TYPE": {("function", "datatype")},
        "SIMILAR_TO": {("function", "function")},
        "CHANGED_TO": {("function", "function")},
    }
    seen_edges: set[str] = set()
    for edge in req.edges:
        if edge.model_extra or edge.properties:
            raise ValueError("Binary graph edges do not allow uncontrolled fields or properties")
        if edge.provenance not in (None, {}, []):
            raise ValueError("Binary graph provenance must be encoded in canonical attributes")
        if edge.id in seen_edges:
            raise ValueError("Binary graph contains duplicate edge ids")
        if edge.type not in BINARY_RELATIONS:
            raise ValueError("Binary graph contains an unsupported relation")
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("Binary graph contains a dangling edge")
        source_type = nodes[edge.source].type
        target_type = nodes[edge.target].type
        if (source_type, target_type) not in relation_matrix[edge.type]:
            raise ValueError("Binary graph relation has incompatible endpoint types")
        attrs = dict(edge.attributes or {})
        if attrs.get("schema_version") != GHIDRA_EXPORT_SCHEMA_VERSION:
            raise ValueError("Binary graph edge schema version is missing or unsupported")
        expected = edge_id(edge.type, edge.source, edge.target, json.dumps(attrs, sort_keys=True, default=str))
        if edge.id != expected:
            raise ValueError("Binary graph edge identity is not canonical")
        seen_edges.add(edge.id)
