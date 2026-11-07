import pandas as pd

from src.paths import (
    OUTLIER_STUDENTS_AUDIT_PATH,
    STUDENT_COURSE_DIPLOMA_PATH,
    STUDENT_COURSE_WITHOUT_OUTLIERS_PATH,
)


# Stable upper limits taken from the current data's 99.9th percentiles.
# IDs, categorical columns, and degree-specific course credits are excluded.
STATUS_UPPER_LIMITS = {
    "observed_gap_semesters": 2,
    "semester_reg_courses": 10,
    "semester_reg_credits": 39,
    "semester_pass_courses": 10,
    "semester_pass_credits": 27,
    "semester_fail_courses": 6,
    "semester_fail_credits": 24,
    "total_semesters": 38,
    "total_reg_courses": 176,
    "total_reg_credits": 573.706,
    "total_pass_courses": 87,
    "total_pass_credits": 275.379,
    "total_fail_courses": 96,
    "total_fail_credits": 340.5,
    "reg_total_semesters": 36,
}

STATUS_GPA_COLUMNS = [
    "prev_gpa_points",
    "last_enrolled_gpa",
    "gpa_points",
    "start_agpa_points",
    "end_agpa_points",
]

STATUS_NONNEGATIVE_COLUMNS = [
    "start_total_in_courses",
    "start_total_in_credits",
    "end_total_in_courses",
    "end_total_in_credits",
    "degree_credits_count",
    *STATUS_UPPER_LIMITS,
]

AUDIT_COLUMNS = [
    "student_id",
    "scope",
    "rule",
    "expected",
    "trigger_count",
    "min_observed",
    "max_observed",
]


def _validate_columns(df, columns):
    missing = set(columns).difference(df.columns)
    if missing:
        raise KeyError(f"Missing columns required for outlier cleaning: {sorted(missing)}")


def _summarize_rule(frame, mask, observed, scope, rule, expected):
    mask = mask.fillna(False)
    if not mask.any():
        return pd.DataFrame(columns=AUDIT_COLUMNS)

    triggered = frame.loc[mask, ["student_id"]].copy()
    triggered["observed"] = observed.loc[mask].astype("Float64")

    summary = (
        triggered.groupby("student_id", as_index=False)
        .agg(
            trigger_count=("observed", "size"),
            min_observed=("observed", "min"),
            max_observed=("observed", "max"),
        )
    )
    summary.insert(1, "scope", scope)
    summary.insert(2, "rule", rule)
    summary.insert(3, "expected", expected)
    return summary[AUDIT_COLUMNS]


def build_outlier_audit(df):
    required_columns = {
        "student_id",
        "student_status_id",
        "final_mark",
        "points",
        "course_credits",
        "attempt_number",
        "semester_reg_courses",
        "semester_reg_credits",
        "semester_pass_courses",
        "semester_pass_credits",
        "semester_fail_courses",
        "semester_fail_credits",
        "total_reg_courses",
        "total_reg_credits",
        "total_pass_courses",
        "total_pass_credits",
        "total_fail_courses",
        "total_fail_credits",
        "reg_total_semesters",
        "total_semesters",
        "start_total_in_courses",
        "start_total_in_credits",
        "end_total_in_courses",
        "end_total_in_credits",
        *STATUS_GPA_COLUMNS,
        *STATUS_NONNEGATIVE_COLUMNS,
    }
    _validate_columns(df, required_columns)

    # Status features repeat once per course, so inspect one row per status.
    status = df.drop_duplicates("student_status_id").copy()
    audits = []

    for column, upper_limit in STATUS_UPPER_LIMITS.items():
        audits.append(
            _summarize_rule(
                status,
                status[column].gt(upper_limit),
                status[column],
                scope="semester_status",
                rule=f"{column}_above_limit",
                expected=f"<= {upper_limit}",
            )
        )

    for column in dict.fromkeys(STATUS_NONNEGATIVE_COLUMNS):
        audits.append(
            _summarize_rule(
                status,
                status[column].lt(0),
                status[column],
                scope="semester_status",
                rule=f"{column}_below_zero",
                expected=">= 0",
            )
        )

    for column in STATUS_GPA_COLUMNS:
        invalid = status[column].lt(0) | status[column].gt(4)
        audits.append(
            _summarize_rule(
                status,
                invalid,
                status[column],
                scope="semester_status",
                rule=f"{column}_outside_gpa_range",
                expected="between 0 and 4",
            )
        )

    course_ranges = {
        "final_mark": (0, 100),
        "points": (0, 4),
        "attempt_number": (1, 5),
    }
    for column, (lower_limit, upper_limit) in course_ranges.items():
        invalid = df[column].lt(lower_limit) | df[column].gt(upper_limit)
        audits.append(
            _summarize_rule(
                df,
                invalid,
                df[column],
                scope="course",
                rule=f"{column}_outside_range",
                expected=f"between {lower_limit} and {upper_limit}",
            )
        )

    # A 24-credit course exists in degree 2.111, so no generic upper cap is used.
    audits.append(
        _summarize_rule(
            df,
            df["course_credits"].lt(0),
            df["course_credits"],
            scope="course",
            rule="course_credits_below_zero",
            expected=">= 0",
        )
    )

    logical_rules = [
        (
            "semester_course_totals_exceed_registered",
            status["semester_pass_courses"]
            + status["semester_fail_courses"]
            - status["semester_reg_courses"],
        ),
        (
            "semester_credit_totals_exceed_registered",
            status["semester_pass_credits"]
            + status["semester_fail_credits"]
            - status["semester_reg_credits"],
        ),
        (
            "total_course_totals_exceed_registered",
            status["total_pass_courses"]
            + status["total_fail_courses"]
            - status["total_reg_courses"],
        ),
        (
            "total_credit_totals_exceed_registered",
            status["total_pass_credits"]
            + status["total_fail_credits"]
            - status["total_reg_credits"],
        ),
        (
            "registered_semesters_exceed_total_semesters",
            status["reg_total_semesters"] - status["total_semesters"],
        ),
        (
            "end_courses_below_start_courses",
            status["start_total_in_courses"]
            - status["end_total_in_courses"],
        ),
        (
            "end_credits_below_start_credits",
            status["start_total_in_credits"]
            - status["end_total_in_credits"],
        ),
    ]
    for rule, excess in logical_rules:
        audits.append(
            _summarize_rule(
                status,
                excess.gt(0),
                excess,
                scope="logical_consistency",
                rule=rule,
                expected="excess <= 0",
            )
        )

    nonempty_audits = [rule_audit for rule_audit in audits if not rule_audit.empty]
    if not nonempty_audits:
        return pd.DataFrame(columns=AUDIT_COLUMNS)

    audit = pd.concat(nonempty_audits, ignore_index=True)
    return audit.sort_values(["student_id", "scope", "rule"]).reset_index(
        drop=True
    )


def remove_outlier_students(df, audit):
    outlier_student_ids = audit["student_id"].drop_duplicates()
    clean_df = df.loc[~df["student_id"].isin(outlier_student_ids)].copy()
    return clean_df.reset_index(drop=True)


def main():
    df = pd.read_parquet(STUDENT_COURSE_DIPLOMA_PATH)
    audit = build_outlier_audit(df)
    clean_df = remove_outlier_students(df, audit)

    STUDENT_COURSE_WITHOUT_OUTLIERS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    clean_df.to_parquet(STUDENT_COURSE_WITHOUT_OUTLIERS_PATH, index=False)
    audit.to_parquet(OUTLIER_STUDENTS_AUDIT_PATH, index=False)

    removed_students = audit["student_id"].nunique()
    removed_rows = len(df) - len(clean_df)
    summary = (
        audit.groupby(["scope", "rule"], as_index=False)
        .agg(
            students=("student_id", "nunique"),
            trigger_records=("trigger_count", "sum"),
        )
        .sort_values(["scope", "students"], ascending=[True, False])
    )

    print(summary.to_string(index=False))
    print("\nInput rows:", len(df))
    print("Removed students:", removed_students)
    print("Removed rows:", removed_rows)
    print("Remaining students:", clean_df["student_id"].nunique())
    print("Remaining rows:", len(clean_df))
    print("Saved clean data:", STUDENT_COURSE_WITHOUT_OUTLIERS_PATH)
    print("Saved outlier audit:", OUTLIER_STUDENTS_AUDIT_PATH)


if __name__ == "__main__":
    main()
