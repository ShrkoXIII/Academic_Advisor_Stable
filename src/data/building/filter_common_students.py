"""Keep students present in both independently cleaned canonical tables."""

import pandas as pd

from src.paths import (
    CLEAN_STUDENT_COURSE_PATH,
    CLEAN_STUDENT_STATUS_PATH,
    PRE_COMMON_STUDENT_COURSE_PATH,
    PRE_COMMON_STUDENT_STATUS_PATH,
)


def filter_common_students(student_course, student_status):
    """Filter on student_id alone while preserving every row of shared students."""
    common_student_ids = set(student_status["student_id"].dropna()) & set(
        student_course["student_id"].dropna()
    )
    filtered_course = student_course.loc[
        student_course["student_id"].isin(common_student_ids)
    ].copy()
    filtered_status = student_status.loc[
        student_status["student_id"].isin(common_student_ids)
    ].copy()
    return filtered_course, filtered_status


def main():
    student_course = pd.read_parquet(PRE_COMMON_STUDENT_COURSE_PATH)
    student_status = pd.read_parquet(PRE_COMMON_STUDENT_STATUS_PATH)
    course_ids = set(student_course["student_id"].dropna())
    status_ids = set(student_status["student_id"].dropna())
    print("Students in status before:", len(status_ids))
    print("Students in course before:", len(course_ids))
    print("Students in both:", len(status_ids & course_ids))
    print("Only in status:", len(status_ids - course_ids))
    print("Only in course:", len(course_ids - status_ids))

    filtered_course, filtered_status = filter_common_students(student_course, student_status)
    after_course_ids = set(filtered_course["student_id"].dropna())
    after_status_ids = set(filtered_status["student_id"].dropna())
    if after_course_ids != after_status_ids:
        raise AssertionError("Common-student filtering produced unequal student sets")
    print("Students in status after:", len(after_status_ids))
    print("Students in course after:", len(after_course_ids))
    print("Only in status:", len(after_status_ids - after_course_ids))
    print("Only in course:", len(after_course_ids - after_status_ids))

    CLEAN_STUDENT_COURSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLEAN_STUDENT_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    filtered_course.to_parquet(CLEAN_STUDENT_COURSE_PATH, index=False)
    filtered_status.to_parquet(CLEAN_STUDENT_STATUS_PATH, index=False)
    print("Saved:", CLEAN_STUDENT_COURSE_PATH)
    print("Saved:", CLEAN_STUDENT_STATUS_PATH)


if __name__ == "__main__":
    main()
