"""Input composition and local evaluation views; recommendation remains in FastAPI."""
from copy import deepcopy

import pandas as pd

from src import paths
from src.api.schemas import RecommendationRequest
from src.api.catalog import load_catalog
from src.recommendation.inputs import _payload_id, _payload_part, normalize_candidates


def combine_request(student_id, degree_id, part_id, cutoff, credits,
                    student, courses, student_context, courses_context):
    context = deepcopy(student_context)
    for key, value in courses_context.items():
        if key in context and isinstance(value, dict) and isinstance(context[key], dict):
            if any(item in context[key] and context[key][item] != record for item, record in value.items()):
                raise ValueError("Conflicting integration context sources.")
            context[key].update(value)
        elif key in context and context[key] != value:
            raise ValueError("Conflicting integration context sources.")
        else:
            context[key] = deepcopy(value)
    identity = {"student_id": student_id, "degree_id": degree_id, "part_id": part_id}
    request = {**identity, "history_as_of_part": cutoff, "target_credits": credits, "top_k": 3,
        "mode": "normal", "student_api_response": student, "courses_api_response": courses,
        "source_contexts": {"student": identity.copy(), "courses": identity.copy()},
        "integration_context": context}
    RecommendationRequest.model_validate(request)
    return request


def comparison_rows(result, observed):
    rows = []
    if observed is not None:
        summary = observed["summary"]
        rows.append({"plan": "Actual registered plan", "credits": summary["total_credits"],
            "predicted_semester_gpa": summary["expected_plan_gpa"],
            "predicted_cumulative_gpa": summary["projected_cumulative_gpa"],
            "actual_semester_gpa": observed.get("official_semester_gpa"),
            "actual_cumulative_gpa": observed.get("official_cumulative_gpa")})
    for plan in result.get("recommendations", []):
        rows.append({"plan": f"Top {plan['rank']}", "credits": plan["total_credits"],
            "predicted_semester_gpa": plan["expected_plan_gpa"],
            "predicted_cumulative_gpa": plan["projected_cumulative_gpa"],
            "actual_semester_gpa": None, "actual_cumulative_gpa": None})
    return rows


def canonical_identity(identity):
    return {"student_id": _payload_id(identity.get("student_id"), "student_id"),
            "degree_id": _payload_id(identity.get("degree_id"), "degree_id"),
            "part_id": _payload_part(identity.get("part_id"))}


def _filters(identity):
    identity = canonical_identity(identity)
    return [("student_id", "==", str(identity["student_id"])),
            ("degree_id", "==", str(identity["degree_id"])),
            ("part_id", "==", int(identity["part_id"]))]


def registered_courses(identity, registration=None):
    identity = canonical_identity(identity)
    if registration is None:
        if not paths.CLEAN_REGISTRATION_ROSTER_PATH.is_file():
            return []
        raw = pd.read_parquet(paths.CLEAN_REGISTRATION_ROSTER_PATH, filters=_filters(identity))
    else:
        if not isinstance(registration.get("source"), str) or not registration["source"].strip():
            raise ValueError("Actual registration requires a source.")
        if canonical_identity(registration) != identity:
            raise ValueError("Actual registration identity does not match the request.")
        raw = pd.DataFrame(registration.get("courses", []))
    if raw.empty:
        return []
    # Reuse the existing observed-plan path: IDs/credits, catalog, strictly prior attempts.
    supplied = raw[["course_id", "course_credits"]].copy()
    catalog = load_catalog()
    history = pd.read_parquet(paths.CLEAN_STUDENT_COURSE_PATH,
        columns=["student_id", "course_id", "part_id", "attempt_number"],
        filters=[("student_id", "==", str(identity["student_id"])),
                 ("part_id", "<", int(identity["part_id"]))])
    normalized, _ = normalize_candidates(supplied, catalog, history, **identity)
    if len(normalized) != len(supplied):
        raise ValueError("Actual registration contains ambiguous or missing courses.")
    return normalized.to_dict("records")


def local_actual_outcomes(identity):
    identity = canonical_identity(identity)
    if not paths.PLAN_GPA_COURSE_PREDICTIONS_PATH.is_file():
        return None
    frame = pd.read_parquet(paths.PLAN_GPA_COURSE_PREDICTIONS_PATH, filters=_filters(identity),
        columns=["course_id", "course_credits", "actual_mark", "actual_points"])
    if frame.empty:
        return None
    result = {**identity, "source": "Stable rebuilt finalized outcome tables",
              "finalized": True, "courses": frame.to_dict("records")}
    status = pd.read_parquet(paths.CLEAN_STUDENT_STATUS_PATH, filters=_filters(identity))
    if len(status) == 1:
        for source, target in (("gpa_points", "semester_gpa"), ("end_agpa_points", "cumulative_gpa")):
            if source in status and pd.notna(status[source].iloc[0]):
                result[target] = float(status[source].iloc[0])
    return result
