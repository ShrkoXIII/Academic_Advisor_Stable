from copy import deepcopy

import pandas as pd
import pytest

from src.evaluation.observed_plan import predict_observed_plan, attach_actual_outcomes
from src.recommendation.two_stage_engine import TwoStagePlanRecommender
from tests.unit.two_stage_fixtures import evaluation_engine, ready_payloads


def test_observed_forecast_uses_full_plan_context_and_ignores_target_results(tmp_path):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    courses = payload["candidates"][:3]
    forecast = predict_observed_plan(engine, payload["snapshot"], courses, history_as_of_part=20243)
    poisoned = [dict(row, final_mark=0, points=0, gpa_points=0) for row in courses]
    again = predict_observed_plan(engine, payload["snapshot"], poisoned, history_as_of_part=20243)
    pd.testing.assert_frame_equal(forecast["courses"], again["courses"])
    assert forecast["summary"]["total_credits"] == 9
    matrix = engine.artifacts.stage2.grade_model.matrices[-1]
    assert matrix.shape == (3, 47) and matrix.plan_course_count.eq(3).all()
    assert not {"final_mark", "points", "gpa_points"}.intersection(matrix.columns)


def test_observed_prediction_rejects_target_history(tmp_path):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    with pytest.raises(ValueError):
        predict_observed_plan(engine, payload["snapshot"], payload["candidates"], history_as_of_part=20251)


def test_registered_courses_are_not_filtered_by_candidate_eligibility(tmp_path):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    courses = deepcopy(payload["candidates"][:3])
    courses[0].update(is_requestable=False, allow_register=False)
    result = predict_observed_plan(engine, payload["snapshot"], courses, history_as_of_part=20243)
    assert len(result["courses"]) == 3 and result["summary"]["total_credits"] == 9


def test_string_semester_identity_is_normalized_before_prediction(tmp_path):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    payload["snapshot"].update(part_id="20251", student_id=" S ")
    result = predict_observed_plan(engine, payload["snapshot"], payload["candidates"][:1], history_as_of_part=20243)
    assert result["identity"] == {"student_id": "S", "degree_id": "D", "part_id": 20251}


def test_observed_repeat_needs_attempt_features_but_not_candidate_status(tmp_path):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    courses = deepcopy(payload["candidates"][:3])
    for row in courses:
        row.pop("previous_course_status", None)
    result = predict_observed_plan(engine, payload["snapshot"], courses, history_as_of_part=20243)
    assert len(result["courses"]) == 3
    assert result["summary"]["projected_gpa_requires_repeat_policy"]


def test_actual_results_are_joined_only_after_prediction_and_require_finalization(tmp_path):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    forecast = predict_observed_plan(engine, payload["snapshot"], payload["candidates"][:2], history_as_of_part=20243)
    actual = {"student_id": "S", "degree_id": "D", "part_id": 20251,
              "source": "synthetic-final-ledger", "finalized": True,
              "courses": [{"course_id": "C00", "course_credits": 3, "actual_mark": 55, "actual_points": 2}],
              "semester_gpa": 2.8, "cumulative_gpa": 2.7}
    joined = attach_actual_outcomes(forecast, actual)
    assert joined["courses"].actual_mark.notna().sum() == 1
    assert joined["official_semester_gpa"] == 2.8
    assert joined["official_cumulative_gpa"] == 2.7
    assert joined["actual_course_gpa"] is None
    actual["finalized"] = False
    with pytest.raises(ValueError):
        attach_actual_outcomes(forecast, actual)


@pytest.mark.parametrize("field,value", [("student_id", "other"), ("degree_id", "other"), ("part_id", 20252)])
def test_outcome_identity_conflicts_fail(tmp_path, field, value):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    forecast = predict_observed_plan(engine, payload["snapshot"], payload["candidates"][:1], history_as_of_part=20243)
    actual = {"student_id": "S", "degree_id": "D", "part_id": 20251,
              "source": "synthetic", "finalized": True, "courses": []}
    actual[field] = value
    with pytest.raises(ValueError):
        attach_actual_outcomes(forecast, actual)


@pytest.mark.parametrize("field,value", [
    ("course_credits", "three"), ("course_credits", None), ("course_credits", True),
    ("actual_mark", True), ("actual_points", False),
    ("semester_gpa", True), ("cumulative_gpa", False),
])
def test_malformed_or_boolean_outcome_numbers_are_value_errors(tmp_path, field, value):
    engine = evaluation_engine(TwoStagePlanRecommender, tmp_path)
    payload, _ = ready_payloads()
    forecast = predict_observed_plan(engine, payload["snapshot"], payload["candidates"][:1], history_as_of_part=20243)
    row = {"course_id": "C00", "course_credits": 3, "actual_mark": 60, "actual_points": 2}
    actual = {"student_id": "S", "degree_id": "D", "part_id": 20251,
              "source": "synthetic", "finalized": True, "courses": [row]}
    if field.endswith("gpa"):
        actual[field] = value
    else:
        row[field] = value
    with pytest.raises(ValueError):
        attach_actual_outcomes(forecast, actual)
