"""HTTP contract coverage with generated identities and synthetic two-stage models."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.service import ApiService
from src.api.settings import ApiSettings
from src.grade_scale import GradeScale
from src.recommendation.cumulative_history import CumulativeHistoryStore
from src.recommendation.two_stage_engine import TwoStagePlanRecommender
from tests.synthetic_api import sample_catalog, sample_request
from tests.unit.test_cumulative_history import payload as history_delta, source as cumulative_source
from tests.unit.test_two_stage_activation import approve_manifest
from tests.unit.two_stage_fixtures import history_manager, synthetic_artifacts


HISTORY_ADMIN = "/api/v1/admin/history"
ADMIN_HEADERS = {"X-API-Key": "synthetic-admin"}
FINALIZATION_HEADERS = {"X-API-Key": "synthetic-finalization"}


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
        finalization_key="synthetic-finalization", history_baseline_source_root=tmp_path / "baseline",
        request_store_path=tmp_path / "requests.sqlite3",
        incremental_history_root=tmp_path / "updates")
    api = ApiService(engine=engine, catalog=sample_catalog(request), grade_scale=scale, settings=settings)
    with TestClient(create_app(service=api)) as client:
        yield client, engine, request


def post(client, request, path="/api/v1/recommendations"):
    return client.post(path, json=request, headers={"X-API-Key": "synthetic-service"})


def split_inputs(request):
    common = {key: request[key] for key in ("student_id", "degree_id", "part_id")}
    common["request_id"] = "synthetic-split"
    integration = request["integration_context"]
    context_fields = {
        "student": ("student_values", "total_reg_credits_source"),
        "courses": ("registration_policy", "previous_course_statuses"),
    }
    payloads = {}
    for component, fields in context_fields.items():
        payloads[component] = {
            **common,
            f"{component}_api_response": request[f"{component}_api_response"],
            "source_contexts": {component: request["source_contexts"][component]},
            "integration_context": {key: integration[key] for key in fields if key in integration},
        }
    option_fields = ("history_as_of_part", "target_credits", "min_credits", "max_credits", "top_k", "mode")
    payloads["student"]["recommendation"] = {key: request[key] for key in option_fields if key in request}
    return payloads


def test_http_recommendation_runs_both_stages_and_alias(api_client):
    client, engine, request = api_client
    assert client.get("/health").json()["recommendation_readiness"]["ready"]
    result = post(client, request)
    assert result.status_code == 200, result.json()
    body = result.json()
    assert body["status"] == "ok" and len(body["recommendations"]) == 3
    assert engine.artifacts.stage1.grade_model.matrices[-1].shape[1] == 31
    assert engine.artifacts.stage2.grade_model.matrices[-1].shape[1] == 43
    alias = post(client, request, "/recommend")
    assert alias.status_code == 200
    assert alias.json() == body


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


@pytest.mark.parametrize("credits", [{"target_credits": 4}, {"min_credits": 3, "max_credits": 4}],
                         ids=["exact", "range-with-feasible-lower-end"])
def test_no_exact_credit_plan_has_explicit_empty_result(api_client, credits):
    client, _, request = api_client
    request.pop("target_credits")
    request.update(credits)
    response = post(client, request)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "no_feasible_plan"
    assert body["recommendations"] == []
    assert body["metadata"]["target_credits"] == "4"
    assert body["metadata"]["feasible_plan_count"] == body["metadata"]["returned_plan_count"] == 0


def test_credit_range_uses_upper_end_of_provider_intersection(api_client):
    client, _, request = api_client
    request["courses_api_response"]["data"]["registserRule"]["MAX_STUDY_CREDITS"] = "6"
    request["target_credits"] = 6
    exact = post(client, request)
    assert exact.status_code == 200, exact.json()
    request.pop("target_credits")
    request.update(min_credits=3, max_credits=9)
    ranged = post(client, request)
    assert ranged.status_code == 200, ranged.json()
    body = ranged.json()
    assert body == exact.json()
    assert body["status"] == "ok"
    assert body["metadata"]["target_credits"] == "6"
    assert body["metadata"]["credit_policy"] == "upper_bound_exact"
    assert len(body["recommendations"]) == 3
    assert all(plan["total_credits"] == 6 for plan in body["recommendations"])


@pytest.mark.parametrize(("mode", "completed", "overflow", "feasible_count"), [
    ("strict_remaining", "9.00", None, 0),
    ("approved_overflow", "11.00", "5.00", 6),
    ("approved_overflow", "16.00", "0", 0),
    ("unbounded", "20", None, 6),
])
def test_provider_group_modes_restrict_the_same_exact_target(api_client, mode, completed, overflow, feasible_count):
    client, _, request = api_client
    request["target_credits"] = 6
    rows = request["courses_api_response"]["data"]["availableCourses"]
    for row in rows:
        row["REQUIREMENT_PASSED_CREDITS"] = completed
    rows.append(deepcopy(rows[0]))
    policy = request["integration_context"]["registration_policy"]
    policy["requirement_group_modes"]["group-example"] = mode
    if overflow is not None:
        policy["group_overflow_credits"] = {"group-example": overflow}

    response = post(client, request)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["metadata"]["target_credits"] == "6"
    assert body["metadata"]["candidate_count"] == 4
    assert body["metadata"]["feasible_plan_count"] == feasible_count
    assert body["status"] == ("ok" if feasible_count else "no_feasible_plan")
    assert len(body["recommendations"]) == min(feasible_count, request["top_k"])


def test_conflicting_strict_group_evidence_keeps_course_diagnostics(api_client):
    client, engine, request = api_client
    for row in request["courses_api_response"]["data"]["availableCourses"]:
        row["REQUIREMENT_PASSED_CREDITS"] = "13"

    validation = {key: request[key] for key in (
        "student_id", "degree_id", "part_id", "courses_api_response", "source_contexts", "integration_context",
    )}
    diagnostic = post(client, validation, "/api/v1/inputs/courses/validate")
    assert diagnostic.status_code == 422
    failure = diagnostic.json()
    assert failure["summary"]["candidate_count"] == 0
    assert [(error["code"], error["field"]) for error in failure["errors"]] == [
        ("CONFLICTING_GROUP", f"availableCourses[{index}]") for index in range(4)
    ]
    response = post(client, request)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INPUTS"
    assert error["details"]["courses"] == failure
    assert engine.artifacts.stage1.grade_model.matrices == []


@pytest.mark.parametrize(("credits", "code"), [
    ({"target_credits": 3, "min_credits": 3, "max_credits": 6}, "INVALID_REQUEST_SCHEMA"),
    ({"min_credits": 3}, "INVALID_REQUEST_SCHEMA"),
    ({"min_credits": 6, "max_credits": 3}, "INVALID_CREDIT_BOUNDS"),
    ({"min_credits": 19, "max_credits": 21}, "CREDIT_RANGE_CONFLICT"),
], ids=["both-modes", "missing-upper-bound", "reversed-range", "outside-provider-range"])
def test_invalid_credit_requests_report_the_rejecting_boundary(api_client, credits, code):
    client, engine, request = api_client
    request.pop("target_credits")
    request.update(credits)
    response = post(client, request)
    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == code
    assert engine.artifacts.stage1.grade_model.matrices == []
    if code == "INVALID_REQUEST_SCHEMA":
        response = post(client, split_inputs(request)["student"], "/api/v1/recommendation-inputs/student")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code


def test_source_evidence_errors_keep_component_and_field_diagnostics(api_client):
    client, engine, request = api_client
    del request["integration_context"]["total_reg_credits_source"]
    rows = request["courses_api_response"]["data"]["availableCourses"]
    rows[0]["ALLOW_REGISTER"] = True
    rows[1]["IS_REQUESTABLE"] = "N"
    rows[2]["STATUS_REASON_CODE"] = "EXCEPTION"

    diagnostics = {}
    for component, payload in split_inputs(request).items():
        validation_body = {key: value for key, value in payload.items()
                           if key not in {"request_id", "recommendation"}}
        response = post(client, validation_body, f"/api/v1/inputs/{component}/validate")
        assert response.status_code == 422, response.json()
        diagnostic = response.json()
        assert diagnostic["validation_status"] == "invalid"
        assert diagnostic["validation_completed"] is False
        diagnostics[component] = diagnostic

        split = post(client, payload, f"/api/v1/recommendation-inputs/{component}")
        assert split.status_code == 422, split.json()
        assert split.json()["error"]["code"] == "INVALID_INPUTS"
        assert split.json()["error"]["details"] == {component: diagnostic}

    assert {(issue["code"], issue["field"]) for issue in diagnostics["student"]["errors"]} == {
        ("GPA_DENOMINATOR_TEMPORALLY_AMBIGUOUS", "current_gpa_credits"),
    }
    assert diagnostics["student"]["summary"]["field_readiness"]["current_gpa_credits"] == "unavailable"
    assert {(issue["code"], issue["field"]) for issue in diagnostics["courses"]["errors"]} == {
        ("INVALID_ELIGIBILITY", "availableCourses[0].ALLOW_REGISTER"),
        ("UNRESOLVED_EXCEPTION", "availableCourses[2]"),
    }
    assert diagnostics["courses"]["summary"]["rejected_count"] == 1

    combined = post(client, request)
    assert combined.status_code == 422, combined.json()
    assert combined.json()["error"]["code"] == "INVALID_INPUTS"
    assert combined.json()["error"]["details"] == diagnostics
    assert engine.artifacts.stage1.grade_model.matrices == []


def test_authentication_is_required(api_client):
    client, engine, request = api_client
    assert client.post("/recommend", json=request).status_code == 401
    assert engine.artifacts.stage1.grade_model.matrices == []


@pytest.mark.parametrize(("first", "credits"), [
    ("student", {"target_credits": 3}),
    ("courses", {"target_credits": 3}),
    ("courses", {"min_credits": 3, "max_credits": 6}),
], ids=["student-first-exact", "courses-first-exact", "courses-first-range"])
def test_split_inputs_wait_then_return_the_same_owned_result(api_client, first, credits):
    client, _, request = api_client
    request.pop("target_credits")
    request.update(credits)
    payloads = split_inputs(request)
    second = "courses" if first == "student" else "student"
    pending = post(client, payloads[first], "/api/v1/recommendation-inputs/" + first)
    assert pending.status_code == 202
    assert pending.headers["X-Request-ID"] == "synthetic-split"
    assert pending.json() == {"request_id": "synthetic-split", "status": "pending",
                              "received": [first], "missing": [second]}
    response = post(client, payloads[second], "/api/v1/recommendation-inputs/" + second)
    assert response.status_code == 200, response.json()
    assert response.headers["X-Request-ID"] == "synthetic-split"
    result = response.json()
    assert len(result["recommendations"]) == 3
    combined = post(client, request)
    assert combined.status_code == 200, combined.json()
    assert "X-Request-ID" not in combined.headers
    assert result == combined.json()
    lookup = client.get("/api/v1/recommendation-requests/synthetic-split",
                        headers={"X-API-Key": "synthetic-service"})
    assert lookup.status_code == 200 and lookup.json()["result"] == result
    assert lookup.json()["status"] == "completed"
    assert lookup.headers["X-Request-ID"] == "synthetic-split"


@pytest.fixture
def initialized_history(api_client, tmp_path):
    client, _, _ = api_client
    _, source_hash = cumulative_source(tmp_path / "baseline")
    response = client.post(f"{HISTORY_ADMIN}/initialize", headers=ADMIN_HEADERS, json={
        "expected_source_hash": source_hash, "approval_reference": "synthetic-approved-prefix",
        "confirmation": True, "cumulative_history_confirmed": True,
    })
    assert response.status_code == 200, response.json()
    assert response.json()["active_as_of_part"] == 20251
    return response.json()["new_history_sha256"]


def history_status(client):
    response = client.get(f"{HISTORY_ADMIN}/status", headers=ADMIN_HEADERS)
    assert response.status_code == 200, response.json()
    return response.json()


def history_event():
    delta = history_delta()
    return {"part_id": delta["delta_part"], "rows": delta["aggregates"], "finalization": {
        "finalized_part_id": delta["delta_part"], "approval_reference": "synthetic-finalized-20252",
    }}


def request_for_history(request, *, target, cutoff):
    request = deepcopy(request)
    request.update(part_id=target, history_as_of_part=cutoff)
    for context in request["source_contexts"].values():
        context["part_id"] = target
    request["student_api_response"]["data"]["studentDegreeInfo"]["STATUS_SEMESTER_ID"] = str(target)
    integration = request["integration_context"]
    integration["total_reg_credits_source"].update(target_part=target, as_of_part=cutoff)
    integration["registration_policy"]["part_id"] = target
    return request


def history_files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_http_manual_history_workflow_keeps_reads_and_activation_distinct(api_client, initialized_history, tmp_path):
    client, engine, request = api_client
    baseline_hash = initialized_history
    root = tmp_path / "updates"
    event = history_event()
    old_request = request_for_history(request, target=20252, cutoff=20251)
    new_request = request_for_history(request, target=20253, cutoff=20252)
    # Make the served prediction reveal which frozen-history data reached Stage 2.
    engine.artifacts.stage2.grade_model.value = lambda matrix: matrix["course_history_avg_mark"]

    before_reads = history_files(root)
    initial_status = history_status(client)
    assert initial_status["active_history_sha256"] == baseline_hash
    assert initial_status["pending_delta"] is None

    diagnostic = client.post("/api/v1/history/deltas/validate", json=event, headers=ADMIN_HEADERS)
    assert diagnostic.status_code == 200, diagnostic.json()
    summary = diagnostic.json()["summary"]
    assert diagnostic.json()["checks"]["lineage"] == "verified"
    assert summary["base_history_sha256"] == baseline_hash
    assert summary["published"] is summary["activated"] is False
    assert history_status(client) == initial_status
    assert history_files(root) == before_reads

    response = client.post(f"{HISTORY_ADMIN}/preview", json=event, headers=ADMIN_HEADERS)
    assert response.status_code == 200, response.json()
    preview = response.json()
    assert preview["status"] == "previewed"
    assert preview["delta_sha256"] == summary["delta_sha256"]
    pending = history_status(client)
    assert pending["pending_delta"]["preview_token"] == preview["preview_token"]
    assert pending["available_versions"] == [20251]
    assert pending["active_history_sha256"] == baseline_hash

    before_reads = history_files(root)
    old = post(client, old_request)
    assert old.status_code == 200, old.json()
    assert old.json()["status"] == "ok"
    assert old.json()["metadata"]["history_as_of_part"] == 20251
    assert history_status(client) == pending
    assert history_files(root) == before_reads

    pinned = engine.history_manager.capture(target_part=20252, history_as_of_part=20251)
    pinned_metadata = pinned.metadata
    assert pinned_metadata["artifact_sha256"]["course_history_state.pkl"] == baseline_hash
    course = old.json()["recommendations"][0]["courses"][0]
    probe = pd.DataFrame([{
        "part_id": 20253, "degree_id": request["degree_id"], "faculty_id": "faculty-example",
        "course_id": course["course_id"], "course_credits": 3, "plan_requirement_type_id": "R",
    }])
    pinned_data = pinned.apply(probe)
    old_mark = pinned_data["course_history_avg_mark"].iat[0]
    assert course["predicted_mark"] == pytest.approx(old_mark)

    response = client.post(f"{HISTORY_ADMIN}/commit", headers=ADMIN_HEADERS, json={
        **event, "preview_token": preview["preview_token"], "confirmation": True,
    })
    assert response.status_code == 200, response.json()
    committed = response.json()
    assert committed["status"] == "committed" and committed["activated"] is False
    new_hash = committed["new_history_sha256"]
    assert new_hash != baseline_hash
    status = history_status(client)
    assert status["available_versions"] == [20251, 20252]
    assert status["active_history_sha256"] == baseline_hash
    unavailable = post(client, new_request)
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "HISTORY_UNAVAILABLE"

    response = client.post(f"{HISTORY_ADMIN}/activate", headers=ADMIN_HEADERS, json={
        "history_as_of_part": 20252, "expected_history_sha256": new_hash, "confirmation": True,
    })
    assert response.status_code == 200, response.json()
    assert response.json()["activated"] is True
    status = history_status(client)
    assert status["active_as_of_part"] == 20252 and status["active_history_sha256"] == new_hash
    assert status["pending_delta"] is None
    assert pinned.as_of_part == 20251 and pinned.metadata == pinned_metadata
    assert_frame_equal(pinned.apply(probe), pinned_data, check_exact=True)

    new = post(client, new_request)
    assert new.status_code == 200, new.json()
    assert new.json()["status"] == "ok"
    assert new.json()["metadata"]["history_as_of_part"] == 20252
    active = engine.history_manager.capture(target_part=20253, history_as_of_part=20252)
    assert active.metadata["artifact_sha256"]["course_history_state.pkl"] == new_hash
    new_mark = active.apply(probe)["course_history_avg_mark"].iat[0]
    assert new_mark != pytest.approx(old_mark)
    new_courses = [course for plan in new.json()["recommendations"] for course in plan["courses"]]
    assert [row["predicted_mark"] for row in new_courses if row["course_id"] == course["course_id"]] == [
        pytest.approx(new_mark),
    ]

    rollback = {"history_as_of_part": 20251, "expected_history_sha256": baseline_hash, "confirmation": True}
    rejected = client.post(f"{HISTORY_ADMIN}/activate", json=rollback, headers=ADMIN_HEADERS)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "ROLLBACK_CONFIRMATION_REQUIRED"
    assert history_status(client)["active_history_sha256"] == new_hash
    response = client.post(f"{HISTORY_ADMIN}/activate", json={**rollback, "rollback": True}, headers=ADMIN_HEADERS)
    assert response.status_code == 200, response.json()
    status = history_status(client)
    assert status["active_history_sha256"] == baseline_hash
    assert status["available_versions"] == [20251, 20252]
    assert status["last_successful_update"]["operation"] == "rollback"
    assert post(client, old_request).json() == old.json()
    unavailable = post(client, new_request)
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "HISTORY_UNAVAILABLE"


def test_http_finalization_requires_its_credential_and_auto_mode(api_client, initialized_history, tmp_path):
    client, _, _ = api_client
    path = f"{HISTORY_ADMIN}/finalization-events"
    event = history_event()
    response = client.post(path, json=event, headers=FINALIZATION_HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUTO_MODE_REQUIRED"
    rejected = history_status(client)
    assert rejected["active_history_sha256"] == initialized_history
    assert rejected["available_versions"] == [20251]
    assert rejected["pending_delta"] is None
    assert rejected["failures"][-1]["code"] == "AUTO_MODE_REQUIRED"

    mode = client.put(f"{HISTORY_ADMIN}/mode", json={"mode": "auto_on_finalization"}, headers=ADMIN_HEADERS)
    assert mode.status_code == 200, mode.json()
    assert mode.json()["active_history_sha256"] == initialized_history
    before = history_files(tmp_path / "updates")
    response = client.post(path, json=event, headers=ADMIN_HEADERS)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH_FORBIDDEN"
    response = client.post(path, json={**event, "finalization": None}, headers=FINALIZATION_HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FINALIZATION_REQUIRED"
    assert history_files(tmp_path / "updates") == before

    response = client.post(path, json=event, headers=FINALIZATION_HEADERS)
    assert response.status_code == 200, response.json()
    assert response.json()["activated"] is True
    status = history_status(client)
    assert status["active_as_of_part"] == 20252
    assert status["active_history_sha256"] == response.json()["new_history_sha256"]
    assert status["active_history_sha256"] != initialized_history
    assert status["pending_delta"] is None


def test_http_request_keeps_the_same_history_after_cross_worker_rollback(
    api_client, initialized_history, tmp_path, monkeypatch,
):
    client, engine, request = api_client
    api = client.app.state.api_service
    store = api.history_store
    delta = history_delta()
    preview = store.preview(history_payload=delta)
    committed = store.commit(history_payload=delta, preview_token=preview["preview_token"],
                             confirmation=True, approval_reference="synthetic-finalized-20252")
    store.activate(cutoff=20252, expected_history_sha256=committed["new_history_sha256"], confirmation=True)
    other_worker = CumulativeHistoryStore(tmp_path / "updates", compatibility_check=api._history_compatibility,
                                          legacy_root=tmp_path / "baseline")
    request = request_for_history(request, target=20253, cutoff=20252)
    engine.artifacts.stage2.grade_model.value = lambda matrix: matrix["course_history_avg_mark"]
    before = post(client, request)
    assert before.status_code == 200, before.json()

    captured, resume = Event(), Event()
    real_capture = store.capture
    cutoffs = []

    def pause_after_capture(**kwargs):
        snapshot = real_capture(**kwargs)
        cutoffs.append(snapshot.as_of_part)
        if len(cutoffs) == 1:
            captured.set()
            assert resume.wait(15)
        return snapshot

    monkeypatch.setattr(store, "capture", pause_after_capture)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(post, client, request)
        try:
            assert captured.wait(15)
            other_worker.activate(cutoff=20251, expected_history_sha256=initialized_history,
                                  confirmation=True, rollback=True)
        finally:
            resume.set()
        response = pending.result(timeout=15)

    assert response.status_code == 200, response.json()
    assert response.json() == before.json()
    assert cutoffs == [20252]
    rejected = post(client, request)
    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == "HISTORY_UNAVAILABLE"


def test_http_preserves_inference_and_history_operation_busy_errors(api_client):
    client, engine, request = api_client
    scoring, resume = Event(), Event()

    def wait_for_other_calls(matrix):
        scoring.set()
        assert resume.wait(15)
        return matrix["course_credits"] * 0 + 90

    engine.artifacts.stage1.grade_model.value = wait_for_other_calls
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(post, client, request)
        try:
            assert scoring.wait(15)
            rejected = post(client, request)
            assert rejected.status_code == 503
            assert rejected.json()["error"]["code"] == "INFERENCE_BUSY"
            rejected = client.post(f"{HISTORY_ADMIN}/preview", json=history_event(), headers=ADMIN_HEADERS)
            assert rejected.status_code == 503
            assert rejected.json()["error"]["code"] == "HISTORY_OPERATION_BUSY"
        finally:
            resume.set()
        response = pending.result(timeout=15)
    assert response.status_code == 200, response.json()


def test_http_preserves_the_public_call_for_an_injected_engine(api_client):
    client, engine, request = api_client
    api = client.app.state.api_service
    expected = post(client, request)
    assert expected.status_code == 200
    seen = []

    def recommend(**options):
        seen.append((options["history_as_of_part"], options["allow_older_history"]))
        return engine.recommend_from_payloads(**options)

    api.engine = SimpleNamespace(recommend_from_payloads=recommend)
    api.history_manager = SimpleNamespace(capture=engine.history_manager.capture)
    response = post(client, request)

    assert response.status_code == 200, response.json()
    assert response.json() == expected.json()
    assert seen == [(20243, False)]
