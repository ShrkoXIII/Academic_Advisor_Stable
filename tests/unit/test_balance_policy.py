"""Balance checks use official groups and synthetic course identities only."""
import json
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def balance_api():
    from src.recommendation.balance_policy import B_OBSERVED_MIDDLE_V1, compute_balance_components
    return B_OBSERVED_MIDDLE_V1, compute_balance_components


def courses(failed=3, withdrawn=0, new=12, other=None):
    values = [("F", failed, "FAILED_RETAKE"), ("W", withdrawn, "WITHDRAWN_RETAKE"),
              ("N", new, "NEW")]
    if other is not None:
        values.append(("O", other, "OTHER_PREVIOUS"))
    return pd.DataFrame(values, columns=["course_id", "course_credits", "candidate_group"])


def compute(selected, eligible=None, semester=1):
    return balance_api()[1](selected, selected if eligible is None else eligible, part_semester=semester)


def test_exact_policy_is_versioned_and_has_no_new_quota():
    policy, _ = balance_api()
    assert policy.version == "B_observed_middle_v1"
    assert policy.failed_band == (Fraction(1, 6), Fraction(4, 17))
    assert policy.withdrawn_band == (Fraction(0), Fraction(3, 17))
    assert policy.total_previous_band == (Fraction(1, 6), Fraction(2, 7))
    assert not hasattr(policy, "new_band")
    with pytest.raises(AttributeError):
        policy.version = "changed"


def test_separate_credit_denominators_and_penalties():
    result = compute(courses(6, 3, 6))
    assert [result[k] for k in ("failed_retake_credits", "withdrawn_retake_credits",
                                "new_credits", "other_previous_credits")] == [6, 3, 6, 0]
    assert result["failed_ratio"] == pytest.approx(6 / 15)
    assert result["withdrawn_ratio"] == pytest.approx(3 / 15)
    assert result["total_previous_ratio"] == pytest.approx(9 / 15)
    assert result["failed_balance_penalty"] == pytest.approx(6 / 15 - 4 / 17)
    assert result["withdrawn_balance_penalty"] == pytest.approx(3 / 15 - 3 / 17)
    assert result["total_previous_balance_penalty"] == pytest.approx(9 / 15 - 2 / 7)
    assert result["scope_applicable"] is True
    assert all(result["component_active_flags"].values())
    assert "balance_score" not in result


@pytest.mark.parametrize("failed,withdrawn,new,component", [(3, 0, 15, "failed"),
    (4, 0, 13, "failed"), (3, 3, 11, "withdrawn"), (3, 0, 15, "withdrawn"),
    (3, 0, 15, "total_previous"), (2, 2, 10, "total_previous")])
def test_exact_band_boundaries_have_zero_distance(failed, withdrawn, new, component):
    selected = courses(failed, withdrawn, new)
    eligible = pd.concat([selected, courses(3, 3, 0).assign(course_id=["xF", "xW", "xN"])])
    result = compute(selected, eligible)
    assert result[f"{component}_balance_penalty"] == 0


@pytest.mark.parametrize("failed,expected", [(0, 1 / 6), (2.49, 1 / 6 - 2.49 / 15),
                                          (3.54, 3.54 / 15 - 4 / 17), (15, 1 - 4 / 17)])
def test_distance_on_both_sides_is_soft(failed, expected):
    selected = courses(failed, 0, 15 - failed)
    eligible = pd.concat([selected, courses(3, 0, 0).assign(course_id=["extraF", "extraW", "extraN"])])
    result = compute(selected, eligible)
    assert result["failed_balance_penalty"] == pytest.approx(expected)
    assert result["scope_applicable"] is True
    assert len(selected) == 3  # No feasibility filtering or quota enforcement.


@pytest.mark.parametrize("semester", [1, 2])
@pytest.mark.parametrize("total", [12, 18, 12.5, 17.99])
def test_reference_scope_accepts_fractional_inclusive_loads(semester, total):
    assert compute(courses(3, 0, total - 3), semester=semester)["scope_applicable"] is True


@pytest.mark.parametrize("semester,total,other,reason", [(3, 15, None, "semester_outside_reference"),
    (1, 11.99, None, "load_outside_reference"), (2, 18.01, None, "load_outside_reference"),
    (1, 15, 0, "other_previous_selected"), (1, 15, 1, "other_previous_selected")])
def test_outside_scope_has_no_artificial_zero_penalty(semester, total, other, reason):
    result = compute(courses(3, 0, total - 3 - (other or 0), other), semester=semester)
    assert result["scope_applicable"] is False
    assert reason in result["disabled_reasons"]["scope"]
    assert not any(result["component_active_flags"].values())
    assert all(result[f"{name}_balance_penalty"] is None for name in ("failed", "withdrawn", "total_previous"))
    assert result["total_previous_ratio"] == pytest.approx(3 / total)  # excludes Other


@pytest.mark.parametrize("failed,withdrawn,flags", [(3, 0, (True, False, True)),
    (0, 3, (False, True, True)), (0, 0, (False, False, False)), (3, 3, (True, True, True))])
def test_only_positive_eligible_candidates_activate_components(failed, withdrawn, flags):
    eligible = courses(failed, withdrawn, 15)
    selected = eligible.loc[eligible.course_id.eq("N")]
    result = compute(selected, eligible)
    names = ("failed", "withdrawn", "total_previous")
    assert tuple(result["component_active_flags"][name] for name in names) == flags
    for name, active in zip(names, flags):
        assert (result[f"{name}_balance_penalty"] is not None) == active
        if not active:
            assert result["disabled_reasons"][name] == ["no_positive_eligible_candidates"]
    if failed:
        assert result["failed_balance_penalty"] == pytest.approx(1 / 6)


def test_zero_credit_members_affect_identity_and_scope_but_not_credit_ratios():
    base = courses(3, 0, 12)
    result = compute(base)
    assert result["withdrawn_balance_penalty"] is None
    assert result["failed_ratio"] == .2
    changed = compute(courses(3, 0, 12, 0))
    assert changed["other_previous_credits"] == 0
    assert changed["scope_applicable"] is False


def test_candidate_permutation_preserves_metrics_and_input_frames():
    selected = courses(3, 2, 10)
    before = selected.copy(deep=True)
    assert compute(selected) == compute(selected.iloc[::-1])
    pd.testing.assert_frame_equal(selected, before)


@pytest.mark.parametrize("bad", [None, np.nan, np.inf, -1, True, "bad", "1e400"])
def test_invalid_credits_are_rejected(bad):
    with pytest.raises(ValueError):
        compute(courses(bad, 0, 15))


def test_sum_of_finite_credits_that_overflows_output_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        compute(courses("1e308", "1e308", 0))


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown_group", "not_eligible", "mismatched_credits", "mismatched_group", "zero_load"])
def test_incomplete_or_inconsistent_plan_input_is_rejected(change):
    selected, eligible = courses(), courses()
    if change == "missing":
        selected = selected.drop(columns="candidate_group")
    elif change == "duplicate":
        selected = pd.concat([selected, selected.iloc[:1]])
    elif change == "unknown_group":
        selected.loc[0, "candidate_group"] = "UNKNOWN"
    elif change == "not_eligible":
        selected.loc[0, "course_id"] = "absent"
    elif change == "mismatched_credits":
        selected.loc[0, "course_credits"] = 4
    elif change == "mismatched_group":
        selected.loc[0, "candidate_group"] = "NEW"
    else:
        selected["course_credits"] = 0
        eligible = selected.copy()
    with pytest.raises(ValueError):
        compute(selected, eligible)




