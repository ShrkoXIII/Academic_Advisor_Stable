"""Exact-credit policy checks using independent subset expectations."""
from decimal import Decimal
from itertools import combinations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.recommendation import constraints


def policies(*records):
    return constraints.normalize_requirement_policies(list(records))


def request(target="3", requirement_policies=None, failed="3", withdrawn=None):
    return constraints.PlanConstraints(
        target_credits=Decimal(target),
        requirement_policies={"R": Decimal("6")} if requirement_policies is None else requirement_policies,
        allowed_failed_repeat_credits=Decimal(failed),
        allowed_withdrawn_repeat_credits=None if withdrawn is None else Decimal(withdrawn),
    )


def candidates(credits, groups, requirements=None):
    return pd.DataFrame({
        "course_credits": credits,
        "candidate_group": groups,
        "plan_requirement_type_id": ["R"] * len(credits) if requirements is None else requirements,
    })


def test_requirement_alias_and_adjustments_preserve_fractional_remaining():
    actual = policies({
        "plan_requirement_type_id": " 12.0 ", "max_credits": "6.25",
        "requirement_max_credits": 6.25, "allowed_overflow_credits": "0.5",
        "completed_credits": "3.125", "reserved_credits": "0.375",
    })
    assert actual == {"12": Decimal("3.250")}


def test_requirement_without_adjustments_defaults_to_zero_adjustments():
    assert policies({"plan_requirement_type_id": "R", "requirement_max_credits": "3.1"}) == {
        "R": Decimal("3.1"),
    }


def test_overcompleted_requirement_has_zero_remaining():
    actual = policies({
        "plan_requirement_type_id": "R", "max_credits": 3,
        "completed_credits": 4, "reserved_credits": 1,
    })
    assert actual == {"R": Decimal("0")}


@pytest.mark.parametrize("record", [
    {"plan_requirement_type_id": "R", "max_credits": 3, "requirement_max_credits": 4},
    {"plan_requirement_type_id": "R"},
    {"max_credits": 3},
    {"plan_requirement_type_id": None, "max_credits": 3},
    {"plan_requirement_type_id": "", "max_credits": 3},
    {"plan_requirement_type_id": "R", "max_credits": "NaN"},
    {"plan_requirement_type_id": "R", "max_credits": "Infinity"},
    {"plan_requirement_type_id": "R", "max_credits": -1},
    {"plan_requirement_type_id": "R", "max_credits": True},
    {"plan_requirement_type_id": "R", "max_credits": 3, "completed_credits": -1},
    {"plan_requirement_type_id": "R", "max_credits": 3, "reserved_credits": None},
    {"plan_requirement_type_id": "R", "max_credits": 3, "allowed_overflow_credits": "bad"},
])
def test_invalid_requirement_policy_rejects(record):
    with pytest.raises(ValueError):
        policies(record)


def test_duplicate_normalized_requirement_ids_reject_even_when_values_match():
    with pytest.raises(ValueError):
        policies(
            {"plan_requirement_type_id": "12", "max_credits": 3},
            {"plan_requirement_type_id": "12.0", "max_credits": 3},
        )


@pytest.mark.parametrize("records", [None, {}, "R", [None], [3]])
def test_invalid_requirement_record_list_rejects(records):
    with pytest.raises(ValueError):
        constraints.normalize_requirement_policies(records)


@pytest.mark.parametrize("field,value", [
    ("target_credits", 0), ("target_credits", -1), ("target_credits", "NaN"),
    ("target_credits", True), ("allowed_failed_repeat_credits", -1),
    ("allowed_failed_repeat_credits", None), ("allowed_failed_repeat_credits", "Infinity"),
    ("allowed_withdrawn_repeat_credits", -1), ("allowed_withdrawn_repeat_credits", "NaN"),
    ("requirement_policies", {"R": -1}), ("requirement_policies", {None: 3}),
])
def test_invalid_direct_constraints_reject(field, value):
    values = dict(target_credits=Decimal("3"), requirement_policies={"R": Decimal("3")},
                  allowed_failed_repeat_credits=Decimal("3"))
    values[field] = value
    with pytest.raises(ValueError):
        constraints.PlanConstraints(**values)


def test_failed_repeat_cap_is_required():
    with pytest.raises(TypeError):
        constraints.PlanConstraints(target_credits=Decimal("3"), requirement_policies={"R": Decimal("3")})


def test_zero_credit_choices_remain_distinct_with_repeat_caps_zero():
    rows = candidates([3, 0, 0], ["NEW", "FAILED_RETAKE", "WITHDRAWN_RETAKE"])
    actual = list(constraints.enumerate_feasible_plan_indices(rows, request(failed="0", withdrawn="0")))
    assert actual == [(0, 1, 2), (0, 1), (0, 2), (0,)]


def test_failed_cap_and_withdrawn_cap_are_independent_maxima():
    rows = candidates([3, 3, 3], ["FAILED_RETAKE", "WITHDRAWN_RETAKE", "NEW"])
    assert list(constraints.enumerate_feasible_plan_indices(rows, request(failed="0", withdrawn="3"))) == [
        (1,), (2,),
    ]
    assert list(constraints.enumerate_feasible_plan_indices(rows, request(failed="3", withdrawn="0"))) == [
        (0,), (2,),
    ]
    assert list(constraints.enumerate_feasible_plan_indices(rows, request(failed="0"))) == [(1,), (2,)]


def test_other_previous_and_attempts_or_probabilities_do_not_consume_repeat_caps():
    rows = candidates([3, 3], ["NEW", "OTHER_PREVIOUS"])
    rows["attempt_number"] = [10, 20]
    rows["fail_probability"] = [1., 1.]
    rows["final_mark"] = [0, 0]
    assert list(constraints.enumerate_feasible_plan_indices(rows, request(failed="0", withdrawn="0"))) == [
        (0,), (1,),
    ]


def test_selected_repeat_costs_full_credits_to_requirement():
    rows = candidates([3, 3], ["FAILED_RETAKE", "NEW"])
    assert list(constraints.enumerate_feasible_plan_indices(
        rows, request(target="6", requirement_policies={"R": Decimal("3")}),
    )) == []


def test_fractional_subsets_match_hand_derived_oracle():
    rows = candidates(["0.1", "0.2", "0.3", "0", "0.1"],
                      ["FAILED_RETAKE", "WITHDRAWN_RETAKE", "NEW", "NEW", "NEW"],
                      ["R", "R", "S", "S", "R"])
    actual = list(constraints.enumerate_feasible_plan_indices(rows, request(
        target="0.3", requirement_policies={"R": Decimal("0.3"), "S": Decimal("0.3")},
        failed="0", withdrawn="0.2",
    )))
    assert actual == [(1, 3, 4), (1, 4), (2, 3), (2,)]


def test_constraints_match_independent_exhaustive_oracle_and_preserve_candidates():
    rows = candidates(["1.25", "0.75", "2", "0", "1", "1"],
                      ["FAILED_RETAKE", "WITHDRAWN_RETAKE", "NEW", "OTHER_PREVIOUS", "NEW", "FAILED_RETAKE"],
                      ["R", "R", "S", "S", "R", "S"])
    before = rows.copy(deep=True)
    expected = set()
    for size in range(1, len(rows) + 1):
        for subset in combinations(range(len(rows)), size):
            selected = rows.iloc[list(subset)]
            values = [Decimal(v) for v in selected.course_credits]
            if sum(values) != Decimal("3"):
                continue
            requirement_r = sum(v for v, r in zip(values, selected.plan_requirement_type_id) if r == "R")
            requirement_s = sum(v for v, r in zip(values, selected.plan_requirement_type_id) if r == "S")
            failed = sum(v for v, g in zip(values, selected.candidate_group) if g == "FAILED_RETAKE")
            withdrawn = sum(v for v, g in zip(values, selected.candidate_group) if g == "WITHDRAWN_RETAKE")
            if requirement_r <= Decimal("2") and requirement_s <= Decimal("2") and failed <= Decimal("1.25") and withdrawn <= Decimal("0"):
                expected.add(subset)
    actual = list(constraints.enumerate_feasible_plan_indices(rows, request(
        requirement_policies={"R": Decimal("2"), "S": Decimal("2")}, failed="1.25", withdrawn="0",
    )))
    assert set(actual) == expected
    assert len(actual) == len(expected)
    assert_frame_equal(rows, before)


def test_unreachable_upper_target_has_no_lower_fallback():
    rows = candidates([2, 2], ["NEW", "NEW"])
    assert list(constraints.enumerate_feasible_plan_indices(rows, request(target="5"))) == []


def test_missing_requirement_policy_rejects_even_for_zero_credit_candidate():
    rows = candidates([3, 0], ["NEW", "NEW"], ["R", "missing"])
    with pytest.raises(ValueError, match="policy"):
        list(constraints.enumerate_feasible_plan_indices(rows, request()))


@pytest.mark.parametrize("column,value", [
    ("course_credits", -1), ("course_credits", "NaN"), ("course_credits", True),
    ("course_credits", None), ("plan_requirement_type_id", None),
    ("candidate_group", None), ("candidate_group", "FAILED"), ("candidate_group", "UNKNOWN"),
])
def test_invalid_candidate_constraint_fields_reject(column, value):
    rows = candidates([3], ["NEW"])
    rows[column] = value
    with pytest.raises(ValueError):
        list(constraints.enumerate_feasible_plan_indices(rows, request()))


@pytest.mark.parametrize("column", ["course_credits", "plan_requirement_type_id", "candidate_group"])
def test_missing_candidate_constraint_column_rejects(column):
    rows = candidates([3], ["NEW"]).drop(columns=column)
    with pytest.raises(ValueError):
        list(constraints.enumerate_feasible_plan_indices(rows, request()))


def test_empty_candidate_set_has_no_feasible_plan():
    rows = candidates([], [])
    assert list(constraints.enumerate_feasible_plan_indices(rows, request())) == []
