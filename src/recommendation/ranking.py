"""Explicit evaluation-only ranking candidates for independent two-stage choices.

No production strategy is selected or approved here. The legacy local scorer
is unchanged. Callers supply plan metrics derived from one stage's predictions
and project GPA via plan_scoring.project_cumulative_gpa with current_gpa_credits.
Stage 1 and Final may select different candidate strategies. Pareto is a complete
quadratic reference implementation for small-set evaluation; its serving cost
is intentionally left to the later benchmark/approval phases.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json

import numpy as np
import pandas as pd

from src.data.cleaning.cleaning_utils import clean_id
from .balance_policy import BALANCE_COMPONENTS


@dataclass(frozen=True)
class PlanIdentity:
    """Stable identity of selected courses, including optional zero-credit ones."""

    course_tuple: tuple
    canonical_json: str
    plan_id: str


def canonical_plan_identity(course_ids):
    """Normalize IDs as the payload adapter does; hash sorted canonical JSON."""
    if isinstance(course_ids, (str, bytes, Mapping)):
        raise ValueError("Supply a collection of course IDs.")
    values = list(course_ids)
    if not values or any(isinstance(value, (bool, np.bool_)) for value in values):
        raise ValueError("A plan needs non-boolean course IDs.")
    ids = clean_id(pd.Series(values))
    if ids.isna().any() or ids.duplicated().any():
        raise ValueError("A plan needs present, unique course IDs.")
    course_tuple = tuple(sorted(ids.tolist()))
    canonical_json = json.dumps(course_tuple, ensure_ascii=False, separators=(",", ":"))
    return PlanIdentity(course_tuple, canonical_json, sha256(canonical_json.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class RankingStrategy:
    """An immutable candidate choice, explicitly tied to one evaluation stage."""

    stage: str
    name: str
    version: str = field(default="v1", init=False)
    approval_status: str = field(default="UNAPPROVED", init=False)

    def __post_init__(self):
        if self.stage not in {"stage1", "final"} or self.name not in {"balance_first", "pareto"}:
            raise ValueError("Choose stage1/final and balance_first/pareto explicitly for evaluation.")

    def metadata(self):
        return {"stage": self.stage, "name": self.name, "version": self.version,
                "approval_status": self.approval_status,
                "usage": "evaluation_only", "scope_rule": "academic_reference_slots_v1"}


_ACADEMIC_COLUMNS = ("expected_quality_points", "expected_failed_credits",
                     "expected_plan_gpa", "projected_cumulative_gpa")


def _validated_rows(plans, *, with_balance):
    required = {"plan_id", "course_tuple", *_ACADEMIC_COLUMNS}
    if with_balance:
        required.update({"scope_applicable", "component_active_flags",
                         *(f"{name}_balance_penalty" for name in BALANCE_COMPONENTS)})
    if not isinstance(plans, pd.DataFrame) or not required.issubset(plans.columns):
        raise ValueError(f"Ranking needs plan metric columns: {sorted(required)}.")
    rows, seen = plans.to_dict("records"), set()
    for row in rows:
        identity = canonical_plan_identity(row["course_tuple"])
        if row["plan_id"] != identity.plan_id or identity.plan_id in seen:
            raise ValueError("Plan IDs must be unique canonical SHA-256 identities.")
        row["course_tuple"] = identity.course_tuple
        seen.add(identity.plan_id)
        for name in _ACADEMIC_COLUMNS:
            value = row[name]
            if isinstance(value, (bool, np.bool_)):
                raise ValueError(f"{name} must be numeric, not boolean.")
            try:
                numeric = float(value)
            except (ValueError, TypeError, OverflowError):
                raise ValueError(f"{name} must be finite and nonnegative.") from None
            if not np.isfinite(numeric) or numeric < 0 or (name.endswith("gpa") and numeric > 4):
                raise ValueError(f"{name} must be finite in its valid range.")
            row[name] = numeric
        if with_balance:
            if not isinstance(row["scope_applicable"], (bool, np.bool_)):
                raise ValueError("scope_applicable must be boolean.")
            flags = row["component_active_flags"]
            if (not isinstance(flags, Mapping) or set(flags) != set(BALANCE_COMPONENTS)
                    or any(not isinstance(value, (bool, np.bool_)) for value in flags.values())):
                raise ValueError("Supply boolean active flags for every Balance component.")
            if flags["total_previous"] != (flags["failed"] or flags["withdrawn"]):
                raise ValueError("Total-previous activation must match Failed or Withdrawn availability.")
            if not row["scope_applicable"] and any(flags.values()):
                raise ValueError("Out-of-scope plans cannot have active Balance components.")
            for name in BALANCE_COMPONENTS:
                key, value = f"{name}_balance_penalty", row[f"{name}_balance_penalty"]
                if flags[name]:
                    if isinstance(value, (bool, np.bool_)):
                        raise ValueError("Active penalties must be finite numeric distances.")
                    try:
                        numeric = float(value)
                    except (ValueError, TypeError, OverflowError):
                        raise ValueError("Active penalties must be finite numeric distances.") from None
                    if not np.isfinite(numeric) or not 0 <= numeric <= 1:
                        raise ValueError("Active penalties must be finite distances in [0, 1].")
                    row[key] = numeric
                elif not pd.isna(value):
                    raise ValueError("Disabled Balance penalties must be missing, not an ideal zero.")
    return rows


def _academic_key(row, stage):
    if stage == "stage1":
        return (-row["expected_quality_points"], row["expected_failed_credits"], row["course_tuple"])
    return (-row["projected_cumulative_gpa"], row["expected_failed_credits"],
            -row["expected_plan_gpa"], row["plan_id"])


def rank_academic_reference(plans, *, stage):
    """Diagnostic comparator only, never a selectable production fallback."""
    if stage not in {"stage1", "final"}:
        raise ValueError("Supply the academic reference stage explicitly.")
    rows = _validated_rows(plans, with_balance=False)
    order = sorted(range(len(rows)), key=lambda i: _academic_key(rows[i], stage))
    return plans.iloc[order].reset_index(drop=True).copy()


def _pareto_levels(rows, active_components):
    """Exact nondomination fronts over GPA, failed credits and each active penalty."""
    vectors = [(-row["projected_cumulative_gpa"], row["expected_failed_credits"],
                *(row[f"{name}_balance_penalty"] for name in active_components)) for row in rows]
    dominates = [[] for _ in rows]
    dominated_count = [0] * len(rows)
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = vectors[i], vectors[j]
            if all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b)):
                dominates[i].append(j)
                dominated_count[j] += 1
            elif all(y <= x for x, y in zip(a, b)) and any(y < x for x, y in zip(a, b)):
                dominates[j].append(i)
                dominated_count[i] += 1
    front = [i for i, count in enumerate(dominated_count) if count == 0]
    levels, level = {}, 0
    while front:
        next_front = []
        for i in front:
            levels[rows[i]["plan_id"]] = level
            for j in dominates[i]:
                dominated_count[j] -= 1
                if dominated_count[j] == 0:
                    next_front.append(j)
        front, level = next_front, level + 1
    return levels


def rank_evaluation_plans(plans, *, strategy):
    """Return a complete, deterministic candidate order with no implicit choice.

    Feasible plans outside Balance scope retain their academic-reference slots.
    Only the included plans are reordered inside the remaining slots. All rows
    must describe one request's candidate availability: component flags among
    in-scope rows must agree. Disabled dimensions never participate in sorting
    or dominance. No active components means the academic reference is retained.

    The caller can inspect any prefix; this function does not shortlist, score
    models or activate serving. Pareto fronts are followed by the complete
    Failed -> Total Previous -> Withdrawn -> academic -> identity key.
    """
    if not isinstance(strategy, RankingStrategy):
        raise ValueError("Supply an explicit evaluation RankingStrategy.")
    rows = _validated_rows(plans, with_balance=True)
    reference = sorted(range(len(rows)), key=lambda i: _academic_key(rows[i], strategy.stage))
    scoped = [i for i in reference if rows[i]["scope_applicable"]]
    signatures = {tuple(rows[i]["component_active_flags"][name] for name in BALANCE_COMPONENTS) for i in scoped}
    if len(signatures) > 1:
        raise ValueError("Plans must share one request's eligible-candidate availability flags.")
    active = [name for name, enabled in zip(BALANCE_COMPONENTS, next(iter(signatures), ())) if enabled]
    levels = _pareto_levels([rows[i] for i in scoped], active) if scoped and active and strategy.name == "pareto" else {}
    if active:
        def key(i):
            row = rows[i]
            front_key = (levels[row["plan_id"]],) if strategy.name == "pareto" else ()
            return (*front_key,
                    *(row[f"{name}_balance_penalty"] for name in active), *_academic_key(row, strategy.stage))

        included = iter(sorted(scoped, key=key))
        order = [next(included) if rows[i]["scope_applicable"] else i for i in reference]
    else:
        order = reference
    result = plans.iloc[order].reset_index(drop=True).copy()
    # Normalize the identity tuple without mutating caller-owned nested values.
    result["course_tuple"] = [rows[i]["course_tuple"] for i in order]
    if strategy.stage == "stage1":
        result["stage1_projected_cumulative_gpa"] = result["projected_cumulative_gpa"]
    if strategy.name == "pareto":
        result["pareto_front"] = pd.array([levels.get(rows[i]["plan_id"]) for i in order], dtype="Int64")
    result.attrs["ranking_strategy"] = strategy.metadata()
    return result
