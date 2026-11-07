"""Phase 5 integration contracts over synthetic payloads and isolated history."""
import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from threading import Event

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.features.feature_contract import BASE_FEATURES, prepare_model_matrix
from src.features.temporal_features import COURSE_HISTORY_COLUMNS, PLAN_CONTEXT_COLUMNS
from src.recommendation.history_update import FrozenHistoryManager
from src.recommendation.inputs import prepare_recommendation_payloads
from src.recommendation.plan_generation import build_plan_rows
from src.recommendation.ranking import RankingStrategy
from tests.unit.recommendation_fixtures import synthetic_components
from tests.unit.two_stage_fixtures import (
    RecordingStageModel, evaluation_engine, history_manager, new_history_delta,
    ready_payloads, synthetic_artifacts,
)


def engine_api():
    assert importlib.util.find_spec("src.recommendation.two_stage_engine") is not None, (
        "Phase 5 needs the two-stage orchestration module"
    )
    return importlib.import_module("src.recommendation.two_stage_engine")


def test_two_stage_orchestration_has_an_explicit_evaluation_entrypoint():
    engine = engine_api().TwoStagePlanRecommender
    assert callable(engine.load_for_evaluation)
    assert callable(engine.recommend_from_payloads)


def recommend(engine, student=None, request=None, **kwargs):
    default_student, default_request = ready_payloads()
    return engine.recommend_from_payloads(
        student_payload=default_student if student is None else student,
        request_payload=default_request if request is None else request,
        **kwargs,
    )


def test_production_activation_refuses_unapproved_independent_strategies(tmp_path, monkeypatch):
    module = engine_api()
    artifacts = synthetic_artifacts()
    monkeypatch.setattr(module, "load_two_stage_artifacts", lambda **kwargs: artifacts)
    monkeypatch.setattr(FrozenHistoryManager, "load", lambda **kwargs: history_manager(tmp_path))
    with pytest.raises(ValueError, match="(?i)approv"):
        module.TwoStagePlanRecommender.load()


def test_evaluation_factory_loads_assets_and_history_once_for_reused_requests(tmp_path, monkeypatch):
    module = engine_api()
    artifacts, manager = synthetic_artifacts(), history_manager(tmp_path)
    calls = {"assets": 0, "history": 0}

    def load_assets(**kwargs):
        calls["assets"] += 1
        assert kwargs["project_root"] == tmp_path
        return artifacts

    def load_history(**kwargs):
        calls["history"] += 1
        assert kwargs["root"] == tmp_path
        return manager

    monkeypatch.setattr(module, "load_two_stage_artifacts", load_assets)
    monkeypatch.setattr(FrozenHistoryManager, "load", load_history)
    engine = module.TwoStagePlanRecommender.load_for_evaluation(
        project_root=tmp_path, history_root=tmp_path,
        stage1_shortlist_strategy=RankingStrategy(stage="stage1", name="balance_first"),
        final_ranking_strategy=RankingStrategy(stage="final", name="pareto"),
    )
    assert recommend(engine)["status"] == recommend(engine)["status"] == "ok"
    assert calls == {"assets": 1, "history": 1}


@pytest.mark.parametrize("stage1,final", [(None, "pareto"), ("balance_first", None)])
def test_evaluation_needs_two_explicit_stage_choices(tmp_path, stage1, final):
    module = engine_api()
    choices = {}
    if stage1 is not None:
        choices["stage1_shortlist_strategy"] = RankingStrategy(stage="stage1", name=stage1)
    if final is not None:
        choices["final_ranking_strategy"] = RankingStrategy(stage="final", name=final)
    with pytest.raises(TypeError):
        module.TwoStagePlanRecommender(synthetic_artifacts(), history_manager(tmp_path), **choices)


def test_stage_one_predicts_n_rows_once_before_plan_constraints(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads()
    request["allowed_failed_repeat_credits"] = 0
    result = recommend(engine, student, request)
    for model in (engine.artifacts.stage1.grade_model, engine.artifacts.stage1.fail_model):
        assert len(model.matrices) == 1
        assert len(model.matrices[0]) == 8
        assert len(model.matrices[0].columns) == 33
        assert model.matrices[0].columns.tolist() == [name for name in BASE_FEATURES if name not in PLAN_CONTEXT_COLUMNS]
        assert not set(PLAN_CONTEXT_COLUMNS) & set(model.matrices[0].columns)
        assert model.matrices[0].prior_fail_credit_ratio.tolist() == pytest.approx([.73] * 8)
        assert model.matrices[0].observed_gap_semesters.tolist() == [7] * 8
    assert result["metadata"]["candidate_count"] == 8
    assert result["metadata"]["stage1_row_count"] == 8
    assert all("C00" not in [row["course_id"] for row in plan["courses"]]
               for plan in result["recommendations"])


@pytest.mark.parametrize("version", [999, None, "invalid-version"])
@pytest.mark.parametrize("size", [0, 8])
def test_invalid_grade_version_is_rejected_before_any_inference(tmp_path, version, size):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=size)
    student["snapshot"]["grade_version_id"] = version
    with pytest.raises(ValueError) as exc:
        recommend(engine, student, request)
    assert "grade_version_id" in str(exc.value)
    assert repr(version) in str(exc.value)
    for pair in (engine.artifacts.stage1, engine.artifacts.stage2):
        assert pair.grade_model.matrices == []
        assert pair.fail_model.matrices == []


def test_missing_grade_version_field_is_rejected_before_any_inference(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads()
    student["snapshot"].pop("grade_version_id")
    with pytest.raises(ValueError, match="grade_version_id.*None"):
        recommend(engine, student, request)
    for pair in (engine.artifacts.stage1, engine.artifacts.stage2):
        assert pair.grade_model.matrices == []
        assert pair.fail_model.matrices == []


def test_only_explicitly_rejected_candidates_are_removed_before_stage_one(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads()
    student["candidates"][-1]["is_requestable"] = "N"
    student["candidates"][-2]["is_requestable"] = None
    result = recommend(engine, student, request)
    assert result["metadata"]["received_candidate_count"] == 8
    assert result["metadata"]["candidate_count"] == result["metadata"]["stage1_row_count"] == 7
    assert result["metadata"]["feasible_plan_count"] == 35
    assert len(engine.artifacts.stage1.grade_model.matrices[0]) == 7
    assert all("C07" not in [row["course_id"] for row in plan["courses"]]
               for plan in result["recommendations"])


def test_more_than_fifty_plans_only_scores_fifty_in_stage_two(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    result = recommend(engine, top_k=50)
    metadata = result["metadata"]
    assert metadata["feasible_plan_count"] == 70  # 8 choose 4, all explicit caps permit.
    assert metadata["shortlist_count"] == metadata["scored_plan_count"] == 50
    assert metadata["stage2_row_count"] == 200
    assert len(metadata["shortlist_plan_ids"]) == 50
    assert len(result["recommendations"]) == 50
    assert {plan["plan_id"] for plan in result["recommendations"]} == set(metadata["shortlist_plan_ids"])
    for model in (engine.artifacts.stage2.grade_model, engine.artifacts.stage2.fail_model):
        assert sum(len(frame) for frame in model.matrices) == 200
        assert all(frame.columns.tolist() == BASE_FEATURES for frame in model.matrices)
    assert metadata["global_top_k_guaranteed"] is False


def test_final_outputs_use_stage_two_predictions_and_backend_projection_denominator(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path,
                               grade1=95, fail1=.01, grade2=60, fail2=.2)
    result = recommend(engine)
    assert result["status"] == "ok"
    for plan in result["recommendations"]:
        assert plan["expected_quality_points"] == 24
        assert plan["expected_plan_gpa"] == 2
        assert plan["expected_failed_credits"] == pytest.approx(2.4)
        assert plan["projected_cumulative_gpa"] == pytest.approx((2.5 * 60 + 24) / 72)
        assert plan["expected_cumulative_gpa_gain"] == pytest.approx(-1 / 12)
        assert all(row["predicted_mark"] == 60 and row["expected_points"] == 2
                   and row["fail_probability"] == .2 for row in plan["courses"])


@pytest.mark.parametrize("stage,role", [("stage1", "grade"), ("stage1", "fail"),
                                      ("stage2", "grade"), ("stage2", "fail")])
@pytest.mark.parametrize("bad", ["column_vector", "scalar", "short", "nan", "infinity"])
def test_model_boundary_rejects_malformed_or_nonfinite_outputs(tmp_path, stage, role, bad):
    artifacts = synthetic_artifacts()
    model = getattr(getattr(artifacts, stage), f"{role}_model")
    responses = {
        "column_vector": lambda matrix: np.ones((len(matrix), 1)),
        "scalar": lambda matrix: np.asarray(.5),
        "short": lambda matrix: np.ones(max(0, len(matrix) - 1)),
        "nan": lambda matrix: np.full(len(matrix), np.nan),
        "infinity": lambda matrix: np.full(len(matrix), np.inf),
    }
    model.value = responses[bad]
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, artifacts=artifacts)
    with pytest.raises(ValueError):
        recommend(engine)


def test_prediction_clipping_applies_before_grade_scale_and_plan_aggregation(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path,
                               grade1=130, fail1=-.4, grade2=130, fail2=1.4)
    result = recommend(engine)
    for plan in result["recommendations"]:
        assert plan["expected_quality_points"] == 48
        assert plan["expected_failed_credits"] == 12
        assert all(row["predicted_mark"] == 100 and row["expected_points"] == 4
                   and row["fail_probability"] == 1 for row in plan["courses"])




def test_stage_two_fourteen_context_features_match_hand_calculated_zero_credit_plan(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=3)
    prepared = prepare_recommendation_payloads(student_payload=student, request_payload=request)
    rows = engine._prepare_candidates(prepared, engine.history_manager.capture(target_part=20251))
    rows["plan_id"] = "hand_calculated"
    rows["course_credits"] = [3., 2., 0.]
    rows["course_history_fail_rate"] = [.2, .6, .9]
    rows["course_history_avg_mark"] = [80., 60., 100.]
    rows["course_history_avg_attempt"] = [1., 2., 3.]
    actual = engine._score_stage2(rows)
    # Zero credits contribute counts and peer maxima, but no weighted load.
    expected = pd.DataFrame({
        "plan_course_count": [3, 3, 3], "plan_total_credits": [5., 5., 5.],
        "plan_credit_weighted_fail_rate": [.36, .36, .36],
        "plan_credit_weighted_avg_mark": [72., 72., 72.],
        "plan_credit_weighted_avg_attempt": [1.4, 1.4, 1.4],
        "plan_difficulty_credit_load": [1.8, 1.8, 1.8],
        "peer_course_count": [2, 2, 2], "peer_total_credits": [2., 3., 5.],
        "peer_credit_weighted_fail_rate": [.6, .2, .36],
        "peer_credit_weighted_avg_mark": [60., 80., 72.],
        "peer_credit_weighted_avg_attempt": [2., 1., 1.4],
        "peer_difficulty_credit_load": [1.2, .6, 1.8],
        "peer_max_fail_rate": [.9, .9, .6], "peer_difficulty_missing": [0, 0, 0],
    })
    np.testing.assert_allclose(actual[PLAN_CONTEXT_COLUMNS].to_numpy(), expected[PLAN_CONTEXT_COLUMNS].to_numpy(),
                               rtol=0, atol=1e-14)




def test_decimal_tenths_at_maximum_grade_points_are_feasible_and_scoreable(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, grade1=100, grade2=100)
    student, request = ready_payloads(size=2, credits=.1, target=.3)
    student["candidates"][1]["course_credits"] = .2
    result = recommend(engine, student, request)
    assert result["status"] == "ok"
    assert result["metadata"]["feasible_plan_count"] == 1
    plan = result["recommendations"][0]
    assert plan["total_credits"] == pytest.approx(.3)
    assert plan["expected_plan_gpa"] == pytest.approx(4)
    assert plan["projected_cumulative_gpa"] == pytest.approx((150 + 1.2) / 60.3)


def test_identity_shortlist_and_input_hash_are_stable_under_candidate_order(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads()
    original = deepcopy((student, request))
    first = recommend(engine, student, request)
    shuffled = deepcopy(student)
    shuffled["candidates"].reverse()
    second = recommend(engine, shuffled, request)
    assert first["metadata"]["input_sha256"] == second["metadata"]["input_sha256"]
    assert len(first["metadata"]["input_sha256"]) == 64
    assert first["metadata"]["shortlist_plan_ids"] == second["metadata"]["shortlist_plan_ids"]
    assert first["recommendations"] == second["recommendations"]
    assert (student, request) == original
    changed = deepcopy(student)
    changed["snapshot"]["current_gpa_credits"] = 61
    assert recommend(engine, changed, request)["metadata"]["input_sha256"] != first["metadata"]["input_sha256"]


def test_missing_history_values_have_a_json_safe_deterministic_fingerprint(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads()
    student["snapshot"].update(gpa_prev_1=None, gpa_prev_2=None)
    first = recommend(engine, student, request)
    second = recommend(engine, student, request)
    assert first["metadata"]["input_sha256"] == second["metadata"]["input_sha256"]
    json.dumps(first, allow_nan=False)


def test_result_provenance_has_model_category_scale_history_and_input_hashes(tmp_path):
    artifacts = synthetic_artifacts()
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, artifacts=artifacts)
    metadata = recommend(engine)["metadata"]
    for stage in ("stage1", "stage2"):
        entry = metadata["models"][stage]
        assert entry["models"]["grade"]["sha256"] == "1" * 64
        assert entry["models"]["fail"]["sha256"] == "2" * 64
        assert entry["category_levels"]["sha256"] == "3" * 64
        assert entry["feature_contract"]["feature_count"] == (33 if stage == "stage1" else 47)
    assert metadata["grade_scale_sha256"] == "4" * 64
    assert metadata["grade_scale_version"] == "sha256:" + "4" * 64
    assert len(metadata["history"]["artifact_sha256"]["course_history_state.pkl"]) == 64
    assert len(metadata["input_sha256"]) == 64
    assert metadata["ranking_approval"] == {
        "stage1_shortlist_strategy": "UNAPPROVED", "final_ranking_strategy": "UNAPPROVED",
        "combination": "UNAPPROVED",
    }


def test_returned_nested_metadata_cannot_change_later_requests_or_history(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    first = recommend(engine)
    first["metadata"]["models"]["stage1"]["models"]["grade"]["sha256"] = "tampered"
    first["metadata"]["history"]["artifact_sha256"]["course_history_state.pkl"] = "tampered"
    first["metadata"]["stage1_shortlist_strategy"]["approval_status"] = "APPROVED"
    first["metadata"]["shortlist_plan_ids"].clear()
    second = recommend(engine)
    assert second["metadata"]["models"]["stage1"]["models"]["grade"]["sha256"] == "1" * 64
    assert len(second["metadata"]["history"]["artifact_sha256"]["course_history_state.pkl"]) == 64
    assert second["metadata"]["stage1_shortlist_strategy"]["approval_status"] == "UNAPPROVED"
    assert second["metadata"]["shortlist_count"] == len(second["metadata"]["shortlist_plan_ids"]) == 50


@pytest.mark.parametrize("opaque", [object(), {1: "nonstring key"}, float("inf")])
def test_unsupported_opaque_metadata_is_rejected_without_nondeterministic_repr(tmp_path, opaque):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads()
    request["allowed_pass_position_type"] = opaque
    with pytest.raises(ValueError):
        recommend(engine, student, request)


@pytest.mark.parametrize("stage1,final", [("balance_first", "balance_first"), ("balance_first", "pareto"),
                                        ("pareto", "balance_first"), ("pareto", "pareto")])
def test_cross_stage_strategy_choices_remain_independent_in_result_metadata(tmp_path, stage1, final):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, stage1=stage1, final=final)
    result = recommend(engine)
    first = result["metadata"]["stage1_shortlist_strategy"]
    last = result["metadata"]["final_ranking_strategy"]
    assert (first["name"], first["stage"]) == (stage1, "stage1")
    assert (last["name"], last["stage"]) == (final, "final")
    assert first["approval_status"] == last["approval_status"] == "UNAPPROVED"
    assert first["usage"] == last["usage"] == "evaluation_only"


@pytest.mark.parametrize("top_k", [0, 51, -1, 1.5, True, None, "3"])
def test_top_k_must_be_an_integer_within_one_to_fifty(tmp_path, top_k):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    with pytest.raises(ValueError):
        recommend(engine, top_k=top_k)


def test_less_than_fifty_returns_available_plans_without_padding(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=5)
    result = recommend(engine, student, request, top_k=50)
    assert result["metadata"]["feasible_plan_count"] == 5
    assert result["metadata"]["shortlist_count"] == 5
    assert len(result["recommendations"]) == 5


def test_fractional_credits_keep_exact_feasibility_and_output_totals(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=5, credits=2.5, target=7.5)
    result = recommend(engine, student, request, top_k=50)
    assert result["metadata"]["feasible_plan_count"] == 10
    assert all(plan["total_credits"] == 7.5 and plan["course_count"] == 3
               for plan in result["recommendations"])


def test_optional_zero_course_preserves_two_identities_and_changes_plan_context(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=4)
    zero = deepcopy(student["candidates"][-1])
    zero.update(course_id="ZERO", course_name="Optional zero", course_credits=0,
                previous_course_status="OTHER", attempt_number=2)
    student["candidates"].append(zero)
    result = recommend(engine, student, request, top_k=50)
    assert result["metadata"]["feasible_plan_count"] == 2
    assert len({plan["plan_id"] for plan in result["recommendations"]}) == 2
    assert sorted(plan["course_count"] for plan in result["recommendations"]) == [4, 5]
    with_zero = next(plan for plan in result["recommendations"] if len(plan["courses"]) == 5)
    assert with_zero["total_credits"] == 12
    assert with_zero["scope_applicable"] is False
    matrices = engine.artifacts.stage2.grade_model.matrices
    assert set(pd.concat(matrices).plan_course_count) == {4., 5.}


def test_credit_range_uses_upper_exact_target_without_lower_fallback(tmp_path):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=3)
    request.pop("target_credits")
    request.update(min_credits=6, max_credits=12)
    result = recommend(engine, student, request)
    assert result["status"] == "no_feasible_plan"
    assert result["metadata"]["feasible_plan_count"] == 0


@pytest.mark.parametrize("empty", [False, True])
def test_no_feasible_plan_never_calls_stage_two(tmp_path, empty):
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path)
    student, request = ready_payloads(size=0 if empty else 3)
    result = recommend(engine, student, request)
    assert result["status"] == "no_feasible_plan"
    assert result["recommendations"] == []
    assert result["metadata"]["feasible_plan_count"] == result["metadata"]["shortlist_count"] == 0
    assert result["metadata"]["stage2_row_count"] == 0
    assert not engine.artifacts.stage2.grade_model.matrices
    assert not engine.artifacts.stage2.fail_model.matrices


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
@pytest.mark.parametrize("cutoff", [20251, 20252])
def test_current_or_future_training_cutoff_is_rejected_on_each_request(tmp_path, stage, cutoff):
    artifacts = synthetic_artifacts()
    artifacts.manifest["stages"][stage]["training_as_of_part"] = cutoff
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, artifacts=artifacts)
    with pytest.raises(ValueError, match="(?i)train|cutoff"):
        recommend(engine)


@pytest.mark.parametrize("cutoff", [20251, 20252])
def test_current_or_future_history_is_rejected(tmp_path, cutoff):
    manager = history_manager(tmp_path, part=cutoff)
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, manager=manager)
    with pytest.raises(ValueError):
        recommend(engine)


def test_older_finalized_history_is_accepted_and_age_is_explicit(tmp_path):
    manager = history_manager(tmp_path, part=20242)
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, manager=manager)
    result = recommend(engine)
    assert result["metadata"]["history"]["history_as_of_part"] == 20242
    assert result["metadata"]["history"]["history_is_stale"] is True


def test_request_retains_one_history_snapshot_during_atomic_update(tmp_path):
    entered, release = Event(), Event()

    def pause_after_capture(matrix):
        entered.set()
        assert release.wait(10), "Test failed to release deterministic Stage 1 barrier"
        return np.full(len(matrix), 95.)

    artifacts = synthetic_artifacts(grade1=pause_after_capture)
    manager = history_manager(tmp_path)
    original_snapshot = manager.capture(target_part=20252)
    original_files = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    engine = evaluation_engine(engine_api().TwoStagePlanRecommender, tmp_path, artifacts=artifacts, manager=manager)
    student, request = ready_payloads(part=20252)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(recommend, engine, student, request)
        try:
            assert entered.wait(10), "Stage 1 did not reach deterministic capture barrier"
            update = engine.update_history_from_payload(history_payload=new_history_delta())
            assert update["status"] == "applied"
            assert manager.capture(target_part=20252).as_of_part == 20251
        finally:
            release.set()
        result = future.result(timeout=10)
    assert result["metadata"]["history"]["history_as_of_part"] == 20243
    old_values = set(artifacts.stage1.grade_model.matrices[0].course_history_avg_mark)
    new_values = set(artifacts.stage2.grade_model.matrices[0].course_history_avg_mark)
    assert new_values <= old_values
    assert original_snapshot.as_of_part == 20243
    assert all(path.read_bytes() == content for path, content in original_files.items())
    assert recommend(engine, student, request)["metadata"]["history"]["history_as_of_part"] == 20251
    assert engine.update_history_from_payload(history_payload=new_history_delta())["status"] == "already_applied"


def test_engine_import_has_no_experiment_or_trainer_runtime_dependency(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = """
import builtins, importlib, sys
sys.path.insert(0, sys.argv[1])
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith(('src.experiments', 'src.modeling')):
        raise AssertionError('Serving attempted a forbidden dependency: ' + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
module = importlib.import_module('src.recommendation.two_stage_engine')
assert module.TwoStagePlanRecommender
assert not any(name.startswith(('src.experiments', 'src.modeling')) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script, str(root)], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
