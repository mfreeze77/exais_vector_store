from svs_common.query_planner import (
    KANSAS_CIVICS_LEGAL_PROFILE_ID,
    decompose_query,
    merge_query_filters,
    plan_query,
    rewrite_query_for_search,
)


def test_rewrite_query_removes_request_filler():
    assert rewrite_query_for_search("Can you tell me what was the RunPod Marker warmup fix?") == "RunPod Marker warmup fix"


def test_decompose_query_splits_compound_questions():
    assert decompose_query("RunPod Marker warmup fix and Voyage embedding profile") == [
        "RunPod Marker warmup fix",
        "Voyage embedding profile",
    ]


def test_plan_query_keeps_original_when_rewrite_disabled():
    plan = plan_query("What was the bug?", rewrite_query=False)

    assert plan.effective_query == "What was the bug"
    assert plan.subqueries == ["What was the bug"]
    assert plan.rewritten is False
    assert plan.filters == {}


def test_plan_query_marks_rewritten_subqueries():
    plan = plan_query("Can you find RunPod Marker warmup and Voyage embeddings?", rewrite_query=True)

    assert plan.effective_query == "RunPod Marker warmup and Voyage embeddings"
    assert plan.subqueries == ["RunPod Marker warmup", "Voyage embeddings"]
    assert plan.rewritten is True


def test_kansas_civics_planner_extracts_docket_filter_and_query_text():
    plan = plan_query(
        "Find State v. Perez docket 80739",
        profile_id=KANSAS_CIVICS_LEGAL_PROFILE_ID,
    )

    assert plan.profile_id == KANSAS_CIVICS_LEGAL_PROFILE_ID
    assert plan.effective_query == "State v. Perez"
    assert plan.subqueries == ["State v. Perez"]
    assert plan.filters == {"file_attribute_filters": {"docket_number": "80739"}}
    assert plan.rewritten is True


def test_kansas_civics_planner_extracts_four_digit_docket_filter():
    plan = plan_query(
        "In re Worden docket 7417",
        profile_id=KANSAS_CIVICS_LEGAL_PROFILE_ID,
    )

    assert plan.effective_query == "In re Worden"
    assert plan.filters == {"file_attribute_filters": {"docket_number": "7417"}}


def test_kansas_civics_planner_extracts_court_status_and_decision_year():
    plan = plan_query(
        "published Kansas Supreme Court school finance cases from 2019",
        rewrite_query=True,
        profile_id=KANSAS_CIVICS_LEGAL_PROFILE_ID,
    )

    assert plan.effective_query == "school finance cases"
    assert plan.filters == {
        "file_attribute_filters": {
            "court": "Supreme Court",
            "status": "Published",
            "decision_year": "2019",
        }
    }


def test_kansas_civics_planner_extracts_unpublished_before_published():
    plan = plan_query(
        "unpublished Court of Appeals tax decision 2020-06-05",
        profile_id=KANSAS_CIVICS_LEGAL_PROFILE_ID,
    )

    assert plan.filters == {
        "file_attribute_filters": {
            "court": "Court of Appeals",
            "status": "Unpublished",
            "decision_date": "2020-06-05",
            "decision_year": "2020",
        }
    }


def test_merge_query_filters_preserves_explicit_filter_on_conflict():
    merged = merge_query_filters(
        {"vector_store_id": "vs_1", "file_attribute_filters": {"docket_number": "11111"}},
        {"file_attribute_filters": {"docket_number": "22222", "court": "Court of Appeals"}},
    )

    assert merged == {
        "vector_store_id": "vs_1",
        "file_attribute_filters": {
            "docket_number": "11111",
            "court": "Court of Appeals",
        },
    }
