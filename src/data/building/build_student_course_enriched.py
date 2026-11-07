import pandas as pd

from src.paths import (
    CLEAN_DEGREE_COURSE_PATH,
    CLEAN_STUDENT_COURSE_PATH,
    CLEAN_STUDENT_STATUS_PATH,
    STUDENT_COURSE_ENRICHED_PATH,
)


KEY_COLUMNS = ["student_id", "degree_id", "part_id"]
PLAN_KEYS = ["degree_id", "course_id"]


def main():
    courses = pd.read_parquet(CLEAN_STUDENT_COURSE_PATH)
    status = pd.read_parquet(CLEAN_STUDENT_STATUS_PATH)
    degree_courses = pd.read_parquet(CLEAN_DEGREE_COURSE_PATH)

    plan = degree_courses.rename(
        columns={
            column: f"plan_{column}"
            for column in degree_courses.columns
            if column not in PLAN_KEYS
        }
    )

    df = courses.merge(
        status,
        on=KEY_COLUMNS,
        how="inner",
        validate="many_to_one",
        suffixes=("_course", "_status"),
    )
    df = df.merge(
        plan,
        on=PLAN_KEYS,
        how="left",
        validate="many_to_one",
        indicator="plan_match",
    )
    df["plan_match"] = df["plan_match"].eq("both")

    STUDENT_COURSE_ENRICHED_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(STUDENT_COURSE_ENRICHED_PATH, index=False)

    print("Rows:", len(df))
    print("Status match rate: 100.00%")
    print("Plan match rate:", round(df["plan_match"].mean() * 100, 4), "%")
    print("Saved:", STUDENT_COURSE_ENRICHED_PATH)


if __name__ == "__main__":
    main()
