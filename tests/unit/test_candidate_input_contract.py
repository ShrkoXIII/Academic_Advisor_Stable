from src.recommendation.inputs import normalize_candidate_payloads


def test_candidate_payload_does_not_require_plan_course_type_id():
    snapshot = {"student_id": "S1", "degree_id": "D1", "part_id": 20251}
    candidate = {
        "course_id": "C1",
        "course_name": "Synthetic course",
        "course_credits": 3,
        "attempt_number": 1,
        "plan_requirement_type_id": "R1",
        "plan_year_order": 1,
        "plan_semester_order": 1,
        "plan_credits_count": 120,
        "previous_course_status": "NEW",
    }

    result = normalize_candidate_payloads([candidate], snapshot)

    assert result.loc[0, "course_id"] == "C1"
    assert "plan_course_type_id" not in result.columns

