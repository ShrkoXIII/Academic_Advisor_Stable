import pandas as pd

from src.data.cleaning.cleaning_utils import (
    clean_column_names,
    clean_id_columns,
    to_float,
    to_integer,
)
from src.paths import (
    PRE_COMMON_STUDENT_COURSE_PATH,
    STUDENT_COURSE_PATH,
)


REGISTER_STATUSES = ["R", "E"]
FINISH_STATUS_MAP = {
    "F": "fail",
    "FE": "fail",
    "FA": "fail",
    "P": "pass",
}


def clean_student_course(df):
    df = clean_column_names(df)

    df["register_status"] = (df["register_status"].astype("string").str.strip().str.upper())

    df = df[df["register_status"].isin(REGISTER_STATUSES)].copy()

    df["finish_status"] = (df["finish_status"].astype("string").str.strip().str.upper()
    )

    # Unparseable semester values have no usable temporal key; never infer one.
    df["part_id"] = pd.to_numeric(df["part_id"], errors="coerce").astype("Int64")

    id_columns = [
        "student_course_id",
        "student_id",
        "course_id",
        "degree_id",
        "grade_id",
        "faculty_id",
    ]
    df = clean_id_columns(df, id_columns)

    # Missing course/semester keys are excluded under the approved cleaning policy.
    df = df.dropna(subset=["course_id", "part_id"]).copy()

    required_keys = ["student_course_id", "student_id", "course_id", "degree_id", "part_id"]
    missing_keys = df[required_keys].isna().any()
    if missing_keys.any():
        raise ValueError(f"Missing required key: {', '.join(missing_keys[missing_keys].index)}")

    if df["student_course_id"].duplicated().any():
        raise ValueError("Duplicate student_course_id")
    if df.duplicated(["student_id", "course_id", "part_id"]).any():
        raise ValueError("Duplicate student_id + course_id + part_id")

    df = df[df["part_id"] > 20193].copy()

    df["final_mark"] = to_integer(df["final_mark"])
    df["points"] = to_float(df["points"])
    df["course_credits"] = to_float(df["course_credits"])

    for column in ["course_name_sl", "degree_name_sl"]:
        df[column] = df[column].astype("string").str.strip()

    in_columns = ["in_agpa", "in_gpa", "in_credits"]
    for column in in_columns:
        df[column] = df[column].astype("string").str.strip().str.upper()
    df = df.sort_values(
        ["student_id", "course_id", "part_id"],
        kind="stable",
    ).reset_index(drop=True)

    attempts = df.groupby(
        ["student_id", "course_id"],
        dropna=False,
        sort=False,
    )
    df["attempt_number"] = (attempts.cumcount() + 1).astype("Int64")

    df = df[df["finish_status"].isin(FINISH_STATUS_MAP)].copy()
    df["course_outcome_status"] = df["finish_status"].map(FINISH_STATUS_MAP)
    rows_with_n = df[in_columns].eq("N").any(axis=1)
    df = df[~rows_with_n].copy().reset_index(drop=True)

    columns_to_drop = [
        "finish_status",
        "register_status",
        "active",
        "in_agpa",
        "in_gpa",
        "in_credits",
        "student_name_sl",
        "study_mode",
    ]
    df = df.drop(columns=columns_to_drop)

    return df


def main():
    df = pd.read_parquet(STUDENT_COURSE_PATH)
    df = clean_student_course(df)

    null_report = df.isna().sum().to_frame("null_count")
    null_report["null_percent"] = (
        null_report["null_count"] / len(df) * 100
    ).round(2)
    null_report = null_report.sort_values("null_count", ascending=False)

    print("Rows after the agreed filters:", len(df))
    print("\nNull report:")
    print(null_report.to_string())

    PRE_COMMON_STUDENT_COURSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PRE_COMMON_STUDENT_COURSE_PATH, index=False)
    print("\nSaved:", PRE_COMMON_STUDENT_COURSE_PATH)


if __name__ == "__main__":
    main()
