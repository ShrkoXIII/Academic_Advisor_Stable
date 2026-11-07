import pandas as pd

from src.data.cleaning.cleaning_utils import clean_column_names, clean_id_columns, to_float, to_integer
from src.paths import (
    CLEAN_DEGREE_COURSE_PATH,
    DEGREE_COURSE_PATH,
)


FINAL_COLUMNS = [
    "degree_course_id",
    "course_id",
    "degree_id",
    "course_type_id",
    "requirement_type_id",
    "requirement_type_sl",
    "course_name_sl",
    "course_official_sl",
    "degree_name_sl",
    "year_order",
    "semester_order",
    "course_credits",
    "credits_count",
    "active",
]


def clean_degree_course(df):
    df = clean_column_names(df)
    df = clean_id_columns(
        df,
        [
            "degree_course_id",
            "course_id",
            "degree_id",
            "course_type_id",
        ],
    )

    for column in ["year_order", "semester_order","requirement_type_id"]:
        df[column] = to_integer(df[column])

    for column in  ["course_credits", "credits_count"]:
        df[column] = to_float(df[column])

    for column in [
        "requirement_type_sl",
        "course_name_sl",
        "course_official_sl",
        "degree_name_sl",
        "active",
    ]:
        df[column] = df[column].astype("string").str.strip()

    return df[FINAL_COLUMNS].sort_values(
        ["degree_id", "year_order", "semester_order", "course_id"],
        kind="stable",
    ).reset_index(drop=True)


def main():
    df = clean_degree_course(pd.read_parquet(DEGREE_COURSE_PATH))
    CLEAN_DEGREE_COURSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CLEAN_DEGREE_COURSE_PATH, index=False)
    print("Rows:", len(df))
    print("Unique courses:", df["course_id"].nunique())
    print("Unique degrees:", df["degree_id"].nunique())
    print("Saved:", CLEAN_DEGREE_COURSE_PATH)


if __name__ == "__main__":
    main()
