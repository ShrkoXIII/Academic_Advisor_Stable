from tests.synthetic_api import sample_catalog, sample_request


def test_release_example_binds_to_the_supplied_catalog_without_using_a_real_student():
    from tools.verify_release import build_example
    catalog = sample_catalog(sample_request()).assign(degree_id="catalog-degree")
    request, registration = build_example(catalog)
    assert request["student_id"] == "release-synthetic-student"
    assert request["degree_id"] == "catalog-degree"
    assert request["target_credits"] == 6
    assert request["source_contexts"]["student"]["degree_id"] == "catalog-degree"
    assert request["student_api_response"]["data"]["studentDegreeInfo"]["DEGREE_ID"] == "catalog-degree"
    assert {r["COURSE_ID"] for r in request["courses_api_response"]["data"]["availableCourses"]} == {
        "synthetic-course-0", "synthetic-course-1", "synthetic-course-2", "synthetic-course-3"}
    assert len(registration["courses"]) == 2
    assert registration["source"] == "synthetic-release-registration-not-university-evidence"
