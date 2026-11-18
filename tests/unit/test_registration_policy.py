"""Registration policy tests with normalized credits and synthetic candidates."""
from decimal import Decimal

import pandas as pd
import pytest

from src.recommendation.constraints import (
    PlanConstraints, enumerate_feasible_plan_indices, normalize_requirement_policies,
)
from src.recommendation.registration_policy import (
    candidate_credit_caps, intersect_credit_bounds, requirement_group_cap, resolve_credit_bounds,
)


def test_exact_and_clipped_range_produce_the_same_target():
    provider = (Decimal("3"), Decimal("6.5"))
    exact = resolve_credit_bounds(credits="6.50")
    ranged = resolve_credit_bounds(min_credits="3.5", max_credits="8")

    assert exact == (Decimal("6.5"), Decimal("6.5"))
    assert ranged == (Decimal("3.5"), Decimal("8"))
    assert intersect_credit_bounds(exact, provider) == exact
    assert intersect_credit_bounds(ranged, provider) == (Decimal("3.5"), exact[1])
    assert intersect_credit_bounds(resolve_credit_bounds(credits=7), provider) is None


@pytest.mark.parametrize(("options", "error"), [
    ({"min_credits": 3}, "Supply credits or both"),
    ({"min_credits": 6, "max_credits": 3}, "Invalid credit bounds"),
    ({"credits": 0}, "Invalid credit bounds"),
], ids=["missing-upper", "reversed", "zero-target"])
def test_direct_credit_bounds_retain_validation(options, error):
    with pytest.raises(ValueError, match=error):
        resolve_credit_bounds(**options)


def test_group_caps_distinguish_strict_overflow_and_available_credits():
    maximum = Decimal("6")
    strict = requirement_group_cap("strict_remaining", maximum, Decimal("6.00"))
    approved = requirement_group_cap("approved_overflow", maximum, Decimal("6.25"), Decimal("1.50"))
    exhausted = requirement_group_cap("approved_overflow", maximum, Decimal("8"), Decimal("1"))
    unbounded = requirement_group_cap("unbounded", maximum, Decimal("7"))
    assert strict.as_tuple() == Decimal("0.00").as_tuple()
    assert approved == Decimal("1.25")
    assert exhausted == Decimal(0)
    assert unbounded is None

    type_caps, group_caps = candidate_credit_caps([
        ("elective", "strict", Decimal("2.25")),
        ("elective", "approved", Decimal("1.25")),
        ("required", "unbounded", Decimal("3.25")),
        ("required", "unbounded", Decimal("1.5")),
    ], {"strict": strict, "approved": approved, "unbounded": unbounded, "empty": None})

    assert type_caps == {"elective": Decimal("3.50"), "required": Decimal("4.75")}
    assert group_caps == {"strict": Decimal(0), "approved": Decimal("1.25"),
                          "unbounded": Decimal("4.75"), "empty": Decimal(0)}


def test_elective_type_maximum_applies_after_completed_and_reserved_credits():
    policies = normalize_requirement_policies([
        {"plan_requirement_type_id": "elective", "max_credits": "6",
         "completed_credits": "2.5", "reserved_credits": "1", "allowed_overflow_credits": "0.5"},
        {"plan_requirement_type_id": "required", "max_credits": "3"},
    ])
    assert policies == {"elective": Decimal(3), "required": Decimal(3)}
    candidates = pd.DataFrame({
        "course_credits": [3, 3, 3], "plan_requirement_type_id": ["elective", "elective", "required"],
        "candidate_group": ["NEW", "NEW", "NEW"],
    })
    constraints = PlanConstraints(Decimal(6), policies, Decimal(0))
    assert list(enumerate_feasible_plan_indices(candidates, constraints)) == [(0, 2), (1, 2)]
