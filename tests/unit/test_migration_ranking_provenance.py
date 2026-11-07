"""A preserved-policy approval uses current migration evidence, never old signatures."""
from copy import deepcopy

import pytest

from src.recommendation.ranking_policy import APPROVED_RANKING, validate_ranking_policy
from tests.unit.test_two_stage_activation import approved_policy


def test_preserved_policy_accepts_current_migration_contract_evidence():
    policy = approved_policy()
    policy["human_approval"].update(
        basis="stable_migration", source="Explicit user request to preserve approved business logic",
        evidence={"migration_contract": {"path": "docs/api_contract.md", "sha256": "a" * 64}},
    )
    manifest = {"ranking_approval": deepcopy(APPROVED_RANKING), "ranking_policy": policy}
    assert validate_ranking_policy(manifest, require_approved=True) == policy
    policy["human_approval"]["source"] = ""
    with pytest.raises(ValueError):
        validate_ranking_policy(manifest, require_approved=True)
