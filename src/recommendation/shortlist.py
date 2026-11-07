"""Score all feasible plans from per-course Stage 1 predictions, then keep 50."""
from dataclasses import dataclass
from fractions import Fraction

import pandas as pd

from .balance_policy import compute_balance_components
from .constraints import enumerate_feasible_plan_indices
from .plan_scoring import SUMMARY_COLUMNS, project_cumulative_gpa
from .ranking import RankingStrategy, canonical_plan_identity, rank_evaluation_plans


SHORTLIST_LIMIT = 50


@dataclass(frozen=True)
class ShortlistResult:
    all_plans: pd.DataFrame
    shortlist: pd.DataFrame
    plan_indices: dict


def build_stage1_shortlist(scored_candidates, constraints, *, stage1_shortlist_strategy,
                           current_gpa, current_gpa_credits, part_semester):
    """No course preselection: hard constraints precede the explicit strategy.

    Search retains exact Decimal credits and optional zero-credit members.
    Prediction aggregation has no plan context or further model calls.
    """
    if not isinstance(stage1_shortlist_strategy, RankingStrategy) or stage1_shortlist_strategy.stage != "stage1":
        raise ValueError("Supply an explicit Stage 1 evaluation strategy.")
    records, indices_by_id = [], {}
    for indices in enumerate_feasible_plan_indices(scored_candidates, constraints):
        selected = scored_candidates.iloc[list(indices)]
        identity = canonical_plan_identity(selected.course_id)
        balance = compute_balance_components(selected, scored_candidates, part_semester=part_semester)
        credits = balance["total_credits"]
        quality = float(sum(Fraction(str(c)) * Fraction(str(p))
                            for c, p in zip(selected.course_credits, selected.expected_points)))
        failed = float(sum(Fraction(str(c)) * Fraction(str(p))
                           for c, p in zip(selected.course_credits, selected.fail_probability)))
        projected = float(project_cumulative_gpa(current_gpa, current_gpa_credits, quality, credits))
        records.append({
            "plan_id": identity.plan_id, "course_tuple": identity.course_tuple,
            "course_count": len(selected), **balance,
            "expected_quality_points": quality, "expected_failed_credits": failed,
            "expected_plan_gpa": quality / credits, "projected_cumulative_gpa": projected,
            "expected_cumulative_gpa_gain": projected - current_gpa,
            "is_expected_cumulative_improvement": projected > current_gpa,
            "projected_gpa_requires_repeat_policy": bool(selected.attempt_number.gt(1).any()
                or selected.candidate_group.ne("NEW").any()),
            "gpa_gain": quality / credits - current_gpa,
        })
        indices_by_id[identity.plan_id] = indices
    if records:
        all_plans = rank_evaluation_plans(pd.DataFrame(records), strategy=stage1_shortlist_strategy)
    else:
        all_plans = pd.DataFrame(columns=[*SUMMARY_COLUMNS, "course_tuple", "stage1_projected_cumulative_gpa"])
    return ShortlistResult(all_plans, all_plans.head(SHORTLIST_LIMIT).copy(), indices_by_id)
