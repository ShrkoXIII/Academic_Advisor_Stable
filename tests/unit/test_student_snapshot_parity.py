"""Request-time student features through the API and ready-input boundaries."""
import math

import pytest

from src.api.adapters.student import adapt_student
from src.api.settings import ApiSettings
from src.recommendation.inputs import derive_observed_gap_semesters, normalize_student_payload
from tests.synthetic_api import sample_request


def student_snapshot(request):
    result = adapt_student(request, settings=ApiSettings())
    assert not result.errors, result.public()
    return result, result.normalized


def ready_student(snapshot):
    identity = {key: snapshot[key] for key in ("student_id", "degree_id", "part_id")}
    return normalize_student_payload(snapshot, **identity)


@pytest.mark.parametrize(("keep_earliest", "trend"), [(True, 0.5), (False, None)])
def test_snapshot_trend_and_readiness_preserve_boundary_missing_values(keep_earliest, trend):
    request = sample_request()
    if not keep_earliest:
        request["student_api_response"]["data"]["studentSummaryInfo"].pop(0)

    diagnostic, snapshot = student_snapshot(request)
    ready = ready_student(snapshot)
    assert snapshot["part_semester"] == ready["part_semester"] == 1
    assert snapshot["gpa_trend_missing"] == ready["gpa_trend_missing"] == int(trend is None)
    readiness = diagnostic.summary["field_readiness"]
    if trend is None:
        assert snapshot["gpa_trend_delta"] is None
        assert math.isnan(ready["gpa_trend_delta"])
        assert readiness["gpa_trend_delta"] == "unavailable"
        assert "gpa_prev_2" in diagnostic.unavailable_fields
    else:
        assert snapshot["gpa_trend_delta"] == ready["gpa_trend_delta"] == pytest.approx(trend)
        assert readiness["gpa_trend_delta"] == "ready"


@pytest.mark.parametrize(("courses", "credits", "gap"), [
    ("0", "0", 1),
    (None, "18", 0),
    (None, "0", None),
], ids=["reported-unregistered", "positive-credits-prove-enrollment", "unknown-enrollment"])
def test_observed_gap_uses_api_enrollment_evidence(courses, credits, gap):
    request = sample_request()
    info = request["student_api_response"]["data"]["studentDegreeInfo"]
    info.update(SEMESTER_REG_COURSES=courses, SEMESTER_REG_CREDITS=credits)

    diagnostic, snapshot = student_snapshot(request)
    assert snapshot["observed_gap_semesters"] == gap
    assert ("observed_gap_semesters" in diagnostic.unavailable_fields) == (gap is None)
    assert diagnostic.summary["field_readiness"]["observed_gap_semesters"] == (
        "unavailable" if gap is None else "ready"
    )


def test_observed_gap_excludes_unregistered_optional_target():
    assert derive_observed_gap_semesters(20251, 20253, target_registered=False) == 1


@pytest.mark.parametrize(("registered", "has_failed_credits", "ratio"), [
    ("75", True, 3 / 75),
    ("0", True, None),
    ("75", False, None),
], ids=["attested-total", "zero-total", "unavailable-failed-credits"])
def test_prior_fail_credit_ratio_keeps_unavailable_totals_unknown(registered, has_failed_credits, ratio):
    request = sample_request()
    info = request["student_api_response"]["data"]["studentDegreeInfo"]
    info["TOTAL_REG_CREDITS"] = registered
    if not has_failed_credits:
        request["integration_context"]["student_values"].pop("prior_total_fail_credits")

    diagnostic, snapshot = student_snapshot(request)
    assert snapshot["prior_fail_credit_ratio"] == ratio
    ready = ready_student(snapshot)
    if ratio is None:
        assert math.isnan(ready["prior_fail_credit_ratio"])
        assert diagnostic.summary["field_readiness"]["prior_fail_credit_ratio"] == "unavailable"
    else:
        assert ready["prior_fail_credit_ratio"] == ratio
        assert diagnostic.summary["field_readiness"]["prior_fail_credit_ratio"] == "ready"
