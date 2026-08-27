from svs_common.kscourts_graphrag import (
    KSCourtsChunkRecord,
    build_graph,
    extract_signals,
    normalize_case_citation_name,
    normalize_docket,
    normalize_statute_section,
    split_case_parties,
)


def test_extract_signals_finds_kansas_case_citation():
    text = "See State v. Clapp, 308 Kan. 976, 982, 425 P.3d 605 (2018) for the rule."

    signals = extract_signals(text)

    case = next(signal for signal in signals if signal.kind == "case_citation")
    assert case.label == "State v. Clapp, 308 Kan. 976 (2018)"
    assert case.attributes["case_name"] == "State v. Clapp"
    assert case.attributes["volume"] == "308"
    assert case.attributes["reporter"] == "Kan."
    assert case.attributes["page"] == "976"
    assert case.attributes["pinpoint"] == "982"
    assert case.attributes["parallel_citation"] == "425 P.3d 605"
    assert case.attributes["year"] == "2018"
    assert case.method == "regex"
    assert case.confidence == 0.95


def test_extract_signals_finds_statutes_rules_and_dockets():
    text = (
        "No. 125,502 was submitted under K.S.A. 2022 Supp. 21-6820(g) "
        "and K.S.A. 2018 Supp. 22- 3716(c)(12), plus Supreme Court Rule 7.041A."
    )

    signals = extract_signals(text)

    dockets = [signal for signal in signals if signal.kind == "docket_reference"]
    statutes = [signal for signal in signals if signal.kind == "statute"]
    rules = [signal for signal in signals if signal.kind == "rule"]
    assert [signal.attributes["docket_number"] for signal in dockets] == ["125502"]
    assert [signal.attributes["section"] for signal in statutes] == ["21-6820(g)", "22-3716(c)(12)"]
    assert [signal.label for signal in rules] == ["Supreme Court Rule 7.041A"]


def test_extract_signals_ignores_non_citation_text():
    assert extract_signals("This paragraph describes facts without legal citations.") == []


def test_extract_signals_trims_case_citation_evidence_start():
    text = (
        "The State carries the burden to prove that the search was lawful. "
        "State v. Goodro, 315 Kan. 235, 238, 506 P.3d 918 (2022)."
    )

    case = next(signal for signal in extract_signals(text) if signal.kind == "case_citation")

    assert case.label == "State v. Goodro, 315 Kan. 235 (2022)"
    assert text[case.start:case.end].startswith("State v. Goodro")


def test_normalizers_and_party_split():
    assert normalize_docket("125,502") == "125502"
    assert normalize_statute_section("22- 3716(c)(12)") == "22-3716(c)(12)"
    assert normalize_case_citation_name("The court in State v. Mitchell") == "State v. Mitchell"
    assert normalize_case_citation_name("See also Jones v. State") == "Jones v. State"
    assert (
        normalize_case_citation_name("State or this court to follow up on. See State v. Davis")
        == "State v. Davis"
    )
    assert split_case_parties("State v. Boles") == ["State", "Boles"]
    assert split_case_parties("In re Christian") == ["Christian"]


def test_build_graph_emits_stable_nodes_edges_and_provenance():
    record = KSCourtsChunkRecord(
        vector_store_id="vs_ks",
        document_id="doc_boles",
        chunk_id="chk_boles_0",
        chunk_ordinal=0,
        text=(
            "No. 125,502. State v. Clapp, 308 Kan. 976, 982, 425 P.3d 605 (2018). "
            "K.S.A. 2018 Supp. 22- 3716(c)(12)."
        ),
        attributes={
            "title": "State v. Boles",
            "docket_number": "125502",
            "decision_date": "2023-03-31",
            "decision_year": "2023",
            "court": "Court of Appeals",
            "status": "Unpublished",
            "source_pdf_filename": "boles.pdf",
            "sha256": "abc123",
        },
    )

    graph = build_graph([record])

    node_types = {node["type"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    assert {"opinion", "case", "docket", "court", "party", "statute", "citation", "year", "publication_status"} <= node_types
    assert {"cites_case", "cites_statute", "mentions_docket", "source_document", "has_docket"} <= edge_types
    assert graph["summary"]["documents_processed"] == 1
    assert graph["summary"]["records_processed"] == 1
    assert graph["summary"]["extraction_error_count"] == 0
    assert graph["summary"]["duplicate_merged_edge_count"] == 0
    assert graph["summary"]["backend_recommendation"] == "postgres_first"

    cites_case = next(edge for edge in graph["edges"] if edge["type"] == "cites_case")
    assert cites_case["provenance"]["document_id"] == "doc_boles"
    assert cites_case["provenance"]["chunk_id"] == "chk_boles_0"
    assert cites_case["provenance"]["extraction_method"] == "regex"
    assert "State v. Clapp" in cites_case["provenance"]["evidence"]


def test_build_graph_adds_same_docket_edges_for_duplicate_dockets():
    records = [
        KSCourtsChunkRecord(
            vector_store_id="vs_ks",
            document_id="doc_harris_1",
            chunk_id="chk_harris_1",
            chunk_ordinal=0,
            text="No. 116515.",
            attributes={"title": "State v. Harris", "docket_number": "116515", "decision_year": "2018"},
        ),
        KSCourtsChunkRecord(
            vector_store_id="vs_ks",
            document_id="doc_harris_2",
            chunk_id="chk_harris_2",
            chunk_ordinal=0,
            text="No. 116515.",
            attributes={"title": "State v. Harris", "docket_number": "116515", "decision_year": "2020"},
        ),
    ]

    graph = build_graph(records)

    same_docket = [edge for edge in graph["edges"] if edge["type"] == "same_docket"]
    assert len(same_docket) == 1
    assert same_docket[0]["attributes"] == {"docket_number": "116515"}
