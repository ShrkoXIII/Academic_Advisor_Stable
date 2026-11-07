import numpy as np
import pandas as pd
import pytest

from src.evaluation import evaluate_plan_gpa as evaluation
from src.grade_scale import GradeScale
from src.features.feature_contract import FEATURE_ENGINEERING_VERSION


class FixedMarks:
    def predict(self, matrix):
        assert len(matrix) == 3
        return np.array([-10.0, 75.0, 110.0])


def test_predict_course_points_preserves_audit_and_quality_points(monkeypatch):
    monkeypatch.setattr(evaluation, "prepare_model_matrix", lambda frame, levels: frame)
    frame = pd.DataFrame({
        "student_course_id": [1, 2, 3], "student_id": ["A"] * 3,
        "degree_id": ["D"] * 3, "part_id": [20251] * 3,
        "course_id": ["C1", "C2", "C3"], "course_name_sl": ["a", "b", "c"],
        "course_credits": [2, 3, 1], "grade_version_id": [1] * 3,
        "final_mark": [20, 70, 90], "points": [0.0, 2.0, 4.0],
        "gpa_points": [2.0] * 3,
    })
    scale = GradeScale(pd.DataFrame({
        "grade_version_id": [1, 1], "from_percent": [50, 75],
        "points": [2.0, 3.0], "grade_show": ["C", "B"],
    }))
    result = evaluation.predict_course_points(frame, FixedMarks(), {}, scale)
    assert {"student_course_id", "student_id", "degree_id", "part_id", "course_id",
            "course_name_sl", "course_credits", "grade_version_id", "actual_mark",
            "actual_points", "source_semester_gpa", "predicted_mark", "predicted_points",
            "predicted_grade", "mark_error", "points_error", "actual_quality_points",
            "predicted_quality_points"} <= set(result)
    assert not {"final_mark", "points", "gpa_points"} & set(result)
    np.testing.assert_array_equal(result.predicted_mark, [0, 75, 100])
    np.testing.assert_array_equal(result.actual_mark, [20, 70, 90])
    np.testing.assert_array_equal(result.actual_points, [0, 2, 4])
    np.testing.assert_array_equal(result.source_semester_gpa, [2, 2, 2])
    np.testing.assert_array_equal(result.predicted_points, [0, 3, 3])
    np.testing.assert_array_equal(result.mark_error, [-20, 5, 10])
    np.testing.assert_array_equal(result.points_error, [0, 1, -1])
    np.testing.assert_array_equal(result.actual_quality_points, [0, 6, 4])
    np.testing.assert_array_equal(result.predicted_quality_points, [0, 9, 3])


def test_aggregate_plan_gpa_uses_student_degree_part_and_credit_weighting():
    courses = pd.DataFrame({
        "student_id": ["A", "A", "A", "A", "B"],
        "degree_id": ["D1", "D1", "D2", "D1", "D1"],
        "part_id": [20251, 20251, 20251, 20252, 20251],
        "course_id": ["C1", "C2", "C3", "C4", "C5"],
        "course_credits": [3, 1, 2, 1, 1],
        "actual_quality_points": [9, 2, 8, 4, 1],
        "predicted_quality_points": [12, 1, 6, 3, 2],
        "source_semester_gpa": [2.5, 2.5, 4, 4, 1],
    })
    plans = evaluation.aggregate_plan_gpa(courses)
    assert len(plans) == 4
    row = plans.set_index(["student_id", "degree_id", "part_id"]).loc[("A", "D1", 20251)]
    assert row.course_count == 2
    assert row.total_credits == 4
    assert row.actual_quality_points == 11
    assert row.predicted_quality_points == 13
    assert row.actual_plan_gpa == pytest.approx(11 / 4)
    assert row.predicted_plan_gpa == pytest.approx(13 / 4)
    assert row.plan_gpa_error == pytest.approx(0.5)
    assert row.plan_gpa_absolute_error == pytest.approx(0.5)
    assert row.formula_vs_source_gpa_error == pytest.approx(0.25)


def test_summarize_plan_errors_includes_threshold_boundaries():
    plans = pd.DataFrame({"plan_gpa_error": [-0.25, 0.5, -1.0, 2.0],
                          "total_credits": [1, 2, 3, 4]})
    result = evaluation.summarize_plan_errors(plans)
    assert result["plans"] == 4
    assert result["mae"] == pytest.approx(0.9375)
    assert result["credits_weighted_mae"] == pytest.approx(1.225)
    assert result["rmse"] == pytest.approx(np.sqrt(5.3125 / 4))
    assert result["bias"] == pytest.approx(0.3125)
    assert result["median_absolute_error"] == pytest.approx(0.75)
    assert result["within_0_25"] == pytest.approx(0.25)
    assert result["within_0_50"] == pytest.approx(0.5)
    assert result["within_1_00"] == pytest.approx(0.75)


def test_build_metrics_report_preserves_contract_and_parts():
    courses = pd.DataFrame({"course_id": [1, 2, 3]})
    plans = pd.DataFrame({"part_id": [20231, 20243],
                          "plan_gpa_error": [0.25, -0.5],
                          "total_credits": [3, 6]})
    report = evaluation.build_metrics_report(courses, plans)
    assert report["course_rows"] == 3
    assert report["overall"]["plans"] == 2
    assert report["overall"]["mae"] == pytest.approx(0.375)
    assert list(report["by_part"]) == ["20231", "20243"]
    assert report["by_part"]["20231"]["mae"] == pytest.approx(0.25)
    assert report["by_part"]["20243"]["mae"] == pytest.approx(0.5)
    assert report["evaluation_unit"] == "student_id + degree_id + part_id"
    assert report["actual_plan_gpa_formula"] == "sum(course_credits * actual_points) / sum(course_credits)"
    assert report["predicted_plan_gpa_formula"] == "sum(course_credits * predicted_points) / sum(course_credits)"
    assert report["feature_engineering_version"] == FEATURE_ENGINEERING_VERSION


def test_import_does_not_run_evaluation():
    assert callable(evaluation.main)
