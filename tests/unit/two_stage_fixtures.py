"""Synthetic Phase 5 models, ready payloads, and locally owned history bundles."""
from copy import deepcopy

import numpy as np
import pandas as pd

from src.features.feature_contract import FEATURE_ENGINEERING_VERSION
from src.features.frozen_history import save_frozen_history
from src.features.temporal_features import CourseHistoryState
from src.recommendation.history_update import FrozenHistoryManager
from src.recommendation.ranking import RankingStrategy
from src.recommendation.two_stage_artifacts import (
    ModelPair, PREDICTION_CONTRACT, TwoStageArtifacts, UNAPPROVED_RANKING,
    stage_feature_contract,
)
from tests.unit.recommendation_fixtures import synthetic_components, synthetic_grade_scale, synthetic_snapshot


class RecordingStageModel:
    """Deterministic inference double; malformed outputs can test model boundaries."""

    def __init__(self, value):
        self.value = value
        self.matrices = []

    def predict(self, matrix, **kwargs):
        self.matrices.append(matrix.copy())
        if callable(self.value):
            return self.value(matrix)
        return np.full(len(matrix), self.value, dtype=float)


def ready_payloads(size=8, *, credits=3, target=12, part=20251):
    snapshot = synthetic_snapshot()
    for key in ("gpa_trend_delta", "gpa_trend_missing"):
        snapshot.pop(key)
    snapshot.update(part_id=part, gpa_prev_1=3.0, gpa_prev_2=2.5,
                    current_gpa_credits=60, prior_total_reg_credits=999,
                    prior_fail_credit_ratio=.73, observed_gap_semesters=7)
    records = []
    for index in range(size):
        records.append({
            "course_id": f"C{index:02d}", "course_name": f"Synthetic Course {index}",
            "course_credits": credits, "attempt_number": 1 if index > 1 else 2,
            "plan_course_type_id": "T", "plan_requirement_type_id": "R",
            "plan_year_order": 1, "plan_semester_order": 1, "plan_credits_count": 120,
            "previous_course_status": "FAILED" if index == 0 else (
                "WITHDRAWN" if index == 1 else "NEW"),
        })
    request = {
        "student_id": "S", "degree_id": "D", "part_id": part,
        "target_credits": target, "allowed_failed_repeat_credits": target,
        "allowed_withdrawn_repeat_credits": target,
        "requirement_policies": [{"plan_requirement_type_id": "R", "max_credits": 120}],
    }
    return {"snapshot": snapshot, "candidates": records}, request


def history_state(*, part=20243, size=8):
    state = CourseHistoryState()
    records = []
    for index in range(size):
        for attempt in range(20):
            records.append({"part_id": part, "degree_id": "D", "faculty_id": "F",
                            "course_id": f"C{index:02d}", "course_credits": 3,
                            "plan_requirement_type_id": "R", "attempt_number": 1,
                            "final_mark": 35 + index * 8 + attempt % 2})
    state.update(pd.DataFrame(records))
    return state


def history_manager(root, *, part=20243, size=8):
    state = history_state(part=part, size=size)
    save_frozen_history(state, None, {
        "dataset_version": "V2", "source_min_part": part, "source_max_part": part,
        "source_row_count": size * 20, "source_part_counts": {str(part): size * 20},
        "finalized_through_part": part,
    }, root=root)
    return FrozenHistoryManager.load(root=root)


def synthetic_artifacts(*, grade1=95., fail1=.01, grade2=60., fail2=.2):
    levels = synthetic_components()[2]
    stages = {}
    for stage in ("stage1", "stage2"):
        stages[stage] = {
            "feature_contract": stage_feature_contract(stage), "training_as_of_part": 20243,
            "models": {
                "grade": {"sha256": "1" * 64, "path": f"models/synthetic/{stage}_grade.txt",
                          "target": "final_mark", "objective": "regression"},
                "fail": {"sha256": "2" * 64, "path": f"models/synthetic/{stage}_fail.txt",
                         "target": "is_fail", "target_definition": "final_mark < 50", "objective": "binary"},
            },
            "category_levels": {"levels": deepcopy(levels), "sha256": "3" * 64,
                                "path": f"models/synthetic/{stage}_levels.json"},
        }
    manifest = {
        "manifest_version": 1, "dataset_version": "V2",
        "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
        "prediction_contract": deepcopy(PREDICTION_CONTRACT),
        "ranking_approval": deepcopy(UNAPPROVED_RANKING), "stages": stages,
        "grade_scale": {"path": "data/synthetic/grade.parquet", "grade_scale_sha256": "4" * 64,
                        "grade_scale_version": "sha256:" + "4" * 64},
    }
    return TwoStageArtifacts(
        ModelPair(RecordingStageModel(grade1), RecordingStageModel(fail1), deepcopy(levels)),
        ModelPair(RecordingStageModel(grade2), RecordingStageModel(fail2), deepcopy(levels)),
        synthetic_grade_scale(), manifest,
    )


def evaluation_engine(engine_class, root, *, artifacts=None, manager=None,
                      stage1="balance_first", final="pareto", **model_values):
    return engine_class(
        synthetic_artifacts(**model_values) if artifacts is None else artifacts,
        history_manager(root) if manager is None else manager,
        stage1_shortlist_strategy=RankingStrategy(stage="stage1", name=stage1),
        final_ranking_strategy=RankingStrategy(stage="final", name=final),
    )


def new_history_delta(part=20251):
    return {"delta_part": part, "finalized": True, "aggregates": [
        {"degree_id": "D", "faculty_id": "F", "course_id": "C00",
         "plan_requirement_type_id": "R", "course_credits": 3,
         "count": 20, "fail_count": 0, "retake_count": 0,
         "mark_sum": 1800, "attempt_sum": 20},
    ]}
