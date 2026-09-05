"""Opt-in SQL/RLS regression against a disposable, fully migrated PostgreSQL DB.

Never uses DATABASE_URL or a running cell. Set the dedicated test URL only for
an empty throwaway database; fixture writes are additionally rolled back.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from svs_api.main import _load_vector_store_graph
from svs_common.db import set_rls_context
from svs_common.grant_graph import (
    GRANT_RELATIONS,
    expand_grant_graph,
    validate_grant_graph,
)
from svs_common.retrieval import RetrievalService
from svs_common.schemas import ChunkRecord, Principal, VectorStoreGraphLoadRequest

TEST_URL = os.getenv("SVS_GRANT_GRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_URL,
    reason="requires explicitly disposable SVS_GRANT_GRAPH_TEST_DATABASE_URL",
)


@pytest.fixture
def corpus():
    engine = create_engine(TEST_URL)
    with engine.connect() as db:
        transaction = db.begin()
        try:
            assert (
                db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "004_wave125_caller_identity"
            )
            suffix = uuid4().hex
            tenant, business, store, kb = (
                f"t_{suffix}",
                f"b_{suffix}",
                f"vs_{suffix}",
                f"kb_{suffix}",
            )
            scope = {"tenant": tenant, "business": business, "store": store, "kb": kb}
            db.execute(
                text(
                    "INSERT INTO tenants(id,name,slug) VALUES (:tenant,'Synthetic graph test',:tenant)"
                ),
                scope,
            )
            db.execute(
                text(
                    "INSERT INTO business_instances(id,tenant_id,name,slug) VALUES (:business,:tenant,'Synthetic graph test',:business)"
                ),
                scope,
            )
            db.execute(
                text(
                    "INSERT INTO knowledge_bases(id,tenant_id,business_instance_id,name,slug,security_level) VALUES (:kb,:tenant,:business,'Synthetic graph test',:kb,0)"
                ),
                scope,
            )
            db.execute(
                text(
                    "INSERT INTO vector_stores(id,tenant_id,business_instance_id,knowledge_base_id,name) VALUES (:store,:tenant,:business,:kb,'Synthetic graph test')"
                ),
                scope,
            )
            principal = Principal(
                tenant_id=tenant, business_instance_id=business, max_security_level=0
            )
            generation = str(uuid4())
            nodes, documents, chunks = [], [], []
            for kind in ("award", "project", "document"):
                projection_id, entity_id = str(uuid4()), str(uuid4())
                document_id, version_id, chunk_id = (
                    f"doc_{uuid4().hex}",
                    f"ver_{uuid4().hex}",
                    f"chk_{uuid4().hex}",
                )
                attributes = {
                    "gip_generation_id": generation,
                    "gip_search_document_id": projection_id,
                    "gip_entity_id": entity_id,
                    "gip_source_version_sha256": "a" * 64,
                    "gip_citation_id": f"gip:{kind}:{entity_id}:aaaaaaaaaaaaaaaa",
                    "visibility": "public",
                }
                nodes.append(
                    {
                        "id": f"gip:{store}:{generation}:{projection_id}",
                        "type": kind,
                        "attributes": attributes,
                    }
                )
                params = {
                    **scope,
                    "document": document_id,
                    "version": version_id,
                    "chunk": chunk_id,
                    "attrs": json.dumps(
                        {
                            **attributes,
                            "gip_entity_type": kind,
                            "state_code": "KS",
                            "year": 2025,
                        }
                    ),
                }
                db.execute(
                    text("""INSERT INTO documents(id,tenant_id,business_instance_id,knowledge_base_id,vector_store_id,title,content_hash,security_level,classification,current_version_id)
                    VALUES (:document,:tenant,:business,:kb,:store,'Synthetic fixture','hash',0,'public',:version)"""),
                    params,
                )
                db.execute(
                    text("""INSERT INTO document_versions(id,document_id,tenant_id,business_instance_id,version_number,parser_profile_id,vectorization_profile_id,embedding_profile_id,chunking_profile_id,source_content_hash)
                    VALUES (:version,:document,:tenant,:business,1,'test','test','test','test','hash')"""),
                    params,
                )
                db.execute(
                    text("""INSERT INTO chunks(id,tenant_id,business_instance_id,knowledge_base_id,vector_store_id,document_id,document_version_id,ordinal,text,text_hash,security_level,classification)
                    VALUES (:chunk,:tenant,:business,:kb,:store,:document,:version,0,'Synthetic public grant evidence','hash',0,'public')"""),
                    params,
                )
                db.execute(
                    text("""INSERT INTO vector_store_files(id,tenant_id,business_instance_id,vector_store_id,document_id,status,attributes)
                    VALUES (:chunk,:tenant,:business,:store,:document,'completed',CAST(:attrs AS jsonb))"""),
                    params,
                )
                documents.append(document_id)
                chunks.append(chunk_id)
            relationship = str(uuid4())
            edge = {
                "id": f"gip:{store}:{generation}:edge:{relationship}",
                "type": "funds",
                "source": nodes[0]["id"],
                "target": nodes[1]["id"],
                "attributes": {
                    "gip_generation_id": generation,
                    "gip_relationship_id": relationship,
                    "gip_relationship_sha256": "b" * 64,
                    "review_status": "accepted",
                    "visibility": "public",
                    "evidence_citation_ids": [
                        nodes[2]["attributes"]["gip_citation_id"]
                    ],
                },
            }
            request = VectorStoreGraphLoadRequest(
                nodes=nodes, edges=[edge], replace=False
            )
            validate_grant_graph(request, store)
            set_rls_context(db, principal)
            db.execute(text("SET LOCAL ROLE svs_app"))
            role = db.execute(
                text(
                    "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
            ).one()
            assert tuple(role) == (False, False)
            result = _load_vector_store_graph(db, principal, store, request)
            assert result["loaded_nodes"] == 3 and result["loaded_edges"] == 1
            yield {
                "db": db,
                "principal": principal,
                "store": store,
                "kb": kb,
                "generation": generation,
                "nodes": nodes,
                "edge": edge,
                "documents": documents,
                "chunks": chunks,
            }
        finally:
            transaction.rollback()
    engine.dispose()


def expand(
    corpus, *, filters=None, principal=None, store=None, relations=GRANT_RELATIONS
):
    db = corpus["db"]
    principal = principal or corpus["principal"]
    set_rls_context(db, principal)
    service = RetrievalService.__new__(RetrievalService)
    return expand_grant_graph(
        db,
        principal,
        store or corpus["store"],
        [
            ChunkRecord(
                id=corpus["chunks"][0],
                document_id=corpus["documents"][0],
                ordinal=0,
                text="Synthetic seed",
                security_level=0,
                classification="public",
            )
        ],
        filters={
            "file_attribute_filters": {"gip_generation_id": corpus["generation"]},
            **(filters or {}),
        },
        relation_types=relations,
        limit=3,
        hydrate=service._hydrate_and_acl,
    )


def test_real_sql_load_expand_and_citation_under_restricted_role(corpus):
    additions, metadata, summary = expand(corpus)
    assert [chunk.document_id for chunk in additions] == [corpus["documents"][1]]
    assert additions[0].citation["file_id"] == corpus["documents"][1]
    assert (
        metadata[additions[0].id]["relationship_id"]
        == corpus["edge"]["attributes"]["gip_relationship_id"]
    )
    assert summary["applied"] is True


@pytest.mark.parametrize(
    "case",
    [
        "stale_file_generation",
        "stale_node_generation",
        "stale_edge_generation",
        "stale_source_hash",
        "wrong_entity",
        "wrong_citation",
        "stale_document_version",
        "cancelled_file",
        "deleted_document",
        "inactive_chunk",
        "private_chunk",
        "denied_group",
        "denied_role",
        "revoked_edge",
        "malformed_edge",
    ],
)
def test_stale_private_or_unbound_graph_never_expands(corpus, case):
    db = corpus["db"]
    # Simulate version changes/revocation as fixture owner, then restore app role.
    db.execute(text("RESET ROLE"))
    params = {
        "document": corpus["documents"][1],
        "node": corpus["nodes"][1]["id"],
        "edge": corpus["edge"]["id"],
    }
    statements = {
        "stale_file_generation": "UPDATE vector_store_files SET attributes=jsonb_set(attributes,'{gip_generation_id}','\"stale\"') WHERE document_id=:document",
        "stale_node_generation": "UPDATE graph_nodes SET attributes=jsonb_set(attributes,'{gip_generation_id}','\"stale\"') WHERE id=:node",
        "stale_edge_generation": "UPDATE graph_edges SET attributes=jsonb_set(attributes,'{gip_generation_id}','\"stale\"') WHERE id=:edge",
        "stale_source_hash": "UPDATE graph_nodes SET attributes=jsonb_set(attributes,'{gip_source_version_sha256}','\"stale\"') WHERE id=:node",
        "wrong_entity": "UPDATE graph_nodes SET attributes=jsonb_set(attributes,'{gip_entity_id}','\"other\"') WHERE id=:node",
        "wrong_citation": "UPDATE graph_nodes SET attributes=jsonb_set(attributes,'{gip_citation_id}','\"other\"') WHERE id=:node",
        "stale_document_version": "UPDATE documents SET current_version_id='other' WHERE id=:document",
        "cancelled_file": "UPDATE vector_store_files SET status='cancelled' WHERE document_id=:document",
        "deleted_document": "UPDATE documents SET status='deleted' WHERE id=:document",
        "inactive_chunk": "UPDATE chunks SET active=false WHERE document_id=:document",
        "private_chunk": "UPDATE chunks SET security_level=1,classification='tenant_private' WHERE document_id=:document",
        "denied_group": "UPDATE chunks SET allowed_groups=ARRAY['not_a_member'] WHERE document_id=:document",
        "denied_role": "UPDATE chunks SET allowed_roles=ARRAY['not_authorized'] WHERE document_id=:document",
        "revoked_edge": "UPDATE graph_edges SET attributes=jsonb_set(attributes,'{review_status}','\"revoked\"') WHERE id=:edge",
        "malformed_edge": "UPDATE graph_edges SET attributes=jsonb_set(attributes,'{gip_relationship_sha256}','\"malformed\"') WHERE id=:edge",
    }
    db.execute(text(statements[case]), params)
    db.execute(text("SET LOCAL ROLE svs_app"))
    assert expand(corpus)[0] == []


@pytest.mark.parametrize(
    "case",
    [
        "group",
        "role",
        "private_document",
        "private_chunk",
        "cancelled_file",
        "source_hash",
        "version",
        "missing_citation",
    ],
)
def test_supporting_third_document_citation_requires_current_public_acl(corpus, case):
    db = corpus["db"]
    db.execute(text("RESET ROLE"))
    params = {
        "document": corpus["documents"][2],
        "node": corpus["nodes"][2]["id"],
        "edge": corpus["edge"]["id"],
    }
    statements = {
        "group": "UPDATE chunks SET allowed_groups=ARRAY['not_a_member'] WHERE document_id=:document",
        "role": "UPDATE chunks SET allowed_roles=ARRAY['not_authorized'] WHERE document_id=:document",
        "private_document": "UPDATE documents SET security_level=1 WHERE id=:document",
        "private_chunk": "UPDATE chunks SET security_level=1,classification='tenant_private' WHERE document_id=:document",
        "cancelled_file": "UPDATE vector_store_files SET status='cancelled' WHERE document_id=:document",
        "source_hash": "UPDATE graph_nodes SET attributes=jsonb_set(attributes,'{gip_source_version_sha256}','\"stale\"') WHERE id=:node",
        "version": "UPDATE documents SET current_version_id='stale' WHERE id=:document",
        "missing_citation": "UPDATE graph_edges SET attributes=jsonb_set(attributes,'{evidence_citation_ids}','[\"missing\"]') WHERE id=:edge",
    }
    db.execute(text(statements[case]), params)
    db.execute(text("SET LOCAL ROLE svs_app"))
    assert expand(corpus)[0] == []


@pytest.mark.parametrize("kind", ["groups", "roles"])
def test_supporting_citation_allows_actual_group_or_role_member(corpus, kind):
    db = corpus["db"]
    db.execute(text("RESET ROLE"))
    # Column name comes from this fixed test parameterization, not a request.
    db.execute(
        text(
            f"UPDATE chunks SET allowed_{kind}=ARRAY['reviewers'] WHERE document_id=:document"
        ),
        {"document": corpus["documents"][2]},
    )
    db.execute(text("SET LOCAL ROLE svs_app"))
    principal = corpus["principal"].model_copy(update={kind: ["reviewers"]})
    assert [chunk.document_id for chunk in expand(corpus, principal=principal)[0]] == [
        corpus["documents"][1]
    ]


@pytest.mark.parametrize(
    "case",
    [
        "tenant",
        "business",
        "store",
        "relationship",
        "generation",
        "document_id",
        "knowledge_base_id",
        "classification",
        "acl_bucket",
        "tag",
        "range",
        "alternative",
        "not_tag",
    ],
)
def test_real_sql_scope_and_request_filters_are_not_widened(corpus, case):
    kwargs = {}
    if case in ("tenant", "business"):
        key = "tenant_id" if case == "tenant" else "business_instance_id"
        kwargs["principal"] = corpus["principal"].model_copy(
            update={key: "other_scope"}
        )
    elif case == "store":
        kwargs["store"] = "vs_other"
    elif case == "relationship":
        kwargs["relations"] = ("has_contract",)
    elif case == "generation":
        kwargs["filters"] = {
            "file_attribute_filters": {"gip_generation_id": str(uuid4())}
        }
    elif case in ("document_id", "knowledge_base_id", "classification", "acl_bucket"):
        kwargs["filters"] = {case: "not_matching"}
    else:
        filters = {
            "file_attribute_filters": {"gip_generation_id": corpus["generation"]}
        }
        if case == "tag":
            filters["file_attribute_filters"]["state_code"] = "MO"
        elif case == "range":
            filters["file_attribute_ranges"] = [
                {"key": "year", "op": "gte", "value": 2030}
            ]
        elif case == "alternative":
            filters["file_attribute_filter_any"] = [
                {"state_code": "MO"},
                {"state_code": "NE"},
            ]
        elif case == "not_tag":
            filters["file_attribute_not_filters"] = [
                {"key": "state_code", "value": "KS"}
            ]
        kwargs["filters"] = filters
    assert expand(corpus, **kwargs)[0] == []
