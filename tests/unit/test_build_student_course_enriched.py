from pathlib import Path
import sys

import pandas as pd
import pytest
from pandas.errors import MergeError


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.data.building.build_student_course_enriched as enriched_module  # noqa: E402


@pytest.fixture
def enrichment_inputs():
    courses = pd.DataFrame(
        {
            "student_course_id": ["SC1", "SC2", "SC3"],
            "student_id": ["S1", "S2", "S3"],
            "degree_id": ["D1", "D1", "D1"],
            "part_id": [20241, 20241, 20241],
            "course_id": ["C1", "C2", "C3"],
            "finish_status": ["passed", "failed", "passed"],
        }
    )
    status = pd.DataFrame(
        {
            "student_status_id": ["ST1", "ST2"],
            "student_id": ["S1", "S2"],
            "degree_id": ["D1", "D1"],
            "part_id": [20241, 20241],
            "finish_status": ["active", "active"],
            "gpa_points": [3.0, 2.0],
        }
    )
    degree_courses = pd.DataFrame(
        {
            "degree_id": ["D1"],
            "course_id": ["C1"],
            "course_name_sl": ["Course One"],
            "year_order": [1],
        }
    )
    return courses, status, degree_courses


def write_enrichment_inputs(tmp_path, monkeypatch, inputs):
    courses, status, degree_courses = inputs
    course_path = tmp_path / "courses.parquet"
    status_path = tmp_path / "status.parquet"
    plan_path = tmp_path / "degree_courses.parquet"
    output_path = tmp_path / "clean" / "enriched.parquet"
    courses.to_parquet(course_path, index=False)
    status.to_parquet(status_path, index=False)
    degree_courses.to_parquet(plan_path, index=False)
    monkeypatch.setattr(enriched_module, "CLEAN_STUDENT_COURSE_PATH", course_path)
    monkeypatch.setattr(enriched_module, "CLEAN_STUDENT_STATUS_PATH", status_path)
    monkeypatch.setattr(enriched_module, "CLEAN_DEGREE_COURSE_PATH", plan_path)
    monkeypatch.setattr(enriched_module, "STUDENT_COURSE_ENRICHED_PATH", output_path)
    return output_path


def test_main_builds_status_inner_join_and_auditable_plan_left_join(
    tmp_path,
    monkeypatch,
    enrichment_inputs,
):
    output_path = write_enrichment_inputs(
        tmp_path,
        monkeypatch,
        enrichment_inputs,
    )

    enriched_module.main()

    result = pd.read_parquet(output_path)
    assert result["student_course_id"].tolist() == ["SC1", "SC2"]  # NOTE: courses without the exact student-degree-semester status are outside the model population.
    assert result["plan_match"].tolist() == [True, False]  # NOTE: unmatched curriculum rows must be flagged, not dropped.
    assert result["plan_match"].dtype == bool  # NOTE: downstream features need a real boolean rather than pandas merge labels.
    assert result.loc[result["course_id"].eq("C1"), "plan_course_name_sl"].item() == "Course One"  # NOTE: curriculum metadata must be namespaced to preserve provenance.
    assert pd.isna(result.loc[result["course_id"].eq("C2"), "plan_course_name_sl"]).all()  # NOTE: a left join keeps unmatched courses explicitly missing.
    assert {"finish_status_course", "finish_status_status"}.issubset(result.columns)  # NOTE: overlapping course and status fields must not overwrite each other.


@pytest.mark.parametrize("duplicate_source", ["status", "plan"])
def test_main_rejects_many_to_many_enrichment_sources(
    tmp_path,
    monkeypatch,
    enrichment_inputs,
    duplicate_source,
):
    courses, status, degree_courses = enrichment_inputs
    if duplicate_source == "status":
        status = pd.concat([status, status.iloc[[0]]], ignore_index=True)
    else:
        degree_courses = pd.concat(
            [degree_courses, degree_courses.iloc[[0]]],
            ignore_index=True,
        )
    write_enrichment_inputs(
        tmp_path,
        monkeypatch,
        (courses, status, degree_courses),
    )

    with pytest.raises(MergeError, match="many-to-one"):  # NOTE: duplicate lookup keys would silently multiply course observations.
        enriched_module.main()
