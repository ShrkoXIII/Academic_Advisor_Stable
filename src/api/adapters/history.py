"""Assemble history delta payloads and read-only diagnostic results."""
from ..validators.common import ApiError, ValidationResult
from ..validators.history import (
    validate_delta_contract, validate_delta_lineage, validate_delta_rows, validate_finalization,
)


def adapt_history_delta(request, *, manager=None):
    result = ValidationResult(checks={"aggregates": "unavailable", "lineage": "unavailable",
                                      "finalization": "unavailable"})
    try:
        cutoff, rows = validate_delta_rows(request)
        payload = {"delta_part": cutoff, "aggregates": rows}
        delta = validate_delta_contract(payload)
        result.checks["aggregates"] = "verified"
        if validate_finalization(request, cutoff):
            result.checks["finalization"] = "admin_attested"
            payload["finalized"] = True
        result.summary = {"delta_part": cutoff, "delta_sha256": delta.delta_sha256,
                          "row_count": len(delta.rows), "published": False, "activated": False}
        result.normalized = delta
        if manager is not None:
            preview = validate_delta_lineage(manager, payload)
            result.summary.update({key: preview[key] for key in
                                   ("status", "history_as_of_part", "base_history_sha256")})
            result.checks["lineage"] = "verified"
    except ApiError as error:
        result.add(error)
    return result
