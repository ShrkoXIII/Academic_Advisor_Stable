"""Plan-level GPA projection, aggregation, and ranking."""
import numpy as np
import pandas as pd

from src.features.feature_contract import prepare_model_matrix


def score_course_rows(rows, grade_model, fail_model, category_levels, grade_scale,
                      *, features=None, num_threads=4):
    """Shared 33/47 prediction processing; callers supply the stage's features.

    History and plan context are prepared upstream. Marks become GradeScale
    points; failure probabilities remain an independent output.
    """
    rows = rows.copy()
    matrix = prepare_model_matrix(rows, category_levels, model_features=features)
    marks = np.asarray(grade_model.predict(matrix, num_threads=num_threads), dtype=float)
    failures = np.asarray(fail_model.predict(matrix, num_threads=num_threads), dtype=float)
    if marks.shape != (len(rows),) or failures.shape != (len(rows),):
        raise ValueError("Model returned predictions with the wrong shape.")
    if not np.isfinite(marks).all() or not np.isfinite(failures).all():
        raise ValueError("Model returned non-finite predictions.")
    rows["predicted_mark"] = np.clip(marks, 0, 100)
    rows["expected_points"], rows["expected_grade"] = grade_scale.convert(
        rows["predicted_mark"], rows["grade_version_id"],
    )
    rows["fail_probability"] = np.clip(failures, 0, 1)
    if not np.isfinite(rows[["expected_points", "fail_probability"]].to_numpy()).all():
        raise ValueError("Model returned non-finite predictions.")
    return rows


SUMMARY_COLUMNS = [
    "plan_id", "course_count", "total_credits", "expected_quality_points",
    "expected_plan_gpa", "projected_cumulative_gpa", "expected_cumulative_gpa_gain",
    "is_expected_cumulative_improvement", "expected_failed_credits",
    "projected_gpa_requires_repeat_policy", "gpa_gain",
]


COURSE_OUTPUT_COLUMNS = [
    "plan_id", "course_id", "course_name", "course_credits", "predicted_mark",
    "expected_points", "expected_grade", "fail_probability",
]


def rank_plans(summaries):
    return summaries.sort_values(
        ["projected_cumulative_gpa", "expected_failed_credits", "expected_plan_gpa", "plan_id"],
        ascending=[False, True, False, True], kind="stable",
    ).reset_index(drop=True)


def project_cumulative_gpa(current_gpa, current_gpa_credits, expected_quality_points, plan_total_credits):
    """Standard additive projection, scalar or vector; no repeat replacement.

    For repeated courses this is only an additive scenario. The official policy
    for replacing prior quality points/credits must be supplied separately.
    """
    gpa, credits = float(current_gpa), float(current_gpa_credits)
    quality, plan_credits = np.asarray(expected_quality_points, dtype=float), np.asarray(plan_total_credits, dtype=float)
    if not np.isfinite([gpa, credits]).all() or not 0 <= gpa <= 4 or credits < 0:
        raise ValueError("GPA must be finite in [0, 4] and current_gpa_credits finite and nonnegative.")
    if (not np.isfinite(quality).all() or not np.isfinite(plan_credits).all()
            or np.any(plan_credits <= 0) or np.any(quality < 0) or np.any(quality > 4 * plan_credits)):
        raise ValueError("Plan credits must be positive and quality points finite in [0, 4 * credits].")
    return (gpa * credits + quality) / (credits + plan_credits)


def summarize_scored_plans(scored_courses, current_gpa, current_gpa_credits):
    work = scored_courses.assign(
        quality=scored_courses["course_credits"] * scored_courses["expected_points"],
        failed=scored_courses["course_credits"] * scored_courses["fail_probability"],
    )
    summary = work.groupby("plan_id", sort=False).agg(
        course_count=("course_id", "size"), total_credits=("course_credits", "sum"),
        expected_quality_points=("quality", "sum"), expected_failed_credits=("failed", "sum"),
    ).reset_index()
    summary["expected_plan_gpa"] = summary["expected_quality_points"] / summary["total_credits"]
    summary["projected_cumulative_gpa"] = project_cumulative_gpa(
        current_gpa, current_gpa_credits, summary["expected_quality_points"], summary["total_credits"],
    )
    summary["expected_cumulative_gpa_gain"] = summary["projected_cumulative_gpa"] - current_gpa
    summary["is_expected_cumulative_improvement"] = summary["projected_cumulative_gpa"].gt(current_gpa)
    # Observed prior attempts are a conservative warning, not a replacement rule.
    repeat = work["attempt_number"].gt(1).groupby(work["plan_id"]).any()
    summary["projected_gpa_requires_repeat_policy"] = summary["plan_id"].map(repeat).astype("bool")
    # Legacy field retained ONLY as the semester-GPA gap; it is not the objective.
    summary["gpa_gain"] = summary["expected_plan_gpa"] - current_gpa
    return rank_plans(summary[SUMMARY_COLUMNS])


def empty_summaries():
    return pd.DataFrame({c: pd.Series(dtype="bool" if c in ["is_expected_cumulative_improvement", "projected_gpa_requires_repeat_policy"]
                                     else "int64" if c in ["plan_id", "course_count"] else "float64")
                         for c in SUMMARY_COLUMNS})
