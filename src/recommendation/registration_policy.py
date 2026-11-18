"""Credit targets and caps calculated independently of source validation."""
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal


CreditBounds = tuple[Decimal, Decimal]


def decimal_credit_units(value, decimal_places):
    """Scale a Decimal exactly using its digits, independent of Decimal context."""
    parts = value.as_tuple()
    coefficient = 0
    for digit in parts.digits:
        coefficient = coefficient * 10 + digit
    return (-coefficient if parts.sign else coefficient) * 10 ** (parts.exponent + decimal_places)


def sum_credit_values(values: Iterable[Decimal]) -> Decimal:
    """Exact signed Decimal sum for policy arithmetic and complete-plan caps."""
    values = tuple(values)
    places = max([0, *[-value.as_tuple().exponent for value in values]])
    total = sum(decimal_credit_units(value, places) for value in values)
    parts = Decimal(total).as_tuple()
    return Decimal((parts.sign, parts.digits, -places))


def resolve_credit_bounds(credits=None, min_credits=None, max_credits=None) -> CreditBounds:
    """Validate direct-core credit options and return the interval for exact targeting."""
    if credits is not None:
        if min_credits is not None or max_credits is not None:
            raise ValueError("Use credits OR min_credits/max_credits, not both.")
        lower = upper = Decimal(str(credits))
    else:
        if min_credits is None or max_credits is None:
            raise ValueError("Supply credits or both min_credits and max_credits.")
        lower, upper = Decimal(str(min_credits)), Decimal(str(max_credits))
    if not lower.is_finite() or not upper.is_finite() or lower < 0 or upper <= 0 or lower > upper:
        raise ValueError("Invalid credit bounds: require 0 <= min <= max and max > 0.")
    return lower, upper


def intersect_credit_bounds(first: CreditBounds, second: CreditBounds) -> CreditBounds | None:
    """Intersect normalized intervals, including a shared endpoint."""
    lower = max(first[0], second[0])
    upper = min(first[1], second[1])
    return (lower, upper) if lower <= upper else None


def remaining_requirement_credits(
    maximum: Decimal, *, overflow: Decimal, completed: Decimal, reserved: Decimal = Decimal(0),
) -> Decimal:
    """Apply allowances and consumed credits to a requirement-type or group cap."""
    return max(Decimal(0), sum_credit_values((maximum, overflow, completed.copy_negate(), reserved.copy_negate())))


def requirement_group_cap(
    mode: str, maximum: Decimal, completed: Decimal, overflow: Decimal | None = None,
) -> Decimal | None:
    """Calculate the confirmed group cap, or defer to available credits for unbounded groups.

    Strict mode expects completed credits within the confirmed maximum.
    """
    if mode == "strict_remaining":
        return sum_credit_values((maximum, completed.copy_negate()))
    if mode == "approved_overflow":
        if overflow is None:
            raise ValueError("Approved overflow requires a credit allowance.")
        return remaining_requirement_credits(maximum, overflow=overflow, completed=completed)
    if mode == "unbounded":
        return None
    raise ValueError("Unknown requirement group mode.")


def candidate_credit_caps(
    candidates: Iterable[tuple[str, str, Decimal]], group_caps: Mapping[str, Decimal | None],
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Resolve type and group caps from eligible, deduplicated (type, group, credits) facts."""
    types, groups = defaultdict(list), defaultdict(list)
    for requirement_type, requirement_group, credits in candidates:
        types[requirement_type].append(credits)
        groups[requirement_group].append(credits)
    return (
        {key: sum_credit_values(values) for key, values in types.items()},
        {key: sum_credit_values(groups[key]) if cap is None else cap for key, cap in group_caps.items()},
    )
