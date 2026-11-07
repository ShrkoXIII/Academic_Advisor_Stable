import pandas as pd

from src.data.academic_calendar import count_regular_semesters_between, is_regular_semester
from src.data.cleaning.cleaning_utils import clean_column_names, clean_id_columns, to_float, to_integer
from src.paths import (
    PRE_COMMON_STUDENT_STATUS_PATH,
    STUDENT_STATUS_PATH,
)


EXCLUDED_PERMANENT_STATUS_IDS = [1, 4, 11, 12, 15, 16, 41]

FINAL_COLUMNS = [
    "student_status_id",
    "student_id",
    "part_id",
    "degree_id",
    "degree_name_sl",
    "start_part_id",
    "finish_part_id",
    "grade_version_id",
    "prev_gpa_points",
    "last_enrolled_gpa",
    "observed_gap_semesters",
    "gpa_points",
    "start_agpa_points",
    "start_total_in_courses",
    "start_total_in_credits",
    "end_total_in_courses",
    "end_total_in_credits",
    "end_agpa_points",
    "semester_reg_courses",
    "semester_reg_credits",
    "semester_pass_courses",
    "semester_pass_credits",
    "semester_fail_courses",
    "semester_fail_credits",
    "total_semesters",
    "total_reg_courses",
    "total_reg_credits",
    "total_pass_courses",
    "total_pass_credits",
    "total_fail_courses",
    "total_fail_credits",
    "reg_total_semesters",
    "finish_status",
    "degree_credits_count",
    "start_level_name_short",
    "end_level_name_short",
]


def add_enrollment_features(df):
    """Track prior enrollment independently for each student's degree."""
    history_keys = ["student_id", "degree_id"]
    df = df.sort_values(
        [*history_keys, "part_id", "student_status_id"],
        kind="stable",
    ).copy()
    history_groups = [df[column] for column in history_keys]

    registered = df["semester_reg_courses"].gt(0)

    previous_enrolled_gpa = (
        df["gpa_points"]
        .where(registered)
        .groupby(history_groups, sort=False)
        .ffill() # Fill missing values with the previous enrolled GPA
        .groupby(history_groups, sort=False)
        .shift() # Shift the previous enrolled GPA to not change the current semester's GPA
    )

    first_row = ~df.duplicated(history_keys)
    strong_prior_history = (
        df["total_reg_courses"].gt(0)
        | df["total_reg_credits"].gt(0)
        | df["start_total_in_credits"].gt(0)
        | df["start_total_in_courses"].gt(0)
    )
    use_initial_fallback = (
        first_row
        & df["part_id"].eq(20201)
        & strong_prior_history
        & previous_enrolled_gpa.isna()
    )
    df["last_enrolled_gpa"] = previous_enrolled_gpa.mask(
        use_initial_fallback,
        df["prev_gpa_points"],
    )

    current_is_regular = df["part_id"].map(is_regular_semester)
    previous_enrolled_part = (
        df["part_id"]
        .where(registered)
        .groupby(history_groups, sort=False)
        .ffill()
        .groupby(history_groups, sort=False)
        .shift()
    )
    df["observed_gap_semesters"] = pd.array(
        [
            pd.NA if pd.isna(previous_part) else (
                count_regular_semesters_between(previous_part, current_part)
                + (is_regular and not is_registered)
            )
            for previous_part, current_part, is_registered, is_regular in zip(
                previous_enrolled_part,
                df["part_id"],
                registered.fillna(False),
                current_is_regular,
            )
        ],
        dtype="Int64",
    )

    return df


def filter_status_rows_after_enrollment(df):
    """Training's ordered status filters, applied after enrollment history."""
    df = df[~df["permanent_status_id"].isin(EXCLUDED_PERMANENT_STATUS_IDS)].copy()
    df = df[df["finish_status"].ne("WITHDRAWN").fillna(True)].copy()
    df = df[df["study_mode"].eq("C")].copy()
    return df[df["degree_id"].notna()].copy()


def clean_student_status(df):
    df = clean_column_names(df)

    df["permanent_status_id"] = to_integer(df["permanent_status_id"])
    df["finish_status"] = (
        df["finish_status"].astype("string").str.strip().str.upper()
    )
    df["part_id"] = to_integer(df["part_id"])
    df = df[df["part_id"] > 20193].copy()
    # Exclude semester 4 before it can affect enrollment history. The calendar
    # validator remains strict, including for all other invalid semester values.
    df = df[df["part_id"].mod(10).ne(4)].copy()

    df["study_mode"] = (
        df["study_mode"].astype("string").str.strip().str.upper()
    )

    id_columns = [
        "student_status_id",
        "student_id",
        "degree_id",
        "grade_version_id",
    ]
    df = clean_id_columns(df, id_columns)

    df["start_part_id"] = to_integer(df["start_part_id"])
    df["finish_part_id"] = to_integer(df["finish_part_id"])

    count_columns = [
        "start_total_in_courses",
        "end_total_in_courses",
        "semester_reg_courses",
        "semester_pass_courses",
        "semester_fail_courses",
        "total_semesters",
        "total_reg_courses",
        "total_pass_courses",
        "total_fail_courses",
        "reg_total_semesters",
    ]
    for column in count_columns:
        df[column] = to_integer(df[column])

    float_columns = [
        "prev_gpa_points",
        "gpa_percent",
        "gpa_points",
        "start_agpa_points",
        "start_total_in_credits",
        "end_total_in_credits",
        "end_agpa_points",
        "semester_reg_credits",
        "semester_pass_credits",
        "semester_fail_credits",
        "total_reg_credits",
        "total_pass_credits",
        "total_fail_credits",
        "degree_credits_count",
    ]
    for column in float_columns:
        df[column] = to_float(df[column])

    for column in [
        "degree_name_sl",
        "start_level_name_short",
        "end_level_name_short",
    ]:
        df[column] = df[column].astype("string").str.strip()

    df = add_enrollment_features(df)

    df = filter_status_rows_after_enrollment(df)

    df = df[FINAL_COLUMNS].copy()
    df = df.sort_values(
        ["student_id", "degree_id", "part_id", "student_status_id"],
        kind="stable",
    ).reset_index(drop=True)

    return df


def main():
    df = pd.read_parquet(STUDENT_STATUS_PATH)
    df = clean_student_status(df)

    null_report = df.isna().sum().to_frame("null_count")
    null_report["null_percent"] = (
        null_report["null_count"] / len(df) * 100
    ).round(2)
    null_report = null_report.sort_values("null_count", ascending=False)

    print("Rows after the agreed filters:", len(df))
    print("\nNull report:")
    print(null_report.to_string())

    PRE_COMMON_STUDENT_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PRE_COMMON_STUDENT_STATUS_PATH, index=False)
    print("\nSaved:", PRE_COMMON_STUDENT_STATUS_PATH)


if __name__ == "__main__":
    main()
