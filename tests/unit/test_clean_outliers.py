from pathlib import Path
import sys

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.data.cleaning.clean_outliers as outlier_module  # noqa: E402


def make_valid_outlier_row(**overrides):
    row = {
        "student_id": "S1",
        "student_status_id": "ST1",
        "observed_gap_semesters": 0,
        "semester_reg_courses": 4,
        "semester_reg_credits": 12.0,
        "semester_pass_courses": 3,
        "semester_pass_credits": 9.0,
        "semester_fail_courses": 1,
        "semester_fail_credits": 3.0,
        "total_semesters": 4,
        "total_reg_courses": 16,
        "total_reg_credits": 48.0,
        "total_pass_courses": 12,
        "total_pass_credits": 36.0,
        "total_fail_courses": 4,
        "total_fail_credits": 12.0,
        "reg_total_semesters": 4,
        "start_total_in_courses": 12,
        "start_total_in_credits": 36.0,
        "end_total_in_courses": 16,
        "end_total_in_credits": 48.0,
        "degree_credits_count": 132.0,
        "prev_gpa_points": 2.5,
        "last_enrolled_gpa": 2.5,
        "gpa_points": 3.0,
        "start_agpa_points": 2.5,
        "end_agpa_points": 3.0,
        "final_mark": 70.0,
        "points": 2.5,
        "course_credits": 3.0,
        "attempt_number": 1,
    }
    row.update(overrides)
    return row


@pytest.fixture
def valid_frame():
    return pd.DataFrame([make_valid_outlier_row()])


def test_validate_columns_names_every_missing_requirement(valid_frame):
    with pytest.raises(KeyError, match="missing_a.*missing_b|missing_b.*missing_a"):  # NOTE: the audit must fail loudly when source features are absent.
        outlier_module._validate_columns(
            valid_frame,
            [*valid_frame.columns, "missing_a", "missing_b"],
        )


def test_summarize_rule_aggregates_repeated_triggers_per_student():
    frame = pd.DataFrame({"student_id": ["S1", "S1", "S2"]})
    observed = pd.Series([-1.0, -2.0, 5.0])
    mask = pd.Series([True, True, pd.NA], dtype="boolean")

    result = outlier_module._summarize_rule(
        frame,
        mask,
        observed,
        scope="course",
        rule="value_below_zero",
        expected=">= 0",
    )

    assert result["student_id"].tolist() == ["S1"]  # NOTE: null masks are non-violations and students are summarized once per rule.
    assert result.loc[0, "trigger_count"] == 2  # NOTE: repeated bad course records must remain countable in the audit.
    assert result.loc[0, "min_observed"] == -2.0  # NOTE: the audit must retain the most extreme low observation.
    assert result.loc[0, "max_observed"] == -1.0  # NOTE: the audit must retain the observed range, not only a flag.


@pytest.mark.parametrize(
    "column, invalid_value, expected_rule",
    [
        ("observed_gap_semesters", 3, "observed_gap_semesters_above_limit"),
        ("semester_reg_courses", 11, "semester_reg_courses_above_limit"),
        ("semester_reg_credits", 40, "semester_reg_credits_above_limit"),
        ("semester_pass_courses", 11, "semester_pass_courses_above_limit"),
        ("semester_pass_credits", 28, "semester_pass_credits_above_limit"),
        ("semester_fail_courses", 7, "semester_fail_courses_above_limit"),
        ("semester_fail_credits", 25, "semester_fail_credits_above_limit"),
        ("total_semesters", 39, "total_semesters_above_limit"),
        ("total_reg_courses", 177, "total_reg_courses_above_limit"),
        ("total_reg_credits", 574, "total_reg_credits_above_limit"),
        ("total_pass_courses", 88, "total_pass_courses_above_limit"),
        ("total_pass_credits", 276, "total_pass_credits_above_limit"),
        ("total_fail_courses", 97, "total_fail_courses_above_limit"),
        ("total_fail_credits", 341, "total_fail_credits_above_limit"),
        ("reg_total_semesters", 37, "reg_total_semesters_above_limit"),
    ],
)
def test_build_outlier_audit_applies_each_status_upper_limit(
    valid_frame,
    column,
    invalid_value,
    expected_rule,
):
    changed = valid_frame.assign(**{column: invalid_value})

    audit = outlier_module.build_outlier_audit(changed)
    matched = audit.loc[audit["rule"].eq(expected_rule)]

    assert len(matched) == 1  # NOTE: every configured status ceiling must emit its named audit rule.
    assert matched.iloc[0]["scope"] == "semester_status"  # NOTE: repeated status features must be distinguishable from course-level faults.


@pytest.mark.parametrize(
    "column",
    [
        "start_total_in_courses",
        "start_total_in_credits",
        "end_total_in_courses",
        "end_total_in_credits",
        "degree_credits_count",
        "observed_gap_semesters",
        "semester_reg_courses",
        "semester_reg_credits",
        "semester_pass_courses",
        "semester_pass_credits",
        "semester_fail_courses",
        "semester_fail_credits",
        "total_semesters",
        "total_reg_courses",
        "total_reg_credits",
        "total_pass_courses",
        "total_pass_credits",
        "total_fail_courses",
        "total_fail_credits",
        "reg_total_semesters",
    ],
)
def test_build_outlier_audit_rejects_negative_status_totals(valid_frame, column):
    audit = outlier_module.build_outlier_audit(valid_frame.assign(**{column: -1}))

    assert f"{column}_below_zero" in audit["rule"].tolist()  # NOTE: negative workload and cumulative totals are invalid even below upper limits.


@pytest.mark.parametrize(
    "column, invalid_value",
    [
        ("prev_gpa_points", -0.1),
        ("prev_gpa_points", 4.1),
        ("last_enrolled_gpa", -0.1),
        ("last_enrolled_gpa", 4.1),
        ("gpa_points", -0.1),
        ("gpa_points", 4.1),
        ("start_agpa_points", -0.1),
        ("start_agpa_points", 4.1),
        ("end_agpa_points", -0.1),
        ("end_agpa_points", 4.1),
    ],
)
def test_build_outlier_audit_checks_both_gpa_boundaries(
    valid_frame,
    column,
    invalid_value,
):
    audit = outlier_module.build_outlier_audit(
        valid_frame.assign(**{column: invalid_value})
    )

    assert f"{column}_outside_gpa_range" in audit["rule"].tolist()  # NOTE: all GPA sources share the official zero-to-four scale.


@pytest.mark.parametrize(
    "column, invalid_value, expected_rule",
    [
        ("final_mark", -1, "final_mark_outside_range"),
        ("final_mark", 101, "final_mark_outside_range"),
        ("points", -0.1, "points_outside_range"),
        ("points", 4.1, "points_outside_range"),
        ("attempt_number", 0, "attempt_number_outside_range"),
        ("attempt_number", 6, "attempt_number_outside_range"),
        ("course_credits", -1, "course_credits_below_zero"),
    ],
)
def test_build_outlier_audit_checks_course_level_ranges(
    valid_frame,
    column,
    invalid_value,
    expected_rule,
):
    audit = outlier_module.build_outlier_audit(
        valid_frame.assign(**{column: invalid_value})
    )

    assert expected_rule in audit["rule"].tolist()  # NOTE: invalid course outcomes must be audited at course grain.


@pytest.mark.parametrize(
    "changes, expected_rule",
    [
        (
            {"semester_pass_courses": 4, "semester_fail_courses": 1},
            "semester_course_totals_exceed_registered",
        ),
        (
            {"semester_pass_credits": 10, "semester_fail_credits": 3},
            "semester_credit_totals_exceed_registered",
        ),
        (
            {"total_pass_courses": 13, "total_fail_courses": 4},
            "total_course_totals_exceed_registered",
        ),
        (
            {"total_pass_credits": 37, "total_fail_credits": 12},
            "total_credit_totals_exceed_registered",
        ),
        (
            {"reg_total_semesters": 5},
            "registered_semesters_exceed_total_semesters",
        ),
        (
            {"end_total_in_courses": 11},
            "end_courses_below_start_courses",
        ),
        (
            {"end_total_in_credits": 35},
            "end_credits_below_start_credits",
        ),
    ],
)
def test_build_outlier_audit_checks_logical_consistency(
    valid_frame,
    changes,
    expected_rule,
):
    audit = outlier_module.build_outlier_audit(valid_frame.assign(**changes))
    matched = audit.loc[audit["rule"].eq(expected_rule)]

    assert len(matched) == 1  # NOTE: impossible cumulative relationships must not pass range checks alone.
    assert matched.iloc[0]["scope"] == "logical_consistency"  # NOTE: logical defects need a separate remediation category.
    assert matched.iloc[0]["max_observed"] == 1  # NOTE: the audit records the amount by which the relationship was violated.


def test_build_outlier_audit_checks_status_once_but_courses_per_record(valid_frame):
    repeated = pd.concat([valid_frame, valid_frame], ignore_index=True)
    repeated["semester_reg_courses"] = 11
    repeated["final_mark"] = 101

    audit = outlier_module.build_outlier_audit(repeated)
    status_rule = audit.loc[audit["rule"].eq("semester_reg_courses_above_limit")].iloc[0]
    course_rule = audit.loc[audit["rule"].eq("final_mark_outside_range")].iloc[0]

    assert status_rule["trigger_count"] == 1  # NOTE: status values repeat on each course and must not inflate the semester audit.
    assert course_rule["trigger_count"] == 2  # NOTE: course faults remain one trigger per affected course row.


def test_build_outlier_audit_accepts_valid_24_credit_course(valid_frame):
    audit = outlier_module.build_outlier_audit(
        valid_frame.assign(course_credits=24.0)
    )

    assert audit.empty  # NOTE: a known 24-credit course proves that no generic positive upper cap is valid.
    assert audit.columns.tolist() == outlier_module.AUDIT_COLUMNS  # NOTE: even an empty audit must keep the persisted schema.


def test_remove_outlier_students_removes_every_row_for_flagged_students():
    frame = pd.DataFrame(
        {"student_id": ["S1", "S1", "S2"], "student_course_id": [1, 2, 3]}
    )
    audit = pd.DataFrame({"student_id": ["S1", "S1"], "rule": ["a", "b"]})

    result = outlier_module.remove_outlier_students(frame, audit)

    assert result["student_id"].tolist() == ["S2"]  # NOTE: one violation excludes the student's complete modeling history.
    assert result.index.tolist() == [0]  # NOTE: downstream parquet output should receive a clean consecutive index.


def test_main_writes_clean_rows_and_outlier_audit(tmp_path, monkeypatch):
    frame = pd.DataFrame(
        [
            make_valid_outlier_row(),
            make_valid_outlier_row(
                student_id="S2",
                student_status_id="ST2",
                final_mark=101,
            ),
        ]
    )
    input_path = tmp_path / "course_diploma.parquet"
    clean_path = tmp_path / "merged" / "without_outliers.parquet"
    audit_path = tmp_path / "merged" / "outliers.parquet"
    frame.to_parquet(input_path, index=False)
    monkeypatch.setattr(outlier_module, "STUDENT_COURSE_DIPLOMA_PATH", input_path)
    monkeypatch.setattr(outlier_module, "STUDENT_COURSE_WITHOUT_OUTLIERS_PATH", clean_path)
    monkeypatch.setattr(outlier_module, "OUTLIER_STUDENTS_AUDIT_PATH", audit_path)

    outlier_module.main()

    clean = pd.read_parquet(clean_path)
    audit = pd.read_parquet(audit_path)
    assert clean["student_id"].tolist() == ["S1"]  # NOTE: main must remove every row belonging to an audited student.
    assert audit["student_id"].unique().tolist() == ["S2"]  # NOTE: the removed population must remain recoverable in a separate audit artifact.
    assert "final_mark_outside_range" in audit["rule"].tolist()  # NOTE: the persisted audit must explain the exact removal reason.
