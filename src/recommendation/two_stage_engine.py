"""Payload-driven 33 -> at most 50 -> 47 core with manifest-gated activation.

Production loads approved policies; evaluation choices remain explicit. No
Backend transport or local joins. Operational service limits remain unresolved.
"""
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json

import numpy as np
import pandas as pd

from src import paths
from src.features.feature_contract import FEATURE_ENGINEERING_VERSION
from src.features.temporal_features import (
    COURSE_HISTORY_COLUMNS, PLAN_CONTEXT_COLUMNS, compute_plan_context_features,
)
from .balance_policy import B_OBSERVED_MIDDLE_V1
from .history_update import FrozenHistoryManager
from .inputs import prepare_recommendation_payloads
from .plan_generation import build_plan_rows
from .plan_scoring import COURSE_OUTPUT_COLUMNS, SUMMARY_COLUMNS, score_course_rows, summarize_scored_plans
from .ranking import RankingStrategy, rank_evaluation_plans
from .ranking_policy import UNAPPROVED_RANKING, validate_ranking_policy
from .shortlist import SHORTLIST_LIMIT, build_stage1_shortlist
from .two_stage_artifacts import TwoStageArtifacts, load_two_stage_artifacts, stage_feature_contract


def _json_value(value):
    """Canonical JSON data, with explicit missing/Decimal handling and no repr()."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Metadata mapping keys must be strings.")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or value is pd.NA:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Metadata cannot contain non-finite Decimal values.")
        # Decimal.normalize() rounds through the ambient precision context.
        text = format(value, "f")
        text = text.rstrip("0").rstrip(".") if "." in text else text
        return "0" if value == 0 else text
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        if np.isnan(value):
            return None
        if not np.isfinite(value):
            raise ValueError("Metadata cannot contain infinite values.")
        return float(value)
    if isinstance(value, str):
        return value
    raise ValueError(f"Unsupported metadata value type: {type(value).__name__}.")


def _input_fingerprint(prepared, top_k):
    constraints = prepared.constraints
    document = {
        "fingerprint_version": "normalized_payload_v1", "top_k": top_k,
        "snapshot": prepared.snapshot, "candidates": prepared.candidates.to_dict("records"),
        "constraints": {
            "target_credits": constraints.target_credits,
            "requirement_policies": constraints.requirement_policies,
            "allowed_failed_repeat_credits": constraints.allowed_failed_repeat_credits,
            "allowed_withdrawn_repeat_credits": constraints.allowed_withdrawn_repeat_credits,
        }, "request_metadata": prepared.request_metadata,
    }
    if constraints.requirement_group_policies is not None:
        document["constraints"]["requirement_group_policies"] = constraints.requirement_group_policies
    if constraints.max_new_courses is not None:
        document["constraints"]["max_new_courses"] = constraints.max_new_courses
    canonical = json.dumps(_json_value(document), sort_keys=True, ensure_ascii=False,
                           allow_nan=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


class TwoStagePlanRecommender:
    """One loaded model bundle and one history manager; requests pin one snapshot.

    Explicit constructor injection is for evaluation/test assets. Ordinary callers
    use load for manifest-approved policy activation, or load_for_evaluation for
    explicit unapproved evaluation choices.
    """

    def __init__(self, artifacts, history_manager, *, stage1_shortlist_strategy,
                 final_ranking_strategy, num_threads=4):
        if not isinstance(artifacts, TwoStageArtifacts) or not isinstance(history_manager, FrozenHistoryManager):
            raise ValueError("Supply loaded TwoStageArtifacts and a FrozenHistoryManager.")
        for choice, stage in ((stage1_shortlist_strategy, "stage1"), (final_ranking_strategy, "final")):
            if not isinstance(choice, RankingStrategy) or choice.stage != stage:
                raise ValueError(f"Supply an explicit {stage} evaluation strategy.")
        if isinstance(num_threads, (bool, np.bool_)) or not isinstance(num_threads, (int, np.integer)) or num_threads < 1:
            raise ValueError("num_threads must be a positive integer.")
        self.artifacts, self.history_manager = artifacts, history_manager
        self.stage1_shortlist_strategy, self.final_ranking_strategy = stage1_shortlist_strategy, final_ranking_strategy
        self.num_threads = int(num_threads)
        self._manifest = deepcopy(artifacts.manifest)
        self._approved_policy = None

    @classmethod
    def load(cls, *, project_root=paths.PROJECT_ROOT, history_root=None, num_threads=4):
        """Load verified assets and history once, using only manifest-approved choices."""
        artifacts = load_two_stage_artifacts(project_root=project_root)
        validate_ranking_policy(artifacts.manifest, require_approved=True)
        manager = FrozenHistoryManager.load(root=history_root)
        return cls.from_loaded_artifacts(artifacts, manager, num_threads=num_threads)

    @classmethod
    def from_loaded_artifacts(cls, artifacts, manager, *, num_threads=4):
        """Bind independently loaded dependencies using the same approval gate."""
        policy = validate_ranking_policy(artifacts.manifest, require_approved=True)
        engine = cls(artifacts, manager,
                     stage1_shortlist_strategy=RankingStrategy(stage="stage1", name=policy["stage1_shortlist_strategy"]["name"]),
                     final_ranking_strategy=RankingStrategy(stage="final", name=policy["final_ranking_strategy"]["name"]),
                     num_threads=num_threads)
        engine._approved_policy = policy
        return engine

    def _ranking_metadata(self, stage1_strategy, final_strategy):
        """Keep evaluation unapproved; enforce and label the activated policy snapshot."""
        metadata = {"usage": "evaluation_only", "ranking_approval": deepcopy(UNAPPROVED_RANKING),
                    "production_ranking_strategy": "UNAPPROVED"}
        policy = self._approved_policy
        names = []
        for key, stage, strategy in (("stage1_shortlist_strategy", "stage1", stage1_strategy),
                                     ("final_ranking_strategy", "final", final_strategy)):
            if policy is not None and (not isinstance(strategy, RankingStrategy) or strategy.stage != stage):
                raise ValueError("Active strategy no longer matches the approved stage identity.")
            entry = strategy.metadata()
            if policy is not None:
                if {"name": strategy.name, "version": strategy.version} != policy[key]:
                    raise ValueError("Active strategy no longer matches the approved manifest policy.")
                entry.update(approval_status="APPROVED", usage="production_core")
                names.append(f"{strategy.name} {strategy.version}")
            metadata[key] = entry
        if policy is not None:
            canonical = json.dumps(policy, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            metadata.update(usage="production_core", ranking_approval=deepcopy(self._manifest["ranking_approval"]),
                            production_ranking_strategy=" -> ".join(names), ranking_policy=deepcopy(policy),
                            ranking_policy_sha256=sha256(canonical.encode("utf8")).hexdigest(),
                            operational_contracts=deepcopy(policy["operational_contracts"]))
        return metadata

    @classmethod
    def load_for_evaluation(cls, *, stage1_shortlist_strategy, final_ranking_strategy,
                            project_root=paths.PROJECT_ROOT, history_root=None, num_threads=4):
        """Load pinned models and latest valid history once; no approval override."""
        artifacts = load_two_stage_artifacts(project_root=project_root)
        manager = FrozenHistoryManager.load(root=history_root)
        return cls(artifacts, manager, stage1_shortlist_strategy=stage1_shortlist_strategy,
                   final_ranking_strategy=final_ranking_strategy, num_threads=num_threads)

    def update_history_from_payload(self, *, history_payload):
        """Delegate the independent immutable Delta publication path."""
        return self.history_manager.update_history_from_payload(history_payload=history_payload)

    def _prepare_candidates(self, prepared, history_snapshot):
        rows = prepared.candidates.copy()
        for column, value in prepared.snapshot.items():
            rows[column] = value
        if not rows.empty:
            history = history_snapshot.apply(rows)
            rows[COURSE_HISTORY_COLUMNS] = history[COURSE_HISTORY_COLUMNS].to_numpy()
        return rows

    def _score_stage2(self, rows):
        rows = rows.copy()
        # Exact credit search has already completed; numeric inference matches Local.
        rows["course_credits"] = pd.to_numeric(rows["course_credits"], errors="raise").astype(float)
        rows[PLAN_CONTEXT_COLUMNS] = compute_plan_context_features(rows, group_columns=["plan_id"]).to_numpy()
        pair = self.artifacts.stage2
        return score_course_rows(rows, pair.grade_model, pair.fail_model,
                                 pair.category_levels, self.artifacts.grade_scale,
                                 num_threads=self.num_threads)

    def recommend_from_payloads(self, *, student_payload, request_payload, top_k=3,
                               history_as_of_part=None, allow_older_history=None):
        """Return Stage 2 Top K inside the explicit Stage 1 shortlist, never global."""
        if isinstance(top_k, (bool, np.bool_)) or not isinstance(top_k, (int, np.integer)) or not 1 <= top_k <= SHORTLIST_LIMIT:
            raise ValueError("top_k must be an integer in 1..50.")
        top_k = int(top_k)
        stage1_strategy, final_strategy = self.stage1_shortlist_strategy, self.final_ranking_strategy
        ranking_metadata = self._ranking_metadata(stage1_strategy, final_strategy)
        if isinstance(student_payload, Mapping) and isinstance(student_payload.get("snapshot"), Mapping):
            self.artifacts.grade_scale.validate_versions([student_payload["snapshot"].get("grade_version_id")])
        prepared = prepare_recommendation_payloads(student_payload=student_payload, request_payload=request_payload)
        snapshot, constraints = prepared.snapshot, prepared.constraints
        target = snapshot["part_id"]
        if any(entry["training_as_of_part"] >= target for entry in self._manifest["stages"].values()):
            raise ValueError("Model training cutoff must precede the target semester.")
        input_sha256 = _input_fingerprint(prepared, top_k)
        if history_as_of_part is None and allow_older_history is None:
            history = self.history_manager.capture(target_part=target)
        else:
            history = self.history_manager.capture(target_part=target, history_as_of_part=history_as_of_part,
                                                   allow_older_history=allow_older_history)
        history_metadata = history.metadata_for_target(target)
        base = self._prepare_candidates(prepared, history)
        shortlist_ids, feasible_count, stage2_count = [], 0, 0
        recommendations = []
        if not base.empty:
            pair = self.artifacts.stage1
            scored_candidates = score_course_rows(
                base, pair.grade_model, pair.fail_model, pair.category_levels,
                self.artifacts.grade_scale, features=stage_feature_contract("stage1")["model_features"],
                num_threads=self.num_threads,
            )
            selection = build_stage1_shortlist(
                scored_candidates, constraints, stage1_shortlist_strategy=stage1_strategy,
                current_gpa=snapshot["start_agpa_points"], current_gpa_credits=snapshot["current_gpa_credits"],
                part_semester=snapshot["part_semester"],
            )
            feasible_count = len(selection.all_plans)
            shortlist_ids = selection.shortlist.plan_id.tolist()
            if shortlist_ids:
                rows = build_plan_rows(base, [selection.plan_indices[plan_id] for plan_id in shortlist_ids])
                rows["plan_id"] = rows.plan_id.map(dict(enumerate(shortlist_ids)))
                scored = self._score_stage2(rows)
                stage2_count = len(scored)
                summary = summarize_scored_plans(scored, snapshot["start_agpa_points"], snapshot["current_gpa_credits"])
                # Carry Balance/identity only; no Stage 1 prediction enters Final.
                balance_columns = [c for c in selection.shortlist if c not in SUMMARY_COLUMNS
                                   and c not in {"stage1_projected_cumulative_gpa", "pareto_front"}]
                summary = summary.merge(selection.shortlist[["plan_id", *balance_columns]],
                                        on="plan_id", validate="one_to_one")
                repeats = scored.candidate_group.ne("NEW").groupby(scored.plan_id).any()
                summary["projected_gpa_requires_repeat_policy"] |= summary.plan_id.map(repeats)
                ranked = rank_evaluation_plans(summary, strategy=final_strategy)
                for rank, record in enumerate(ranked.head(top_k).to_dict("records"), 1):
                    record["rank"] = rank
                    record["courses"] = scored.loc[scored.plan_id.eq(record["plan_id"]), COURSE_OUTPUT_COLUMNS].to_dict("records")
                    recommendations.append(_json_value(record))
        metadata = {
            **ranking_metadata, "dataset_version": "V2",
            "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
            "student_id": snapshot["student_id"], "degree_id": snapshot["degree_id"], "part_id": target,
            "input_fingerprint_version": "normalized_payload_v1", "input_sha256": input_sha256,
            "history": history_metadata, "skipped_history_bundles": deepcopy(self.history_manager.skipped_bundles),
            "manifest_version": self._manifest["manifest_version"],
            "models": {stage: {"models": entry["models"], "category_levels": {
                key: entry["category_levels"][key] for key in ("path", "sha256")},
                "training_as_of_part": entry["training_as_of_part"], "feature_contract": entry["feature_contract"]}
                for stage, entry in self._manifest["stages"].items()},
            **self._manifest["grade_scale"], "grade_model_target": "final_mark",
            "expected_points_method": "predicted_mark_to_grade_scale",
            "balance_policy_version": B_OBSERVED_MIDDLE_V1.version,
            "received_candidate_count": len(student_payload["candidates"]), "candidate_count": len(base),
            "stage1_row_count": len(base), "feasible_plan_count": feasible_count,
            "shortlist_count": len(shortlist_ids), "shortlist_limit": SHORTLIST_LIMIT,
            "shortlist_plan_ids": shortlist_ids, "scored_plan_count": len(shortlist_ids),
            "stage2_row_count": stage2_count, "returned_plan_count": len(recommendations), "top_k": top_k,
            "global_top_k_guaranteed": False, "credit_policy": "upper_bound_exact",
            "target_credits": constraints.target_credits,
            "requirement_remaining_credits": constraints.requirement_policies,
            "allowed_failed_repeat_credits": constraints.allowed_failed_repeat_credits,
            "allowed_withdrawn_repeat_credits": constraints.allowed_withdrawn_repeat_credits,
            "request_metadata": prepared.request_metadata,
            "current_gpa_credits": snapshot["current_gpa_credits"],
            "current_gpa_credits_source": "snapshot.current_gpa_credits",
            "projected_gpa_method": "standard_additive_without_repeat_replacement",
        }
        if constraints.requirement_group_policies is not None:
            metadata["requirement_group_remaining_credits"] = constraints.requirement_group_policies
        if constraints.max_new_courses is not None:
            metadata["max_new_courses"] = constraints.max_new_courses
        return {"status": "ok" if recommendations else "no_feasible_plan",
                "metadata": _json_value(metadata), "recommendations": recommendations}
