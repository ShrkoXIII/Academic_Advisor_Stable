"""HTTP contract coverage with generated identities and synthetic two-stage models."""
from copy import deepcopy

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.service import ApiService
from src.api.settings import ApiSettings
from src.grade_scale import GradeScale
from src.recommendation.two_stage_engine import TwoStagePlanRecommender
from tests.synthetic_api import sample_catalog, sample_request
from tests.unit.test_two_stage_activation import approve_manifest
from tests.unit.two_stage_fixtures import history_manager, synthetic_artifacts


@pytest.fixture
def api_client(tmp_path):
    request = sample_request()
    scale = GradeScale(pd.DataFrame({"grade_version_id": [3.111] * 3,
        "from_percent": [50, 60, 80], "points": [1, 2, 4], "grade_show": ["D", "C", "A"]}))
    assets = synthetic_artifacts()
    assets = type(assets)(assets.stage1, assets.stage2, scale, assets.manifest)
    approve_manifest(assets.manifest)
    engine = TwoStagePlanRecommender.from_loaded_artifacts(assets, history_manager(tmp_path / "history"))
    settings = ApiSettings(service_key="synthetic-service", admin_key="synthetic-admin",
        request_store_path=tmp_path / "requests.sqlite3",
        incremental_history_root=tmp_path / "updates")
    api = ApiService(engine=engine, catalog=sample_catalog(request), grade_scale=scale, settings=settings)
    with TestClient(create_app(service=api)) as client:
        yield client, engine, request


def post(client, request, path="/api/v1/recommendations"):
    return client.post(path, json=request, headers={"X-API-Key": "synthetic-service"})


def test_http_recommendation_runs_both_stages_and_alias(api_client):
    client, engine, request = api_client
    assert client.get("/health").json()["recommendation_readiness"]["ready"]
    result = post(client, request)
    assert result.status_code == 200, result.json()
    body = result.json()
    assert body["status"] == "ok" and len(body["recommendations"]) == 3
    assert engine.artifacts.stage1.grade_model.matrices[-1].shape[1] == 33
    assert engine.artifacts.stage2.grade_model.matrices[-1].shape[1] == 47
    assert post(client, request, "/recommend").json() == body


@pytest.mark.parametrize("component", ["student", "courses"])
def test_identity_conflict_is_rejected_before_model_execution(api_client, component):
    client, engine, request = api_client
    request["source_contexts"][component]["student_id"] = "conflicting-synthetic-id"
    assert post(client, request).status_code == 422
    assert engine.artifacts.stage1.grade_model.matrices == []


@pytest.mark.parametrize("field", ["START_AGPA_POINTS", "diploma_gpa", "GRADE_VERSION_ID"])
def test_missing_student_fields_never_become_guessed_inputs(api_client, field):
    client, engine, request = api_client
    del request["student_api_response"]["data"]["studentDegreeInfo"][field]
    assert post(client, request).status_code == 422
    assert engine.artifacts.stage1.grade_model.matrices == []


def test_target_outcomes_cannot_enter_student_history(api_client):
    client, _, request = api_client
    row = deepcopy(request["student_api_response"]["data"]["studentSummaryInfo"][-1])
    row.update(PART_ID="20251", STUDENT_STATUS_ID="synthetic-target-outcome", GPA_POINTS="4")
    request["student_api_response"]["data"]["studentSummaryInfo"].append(row)
    assert post(client, request).status_code == 422


def test_no_exact_credit_plan_has_explicit_empty_result(api_client):
    client, _, request = api_client
    request["target_credits"] = 4
    response = post(client, request)
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "no_feasible_plan"
    assert response.json()["recommendations"] == []


def test_authentication_is_required(api_client):
    client, engine, request = api_client
    assert client.post("/recommend", json=request).status_code == 401
    assert engine.artifacts.stage1.grade_model.matrices == []


@pytest.mark.parametrize("first", ["student", "courses"])
def test_split_inputs_wait_then_return_the_same_owned_result(api_client, first):
    client, _, request = api_client
    common = {key: request[key] for key in
              ("student_id", "degree_id", "part_id", "source_contexts", "integration_context")}
    student = {**common, "request_id": "synthetic-split", "student_api_response": request["student_api_response"],
               "recommendation": {key: request[key] for key in
                                  ("history_as_of_part", "target_credits", "top_k", "mode")}}
    courses = {**common, "request_id": "synthetic-split", "courses_api_response": request["courses_api_response"]}
    payloads = {"student": student, "courses": courses}
    second = "courses" if first == "student" else "student"
    assert post(client, payloads[first], "/api/v1/recommendation-inputs/" + first).status_code == 202
    response = post(client, payloads[second], "/api/v1/recommendation-inputs/" + second)
    assert response.status_code == 200, response.json()
    assert len(response.json()["recommendations"]) == 3
    lookup = client.get("/api/v1/recommendation-requests/synthetic-split",
                        headers={"X-API-Key": "synthetic-service"})
    assert lookup.status_code == 200 and lookup.json()["result"] == response.json()
