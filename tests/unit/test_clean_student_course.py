from pathlib import Path
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.data.cleaning.clean_student_course as course_module  # noqa: E402


@pytest.fixture
def valid_course_row():
    """Small raw row containing every column used by the current cleaner."""
    return {
        "Student Course ID": " 1001.0 ",
        "Student ID": " S1 ",
        "Course ID": " C1 ",
        "Degree ID": " D1 ",
        "Grade ID": " 7.0 ",
        "Faculty ID": " 12.111 ",
        "Part ID": 20241,
        "Register Status": " r ",
        "Finish Status": " p ",
        "Final Mark": "88.0",
        "Points": "3.5",
        "Course Credits": "3.0",
        "Course Name SL": "  Machine Learning ",
        "Degree Name SL": "  Computer Science ",
        "In AGPA": " Y ",
        "In GPA": " y ",
        "In Credits": " Y ",
        "Active": "Y",
        "Student Name SL": " Student One ",
        "Study Mode": "C",
    }


@pytest.fixture
def valid_course_frame(valid_course_row):
    return pd.DataFrame([valid_course_row])


def test_clean_student_course_basic_contract_and_input_immutability(
    valid_course_frame,
):
    source = valid_course_frame.copy(deep=True)

    result = course_module.clean_student_course(source)

    assert_frame_equal(source, valid_course_frame)  # NOTE: a cleaner must not mutate the caller's raw DataFrame.
    assert result.index.tolist() == [0]  # NOTE: reset_index makes persisted row order reproducible.
    assert result.loc[0, "student_course_id"] == "1001"  # NOTE: normalized identifiers are the keys used downstream.
    assert result.loc[0, "course_outcome_status"] == "pass"  # NOTE: the mapped outcome is the model-facing result field.
    assert result.loc[0, "course_name_sl"] == "Machine Learning"  # NOTE: display text is trimmed before storage.
    assert result.loc[0, "degree_name_sl"] == "Computer Science"  # NOTE: display text is trimmed before storage.
    assert "register_status" not in result.columns  # NOTE: raw registration flags are internal cleaning inputs.
    assert "finish_status" not in result.columns  # NOTE: raw finish codes are replaced by course_outcome_status.
    assert "attempt_number" in result.columns  # NOTE: attempt number is a required derived course-history feature.


@pytest.mark.parametrize(
    "raw_status, expected_rows",
    [
        ("R", 1),
        (" r ", 1),
        ("E", 1),
        (" e ", 1),
        ("X", 0),
        ("", 0),
        (None, 0),
    ],
)
def test_registration_status_is_normalized_before_filtering(
    valid_course_frame,
    raw_status,
    expected_rows,
):
    raw = valid_course_frame.assign(**{"Register Status": raw_status})

    result = course_module.clean_student_course(raw)

    assert len(result) == expected_rows  # NOTE: only normalized R/E registrations belong in the cleaned course population.


@pytest.mark.parametrize(
    "raw_status, expected_outcome",
    [
        ("P", "pass"),
        (" p ", "pass"),
        ("F", "fail"),
        (" f ", "fail"),
        ("fe", "fail"),
        (" FE ", "fail"),
        ("fa", "fail"),
        (" FA ", "fail"),
    ],
)
def test_finish_status_map_normalizes_and_maps_current_codes(
    valid_course_frame,
    raw_status,
    expected_outcome,
):
    raw = valid_course_frame.assign(**{"Finish Status": raw_status})

    result = course_module.clean_student_course(raw)

    assert result["course_outcome_status"].tolist() == [expected_outcome]  # NOTE: all currently supported finish codes must map to the stable pass/fail contract.


@pytest.mark.parametrize("unsupported_status", ["WITHDRAWN", "W", "ACTIVE", "", None])
def test_unsupported_finish_statuses_are_currently_removed(
    valid_course_frame,
    unsupported_status,
):
    raw = valid_course_frame.assign(**{"Finish Status": unsupported_status})

    result = course_module.clean_student_course(raw)

    assert result.empty  # NOTE: unsupported codes are not currently retained as course outcomes.
    assert "attempt_number" in result.columns  # NOTE: even an empty result keeps the current derived schema.


def _course_row(valid_course_row, *, student, course, part, course_row_id, finish="P"):
    row = valid_course_row.copy()
    row.update(
        {
            "Student Course ID": course_row_id,
            "Student ID": student,
            "Course ID": course,
            "Degree ID": "D1",
            "Part ID": part,
            "Finish Status": finish,
            "Register Status": "R",
        }
    )
    return row


def test_attempts_are_numbered_per_student_and_course_after_chronological_sort(
    valid_course_row,
):
    raw = pd.DataFrame(
        [
            _course_row(valid_course_row, student="S2", course="C1", part=20222, course_row_id="50", finish="F"),
            _course_row(valid_course_row, student="S1", course="C1", part=20232, course_row_id="30", finish="P"),
            _course_row(valid_course_row, student="S1", course="C2", part=20222, course_row_id="40", finish="P"),
            _course_row(valid_course_row, student="S1", course="C1", part=20221, course_row_id="10", finish="F"),
            _course_row(valid_course_row, student="S1", course="C1", part=20231, course_row_id="20", finish="F"),
        ]
    )

    result = course_module.clean_student_course(raw)

    assert result.loc[result["student_id"].eq("S1") & result["course_id"].eq("C1"), "attempt_number"].tolist() == [1, 2, 3]  # NOTE: repeated attempts must be chronological within one student-course history.
    assert result.loc[result["student_id"].eq("S1") & result["course_id"].eq("C2"), "attempt_number"].tolist() == [1]  # NOTE: different courses start their own attempt sequence.
    assert result.loc[result["student_id"].eq("S2") & result["course_id"].eq("C1"), "attempt_number"].tolist() == [1]  # NOTE: the same course for another student is an independent history.
    assert result["student_course_id"].tolist() == ["10", "20", "30", "40", "50"]  # NOTE: final ordering is student, course, semester, then course-row ID.


def test_duplicate_student_course_semester_raises_value_error(valid_course_row):
    raw = pd.DataFrame(
        [
            _course_row(valid_course_row, student="S1", course="C1", part=20221, course_row_id="20", finish="P"),
            _course_row(valid_course_row, student="S1", course="C1", part=20221, course_row_id="10", finish="F"),
        ]
    )

    with pytest.raises(ValueError, match="student_id.*course_id.*part_id"):
        course_module.clean_student_course(raw)


def test_withdrawn_counts_as_attempt_before_removal(
    valid_course_row,
):
    raw = pd.DataFrame(
        [
            _course_row(valid_course_row, student="S1", course="C1", part=20221, course_row_id="10", finish="WITHDRAWN"),
            _course_row(valid_course_row, student="S1", course="C1", part=20231, course_row_id="20", finish="F"),
            _course_row(valid_course_row, student="S1", course="C1", part=20232, course_row_id="30", finish="P"),
        ]
    )

    result = course_module.clean_student_course(raw)

    assert result["part_id"].tolist() == [20231, 20232]
    assert result.index.tolist() == [0, 1]
    assert result["attempt_number"].tolist() == [2, 3]
    assert result["course_outcome_status"].tolist() == ["fail", "pass"]


@pytest.mark.parametrize(
    "part_id, expected_rows",
    [
        (20192, 0),
        (20193, 0),
        (20201, 1),
        (20241, 1),
    ],
)
def test_semester_cutoff_is_strictly_greater_than_20193(
    valid_course_frame,
    part_id,
    expected_rows,
):
    raw = valid_course_frame.assign(**{"Part ID": part_id})

    result = course_module.clean_student_course(raw)

    assert len(result) == expected_rows  # NOTE: the current temporal population excludes 20193 and every earlier semester.
    assert str(result["part_id"].dtype) == "Int64"  # NOTE: part_id is a nullable integer even when the row is filtered out.


@pytest.mark.parametrize(
    "column, raw_value, expected_value",
    [
        ("Student Course ID", " 100.0 ", "100"),
        ("Student ID", " 12.111 ", "12.111"),
        ("Course ID", " 123.0 ", "123"),
        ("Degree ID", " ABC-1 ", "ABC-1"),
        ("Grade ID", " 7.000 ", "7"),
        ("Faculty ID", " 12.111 ", "12.111"),
    ],
)
def test_all_course_id_columns_use_safe_id_normalization(
    valid_course_frame,
    column,
    raw_value,
    expected_value,
):
    result = course_module.clean_student_course(
        valid_course_frame.assign(**{column: raw_value})
    )

    assert result.loc[0, column.strip().lower().replace(" ", "_")] == expected_value  # NOTE: '.0' is removed only from integer-looking IDs; meaningful dotted IDs remain intact.


@pytest.mark.parametrize("column", ["Student Course ID", "Student ID", "Degree ID"])
def test_missing_required_key_raises_value_error(valid_course_frame, column):
    raw = valid_course_frame.assign(**{column: " none " if column != "Part ID" else None})

    with pytest.raises(ValueError, match="required key"):
        course_module.clean_student_course(raw)


@pytest.mark.parametrize("column, missing", [
    ("Course ID", None), ("Course ID", " none "), ("Course ID", "  "),
    ("Course ID", "<NA>"), ("Part ID", None), ("Part ID", ""),
    ("Part ID", "null"), ("Part ID", "not-a-part"),
])
def test_missing_critical_key_excludes_only_that_row(valid_course_row, column, missing):
    valid = dict(valid_course_row, **{"Student Course ID": "kept"})
    invalid = dict(valid_course_row, **{"Student Course ID": "excluded", column: missing})
    raw = pd.DataFrame([invalid, valid])
    before = raw.copy(deep=True)

    result = course_module.clean_student_course(raw)

    assert result.student_course_id.tolist() == ["kept"]
    assert result.course_id.tolist() == ["C1"]
    assert result.part_id.tolist() == [20241]
    assert result.attempt_number.tolist() == [1]
    assert_frame_equal(raw, before)  # No fill, inference, or mutation of raw rows.


def test_both_critical_keys_missing_on_same_row_yields_empty_clean_frame(valid_course_row):
    raw = pd.DataFrame([dict(valid_course_row, **{"Course ID": None, "Part ID": None})])
    result = course_module.clean_student_course(raw)
    assert result.empty
    assert "attempt_number" in result
    assert str(result.part_id.dtype) == "Int64"


def test_duplicate_student_course_id_raises_value_error(valid_course_row):
    raw = pd.DataFrame([
        _course_row(valid_course_row, student="S1", course="C1", part=20241, course_row_id="1"),
        _course_row(valid_course_row, student="S2", course="C2", part=20242, course_row_id=" 1.0 "),
    ])

    with pytest.raises(ValueError, match="student_course_id"):
        course_module.clean_student_course(raw)


def test_numeric_fields_are_converted_to_current_nullable_dtypes(valid_course_frame):
    raw = valid_course_frame.assign(
        **{
            "Final Mark": "88.0",
            "Points": "3.25",
            "Course Credits": "3.5",
        }
    )

    result = course_module.clean_student_course(raw)

    assert result.loc[0, "final_mark"] == 88  # NOTE: final marks are stored as nullable integer values.
    assert result.loc[0, "points"] == 3.25  # NOTE: model points preserve decimal precision.
    assert result.loc[0, "course_credits"] == 3.5  # NOTE: course credits support fractional values.
    assert str(result["final_mark"].dtype) == "Int64"  # NOTE: the current contract uses pandas nullable Int64 for marks.
    assert str(result["points"].dtype) == "Float64"  # NOTE: the current contract uses pandas nullable Float64 for points.
    assert str(result["course_credits"].dtype) == "Float64"  # NOTE: the current contract uses pandas nullable Float64 for credits.


@pytest.mark.parametrize("invalid_column", ["Final Mark", "Points", "Course Credits"])
def test_invalid_numeric_input_keeps_current_conversion_failure(
    valid_course_frame,
    invalid_column,
):
    with pytest.raises(ValueError):  # NOTE: pd.to_numeric currently raises; this test prevents accidental silent coercion.
        course_module.clean_student_course(
            valid_course_frame.assign(**{invalid_column: "not-a-number"})
        )


def test_text_fields_are_trimmed(valid_course_frame):
    result = course_module.clean_student_course(
        valid_course_frame.assign(
            **{
                "Course Name SL": "  Machine Learning ",
                "Degree Name SL": "  Computer Science ",
            }
        )
    )

    assert result.loc[0, "course_name_sl"] == "Machine Learning"  # NOTE: whitespace must not create duplicate text categories.
    assert result.loc[0, "degree_name_sl"] == "Computer Science"  # NOTE: whitespace must not create duplicate degree categories.


@pytest.mark.parametrize(
    "in_agpa, in_gpa, in_credits, expected_rows",
    [
        ("Y", "Y", "Y", 1),
        ("N", "Y", "Y", 0),
        ("Y", "N", "Y", 0),
        ("Y", "Y", "N", 0),
        (" y ", " y ", " n ", 0),
    ],
)
def test_any_exclusion_flag_n_removes_the_course(
    valid_course_frame,
    in_agpa,
    in_gpa,
    in_credits,
    expected_rows,
):
    raw = valid_course_frame.assign(
        **{
            "In AGPA": in_agpa,
            "In GPA": in_gpa,
            "In Credits": in_credits,
        }
    )

    result = course_module.clean_student_course(raw)

    assert len(result) == expected_rows  # NOTE: the current rule is an ANY-of-three exclusion, after trim and uppercase.


def test_deterministic_ordering_is_independent_of_source_order(valid_course_row):
    raw = pd.DataFrame(
        [
            _course_row(valid_course_row, student="S2", course="C2", part=20242, course_row_id="4", finish="P"),
            _course_row(valid_course_row, student="S1", course="C2", part=20241, course_row_id="3", finish="P"),
            _course_row(valid_course_row, student="S1", course="C1", part=20242, course_row_id="2", finish="P"),
            _course_row(valid_course_row, student="S1", course="C1", part=20241, course_row_id="1", finish="F"),
        ]
    )

    result = course_module.clean_student_course(raw)

    assert list(zip(result["student_id"], result["course_id"], result["part_id"], result["student_course_id"])) == [
        ("S1", "C1", 20241, "1"),
        ("S1", "C1", 20242, "2"),
        ("S1", "C2", 20241, "3"),
        ("S2", "C2", 20242, "4"),
    ]  # NOTE: deterministic order is required for reproducible attempt numbering and artifacts.


def test_raw_and_internal_columns_are_removed_but_outcome_remains(valid_course_frame):
    result = course_module.clean_student_course(valid_course_frame)

    for column in [
        "finish_status",
        "register_status",
        "active",
        "in_agpa",
        "in_gpa",
        "in_credits",
        "student_name_sl",
        "study_mode",
    ]:
        assert column not in result.columns  # NOTE: these source/internal fields are intentionally excluded from cleaned records.
    assert "course_outcome_status" in result.columns  # NOTE: the normalized outcome replaces the dropped raw finish code.


def test_empty_result_is_a_dataframe_with_current_output_schema(valid_course_frame):
    raw = valid_course_frame.assign(**{"Register Status": "X"})

    result = course_module.clean_student_course(raw)

    assert isinstance(result, pd.DataFrame)  # NOTE: downstream pipeline stages must handle an empty partition without a type change.
    assert result.empty  # NOTE: all rows are expected to be filtered by the registration contract.
    assert result.index.tolist() == []  # NOTE: empty outputs still have a clean reset index.
    assert "course_outcome_status" in result.columns  # NOTE: the current transformation schema is retained even with zero rows.
    assert "attempt_number" in result.columns  # NOTE: downstream code can consume the same derived-column schema.


def test_main_persists_the_same_cleaning_result_to_a_created_directory(
    tmp_path,
    monkeypatch,
    valid_course_row,
):
    raw = pd.DataFrame(
        [
            _course_row(valid_course_row, student="S1", course="C1", part=20241, course_row_id="1", finish="P"),
            _course_row(valid_course_row, student="S2", course="C1", part=20241, course_row_id="2", finish="P"),
            _course_row(valid_course_row, student="S1", course="C2", part=20241, course_row_id="3", finish="P"),
        ]
    )
    raw.loc[2, "Degree ID"] = "D2"
    raw_path = tmp_path / "raw" / "student_course.parquet"
    output_path = tmp_path / "nested" / "clean" / "student_course.parquet"
    raw_path.parent.mkdir(parents=True)
    raw.to_parquet(raw_path, index=False)
    monkeypatch.setattr(course_module, "STUDENT_COURSE_PATH", raw_path)
    monkeypatch.setattr(course_module, "PRE_COMMON_STUDENT_COURSE_PATH", output_path)

    course_module.main()

    expected = course_module.clean_student_course(raw)
    actual = pd.read_parquet(output_path)
    assert output_path.exists()  # NOTE: main must create its destination directory before writing.
    assert actual["student_course_id"].tolist() == ["1", "3", "2"]
    assert_frame_equal(actual, expected, check_dtype=False, check_column_type=False)  # NOTE: persisted values must match the direct transformation.
