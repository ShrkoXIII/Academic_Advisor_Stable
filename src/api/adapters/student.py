"""Build beginning-of-semester snapshots without HTTP or new feature formulas."""
import pandas as pd

from src.data.academic_calendar import count_regular_semesters_between, is_regular_semester
from src.features.temporal_features import compute_student_gpa_history, add_student_history_features
from src.recommendation.inputs import BACKEND_SNAPSHOT_COLUMNS

from ..validators.common import ApiError, ValidationResult, number
from ..validators.student import (
    COUNTS, DIRECT, SOURCED_FIELDS, _official_gpa_credits, diploma_value, extract_student_info,
    missing_student_supplement, normalize_student_history, student_field_value, student_supplement_value,
    validate_diploma_gpa, validate_grade_version, validate_history_target, validate_mapped_student_value,
    validate_student_counter, validate_student_source_match, validate_student_supplements,
)


def adapt_student(request, *, settings, grade_scale=None):
    """Return the existing diagnostic result, with a snapshot when construction completes."""
    result = ValidationResult(checks={"identity": "unavailable", "grade_scale": "unavailable"})
    try:
        expected, info, histories = extract_student_info(request, result)
        result.normalized = build_student_snapshot(
            info, histories, expected, request.get("integration_context") or {},
            settings=settings, grade_scale=grade_scale, result=result)
    except ApiError as error:
        result.add(error)
    return result


def build_student_snapshot(info, histories, expected, context, *, settings, grade_scale, result):
    """Map sources, add historical features, and retain field-level diagnostics."""
    snapshot = {key: None for key in BACKEND_SNAPSHOT_COLUMNS}
    snapshot.update(expected)
    map_student_fields(snapshot, info, settings, result)
    add_sourced_student_values(snapshot, info, expected, context, result)
    add_history_features(histories, info, expected, snapshot, result)
    denominator, failed = snapshot["prior_total_reg_credits"], snapshot["prior_total_fail_credits"]
    snapshot["prior_fail_credit_ratio"] = None if denominator in (None, 0) or failed is None else failed / denominator
    validate_grade_version(snapshot, grade_scale, result)
    add_snapshot_features(snapshot, expected)
    result.summary["field_readiness"] = {key: "unavailable" if value is None else "ready"
                                         for key, value in snapshot.items() if key not in expected}
    return snapshot


def map_student_fields(snapshot, info, settings, result):
    """Map degree fields and configured diploma aliases, preserving partial values."""
    for key, source in DIRECT.items():
        try:
            value = student_field_value(info, key, source)
            snapshot[key] = value if key in {"faculty_id", "grade_version_id"} else float(value)
            if key not in {"faculty_id", "grade_version_id"}:
                validate_mapped_student_value(key, snapshot[key])
        except ApiError as error:
            result.add(error)
    for key, aliases in (("diploma_gpa", settings.diploma_gpa_aliases),
                         ("diploma_type_id", settings.diploma_type_aliases)):
        try:
            value = diploma_value(info, key, aliases)
            snapshot[key] = value if key.endswith("id") else float(value)
            if key == "diploma_gpa":
                validate_diploma_gpa(snapshot[key])
        except ApiError as error:
            result.add(error)


def add_sourced_student_values(snapshot, info, expected, context, result):
    """Add attested beginning totals; never infer unknown academic sources."""
    values = context.get("student_values", {})
    validate_student_supplements(values)
    official_credits, official_provenance = None, None
    try:
        official_credits, official_provenance = _official_gpa_credits(
            info, context.get("total_reg_credits_source"), expected)
    except ApiError as error:
        result.add(error)
    if official_credits is not None:
        snapshot["current_gpa_credits"] = snapshot["prior_total_reg_credits"] = float(official_credits)
    for key in SOURCED_FIELDS:
        try:
            if key not in values:
                missing_student_supplement(key, context, official_credits, result)
                continue
            numeric_value = student_supplement_value(values[key], key, expected, official_credits)
            snapshot[key] = float(numeric_value)
            validate_student_source_match(info, key, numeric_value, snapshot[key])
            raw_total = {"prior_total_reg_courses": "TOTAL_REG_COURSES", "prior_total_reg_credits": "TOTAL_REG_CREDITS"}.get(key)
            if raw_total in info:
                result.summary["registration_totals_require_timing_contract"] = True
        except ApiError as error:
            result.add(error)
    result.summary["gpa_credit_provenance"] = {
        "denominator": official_provenance or ("sourced_override" if snapshot["current_gpa_credits"] is not None else "unavailable"),
        "prior_total_reg_credits": official_provenance or ("sourced_supplement" if snapshot["prior_total_reg_credits"] is not None else "unavailable"),
    }


def add_history_features(histories, info, expected, snapshot, result):
    """Reuse the feature builders after validating the historical semester rows."""
    records = normalize_student_history(histories, expected, result)
    if records is None:
        return
    target_count, target_status = validate_history_target(info, expected, records)
    target = {"student_status_id": target_status, **expected, "semester_reg_courses": target_count, "gpa_points": None}
    for key, source in (("total_reg_courses", "prior_total_reg_courses"), ("total_reg_credits", "prior_total_reg_credits"),
                        ("total_fail_courses", "prior_total_fail_courses"), ("total_fail_credits", "prior_total_fail_credits")):
        target[key] = snapshot[source]
    full_columns = {"last_enrolled_gpa", "total_reg_courses", "total_reg_credits", "total_fail_courses", "total_fail_credits", "reg_total_semesters"}
    frame = pd.DataFrame([*records, target])
    if records and all(full_columns.issubset(row) for row in records):
        target["last_enrolled_gpa"], target["reg_total_semesters"] = None, None
        frame = pd.DataFrame([*records, target])
        lookup, _ = add_student_history_features(frame[["student_status_id"]], frame[["student_status_id"]].iloc[:0], frame)
        computed = lookup[lookup.student_status_id.eq(target_status)].iloc[0]
        key = "prior_registered_semesters"
        value = None if pd.isna(computed[key]) else float(computed[key])
        validate_student_counter(snapshot, key, value)
        if snapshot[key] is None and value is not None:
            snapshot[key] = value
            result.unavailable_fields = [field for field in result.unavailable_fields if field != key]
    else:
        lookup = compute_student_gpa_history(frame)
    last = lookup[lookup.student_status_id.eq(target_status)].iloc[0]
    for key in ("gpa_prev_1", "gpa_prev_2"):
        snapshot[key] = None if pd.isna(last[key]) else float(last[key])
        if snapshot[key] is None:
            result.unavailable_fields.append(key)
    registered = [row for row in records if row["semester_reg_courses"] > 0]
    current_registered = None if target_count is None else target_count > 0
    if current_registered is None and info.get("SEMESTER_REG_CREDITS") is not None:
        if number(info["SEMESTER_REG_CREDITS"], "SEMESTER_REG_CREDITS") > 0:
            current_registered = True  # Positive credits prove positive course enrollment.
    if registered and current_registered is not None:
        previous = max(row["part_id"] for row in registered)
        snapshot["observed_gap_semesters"] = count_regular_semesters_between(previous, expected["part_id"]) + (
            is_regular_semester(expected["part_id"]) and not current_registered)
    else:
        result.unavailable_fields.append("observed_gap_semesters")
    result.checks["student_history_schema"] = "verified"
    result.summary["historical_semester_count"] = len(records)


def add_snapshot_features(snapshot, expected):
    snapshot["part_semester"] = expected["part_id"] % 10
    snapshot["gpa_trend_delta"] = (None if snapshot["gpa_prev_1"] is None or snapshot["gpa_prev_2"] is None
                                   else snapshot["gpa_prev_1"] - snapshot["gpa_prev_2"])
    snapshot["gpa_trend_missing"] = int(snapshot["gpa_trend_delta"] is None)
