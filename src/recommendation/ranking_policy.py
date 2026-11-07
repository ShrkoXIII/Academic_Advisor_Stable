"""Manifest approval contracts; no inference, search, report reads or approval creation."""
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
import json
from pathlib import PurePosixPath
import re

from .balance_policy import B_OBSERVED_MIDDLE_V1
from .ranking import RankingStrategy


UNAPPROVED_RANKING = {
    "stage1_shortlist_strategy": "UNAPPROVED",
    "final_ranking_strategy": "UNAPPROVED", "combination": "UNAPPROVED",
}
APPROVED_RANKING = {key: "APPROVED" for key in UNAPPROVED_RANKING}
UNRESOLVED_OPERATIONAL_CONTRACTS = {
    "backend_max_candidate_count": "UNRESOLVED",
    "recommendation_latency_sla": "UNRESOLVED", "memory_budget_per_request": "UNRESOLVED",
}


def balance_policy_contract():
    """Pin exact approved Balance fractions and scope without report dependencies."""
    policy = B_OBSERVED_MIDDLE_V1
    return {
        "version": policy.version, "scope_rule": "academic_reference_slots_v1",
        **{f"{name}_band": [str(value) for value in getattr(policy, f"{name}_band")]
           for name in ("failed", "withdrawn", "total_previous")},
        "semesters": list(policy.semesters), "min_credits": policy.min_credits,
        "max_credits": policy.max_credits, "other_previous_selected": "disable_scope",
        "unavailable_component": "disabled_not_zero",
    }


def validate_ranking_policy(manifest, *, require_approved=False):
    """Return an independent approved policy snapshot, or None for legacy evaluation.

    The deployed manifest is the trusted approval record. Archived evidence hashes
    identify the reviewed bytes; serving does not require the report files. This
    validates recorded human decisions, never grants approval or chooses defaults.
    """
    try:
        if not isinstance(manifest, Mapping):
            raise ValueError("Ranking activation requires a manifest mapping.")
        approvals = manifest.get("ranking_approval")
        if approvals == UNAPPROVED_RANKING:
            if require_approved or "ranking_policy" in manifest:
                raise ValueError("Ranking activation requires complete human approval.")
            return None
        if approvals != APPROVED_RANKING:
            raise ValueError("All three independent approvals are required for production ranking activation.")
        policy = manifest["ranking_policy"]
        if (not isinstance(policy, Mapping) or set(policy) != {
                "schema_version", "stage1_shortlist_strategy", "final_ranking_strategy",
                "approved_combination", "balance_policy", "human_approval", "operational_contracts"}
                or type(policy["schema_version"]) is not int or policy["schema_version"] != 1):
            raise ValueError("Unsupported ranking approval policy schema.")
        combination = {}
        for key, stage in (("stage1_shortlist_strategy", "stage1"), ("final_ranking_strategy", "final")):
            identity = policy[key]
            if not isinstance(identity, Mapping) or set(identity) != {"name", "version"}:
                raise ValueError("Ranking approval requires separate name/version identities.")
            strategy = RankingStrategy(stage=stage, name=identity["name"])
            if identity["version"] != strategy.version:
                raise ValueError("Unsupported approved ranking strategy version.")
            combination[key] = dict(identity)
        if policy["approved_combination"] != combination:
            raise ValueError("Approved combination does not match the independent strategy approvals.")
        # JSON comparison distinguishes booleans from numeric scope parameters.
        if json.dumps(policy["balance_policy"], sort_keys=True, allow_nan=False) != json.dumps(balance_policy_contract(), sort_keys=True):
            raise ValueError("Approved Balance parameters or scope disagree with the implementation.")
        if policy["operational_contracts"] != UNRESOLVED_OPERATIONAL_CONTRACTS:
            raise ValueError("Operational contracts remain UNRESOLVED; no limits were approved.")
        approval = policy["human_approval"]
        if (approval["authority"] != "human_user" or approval["basis"] not in {"corrected_phase6", "stable_migration"}
                or not isinstance(approval["source"], str) or not approval["source"].strip()):
            raise ValueError("Explicit human approval with a supported provenance basis is required.")
        date.fromisoformat(approval["date"])
        for key in ("rationale", "limitations"):
            values = approval[key]
            if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError("Human approval must record rationale and limitations.")
        evidence = approval["evidence"]
        if not isinstance(evidence, Mapping) or not evidence:
            raise ValueError("Corrected Phase 6 evidence hashes are required.")
        for entry in evidence.values():
            path = entry["path"]
            valid_evidence_path = (isinstance(path, str) and (
                path == "docs/api_contract.md" if approval["basis"] == "stable_migration"
                else path.startswith("reports/two_stage_phase6/corrected/")))
            if (not valid_evidence_path
                    or "\\" in path or ".." in PurePosixPath(path).parts
                    or not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None):
                raise ValueError("Corrected approval evidence requires relative paths and SHA-256 hashes.")
        return deepcopy(dict(policy))
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Incomplete ranking activation approval contract.") from exc
