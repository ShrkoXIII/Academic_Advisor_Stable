"""Canonical project-relative paths for the data pipeline.

Each artifact has one unversioned path. Cleaning modules import the canonical
constants directly.
Serialized metadata versions and academic cutoffs identify compatible artifacts,
not parallel pipeline paths.
Importing this module does not create directories or read data.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"
MERGED_DIR = DATA_DIR / "merged"
TEMPORAL_DIR = DATA_DIR / "temporal"

STUDENT_COURSE_PATH = RAW_DIR / "v_crg_student_course_raw.parquet"
STUDENT_STATUS_PATH = RAW_DIR / "v_add_student_degree_status.parquet"
DEGREE_COURSE_PATH = RAW_DIR / "v_acd_degree_course.parquet"
ACADEMIC_INFO_PATH = RAW_DIR / "v_add_academic_info.parquet"

PRE_COMMON_STUDENT_COURSE_PATH = CLEAN_DIR / "student_course_pre_common.parquet"
PRE_COMMON_STUDENT_STATUS_PATH = CLEAN_DIR / "student_status_pre_common.parquet"
CLEAN_DEGREE_COURSE_PATH = CLEAN_DIR / "degree_course.parquet"
CLEAN_STUDENT_DIPLOMA_PATH = CLEAN_DIR / "student_diploma.parquet"
CLEAN_STUDENT_COURSE_PATH = CLEAN_DIR / "student_course.parquet"
CLEAN_STUDENT_STATUS_PATH = CLEAN_DIR / "student_status.parquet"

# Produced by Data Building and consumed by diploma cleaning.
STUDENT_COURSE_ENRICHED_PATH = CLEAN_DIR / "student_course_enriched.parquet"

STUDENT_COURSE_DIPLOMA_PATH = (
    MERGED_DIR / "student_course_enriched_with_diploma.parquet"
)
STUDENT_COURSE_WITHOUT_OUTLIERS_PATH = (
    MERGED_DIR / "student_course_enriched_without_outliers.parquet"
)
OUTLIER_STUDENTS_AUDIT_PATH = MERGED_DIR / "outlier_students.parquet"
TEMPORAL_TRAIN_PATH = TEMPORAL_DIR / "temporal_train.parquet"
TEMPORAL_TEST_PATH = TEMPORAL_DIR / "temporal_test.parquet"
CLEAN_REGISTRATION_ROSTER_PATH = CLEAN_DIR / "registration_roster.parquet"
TEMPORAL_TRAIN_ROSTER_PATH = TEMPORAL_DIR / "temporal_train_roster.parquet"
TEMPORAL_TEST_ROSTER_PATH = TEMPORAL_DIR / "temporal_test_roster.parquet"

FEATURE_DIR = DATA_DIR / "features"
ARTIFACT_DIR = DATA_DIR / "artifacts"
TEMPORAL_TRAIN_FEATURES_PATH = FEATURE_DIR / "temporal_train_features.parquet"
TEMPORAL_TEST_FEATURES_PATH = FEATURE_DIR / "temporal_test_features.parquet"
COURSE_HISTORY_STATE_PATH = ARTIFACT_DIR / "course_history_state.pkl"

FROZEN_HISTORY_DIR = ARTIFACT_DIR / "history"

def academic_part(value):
    """Validate the project's YYYY{1,2,3} academic-part identifiers."""
    text = str(value)
    if len(text) != 5 or not text.isdigit() or int(text[-1]) not in (1, 2, 3):
        raise ValueError(f"Invalid academic part: {value!r}; expected YYYY1, YYYY2 or YYYY3.")
    return int(text)

def frozen_history_dir(as_of_part, root=None):
    return Path(root if root is not None else FROZEN_HISTORY_DIR) / f"as_of_{academic_part(as_of_part)}"

def course_history_state_path(as_of_part, root=None):
    return frozen_history_dir(as_of_part, root) / "course_history_state.pkl"

def specialty_history_state_path(as_of_part, root=None):
    return frozen_history_dir(as_of_part, root) / "specialty_history_state.pkl"

def history_metadata_path(as_of_part, root=None):
    return frozen_history_dir(as_of_part, root) / "metadata.json"

MODEL_DIR = PROJECT_ROOT / "models"
EVALUATION_DIR = DATA_DIR / "evaluation"
CATEGORY_LEVELS_PATH = ARTIFACT_DIR / "category_levels.json"
GRADE_MODEL_PATH = MODEL_DIR / "grade_regressor.txt"
FAIL_MODEL_PATH = MODEL_DIR / "fail_risk_classifier.txt"
MODEL_METADATA_PATH = MODEL_DIR / "model_metadata.json"
COURSE_ONLY_MODEL_DIR = MODEL_DIR / "shortlist_training"
COURSE_ONLY_EVALUATION_DIR = EVALUATION_DIR / "shortlist"

GRADE_SCALE_PATH = RAW_DIR / "v_acs_grade.parquet"
SHORTLIST_MODEL_DIR = MODEL_DIR / "shortlist"
SHORTLIST_GRADE_MODEL_PATH = SHORTLIST_MODEL_DIR / "grade_model.txt"
SHORTLIST_FAIL_MODEL_PATH = SHORTLIST_MODEL_DIR / "fail_model.txt"
SHORTLIST_CATEGORY_LEVELS_PATH = SHORTLIST_MODEL_DIR / "category_levels.json"
TWO_STAGE_MANIFEST_PATH = SHORTLIST_MODEL_DIR / "manifest.json"
FROZEN_HISTORY_INCREMENTAL_DIR = ARTIFACT_DIR / "history_incremental"

PLAN_GPA_COURSE_PREDICTIONS_PATH = EVALUATION_DIR / "plan_gpa_course_predictions_2025.parquet"
PLAN_GPA_EVALUATION_PATH = EVALUATION_DIR / "plan_gpa_evaluation_2025.parquet"
PLAN_GPA_METRICS_PATH = EVALUATION_DIR / "plan_gpa_metrics_2025.json"
