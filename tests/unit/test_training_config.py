import numpy as np
import pandas as pd
import pytest

from src.modeling.training_config import TARGET_FAIL, TARGET_GRADE, training_weights


def test_target_definitions():
    assert TARGET_GRADE == "final_mark"
    assert TARGET_FAIL == "is_fail"


@pytest.mark.parametrize(
    ("part_id", "expected"),
    [(20201, 0.25), (20213, 0.25), (20221, 1.0), (20243, 1.0), (20251, 1.0)],
)
def test_training_weights_year_boundary(part_id, expected):
    result = training_weights(pd.DataFrame({"part_id": [part_id]}))
    assert result.tolist() == [expected]
    assert result.dtype == np.dtype("float32")


def test_training_weights_preserves_index_and_numeric_coercion():
    frame = pd.DataFrame(
        {"part_id": ["20213", "20221", None, "invalid"]}, index=[8, 3, 5, 1]
    )
    pd.testing.assert_series_equal(
        training_weights(frame),
        pd.Series([0.25, 1.0, 1.0, 1.0], index=frame.index, name="part_id", dtype="float32"),
    )
