"""Student identity, source provenance and semester-history validation.

Typed values returned here retain the existing numeric and temporal contracts;
feature calculations remain in adapters.student and src.features.
"""
from collections.abc import Mapping
import math

from src.features.frozen_history import previous_academic_part
from src.recommendation.plan_generation import sum_credit_values

from .common import ApiError, binding, check_record_identity, identifier, number, part, response_data, sourced


DIRECT = {"faculty_id": "FACULTY_ID", "grade_version_id": "GRADE_VERSION_ID",
          "start_agpa_points": "START_AGPA_POINTS", "start_total_in_courses": "START_TOTAL_IN_COURSES",
          "start_total_in_credits": "START_TOTAL_IN_CREDITS", "degree_credits_count": "DEGREE_CREDITS_COUNT"}
SOURCED_FIELDS = {"current_gpa_credits", "prior_total_reg_courses", "prior_total_reg_credits",
                 "prior_total_fail_courses", "prior_total_fail_credits", "prior_registered_semesters"}
COUNTS = {"start_total_in_courses", "prior_total_reg_courses", "prior_total_fail_courses", "prior_registered_semesters"}


def extract_student_info(request, result):
    """Check the envelope and all current identities before building a snapshot."""
    expected = binding(request, "student")
    data = response_data(request.get("student_api_response"), "student")
    check_record_identity(request["student_api_response"], expected)
    check_record_identity(data, expected)
    info, histories = data.get("studentDegreeInfo"), data.get("studentSummaryInfo")
    if not isinstance(info, Mapping) or not isinstance(histories, list):
        raise ApiError("INVALID_STUDENT_SHAPE", "Student degree information and summary rows are required.")
    check_record_identity(info, expected, required=True)
    result.checks["identity"] = "payload_verified"
    return expected, info, histories


def student_field_value(info, key, source):
    if source not in info or info[source] is None:
        raise ApiError("MISSING_FIELD", "Required student source field is missing.", field=key)
    if key in {"faculty_id", "grade_version_id"}:
        return identifier(info[source], source)
    return number(info[source], key, integer=key in COUNTS)


def validate_mapped_student_value(key, value):
    if not math.isfinite(value):
        raise ApiError("INVALID_NUMBER", "Numeric value exceeds supported range.", field=key)
    if key == "start_agpa_points" and value > 4:
        raise ApiError("INVALID_GPA", "Starting GPA must be between zero and four.", field=key)


def diploma_value(info, key, aliases):
    present = [info[name] for name in aliases if name in info and info[name] is not None]
    if not present:
        raise ApiError("MISSING_FIELD", "Required diploma information is missing.", field=key)
    values = [identifier(v, key) if key.endswith("id") else number(v, key) for v in present]
    if any(value != values[0] for value in values[1:]):
        raise ApiError("CONFLICTING_ALIASES", "Configured source aliases conflict.", field=key)
    return values[0]


def validate_diploma_gpa(value):
    if not math.isfinite(value):
        raise ApiError("INVALID_NUMBER", "Diploma value exceeds supported range.", field="diploma_gpa")


def validate_student_supplements(values):
    if set(values) - SOURCED_FIELDS:
        raise ApiError("UNSUPPORTED_SUPPLEMENT", "Only documented student supplement fields are accepted.")


def missing_student_supplement(key, context, official_credits, result):
    """Preserve the distinction between an unavailable value and an invalid GPA denominator."""
    if key in {"current_gpa_credits", "prior_total_reg_credits"} and official_credits is not None:
        return
    if key == "current_gpa_credits" and context.get("total_reg_credits_source") is None:
        raise ApiError("GPA_DENOMINATOR_TEMPORALLY_AMBIGUOUS",
                       "Establish TOTAL_REG_CREDITS timing and university counting rules, or supply a sourced beginning-of-semester GPA-credit override.",
                       field=key)
    result.unavailable_fields.append(key)


def student_supplement_value(record, key, expected, official_credits):
    value = sourced(record, expected["part_id"], key)
    if (key in {"current_gpa_credits", "prior_total_reg_credits"}
            and part(record["as_of_part"], key + ".as_of_part") != previous_academic_part(expected["part_id"])):
        raise ApiError("GPA_DENOMINATOR_TEMPORALLY_AMBIGUOUS", "GPA-credit snapshots must describe the immediately preceding academic semester, not older cumulative totals.", field=key)
    numeric_value = number(value, key, integer=key in COUNTS)
    if (key in {"current_gpa_credits", "prior_total_reg_credits"} and official_credits is not None
            and numeric_value != official_credits):
        raise ApiError("CONFLICTING_STUDENT_SOURCE", "The supplement conflicts with established official beginning-of-semester registered credits.", field=key)
    return numeric_value


def validate_student_source_match(info, key, numeric_value, mapped_value):
    if not math.isfinite(mapped_value):
        raise ApiError("INVALID_NUMBER", "Supplement value exceeds supported range.", field=key)
    original_key = {"prior_total_fail_courses": "TOTAL_FAIL_COURSES", "prior_total_fail_credits": "TOTAL_FAIL_CREDITS",
                    "current_gpa_credits": "CURRENT_GPA_CREDITS"}.get(key, key.upper())
    if original_key in info and numeric_value != number(info[original_key], original_key, integer=key in COUNTS):
        raise ApiError("CONFLICTING_STUDENT_SOURCE", "Beginning-of-semester student sources conflict.", field=key)


def _official_gpa_credits(info, evidence, expected):
    """Validate trusted PHP timing/rule attestation and reconcile its exact credits.

    The subtraction is part of the additive accounting proof. Keeping it here
    avoids validating the same credit inputs twice or changing their meaning.
    """
    if evidence is None:
        return None, None
    field = "current_gpa_credits"
    if (not isinstance(evidence, Mapping)
            or not isinstance(evidence.get("source"), str) or not evidence["source"].strip()
            or not isinstance(evidence.get("rules_reference"), str) or not evidence["rules_reference"].strip()):
        raise ApiError("MISSING_PROVENANCE", "Official credit timing requires a source and university inclusion/exclusion rules reference.", field=field)
    if part(evidence.get("target_part"), "total_reg_credits_source.target_part") != expected["part_id"]:
        raise ApiError("IDENTITY_MISMATCH", "Official registered-credit semantics target another semester.", field=field)
    cutoff = part(evidence.get("as_of_part"), "total_reg_credits_source.as_of_part")
    total = number(info.get("TOTAL_REG_CREDITS"), "TOTAL_REG_CREDITS")
    timing = evidence.get("timing")
    if timing == "beginning_of_semester":
        if cutoff != previous_academic_part(expected["part_id"]):
            raise ApiError("GPA_DENOMINATOR_TEMPORALLY_AMBIGUOUS", "Beginning-of-semester registered credits must be attested through the immediately preceding academic semester.", field=field)
        return total, "php_attested_total_reg_credits_beginning"
    if timing != "end_of_semester":
        raise ApiError("GPA_DENOMINATOR_TEMPORALLY_AMBIGUOUS", "Official registered-credit timing must be beginning_of_semester or end_of_semester.", field=field)
    if cutoff != expected["part_id"]:
        raise ApiError("GPA_DENOMINATOR_TEMPORALLY_AMBIGUOUS", "Post-semester registered credits must describe the finalized target semester.", field=field)
    if (evidence.get("semester_complete") is not True or evidence.get("additive_credit_accounting") is not True
            or evidence.get("semester_gpa_counted_credits") is None):
        raise ApiError("GPA_DENOMINATOR_DERIVATION_UNPROVEN", "Post-semester totals require confirmed completeness, additive university accounting and the official target-semester GPA-counted credit increment.", field=field)
    increment = number(evidence["semester_gpa_counted_credits"], "total_reg_credits_source.semester_gpa_counted_credits")
    registered = number(info.get("SEMESTER_REG_CREDITS"), "SEMESTER_REG_CREDITS")
    if increment > registered or increment > total:
        raise ApiError("CONFLICTING_STUDENT_SOURCE", "Official target-semester GPA-counted credits exceed registered credits or the cumulative count.", field=field)
    return sum_credit_values((total, increment.copy_negate())), "php_attested_total_reg_credits_derived"


def normalize_student_history(histories, expected, result):
    """Validate every identity first, then normalize usable historical rows."""
    records, seen = [], set()
    required = {"STUDENT_STATUS_ID", "STUDENT_ID", "DEGREE_ID", "PART_ID", "GPA_POINTS", "SEMESTER_REG_COURSES"}
    for raw in histories:
        if not isinstance(raw, Mapping):
            raise ApiError("INVALID_HISTORY_ROW", "Semester summaries must be records.")
        check_record_identity(raw, expected, historical=True, required=True)
    for raw in histories:
        if not required.issubset(raw):
            result.unavailable_fields.extend(["gpa_prev_1", "gpa_prev_2", "observed_gap_semesters"])
            result.checks["student_history_schema"] = "unavailable"
            return None
        semester = part(raw["PART_ID"])
        status = identifier(raw["STUDENT_STATUS_ID"], "STUDENT_STATUS_ID")
        if semester in seen or any(row["student_status_id"] == status for row in records):
            raise ApiError("DUPLICATE_HISTORY", "Semester summary keys must be unique.")
        seen.add(semester)
        record = {"student_status_id": status, "student_id": expected["student_id"], "degree_id": expected["degree_id"],
                  "part_id": semester, "semester_reg_courses": number(raw["SEMESTER_REG_COURSES"], "SEMESTER_REG_COURSES", integer=True),
                  "gpa_points": float(number(raw["GPA_POINTS"], "GPA_POINTS", nullable=True)) if raw["GPA_POINTS"] is not None else None}
        if record["gpa_points"] is not None and record["gpa_points"] > 4:
            raise ApiError("INVALID_GPA", "Historical GPA must be between zero and four.", field="GPA_POINTS")
        for key in ("last_enrolled_gpa", "total_reg_courses", "total_reg_credits", "total_fail_courses", "total_fail_credits", "reg_total_semesters"):
            if key.upper() in raw:
                val = number(raw[key.upper()], key, nullable=True,
                             integer=key in {"total_reg_courses", "total_fail_courses", "reg_total_semesters"})
                if key == "last_enrolled_gpa" and val is not None and val > 4:
                    raise ApiError("INVALID_GPA", "Previous enrolled GPA must be between zero and four.", field=key)
                record[key] = None if val is None else float(val)
                if record[key] is not None and not math.isfinite(record[key]):
                    raise ApiError("INVALID_NUMBER", "History value exceeds supported range.", field=key)
        records.append(record)
    return records


def validate_history_target(info, expected, records):
    count = number(info.get("SEMESTER_REG_COURSES"), "SEMESTER_REG_COURSES", integer=True, nullable=True)
    status = identifier(info.get("STUDENT_STATUS_ID", "api-target-status"), "STUDENT_STATUS_ID")
    if any(row["student_status_id"] == status for row in records):
        raise ApiError("DUPLICATE_HISTORY", "Target and historical status keys conflict.")
    return count, status


def validate_student_counter(snapshot, key, value):
    if value is not None and snapshot[key] is not None and snapshot[key] != value:
        raise ApiError("CONFLICTING_STUDENT_SOURCE", "Student counter sources conflict.", field=key)


def validate_grade_version(snapshot, grade_scale, result):
    if grade_scale is not None and snapshot["grade_version_id"] is not None:
        try:
            grade_scale.validate_versions([snapshot["grade_version_id"]])
            result.checks["grade_scale"] = "verified"
        except ValueError:
            result.add(ApiError("UNSUPPORTED_GRADE_VERSION", "Grade version is unsupported.", field="grade_version_id"))
