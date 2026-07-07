from svs_common.query_planner import decompose_query, plan_query, rewrite_query_for_search


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


def test_plan_query_marks_rewritten_subqueries():
    plan = plan_query("Can you find RunPod Marker warmup and Voyage embeddings?", rewrite_query=True)

    assert plan.effective_query == "RunPod Marker warmup and Voyage embeddings"
    assert plan.subqueries == ["RunPod Marker warmup", "Voyage embeddings"]
    assert plan.rewritten is True
