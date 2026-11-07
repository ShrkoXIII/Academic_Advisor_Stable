from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json

import numpy as np
import pandas as pd

from src.features.feature_contract import (
    FEATURE_ENGINEERING_VERSION,
    BASE_FEATURES,
    load_category_levels,
    prepare_model_matrix,
    require_current_features,
)
from src.grade_scale import GradeScale
from src.paths import (
    CATEGORY_LEVELS_PATH,
    GRADE_MODEL_PATH,
    GRADE_SCALE_PATH,
    MODEL_METADATA_PATH,
    PLAN_GPA_COURSE_PREDICTIONS_PATH,
    PLAN_GPA_EVALUATION_PATH,
    PLAN_GPA_METRICS_PATH,
    PROJECT_ROOT,
    TEMPORAL_TEST_FEATURES_PATH,
)


PLAN_KEY = ["student_id", "degree_id", "part_id"]

AUDIT_COLUMNS = [
    "student_course_id",
    "student_id",
    "degree_id",
    "part_id",
    "course_id",
    "course_name_sl",
    "course_credits",
    "grade_version_id",
    "final_mark",
    "points",
    "gpa_points",
]


def predict_course_points(frame, grade_model, category_levels, grade_scale):
    result = frame[AUDIT_COLUMNS].copy()
    matrix = prepare_model_matrix(frame, category_levels)
    result["predicted_mark"] = np.clip(grade_model.predict(matrix), 0, 100)
    predicted_points, predicted_grades = grade_scale.convert(
        result["predicted_mark"],
        result["grade_version_id"],
    )
    result = result.rename(
        columns={
            "final_mark": "actual_mark",
            "points": "actual_points",
            "gpa_points": "source_semester_gpa",
        }
    )
    result["predicted_points"] = predicted_points
    result["predicted_grade"] = predicted_grades
    result["mark_error"] = result["predicted_mark"] - result["actual_mark"]
    result["points_error"] = result["predicted_points"] - result["actual_points"]
    result["actual_quality_points"] = (
        result["course_credits"] * result["actual_points"]
    )
    result["predicted_quality_points"] = (
        result["course_credits"] * result["predicted_points"]
    )
    return result


def aggregate_plan_gpa(course_predictions):
    plans = (
        course_predictions.groupby(PLAN_KEY, as_index=False, sort=False)
        .agg(
            course_count=("course_id", "size"),
            total_credits=("course_credits", "sum"),
            actual_quality_points=("actual_quality_points", "sum"),
            predicted_quality_points=("predicted_quality_points", "sum"),
            source_semester_gpa=("source_semester_gpa", "first"),
        )
    )
    plans["actual_plan_gpa"] = (
        plans["actual_quality_points"] / plans["total_credits"]
    )
    plans["predicted_plan_gpa"] = (
        plans["predicted_quality_points"] / plans["total_credits"]
    )
    plans["plan_gpa_error"] = (
        plans["predicted_plan_gpa"] - plans["actual_plan_gpa"]
    )
    plans["plan_gpa_absolute_error"] = plans["plan_gpa_error"].abs()
    plans["quality_points_error"] = (
        plans["predicted_quality_points"] - plans["actual_quality_points"]
    )
    plans["formula_vs_source_gpa_error"] = (
        plans["actual_plan_gpa"] - plans["source_semester_gpa"]
    )
    return plans.sort_values(
        "plan_gpa_absolute_error",
        ascending=False,
        kind="stable",
    ).reset_index(drop=True)


def summarize_plan_errors(plans):
    error = plans["plan_gpa_error"].to_numpy(dtype="float64")
    absolute_error = np.abs(error)
    weights = plans["total_credits"].to_numpy(dtype="float64")
    return {
        "plans": int(len(plans)),
        "mae": float(absolute_error.mean()),
        "credits_weighted_mae": float(np.average(absolute_error, weights=weights)),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
        "bias": float(error.mean()),
        "median_absolute_error": float(np.median(absolute_error)),
        "within_0_25": float(np.mean(absolute_error <= 0.25)),
        "within_0_50": float(np.mean(absolute_error <= 0.50)),
        "within_1_00": float(np.mean(absolute_error <= 1.00)),
    }


def build_metrics_report(course_predictions, plans):
    by_part = {}
    for part_id, part_plans in plans.groupby("part_id", sort=True):
        by_part[str(int(part_id))] = summarize_plan_errors(part_plans)
    return {
        "evaluation_unit": "student_id + degree_id + part_id",
        "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
        "actual_plan_gpa_formula": (
            "sum(course_credits * actual_points) / sum(course_credits)"
        ),
        "predicted_plan_gpa_formula": (
            "sum(course_credits * predicted_points) / sum(course_credits)"
        ),
        "predicted_points_source": (
            "GradeRegressor predicted_mark mapped through v_acs_grade"
        ),
        "course_rows": int(len(course_predictions)),
        "overall": summarize_plan_errors(plans),
        "by_part": by_part,
    }


def print_report(report, plans):
    overall = report["overall"]
    print("Plan-level GPA evaluation on the observed 2025 plans")
    print("Course rows:", report["course_rows"])
    print("Plans:", overall["plans"])
    print("MAE:", round(overall["mae"], 4))
    print("Credits-weighted MAE:", round(overall["credits_weighted_mae"], 4))
    print("RMSE:", round(overall["rmse"], 4))
    print("Bias (predicted - actual):", round(overall["bias"], 4))
    print("Within +/-0.25 GPA:", f"{overall['within_0_25']:.2%}")
    print("Within +/-0.50 GPA:", f"{overall['within_0_50']:.2%}")
    print("Within +/-1.00 GPA:", f"{overall['within_1_00']:.2%}")
    print("\nBy academic part:")
    for part_id, metrics in report["by_part"].items():
        print(
            f"  {part_id}: plans={metrics['plans']}, "
            f"MAE={metrics['mae']:.4f}, RMSE={metrics['rmse']:.4f}, "
            f"bias={metrics['bias']:.4f}"
        )
    print("Per-student evaluation tables are saved privately; identifiers are not printed.")


def main():
    import lightgbm as lgb

    require_current_features(json.loads(MODEL_METADATA_PATH.read_text(encoding="utf-8")))
    columns = list(dict.fromkeys([*AUDIT_COLUMNS, *BASE_FEATURES]))
    test = pd.read_parquet(TEMPORAL_TEST_FEATURES_PATH, columns=columns)
    require_current_features(test.attrs)
    course_predictions = predict_course_points(
        test,
        lgb.Booster(model_file=str(GRADE_MODEL_PATH)),
        load_category_levels(CATEGORY_LEVELS_PATH),
        GradeScale.from_parquet(GRADE_SCALE_PATH),
    )
    plans = aggregate_plan_gpa(course_predictions)
    report = build_metrics_report(course_predictions, plans)
    report["dataset_version"] = "V2"
    report["sources"] = {
        "test_features": TEMPORAL_TEST_FEATURES_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "grade_model": GRADE_MODEL_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "category_levels": CATEGORY_LEVELS_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "model_metadata": MODEL_METADATA_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "grade_scale": GRADE_SCALE_PATH.relative_to(PROJECT_ROOT).as_posix(),
    }

    PLAN_GPA_EVALUATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    course_predictions.to_parquet(
        PLAN_GPA_COURSE_PREDICTIONS_PATH,
        index=False,
    )
    plans.to_parquet(PLAN_GPA_EVALUATION_PATH, index=False)
    PLAN_GPA_METRICS_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print_report(report, plans)
    print("\nSaved:", PLAN_GPA_COURSE_PREDICTIONS_PATH)
    print("Saved:", PLAN_GPA_EVALUATION_PATH)
    print("Saved:", PLAN_GPA_METRICS_PATH)


if __name__ == "__main__":
    main()
