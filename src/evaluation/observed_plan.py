"""Observed-plan adapter using the existing Stage 2 calculations.

The prediction interface accepts beginning-of-semester features only. Actual
outcomes have a separate post-prediction interface and are never model inputs.
"""
from collections.abc import Mapping

import numpy as np
import pandas as pd

from src.data.cleaning.cleaning_utils import clean_id
from src.features.temporal_features import COURSE_HISTORY_COLUMNS
from src.features.frozen_history import validate_history_selection
from src.recommendation.inputs import (
    _payload_id, _payload_part, _payload_number, normalize_candidate_payloads, normalize_student_payload,
)
from src.recommendation.plan_generation import build_plan_rows
from src.recommendation.plan_scoring import summarize_scored_plans


def predict_observed_plan(engine, snapshot, courses, *, history_as_of_part):
    identity = {key: _payload_id(snapshot.get(key), key) for key in ("student_id", "degree_id")}
    identity["part_id"] = _payload_part(snapshot.get("part_id"))
    normalized = normalize_student_payload(snapshot, **identity)
    target = normalized["part_id"]
    validate_history_selection(target, history_as_of_part)
    if any(stage["training_as_of_part"] >= target for stage in engine.artifacts.manifest["stages"].values()):
        raise ValueError("Model training must precede the observed target semester.")
    if not isinstance(courses, list) or any(not isinstance(row, Mapping) for row in courses):
        raise ValueError("Registered courses must be a list of records.")
    # Eligibility selects alternatives; it must not remove an observed registration.
    registered = [{key: value for key, value in row.items()
                   if key not in {"is_requestable", "allow_register"}} for row in courses]
    base = normalize_candidate_payloads(registered, normalized)
    if len(base) != len(courses):
        raise ValueError("The complete registered plan is required for prediction.")
    if base.empty:
        raise ValueError("Supply the actual registered courses with their pre-target features.")
    history = engine.history_manager.capture(target_part=target,
        history_as_of_part=history_as_of_part, allow_older_history=False)
    for key, value in normalized.items():
        base[key] = value
    values = history.apply(base)
    base[COURSE_HISTORY_COLUMNS] = values[COURSE_HISTORY_COLUMNS].to_numpy()
    rows = build_plan_rows(base, [tuple(range(len(base)))])
    scored = engine._score_stage2(rows)
    summary = summarize_scored_plans(scored, normalized["start_agpa_points"],
                                     normalized["current_gpa_credits"]).iloc[0].to_dict()
    output = ["course_id", "course_name", "course_credits", "predicted_mark",
              "expected_points", "expected_grade", "fail_probability"]
    return {"identity": identity, "courses": scored[output].copy(), "summary": summary,
            "history_as_of_part": history_as_of_part,
            "prediction_scope": "observed_plan_descriptive",
            "projected_gpa_method": "standard_additive_without_repeat_replacement"}


def attach_actual_outcomes(forecast, actual):
    if (actual.get("finalized") is not True or not isinstance(actual.get("source"), str)
            or not actual["source"].strip()):
        raise ValueError("Actual outcomes require a source and explicit finalization.")
    for key, expected in forecast["identity"].items():
        if str(actual.get(key)) != str(expected):
            raise ValueError("Actual outcomes do not match the forecast identity.")
    columns = ["course_id", "actual_mark", "actual_points"]
    results = pd.DataFrame(actual.get("courses", []))
    if results.empty:
        results = pd.DataFrame(columns=columns)
    else:
        if not {"course_id", "course_credits"}.issubset(results.columns):
            raise ValueError("Actual course IDs and credits are required.")
        results["course_id"] = clean_id(results["course_id"])
        if results.course_id.isna().any() or results.course_id.duplicated().any():
            raise ValueError("Actual course IDs must be known and unique.")
        expected = forecast["courses"].set_index("course_id").course_credits
        for row in results.to_dict("records"):
            if (row["course_id"] not in expected.index
                    or _payload_number(row["course_credits"], "course_credits", nonnegative=True)
                    != _payload_number(expected[row["course_id"]], "course_credits", nonnegative=True)):
                raise ValueError("Actual course identity or credits do not match the registered plan.")
        for key, maximum in (("actual_mark", 100), ("actual_points", 4)):
            if key in results and results[key].map(lambda value: isinstance(value, (bool, np.bool_))).any():
                raise ValueError("Actual marks and points must be numbers, not booleans.")
            results[key] = pd.to_numeric(results.get(key, pd.Series(index=results.index, dtype=float)), errors="raise")
            known = results[key].dropna()
            if not np.isfinite(known).all() or not known.between(0, maximum).all():
                raise ValueError("Actual marks or points are outside the source contract.")
    joined = forecast["courses"].merge(results[columns], on="course_id", how="left", validate="one_to_one")
    joined["mark_error"] = joined.predicted_mark - joined.actual_mark
    joined["points_error"] = joined.expected_points - joined.actual_points
    official = {}
    for key in ("semester_gpa", "cumulative_gpa"):
        value = actual.get(key)
        number = None if value is None else float(_payload_number(value, key, nonnegative=True))
        if number is not None and not 0 <= number <= 4:
            raise ValueError("Official GPA must be finite and within zero to four.")
        official[key] = number
    errors = joined.mark_error.dropna()
    complete = joined.actual_points.notna().all()
    course_gpa = (float((joined.course_credits * joined.actual_points).sum() / joined.course_credits.sum())
                  if complete else None)
    return {**forecast, "courses": joined, "actual_source": actual["source"],
            "official_semester_gpa": official["semester_gpa"],
            "official_cumulative_gpa": official["cumulative_gpa"],
            "actual_course_gpa": course_gpa,
            "mark_mae": float(errors.abs().mean()) if len(errors) else None,
            "matched_outcome_count": int(joined.actual_mark.notna().sum())}
