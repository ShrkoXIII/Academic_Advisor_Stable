"""Read-only aggregate, finalization, and history lineage validation."""
from src.recommendation.history_update import DELTA_ID_COLUMNS, normalize_history_delta

from .common import ApiError, identifier, part


def validate_delta_rows(request):
    cutoff = part(request.get("part_id"))
    rows = request.get("rows")
    if not isinstance(rows, list):
        raise ApiError("INVALID_DELTA", "Aggregate rows are required.")
    for row in rows:
        if not isinstance(row, dict):
            raise ApiError("INVALID_DELTA", "Aggregate rows must be records.")
        for key in DELTA_ID_COLUMNS:
            identifier(row.get(key), key)
    return cutoff, rows


def validate_delta_contract(payload):
    """Delegate aggregate semantics and canonical hash to the existing core."""
    try:
        return normalize_history_delta(payload, require_finalized=False)
    except ValueError:
        raise ApiError("INVALID_DELTA", "Aggregate schema or sums violate the history contract.") from None


def validate_finalization(request, cutoff):
    proof = request.get("finalization")
    if proof is None:
        return False
    if not isinstance(proof, dict) or part(proof.get("finalized_part_id")) != cutoff:
        raise ApiError("FINALIZATION_CONFLICT", "Finalization attestation must identify this semester.")
    identifier(proof.get("approval_reference"), "approval_reference")
    return True


def validate_delta_lineage(manager, payload):
    """Preview recorded lineage without publishing or activating history."""
    try:
        return manager.preview_delta(history_payload=payload)
    except ValueError:
        raise ApiError("DELTA_CONFLICT", "Delta conflicts with recorded lineage or semester order.", status_code=409) from None
