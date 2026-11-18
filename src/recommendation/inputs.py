"""I/O-free adapters for Backend-ready recommendation payloads."""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd

from src.data.cleaning.cleaning_utils import clean_id
from src.data.academic_calendar import count_regular_semesters_between, is_regular_semester

from .constraints import PlanConstraints, normalize_requirement_policies
from .course_status import classify_candidate_status
from .registration_policy import resolve_credit_bounds


STUDENT_SNAPSHOT_COLUMNS = [
    "student_id", "degree_id", "faculty_id", "grade_version_id",
    "gpa_prev_1", "gpa_prev_2", "gpa_trend_delta", "gpa_trend_missing",
    "start_agpa_points", "start_total_in_courses", "start_total_in_credits",
    "prior_total_reg_courses", "prior_total_reg_credits", "prior_total_fail_courses",
    "prior_total_fail_credits", "prior_fail_credit_ratio", "prior_registered_semesters",
    "observed_gap_semesters", "diploma_gpa", "diploma_type_id", "degree_credits_count",
]
CANDIDATE_COURSE_COLUMNS = [
    "course_id", "course_credits", "attempt_number",
    "plan_requirement_type_id", "plan_year_order", "plan_semester_order", "plan_credits_count",
]


# Core mapping schema only; transport/HTTP contracts remain outside Phase 2.
BACKEND_SNAPSHOT_COLUMNS = [
    c for c in STUDENT_SNAPSHOT_COLUMNS
    if c not in {"gpa_trend_delta", "gpa_trend_missing"}
] + ["part_id", "current_gpa_credits"]


@dataclass(frozen=True)
class PreparedRecommendationInputs:
    snapshot: dict
    candidates: pd.DataFrame
    constraints: PlanConstraints
    request_metadata: dict


def _payload_id(value, name):
    result = clean_id(pd.Series([value])).iloc[0]
    if pd.isna(result):
        raise ValueError(f"Missing {name}.")
    return str(result)


def _payload_number(value, name, *, nullable=False, nonnegative=False):
    if value is None or pd.isna(value):
        if nullable:
            return float("nan")
        raise ValueError(f"Missing {name}.")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {name}.") from exc
    if not number.is_finite() or (nonnegative and number < 0):
        raise ValueError(f"Invalid {name}.")
    if not np.isfinite(float(number)):
        raise ValueError(f"{name} exceeds the finite numeric range.")
    return number


def _payload_part(value):
    number = _payload_number(value, "part_id")
    if number != number.to_integral_value() or not 10000 <= number <= 99999:
        raise ValueError("part_id must be a five-digit academic semester.")
    result = int(number)
    is_regular_semester(result)
    return result


def _validate_payload_identity(record, student_id, degree_id, part_id, *, required):
    for key, expected in (("student_id", student_id), ("degree_id", degree_id), ("part_id", part_id)):
        if key not in record and not required:
            continue
        actual = _payload_part(record.get(key)) if key == "part_id" else _payload_id(record.get(key), key)
        if actual != expected:
            raise ValueError(f"Payload {key} does not match the request.")


def derive_semester_and_gpa_trend(
    part_id: int, gpa_prev_1: float | None, gpa_prev_2: float | None,
) -> tuple[int, float | None]:
    """Derive fields from normalized values, preserving the input's missing representation."""
    trend = None if gpa_prev_1 is None or gpa_prev_2 is None else gpa_prev_1 - gpa_prev_2
    return part_id % 10, trend


def derive_prior_fail_credit_ratio(failed: float | None, registered: float | None) -> float | None:
    """Use the beginning-of-semester totals when the denominator is available."""
    return None if registered in (None, 0) or failed is None else failed / registered


def derive_observed_gap_semesters(previous_part: int, target_part: int, *, target_registered: bool) -> int:
    """Count intervening regular terms and the target if it is regular and unregistered."""
    return count_regular_semesters_between(previous_part, target_part) + (
        is_regular_semester(target_part) and not target_registered
    )


def normalize_student_payload(snapshot, *, student_id, degree_id, part_id):
    """Accept ready history values and derive only GPA trend and semester.

    current_gpa_credits is required independently of registered-credit counters.
    Explicit null histories remain unknown.
    """
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a mapping.")
    missing = set(BACKEND_SNAPSHOT_COLUMNS) - snapshot.keys()
    if missing:
        raise ValueError(f"Incomplete Backend snapshot: {sorted(missing)}")
    _validate_payload_identity(snapshot, student_id, degree_id, part_id, required=True)
    result = {key: snapshot[key] for key in BACKEND_SNAPSHOT_COLUMNS}
    ids = {"student_id", "degree_id", "faculty_id", "grade_version_id", "diploma_type_id"}
    for key in ids:
        result[key] = (None if key == "diploma_type_id" and pd.isna(result[key])
                       else _payload_id(result[key], key))
    for key in set(BACKEND_SNAPSHOT_COLUMNS) - ids - {"part_id"}:
        value = _payload_number(result[key], key,
                                nullable=key not in {"current_gpa_credits", "start_agpa_points"},
                                nonnegative=True)
        result[key] = float(value)
    if not 0 <= result["start_agpa_points"] <= 4:   
        raise ValueError("start_agpa_points must be between 0 and 4.")
    result["part_id"] = part_id
    result["part_semester"], result["gpa_trend_delta"] = derive_semester_and_gpa_trend(
        part_id, result["gpa_prev_1"], result["gpa_prev_2"],
    )
    result["gpa_trend_missing"] = int(pd.isna(result["gpa_trend_delta"]))
    return result


def _explicitly_ineligible(record):
    rejected = False
    for key in ("is_requestable", "allow_register"):
        if key not in record or record[key] is None or pd.isna(record[key]):
            continue
        flag = str(record[key]).strip().upper()
        if flag in {"N", "NO", "FALSE", "0"}:
            rejected = True
        elif flag not in {"Y", "YES", "TRUE", "1"}:
            raise ValueError(f"Invalid eligibility flag {key}.")
    return rejected


def normalize_candidate_payloads(records, snapshot):
    """Accept eligible ready candidates without catalog joins or attempt rebuilds.

    attempt_number must match clean_student_course's chronological count per
    (student_id, course_id), across degrees, assigned before finish-status and
    GPA-inclusion filters. It is not a failure count. Backend supplies it.
    """
    if not isinstance(records, list) or any(not isinstance(row, Mapping) for row in records):
        raise ValueError("candidates must be a list of mappings.")
    columns = [*CANDIDATE_COURSE_COLUMNS, "course_name", "previous_course_status", "candidate_group"]
    if any("requirement_group_id" in row for row in records):
        columns.append("requirement_group_id")
    normalized = []
    for record in records:
        _validate_payload_identity(record, snapshot["student_id"], snapshot["degree_id"],
                                   snapshot["part_id"], required=False)
        if _explicitly_ineligible(record):
            continue
        missing = set([*CANDIDATE_COURSE_COLUMNS, "course_name"]) - record.keys()
        if missing:
            raise ValueError(f"Incomplete Backend candidate: {sorted(missing)}")
        row = {key: record[key] for key in [*CANDIDATE_COURSE_COLUMNS, "course_name"]}
        for key in ("course_id", "plan_requirement_type_id"):
            row[key] = _payload_id(row[key], key)
        row["course_credits"] = _payload_number(row["course_credits"], "course_credits", nonnegative=True)
        attempt = _payload_number(row["attempt_number"], "attempt_number")
        if attempt < 1 or attempt != attempt.to_integral_value():
            raise ValueError("attempt_number must be a positive integer supplied by Backend.")
        row["attempt_number"] = int(attempt)
        for key in ("plan_year_order", "plan_semester_order", "plan_credits_count"):
            row[key] = float(_payload_number(row[key], key, nullable=True, nonnegative=True))
        row["previous_course_status"], row["candidate_group"] = classify_candidate_status(record)
        if "requirement_group_id" in columns:
            row["requirement_group_id"] = _payload_id(record.get("requirement_group_id"), "requirement_group_id")
        normalized.append(row)
    rows = pd.DataFrame(normalized, columns=columns)
    if rows.course_id.duplicated().any():
        raise ValueError("Candidate course IDs must be unique after normalization.")
    return rows.sort_values("course_id", kind="stable").reset_index(drop=True)


def normalize_request_payload(request):
    """Normalize core request fields; legacy policy names are opaque metadata."""
    if not isinstance(request, Mapping):
        raise ValueError("request_payload must be a mapping.")
    identity = {key: _payload_id(request.get(key), key) for key in ("student_id", "degree_id")}
    identity["part_id"] = _payload_part(request.get("part_id"))
    target = request.get("target_credits")
    if target is not None:
        _, exact = resolve_credit_bounds(target)
        if request.get("min_credits") is not None or request.get("max_credits") is not None:
            resolve_credit_bounds(None, request.get("min_credits"), request.get("max_credits"))
    else:
        _, exact = resolve_credit_bounds(None, request.get("min_credits"), request.get("max_credits"))
    failed = _payload_number(request.get("allowed_failed_repeat_credits"),
                             "allowed_failed_repeat_credits", nonnegative=True)
    withdrawn = (_payload_number(request["allowed_withdrawn_repeat_credits"],
                                 "allowed_withdrawn_repeat_credits", nonnegative=True)
                 if "allowed_withdrawn_repeat_credits" in request else None)
    policies = normalize_requirement_policies(request.get("requirement_policies"))
    group_policies = request.get("requirement_group_policies")
    constraints = PlanConstraints(exact, policies, failed, withdrawn,
                                  requirement_group_policies=group_policies,
                                  max_new_courses=request.get("max_new_courses"))
    metadata = {key: request[key] for key in ("allowed_fail_credits", "allowed_pass_position_type") if key in request}
    return identity, constraints, metadata


def prepare_recommendation_payloads(*, student_payload, request_payload):
    """Prepare {snapshot, candidates} + request mappings, without scoring or I/O.

    Requirements are records keyed by plan_requirement_type_id. This schema is
    an in-process adapter contract, not a published Backend transport contract.
    """
    if not isinstance(student_payload, Mapping) or not {"snapshot", "candidates"} <= student_payload.keys():
        raise ValueError("student_payload requires snapshot and candidates.")
    identity, constraints, metadata = normalize_request_payload(request_payload)
    snapshot = normalize_student_payload(student_payload["snapshot"], **identity)
    candidates = normalize_candidate_payloads(student_payload["candidates"], snapshot)
    missing = set(candidates.plan_requirement_type_id) - constraints.requirement_policies.keys()
    if missing:
        raise ValueError(f"Missing requirement policies for candidates: {sorted(missing)}")
    return PreparedRecommendationInputs(snapshot, candidates, constraints, metadata)
