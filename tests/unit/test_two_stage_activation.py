"""Phase 7 approval gates and activation parity; synthetic students only."""
from copy import deepcopy
import json

import numpy as np
import pytest

from src.recommendation import two_stage_engine as engine_module
from src import paths
from src.recommendation.ranking import RankingStrategy
from tests.unit.test_two_stage_artifacts import artifact_root, load, mutate_manifest, promote
from tests.unit.two_stage_fixtures import evaluation_engine, history_manager, ready_payloads, synthetic_artifacts


def approved_policy(stage1="pareto", final="pareto"):
    """Independent literal approval fixture, never a production approval writer."""
    first, last = {"name": stage1, "version": "v1"}, {"name": final, "version": "v1"}
    return {
        "schema_version": 1,
        "stage1_shortlist_strategy": first,
        "final_ranking_strategy": last,
        "approved_combination": {"stage1_shortlist_strategy": deepcopy(first),
                                 "final_ranking_strategy": deepcopy(last)},
        "balance_policy": {
            "version": "B_observed_middle_v1", "scope_rule": "academic_reference_slots_v1",
            "failed_band": ["1/6", "4/17"], "withdrawn_band": ["0", "3/17"],
            "total_previous_band": ["1/6", "2/7"], "semesters": [1, 2],
            "min_credits": 12, "max_credits": 18,
            "other_previous_selected": "disable_scope", "unavailable_component": "disabled_not_zero",
        },
        "human_approval": {
            "authority": "human_user", "basis": "corrected_phase6",
            "source": "Explicit HUMAN APPROVAL in this task", "date": "2026-10-08",
            "rationale": ["Retention and independent Balance objective"],
            "limitations": ["No latency, memory or candidate limits approved"],
            "evidence": {"corrected_result": {"path": "reports/two_stage_phase6/corrected/RESULT.md",
                                                "sha256": "a" * 64}},
        },
        "operational_contracts": {"backend_max_candidate_count": "UNRESOLVED",
                                  "recommendation_latency_sla": "UNRESOLVED",
                                  "memory_budget_per_request": "UNRESOLVED"},
    }


def approve_manifest(manifest, stage1="pareto", final="pareto"):
    manifest["ranking_approval"] = {"stage1_shortlist_strategy": "APPROVED",
                                    "final_ranking_strategy": "APPROVED", "combination": "APPROVED"}
    manifest["ranking_policy"] = approved_policy(stage1, final)


def production_engine(tmp_path, monkeypatch, *, stage1="pareto", final="pareto"):
    artifacts = synthetic_artifacts()
    approve_manifest(artifacts.manifest, stage1, final)
    manager = history_manager(tmp_path)
    monkeypatch.setattr(engine_module, "load_two_stage_artifacts", lambda **kwargs: artifacts)
    monkeypatch.setattr(engine_module.FrozenHistoryManager, "load", lambda **kwargs: manager)
    return engine_module.TwoStagePlanRecommender.load(), artifacts, manager


def recommend(engine):
    student, request = ready_payloads()
    return engine.recommend_from_payloads(student_payload=student, request_payload=request)


def test_verified_artifact_loader_accepts_complete_human_approval(artifact_root):
    promote(artifact_root)
    mutate_manifest(artifact_root, approve_manifest)
    bundle = load(artifact_root)
    assert bundle.stage1.grade_model.num_feature() == 33
    assert bundle.stage2.grade_model.num_feature() == 47
    assert bundle.manifest["ranking_policy"]["approved_combination"] == {
        "stage1_shortlist_strategy": {"name": "pareto", "version": "v1"},
        "final_ranking_strategy": {"name": "pareto", "version": "v1"},
    }


@pytest.mark.parametrize("change", [
    lambda m: m.pop("ranking_policy"),
    lambda m: m["ranking_approval"].update(combination="UNAPPROVED"),
    lambda m: m["ranking_policy"].update(schema_version=True),
    lambda m: m["ranking_policy"]["stage1_shortlist_strategy"].update(name="unknown"),
    lambda m: m["ranking_policy"]["final_ranking_strategy"].update(version="v2"),
    lambda m: m["ranking_policy"]["approved_combination"]["final_ranking_strategy"].update(name="balance_first"),
    lambda m: m["ranking_policy"]["balance_policy"].update(failed_band=["0", "1"]),
    lambda m: m["ranking_policy"]["balance_policy"].update(semesters=[1, 2, 3]),
    lambda m: m["ranking_policy"]["human_approval"].update(authority="automatic"),
    lambda m: m["ranking_policy"]["human_approval"].update(basis="old_phase6"),
    lambda m: m["ranking_policy"]["human_approval"].update(evidence={}),
    lambda m: m["ranking_policy"]["human_approval"]["evidence"]["corrected_result"].update(sha256="bad"),
    lambda m: m["ranking_policy"]["human_approval"]["evidence"]["corrected_result"].update(path="../outside.md"),
    lambda m: m["ranking_policy"]["operational_contracts"].update(backend_max_candidate_count=35),
])
def test_incomplete_or_inconsistent_approval_still_refuses_assets(artifact_root, change):
    promote(artifact_root)
    def mutate(manifest):
        approve_manifest(manifest)
        change(manifest)
    mutate_manifest(artifact_root, mutate)
    with pytest.raises(ValueError):
        load(artifact_root)


def test_approval_does_not_bypass_existing_feature_or_model_hash_checks(artifact_root):
    promote(artifact_root)
    mutate_manifest(artifact_root, approve_manifest)
    (artifact_root / "models/shortlist/grade_model.txt").write_text("tampered", encoding="utf8")
    with pytest.raises(ValueError, match="SHA-256"):
        load(artifact_root)


def test_approved_production_preserves_pareto_results_and_labels_actual_usage(tmp_path, monkeypatch):
    engine, artifacts, manager = production_engine(tmp_path, monkeypatch)
    evaluation = evaluation_engine(engine_module.TwoStagePlanRecommender, tmp_path,
                                   artifacts=artifacts, manager=manager, stage1="pareto", final="pareto")
    production, reference = recommend(engine), recommend(evaluation)
    assert production["recommendations"] == reference["recommendations"]
    assert production["metadata"]["shortlist_plan_ids"] == reference["metadata"]["shortlist_plan_ids"]
    metadata = production["metadata"]
    assert metadata["usage"] == "production_core"
    assert metadata["production_ranking_strategy"] == "pareto v1 -> pareto v1"
    assert metadata["ranking_approval"] == {
        "stage1_shortlist_strategy": "APPROVED", "final_ranking_strategy": "APPROVED", "combination": "APPROVED"}
    for key in ("stage1_shortlist_strategy", "final_ranking_strategy"):
        assert metadata[key]["name"] == "pareto"
        assert metadata[key]["version"] == "v1"
        assert metadata[key]["approval_status"] == "APPROVED"
        assert metadata[key]["usage"] == "production_core"
    assert metadata["operational_contracts"] == {
        "backend_max_candidate_count": "UNRESOLVED", "recommendation_latency_sla": "UNRESOLVED",
        "memory_budget_per_request": "UNRESOLVED"}
    assert metadata["global_top_k_guaranteed"] is False
    assert reference["metadata"]["usage"] == "evaluation_only"
    assert reference["metadata"]["production_ranking_strategy"] == "UNAPPROVED"
    assert reference["metadata"]["ranking_approval"]["combination"] == "UNAPPROVED"
    assert reference["metadata"]["final_ranking_strategy"]["approval_status"] == "UNAPPROVED"
    json.dumps(production, allow_nan=False)


def test_production_loads_once_then_is_deterministic_and_defends_approval_snapshot(tmp_path, monkeypatch):
    engine, artifacts, manager = production_engine(tmp_path, monkeypatch)
    first = recommend(engine)
    def unexpected_reload(**kwargs):
        raise AssertionError("Models/history must not reload between requests")
    monkeypatch.setattr(engine_module, "load_two_stage_artifacts", unexpected_reload)
    monkeypatch.setattr(engine_module.FrozenHistoryManager, "load", unexpected_reload)
    artifacts.manifest["ranking_policy"]["final_ranking_strategy"]["name"] = "balance_first"
    first["metadata"]["ranking_approval"]["combination"] = "UNAPPROVED"
    second = recommend(engine)
    assert second["metadata"]["final_ranking_strategy"]["name"] == "pareto"
    assert second["metadata"]["ranking_approval"]["combination"] == "APPROVED"
    assert first["recommendations"] == second["recommendations"]
    assert len(artifacts.stage1.grade_model.matrices) == 2
    assert all(len(matrix) == 8 and len(matrix.columns) == 33 for matrix in artifacts.stage1.grade_model.matrices)
    assert all(len(matrix) == 200 and len(matrix.columns) == 47 for matrix in artifacts.stage2.grade_model.matrices)


def test_production_does_not_allow_replacing_an_approved_strategy(tmp_path, monkeypatch):
    engine, _, _ = production_engine(tmp_path, monkeypatch)
    engine.final_ranking_strategy = RankingStrategy(stage="final", name="balance_first")
    with pytest.raises(ValueError, match="(?i)approv"):
        recommend(engine)


@pytest.mark.parametrize("replacement", [None, RankingStrategy(stage="stage1", name="pareto")])
def test_wrong_stage_or_missing_strategy_fails_before_any_inference(tmp_path, monkeypatch, replacement):
    engine, artifacts, _ = production_engine(tmp_path, monkeypatch)
    engine.final_ranking_strategy = replacement
    with pytest.raises(ValueError, match="(?i)approv"):
        recommend(engine)
    assert artifacts.stage1.grade_model.matrices == []
    assert artifacts.stage2.grade_model.matrices == []


def test_one_request_pins_both_approved_choices_despite_mid_request_replacement(tmp_path, monkeypatch):
    engine, artifacts, _ = production_engine(tmp_path, monkeypatch)
    seen = []
    actual_shortlist = engine_module.build_stage1_shortlist
    actual_rank = engine_module.rank_evaluation_plans
    def shortlist(*args, **kwargs):
        seen.append(("stage1", kwargs["stage1_shortlist_strategy"].name))
        return actual_shortlist(*args, **kwargs)
    def rank(*args, **kwargs):
        seen.append(("final", kwargs["strategy"].name))
        return actual_rank(*args, **kwargs)
    def replace_after_validation(matrix):
        engine.stage1_shortlist_strategy = RankingStrategy(stage="stage1", name="balance_first")
        engine.final_ranking_strategy = RankingStrategy(stage="final", name="balance_first")
        return np.full(len(matrix), 95.)
    artifacts.stage1.grade_model.value = replace_after_validation
    monkeypatch.setattr(engine_module, "build_stage1_shortlist", shortlist)
    monkeypatch.setattr(engine_module, "rank_evaluation_plans", rank)
    result = recommend(engine)
    assert seen == [("stage1", "pareto"), ("final", "pareto")]
    assert result["metadata"]["production_ranking_strategy"] == "pareto v1 -> pareto v1"
    with pytest.raises(ValueError, match="(?i)approv"):
        recommend(engine)


def test_unapproved_load_fails_before_history_loading(monkeypatch):
    monkeypatch.setattr(engine_module, "load_two_stage_artifacts", lambda **kwargs: synthetic_artifacts())
    def forbidden_history(**kwargs):
        raise AssertionError("Unapproved activation must stop before history load")
    monkeypatch.setattr(engine_module.FrozenHistoryManager, "load", forbidden_history)
    with pytest.raises(ValueError, match="(?i)approv"):
        engine_module.TwoStagePlanRecommender.load()


def test_manifest_choices_are_independent_without_changing_the_actual_human_approval(tmp_path, monkeypatch):
    # Synthetic contract only: proves activation never assumes both choices must match.
    engine, _, _ = production_engine(tmp_path, monkeypatch, stage1="balance_first", final="pareto")
    metadata = recommend(engine)["metadata"]
    assert metadata["stage1_shortlist_strategy"]["name"] == "balance_first"
    assert metadata["final_ranking_strategy"]["name"] == "pareto"
    assert metadata["production_ranking_strategy"] == "balance_first v1 -> pareto v1"


def test_pinned_approved_models_match_evaluation_on_known_grade_version_synthetic_payload(tmp_path):
    """Read actual model bytes; use fake student IDs and owned temporary history."""
    required = (paths.TWO_STAGE_MANIFEST_PATH, paths.SHORTLIST_GRADE_MODEL_PATH,
                paths.SHORTLIST_FAIL_MODEL_PATH, paths.GRADE_MODEL_PATH,
                paths.FAIL_MODEL_PATH, paths.SHORTLIST_CATEGORY_LEVELS_PATH,
                paths.CATEGORY_LEVELS_PATH, paths.MODEL_METADATA_PATH, paths.GRADE_SCALE_PATH)
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        pytest.skip("Pinned artifact activation unavailable: " + ", ".join(missing))
    history_manager(tmp_path)
    production = engine_module.TwoStagePlanRecommender.load(history_root=tmp_path, num_threads=1)
    evaluation = engine_module.TwoStagePlanRecommender(
        production.artifacts, production.history_manager,
        stage1_shortlist_strategy=RankingStrategy(stage="stage1", name="pareto"),
        final_ranking_strategy=RankingStrategy(stage="final", name="pareto"), num_threads=1)
    student, request = ready_payloads()
    student["snapshot"]["grade_version_id"] = 2.111
    assert 2.111 in production.artifacts.grade_scale.pass_bands.grade_version_id.to_list()
    for pair in (production.artifacts.stage1, production.artifacts.stage2):
        assert "2.111" in pair.category_levels["grade_version_id"]
    actual = production.recommend_from_payloads(student_payload=student, request_payload=request)
    reference = evaluation.recommend_from_payloads(student_payload=student, request_payload=request)
    assert actual["status"] == reference["status"] == "ok"
    assert actual["recommendations"] == reference["recommendations"]
    assert actual["metadata"]["shortlist_plan_ids"] == reference["metadata"]["shortlist_plan_ids"]
    assert actual["metadata"]["stage1_row_count"] == 8
    assert actual["metadata"]["stage2_row_count"] == 200
    assert actual["metadata"]["usage"] == "production_core"
    assert actual["metadata"]["production_ranking_strategy"] == "pareto v1 -> pareto v1"
