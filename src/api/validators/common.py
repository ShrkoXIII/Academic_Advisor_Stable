"""Safe diagnostics and strict source validation, independent of model loading."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping
import math

from src.paths import academic_part


class ApiError(ValueError):
    def __init__(self, code, message, *, field=None, component="input", status_code=422, details=None):
        self.status_code = status_code
        self.issue = {"code": code, "message": message, "component": component}
        if field is not None:
            self.issue["field"] = field
        if details is not None:
            self.issue["details"] = details
        super().__init__(message)


def identifier(value, field):
    if not isinstance(value, str) or not value.strip() or value.strip().lower() in {"null", "none", "nan"}:
        raise ApiError("INVALID_ID", "A nonempty string identifier is required.", field=field)
    return value.strip()


def number(value, field, *, integer=False, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or value is None:
        raise ApiError("INVALID_NUMBER", "A finite nonnegative numeric value is required.", field=field)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ApiError("INVALID_NUMBER", "A finite nonnegative numeric value is required.", field=field) from None
    if (not result.is_finite() or result < 0 or not math.isfinite(float(result))
            or (integer and result != result.to_integral_value())):
        raise ApiError("INVALID_NUMBER", "Invalid numeric value or integer count.", field=field)
    return int(result) if integer else result


def part(value, field="part_id"):
    result = number(value, field, integer=True)
    try:
        return academic_part(result)
    except ValueError:
        raise ApiError("INVALID_SEMESTER", "A five-digit academic semester is required.", field=field) from None


def response_data(payload, component):
    if not isinstance(payload, Mapping) or payload.get("success") is not True or not isinstance(payload.get("data"), Mapping):
        raise ApiError("INVALID_BACKEND_RESPONSE", "A successful backend response with data is required.", component=component)
    return payload["data"]


def identity(request):
    return {"student_id": identifier(request.get("student_id"), "student_id"),
            "degree_id": identifier(request.get("degree_id"), "degree_id"), "part_id": part(request.get("part_id"))}


def check_record_identity(record, expected, *, historical=False, required=False):
    for key, aliases in {"student_id": ("STUDENT_ID", "student_id"),
                         "degree_id": ("DEGREE_ID", "degree_id"),
                         "part_id": ("STATUS_SEMESTER_ID", "PART_ID", "SEMESTER_ID", "part_id")}.items():
        present = [name for name in aliases if name in record]
        if required and not present:
            raise ApiError("MISSING_IDENTITY", "Required source identity is missing.", field=key)
        normalized = []
        for name in present:
            actual = part(record[name], name) if key == "part_id" else identifier(record[name], name)
            normalized.append(actual)
            matches = actual < expected[key] if historical and key == "part_id" else actual == expected[key]
            if not matches:
                raise ApiError("IDENTITY_MISMATCH", "Source identity or semester does not match the request.", field=name)
        if normalized and any(value != normalized[0] for value in normalized[1:]):
            raise ApiError("IDENTITY_MISMATCH", "Source identity aliases disagree.", field=key)


def binding(request, component):
    expected = identity(request)
    contexts = request.get("source_contexts")
    context = contexts.get(component) if isinstance(contexts, Mapping) else None
    if not isinstance(context, Mapping):
        raise ApiError("MISSING_SOURCE_CONTEXT", "PHP must bind each fetched response to its request identity.", component=component)
    check_record_identity(context, expected, required=True)
    return expected


def sourced(record, target_part, field):
    if (not isinstance(record, Mapping) or "value" not in record
            or not isinstance(record.get("source"), str) or not record["source"].strip()):
        raise ApiError("MISSING_PROVENANCE", "A value and authoritative source are required.", field=field)
    if part(record.get("as_of_part"), field + ".as_of_part") >= target_part:
        raise ApiError("FUTURE_SOURCE", "Supplemental information must precede the target semester.", field=field)
    return record["value"]


@dataclass
class ValidationResult:
    normalized: object = None
    errors: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    unavailable_fields: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    http_status: int = 200

    @property
    def status(self):
        if self.errors:
            return "invalid"
        return "partial" if self.unavailable_fields or "unavailable" in self.checks.values() else "valid"

    def add(self, error):
        self.errors.append(error.issue)
        self.http_status = max(self.http_status, error.status_code)

    def public(self):
        return {"validation_status": self.status, "validation_completed": self.status == "valid",
                "errors": self.errors, "checks": self.checks,
                "unavailable_fields": sorted(set(self.unavailable_fields)), "summary": self.summary}


def json_safe(value):
    """Encode credit Decimals without float conversion or sensitive repr output."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
