import json

import pandas as pd


FEATURE_ENGINEERING_VERSION = 2


def require_current_features(metadata):
    if metadata.get("feature_engineering_version") != FEATURE_ENGINEERING_VERSION:
        raise ValueError(
            "Stale feature engineering: rebuild temporal features, retrain models, "
            "then rerun evaluation. Artifacts from before the leakage fix cannot be used."
        )


CATEGORY_MISSING = "__MISSING__"
CATEGORY_UNKNOWN = "__UNKNOWN__"

CATEGORICAL_FEATURES = [
    "plan_course_type_id",
    "plan_requirement_type_id",
    "diploma_type_id",
    "grade_version_id",
    "part_semester",
]

NUMERIC_FEATURES = [
    # Student history available before the target semester.
    "gpa_prev_1",
    "gpa_prev_2",
    "gpa_trend_delta",
    "gpa_trend_missing",
    "start_agpa_points",
    "start_total_in_courses",
    "start_total_in_credits",
    "prior_total_reg_courses",
    "prior_total_reg_credits",
    "prior_total_fail_courses",
    "prior_total_fail_credits",
    "prior_fail_credit_ratio",
    "prior_registered_semesters",
    "observed_gap_semesters",
    # Pre-university and course/plan properties.
    "diploma_gpa",
    ## course_features
    "course_credits",
    "attempt_number",
    "plan_year_order",
    "plan_semester_order",
    "plan_credits_count",
    "degree_credits_count",
    # Course difficulty learned strictly from earlier semesters.
    "course_history_avg_mark",
    "course_history_fail_rate",
    "course_history_avg_attempt",
    "course_history_retake_rate",
    "course_history_effective_support",
    "course_history_fallback_level",
    "course_history_missing",
    # Full-plan context and target-course leave-one-out peer context.

    "plan_course_count",                  # عدد كل المواد المسجلة للطالب في هذا الفصل
    "plan_total_credits",                 # مجموع ساعات كل مواد الفصل للطالب

    "plan_credit_weighted_fail_rate",     # متوسط نسبة الرسوب التاريخية لكل مواد الفصل، موزون بعدد الساعات
    "plan_credit_weighted_avg_mark",       # متوسط العلامة التاريخية لكل مواد الفصل، موزون بعدد الساعات
    "plan_credit_weighted_avg_attempt",    # متوسط عدد المحاولات التاريخي لكل مواد الفصل، موزون بعدد الساعات
    "plan_difficulty_credit_load",         # حمل صعوبة الفصل الكلي = مجموع (نسبة الرسوب التاريخية × ساعات المادة)

    "peer_course_count",                  # عدد المواد الأخرى في الفصل باستثناء المادة الحالية
    "peer_total_credits",                 # مجموع ساعات المواد الأخرى باستثناء المادة الحالية

    "peer_credit_weighted_fail_rate",      # متوسط نسبة الرسوب التاريخية للمواد الأخرى فقط، موزون بالساعات
    "peer_credit_weighted_avg_mark",       # متوسط العلامة التاريخية للمواد الأخرى فقط، موزون بالساعات
    "peer_credit_weighted_avg_attempt",    # متوسط عدد المحاولات التاريخي للمواد الأخرى فقط، موزون بالساعات
    "peer_difficulty_credit_load",         # حمل صعوبة المواد الأخرى = مجموع (نسبة الرسوب × الساعات) بدون المادة الحالية

    "peer_max_fail_rate",                 # أعلى نسبة رسوب تاريخية بين المواد الأخرى في نفس الفصل
    "peer_difficulty_missing",             # 1 إذا لم نستطع حساب صعوبة المواد الأخرى، وإلا 0

]

BASE_FEATURES = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]

# Documentation guard: these columns are deliberately outside BASE_FEATURES.
LEAKAGE_COLUMNS = [
    "final_mark",
    "is_fail",
    "points",
    "grade_id",
    "course_outcome_status",
    "gpa_points",
    "end_agpa_points",
    "end_total_in_courses",
    "end_total_in_credits",
    "semester_pass_courses",
    "semester_pass_credits",
    "semester_fail_courses",
    "semester_fail_credits",
    "reg_total_semesters",
    "total_pass_courses",
    "total_pass_credits",
    "finish_part_id",
    "finish_status",
]

RAW_ID_COLUMNS = [
    "student_course_id",
    "student_status_id",
    "student_id",
    "course_id",
    "degree_id",
    "faculty_id",
    "plan_degree_course_id",
]


def learn_category_levels(frame):
    levels = {}
    for column in CATEGORICAL_FEATURES:
        observed = (
            frame[column]
            .astype("string")
            .fillna(CATEGORY_MISSING)
            .drop_duplicates()
            .tolist()
        )
        observed = sorted(
            value
            for value in observed
            if value not in {CATEGORY_MISSING, CATEGORY_UNKNOWN}
        )
        levels[column] = [CATEGORY_MISSING, CATEGORY_UNKNOWN, *observed]
    return levels


def prepare_model_matrix(frame, category_levels, *, model_features=None):
    """Coerce an ordered model-feature subset, defaulting to the official 47."""
    features = BASE_FEATURES if model_features is None else list(model_features)
    selected = set(features)
    if len(selected) != len(features):
        raise ValueError("Duplicate model features are not allowed.")
    unknown = selected - set(BASE_FEATURES)
    if unknown:
        raise ValueError(f"Unknown model features: {sorted(unknown, key=str)}")

    matrix = pd.DataFrame(index=frame.index)
    for column in NUMERIC_FEATURES:
        if column not in selected:
            continue
        matrix[column] = pd.to_numeric(frame[column], errors="coerce").astype(
            "float32"
        )

    for column in CATEGORICAL_FEATURES:
        if column not in selected:
            continue
        values = frame[column].astype("string").fillna(CATEGORY_MISSING)
        values = values.where(values.isin(category_levels[column]), CATEGORY_UNKNOWN)
        matrix[column] = pd.Categorical(
            values,
            categories=category_levels[column],
        )
    return matrix[features]


def save_category_levels(category_levels, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(category_levels, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_category_levels(path):
    return json.loads(path.read_text(encoding="utf-8"))
