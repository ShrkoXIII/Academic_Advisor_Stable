"""Synthetic serving fixtures; never load trained models or student artifacts."""
import numpy as np
import pandas as pd

from src.features.feature_contract import (
    BASE_FEATURES, CATEGORICAL_FEATURES, CATEGORY_MISSING, CATEGORY_UNKNOWN,
    FEATURE_ENGINEERING_VERSION, NUMERIC_FEATURES,
)
from src.features.temporal_features import CourseHistoryState
from src.grade_scale import GradeScale
from src.recommendation.inputs import CANDIDATE_COURSE_COLUMNS, STUDENT_SNAPSHOT_COLUMNS


class RecordingModel:
    def __init__(self, value):
        self.value = value
        self.matrices = []

    def feature_name(self):
        return BASE_FEATURES.copy()

    def predict(self, matrix, **kwargs):
        self.matrices.append(matrix.copy())
        return np.full(len(matrix), self.value, dtype=float)


def synthetic_grade_scale():
    return GradeScale(pd.DataFrame({
        "grade_version_id": [1] * 4,
        "from_percent": [50., 60., 75., 90.],
        "points": [1., 2., 3., 4.], "grade_show": ["D", "C", "B", "A"],
    }))


def synthetic_snapshot():
    snapshot = {column: 1 for column in STUDENT_SNAPSHOT_COLUMNS}
    snapshot.update(student_id="S", degree_id="D", faculty_id="F", part_id=20251,
                    grade_version_id=1, diploma_type_id="T", start_agpa_points=2.5,
                    start_total_in_credits=30., prior_total_reg_credits=60., current_gpa_credits=60.)
    return snapshot


def synthetic_candidates(size=6):
    rows = pd.DataFrame({column: [1] * size for column in CANDIDATE_COURSE_COLUMNS})
    rows["course_id"] = list("ABCDEF")[:size]
    rows["course_name"] = [f"Synthetic course {course}" for course in rows.course_id]
    rows["course_credits"] = 3.
    rows["plan_course_type_id"] = "T"
    rows["plan_requirement_type_id"] = "R"
    return rows


def synthetic_course_history(as_of_part=20243):
    rows = synthetic_candidates().assign(part_id=as_of_part, degree_id="D", faculty_id="F",
                                         final_mark=60., student_course_id=lambda x: "history_" + x.course_id)
    history = CourseHistoryState()
    history.update(rows)
    return history


def synthetic_components(history=None, *, grade=60., fail=.1):
    levels = {column: [CATEGORY_MISSING, CATEGORY_UNKNOWN, "1", "T", "R"]
              for column in CATEGORICAL_FEATURES}
    metadata = {"feature_engineering_version": FEATURE_ENGINEERING_VERSION,
                "dataset_version": "V2", "training_as_of_part": 20243,
                "targets": {"grade_regressor": "final_mark", "fail_risk_classifier": "is_fail"},
                "feature_contract": {"model_features": BASE_FEATURES,
                                     "numeric_features": NUMERIC_FEATURES,
                                     "categorical_features": CATEGORICAL_FEATURES}}
    provenance = {"dataset_version": "V2", "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
                  "training": {"grade": {"training_as_of_part": 20243},
                               "fail_risk": {"training_as_of_part": 20243}},
                  "artifact_sha256": {"synthetic_grade": "mock", "synthetic_fail": "mock"}}
    return (RecordingModel(grade), RecordingModel(fail), levels, synthetic_grade_scale(),
            history if history is not None else synthetic_course_history(), metadata, provenance)

