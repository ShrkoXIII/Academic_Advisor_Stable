"""Single-host SQLite correlation with durable claims and bounded private payloads.

Each operation uses a separate connection and an immediate transaction. Claims
are never retried after worker loss: processing expiry records a failure. Expired
IDs remain as 410 tombstones for one additional result-retention interval, then
are deleted so request capacity is reclaimed. After that bounded idempotency
window, callers must use a new, unique request_id to avoid duplicate work.
Use a dedicated service-account-private directory; Windows deployments must
provide private ACLs for that directory and its database/journal files.
"""
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from secrets import compare_digest, token_hex
import sqlite3
import time

from .validators.common import ApiError, identifier, identity


COMPONENTS = ("student", "courses")


def validate_request_id(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None:
        raise ApiError("INVALID_REQUEST_ID", "A request identifier of 1 to 128 safe characters is required.", field="request_id")
    return value


def _encode(value):
    """Tag every node, so user dictionaries cannot collide with Decimal tags."""
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, Decimal) and value.is_finite():
        return ["decimal", str(value)]
    if isinstance(value, float) and math.isfinite(value):
        return ["float", repr(value)]
    if isinstance(value, list):
        return ["list", [_encode(item) for item in value]]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return ["dict", [[key, _encode(value[key])] for key in sorted(value)]]
    raise ValueError("Unsupported request value.")


def _decode(node):
    tag = node[0]
    if tag == "null":
        return None
    value = node[1]
    if tag in {"str", "bool"}:
        return value
    if tag == "int":
        return int(value)
    if tag == "float":
        return float(value)
    if tag == "decimal":
        return Decimal(value)
    if tag == "list":
        return [_decode(item) for item in value]
    if tag == "dict":
        return {key: _decode(item) for key, item in value}
    raise ValueError("Invalid stored value.")


def _serialized(value):
    return json.dumps(_encode(value), ensure_ascii=False, separators=(",", ":"))


def _digest(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()


class RequestStore:
    def __init__(self, path, *, pending_ttl_seconds, processing_ttl_seconds,
                 result_ttl_seconds, max_requests, max_payload_bytes, clock=time.time):
        for value in (pending_ttl_seconds, processing_ttl_seconds, result_ttl_seconds,
                      max_requests, max_payload_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("Request retention and capacity limits must be positive integers.")
        if not callable(clock):
            raise ValueError("Request clock must be callable.")
        self.path = Path(path).expanduser().resolve()
        self.pending_ttl_seconds, self.processing_ttl_seconds = pending_ttl_seconds, processing_ttl_seconds
        self.result_ttl_seconds, self.max_requests = result_ttl_seconds, max_requests
        self.max_payload_bytes, self.clock = max_payload_bytes, clock
        try:
            # mkdir(mode=...) protects a newly created directory. Do not chmod
            # pre-existing directories: they may be shared with other services.
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                if stat.S_IMODE(self.path.parent.stat().st_mode) & 0o077:
                    raise self._unavailable()
                # Atomically create new DB files with private permissions rather
                # than letting SQLite create them with a permissive process umask.
                try:
                    fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                except FileExistsError:
                    pass
                else:
                    os.close(fd)
                # Existing files must already be private; never rewrite their
                # permissions as a side effect of application startup.
                if not self.path.is_file() or stat.S_IMODE(self.path.stat().st_mode) & 0o077:
                    raise self._unavailable()
            with self._transaction() as connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    identity_digest TEXT NOT NULL, status TEXT NOT NULL
                        CHECK (status IN ('pending','processing','completed','failed')),
                    student_digest TEXT, courses_digest TEXT,
                    student_payload TEXT, courses_payload TEXT, claim_token TEXT,
                    result TEXT, error TEXT, http_status INTEGER, expires_at REAL
                )""")
        except OSError:
            raise self._unavailable() from None

    @staticmethod
    def _unavailable():
        return ApiError("REQUEST_STORE_UNAVAILABLE", "Request storage is unavailable.", status_code=503)

    @contextmanager
    def _transaction(self):
        connection = None
        try:
            connection = sqlite3.connect(str(self.path), timeout=1.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError) as error:
            if connection is not None:
                connection.rollback()
            if getattr(error, "sqlite_errorcode", None) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise ApiError("REQUEST_STORE_BUSY", "Request storage is busy; retry later.", status_code=503) from None
            raise self._unavailable() from None
        except ApiError as error:
            if connection is not None:
                # These rejections precede all component/result writes. Commit
                # housekeeping so an expired payload is erased even when the
                # caller conflicts, looks up an unknown ID, or hits capacity.
                if error.issue["code"] in {"REQUEST_NOT_FOUND", "REQUEST_STORE_FULL", "REQUEST_COMPONENT_CONFLICT",
                                           "REQUEST_IDENTITY_MISMATCH", "REQUEST_CLAIM_CONFLICT"}:
                    try:
                        connection.commit()
                    except sqlite3.Error:
                        raise self._unavailable() from None
                else:
                    connection.rollback()
            raise
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    def _now(self):
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise self._unavailable()
        return float(value)

    @staticmethod
    def _owner(owner):
        owner = identifier(owner, "owner")
        if len(owner) > 256:
            raise ApiError("INVALID_REQUEST_OWNER", "Request ownership is invalid.")
        return owner

    def _payload(self, payload):
        try:
            encoded = _serialized(payload)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ApiError("INVALID_REQUEST_PAYLOAD", "Request values are unsupported.") from None
        if len(encoded.encode("utf8")) > self.max_payload_bytes:
            raise ApiError("REQUEST_PAYLOAD_TOO_LARGE", "Request component exceeds the configured size limit.", status_code=413)
        return encoded

    def _input(self, owner, request_id, component, payload):
        owner, request_id = self._owner(owner), validate_request_id(request_id)
        if component not in COMPONENTS:
            raise ApiError("INVALID_REQUEST_COMPONENT", "A student or courses component is required.")
        if not isinstance(payload, dict):
            raise ApiError("INVALID_REQUEST_PAYLOAD", "A request component must be a record.")
        identity_digest = _digest(_serialized(identity(payload)))
        encoded = self._payload(payload)
        return owner, request_id, identity_digest, encoded, _digest(encoded)

    @staticmethod
    def _safe_error(code, message):
        return _serialized({"code": code, "message": message, "component": "input"})

    def _expire(self, connection, now):
        expired = self._safe_error("REQUEST_EXPIRED", "Request retention has expired; use a new request identifier.")
        processing = self._safe_error("REQUEST_PROCESSING_EXPIRED", "Recommendation processing expired; the request will not be retried.")
        # Remove tombstones only after their bounded grace period. Old databases
        # may contain permanent (expires_at=NULL) tombstones; clean those up too.
        connection.execute("""DELETE FROM requests WHERE status='failed' AND error=?
            AND (expires_at IS NULL OR expires_at <= ?)""", (expired, now))
        # Keep an expired ID reserved for one more result-retention interval.
        # This gives late retries an explicit 410 without indefinitely consuming
        # SQLite capacity. Do not re-expire an existing tombstone every lookup.
        tombstone_deadline = now + self.result_ttl_seconds
        connection.execute("""UPDATE requests SET status='failed', student_payload=NULL,
            courses_payload=NULL, claim_token=NULL, result=NULL, error=?, http_status=410, expires_at=?
            WHERE status IN ('completed','failed') AND (error IS NULL OR error != ?)
              AND expires_at <= ?""", (expired, tombstone_deadline, expired, now))
        connection.execute("""UPDATE requests SET status='failed', student_payload=NULL,
            courses_payload=NULL, claim_token=NULL, result=NULL, error=?, http_status=410, expires_at=?
            WHERE status='pending' AND expires_at <= ?""", (expired, tombstone_deadline, now))
        # Processing timeouts first retain a 503 diagnostic for the result TTL.
        # Their later expiry transitions to a 410 tombstone, then deletion.
        connection.execute("""UPDATE requests SET status='failed', student_payload=NULL,
            courses_payload=NULL, claim_token=NULL, result=NULL, error=?, http_status=503, expires_at=?
            WHERE status='processing' AND expires_at <= ?""", (processing, now + self.result_ttl_seconds, now))

    @staticmethod
    def _row(connection, owner, request_id, *, required=True):
        row = connection.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            if not required:
                return None
        elif row["owner"] == owner:
            return row
        raise ApiError("REQUEST_NOT_FOUND", "Request identifier was not found.", status_code=404)

    def _state(self, row):
        received = [component for component in COMPONENTS if row[component + "_digest"] is not None]
        result = {"request_id": row["request_id"], "status": row["status"], "received": received,
                  "missing": [component for component in COMPONENTS if component not in received]}
        try:
            if row["result"] is not None:
                result["result"] = _decode(json.loads(row["result"]))
            if row["error"] is not None:
                result["error"] = _decode(json.loads(row["error"]))
                result["http_status"] = row["http_status"]
        except (ValueError, TypeError, IndexError, KeyError, RecursionError):
            raise self._unavailable() from None
        return result

    @staticmethod
    def _match(row, identity_digest, component, digest):
        if row["identity_digest"] != identity_digest:
            raise ApiError("REQUEST_IDENTITY_MISMATCH", "Request components identify different students, degrees or semesters.", status_code=409)
        previous = row[component + "_digest"]
        if previous is not None and previous != digest:
            raise ApiError("REQUEST_COMPONENT_CONFLICT", "An existing request component has different contents.", status_code=409)
        return previous is not None

    def lookup(self, owner, request_id):
        owner, request_id = self._owner(owner), validate_request_id(request_id)
        with self._transaction() as connection:
            self._expire(connection, self._now())
            return self._state(self._row(connection, owner, request_id))

    def replay(self, owner, request_id, component, payload):
        """Check an existing component without inserting or claiming new work."""
        owner, request_id, identity_digest, encoded, digest = self._input(owner, request_id, component, payload)
        with self._transaction() as connection:
            self._expire(connection, self._now())
            row = self._row(connection, owner, request_id, required=False)
            if row is None:
                return None
            present = self._match(row, identity_digest, component, digest)
            return self._state(row) if present or row["status"] != "pending" else None

    def submit(self, owner, request_id, component, payload):
        owner, request_id, identity_digest, encoded, digest = self._input(owner, request_id, component, payload)
        with self._transaction() as connection:
            now = self._now()
            self._expire(connection, now)
            row = self._row(connection, owner, request_id, required=False)
            if row is None:
                if connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= self.max_requests:
                    raise ApiError("REQUEST_STORE_FULL", "Request storage has reached its configured capacity.", status_code=503)
                connection.execute("""INSERT INTO requests
                    (request_id,owner,identity_digest,status,expires_at) VALUES (?,?,?,'pending',?)""",
                    (request_id, owner, identity_digest, now + self.pending_ttl_seconds))
                row = self._row(connection, owner, request_id)
            present = self._match(row, identity_digest, component, digest)
            if present or row["status"] != "pending":
                return {**self._state(row), "claimed": False}
            # Column names come solely from the fixed COMPONENTS allowlist.
            connection.execute(f"UPDATE requests SET {component}_payload=?, {component}_digest=? WHERE request_id=?",
                               (encoded, digest, request_id))
            row = self._row(connection, owner, request_id)
            if any(row[key + "_digest"] is None for key in COMPONENTS):
                return {**self._state(row), "claimed": False}
            try:
                components = {key: _decode(json.loads(row[key + "_payload"])) for key in COMPONENTS}
            except (ValueError, TypeError, IndexError, KeyError, RecursionError):
                raise self._unavailable() from None
            token = token_hex(32)
            connection.execute("""UPDATE requests SET status='processing', claim_token=?, expires_at=?,
                student_payload=NULL, courses_payload=NULL WHERE request_id=?""",
                (token, now + self.processing_ttl_seconds, request_id))
            return {**self._state(self._row(connection, owner, request_id)), "claimed": True,
                    "claim_token": token, "components": components}

    def _finish(self, owner, request_id, claim_token, value, *, http_status=None):
        owner, request_id = self._owner(owner), validate_request_id(request_id)
        with self._transaction() as connection:
            now = self._now()
            self._expire(connection, now)
            row = self._row(connection, owner, request_id)
            if row["status"] in {"completed", "failed"}:
                return self._state(row)
            if (row["status"] != "processing" or not isinstance(claim_token, str)
                    or not compare_digest(row["claim_token"] or "", claim_token)):
                raise ApiError("REQUEST_CLAIM_CONFLICT", "Request completion does not match the active claim.", status_code=409)
            try:
                encoded = self._payload(value)
            except ApiError:
                encoded = self._safe_error("REQUEST_RESULT_TOO_LARGE", "Recommendation result cannot be retained within the configured storage limit.")
                http_status = 413
            completed = http_status is None
            connection.execute("""UPDATE requests SET status=?, result=?, error=?, http_status=?,
                claim_token=NULL, student_payload=NULL, courses_payload=NULL, expires_at=? WHERE request_id=?""",
                ("completed" if completed else "failed", encoded if completed else None,
                 None if completed else encoded, http_status, now + self.result_ttl_seconds, request_id))
            return self._state(self._row(connection, owner, request_id))

    def complete(self, owner, request_id, claim_token, result):
        return self._finish(owner, request_id, claim_token, result)

    def fail(self, owner, request_id, claim_token, error, http_status=422):
        if isinstance(http_status, bool) or not isinstance(http_status, int) or not 400 <= http_status <= 599:
            raise ValueError("A valid HTTP error status is required.")
        return self._finish(owner, request_id, claim_token, error, http_status=http_status)
