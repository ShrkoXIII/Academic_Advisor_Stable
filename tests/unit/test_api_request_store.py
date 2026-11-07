"""Durable split-request correlation using synthetic payloads and owned SQLite files."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.api.validators.common import ApiError


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def store(tmp_path, **options):
    from src.api.request_store import RequestStore
    config = dict(pending_ttl_seconds=10, processing_ttl_seconds=20,
                  result_ttl_seconds=30, max_requests=50, max_payload_bytes=10000)
    config.update(options)
    return RequestStore(tmp_path / "requests" / "requests.sqlite3", **config)


def payload(component, **changes):
    return {"student_id": "synthetic-student", "degree_id": "synthetic-degree", "part_id": 20251,
            component + "_api_response": {"source": component, "value": "synthetic-private-value"},
            **changes}


def assert_error(code, call, status):
    with pytest.raises(ApiError) as caught:
        call()
    assert caught.value.issue["code"] == code
    assert caught.value.status_code == status


@pytest.mark.parametrize("first", ["student", "courses"])
def test_either_order_is_pending_until_one_atomic_claim(tmp_path, first):
    db = store(tmp_path)
    second = "courses" if first == "student" else "student"
    pending = db.submit("caller", "synthetic-1", first, payload(first))
    assert pending == {"request_id": "synthetic-1", "status": "pending", "received": [first],
                       "missing": [second], "claimed": False}
    claimed = db.submit("caller", "synthetic-1", second, payload(second))
    assert claimed["status"] == "processing" and claimed["claimed"] is True
    assert claimed["received"] == ["student", "courses"] and claimed["missing"] == []
    assert claimed["components"] == {first: payload(first), second: payload(second)}
    assert claimed["claim_token"]
    public = db.lookup("caller", "synthetic-1")
    assert public == {"request_id": "synthetic-1", "status": "processing",
                      "received": ["student", "courses"], "missing": []}


def test_canonical_retry_and_conflict_are_typed_and_durable(tmp_path):
    db = store(tmp_path)
    data = payload("student", value=Decimal("0.10000000000000000000000000001"))
    first = db.submit("caller", "synthetic-1", "student", data)
    reordered = dict(reversed(list(data.items())))
    assert db.submit("caller", "synthetic-1", "student", reordered) == first
    changed = dict(data, value="0.10000000000000000000000000001")
    assert_error("REQUEST_COMPONENT_CONFLICT", lambda: db.submit("caller", "synthetic-1", "student", changed), 409)
    restarted = store(tmp_path)
    assert restarted.replay("caller", "synthetic-1", "student", reordered) == db.lookup("caller", "synthetic-1")
    assert restarted.replay("caller", "missing", "student", data) is None
    assert restarted.replay("caller", "synthetic-1", "courses", payload("courses")) is None


def test_decimal_envelopes_do_not_confuse_user_tag_keys(tmp_path):
    db = store(tmp_path)
    nested = {"decimal": "user string", "__decimal__": ["decimal", "user content"],
              "value": Decimal("0.10000000000000000000000000001"),
              "items": [True, 1, 1.0, None, {"dict": {"str": "value"}}]}
    data = payload("student", nested=nested)
    db.submit("caller", "synthetic-1", "student", data)
    claimed = db.submit("caller", "synthetic-1", "courses", payload("courses"))
    assert claimed["components"]["student"] == data
    assert isinstance(claimed["components"]["student"]["nested"]["value"], Decimal)
    assert claimed["components"]["student"]["nested"]["value"].as_tuple() == nested["value"].as_tuple()


@pytest.mark.parametrize("field,value", [("student_id", "other"), ("degree_id", "other"), ("part_id", 20252)])
def test_identity_mismatch_cannot_store_or_claim_another_component(tmp_path, field, value):
    db = store(tmp_path)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    other = payload("courses", **{field: value})
    for method in (db.replay, db.submit):
        assert_error("REQUEST_IDENTITY_MISMATCH", lambda method=method: method("caller", "synthetic-1", "courses", other), 409)
    assert db.lookup("caller", "synthetic-1")["received"] == ["student"]


def test_identity_normalization_preserves_existing_id_and_part_semantics(tmp_path):
    db = store(tmp_path)
    db.submit("caller", "synthetic-1", "student", payload("student", student_id=" synthetic-student ", part_id="20251"))
    assert db.submit("caller", "synthetic-1", "courses", payload("courses"))["claimed"] is True


def test_cross_owner_cannot_discover_submit_or_complete_a_request(tmp_path):
    db = store(tmp_path)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    for call in [lambda: db.lookup("other", "synthetic-1"),
                 lambda: db.replay("other", "synthetic-1", "student", payload("student")),
                 lambda: db.submit("other", "synthetic-1", "courses", payload("courses")),
                 lambda: db.complete("other", "synthetic-1", "token", {})]:
        assert_error("REQUEST_NOT_FOUND", call, 404)


def test_thread_retries_and_separate_instances_obtain_only_one_claim(tmp_path):
    db = store(tmp_path)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    workers = [store(tmp_path) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(lambda worker: worker.submit("caller", "synthetic-1", "courses", payload("courses")), workers))
    assert sum(result["claimed"] for result in outcomes) == 1
    assert all(result["status"] == "processing" for result in outcomes)
    assert all("components" not in result and "claim_token" not in result
               for result in outcomes if not result["claimed"])


def test_separate_worker_processes_cannot_claim_duplicate_inference(tmp_path):
    db = store(tmp_path)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    script = """
import json, sys
from src.api.request_store import RequestStore
db = RequestStore(sys.argv[1], pending_ttl_seconds=10, processing_ttl_seconds=20,
                  result_ttl_seconds=30, max_requests=50, max_payload_bytes=10000)
data = {'student_id':'synthetic-student','degree_id':'synthetic-degree','part_id':20251,
        'courses_api_response':{'source':'courses','value':'synthetic-private-value'}}
state = db.submit('caller','synthetic-1','courses',data)
print(json.dumps({'claimed':state['claimed'],'status':state['status']}))
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(db.path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(6)]
    outcomes = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            outcomes.append(json.loads(stdout))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert sum(result["claimed"] for result in outcomes) == 1
    assert {result["status"] for result in outcomes} == {"processing"}


def test_completion_and_failure_are_retrievable_without_retrying_claim(tmp_path):
    db = store(tmp_path)
    for request_id in ("complete", "failed"):
        db.submit("caller", request_id, "student", payload("student"))
        claimed = db.submit("caller", request_id, "courses", payload("courses"))
        if request_id == "complete":
            result = {"status": "ok", "recommendations": [{"credits": Decimal("12.1")}], "metadata": {}}
            terminal = db.complete("caller", request_id, claimed["claim_token"], result)
            assert terminal["result"] == result and terminal["status"] == "completed"
        else:
            issue = {"code": "INVALID_INPUTS", "message": "Synthetic invalid input.", "component": "input"}
            terminal = db.fail("caller", request_id, claimed["claim_token"], issue, http_status=422)
            assert terminal["error"] == issue and terminal["http_status"] == 422 and terminal["status"] == "failed"
        assert store(tmp_path).lookup("caller", request_id) == terminal
        retry = db.submit("caller", request_id, "courses", payload("courses"))
        assert retry == {**terminal, "claimed": False}
        assert "components" not in retry and "claim_token" not in retry


def test_only_current_claim_can_write_a_terminal_result(tmp_path):
    db = store(tmp_path)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    assert_error("REQUEST_CLAIM_CONFLICT", lambda: db.complete("caller", "synthetic-1", "wrong", {}), 409)
    claimed = db.submit("caller", "synthetic-1", "courses", payload("courses"))
    assert_error("REQUEST_CLAIM_CONFLICT", lambda: db.complete("caller", "synthetic-1", "wrong", {}), 409)
    assert db.complete("caller", "synthetic-1", claimed["claim_token"], {"status": "ok"})["status"] == "completed"


def test_pending_expiry_scrubs_payload_and_preserves_nonreusable_id(tmp_path):
    clock = Clock()
    db = store(tmp_path, clock=clock)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    clock.now += 10
    expired = db.lookup("caller", "synthetic-1")
    assert expired["status"] == "failed" and expired["error"]["code"] == "REQUEST_EXPIRED"
    assert expired["http_status"] == 410 and expired["received"] == ["student"]
    retry = db.submit("caller", "synthetic-1", "courses", payload("courses"))
    assert retry["claimed"] is False and retry["http_status"] == 410
    with sqlite3.connect(db.path) as connection:
        row = connection.execute("SELECT student_payload,courses_payload,result,claim_token FROM requests").fetchone()
    assert row == (None, None, None, None)


def test_processing_expiry_never_reclaims_or_accepts_a_late_completion(tmp_path):
    clock = Clock()
    db = store(tmp_path, clock=clock)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    claim = db.submit("caller", "synthetic-1", "courses", payload("courses"))
    clock.now += 20
    expired = db.lookup("caller", "synthetic-1")
    assert expired["error"]["code"] == "REQUEST_PROCESSING_EXPIRED" and expired["http_status"] == 503
    assert db.submit("caller", "synthetic-1", "courses", payload("courses"))["claimed"] is False
    assert db.complete("caller", "synthetic-1", claim["claim_token"], {"status": "ok"}) == expired
    clock.now += 30
    assert db.lookup("caller", "synthetic-1")["http_status"] == 410


def test_result_retention_scrubs_result_and_input_columns(tmp_path):
    clock = Clock()
    db = store(tmp_path, clock=clock)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    claim = db.submit("caller", "synthetic-1", "courses", payload("courses"))
    db.complete("caller", "synthetic-1", claim["claim_token"], {"synthetic_result": "private outcome"})
    clock.now += 30
    state = db.lookup("caller", "synthetic-1")
    assert state["status"] == "failed" and state["http_status"] == 410 and "result" not in state
    with sqlite3.connect(db.path) as connection:
        row = connection.execute("SELECT student_payload,courses_payload,result,claim_token FROM requests").fetchone()
    assert row == (None, None, None, None)


def test_capacity_counts_expired_tombstones_and_does_not_lose_pending_rows(tmp_path):
    clock = Clock()
    db = store(tmp_path, max_requests=1, clock=clock)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    assert_error("REQUEST_STORE_FULL", lambda: db.submit("caller", "synthetic-2", "student", payload("student")), 503)
    clock.now += 10
    assert_error("REQUEST_STORE_FULL", lambda: db.submit("caller", "synthetic-2", "student", payload("student")), 503)
    with sqlite3.connect(db.path) as connection:
        row = connection.execute("SELECT student_payload,status FROM requests").fetchone()
    assert row == (None, "failed")
    assert db.lookup("caller", "synthetic-1")["http_status"] == 410


def test_oversized_components_are_rejected_without_inserting_rows(tmp_path):
    db = store(tmp_path, max_payload_bytes=500)
    assert_error("REQUEST_PAYLOAD_TOO_LARGE", lambda: db.submit("caller", "synthetic-1", "student", payload("student", huge="x" * 501)), 413)
    assert_error("REQUEST_NOT_FOUND", lambda: db.lookup("caller", "synthetic-1"), 404)


def test_oversized_result_finishes_as_safe_terminal_failure(tmp_path):
    db = store(tmp_path, max_payload_bytes=500)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    claim = db.submit("caller", "synthetic-1", "courses", payload("courses"))
    state = db.complete("caller", "synthetic-1", claim["claim_token"], {"huge": "x" * 501})
    assert state["status"] == "failed" and state["http_status"] == 413
    assert state["error"]["code"] == "REQUEST_RESULT_TOO_LARGE"
    assert db.submit("caller", "synthetic-1", "courses", payload("courses"))["claimed"] is False


@pytest.mark.parametrize("name", ["pending_ttl_seconds", "processing_ttl_seconds", "result_ttl_seconds", "max_requests", "max_payload_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_limits_require_positive_integer_configuration(tmp_path, name, value):
    with pytest.raises(ValueError):
        store(tmp_path, **{name: value})


@pytest.mark.parametrize("request_id", ["", "../private", "space id", "id:part", "x" * 129, None, True])
def test_request_id_is_bounded_and_cannot_act_as_a_path(tmp_path, request_id):
    db = store(tmp_path)
    assert_error("INVALID_REQUEST_ID", lambda: db.submit("caller", request_id, "student", payload("student")), 422)


def test_database_lock_failure_is_safe_and_does_not_silently_drop_state(tmp_path):
    db = store(tmp_path)
    db.submit("caller", "synthetic-1", "student", payload("student"))
    with sqlite3.connect(db.path, isolation_level=None) as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert_error("REQUEST_STORE_BUSY", lambda: db.lookup("caller", "synthetic-1"), 503)
        connection.rollback()
    assert db.lookup("caller", "synthetic-1")["status"] == "pending"


def test_corrupt_database_errors_never_expose_sql_or_paths(tmp_path):
    db = store(tmp_path)
    db.path.write_bytes(b"synthetic corrupted database")
    with pytest.raises(ApiError) as caught:
        db.lookup("caller", "synthetic-1")
    assert caught.value.issue["code"] == "REQUEST_STORE_UNAVAILABLE"
    assert str(db.path) not in str(caught.value.issue)
    assert "database" not in caught.value.issue["message"].lower()


@pytest.mark.skipif(os.name == "nt", reason="Windows protection uses deployment service-account ACLs.")
def test_posix_database_and_private_root_permissions(tmp_path):
    db = store(tmp_path)
    assert db.path.stat().st_mode & 0o777 == 0o600
    assert db.path.parent.stat().st_mode & 0o777 == 0o700
