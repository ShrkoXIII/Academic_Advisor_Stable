"""Credit-bound validation and exhaustive plan-row generation."""
from decimal import Decimal

import numpy as np

from .registration_policy import decimal_credit_units, resolve_credit_bounds
from .registration_policy import sum_credit_values as sum_credit_values


def enumerate_plan_indices(candidate_courses, target_credits=None, *, min_credits=None, max_credits=None,
                           search_stats=None):
    """Yield all subsets exactly matching the requested upper bound, without rounding.

    Zero-credit courses remain optional members even after reaching the upper bound.
    Optional diagnostic counters observe actual visits, including pruned states;
    they do not change traversal or apply a search budget.
    """
    values = [Decimal(str(v)) for v in candidate_courses["course_credits"]]
    lower, upper = resolve_credit_bounds(target_credits, min_credits, max_credits)
    lower = upper
    if any(not v.is_finite() or v < 0 for v in values):
        raise ValueError("Course credits must be finite and nonnegative.")
    places = max(0, *[-v.as_tuple().exponent for v in [*values, lower, upper]])
    units = [decimal_credit_units(v, places) for v in values]
    minimum, maximum = decimal_credit_units(lower, places), decimal_credit_units(upper, places)
    suffix = [0] * (len(units) + 1)
    for i in range(len(units) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + units[i]
    if search_stats is not None:
        search_stats.update(visited_search_states=0, exact_credit_plan_count=0)

    def visit(i, total, selected):
        if search_stats is not None:
            search_stats["visited_search_states"] += 1
        if total > maximum or total + suffix[i] < minimum:
            return
        if i == len(units):
            if minimum <= total <= maximum and total > 0:
                if search_stats is not None:
                    search_stats["exact_credit_plan_count"] += 1
                yield selected
            return
        yield from visit(i + 1, total + units[i], (*selected, i))
        yield from visit(i + 1, total, selected)

    yield from visit(0, 0, ())


def build_plan_rows(candidates, plans, first_plan_id=0):
    lengths = np.array([len(p) for p in plans], dtype="int64")
    indices = np.fromiter((i for plan in plans for i in plan), dtype="int64")
    rows = candidates.iloc[indices].reset_index(drop=True).copy()
    rows["plan_id"] = np.repeat(np.arange(first_plan_id, first_plan_id + len(plans)), lengths)
    return rows
