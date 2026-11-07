"""Characterize the migrated temporal boundaries without changing their policy."""
import pandas as pd
from pandas.testing import assert_frame_equal

from src.data.building.build_temporal_split import build_temporal_split


def test_fixed_parts_sort_and_preserve_existing_incomplete_and_unknown_policy():
    source = pd.DataFrame({
        "student_course_id": ["b", "a", "c", "d", "e", "f"],
        "student_id": ["S"] * 6,
        "course_id": ["C"] * 6,
        "part_id": [20243, 20201, 20252, 20251, 20253, 20261],
        "course_outcome_status": ["pass"] * 6,
    })
    original = source.copy(deep=True)
    train, test, incomplete = build_temporal_split(source)
    assert train.part_id.tolist() == [20201, 20243]
    assert test.part_id.tolist() == [20251, 20252]
    assert incomplete.part_id.tolist() == [20253]
    assert set(train.student_course_id).isdisjoint(test.student_course_id)
    assert "f" not in set(pd.concat([train, test, incomplete]).student_course_id)
    assert train.columns.tolist() == source.columns.tolist()
    assert_frame_equal(source, original)
