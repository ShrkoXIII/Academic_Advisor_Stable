"""Read-only university API fetching + calls to the EXISTING Academic Advisor HTTP service.

No model imports, history arithmetic, or changes to the FastAPI application.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests


MAX_REMOTE_BYTES = 8 * 1024 * 1024


class ClientError(RuntimeError):
    """User-readable failure without credentials or raw private responses."""


def _reject_constant(value: str) -> None:
    raise ValueError("Nonfinite numbers are not valid JSON.")


def parse_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ClientError("الخدمة لم تُرجع JSON صالحاً.") from exc
    if not isinstance(data, dict):
        raise ClientError("رد الـAPI يجب أن يكون JSON object.")
    return data


def _wire_value(value: Any) -> Any:
    """Decimal values remain exact; API's documented numeric fields also accept strings."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ClientError("لا يمكن إرسال أرقام غير منتهية.")
        return str(value)
    if isinstance(value, dict):
        return {key: _wire_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_wire_value(item) for item in value]
    return value


def encode_json(value: Any) -> str:
    return json.dumps(_wire_value(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _env_headers() -> dict[str, str]:
    """Optional headers sent ONLY to upstream university/PHP APIs."""
    raw = os.getenv("ADVISOR_UI_BACKEND_HEADERS", "{}").strip()
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ClientError("ADVISOR_UI_BACKEND_HEADERS يجب أن يكون JSON object صالحاً.") from exc
    header_name = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
    forbidden = {"host", "content-length", "transfer-encoding", "connection", "content-type"}
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not header_name.fullmatch(key)
        or key.lower() in forbidden
        or not isinstance(item, str) or not item or any(ord(c) < 32 or ord(c) == 127 for c in item)
        for key, item in value.items()
    ) or len({k.lower() for k in value}) != len(value):
        raise ClientError("ADVISOR_UI_BACKEND_HEADERS يحتوي أسماء أو قيماً غير صالحة.")
    return value


def _env_map(name: str, default: str) -> dict[str, str]:
    raw = os.getenv(name, default)
    try:
        mapping = json.loads(raw)
    except ValueError as exc:
        raise ClientError(f"إعداد {name} ليس JSON صالحاً.") from exc
    if not isinstance(mapping, dict) or not mapping or any(
        key not in {"student_id", "degree_id", "part_id"}
        or not isinstance(value, str)
        or re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]*", value) is None
        for key, value in mapping.items()
    ) or len(set(mapping.values())) != len(mapping):
        raise ClientError(f"إعداد {name} يحتاج خريطة معاملات صحيحة وغير متكررة.")
    return mapping


def _valid_url(value: str, name: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ClientError(f"إعداد {name} يجب أن يكون رابطاً ثابتاً دون query أو بيانات دخول.")
    loopback = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if not parts.hostname or (parts.scheme != "https" and not (parts.scheme == "http" and loopback)):
        raise ClientError(f"إعداد {name} يحتاج HTTPS أو HTTP محلياً على loopback فقط.")
    return value.rstrip("/")


@dataclass(frozen=True)
class Config:
    fastapi_base: str
    student_url: str
    courses_url: str
    history_url: str
    student_params: dict[str, str]
    courses_params: dict[str, str]
    history_params: dict[str, str]
    history_method: str
    service_key: str
    admin_key: str
    upstream_bearer: str
    timeout: float
    context_file: Path | None
    upstream_headers: dict[str, str] = field(default_factory=dict)
    upstream_ca_bundle: Path | None = None
    dev_insecure_tls_host: str = ""  # DEV ONLY: upstream hostname allowed to skip TLS verification

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "Config":
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[2]
        default_env = root / ".env.local" if (root / ".env.local").is_file() else root / ".env"
        load_dotenv(dotenv_path=env_path or default_env, override=False)
        def project_file(value):
            candidate = Path(value).expanduser()
            return candidate if candidate.is_absolute() else Path(__file__).resolve().parents[2] / candidate
        context = os.getenv("ADVISOR_UI_INTEGRATION_CONTEXT_FILE", "").strip()
        certificate = os.getenv("ADVISOR_UI_BACKEND_CA_BUNDLE", "").strip()
        insecure_host = os.getenv("ADVISOR_UI_DEV_INSECURE_TLS_HOST", "").strip().lower()
        if insecure_host and (not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", insecure_host)
                              or ".." in insecure_host or insecure_host.startswith("-") or insecure_host.endswith("-")):
            raise ClientError("ADVISOR_UI_DEV_INSECURE_TLS_HOST يجب أن يكون اسم خادم واحداً فقط، دون https:// أو مسار.")
        if insecure_host and certificate:
            raise ClientError("لا تفعّل تجاوز شهادة HTTPS وملف CA في الوقت نفسه؛ اختر إعداداً واحداً.")
        ca_bundle = project_file(certificate).resolve() if certificate else None
        if ca_bundle is not None and not ca_bundle.is_file():
            raise ClientError("ملف شهادة neptune المحدد في ADVISOR_UI_BACKEND_CA_BUNDLE غير موجود أو ليس ملفاً.")
        if insecure_host:
            upstream_urls = [os.getenv(k, "") for k in (
                "ADVISOR_UI_STUDENT_API_URL", "ADVISOR_UI_COURSES_API_URL", "ADVISOR_UI_HISTORY_API_URL")]
            if insecure_host not in {urlsplit(u).hostname for u in upstream_urls if u}:
                raise ClientError("الخادم المحدد لتجاوز SSL غير موجود ضمن روابط APIs الجامعة في .env.")
            if insecure_host == urlsplit(os.getenv("ADVISOR_UI_FASTAPI_URL", "http://127.0.0.1:8000")).hostname:
                raise ClientError("لا يمكن تعطيل التحقق من HTTPS لخادم FastAPI المحلي.")
        try:
            timeout = float(os.getenv("ADVISOR_UI_HTTP_TIMEOUT", "20"))
        except ValueError as exc:
            raise ClientError("ADVISOR_UI_HTTP_TIMEOUT يجب أن يكون رقماً.") from exc
        if not 0 < timeout <= 300:
            raise ClientError("مهلة الاتصال يجب أن تكون بين صفر و300 ثانية.")
        method = os.getenv("ADVISOR_UI_HISTORY_METHOD", "GET").upper().strip()
        if method not in {"GET", "POST"}:
            raise ClientError("ADVISOR_UI_HISTORY_METHOD يجب أن تكون GET أو POST.")
        return cls(
            fastapi_base=_valid_url(os.getenv("ADVISOR_UI_FASTAPI_URL", "http://127.0.0.1:8000"), "ADVISOR_UI_FASTAPI_URL"),
            student_url=_valid_url(os.getenv("ADVISOR_UI_STUDENT_API_URL", ""), "ADVISOR_UI_STUDENT_API_URL"),
            courses_url=_valid_url(os.getenv("ADVISOR_UI_COURSES_API_URL", ""), "ADVISOR_UI_COURSES_API_URL"),
            history_url=_valid_url(os.getenv("ADVISOR_UI_HISTORY_API_URL", ""), "ADVISOR_UI_HISTORY_API_URL"),
            student_params=_env_map("ADVISOR_UI_STUDENT_PARAMS", '{"student_id":"studentId","part_id":"semesterId"}'),
            courses_params=_env_map("ADVISOR_UI_COURSES_PARAMS", '{"student_id":"studentId","degree_id":"degreeId","part_id":"semesterId"}'),
            history_params=_env_map("ADVISOR_UI_HISTORY_PARAMS", '{"part_id":"part_id"}'),
            history_method=method,
            service_key=os.getenv("ADVISOR_UI_SERVICE_KEY", os.getenv("ADVISOR_API_KEY", "")),
            admin_key=os.getenv("ADVISOR_UI_ADMIN_KEY", os.getenv("ADVISOR_ADMIN_API_KEY", "")),
            upstream_bearer=os.getenv("ADVISOR_UI_BACKEND_TOKEN", os.getenv("ADVISOR_BACKEND_TOKEN", "")),
            timeout=timeout,
            context_file=project_file(context) if context else None,
            upstream_headers=_env_headers(),
            upstream_ca_bundle=ca_bundle,
            dev_insecure_tls_host=insecure_host,
        )


def mapping_values(mapping: dict[str, str], *, student_id: str | None = None,
                   degree_id: str | None = None, part_id: int | None = None) -> dict[str, str]:
    values = {"student_id": student_id, "degree_id": degree_id, "part_id": part_id}
    missing = [key for key in mapping if values[key] is None or values[key] == ""]
    if missing:
        raise ClientError("معاملات غير متوفرة للرابط: " + ", ".join(missing))
    return {remote: str(values[key]) for key, remote in mapping.items()}


def previous_academic_part(value: int) -> int:
    # Same academic numbering contract as src.features.frozen_history.previous_academic_part.
    if value < 10001 or value % 10 not in (1, 2, 3):
        raise ClientError("part_id غير صالح؛ مثال 20262.")
    return value - 1 if value % 10 > 1 else (value // 10 - 1) * 10 + 3


def student_degree_id(response: dict[str, Any], student_id: str, part_id: int) -> str:
    data = response.get("data")
    info = data.get("studentDegreeInfo") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        raise ClientError("Student API لا يحتوي data.studentDegreeInfo.")
    if str(info.get("STUDENT_ID", "")) != student_id:
        raise ClientError("معرف الطالب في رد Student API لا يطابق المدخل.")
    if str(info.get("STATUS_SEMESTER_ID", "")) != str(part_id):
        raise ClientError("الفصل في رد Student API لا يطابق الفصل المطلوب.")
    degree_id = info.get("DEGREE_ID")
    if degree_id is None or not str(degree_id).strip():
        raise ClientError("Student API لا يحتوي DEGREE_ID.")
    return str(degree_id)


def load_context(config: Config) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.context_file is None:
        return {}, {}
    try:
        contents = parse_json(config.context_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ClientError("تعذر قراءة ملف integration_context المحدد في .env.") from exc
    if set(contents) - {"student", "courses"} or not all(
        isinstance(contents.get(key, {}), dict) for key in ("student", "courses")
    ):
        raise ClientError('ملف السياق يجب أن يكون {"student": {...}, "courses": {...}}.')
    return contents.get("student", {}), contents.get("courses", {})


def make_payloads(*, student_id: str, degree_id: str, part_id: int, cutoff: int,
                  student_response: dict, courses_response: dict,
                  student_context: dict, courses_context: dict,
                  target_credits: str, top_k: int, request_id: str | None = None) -> tuple[dict, dict]:
    request_id = request_id or uuid4().hex
    identity = {"student_id": student_id, "degree_id": degree_id, "part_id": part_id}
    student = {**identity, "request_id": request_id,
               "source_contexts": {"student": dict(identity)},
               "integration_context": student_context, "student_api_response": student_response,
               "recommendation": {"history_as_of_part": cutoff, "target_credits": target_credits,
                                  "top_k": top_k, "mode": "normal"}}
    courses = {**identity, "request_id": request_id,
               "source_contexts": {"courses": dict(identity)},
               "integration_context": courses_context, "courses_api_response": courses_response}
    return student, courses


class HttpClient:
    def __init__(self, config: Config, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.trust_env = False  # do not send credentials through ambient proxies

    def _call(self, method: str, url: str, *, params=None, data=None, upstream=False, admin=False,
              public_health=False, include_raw=False) -> tuple:
        headers = {"Accept": "application/json"}
        if upstream:
            headers.update(self.config.upstream_headers)
            if self.config.upstream_bearer:
                if any(k.lower() == "authorization" for k in self.config.upstream_headers):
                    raise ClientError("حدد Authorization داخل ADVISOR_UI_BACKEND_HEADERS أو استخدم ADVISOR_UI_BACKEND_TOKEN، وليس الاثنين.")
                headers["Authorization"] = "Bearer " + self.config.upstream_bearer
        if not upstream and not public_health:
            key = self.config.admin_key if admin else self.config.service_key
            if not key:
                raise ClientError("مفتاح FastAPI غير موجود في إعدادات .env.")
            headers["X-API-Key"] = key
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            # Local-development escape hatch for ONE explicitly named university host.
            # It never changes TLS verification for FastAPI or any other remote host.
            # IMPORTANT: the connection cannot authenticate the server when verify=False.
            verify = str(self.config.upstream_ca_bundle) if upstream and self.config.upstream_ca_bundle else True
            if (upstream and self.config.dev_insecure_tls_host
                    and urlsplit(url).hostname == self.config.dev_insecure_tls_host):
                verify = False
            with self.session.request(method, url, params=params, data=encode_json(data) if data is not None else None,
                                      headers=headers, timeout=self.config.timeout, allow_redirects=False,
                                      stream=True, verify=verify) as response:
                if 300 <= response.status_code < 400:
                    raise ClientError("تم رفض redirect لحماية روابط ومفاتيح API.")
                total, chunks = 0, []
                for piece in response.iter_content(chunk_size=65536):
                    total += len(piece)
                    if total > MAX_REMOTE_BYTES:
                        raise ClientError("رد الـAPI أكبر من 8 MiB؛ تم إيقاف القراءة.")
                    chunks.append(piece)
                text = b"".join(chunks).decode("utf-8-sig")
                parsed = parse_json(text)
                status = response.status_code
                safe_headers = {"X-Request-ID": response.headers.get("X-Request-ID", "")}
                return (status, parsed, safe_headers, b"".join(chunks)) if include_raw else (status, parsed, safe_headers)
        except requests.exceptions.Timeout as exc:
            raise ClientError("انتهت مهلة الاتصال بالـAPI؛ تحقق من تشغيل السيرفر والشبكة.") from exc
        except requests.exceptions.SSLError as exc:
            raise ClientError("فشل التحقق من شهادة HTTPS الخاصة بالـAPI. اطلب شهادة CA الموثوقة من مسؤول الشبكة وحدد مسارها في ADVISOR_UI_BACKEND_CA_BUNDLE.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise ClientError("تعذر فتح اتصال بالـAPI؛ تحقق من العنوان والمنفذ وأن السيرفر ما زال يعمل.") from exc
        except requests.RequestException as exc:
            raise ClientError("فشل طلب HTTP؛ تحقق من إعدادات الاتصال.") from exc

    def health(self) -> tuple[int, dict]:
        """Check the public FastAPI /health endpoint without requiring an API key."""
        if not self.config.fastapi_base:
            raise ClientError("عنوان FastAPI غير مضبوط في .env.")
        code, payload, _ = self._call("GET", self.config.fastapi_base + "/health", public_health=True)
        return code, payload

    def upstream_get(self, url: str, params: dict) -> dict:
        code, response, _ = self._call("GET", url, params=params, upstream=True)
        if not 200 <= code < 300:
            raise ClientError(f"مصدر الجامعة أعاد HTTP {code}.")
        if response.get("success") is False:
            raise ClientError("مصدر الجامعة أعاد success=false رغم نجاح HTTP.")
        return response

    def student(self, student_id: str, part_id: int) -> dict:
        if not self.config.student_url:
            raise ClientError("ADVISOR_UI_STUDENT_API_URL غير مضبوط في .env.")
        return self.upstream_get(self.config.student_url, mapping_values(self.config.student_params,
                                   student_id=student_id, part_id=part_id))

    def courses(self, student_id: str, degree_id: str, part_id: int) -> dict:
        if not self.config.courses_url:
            raise ClientError("ADVISOR_UI_COURSES_API_URL غير مضبوط في .env.")
        response = self.upstream_get(self.config.courses_url, mapping_values(self.config.courses_params,
                                     student_id=student_id, degree_id=degree_id, part_id=part_id))
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("availableCourses"), list) \
                or not isinstance(data.get("registserRule"), dict):
            raise ClientError("Courses API لم يرجع data.availableCourses وdata.registserRule بالشكل المتوقع.")
        return response

    def frozen_history(self, part_id: int) -> dict:
        if not self.config.history_url:
            raise ClientError("ADVISOR_UI_HISTORY_API_URL غير مضبوط في .env.")
        values = mapping_values(self.config.history_params, part_id=part_id)
        if self.config.history_method == "GET":
            response = self.upstream_get(self.config.history_url, values)
        else:
            code, response, _ = self._call("POST", self.config.history_url, data=values, upstream=True)
            if not 200 <= code < 300:
                raise ClientError(f"مصدر التاريخ أعاد HTTP {code}.")
        data = response.get("data", response)
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise ClientError("History API يجب أن يعيد part_id و rows[].")
        if str(data.get("part_id")) != str(part_id):
            raise ClientError("History API أعاد بيانات فصل مختلف عن الفصل المطلوب.")
        payload = {"part_id": part_id, "rows": data["rows"]}
        if "finalization" in data:
            payload["finalization"] = data["finalization"]
        return payload

    def advisor(self, method: str, path: str, *, data=None, admin=False) -> tuple[int, dict, dict]:
        if not path.startswith("/") or path.startswith("//"):
            raise ClientError("مسار FastAPI غير صالح.")
        return self._call(method, self.config.fastapi_base + path, data=data, admin=admin)

    def submit_pair(self, student_payload: dict, courses_payload: dict) -> list[tuple[str, int, dict]]:
        results = []
        for part, payload in (("student", student_payload), ("courses", courses_payload)):
            code, data, _ = self.advisor("POST", "/api/v1/recommendation-inputs/" + part, data=payload)
            results.append((part, code, data))
            if not 200 <= code < 300:
                break
        return results

    def capture_student(self, student_id: str, part_id: int) -> tuple[dict, bytes]:
        """Fetch and retain the exact original HTTP JSON body."""
        if not self.config.student_url:
            raise ClientError("Student API URL is missing.")
        status, response, _, body = self._call(
            "GET", self.config.student_url,
            params=mapping_values(self.config.student_params, student_id=student_id, part_id=part_id),
            upstream=True, include_raw=True,
        )
        if not 200 <= status < 300 or response.get("success") is False:
            raise ClientError(f"Student API returned unsuccessful HTTP {status}.")
        student_degree_id(response, student_id, part_id)
        return response, body

    def capture_courses(self, student_id: str, degree_id: str, part_id: int) -> tuple[dict, bytes]:
        if not self.config.courses_url:
            raise ClientError("Courses API URL is missing.")
        status, response, _, body = self._call(
            "GET", self.config.courses_url,
            params=mapping_values(self.config.courses_params, student_id=student_id, degree_id=degree_id, part_id=part_id),
            upstream=True, include_raw=True,
        )
        if not 200 <= status < 300 or response.get("success") is False:
            raise ClientError(f"Courses API returned unsuccessful HTTP {status}.")
        data = response.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('availableCourses'), list) or not isinstance(data.get('registserRule'), dict):
            raise ClientError("Courses API did not return expected data.availableCourses/registserRule.")
        return response, body

    def capture_history(self, part_id: int) -> tuple[dict, bytes, int]:
        """Raw archival fetch only: never commit, activate or normalize Frozen History."""
        if not self.config.history_url:
            raise ClientError("History API URL is missing.")
        values = mapping_values(self.config.history_params, part_id=part_id)
        if self.config.history_method == 'GET':
            status, response, _, body = self._call(
                'GET', self.config.history_url, params=values, upstream=True, include_raw=True)
        else:
            status, response, _, body = self._call(
                'POST', self.config.history_url, data=values, upstream=True, include_raw=True)
        if not 200 <= status < 300 or response.get('success') is False:
            raise ClientError(f"History API returned unsuccessful HTTP {status}.")
        data = response.get('data', response)
        if not isinstance(data, dict):
            raise ClientError('History API data must be an object.')
        rows = data.get('rows', data.get('CoursesStatistsic'))
        if not isinstance(rows, list):
            raise ClientError('History API should contain rows or CoursesStatistsic array.')
        if not rows:
            raise ClientError(f'History API returned no rows for part {part_id}; manual review required.')
        if any(not isinstance(row, dict) or str(row.get('PART_ID', row.get('part_id', part_id))) != str(part_id)
               for row in rows):
            raise ClientError('History API contains a different part_id or malformed rows.')
        envelope_part = data.get('part_id', data.get('PART_ID'))
        if envelope_part is not None and str(envelope_part) != str(part_id):
            raise ClientError('History API envelope part_id mismatch.')
        return response, body, len(rows)
