"""Preserve serving coercion while selecting an explicit ordered feature subset."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from src.features.feature_contract import (
    BASE_FEATURES,
    CATEGORICAL_FEATURES,
    CATEGORY_MISSING,
    CATEGORY_UNKNOWN,
    NUMERIC_FEATURES,
    prepare_model_matrix,
)
from src.recommendation.two_stage_artifacts import stage_feature_contract


def _legacy_47_matrix(frame, category_levels):
    """Frozen pre-generalization implementation, used only as a parity oracle."""
    matrix = pd.DataFrame(index=frame.index)
    for column in NUMERIC_FEATURES:
        matrix[column] = pd.to_numeric(frame[column], errors="coerce").astype(
            "float32"
        )
    for column in CATEGORICAL_FEATURES:
        values = frame[column].astype("string").fillna(CATEGORY_MISSING)
        values = values.where(values.isin(category_levels[column]), CATEGORY_UNKNOWN)
        matrix[column] = pd.Categorical(values, categories=category_levels[column])
    return matrix[BASE_FEATURES]


def _matrix_inputs(empty=False):
    index = pd.Index([91, 8, 91, -6], name="source_row")
    frame = pd.DataFrame({
        **{name: ["2.75", "bad", None, "-1"] for name in NUMERIC_FEATURES},
        **{name: ["known", None, "unseen", CATEGORY_UNKNOWN]
           for name in CATEGORICAL_FEATURES},
        "student_id": [1, 2, 3, 4],
        "final_mark": [99, 10, 75, 0],
    }, index=index)
    levels = {name: [CATEGORY_MISSING, CATEGORY_UNKNOWN, "unused", "known"]
              for name in CATEGORICAL_FEATURES}
    return frame.iloc[:0] if empty else frame, levels


@pytest.mark.parametrize("empty", [False, True])
def test_default_matrix_matches_legacy_47_exactly_without_mutating_inputs(empty):
    frame, levels = _matrix_inputs(empty)
    original_frame, original_levels = frame.copy(deep=True), deepcopy(levels)

    actual = prepare_model_matrix(frame, levels)

    pd.testing.assert_frame_equal(actual, _legacy_47_matrix(frame, levels), check_exact=True)
    pd.testing.assert_frame_equal(frame, original_frame, check_exact=True)
    assert levels == original_levels


@pytest.mark.parametrize("empty", [False, True])
def test_stage1_matches_legacy_slice_without_requiring_plan_context(empty):
    frame, levels = _matrix_inputs(empty)
    features = stage_feature_contract("stage1")["model_features"]
    course_rows = frame.loc[:, features].copy()
    original_rows, original_levels = course_rows.copy(deep=True), deepcopy(levels)

    actual = prepare_model_matrix(course_rows, levels, model_features=features)

    pd.testing.assert_frame_equal(
        actual, _legacy_47_matrix(frame, levels).loc[:, features], check_exact=True,
    )
    pd.testing.assert_frame_equal(course_rows, original_rows, check_exact=True)
    assert levels == original_levels


def test_explicit_feature_order_coerces_only_the_requested_columns():
    index = pd.Index([15, 3, 15, 0], name="request_row")
    features = ("part_semester", "course_credits", "grade_version_id", "gpa_prev_1")
    frame = pd.DataFrame({
        "gpa_prev_1": ["3.1", "", None, "0"],
        "course_credits": ["2.5", "invalid", None, "-1"],
        "part_semester": pd.array([1, pd.NA, 3, 2], dtype="Int64"),
        "grade_version_id": ["known", pd.NA, "new", CATEGORY_UNKNOWN],
    }, index=index)
    levels = {
        "part_semester": [CATEGORY_MISSING, CATEGORY_UNKNOWN, "2", "1"],
        "grade_version_id": [CATEGORY_MISSING, CATEGORY_UNKNOWN, "known"],
    }
    original_frame, original_levels = frame.copy(deep=True), deepcopy(levels)
    expected = pd.DataFrame({
        "part_semester": pd.Categorical(
            ["1", CATEGORY_MISSING, CATEGORY_UNKNOWN, "2"],
            categories=levels["part_semester"],
        ),
        "course_credits": np.array([2.5, np.nan, np.nan, -1], dtype="float32"),
        "grade_version_id": pd.Categorical(
            ["known", CATEGORY_MISSING, CATEGORY_UNKNOWN, CATEGORY_UNKNOWN],
            categories=levels["grade_version_id"],
        ),
        "gpa_prev_1": np.array([3.1, np.nan, np.nan, 0], dtype="float32"),
    }, index=index)

    actual = prepare_model_matrix(frame, levels, model_features=features)

    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    pd.testing.assert_frame_equal(frame, original_frame, check_exact=True)
    assert levels == original_levels


@pytest.mark.parametrize("unknown", ["final_mark", "student_id", "unknown_feature"])
def test_explicit_features_reject_names_outside_the_model_contract(unknown):
    frame, levels = _matrix_inputs()
    frame[unknown] = 1

    with pytest.raises(ValueError, match="Unknown model features"):
        prepare_model_matrix(frame, levels, model_features=["course_credits", unknown])


@pytest.mark.parametrize("feature", ["course_credits", "part_semester"])
def test_explicit_features_reject_duplicate_model_columns(feature):
    frame, levels = _matrix_inputs()

    with pytest.raises(ValueError, match="Duplicate model features"):
        prepare_model_matrix(frame, levels, model_features=[feature, feature])


def test_legacy_course_matrix_api_retains_33_feature_coercion_and_missing_validation():
    from src.modeling.shortlist_features import COURSE_ONLY_FEATURES, prepare_course_matrix

    frame, levels = _matrix_inputs()
    course_rows = frame.loc[:, COURSE_ONLY_FEATURES]

    pd.testing.assert_frame_equal(
        prepare_course_matrix(course_rows, levels),
        _legacy_47_matrix(frame, levels).loc[:, COURSE_ONLY_FEATURES],
        check_exact=True,
    )
    with pytest.raises(ValueError, match="Missing course-only features"):
        prepare_course_matrix(course_rows.drop(columns="course_credits"), levels)
