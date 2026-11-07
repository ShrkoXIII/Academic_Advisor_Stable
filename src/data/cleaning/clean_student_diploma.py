import pandas as pd

from src.data.cleaning.cleaning_utils import clean_column_names, clean_id_columns, to_float
from src.paths import (
    ACADEMIC_INFO_PATH,
    CLEAN_STUDENT_DIPLOMA_PATH,
    STUDENT_COURSE_DIPLOMA_PATH,
    STUDENT_COURSE_ENRICHED_PATH,
)


FINAL_COLUMNS = ["student_id", "diploma_gpa", "diploma_type_id"]
RARE_DIPLOMA_TYPE_ID = 55.111
TOP_DIPLOMA_TYPE_COUNT = 4


def clean_student_diploma(df):
    """Clean the academic-info table and return one diploma row per student."""
    df = clean_column_names(df)

    missing_columns = set(FINAL_COLUMNS).difference(df.columns)
    if missing_columns:
        raise KeyError(
            f"Missing required academic-info columns: {sorted(missing_columns)}"
        )

    df = df[FINAL_COLUMNS].copy()
    df = clean_id_columns(df, ["student_id"])
    df["diploma_gpa"] = to_float(df["diploma_gpa"])
    df["diploma_type_id"] = to_float(df["diploma_type_id"])

    df = df.dropna(subset=["diploma_type_id"]).copy()

    top_diploma_types = (
        df["diploma_type_id"]
        .value_counts()
        .nlargest(TOP_DIPLOMA_TYPE_COUNT)
        .index
    )
    df.loc[
        ~df["diploma_type_id"].isin(top_diploma_types),
        "diploma_type_id",
    ] = RARE_DIPLOMA_TYPE_ID

    # The user explicitly approved a global forward fill for this small gap.
    df["diploma_gpa"] = df["diploma_gpa"].ffill()

    if df["student_id"].isna().any():
        raise ValueError("student_id contains missing values after cleaning")
    if df["student_id"].duplicated().any():
        raise ValueError("student_id must be unique in student_diploma")

    return df.reset_index(drop=True)


def merge_student_course_with_diploma(student_course, student_diploma):
    """Attach diploma features without dropping student-course rows."""
    existing_columns = set(FINAL_COLUMNS[1:]).intersection(student_course.columns)
    if existing_columns:
        raise ValueError(
            "Student-course input already contains diploma columns: "
            f"{sorted(existing_columns)}"
        )

    row_count = len(student_course)
    merged = student_course.merge(
        student_diploma,
        on="student_id",
        how="left",
        validate="many_to_one",
    )

    if len(merged) != row_count:
        raise AssertionError("Diploma merge changed the student-course row count")

    return merged


def main():
    academic_info = pd.read_parquet(ACADEMIC_INFO_PATH)
    student_diploma = clean_student_diploma(academic_info)

    CLEAN_STUDENT_DIPLOMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    student_diploma.to_parquet(CLEAN_STUDENT_DIPLOMA_PATH, index=False)

    student_course = pd.read_parquet(STUDENT_COURSE_ENRICHED_PATH)
    merged = merge_student_course_with_diploma(
        student_course,
        student_diploma,
    )

    STUDENT_COURSE_DIPLOMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(STUDENT_COURSE_DIPLOMA_PATH, index=False)

    matched_rows = int(merged["diploma_type_id"].notna().sum())
    print("Clean diploma rows:", len(student_diploma))
    print("Diploma type counts:")
    print(student_diploma["diploma_type_id"].value_counts().to_string())
    missing_gpa = int(student_diploma["diploma_gpa"].isna().sum())
    print("Missing diploma GPA after ffill:", missing_gpa)
    print("Saved clean diploma:", CLEAN_STUDENT_DIPLOMA_PATH)
    print("Merged rows:", len(merged))
    print("Matched rows:", matched_rows)
    print("Unmatched rows:", len(merged) - matched_rows)
    print("Saved merged data:", STUDENT_COURSE_DIPLOMA_PATH)


if __name__ == "__main__":
    main()
