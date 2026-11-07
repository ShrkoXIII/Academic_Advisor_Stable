"""Rules for regular and optional academic semesters."""

REGULAR_SEMESTERS = {1, 2}
OPTIONAL_SEMESTERS = {3}


def is_regular_semester(part_id):
    """Return whether a valid academic part is a regular semester."""
    try:
        semester = int(part_id) % 10
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid part_id {part_id!r}: semester must be 1, 2, or 3") from exc
    if semester not in REGULAR_SEMESTERS | OPTIONAL_SEMESTERS:
        raise ValueError(f"Invalid part_id {part_id!r}: semester must be 1, 2, or 3")
    return semester in REGULAR_SEMESTERS


def count_regular_semesters_between(previous_part_id, current_part_id):
    """Count regular semesters strictly between two ordered part IDs."""
    is_regular_semester(previous_part_id)
    is_regular_semester(current_part_id)
    previous_year, previous_semester = divmod(int(previous_part_id), 10)
    current_year, current_semester = divmod(int(current_part_id), 10)
    if current_part_id < previous_part_id:
        raise ValueError("current_part_id must not precede previous_part_id")
    if current_part_id == previous_part_id:
        return 0

    return (
        len(REGULAR_SEMESTERS) * (current_year - previous_year)
        + sum(semester < current_semester for semester in REGULAR_SEMESTERS)
        - sum(semester <= previous_semester for semester in REGULAR_SEMESTERS)
    )
