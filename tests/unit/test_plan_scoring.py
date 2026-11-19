"""Aggregation order and legacy ranking for synthetic scored plans."""
import pandas as pd
import pytest

from src.recommendation import plan_scoring
from src.recommendation.two_stage_engine import TwoStagePlanRecommender
from tests.unit.two_stage_fixtures import evaluation_engine, ready_payloads


def scored_courses():
    return pd.DataFrame({
        "plan_id": [20, 30, 10, 30],
        "course_id": ["A", "B", "C", "D"],
        "course_credits": [6., 2.5, 6., 3.5],
        "expected_points": [3., 2., 3., 3.],
        "fail_probability": [.1, .2, .1, .1],
        "attempt_number": [1, 1, 1, 2],
    })


def test_plan_aggregation_keeps_input_order_and_legacy_summary_keeps_rank():
    scored = scored_courses()
    aggregated = plan_scoring.aggregate_scored_plans(scored, 2.5, 42)
    legacy = plan_scoring.summarize_scored_plans(scored, 2.5, 42)

    assert aggregated.plan_id.tolist() == [20, 30, 10]
    assert legacy.plan_id.tolist() == [10, 20, 30]
    assert list(aggregated) == plan_scoring.SUMMARY_COLUMNS
    pd.testing.assert_frame_equal(
        aggregated.set_index("plan_id").sort_index(), legacy.set_index("plan_id").sort_index(),
    )

    plan = aggregated.set_index("plan_id").loc[30]
    assert plan["total_credits"] == 6
    assert plan["expected_quality_points"] == 15.5
    assert plan["expected_failed_credits"] == pytest.approx(.85)
    assert plan["expected_plan_gpa"] == pytest.approx(15.5 / 6)
    assert plan["projected_cumulative_gpa"] == pytest.approx(120.5 / 48)
    assert plan["expected_cumulative_gpa_gain"] == pytest.approx(120.5 / 48 - 2.5)
    assert plan["gpa_gain"] == pytest.approx(15.5 / 6 - 2.5)
    assert plan["is_expected_cumulative_improvement"]
    assert plan["projected_gpa_requires_repeat_policy"]


def test_empty_aggregation_keeps_legacy_summary_schema():
    scored = scored_courses().iloc[:0]
    aggregated = plan_scoring.aggregate_scored_plans(scored, 2.5, 42)
    legacy = plan_scoring.summarize_scored_plans(scored, 2.5, 42)

    assert aggregated.empty
    assert list(aggregated) == plan_scoring.SUMMARY_COLUMNS
    pd.testing.assert_frame_equal(aggregated, legacy)


def test_engine_ranks_without_the_legacy_sort(tmp_path, monkeypatch):
    def reject_legacy_sort(_):
        pytest.fail("Inference should rank plans only through its configured strategies.")

    monkeypatch.setattr(plan_scoring, "rank_plans", reject_legacy_sort)
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=6, target=6)
    result = engine.recommend_from_payloads(student_payload=student, request_payload=request, top_k=3)

    assert result["status"] == "ok"
    assert [plan["rank"] for plan in result["recommendations"]] == [1, 2, 3]
