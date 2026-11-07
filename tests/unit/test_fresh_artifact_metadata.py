"""Fresh training selection is verified rather than pinned to an old winner."""
from copy import deepcopy

import pytest

from src.recommendation.two_stage_artifacts import validate_stage_metadata
from tests.unit.test_two_stage_artifacts import artifact_root, OFFICIAL_ARTIFACTS, read_json


def test_fresh_metadata_accepts_the_winner_of_its_recorded_validation(artifact_root):
    metadata = read_json(artifact_root / OFFICIAL_ARTIFACTS["model_metadata"])
    for section in ("grade_regressor", "fail_risk_classifier"):
        selected = {"candidate": {"name": "regularized_47"}, "mean_primary_metric": 0.5}
        metadata[section]["selected_candidate"] = selected
        metadata[section]["all_candidates"] = [
            {"candidate": {"name": "capacity_63"}, "mean_primary_metric": 1.0}, selected,
        ]
    assert validate_stage_metadata("stage2", metadata)[0] == 20243


def test_metadata_rejects_a_selection_outside_recorded_validation(artifact_root):
    metadata = read_json(artifact_root / OFFICIAL_ARTIFACTS["model_metadata"])
    for section in ("grade_regressor", "fail_risk_classifier"):
        selected = deepcopy(metadata[section]["selected_candidate"])
        selected["mean_primary_metric"] = 1.0
        metadata[section]["selected_candidate"] = selected
        metadata[section]["all_candidates"] = [
            {"candidate": {"name": "regularized_47"}, "mean_primary_metric": 0.5},
        ]
    with pytest.raises(ValueError, match="candidate mismatch"):
        validate_stage_metadata("stage2", metadata)
