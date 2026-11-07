from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "academic_advisor_streamlit"))
from ui_client import (ClientError, Config, HttpClient, encode_json, load_context, make_payloads,
                       mapping_values, parse_json, previous_academic_part, student_degree_id)


def test_default_config_prefers_ignored_local_environment(tmp_path, monkeypatch):
    import ui_client
    fake_module = tmp_path / "tools/academic_advisor_streamlit/ui_client.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.touch()
    (tmp_path / ".env").write_text("ADVISOR_API_KEY=synthetic-tracked-placeholder\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("ADVISOR_API_KEY=synthetic-private-local\n", encoding="utf-8")
    monkeypatch.setattr(ui_client, "__file__", str(fake_module))
    monkeypatch.delenv("ADVISOR_API_KEY", raising=False)
    monkeypatch.delenv("ADVISOR_UI_SERVICE_KEY", raising=False)
    assert Config.from_env().service_key == "synthetic-private-local"


@pytest.fixture
def config():
    return Config(fastapi_base="http://127.0.0.1:8000",
                  student_url="https://university.example/student", courses_url="https://university.example/courses",
                  history_url="https://university.example/history",
                  student_params={"student_id": "studentId", "part_id": "semesterId"},
                  courses_params={"student_id": "studentId", "degree_id": "degreeId", "part_id": "semesterId"},
                  history_params={"part_id": "part_id"}, history_method="GET", service_key="test-service", admin_key="test-admin",
                  upstream_bearer="test-backend-token", timeout=5, context_file=None)


class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self.raw = json.dumps(payload, ensure_ascii=False).encode("utf8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def iter_content(self, chunk_size):
        yield self.raw


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


def test_term_cutoff():
    assert previous_academic_part(20262) == 20261
    assert previous_academic_part(20261) == 20253
    with pytest.raises(ClientError):
        previous_academic_part(20264)


def test_parameter_mapping():
    assert mapping_values({"student_id": "studentId", "part_id": "semesterId"},
                          student_id="27700.111", part_id=20262) == {"studentId": "27700.111", "semesterId": "20262"}
    with pytest.raises(ClientError):
        mapping_values({"degree_id": "degreeId"}, student_id="27700.111", part_id=20262)


def test_decimal_precision_and_nonfinite_rejection():
    response = parse_json('{"success":true,"data":{"marks":0.30000000000000001}}')
    assert response["data"]["marks"] == Decimal("0.30000000000000001")
    assert json.loads(encode_json(response))["data"]["marks"] == "0.30000000000000001"
    with pytest.raises(ClientError):
        parse_json('{"x":NaN}')


def test_degree_resolution_validates_student_and_term():
    response = {"data": {"studentDegreeInfo": {"STUDENT_ID": "27700.111", "DEGREE_ID": "13.111", "STATUS_SEMESTER_ID": "20262"}}}
    assert student_degree_id(response, "27700.111", 20262) == "13.111"
    with pytest.raises(ClientError):
        student_degree_id(response, "other", 20262)
    with pytest.raises(ClientError):
        student_degree_id(response, "27700.111", 20261)


def test_builds_two_separate_requests_and_no_fabricated_evidence():
    student, courses = make_payloads(student_id="S", degree_id="D", part_id=20262, cutoff=20261,
        student_response={"success": True}, courses_response={"success": True},
        student_context={}, courses_context={}, target_credits="18", top_k=3, request_id="rid-12")
    assert student["request_id"] == courses["request_id"] == "rid-12"
    assert student["source_contexts"] == {"student": {"student_id": "S", "degree_id": "D", "part_id": 20262}}
    assert courses["source_contexts"] == {"courses": {"student_id": "S", "degree_id": "D", "part_id": 20262}}
    assert "courses_api_response" not in student
    assert "student_api_response" not in courses
    assert student["recommendation"]["history_as_of_part"] == 20261
    assert student["integration_context"] == {}


def test_student_and_courses_get_use_proper_endpoints_auth_and_params(config):
    fake = FakeSession([
        FakeResponse(200, {"success": True, "data": {"studentDegreeInfo": {"STUDENT_ID": "S", "DEGREE_ID": "D", "STATUS_SEMESTER_ID": "20262"}}}),
        FakeResponse(200, {"success": True, "data": {"availableCourses": [], "registserRule": {}}})
    ])
    client = HttpClient(config, fake)
    assert client.student("S", 20262)["success"]
    assert client.courses("S", "D", 20262)["success"]
    assert fake.calls[0][0:2] == ("GET", "https://university.example/student")
    assert fake.calls[0][2]["params"] == {"studentId": "S", "semesterId": "20262"}
    assert fake.calls[1][2]["params"] == {"studentId": "S", "degreeId": "D", "semesterId": "20262"}
    assert fake.calls[0][2]["headers"]["Authorization"] == "Bearer test-backend-token"
    assert "X-API-Key" not in fake.calls[0][2]["headers"]
    assert fake.trust_env is False


def test_submit_pair_calls_different_post_urls(config):
    fake = FakeSession([FakeResponse(202, {"status": "pending"}), FakeResponse(200, {"status": "ok", "recommendations": []})])
    client = HttpClient(config, fake)
    result = client.submit_pair({"request_id": "r1"}, {"request_id": "r1"})
    assert [x[1] for x in result] == [202, 200]
    assert [x[0] for x in result] == ["student", "courses"]
    assert fake.calls[0][1] == "http://127.0.0.1:8000/api/v1/recommendation-inputs/student"
    assert fake.calls[1][1] == "http://127.0.0.1:8000/api/v1/recommendation-inputs/courses"
    assert fake.calls[0][2]["headers"]["X-API-Key"] == "test-service"


def test_submit_pair_stops_on_validation_failure(config):
    fake = FakeSession([FakeResponse(422, {"error": {"code": "INVALID_INPUTS"}})])
    result = HttpClient(config, fake).submit_pair({"request_id": "r"}, {"request_id": "r"})
    assert len(result) == len(fake.calls) == 1


def test_history_get_accepts_semester_delta_only(config):
    fake = FakeSession([FakeResponse(200, {"success": True, "data": {"part_id": 20261, "rows": [{"count": 20}]}})])
    result = HttpClient(config, fake).frozen_history(20261)
    assert result == {"part_id": 20261, "rows": [{"count": 20}]}
    assert fake.calls[0][2]["params"] == {"part_id": "20261"}


def test_history_can_use_post_but_must_match_part(config):
    fake = FakeSession([FakeResponse(200, {"part_id": 20262, "rows": []})])
    client = HttpClient(replace(config, history_method="POST"), fake)
    with pytest.raises(ClientError):
        client.frozen_history(20261)
    assert fake.calls[0][0] == "POST"
    assert json.loads(fake.calls[0][2]["data"]) == {"part_id": "20261"}


def test_context_missing_is_empty_and_existing_does_not_forge(tmp_path, config):
    assert load_context(config) == ({}, {})
    context = tmp_path / "context.json"
    context.write_text('{"student":{"student_values":{}},"courses":{"registration_policy":null}}', encoding="utf8")
    left, right = load_context(replace(config, context_file=context))
    assert left["student_values"] == {}
    assert right["registration_policy"] is None


def test_upstream_http_failure_is_private(config):
    fake = FakeSession([FakeResponse(403, {"detail": "student named Example forbidden"})])
    with pytest.raises(ClientError) as err:
        HttpClient(config, fake).student("S", 20262)
    assert "student named" not in str(err.value)


def test_redirect_is_rejected(config):
    fake = FakeSession([FakeResponse(302, {"message": "Moved"})])
    with pytest.raises(ClientError):
        HttpClient(config, fake).student("S", 20262)


def test_frozen_history_requires_rows(config):
    fake = FakeSession([FakeResponse(200, {"part_id": 20261})])
    with pytest.raises(ClientError):
        HttpClient(config, fake).frozen_history(20261)


def test_custom_university_headers_are_not_sent_to_fastapi(config):
    fake = FakeSession([FakeResponse(200, {"ok": True}), FakeResponse(202, {"status": "pending"})])
    configured = replace(config, upstream_headers={"token": "uni-token", "user": "uni-user"}, upstream_bearer="")
    client = HttpClient(configured, fake)
    client.student("S", 20262)
    client.advisor("POST", "/api/v1/recommendation-inputs/student", data={"request_id": "a"})
    upstream_headers = fake.calls[0][2]["headers"]
    fastapi_headers = fake.calls[1][2]["headers"]
    assert upstream_headers["token"] == "uni-token"
    assert upstream_headers["user"] == "uni-user"
    assert "Authorization" not in upstream_headers
    assert "token" not in fastapi_headers and "user" not in fastapi_headers
    assert fastapi_headers["X-API-Key"] == "test-service"

def test_custom_headers_can_be_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADVISOR_UI_BACKEND_HEADERS", '{"token":"abc","user":"demo"}')
    result = Config.from_env(env_path=tmp_path / "nonexistent.env")
    assert result.upstream_headers == {"token": "abc", "user": "demo"}
    monkeypatch.setenv("ADVISOR_UI_BACKEND_HEADERS", '{"token":"abc\\nxyz"}')
    with pytest.raises(ClientError):
        Config.from_env(env_path=tmp_path / "nonexistent.env")

def test_explicit_authorization_conflicts_with_bearer_setting(config):
    configured = replace(config, upstream_headers={"Authorization": "custom"})
    fake = FakeSession([])
    with pytest.raises(ClientError, match="Authorization"):
        HttpClient(configured, fake).student("S", 20262)
    assert fake.calls == []
