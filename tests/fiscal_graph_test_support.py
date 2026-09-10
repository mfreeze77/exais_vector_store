from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from svs_common.fiscal_graph import FISCAL_SCHEMA_VERSION, fiscal_edge_id, fiscal_node_id
from svs_common.schemas import ChunkRecord


def _uuid(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"exais-fiscal-test:{name}"))


def graph_payload(vector_store_id="vs_fiscal_test", run_id=None, artifact_class="reviewed_public") -> dict:
    run_id = run_id or _uuid("run")
    nodes = []
    for index, node_type in enumerate((
        "enacted_provision", "appropriation_action", "budget_account", "agency", "fund", "fiscal_document"
    )):
        revision = _uuid(f"revision:{node_type}")
        attrs = {
            "fiscal_schema_version": FISCAL_SCHEMA_VERSION,
            "fiscal_artifact_class": artifact_class,
            "fiscal_derivation_run_id": run_id,
            "fiscal_entity_id": _uuid(f"entity:{node_type}"),
            "fiscal_entity_sha256": f"{index + 1:x}" * 64,
            "fiscal_logical_document_id": f"{index + 7:x}" * 64,
            "fiscal_source_revision_id": revision,
            "fiscal_source_content_hash_sha256": f"{index + 10:x}" * 64,
            "fiscal_source_span_id": _uuid(f"span:{node_type}"),
            "fiscal_chunk_id": f"chk_fiscal_{index}",
            "fiscal_year": 2026,
            "fiscal_bill_version_id": _uuid("bill-version") if node_type in {"enacted_provision", "appropriation_action"} else None,
            "fiscal_publication_status": "published",
            "visibility": "public",
        }
        if node_type == "enacted_provision":
            attrs["fiscal_entity_id"] = attrs["fiscal_source_span_id"]
        elif node_type == "fiscal_document":
            attrs["fiscal_entity_id"] = revision
        nodes.append({"id": fiscal_node_id(vector_store_id, node_type, attrs), "type": node_type,
                      "label": node_type.replace("_", " ").title(), "attributes": attrs})
    by_type = {node["type"]: node for node in nodes}
    specifications = (
        ("contains_appropriation", "enacted_provision", "appropriation_action"),
        ("targets_account", "appropriation_action", "budget_account"),
        ("account_of_agency", "budget_account", "agency"),
        ("account_in_fund", "budget_account", "fund"),
        ("documented_by", "appropriation_action", "fiscal_document"),
    )
    edges = []
    for index, (edge_type, source_type, target_type) in enumerate(specifications):
        source, target = by_type[source_type], by_type[target_type]
        attrs = {
            "fiscal_schema_version": FISCAL_SCHEMA_VERSION,
            "fiscal_artifact_class": artifact_class,
            "fiscal_derivation_run_id": run_id,
            "fiscal_relationship_id": _uuid(f"relationship:{edge_type}"),
            "fiscal_relationship_sha256": f"{index + 1:x}" * 64,
            "fiscal_review_status": "accepted",
            "fiscal_publication_allowed": True,
            "fiscal_year": 2026,
            "visibility": "public",
            "evidence_citation_ids": [source["attributes"]["fiscal_source_span_id"], target["attributes"]["fiscal_source_span_id"]],
        }
        edges.append({"id": fiscal_edge_id(vector_store_id, edge_type, source["id"], target["id"], attrs),
                      "type": edge_type, "source": source["id"], "target": target["id"], "attributes": attrs})
    return {"nodes": nodes, "edges": edges, "replace": False, "dry_run": True}


def chunk_for_node(node) -> ChunkRecord:
    attrs = node["attributes"] if isinstance(node, dict) else node.attributes
    return ChunkRecord(id=attrs["fiscal_chunk_id"], document_id=f"doc_{attrs['fiscal_chunk_id']}",
                       document_version_id=f"ver_{attrs['fiscal_chunk_id']}", ordinal=0,
                       text=f"Synthetic evidence for {node['type'] if isinstance(node, dict) else node.type}",
                       security_level=0, classification="public",
                       citation={"file_id": f"doc_{attrs['fiscal_chunk_id']}"})
