"""Synthetic contracts for the Backend-ready Phase 2 adapters."""
from copy import deepcopy
import math
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.recommendation import inputs
from tests.unit.recommendation_fixtures import synthetic_candidates, synthetic_snapshot


def payloads():
    snapshot = synthetic_snapshot()
    for key in ("gpa_trend_delta", "gpa_trend_missing"):
        snapshot.pop(key)
    snapshot.update(gpa_prev_1=3.2, gpa_prev_2=2.7, current_gpa_credits=42,
                    prior_fail_credit_ratio=.73, observed_gap_semesters=7)
    courses = synthetic_candidates(3).to_dict("records")
    courses[0].update(previous_finish_status="FE", attempt_number=4)
    courses[1].update(previous_course_status="NEW", attempt_number=8)
    courses[2].update(previous_course_status="WITHDRAWN", previous_finish_status="W")
    request = dict(student_id="S", degree_id="D", part_id=20251,
                   min_credits=3, max_credits=6, allowed_failed_repeat_credits=0,
                   requirement_policies=[dict(plan_requirement_type_id="R", max_credits=18,
                                              completed_credits=9, reserved_credits=1,
                                              allowed_overflow_credits=2)],
                   allowed_fail_credits=99, allowed_pass_position_type="opaque")
    return {"snapshot": snapshot, "candidates": courses}, request


def prepare(student=None, request=None):
    original_student, original_request = payloads()
    return inputs.prepare_recommendation_payloads(
        student_payload=original_student if student is None else student,
        request_payload=original_request if request is None else request,
    )


def test_ready_values_are_preserved_without_io_or_candidate_cap_filtering(monkeypatch):
    student, request = payloads()
    before = deepcopy((student, request))
    def forbidden(*args, **kwargs):
        pytest.fail("Backend adapters must not read local files or compute local history")
    monkeypatch.setattr(pd, "read_parquet", forbidden)
    monkeypatch.setattr(inputs, "normalize_candidates", forbidden)
    monkeypatch.setattr(inputs, "build_student_snapshot", forbidden)
    result = prepare(student, request)
    assert result.snapshot["prior_fail_credit_ratio"] == .73
    assert result.snapshot["observed_gap_semesters"] == 7
    assert result.snapshot["current_gpa_credits"] == 42
    assert result.snapshot["gpa_trend_delta"] == pytest.approx(.5)
    assert result.snapshot["gpa_trend_missing"] == 0
    assert result.snapshot["part_semester"] == 1
    assert result.candidates.attempt_number.tolist() == [4, 8, 1]
    assert result.candidates.candidate_group.tolist() == ["FAILED_RETAKE", "NEW", "WITHDRAWN_RETAKE"]
    assert result.constraints.target_credits == 6
    assert result.constraints.requirement_policies["R"] == 10
    assert result.request_metadata["allowed_fail_credits"] == 99
    assert result.request_metadata["allowed_pass_position_type"] == "opaque"
    assert (student, request) == before


@pytest.mark.parametrize("first,second", [(None, 2.7), (3.2, None), (None, None)])
def test_missing_trend_stays_missing(first, second):
    student, _ = payloads()
    student["snapshot"].update(gpa_prev_1=first, gpa_prev_2=second,
                               gpa_trend_delta=99, gpa_trend_missing=0)
    snapshot = prepare(student).snapshot
    assert math.isnan(snapshot["gpa_trend_delta"])
    assert snapshot["gpa_trend_missing"] == 1


def test_only_explicit_eligibility_rejection_removes_candidates():
    student, _ = payloads()
    student["candidates"][0]["is_requestable"] = " N "
    student["candidates"][1]["allow_register"] = False
    assert prepare(student).candidates.course_id.tolist() == ["C"]


@pytest.mark.parametrize("location,field,value", [
    ("snapshot", "student_id", "other"), ("snapshot", "degree_id", "other"),
    ("snapshot", "part_id", 20252), ("candidate", "student_id", "other"),
    ("candidate", "degree_id", "other"), ("candidate", "part_id", 20252),
    ("request", "part_id", 20251.5), ("request", "part_id", 20254),
])
def test_cross_identity_or_invalid_part_is_rejected(location, field, value):
    student, request = payloads()
    target = student["snapshot"] if location == "snapshot" else (
        student["candidates"][0] if location == "candidate" else request)
    target[field] = value
    with pytest.raises(ValueError):
        prepare(student, request)


@pytest.mark.parametrize("field", ["current_gpa_credits", "prior_fail_credit_ratio", "observed_gap_semesters"])
def test_missing_ready_snapshot_field_is_rejected(field):
    student, _ = payloads()
    student["snapshot"].pop(field)
    with pytest.raises(ValueError):
        prepare(student)


@pytest.mark.parametrize("field,value", [
    ("current_gpa_credits", None), ("current_gpa_credits", -1),
    ("current_gpa_credits", float("inf")), ("gpa_prev_1", "bad"),
    ("start_agpa_points", 5), ("start_agpa_points", None),
])
def test_invalid_snapshot_numbers_are_rejected(field, value):
    student, _ = payloads()
    student["snapshot"][field] = value
    with pytest.raises(ValueError):
        prepare(student)


@pytest.mark.parametrize("location,field", [
    ("snapshot", "current_gpa_credits"), ("snapshot", "prior_total_reg_credits"),
    ("snapshot", "gpa_prev_1"), ("candidate", "plan_credits_count"),
])
def test_decimal_to_float_overflow_is_rejected(location, field):
    student, _ = payloads()
    target = student["snapshot"] if location == "snapshot" else student["candidates"][0]
    target[field] = "1e400"
    with pytest.raises(ValueError):
        prepare(student)


@pytest.mark.parametrize("field,value", [
    ("attempt_number", 0), ("attempt_number", 1.5), ("course_credits", -1),
    ("course_credits", None), ("course_credits", float("inf")),
])
def test_invalid_candidate_numbers_are_rejected(field, value):
    student, _ = payloads()
    student["candidates"][0][field] = value
    with pytest.raises(ValueError):
        prepare(student)


def test_duplicate_course_identity_after_normalization_is_rejected():
    student, _ = payloads()
    student["candidates"][0]["course_id"] = 12.0
    student["candidates"][1]["course_id"] = "12"
    with pytest.raises(ValueError):
        prepare(student)


def test_candidate_order_and_untrusted_features_do_not_change_prepared_rows():
    student, _ = payloads()
    baseline = prepare(student).candidates
    for course in student["candidates"]:
        course.update(final_mark=0, fail_probability=1, course_history_avg_mark=999,
                      plan_total_credits=999, gpa_prev_1=999, candidate_group="NEW")
    student["candidates"].reverse()
    assert_frame_equal(prepare(student).candidates, baseline)
    assert not {"final_mark", "fail_probability", "plan_total_credits", "course_history_avg_mark"} & set(baseline)


def test_empty_candidates_keep_model_and_status_columns():
    student, _ = payloads()
    student["candidates"] = []
    result = prepare(student)
    assert result.candidates.empty
    assert set(inputs.CANDIDATE_COURSE_COLUMNS + ["candidate_group", "course_name"]) <= set(result.candidates)


def test_target_overrides_valid_range_and_legacy_fail_name_is_not_a_cap():
    _, request = payloads()
    request["target_credits"] = 3
    assert prepare(request=request).constraints.target_credits == 3
    request.pop("allowed_failed_repeat_credits")
    with pytest.raises(ValueError):
        prepare(request=request)


@pytest.mark.parametrize("change", [
    {"target_credits": 0}, {"min_credits": 7}, {"max_credits": float("inf")},
    {"allowed_failed_repeat_credits": -1}, {"allowed_withdrawn_repeat_credits": None},
    {"allowed_withdrawn_repeat_credits": -1},
])
def test_invalid_request_constraints_are_rejected(change):
    _, request = payloads()
    request.update(change)
    with pytest.raises(ValueError):
        prepare(request=request)


def test_imports_are_production_safe():
    script = "import sys; from src.recommendation.inputs import prepare_recommendation_payloads; assert not any(n.startswith(('src.experiments', 'src.modeling', 'src.diagnostics')) for n in sys.modules)"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("semantic,official,group", [
    ("NEW", None, "NEW"), ("NEVER_TAKEN", None, "NEW"),
    ("FAILED", "F", "FAILED_RETAKE"), ("FAILED", "FE", "FAILED_RETAKE"),
    ("FAILED", "FA", "FAILED_RETAKE"), ("WITHDRAWN", "W", "WITHDRAWN_RETAKE"),
    ("PASSED", "P", "OTHER_PREVIOUS"), ("OTHER", "D", "OTHER_PREVIOUS"),
    ("OTHER", "Z", "OTHER_PREVIOUS"), ("OTHER", "ST", "OTHER_PREVIOUS"),
    ("OTHER", "T", "OTHER_PREVIOUS"), ("UNRESOLVED", "I", "OTHER_PREVIOUS"),
    ("UNRESOLVED", "IP", "OTHER_PREVIOUS"), (None, None, "OTHER_PREVIOUS"),
    ("UNKNOWN", None, "OTHER_PREVIOUS"),
])
def test_official_classification_does_not_use_marks_or_attempts(semantic, official, group):
    student, _ = payloads()
    row = student["candidates"][0]
    row.pop("previous_finish_status", None)
    row.update(attempt_number=9, final_mark=0, fail_probability=1)
    if semantic is not None:
        row["previous_course_status"] = semantic
    if official is not None:
        row["previous_finish_status"] = official
    assert prepare(student).candidates.iloc[0].candidate_group == group


@pytest.mark.parametrize("semantic,official", [("FAILED", "W"), ("PASSED", "I"), ("NEW", "P"), ("UNKNOWN", "F")])
def test_conflicting_full_status_meanings_are_rejected(semantic, official):
    student, _ = payloads()
    student["candidates"][0].update(previous_course_status=semantic, previous_finish_status=official)
    with pytest.raises(ValueError):
        prepare(student)
