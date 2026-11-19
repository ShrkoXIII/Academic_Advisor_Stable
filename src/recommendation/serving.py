"""Serving compatibility and request-owned frozen history selection."""
from copy import deepcopy
from dataclasses import dataclass

from .history_update import HistorySnapshot
from .ranking_policy import validate_ranking_policy


def validate_pareto_serving_policy(artifacts):
    """Require the serving service's approved Pareto policy for both stages."""
    policy = validate_ranking_policy(artifacts.manifest, require_approved=True)
    if any(policy[key] != {"name": "pareto", "version": "v1"} for key in
           ("stage1_shortlist_strategy", "final_ranking_strategy")):
        raise ValueError("SERVING_POLICY_INCOMPATIBLE")


def validate_serving_history_compatibility(artifacts, state, metadata):
    """Check candidate activation against loaded models and the frozen cutoff."""
    if artifacts is None:
        raise ValueError("SERVING_ARTIFACTS_UNAVAILABLE")
    validate_pareto_serving_policy(artifacts)
    for stage in artifacts.manifest["stages"].values():
        columns = stage["feature_contract"]["model_features"]
        if any("specialty_history" in column or "degree_history" in column for column in columns):
            raise ValueError("SPECIALTY_HISTORY_AGGREGATES_UNAVAILABLE")
    if state.as_of_part != metadata.get("as_of_part"):
        raise ValueError("SERVING_HISTORY_INCOMPATIBLE")


@dataclass(frozen=True)
class PinnedServingHistory:
    snapshot: HistorySnapshot
    skipped_bundles: tuple


def pin_serving_history(manager, *, target_part, history_as_of_part=None, allow_older_history=None):
    """Capture history and its loader diagnostics from the same manager."""
    if history_as_of_part is None and allow_older_history is None:
        snapshot = manager.capture(target_part=target_part)
    else:
        snapshot = manager.capture(target_part=target_part, history_as_of_part=history_as_of_part,
                                   allow_older_history=allow_older_history)
    return PinnedServingHistory(snapshot, deepcopy(getattr(manager, "skipped_bundles", ())))
