from pathlib import Path
import sys

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.data.building.build_registration_roster as roster_module  # noqa: E402


def make_raw_course(**overrides):
    row = {
        "Student Course ID": "1.0",
        "Student ID": "S1",
        "Degree ID": "D1",
        "Faculty ID": "F1",
        "Course ID": "C1",
        "Part ID": 20241,
        "Course Credits": 3,
        "Register Status": "R",
        "Finish Status": " active ",
    }
    row.update(overrides)
    return row


def make_plan(course_id="C1"):
    return {
        "degree_id": "D1",
        "course_id": course_id,
        "course_type_id": "T1",
        "requirement_type_id": 1,
        "year_order": 1,
        "semester_order": 1,
        "credits_count": 3.0,
    }


@pytest.mark.parametrize(
    "register_status, expected_rows",
    [
        ("R", 1),
        (" e ", 1),
        ("X", 0),
        ("", 0),
        (None, 0),
    ],
)
def test_build_registration_roster_keeps_only_registered_or_enrolled(
    register_status,
    expected_rows,
):
    raw = pd.DataFrame([make_raw_course(**{"Register Status": register_status})])
    status = pd.DataFrame(
        {
            "student_status_id": ["ST1"],
            "student_id": ["S1"],
            "degree_id": ["D1"],
            "part_id": [20241],
        }
    )
    plan = pd.DataFrame([make_plan()])
    outliers = pd.DataFrame({"student_id": pd.Series(dtype="string")})

    result = roster_module.build_registration_roster(raw, status, plan, outliers)

    assert len(result) == expected_rows  # NOTE: workload context includes only actual R/E registrations, after trimming and case normalization.


@pytest.fixture
def roster_inputs():
    raw = pd.DataFrame(
        [
            make_raw_course(),
            make_raw_course(
                **{
                    "Student Course ID": "2.0",
                    "Student ID": "S2",
                    "Course ID": "C2",
                    "Part ID": 20251,
                    "Register Status": " e ",
                }
            ),
            make_raw_course(**{"Student Course ID": "3.0", "Register Status": "X"}),
            make_raw_course(**{"Student Course ID": "4.0", "Part ID": 20193}),
            make_raw_course(**{"Student Course ID": "5.0", "Student ID": "S3"}),
            make_raw_course(
                **{
                    "Student Course ID": "6.0",
                    "Course ID": "C3",
                    "Part ID": 20252,
                    "Register Status": "E",
                    "Course Credits": 4,
                }
            ),
        ]
    )
    status = pd.DataFrame(
        {
            "student_status_id": ["ST1", "ST2", "ST3"],
            "student_id": ["S1", "S1", "S2"],
            "degree_id": ["D1", "D1", "D1"],
            "part_id": [20241, 20252, 20251],
        }
    )
    plan = pd.DataFrame([make_plan("C1"), make_plan("C2")])
    outliers = pd.DataFrame({"student_id": ["S2"]})
    return raw, status, plan, outliers


def test_build_registration_roster_joins_exact_status_removes_outliers_and_keeps_plan_gaps(
    roster_inputs,
):
    result = roster_module.build_registration_roster(*roster_inputs)

    assert result["student_course_id"].tolist() == ["1", "6"]  # NOTE: filters, exact status membership, and student-level outlier removal all define the roster population.
    assert result["student_status_id"].tolist() == ["ST1", "ST2"]  # NOTE: each registration must inherit the status from the same student, degree, and semester.
    assert result["register_status"].tolist() == ["R", "E"]  # NOTE: normalized values prevent lowercase or whitespace variants from splitting categories.
    assert result["finish_status"].tolist() == ["ACTIVE", "ACTIVE"]  # NOTE: finish status is also a categorical model input and must be normalized.
    assert result["course_credits"].tolist() == [3.0, 4.0]  # NOTE: roster credit-load calculations require numeric credits.
    assert result.loc[result["course_id"].eq("C1"), "plan_course_type_id"].item() == "T1"  # NOTE: matching curriculum metadata must be attached to the registration.
    assert pd.isna(result.loc[result["course_id"].eq("C3"), "plan_course_type_id"]).all()  # NOTE: unmatched curriculum courses remain in the roster with explicit missing plan data.
    assert result.columns.tolist() == roster_module.ROSTER_COLUMNS  # NOTE: temporal feature builders depend on the fixed roster schema.


def test_main_writes_full_train_and_test_rosters(tmp_path, monkeypatch):
    raw = pd.DataFrame(
        [
            make_raw_course(**{"Student Course ID": "1.0", "Part ID": 20241}),
            make_raw_course(**{"Student Course ID": "2.0", "Part ID": 20251}),
            make_raw_course(**{"Student Course ID": "3.0", "Part ID": 20253}),
        ]
    )
    status = pd.DataFrame(
        {
            "student_status_id": ["ST1", "ST2", "ST3"],
            "student_id": ["S1", "S1", "S1"],
            "degree_id": ["D1", "D1", "D1"],
            "part_id": [20241, 20251, 20253],
        }
    )
    plan = pd.DataFrame([make_plan()])
    outliers = pd.DataFrame({"student_id": pd.Series(dtype="string")})
    input_paths = {
        "STUDENT_COURSE_PATH": tmp_path / "raw_courses.parquet",
        "CLEAN_STUDENT_STATUS_PATH": tmp_path / "status.parquet",
        "CLEAN_DEGREE_COURSE_PATH": tmp_path / "plan.parquet",
        "OUTLIER_STUDENTS_AUDIT_PATH": tmp_path / "outliers.parquet",
    }
    output_paths = {
        "CLEAN_REGISTRATION_ROSTER_PATH": tmp_path / "clean" / "roster.parquet",
        "TEMPORAL_TRAIN_ROSTER_PATH": tmp_path / "temporal" / "train_roster.parquet",
        "TEMPORAL_TEST_ROSTER_PATH": tmp_path / "temporal" / "test_roster.parquet",
    }
    raw.to_parquet(input_paths["STUDENT_COURSE_PATH"], index=False)
    status.to_parquet(input_paths["CLEAN_STUDENT_STATUS_PATH"], index=False)
    plan.to_parquet(input_paths["CLEAN_DEGREE_COURSE_PATH"], index=False)
    outliers.to_parquet(input_paths["OUTLIER_STUDENTS_AUDIT_PATH"], index=False)
    for name, path in {**input_paths, **output_paths}.items():
        monkeypatch.setattr(roster_module, name, path)

    roster_module.main()

    full = pd.read_parquet(output_paths["CLEAN_REGISTRATION_ROSTER_PATH"])
    train = pd.read_parquet(output_paths["TEMPORAL_TRAIN_ROSTER_PATH"])
    test = pd.read_parquet(output_paths["TEMPORAL_TEST_ROSTER_PATH"])
    assert full["part_id"].tolist() == [20241, 20251, 20253]  # NOTE: the clean roster keeps all valid semesters for reusable workload history.
    assert train["part_id"].tolist() == [20241]  # NOTE: training roster must obey the central temporal split constants.
    assert test["part_id"].tolist() == [20251]  # NOTE: test roster must exclude both training and incomplete semesters.


@pytest.mark.parametrize("duplicate_input", [1, 2], ids=["status", "degree_plan"])
def test_duplicate_merge_keys_raise_instead_of_multiplying_rows(roster_inputs, duplicate_input):
    inputs = list(roster_inputs)
    frame = inputs[duplicate_input]
    inputs[duplicate_input] = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(pd.errors.MergeError, match="not a many-to-one merge"):
        roster_module.build_registration_roster(*inputs)
