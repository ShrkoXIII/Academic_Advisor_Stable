"""Versioned soft Balance components; no feasibility rules, predictions, or I/O."""
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import pandas as pd

from src.data.cleaning.cleaning_utils import clean_id
from .constraints import _CANDIDATE_GROUPS, _credit_value


@dataclass(frozen=True)
class BalancePolicy:
    """Local policy values from the approved plan, independent of audit reports."""

    version: str = "B_observed_middle_v1"
    failed_band: tuple = (Fraction(1, 6), Fraction(4, 17))
    withdrawn_band: tuple = (Fraction(0), Fraction(3, 17))
    total_previous_band: tuple = (Fraction(1, 6), Fraction(2, 7))
    semesters: tuple = (1, 2)
    min_credits: int = 12
    max_credits: int = 18


B_OBSERVED_MIDDLE_V1 = BalancePolicy()
BALANCE_COMPONENTS = ("failed", "total_previous", "withdrawn")


def _course_records(frame):
    """Validate an already eligible/normalized set, preserving exact credits."""
    required = {"course_id", "course_credits", "candidate_group"}
    if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
        raise ValueError("Balance needs course_id, course_credits and official candidate_group.")
    if any(isinstance(value, (bool, np.bool_)) for value in frame["course_id"]):
        raise ValueError("Course IDs cannot be boolean.")
    ids = clean_id(frame["course_id"])
    if ids.isna().any() or ids.duplicated().any():
        raise ValueError("Balance course IDs must be present and unique.")
    records = {}
    for course_id, value, group in zip(ids, frame["course_credits"], frame["candidate_group"]):
        if group not in _CANDIDATE_GROUPS:
            raise ValueError("Balance requires official candidate_group values.")
        credits = _credit_value(value, "course_credits")
        if not np.isfinite(float(credits)):
            raise ValueError("Course credits must be representable as finite numbers.")
        records[str(course_id)] = (Fraction(credits), group)
    return records


def compute_balance_components(selected_courses, eligible_candidates, *, part_semester):
    """Describe one feasible plan relative to the full eligible candidate set.

    Inputs contain course_id/course_credits/candidate_group from the payload
    adapter. Availability means positive-credit *eligible candidates*, not the
    courses selected in this plan or the student's raw backlog. Ratios use the
    whole plan load; total_previous includes Failed+Withdrawn only. Any selected
    OTHER_PREVIOUS course, even at zero credits, disables the reference scope.

    Disabled penalties are None with reasons, never an ideal zero. Fractions
    keep the approved boundaries exact until JSON-safe numeric output. This
    function neither changes eligibility nor imposes minimum retake credits.
    """
    policy = B_OBSERVED_MIDDLE_V1
    semester = _credit_value(part_semester, "part_semester", positive=True)
    if semester != semester.to_integral_value():
        raise ValueError("part_semester must be an integer.")
    selected, eligible = _course_records(selected_courses), _course_records(eligible_candidates)
    if any(course_id not in eligible or eligible[course_id] != value for course_id, value in selected.items()):
        raise ValueError("Selected courses must match the eligible candidates' credits and groups.")
    totals = {group: Fraction(0) for group in _CANDIDATE_GROUPS}
    for credits, group in selected.values():
        totals[group] += credits
    total = sum(totals.values())
    try:
        total_number = float(total)
    except OverflowError:
        raise ValueError("Balance requires a positive finite plan load.") from None
    if total <= 0 or not np.isfinite(total_number):
        raise ValueError("Balance requires a positive finite plan load.")
    scope_reasons = []
    if int(semester) not in policy.semesters:
        scope_reasons.append("semester_outside_reference")
    if not policy.min_credits <= total <= policy.max_credits:
        scope_reasons.append("load_outside_reference")
    if any(group == "OTHER_PREVIOUS" for _, group in selected.values()):
        scope_reasons.append("other_previous_selected")
    scope = not scope_reasons
    available_failed = any(credits > 0 and group == "FAILED_RETAKE" for credits, group in eligible.values())
    available_withdrawn = any(credits > 0 and group == "WITHDRAWN_RETAKE" for credits, group in eligible.values())
    available = {"failed": available_failed, "withdrawn": available_withdrawn,
                 "total_previous": available_failed or available_withdrawn}
    ratios = {"failed": totals["FAILED_RETAKE"] / total, "withdrawn": totals["WITHDRAWN_RETAKE"] / total,
              "total_previous": (totals["FAILED_RETAKE"] + totals["WITHDRAWN_RETAKE"]) / total}
    flags, penalties, reasons = {}, {}, {"scope": scope_reasons}
    for name in BALANCE_COMPONENTS:
        flags[name] = scope and available[name]
        reasons[name] = [*scope_reasons, *([] if available[name] else ["no_positive_eligible_candidates"])]
        lower, upper = getattr(policy, f"{name}_band")
        penalties[f"{name}_balance_penalty"] = float(max(lower - ratios[name], 0, ratios[name] - upper)) if flags[name] else None
    return {
        "balance_policy_version": policy.version, "total_credits": total_number,
        "failed_retake_credits": float(totals["FAILED_RETAKE"]),
        "withdrawn_retake_credits": float(totals["WITHDRAWN_RETAKE"]),
        "new_credits": float(totals["NEW"]), "other_previous_credits": float(totals["OTHER_PREVIOUS"]),
        **{f"{name}_ratio": float(value) for name, value in ratios.items()}, **penalties,
        "scope_applicable": scope, "component_active_flags": flags, "disabled_reasons": reasons,
    }
