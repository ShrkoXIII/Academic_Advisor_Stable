import pandas as pd

from src.data.cleaning.cleaning_utils import clean_column_names, clean_id_columns, to_float, to_integer
from src.paths import (
    CLEAN_DEGREE_COURSE_PATH,
    CLEAN_REGISTRATION_ROSTER_PATH,
    CLEAN_STUDENT_STATUS_PATH,
    OUTLIER_STUDENTS_AUDIT_PATH,
    STUDENT_COURSE_PATH,
    TEMPORAL_TEST_ROSTER_PATH,
    TEMPORAL_TRAIN_ROSTER_PATH,
)
from src.data.building.build_temporal_split import TEST_PARTS, TRAIN_PARTS


ROSTER_COLUMNS = [
    "student_course_id",
    "student_status_id",
    "student_id",
    "degree_id",
    "faculty_id",
    "course_id",
    "part_id",
    "course_credits",
    "register_status",
    "finish_status",
    "plan_course_type_id",
    "plan_requirement_type_id",
    "plan_year_order",
    "plan_semester_order",
    "plan_credits_count",
]


def build_registration_roster(raw_courses, student_status, degree_courses, outliers):
    roster = clean_column_names(raw_courses)
    roster["register_status"] = (
        roster["register_status"].astype("string").str.strip().str.upper()
    )
    roster = roster[roster["register_status"].isin(["R", "E"])].copy()
    roster["finish_status"] = (
        roster["finish_status"].astype("string").str.strip().str.upper()
    )
    roster["part_id"] = to_integer(roster["part_id"])
    roster = roster[roster["part_id"] > 20193].copy()
    roster = clean_id_columns(
        roster,
        [
            "student_course_id",
            "student_id",
            "degree_id",
            "faculty_id",
            "course_id",
        ],
    )
    roster["course_credits"] = to_float(roster["course_credits"])

    status_keys = student_status[
        ["student_status_id", "student_id", "degree_id", "part_id"]
    ]
    roster = roster.merge(
        status_keys,
        on=["student_id", "degree_id", "part_id"],
        how="inner",
        validate="many_to_one",
    )
    roster = roster[~roster["student_id"].isin(outliers["student_id"])].copy()

    plan = degree_courses[
        [
            "degree_id",
            "course_id",
            "course_type_id",
            "requirement_type_id",
            "year_order",
            "semester_order",
            "credits_count",
        ]
    ].rename(
        columns={
            "course_type_id": "plan_course_type_id",
            "requirement_type_id": "plan_requirement_type_id",
            "year_order": "plan_year_order",
            "semester_order": "plan_semester_order",
            "credits_count": "plan_credits_count",
        }
    )
    roster = roster.merge(plan, on=["degree_id", "course_id"], how="left", validate="many_to_one")
    return roster[ROSTER_COLUMNS].sort_values(
        ["part_id", "student_id", "course_id", "student_course_id"],
        kind="stable",
    ).reset_index(drop=True)


def main():
    roster = build_registration_roster(
        pd.read_parquet(STUDENT_COURSE_PATH),
        pd.read_parquet(CLEAN_STUDENT_STATUS_PATH),
        pd.read_parquet(CLEAN_DEGREE_COURSE_PATH),
        pd.read_parquet(OUTLIER_STUDENTS_AUDIT_PATH),
    )
    temporal_train_roster = roster[roster["part_id"].isin(TRAIN_PARTS)].copy()
    temporal_test_roster = roster[roster["part_id"].isin(TEST_PARTS)].copy()

    CLEAN_REGISTRATION_ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPORAL_TRAIN_ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    roster.to_parquet(CLEAN_REGISTRATION_ROSTER_PATH, index=False)
    temporal_train_roster.to_parquet(TEMPORAL_TRAIN_ROSTER_PATH, index=False)
    temporal_test_roster.to_parquet(TEMPORAL_TEST_ROSTER_PATH, index=False)

    print("Roster rows:", len(roster))
    print("Roster students:", roster["student_id"].nunique())
    print("Temporal train roster rows:", len(temporal_train_roster))
    print("Temporal test roster rows:", len(temporal_test_roster))
    print("Saved:", CLEAN_REGISTRATION_ROSTER_PATH)
    print("Saved:", TEMPORAL_TRAIN_ROSTER_PATH)
    print("Saved:", TEMPORAL_TEST_ROSTER_PATH)


if __name__ == "__main__":
    main()
