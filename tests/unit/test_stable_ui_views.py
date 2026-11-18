from copy import deepcopy

import pytest
import pandas as pd

from tools.academic_advisor_streamlit.views import combine_request, comparison_rows, registered_courses
from src import paths
from src.evaluation.local_course_inputs import normalize_registered_courses
from tests.synthetic_api import sample_request


def test_live_inputs_use_the_same_combined_api_contract():
    source = sample_request()
    result = combine_request(source["student_id"], source["degree_id"], source["part_id"],
        source["history_as_of_part"], source["target_credits"], source["student_api_response"],
        source["courses_api_response"], source["integration_context"], {})
    for key in ("student_id", "degree_id", "part_id", "student_api_response", "courses_api_response"):
        assert result[key] == source[key]
    assert result["top_k"] == 3


def test_conflicting_context_is_not_silently_overwritten():
    source = sample_request()
    with pytest.raises(ValueError):
        combine_request(source["student_id"], source["degree_id"], 20251, 20243, 3,
            source["student_api_response"], source["courses_api_response"],
            {"student_values": {"x": 1}}, {"student_values": {"x": 2}})


def test_unobserved_alternative_gpas_stay_unavailable():
    result = {"recommendations": [{"rank": 1, "total_credits": 3,
        "expected_plan_gpa": 3.2, "projected_cumulative_gpa": 2.9}]}
    rows = comparison_rows(result, None)
    assert rows[0]["actual_semester_gpa"] is None
    assert rows[0]["actual_cumulative_gpa"] is None


def test_local_registration_lookup_uses_canonical_identity_and_prior_attempts(tmp_path, monkeypatch):
    tables = {
        "CLEAN_REGISTRATION_ROSTER_PATH": pd.DataFrame({"student_id": ["S"], "degree_id": ["D"],
            "part_id": [20251], "course_id": ["C"], "course_credits": [3.0]}),
        "CLEAN_DEGREE_COURSE_PATH": pd.DataFrame({"degree_id": ["D"], "course_id": ["C"],
            "course_credits": [3.0], "course_name_sl": ["Synthetic"], "course_type_id": ["3"],
            "requirement_type_id": ["R"], "year_order": [1], "semester_order": [1], "credits_count": [12.0]}),
        "CLEAN_STUDENT_COURSE_PATH": pd.DataFrame({"student_id": ["S", "S"], "course_id": ["C", "C"],
            "part_id": [20243, 20251], "attempt_number": [1, 99]}),
    }
    for name, frame in tables.items():
        target = tmp_path / (name + ".parquet")
        frame.to_parquet(target)
        monkeypatch.setattr(paths, name, target)
    result = registered_courses({"student_id": " S ", "degree_id": " D ", "part_id": "20251"})
    assert len(result) == 1
    assert result[0]["course_id"] == "C" and result[0]["attempt_number"] == 2


def test_local_course_normalizer_ignores_target_and_future_attempts_with_canonical_ids():
    raw = pd.DataFrame({"course_id": [" 12.0 "], "course_credits": [3.0]})
    catalog = pd.DataFrame({"degree_id": [" D "], "course_id": ["12"],
        "course_credits": [3.0], "course_name_sl": ["Synthetic"],
        "requirement_type_id": ["R"], "year_order": [1], "semester_order": [1],
        "credits_count": [12.0]})
    history = pd.DataFrame({"student_id": ["S", " S ", "S"], "course_id": [12, "12.0", "12"],
        "part_id": [20243, 20251, 20252], "attempt_number": [2, 99, 100]})

    normalized, report = normalize_registered_courses(raw, catalog, history, " S ", "D", 20251)

    assert normalized.loc[0, "course_id"] == "12"
    assert normalized.loc[0, "attempt_number"] == 3
    assert report["history_latest_part"] == 20243


@pytest.mark.parametrize("raw,catalog", [
    (pd.DataFrame({"course_id": ["missing"], "course_credits": [3.0]}),
     pd.DataFrame({"degree_id": ["D"], "course_id": ["C"], "course_credits": [3.0],
                   "course_name_sl": ["Synthetic"], "requirement_type_id": ["R"],
                   "year_order": [1], "semester_order": [1], "credits_count": [12.0]})),
    (pd.DataFrame({"course_id": ["C"], "course_credits": [4.0]}),
     pd.DataFrame({"degree_id": ["D"], "course_id": ["C"], "course_credits": [3.0],
                   "course_name_sl": ["Synthetic"], "requirement_type_id": ["R"],
                   "year_order": [1], "semester_order": [1], "credits_count": [12.0]})),
])
def test_local_course_normalizer_preserves_catalog_rejections(raw, catalog):
    history = pd.DataFrame(columns=["student_id", "course_id", "part_id", "attempt_number"])
    with pytest.raises(ValueError):
        normalize_registered_courses(raw, catalog, history, "S", "D", 20251)
