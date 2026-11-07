from pathlib import Path
import sys

import pandas as pd
import pytest
from pandas.errors import MergeError
from pandas.testing import assert_frame_equal


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.data.cleaning.clean_student_diploma as diploma_module  # noqa: E402


@pytest.fixture
def academic_info():
    return pd.DataFrame(
        {
            " Student ID ": ["1.111", "2.111", "3.111", "4.111", "5.111", "6.111", "7.111"],
            "Diploma GPA": [3.0, None, 2.5, 2.0, 3.5, 1.5, 4.0],
            "Diploma Type ID": [1, 1, 2, 3, 4, 5, None],
            "Unused": ["x"] * 7,
        }
    )


def test_clean_student_diploma_groups_rare_types_and_fills_gpa(academic_info):
    result = diploma_module.clean_student_diploma(academic_info)

    assert result.columns.tolist() == diploma_module.FINAL_COLUMNS  # NOTE: only stable diploma features may enter the course table.
    assert result["student_id"].tolist() == ["1.111", "2.111", "3.111", "4.111", "5.111", "6.111"]  # NOTE: rows without a diploma type are unusable and must be removed.
    assert result.loc[result["student_id"].eq("2.111"), "diploma_gpa"].item() == 3.0  # NOTE: the approved forward-fill policy must remain explicit and reproducible.
    assert result.loc[result["student_id"].eq("6.111"), "diploma_type_id"].item() == diploma_module.RARE_DIPLOMA_TYPE_ID  # NOTE: types outside the four most frequent groups share the rare category.


@pytest.mark.parametrize(
    "case, expected_exception, expected_message",
    [
        ("missing_column", KeyError, "Missing required"),
        ("missing_student", ValueError, "student_id contains missing"),
        ("duplicate_student", ValueError, "student_id must be unique"),
    ],
)
def test_clean_student_diploma_rejects_broken_input_contract(
    academic_info,
    case,
    expected_exception,
    expected_message,
):
    frame = academic_info.iloc[:2].copy()
    if case == "missing_column":
        frame = frame.drop(columns="Diploma GPA")
    elif case == "missing_student":
        frame.loc[frame.index[0], " Student ID "] = None
    else:
        frame.loc[frame.index[1], " Student ID "] = frame.loc[frame.index[0], " Student ID "]

    with pytest.raises(expected_exception, match=expected_message):  # NOTE: invalid keys must fail before a many-to-one merge can corrupt row counts.
        diploma_module.clean_student_diploma(frame)


def test_merge_student_course_with_diploma_preserves_unmatched_courses():
    courses = pd.DataFrame(
        {
            "student_course_id": ["C1", "C2", "C3"],
            "student_id": ["1.111", "2.111", "9.111"],
        }
    )
    diplomas = pd.DataFrame(
        {
            "student_id": ["1.111", "2.111"],
            "diploma_gpa": [3.0, 2.5],
            "diploma_type_id": [1.0, 2.0],
        }
    )

    result = diploma_module.merge_student_course_with_diploma(courses, diplomas)

    assert len(result) == len(courses)  # NOTE: a left feature join must never remove course observations.
    assert pd.isna(result.loc[result["student_id"].eq("9.111"), "diploma_type_id"]).all()  # NOTE: unmatched students remain visible for later auditing.


@pytest.mark.parametrize("invalid_source", ["existing_columns", "duplicate_diploma"])
def test_merge_student_course_with_diploma_rejects_ambiguous_features(invalid_source):
    courses = pd.DataFrame({"student_course_id": ["C1"], "student_id": ["1.111"]})
    diplomas = pd.DataFrame(
        {"student_id": ["1.111"], "diploma_gpa": [3.0], "diploma_type_id": [1.0]}
    )
    if invalid_source == "existing_columns":
        courses["diploma_gpa"] = 2.0
        expected_exception = ValueError
    else:
        diplomas = pd.concat([diplomas, diplomas], ignore_index=True)
        expected_exception = MergeError

    with pytest.raises(expected_exception):  # NOTE: duplicate or pre-existing features would make diploma provenance ambiguous.
        diploma_module.merge_student_course_with_diploma(courses, diplomas)


def test_main_writes_clean_and_merged_diploma_artifacts(
    tmp_path,
    monkeypatch,
    academic_info,
):
    courses = pd.DataFrame(
        {
            "student_course_id": ["C1", "C2"],
            "student_id": ["1.111", "9.111"],
        }
    )
    academic_path = tmp_path / "academic.parquet"
    course_path = tmp_path / "courses.parquet"
    clean_path = tmp_path / "clean" / "student_diploma.parquet"
    merged_path = tmp_path / "merged" / "course_diploma.parquet"
    academic_info.to_parquet(academic_path, index=False)
    courses.to_parquet(course_path, index=False)
    monkeypatch.setattr(diploma_module, "ACADEMIC_INFO_PATH", academic_path)
    monkeypatch.setattr(diploma_module, "STUDENT_COURSE_ENRICHED_PATH", course_path)
    monkeypatch.setattr(diploma_module, "CLEAN_STUDENT_DIPLOMA_PATH", clean_path)
    monkeypatch.setattr(diploma_module, "STUDENT_COURSE_DIPLOMA_PATH", merged_path)

    diploma_module.main()

    expected_clean = diploma_module.clean_student_diploma(academic_info)
    expected_merged = diploma_module.merge_student_course_with_diploma(courses, expected_clean)
    assert clean_path.exists() and merged_path.exists()  # NOTE: the script contract includes both output artifacts.
    assert_frame_equal(
        pd.read_parquet(clean_path),
        expected_clean,
        check_column_type=False,
    )  # NOTE: compare persisted values/dtypes while ignoring Parquet's non-semantic column-index dtype.
    assert_frame_equal(
        pd.read_parquet(merged_path),
        expected_merged,
        check_column_type=False,
        check_dtype=False,
    )  # NOTE: verify the row-preserving values while allowing Parquet to restore object strings as StringDtype.
