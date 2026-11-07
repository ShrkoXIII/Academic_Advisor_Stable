"""Local file adapters and separate, I/O-free Backend-ready payload adapters."""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.cleaning.cleaning_utils import clean_column_names, clean_id, clean_id_columns
from src.paths import (
    CLEAN_DEGREE_COURSE_PATH, CLEAN_STUDENT_COURSE_PATH,
    CLEAN_STUDENT_DIPLOMA_PATH, CLEAN_STUDENT_STATUS_PATH,
)
from src.features.temporal_features import add_student_history_features
from src.data.academic_calendar import is_regular_semester

from .constraints import PlanConstraints, normalize_requirement_policies
from .course_status import classify_candidate_status
from .plan_generation import resolve_credit_bounds


STUDENT_SNAPSHOT_COLUMNS = [
    "student_id", "degree_id", "faculty_id", "grade_version_id",
    "gpa_prev_1", "gpa_prev_2", "gpa_trend_delta", "gpa_trend_missing",
    "start_agpa_points", "start_total_in_courses", "start_total_in_credits",
    "prior_total_reg_courses", "prior_total_reg_credits", "prior_total_fail_courses",
    "prior_total_fail_credits", "prior_fail_credit_ratio", "prior_registered_semesters",
    "observed_gap_semesters", "diploma_gpa", "diploma_type_id", "degree_credits_count",
]
CANDIDATE_COURSE_COLUMNS = [
    "course_id", "course_credits", "attempt_number", "plan_course_type_id",
    "plan_requirement_type_id", "plan_year_order", "plan_semester_order", "plan_credits_count",
]


class CandidateImportError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("Candidate import failed; see import_report.json: " + "; ".join(report["errors"]))


def read_candidate_file(path):
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError("Candidate JSON must be an array of course records.")
        return pd.DataFrame(data) if data else pd.DataFrame(columns=["course_id", "course_credits"])
    raise ValueError("Candidate file must be JSON or Parquet.")


def normalize_candidates(raw, catalog, course_history, student_id, degree_id, part_id):
    student_id, degree_id = clean_id(pd.Series([student_id, degree_id])).tolist()
    rows = clean_column_names(raw)
    report = {"source_rows": len(rows), "errors": [], "warnings": []}
    missing = {"course_id", "course_credits"} - set(rows.columns)
    if missing:
        report["errors"].append(f"Missing columns: {sorted(missing)}")
        raise CandidateImportError(report)
    rows = clean_id_columns(rows, [c for c in ["student_id", "degree_id", "course_id"] if c in rows])
    if "is_requestable" in rows and "student_id" not in rows:
        report["errors"].append("A company export with is_requestable must include student_id.")
    if "student_id" in rows:
        rows = rows[rows.student_id.eq(student_id)].copy()
    if "is_requestable" in rows:
        rows = rows[rows.is_requestable.astype("string").str.strip().str.upper().eq("Y")].copy()
    report["selected_rows"] = len(rows)
    report["filtered_rows"] = report["source_rows"] - len(rows)
    if "degree_id" in rows and rows.degree_id.ne(degree_id).fillna(True).any():
        report["errors"].append("Selected rows contain a missing or different degree_id.")
    if "part_id" in rows:
        parts = pd.to_numeric(rows.part_id, errors="coerce")
        if (rows.part_id.notna() & (parts.isna() | parts.ne(int(part_id)))).any():
            report["errors"].append("Selected rows contain another semester; supply a target-specific list.")
        if parts.isna().any():
            report["warnings"].append("Null part_id rows use the explicitly supplied target semester.")
    rows["course_credits"] = pd.to_numeric(rows.course_credits, errors="coerce")
    if (~np.isfinite(rows.course_credits.astype(float)) | rows.course_credits.lt(0)).any():
        report["errors"].append("Course credits must be finite and nonnegative.")
    if rows.course_id.isna().any() or rows.course_id.eq("").any():
        report["errors"].append("Missing course_id.")
    # Ignore request-row IDs when identifying duplicate courses, but report every removal.
    report["duplicate_course_ids"] = rows.loc[rows.course_id.duplicated(keep=False), "course_id"].drop_duplicates().tolist()
    comparison = [c for c in ["course_credits", "course_type_id", "requirement_type_id", "year_order", "semester_order"] if c in rows]
    for course_id, group in rows[rows.course_id.duplicated(keep=False)].groupby("course_id"):
        if any(group[c].nunique(dropna=False) > 1 for c in comparison):
            report["errors"].append(f"Conflicting duplicate course: {course_id}")
    report["duplicate_rows_removed"] = int(rows.course_id.duplicated().sum())
    rows = rows.drop_duplicates("course_id").copy()
    name_column = next((c for c in ["course_name_sl", "course_name"] if c in rows), None)
    rows["provided_name"] = rows[name_column] if name_column else pd.Series(None, index=rows.index, dtype="string")
    rows = rows[["course_id", "course_credits", "provided_name"]]
    catalog = clean_id_columns(catalog, ["degree_id", "course_id"])
    catalog = catalog[catalog.degree_id.eq(degree_id)].copy()
    if catalog.course_id.duplicated().any():
        report["errors"].append("Degree catalog has duplicate course keys.")
    if report["errors"]:
        raise CandidateImportError(report)
    catalog = catalog.rename(columns={
        "course_credits": "catalog_credits", "course_name_sl": "catalog_name",
        "course_type_id": "plan_course_type_id", "requirement_type_id": "plan_requirement_type_id",
        "year_order": "plan_year_order", "semester_order": "plan_semester_order",
        "credits_count": "plan_credits_count",
    })
    cols = ["course_id", "catalog_credits", "catalog_name", "plan_course_type_id",
            "plan_requirement_type_id", "plan_year_order", "plan_semester_order", "plan_credits_count"]
    rows = rows.merge(catalog[cols], on="course_id", how="left", validate="one_to_one", indicator=True)
    report["unmatched_course_ids"] = rows.loc[rows._merge.eq("left_only"), "course_id"].tolist()
    conflict = rows._merge.eq("both") & rows.course_credits.ne(pd.to_numeric(rows.catalog_credits))
    report["credit_conflicts"] = rows.loc[conflict, ["course_id", "course_credits", "catalog_credits"]].to_dict("records")
    if report["unmatched_course_ids"]:
        report["errors"].append("Courses missing from the selected degree catalog.")
    if report["credit_conflicts"]:
        report["errors"].append("Supplied credits conflict with the degree catalog.")
    if report["errors"]:
        raise CandidateImportError(report)
    # Match training's attempt semantics (cleaned GPA-bearing attempts across degrees).
    history = clean_id_columns(course_history, ["student_id", "course_id"])
    prior = history[history.student_id.eq(student_id) & history.part_id.lt(int(part_id))]
    attempts = prior.groupby("course_id").attempt_number.max()
    rows["attempt_number"] = rows.course_id.map(attempts).fillna(0).astype("int64") + 1
    rows["course_name"] = rows.provided_name.combine_first(rows.catalog_name).astype("string")
    rows = rows.drop(columns=["provided_name", "catalog_name", "catalog_credits", "_merge"])
    report["candidate_count"] = len(rows)
    report["history_latest_part"] = int(prior.part_id.max()) if len(prior) else None
    return rows.sort_values("course_id", kind="stable").reset_index(drop=True), report


def build_student_snapshot(status, course_history, diplomas, student_id, degree_id, part_id):
    """Use the exact target's start fields and shifted prior history, never end fields."""
    student_id, degree_id = clean_id(pd.Series([student_id, degree_id])).tolist()
    status = status[status.student_id.eq(student_id) & status.part_id.le(int(part_id))].copy()
    target = status[status.degree_id.eq(degree_id) & status.part_id.eq(int(part_id))]
    if len(target) != 1:
        raise ValueError("No unique target-semester status. Supply a complete --snapshot JSON.")
    lookup, _ = add_student_history_features(
        target[["student_status_id"]], target[["student_status_id"]].iloc[:0], status,
    )
    snapshot = target.iloc[0].to_dict()
    snapshot.update(lookup.iloc[0].to_dict())
    prior = course_history[course_history.student_id.eq(student_id)
                           & course_history.degree_id.eq(degree_id)
                           & course_history.part_id.lt(int(part_id))]
    faculties = prior.faculty_id.dropna().unique()
    diploma = diplomas[diplomas.student_id.eq(student_id)]
    if len(faculties) != 1 or len(diploma) != 1:
        raise ValueError("Missing/ambiguous faculty or diploma data. Supply --snapshot JSON.")
    snapshot.update(diploma.iloc[0].to_dict())
    snapshot["faculty_id"] = faculties[0]
    columns = [*STUDENT_SNAPSHOT_COLUMNS, "part_id"]
    # Preserve an explicitly supplied GPA denominator without deriving it from
    # either registered credits or completed credits.
    if "current_gpa_credits" in snapshot:
        columns.append("current_gpa_credits")
    return {c: snapshot[c] for c in columns}


def validate_snapshot(snapshot, student_id, degree_id, part_id):
    frame = clean_column_names(pd.DataFrame([snapshot]))
    required = [*STUDENT_SNAPSHOT_COLUMNS, "part_id"]
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Incomplete snapshot; missing {sorted(missing)}")
    frame = clean_id_columns(frame, ["student_id", "degree_id", "faculty_id", "grade_version_id", "diploma_type_id"])
    if frame[["student_id", "degree_id", "part_id"]].isna().any().any():
        raise ValueError("Snapshot student, degree and semester must be present.")
    snapshot = frame.iloc[0].to_dict()
    ids = clean_id(pd.Series([student_id, degree_id])).tolist()
    if [snapshot["student_id"], snapshot["degree_id"]] != ids or float(snapshot["part_id"]) != int(part_id):
        raise ValueError("Snapshot student, degree or semester does not match the request.")
    # Explicit null histories remain unknown, not fabricated zero histories.
    # This serving-only field is never added to the model feature contract.
    optional = ["current_gpa_credits"] if "current_gpa_credits" in snapshot else []
    return {c: snapshot[c] for c in [*required, *optional]}


def load_local_inputs(candidate_path, student_id, degree_id, part_id, snapshot_path=None):
    # This common-student table retains the cleaner's cross-degree attempt
    # numbers and GPA-bearing outcomes, before model-specific outcome filters.
    history = pd.read_parquet(CLEAN_STUDENT_COURSE_PATH)
    candidates, report = normalize_candidates(
        read_candidate_file(candidate_path), pd.read_parquet(CLEAN_DEGREE_COURSE_PATH),
        history, student_id, degree_id, part_id,
    )
    if snapshot_path:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8-sig"))
    else:
        # Common-student filtering preserves all cleaned status semesters;
        # this is also the official feature builder's student-history source.
        status = pd.read_parquet(CLEAN_STUDENT_STATUS_PATH)
        snapshot = build_student_snapshot(status, history, pd.read_parquet(CLEAN_STUDENT_DIPLOMA_PATH),
                                          student_id, degree_id, part_id)
    return candidates, validate_snapshot(snapshot, student_id, degree_id, part_id), report


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
    result["part_semester"] = part_id % 10
    result["gpa_trend_delta"] = result["gpa_prev_1"] - result["gpa_prev_2"]
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
        for key in ("course_id", "plan_course_type_id", "plan_requirement_type_id"):
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
