from pathlib import Path
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.data.cleaning.clean_degree_course as degree_course_module  # noqa: E402


@pytest.fixture
def raw_degree_courses():
    return pd.DataFrame(
        {
            "Degree Course ID": ["2.0", "1.0"],
            "Course ID": ["C2", "C1"],
            "Degree ID": ["D1", "D1"],
            "Course Type ID": ["20.0", "10.0"],
            "Requirement Type ID": ["2", "1"],
            "Requirement Type SL": [" Optional ", " Core  "],
            "Course Name SL": [" Course B ", " Course A "],
            "Course Official SL": [" B ", " A "],
            "Degree Name SL": [" Degree ", " Degree "],
            "Year Order": ["2", "1"],
            "Semester Order": ["1", "2"],
            "Course Credits": ["3.5", "3"],
            "Credits Count": ["3.5", "3"],
            "Active": [" Y ", " N "],
            "Ignored": [1, 2],
        }
    )


def test_clean_degree_course_normalizes_contract_and_stable_order(raw_degree_courses):
    result = degree_course_module.clean_degree_course(raw_degree_courses)

    assert result.columns.tolist() == degree_course_module.FINAL_COLUMNS  # NOTE: enrichment consumes a fixed plan-column contract.
    assert result["course_id"].tolist() == ["C1", "C2"]  # NOTE: deterministic degree/year/semester ordering keeps artifacts reproducible.
    assert result["degree_course_id"].tolist() == ["1", "2"]  # NOTE: numeric-looking IDs must not retain the source '.0' suffix.
    assert result["requirement_type_sl"].tolist() == ["Core", "Optional"]  # NOTE: category whitespace would create false model levels.
    assert result["course_credits"].tolist() == [3.0, 3.5]  # NOTE: credits must be numeric before plan calculations.
    assert str(result["year_order"].dtype) == "Int64"  # NOTE: nullable integers preserve missing plan positions without floats.


@pytest.mark.parametrize(
    "missing_column",
    ["Degree ID", "Course ID", "Requirement Type ID", "Course Credits"],
)
def test_clean_degree_course_rejects_missing_required_columns(
    raw_degree_courses,
    missing_column,
):
    with pytest.raises(KeyError):  # NOTE: a partial curriculum row must fail instead of silently producing incomplete plan features.
        degree_course_module.clean_degree_course(
            raw_degree_courses.drop(columns=missing_column)
        )


def test_main_writes_the_clean_degree_course_artifact(
    tmp_path,
    monkeypatch,
    raw_degree_courses,
):
    raw_path = tmp_path / "degree_course_raw.parquet"
    output_path = tmp_path / "clean" / "degree_course.parquet"
    raw_degree_courses.to_parquet(raw_path, index=False)
    monkeypatch.setattr(degree_course_module, "DEGREE_COURSE_PATH", raw_path)
    monkeypatch.setattr(degree_course_module, "CLEAN_DEGREE_COURSE_PATH", output_path)

    degree_course_module.main()

    expected = degree_course_module.clean_degree_course(raw_degree_courses)
    assert output_path.exists()  # NOTE: main must create the clean directory and final plan artifact.
    assert_frame_equal(
        pd.read_parquet(output_path),
        expected,
        check_column_type=False,
    )  # NOTE: compare persisted values/dtypes while ignoring Parquet's non-semantic column-index dtype.
