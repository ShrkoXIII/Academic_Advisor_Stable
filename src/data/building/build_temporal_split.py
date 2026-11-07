import pandas as pd

from src.paths import (
    STUDENT_COURSE_WITHOUT_OUTLIERS_PATH,
    TEMPORAL_TEST_PATH,
    TEMPORAL_TRAIN_PATH,
)


TRAIN_PARTS = [
    20201,
    20202,
    20203,
    20211,
    20212,
    20213,
    20221,
    20222,
    20223,
    20231,
    20232,
    20233,
    20241,
    20242,
    20243,
]
TEST_PARTS = [20251, 20252]
INCOMPLETE_PARTS = [20253]
TARGET_COLUMN = "course_outcome_status"


def build_temporal_split(df):
    train = df[df["part_id"].isin(TRAIN_PARTS)].copy()
    test = df[df["part_id"].isin(TEST_PARTS)].copy()
    incomplete = df[df["part_id"].isin(INCOMPLETE_PARTS)]

    sort_columns = [
        "part_id",
        "student_id",
        "course_id",
        "student_course_id",
    ]
    train = train.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    test = test.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    return train, test, incomplete


def summarize_split(name, df):
    summary = (
        df.assign(is_fail=df[TARGET_COLUMN].eq("fail"))
        .groupby("part_id", as_index=False)
        .agg(
            rows=("student_course_id", "size"),
            students=("student_id", "nunique"),
            fail_rate=("is_fail", "mean"),
        )
    )
    summary["fail_rate"] = (summary["fail_rate"] * 100).round(2)
    print(f"\n{name}:")
    print(summary.to_string(index=False))
    print("Total rows:", len(df))
    print("Unique students:", df["student_id"].nunique())


def main():
    df = pd.read_parquet(STUDENT_COURSE_WITHOUT_OUTLIERS_PATH)
    temporal_train, temporal_test, incomplete = build_temporal_split(df)

    TEMPORAL_TRAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporal_train.to_parquet(TEMPORAL_TRAIN_PATH, index=False)
    temporal_test.to_parquet(TEMPORAL_TEST_PATH, index=False)

    summarize_split("Temporal train", temporal_train)
    summarize_split("Temporal test", temporal_test)
    print("\nExcluded incomplete rows:", len(incomplete))
    print("Excluded parts:", sorted(incomplete["part_id"].unique().tolist()))
    print("Saved temporal train:", TEMPORAL_TRAIN_PATH)
    print("Saved temporal test:", TEMPORAL_TEST_PATH)


if __name__ == "__main__":
    main()
