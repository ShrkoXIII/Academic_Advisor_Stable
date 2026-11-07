"""Small complete-plan oracle; synthetic course predictions only."""
import importlib
import importlib.util
from itertools import combinations
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.recommendation.constraints import PlanConstraints
from src.recommendation.ranking import RankingStrategy
from tests.unit.recommendation_fixtures import synthetic_candidates, synthetic_components


def shortlist_api():
    assert importlib.util.find_spec("src.recommendation.shortlist") is not None, "Phase 5 shortlist is missing"
    return importlib.import_module("src.recommendation.shortlist")


def candidates():
    rows = synthetic_candidates().assign(candidate_group="NEW", expected_points=2., fail_probability=.1)
    rows.loc[0, "candidate_group"] = "FAILED_RETAKE"
    rows.loc[1, "candidate_group"] = "WITHDRAWN_RETAKE"
    rows["course_credits"] = [2.5, 3.5, 6, 0, 3, 3]
    return rows


@pytest.mark.parametrize("name", ["balance_first", "pareto"])
def test_complete_feasibility_before_shortlist_fractional_and_optional_zero(name):
    rows = candidates()
    constraints = PlanConstraints(Decimal(6), {"R": Decimal(6)}, Decimal(2.5), Decimal(0))
    expected = set()
    for n in range(1, len(rows) + 1):
        for indices in combinations(range(len(rows)), n):
            costs = [Decimal(str(rows.iloc[i].course_credits)) for i in indices]
            if sum(costs) == 6 and not any(i == 1 for i in indices):
                expected.add(tuple(sorted(rows.iloc[list(indices)].course_id)))
    result = shortlist_api().build_stage1_shortlist(
        rows, constraints, stage1_shortlist_strategy=RankingStrategy("stage1", name),
        current_gpa=2.5, current_gpa_credits=42, part_semester=1,
    )
    assert set(result.all_plans.course_tuple) == expected == {("C",), ("C", "D"), ("E", "F"), ("D", "E", "F")}
    assert len(result.shortlist) == 4
    for row in result.all_plans.itertuples():
        assert row.expected_quality_points == 12
        assert row.projected_cumulative_gpa == pytest.approx((2.5 * 42 + 12) / 48)
        assert row.expected_failed_credits == pytest.approx(.6)
        assert row.failed_balance_penalty is None or pd.isna(row.failed_balance_penalty)
        assert row.component_active_flags == {"failed": False, "total_previous": False, "withdrawn": False}


def test_no_lower_credit_fallback_and_no_prefiltering_of_failed_availability():
    rows = synthetic_candidates(3).assign(candidate_group=["FAILED_RETAKE", "NEW", "NEW"],
                                          expected_points=3., fail_probability=.1)
    result = shortlist_api().build_stage1_shortlist(
        rows, PlanConstraints(12, {"R": 100}, 0),
        stage1_shortlist_strategy=RankingStrategy("stage1", "balance_first"),
        current_gpa=2.5, current_gpa_credits=42, part_semester=1,
    )
    assert result.all_plans.empty and result.shortlist.empty and result.plan_indices == {}


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, np.zeros((3, 1)), np.zeros(2)])
def test_shared_scoring_rejects_nonfinite_or_wrong_shape_before_clip(value):
    module = importlib.import_module("src.recommendation.plan_scoring")
    assert hasattr(module, "score_course_rows"), "Phase 5 shared scorer is missing"
    grade, fail, levels, scale, *_ = synthetic_components()
    grade.predict = lambda matrix, **kwargs: value if isinstance(value, np.ndarray) else np.full(len(matrix), value)
    from src.features.feature_contract import BASE_FEATURES
    frame = pd.DataFrame({c: [1] * 3 for c in BASE_FEATURES}).assign(grade_version_id="1")
    with pytest.raises(ValueError):
        module.score_course_rows(frame, grade, fail, levels, scale)


def test_input_hash_preserves_credit_precision_beyond_decimal_context(tmp_path):
    from tests.unit.two_stage_fixtures import evaluation_engine, ready_payloads
    cls = importlib.import_module("src.recommendation.two_stage_engine").TwoStagePlanRecommender
    engine = evaluation_engine(cls, tmp_path)
    student, request = ready_payloads(size=3)
    request["target_credits"] = "12.00000000000000000000000000001"
    first = engine.recommend_from_payloads(student_payload=student, request_payload=request)
    request["target_credits"] = "12.00000000000000000000000000002"
    second = engine.recommend_from_payloads(student_payload=student, request_payload=request)
    assert first["metadata"]["input_sha256"] != second["metadata"]["input_sha256"]


def test_exact_target_above_twelve_does_not_accept_twelve(tmp_path):
    from tests.unit.two_stage_fixtures import evaluation_engine, ready_payloads
    cls = importlib.import_module("src.recommendation.two_stage_engine").TwoStagePlanRecommender
    engine = evaluation_engine(cls, tmp_path)
    student, request = ready_payloads(size=4)
    request["target_credits"] = "12.00000000000000000000000000001"
    result = engine.recommend_from_payloads(student_payload=student, request_payload=request)
    assert result["status"] == "no_feasible_plan"


@pytest.mark.parametrize("cap", ["requirement", "failed", "withdrawn"])
def test_exact_long_decimal_cost_cannot_round_below_a_hard_cap(tmp_path, cap):
    from tests.unit.two_stage_fixtures import evaluation_engine, ready_payloads
    cls = importlib.import_module("src.recommendation.two_stage_engine").TwoStagePlanRecommender
    engine = evaluation_engine(cls, tmp_path)
    student, request = ready_payloads(size=4)
    student["candidates"][0].update(course_credits="3.00000000000000000000000000001",
        previous_course_status="WITHDRAWN" if cap == "withdrawn" else "FAILED")
    request["target_credits"] = "12.00000000000000000000000000001"
    if cap == "requirement":
        request["requirement_policies"][0]["max_credits"] = 12
    else:
        student["candidates"][1]["previous_course_status"] = "NEW"
        request[f"allowed_{cap}_repeat_credits"] = 3
    result = engine.recommend_from_payloads(student_payload=student, request_payload=request)
    assert result["status"] == "no_feasible_plan"


def test_remaining_policy_arithmetic_preserves_every_supplied_decimal_digit():
    from src.recommendation.constraints import normalize_requirement_policies
    remaining = normalize_requirement_policies([dict(plan_requirement_type_id="R",
        max_credits="12.00000000000000000000000000001", completed_credits=2)])
    assert remaining["R"] == Decimal("10.00000000000000000000000000001")
