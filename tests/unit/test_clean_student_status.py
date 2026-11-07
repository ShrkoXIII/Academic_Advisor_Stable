from pathlib import Path
import json
import shutil
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.data.cleaning.clean_student_status as status_module  # noqa: E402


def make_status_row(**overrides):
    row = {
        "student_status_id": "100.0",
        "student_id": "1.111",
        "part_id": 20241,
        "degree_id": "10.111",
        "degree_name_sl": "  Computer Science  ",
        "start_part_id": 20201,
        "finish_part_id": 20252,
        "grade_version_id": "1.0",
        "prev_gpa_points": 2.5,
        "gpa_percent": 75,
        "gpa_points": 3.0,
        "start_agpa_points": 2.5,
        "start_total_in_courses": 8,
        "start_total_in_credits": 24,
        "end_total_in_courses": 12,
        "end_total_in_credits": 36,
        "end_agpa_points": 3.0,
        "semester_reg_courses": 4,
        "semester_reg_credits": 12,
        "semester_pass_courses": 4,
        "semester_pass_credits": 12,
        "semester_fail_courses": 0,
        "semester_fail_credits": 0,
        "total_semesters": 3,
        "total_reg_courses": 8,
        "total_reg_credits": 24,
        "total_pass_courses": 8,
        "total_pass_credits": 24,
        "total_fail_courses": 0,
        "total_fail_credits": 0,
        "reg_total_semesters": 3,
        "finish_status": " active ",
        "degree_credits_count": 132,
        "start_level_name_short": "  Y2 ",
        "end_level_name_short": " Y2  ",
        "permanent_status_id": 2,
        "study_mode": " c ",
    }
    row.update(overrides)
    return row


@pytest.fixture
def enrollment_features():
    frame = pd.DataFrame(
        [
            {
                "student_status_id": "A-3",
                "student_id": "A",
                "part_id": 20232,
                "semester_reg_courses": 4,
                "gpa_points": 3.2,
                "prev_gpa_points": 0.0,
                "total_reg_courses": 4,
                "total_reg_credits": 12,
                "start_total_in_courses": 4,
                "start_total_in_credits": 12,
            },
            {
                "student_status_id": "A-1",
                "student_id": "A",
                "part_id": 20221,
                "semester_reg_courses": 4,
                "gpa_points": 0.0,
                "prev_gpa_points": 0.0,
                "total_reg_courses": 0,
                "total_reg_credits": 0,
                "start_total_in_courses": 0,
                "start_total_in_credits": 0,
            },
            {
                "student_status_id": "A-2",
                "student_id": "A",
                "part_id": 20231,
                "semester_reg_courses": 0,
                "gpa_points": 4.0,
                "prev_gpa_points": 0.0,
                "total_reg_courses": 4,
                "total_reg_credits": 12,
                "start_total_in_courses": 4,
                "start_total_in_credits": 12,
            },
            {
                "student_status_id": "B-1",
                "student_id": "B",
                "part_id": 20201,
                "semester_reg_courses": 3,
                "gpa_points": 3.0,
                "prev_gpa_points": 2.7,
                "total_reg_courses": 5,
                "total_reg_credits": 15,
                "start_total_in_courses": 5,
                "start_total_in_credits": 15,
            },
            {
                "student_status_id": "C-1",
                "student_id": "C",
                "part_id": 20201,
                "semester_reg_courses": 3,
                "gpa_points": 3.0,
                "prev_gpa_points": 2.7,
                "total_reg_courses": 0,
                "total_reg_credits": 0,
                "start_total_in_courses": 0,
                "start_total_in_credits": 0,
            },
        ]
    )
    frame["degree_id"] = "D1"
    return status_module.add_enrollment_features(frame)


@pytest.mark.parametrize(
    "student_id, part_id, expected_gpa, expected_gap",
    [
        ("A", 20221, None, None),
        ("A", 20231, 0.0, 2),
        ("A", 20232, 0.0, 2),
        ("B", 20201, 2.7, None),
        ("C", 20201, None, None),
    ],
)
def test_add_enrollment_features_tracks_only_observed_history(
    enrollment_features,
    student_id,
    part_id,
    expected_gpa,
    expected_gap,
):
    row = enrollment_features.loc[
        enrollment_features["student_id"].eq(student_id)
        & enrollment_features["part_id"].eq(part_id)
    ].iloc[0]

    actual_gpa = row["last_enrolled_gpa"]
    actual_gap = row["observed_gap_semesters"]
    assert (
        pd.isna(actual_gpa) if expected_gpa is None else actual_gpa == expected_gpa
    )  # NOTE: a current or non-enrolled GPA must never replace prior enrolled GPA.
    assert (
        pd.isna(actual_gap) if expected_gap is None else actual_gap == expected_gap
    )  # NOTE: gaps are meaningful only after an observed enrollment.


@pytest.mark.parametrize(
    "parts, registered_parts, expected_gaps",
    [
        ([20221, 20222], {20221, 20222}, {20222: 0}),
        ([20221, 20223], {20221, 20223}, {20223: 1}),
        ([20222, 20223, 20231], {20222, 20231}, {20231: 0}),
        ([20221, 20231], {20221, 20231}, {20231: 1}),
        ([20221, 20222, 20223, 20231, 20232], {20221, 20232}, {20232: 2}),
        ([20221, 20222, 20223, 20231], {20221, 20223, 20231}, {20223: 1, 20231: 0}),
    ],
)
def test_observed_gap_counts_regular_semesters_between_enrollments(
    parts, registered_parts, expected_gaps
):
    raw = pd.DataFrame([
        make_status_row(
            student_status_id=str(part),
            part_id=part,
            semester_reg_courses=4 if part in registered_parts else 0,
        )
        for part in reversed(parts)
    ])

    result = status_module.clean_student_status(raw).set_index("part_id")

    for part, expected in expected_gaps.items():
        assert result.loc[part, "observed_gap_semesters"] == expected


def test_optional_non_enrollment_does_not_increase_gap():
    raw = pd.DataFrame([
        make_status_row(student_status_id="1", part_id=20222, semester_reg_courses=4),
        make_status_row(student_status_id="2", part_id=20223, semester_reg_courses=0),
        make_status_row(student_status_id="3", part_id=20231, semester_reg_courses=0),
    ])

    result = status_module.clean_student_status(raw).set_index("part_id")

    assert result.loc[20223, "observed_gap_semesters"] == 0
    assert result.loc[20231, "observed_gap_semesters"] == 1


@pytest.mark.parametrize("invalid_part", [20214, 20224, 20254])
def test_semester_four_is_excluded_before_enrollment_history(invalid_part):
    raw = pd.DataFrame([
        make_status_row(student_status_id="1", part_id=20211, gpa_points=2.1),
        make_status_row(student_status_id="2", part_id=20212, gpa_points=2.2),
        make_status_row(student_status_id="3", part_id=20213, gpa_points=2.3),
        make_status_row(student_status_id="invalid", part_id=invalid_part, gpa_points=0.0),
        make_status_row(student_status_id="4", part_id=20261, gpa_points=3.0),
    ])
    before = raw.copy(deep=True)

    result = status_module.clean_student_status(raw)
    expected = status_module.clean_student_status(raw[raw.student_status_id.ne("invalid")])
    assert result.part_id.tolist() == [20211, 20212, 20213, 20261]
    assert result.iloc[-1].last_enrolled_gpa == 2.3
    assert_frame_equal(result, expected)
    assert_frame_equal(raw, before)


def test_only_semester_four_rows_produce_empty_clean_status():
    raw = pd.DataFrame([make_status_row(part_id=20214)])

    result = status_module.clean_student_status(raw)
    assert result.empty
    assert result.columns.tolist() == status_module.FINAL_COLUMNS


@pytest.mark.parametrize("invalid_part", [20210, 20215])
def test_other_invalid_semesters_remain_strict(invalid_part):
    raw = pd.DataFrame([make_status_row(part_id=invalid_part)])
    with pytest.raises(ValueError, match="part_id"):
        status_module.clean_student_status(raw)


def test_enrolled_optional_semester_updates_last_enrolled_gpa():
    raw = pd.DataFrame([
        make_status_row(student_status_id="1", part_id=20221, gpa_points=2.5),
        make_status_row(student_status_id="2", part_id=20223, gpa_points=2.8),
        make_status_row(student_status_id="3", part_id=20231, gpa_points=3.0),
    ])

    result = status_module.clean_student_status(raw).set_index("part_id")

    assert result.loc[20231, "last_enrolled_gpa"] == 2.8
    assert result.loc[20231, "observed_gap_semesters"] == 0


@pytest.mark.parametrize(
    "excluded_field, excluded_value",
    [
        ("permanent_status_id", 1),
        ("finish_status", " withdrawn "),
        ("study_mode", " E "),
        ("degree_id", " none "),
    ],
)
def test_business_filters_remove_only_the_matching_row(excluded_field, excluded_value):
    raw = pd.DataFrame([
        make_status_row(student_status_id="101", student_id="1.111"),
        make_status_row(student_status_id="102", student_id="2.111", **{excluded_field: excluded_value}),
    ])

    result = status_module.clean_student_status(raw)

    assert result["student_status_id"].tolist() == ["101"]


@pytest.mark.parametrize("permanent_status_id", [1, 4, 11, 12, 15, 16, 41])
def test_every_excluded_permanent_status_id_is_filtered(permanent_status_id):
    raw = pd.DataFrame([
        make_status_row(student_status_id="101", student_id="1.111"),
        make_status_row(student_status_id="102", student_id="2.111", permanent_status_id=permanent_status_id),
    ])

    assert status_module.clean_student_status(raw)["student_status_id"].tolist() == ["101"]


@pytest.mark.parametrize(
    "excluded_field, excluded_value, expected_gpa, expected_gap",
    [
        ("permanent_status_id", 1, 2.8, 0),
        ("finish_status", " withdrawn ", 2.8, 0),
        ("study_mode", " E ", 2.8, 0),
        # An unknown degree cannot supply a known degree's history. The row is
        # still filtered after history, just like the other excluded statuses.
        ("degree_id", " none ", 2.5, 1),
    ],
)
def test_filtered_row_still_supplies_prior_enrollment_history(
    excluded_field, excluded_value, expected_gpa, expected_gap
):
    raw = pd.DataFrame([
        make_status_row(student_status_id="101", part_id=20221, gpa_points=2.5),
        make_status_row(student_status_id="102", part_id=20222, gpa_points=2.8, **{excluded_field: excluded_value}),
        make_status_row(student_status_id="103", part_id=20231, gpa_points=3.0),
    ])

    result = status_module.clean_student_status(raw)

    assert result["student_status_id"].tolist() == ["101", "103"]
    assert result.loc[1, "last_enrolled_gpa"] == expected_gpa
    assert result.loc[1, "observed_gap_semesters"] == expected_gap


def test_clean_student_status_preserves_columns_and_normalizes_ids_and_text():
    raw = pd.DataFrame(
        [
            make_status_row(
                student_status_id="101",
                part_id=20221,
                semester_reg_courses=4,
                gpa_points=2.5,
            ),
            make_status_row(
                student_status_id="102",
                part_id=20231,
                semester_reg_courses=0,
                gpa_points=0,
            ),
            make_status_row(student_status_id="103", part_id=20232),
        ]
    )

    result = status_module.clean_student_status(raw)

    assert result["student_status_id"].tolist() == ["101", "102", "103"]
    assert result.columns.tolist() == status_module.FINAL_COLUMNS  # NOTE: downstream feature code depends on the exact output contract.
    assert result.loc[2, "last_enrolled_gpa"] == 2.5
    assert result.loc[2, "observed_gap_semesters"] == 2
    assert result.loc[0, "degree_name_sl"] == "Computer Science"  # NOTE: display categories must not keep source whitespace.
    assert result.loc[0, "student_id"] == "1.111"
    assert result.loc[0, "grade_version_id"] == "1"


def test_part_id_cutoff_still_excludes_20193():
    raw = pd.DataFrame([
        make_status_row(student_status_id="1", part_id=20193),
        make_status_row(student_status_id="2", part_id=20201),
    ])

    assert status_module.clean_student_status(raw)["part_id"].tolist() == [20201]


def test_main_reads_only_status_and_writes_complete_clean_status(tmp_path, monkeypatch):
    raw = pd.DataFrame([make_status_row()])
    raw_path = tmp_path / "raw_status.parquet"
    output_path = tmp_path / "nested" / "student_status.parquet"
    raw.to_parquet(raw_path, index=False)
    monkeypatch.setattr(status_module, "STUDENT_STATUS_PATH", raw_path)
    monkeypatch.setattr(status_module, "PRE_COMMON_STUDENT_STATUS_PATH", output_path)

    status_module.main()

    expected = status_module.clean_student_status(raw)
    assert output_path.exists()  # NOTE: main must create its destination directory and artifact.
    assert_frame_equal(
        pd.read_parquet(output_path),
        expected,
        check_column_type=False,
    )  # NOTE: compare persisted values/dtypes while ignoring Parquet's non-semantic column-index dtype.


@pytest.fixture
def degree_history_raw():
    # IDs are synthetic. Interleave degrees and students and scramble input order.
    records = [
        ("A-first", "S1", "D1", 20221, 4, 2.1),
        ("A-gap", "S1", "D1", 20222, 0, 4.0),
        ("B-first", "S1", "D2", 20231, 0, 3.9),
        ("B-enrolled", "S1", "D2", 20232, 4, 3.2),
        ("B-summer", "S1", "D2", 20233, 2, 3.4),
        ("A-return", "S1", "D1", 20241, 4, 2.4),
        ("A-next", "S1", "D1", 20242, 4, 2.6),
        ("B-return", "S1", "D2", 20251, 4, 3.5),
        ("other-first", "S2", "D1", 20232, 4, 1.4),
        ("other-next", "S2", "D1", 20241, 4, 1.8),
    ]
    return pd.DataFrame([
        make_status_row(
            student_status_id=status_id,
            student_id=student,
            degree_id=degree,
            part_id=part,
            semester_reg_courses=registered,
            gpa_points=gpa,
        )
        for status_id, student, degree, part, registered, gpa in reversed(records)
    ])


@pytest.mark.parametrize(
    "status_id, expected_gpa, expected_gap",
    [
        ("A-first", None, None),
        ("A-gap", 2.1, 1),
        ("B-first", None, None),
        ("B-enrolled", None, None),
        ("B-summer", 3.2, 0),
        ("A-return", 2.1, 3),
        ("A-next", 2.4, 0),
        ("B-return", 3.4, 2),
        ("other-first", None, None),
        ("other-next", 1.4, 0),
    ],
)
def test_history_is_independent_per_student_and_degree(
    degree_history_raw, status_id, expected_gpa, expected_gap
):
    result = status_module.clean_student_status(degree_history_raw).set_index(
        "student_status_id"
    )
    row = result.loc[status_id]
    assert (
        pd.isna(row.last_enrolled_gpa)
        if expected_gpa is None else row.last_enrolled_gpa == expected_gpa
    )
    assert (
        pd.isna(row.observed_gap_semesters)
        if expected_gap is None else row.observed_gap_semesters == expected_gap
    )


def test_missing_enrolled_gpa_is_filled_only_within_its_degree():
    raw = pd.DataFrame([
        make_status_row(student_status_id="1", degree_id="D1", part_id=20221, gpa_points=2.5),
        make_status_row(student_status_id="2", degree_id="D2", part_id=20222, gpa_points=None),
        make_status_row(student_status_id="3", degree_id="D1", part_id=20223, gpa_points=None),
        make_status_row(student_status_id="4", degree_id="D2", part_id=20231, gpa_points=3.0),
        make_status_row(student_status_id="5", degree_id="D1", part_id=20232, gpa_points=2.8),
    ])
    result = status_module.clean_student_status(raw).set_index("student_status_id")
    assert pd.isna(result.loc["4", "last_enrolled_gpa"])
    assert result.loc["4", "observed_gap_semesters"] == 0
    assert result.loc["5", "last_enrolled_gpa"] == 2.5
    assert result.loc["5", "observed_gap_semesters"] == 1


def test_initial_fallback_applies_independently_to_each_degree():
    # Defensive same-part case: retain both rows and the existing 20201 policy.
    raw = pd.DataFrame([
        make_status_row(student_status_id="1", degree_id="D1", part_id=20201,
                        prev_gpa_points=2.7, gpa_points=3.7),
        make_status_row(student_status_id="2", degree_id="D2", part_id=20201,
                        prev_gpa_points=1.6, gpa_points=3.9),
    ])
    result = status_module.clean_student_status(raw).set_index("degree_id")
    assert result.loc["D1", "last_enrolled_gpa"] == 2.7
    assert result.loc["D2", "last_enrolled_gpa"] == 1.6
    assert result.observed_gap_semesters.isna().all()


@pytest.mark.parametrize(
    "part, prior_courses, expected_gpa",
    [(20201, 0, None), (20201, 5, 2.7), (20211, 5, None)],
)
def test_degree_independence_preserves_initial_fallback_conditions(
    part, prior_courses, expected_gpa
):
    raw = pd.DataFrame([make_status_row(
        part_id=part, prev_gpa_points=2.7, gpa_points=3.9,
        total_reg_courses=prior_courses, total_reg_credits=0,
        start_total_in_courses=0, start_total_in_credits=0,
    )])
    row = status_module.clean_student_status(raw).iloc[0]
    assert pd.isna(row.last_enrolled_gpa) if expected_gpa is None else row.last_enrolled_gpa == expected_gpa
    assert pd.isna(row.observed_gap_semesters)


@pytest.mark.parametrize("cutoff", [20221, 20222, 20231, 20232, 20233, 20241, 20242])
def test_future_rows_cannot_change_historical_features(degree_history_raw, cutoff):
    full = status_module.clean_student_status(degree_history_raw)
    prefix = status_module.clean_student_status(
        degree_history_raw.loc[degree_history_raw.part_id.le(cutoff)]
    )
    assert_frame_equal(full.loc[full.part_id.le(cutoff)].reset_index(drop=True), prefix)


def test_current_results_cannot_replace_previous_enrollment_gpa(degree_history_raw):
    changed = degree_history_raw.copy(deep=True)
    current_and_future = changed.part_id.ge(20241)
    changed.loc[current_and_future, ["gpa_points", "prev_gpa_points", "end_agpa_points"]] = 4.0
    original = status_module.clean_student_status(degree_history_raw)
    result = status_module.clean_student_status(changed)
    historical = ["student_status_id", "last_enrolled_gpa", "observed_gap_semesters"]
    assert_frame_equal(
        result.loc[result.part_id.le(20241), historical].reset_index(drop=True),
        original.loc[original.part_id.le(20241), historical].reset_index(drop=True),
    )


def test_duplicate_student_part_retains_rows_and_existing_status_id_tie_order():
    # Characterize, do not deduplicate or invent an academic resolution policy.
    raw = pd.DataFrame([
        make_status_row(student_status_id="tie-2", part_id=20221, gpa_points=2.5),
        make_status_row(student_status_id="next", part_id=20222, gpa_points=3.5),
        make_status_row(student_status_id="tie-1", part_id=20221, gpa_points=1.5),
    ])
    result = status_module.clean_student_status(raw)
    assert result.student_status_id.tolist() == ["tie-1", "tie-2", "next"]
    assert pd.isna(result.loc[0, "last_enrolled_gpa"])
    assert result.loc[1:, "last_enrolled_gpa"].tolist() == [1.5, 2.5]
    assert result.loc[1:, "observed_gap_semesters"].tolist() == [0, 0]
    assert_frame_equal(result, status_module.clean_student_status(raw.iloc[::-1]))


@pytest.mark.parametrize("relocated", [False, True], ids=["different-cwd", "relocated-project"])
def test_canonical_paths_work_independently_of_location(tmp_path, relocated):
    project = Path(__file__).resolve().parents[2]
    source = project / "src" / "paths.py"
    if relocated:
        project = tmp_path / "copied project"
        source_copy = project / "src" / "paths.py"
        source_copy.parent.mkdir(parents=True)
        shutil.copyfile(source, source_copy)
        source = source_copy
    working_dir = tmp_path / "unrelated working directory"
    working_dir.mkdir()
    probe = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('portable_paths', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps({name: str(value) for name, value in vars(module).items()
                  if isinstance(value, Path)}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(source)],
        cwd=working_dir, check=True, capture_output=True, text=True,
    )
    actual = {name: Path(value) for name, value in json.loads(completed.stdout).items()}
    expected = {
        "PROJECT_ROOT": ".",
        "DATA_DIR": "data", "RAW_DIR": "data/raw", "CLEAN_DIR": "data/clean",
        "MERGED_DIR": "data/merged",
        'PLAN_GPA_COURSE_PREDICTIONS_PATH': 'data/evaluation/plan_gpa_course_predictions_2025.parquet',
        'PLAN_GPA_EVALUATION_PATH': 'data/evaluation/plan_gpa_evaluation_2025.parquet',
        'PLAN_GPA_METRICS_PATH': 'data/evaluation/plan_gpa_metrics_2025.json',
        'GRADE_SCALE_PATH': 'data/raw/v_acs_grade.parquet',
        'SHORTLIST_MODEL_DIR': 'models/shortlist',
        'SHORTLIST_GRADE_MODEL_PATH': 'models/shortlist/grade_model.txt',
        'SHORTLIST_FAIL_MODEL_PATH': 'models/shortlist/fail_model.txt',
        'SHORTLIST_CATEGORY_LEVELS_PATH': 'models/shortlist/category_levels.json',
        'TWO_STAGE_MANIFEST_PATH': 'models/shortlist/manifest.json',
        'FROZEN_HISTORY_INCREMENTAL_DIR': 'data/artifacts/history_incremental',
        'MODEL_DIR': 'models',
        'EVALUATION_DIR': 'data/evaluation',
        'CATEGORY_LEVELS_PATH': 'data/artifacts/category_levels.json',
        'GRADE_MODEL_PATH': 'models/grade_regressor.txt',
        'FAIL_MODEL_PATH': 'models/fail_risk_classifier.txt',
        'MODEL_METADATA_PATH': 'models/model_metadata.json',
        'COURSE_ONLY_MODEL_DIR': 'models/shortlist_training',
        'COURSE_ONLY_EVALUATION_DIR': 'data/evaluation/shortlist',
        "FROZEN_HISTORY_DIR": "data/artifacts/history",
        'FEATURE_DIR': 'data/features',
        'ARTIFACT_DIR': 'data/artifacts',
        'TEMPORAL_TRAIN_FEATURES_PATH': 'data/features/temporal_train_features.parquet',
        'TEMPORAL_TEST_FEATURES_PATH': 'data/features/temporal_test_features.parquet',
        'COURSE_HISTORY_STATE_PATH': 'data/artifacts/course_history_state.pkl',
        "TEMPORAL_DIR": "data/temporal",
        "STUDENT_COURSE_PATH": "data/raw/v_crg_student_course_raw.parquet",
        "STUDENT_STATUS_PATH": "data/raw/v_add_student_degree_status.parquet",
        "DEGREE_COURSE_PATH": "data/raw/v_acd_degree_course.parquet",
        "ACADEMIC_INFO_PATH": "data/raw/v_add_academic_info.parquet",
        "PRE_COMMON_STUDENT_COURSE_PATH": "data/clean/student_course_pre_common.parquet",
        "PRE_COMMON_STUDENT_STATUS_PATH": "data/clean/student_status_pre_common.parquet",
        "CLEAN_DEGREE_COURSE_PATH": "data/clean/degree_course.parquet",
        "CLEAN_STUDENT_DIPLOMA_PATH": "data/clean/student_diploma.parquet",
        "STUDENT_COURSE_ENRICHED_PATH": "data/clean/student_course_enriched.parquet",
        "STUDENT_COURSE_DIPLOMA_PATH": "data/merged/student_course_enriched_with_diploma.parquet",
        "STUDENT_COURSE_WITHOUT_OUTLIERS_PATH": "data/merged/student_course_enriched_without_outliers.parquet",
        "OUTLIER_STUDENTS_AUDIT_PATH": "data/merged/outlier_students.parquet",
        "CLEAN_STUDENT_COURSE_PATH": "data/clean/student_course.parquet",
        "CLEAN_STUDENT_STATUS_PATH": "data/clean/student_status.parquet",
        "TEMPORAL_TRAIN_PATH": "data/temporal/temporal_train.parquet",
        "TEMPORAL_TEST_PATH": "data/temporal/temporal_test.parquet",
        "CLEAN_REGISTRATION_ROSTER_PATH": "data/clean/registration_roster.parquet",
        "TEMPORAL_TRAIN_ROSTER_PATH": "data/temporal/temporal_train_roster.parquet",
        "TEMPORAL_TEST_ROSTER_PATH": "data/temporal/temporal_test_roster.parquet",
    }
    assert actual == {name: project / relative for name, relative in expected.items()}
    if relocated:
        assert not (project / "data").exists()
