import pandas as pd
from pandas.testing import assert_frame_equal

import src.data.building.filter_common_students as module
from src.data.building.filter_common_students import filter_common_students


def test_keeps_only_students_present_in_both_tables():
    status = pd.DataFrame({"student_id": ["A", "B", "C"], "part_id": [20251] * 3})
    course = pd.DataFrame({"student_id": ["B", "C", "D"], "part_id": [20251] * 3})

    filtered_course, filtered_status = filter_common_students(course, status)

    assert filtered_status.student_id.tolist() == ["B", "C"]
    assert filtered_course.student_id.tolist() == ["B", "C"]
    assert set(filtered_status.student_id) == set(filtered_course.student_id)


def test_keeps_all_rows_for_common_student_despite_different_parts_and_degrees():
    status = pd.DataFrame({
        "student_id": ["A", "A"], "degree_id": ["degree1", "degree2"],
        "part_id": [20251, 20253],
    })
    course = pd.DataFrame({
        "student_id": ["A", "A"], "degree_id": ["degree1", "degree3"],
        "part_id": [20252, 20253],
    })

    filtered_course, filtered_status = filter_common_students(course, status)

    assert_frame_equal(filtered_course, course)
    assert_frame_equal(filtered_status, status)
    assert filtered_course is not course
    assert filtered_status is not status


def test_does_not_modify_inputs_in_place():
    status = pd.DataFrame({"student_id": ["A", "B"], "part_id": [20251, 20252]})
    course = pd.DataFrame({"student_id": ["B", "C"], "part_id": [20253, 20251]})
    original_status, original_course = status.copy(deep=True), course.copy(deep=True)

    filtered_course, filtered_status = filter_common_students(course, status)
    filtered_course.loc[:, "part_id"] = 20243
    filtered_status.loc[:, "part_id"] = 20243

    assert_frame_equal(status, original_status)
    assert_frame_equal(course, original_course)


def test_stage_reads_pre_common_and_writes_canonical_outputs(tmp_path, monkeypatch, capsys):
    course = pd.DataFrame({"student_id": ["B", "C", "D"], "part_id": [20251] * 3})
    status = pd.DataFrame({"student_id": ["A", "B", "C"], "part_id": [20252] * 3})
    paths = {
        "PRE_COMMON_STUDENT_COURSE_PATH": tmp_path / "course_pre.parquet",
        "PRE_COMMON_STUDENT_STATUS_PATH": tmp_path / "status_pre.parquet",
        "CLEAN_STUDENT_COURSE_PATH": tmp_path / "course.parquet",
        "CLEAN_STUDENT_STATUS_PATH": tmp_path / "status.parquet",
    }
    course.to_parquet(paths["PRE_COMMON_STUDENT_COURSE_PATH"])
    status.to_parquet(paths["PRE_COMMON_STUDENT_STATUS_PATH"])
    for name, path in paths.items():
        monkeypatch.setattr(module, name, path)

    module.main()

    assert pd.read_parquet(paths["CLEAN_STUDENT_COURSE_PATH"]).student_id.tolist() == ["B", "C"]
    assert pd.read_parquet(paths["CLEAN_STUDENT_STATUS_PATH"]).student_id.tolist() == ["B", "C"]
    output = capsys.readouterr().out
    assert "Only in status: 1" in output
    assert "Only in course: 1" in output
    assert "Students in status after: 2" in output
    assert "Students in course after: 2" in output
