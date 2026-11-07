from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data.academic_calendar import count_regular_semesters_between, is_regular_semester  # noqa: E402


@pytest.mark.parametrize(
    "previous, current, expected",
    [
        (20221, 20222, 0),
        (20221, 20223, 1),
        (20222, 20231, 0),
        (20221, 20231, 1),
        (20221, 20301, 15),
        (20221, 20221, 0),
        (20223, 20231, 0),
        (20223, 20232, 1),
        (20223, 20223, 0),
    ],
)
def test_regular_semesters_between(previous, current, expected):
    assert count_regular_semesters_between(previous, current) == expected


@pytest.mark.parametrize("part_id, expected", [(20221, True), (20222, True), (20223, False)])
def test_is_regular_semester(part_id, expected):
    assert is_regular_semester(part_id) is expected


@pytest.mark.parametrize("part_id", [20210, 20214, 20215])
def test_is_regular_semester_rejects_invalid_part_id(part_id):
    with pytest.raises(ValueError, match="part_id"):
        is_regular_semester(part_id)


@pytest.mark.parametrize("invalid_part_id", [20210, 20214, 20215])
@pytest.mark.parametrize("invalid_position", ["previous", "current"])
def test_count_regular_semesters_between_rejects_invalid_part_id(
    invalid_part_id, invalid_position
):
    previous, current = (invalid_part_id, 20221) if invalid_position == "previous" else (20211, invalid_part_id)
    with pytest.raises(ValueError, match="part_id"):
        count_regular_semesters_between(previous, current)


def test_count_regular_semesters_between_rejects_reversed_chronology():
    with pytest.raises(ValueError, match="current_part_id must not precede previous_part_id"):
        count_regular_semesters_between(20231, 20223)
