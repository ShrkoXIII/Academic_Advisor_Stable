import pandas as pd

from src.features.feature_contract import FEATURE_ENGINEERING_VERSION
from src.paths import (
    CLEAN_STUDENT_STATUS_PATH,
    COURSE_HISTORY_STATE_PATH,
    TEMPORAL_TEST_FEATURES_PATH,
    TEMPORAL_TEST_PATH,
    TEMPORAL_TEST_ROSTER_PATH,
    TEMPORAL_TRAIN_FEATURES_PATH,
    TEMPORAL_TRAIN_PATH,
    TEMPORAL_TRAIN_ROSTER_PATH,
)
from src.features.temporal_features import (
    COURSE_HISTORY_COLUMNS,
    PLAN_CONTEXT_COLUMNS,
    add_student_history_features,
    build_temporal_course_history,
    compute_plan_context_features,
    save_course_history_state,
)


def attach_plan_context(target, enriched_roster):
    context = compute_plan_context_features(enriched_roster)
    lookup = pd.concat(
        [
            enriched_roster[["student_course_id"]].reset_index(drop=True),
            context.reset_index(drop=True),
        ],
        axis=1,
    )
    return target.merge(lookup, on="student_course_id", how="left")


def build_feature_tables(train, test, train_roster, test_roster, student_status=None):
    (
        train_history,
        train_roster_history,
        test_history,
        test_roster_history,
        state,
    ) = build_temporal_course_history(train, train_roster, test, test_roster)

    train = pd.concat(
        [train.reset_index(drop=True), train_history.reset_index(drop=True)],
        axis=1,
    )
    test = pd.concat(
        [test.reset_index(drop=True), test_history.reset_index(drop=True)],
        axis=1,
    )
    train_roster = pd.concat(
        [
            train_roster.reset_index(drop=True),
            train_roster_history.reset_index(drop=True),
        ],
        axis=1,
    )
    test_roster = pd.concat(
        [
            test_roster.reset_index(drop=True),
            test_roster_history.reset_index(drop=True),
        ],
        axis=1,
    )

    train = attach_plan_context(train, train_roster)
    test = attach_plan_context(test, test_roster)
    train, test = add_student_history_features(train, test, student_status)

    for frame in [train, test]:
        frame["part_semester"] = (frame["part_id"] % 10).astype("Int64")
        frame["is_fail"] = frame["final_mark"].lt(50).astype("int64")
        frame.attrs["feature_engineering_version"] = FEATURE_ENGINEERING_VERSION

    return train, test, state


def print_feature_summary(name, frame):
    print(f"\n{name} rows:", len(frame))
    print(f"{name} students:", frame["student_id"].nunique())
    print(f"{name} fail rate:", round(frame["is_fail"].mean() * 100, 3), "%")
    print(f"{name} GPA trend coverage:", round(frame["gpa_trend_delta"].notna().mean() * 100, 3), "%")
    print(
        f"{name} direct course-history coverage:",
        round(frame["course_history_fallback_level"].le(2).mean() * 100, 3),
        "%",
    )


def main():
    train, test, state = build_feature_tables(
        pd.read_parquet(TEMPORAL_TRAIN_PATH),
        pd.read_parquet(TEMPORAL_TEST_PATH),
        pd.read_parquet(TEMPORAL_TRAIN_ROSTER_PATH),
        pd.read_parquet(TEMPORAL_TEST_ROSTER_PATH),
        pd.read_parquet(CLEAN_STUDENT_STATUS_PATH),
    )

    TEMPORAL_TRAIN_FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    train.to_parquet(TEMPORAL_TRAIN_FEATURES_PATH, index=False)
    test.to_parquet(TEMPORAL_TEST_FEATURES_PATH, index=False)
    save_course_history_state(state, COURSE_HISTORY_STATE_PATH)

    print_feature_summary("Temporal train features", train)
    print_feature_summary("Temporal test features", test)
    print("New course-history columns:", COURSE_HISTORY_COLUMNS)
    print("New plan-context columns:", PLAN_CONTEXT_COLUMNS)
    print("Saved:", TEMPORAL_TRAIN_FEATURES_PATH)
    print("Saved:", TEMPORAL_TEST_FEATURES_PATH)
    print("Saved:", COURSE_HISTORY_STATE_PATH)


if __name__ == "__main__":
    main()
