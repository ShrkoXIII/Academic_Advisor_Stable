import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from src.data.cleaning.cleaning_utils import (
    clean_column_names,
    clean_id,
    clean_id_columns,
    extract_university_id,
    to_float,
    to_integer,
)


def test_clean_column_names_normalizes_whitespace_without_mutating_input():
    source = pd.DataFrame(
        [[1, 2, 3]],
        columns=[" Final   Mark ", "Student\tID", "  Course  Name  SL  "],
    )
    original = source.copy(deep=True)

    result = clean_column_names(source)

    assert result.columns.tolist() == ["final_mark", "student_id", "course_name_sl"]  # NOTE: column normalization makes raw source names usable as stable Python keys.
    assert_frame_equal(source, original)  # NOTE: utility cleaning must not mutate the caller's DataFrame.


@pytest.mark.parametrize(
    "raw_value, expected_value",
    [
        (" 12.111 ", "12.111"),
        ("123.0", "123"),
        ("123.000", "123"),
        ("ABC-1", "ABC-1"),
        ("", pd.NA),
        ("nan", pd.NA),
        ("NaN", pd.NA),
        ("none", pd.NA),
        ("NONE", pd.NA),
        ("null", pd.NA),
        ("<NA>", pd.NA),
        (None, pd.NA),
    ],
)
def test_clean_id_preserves_meaningful_dots_and_normalizes_nulls(
    raw_value,
    expected_value,
):
    result = clean_id(pd.Series([raw_value], name="identifier"))

    assert str(result.dtype) == "string"  # NOTE: nullable string IDs keep missing keys representable without object fallback.
    if expected_value is pd.NA:
        assert pd.isna(result.iloc[0])  # NOTE: null-like source text must not become a literal identifier.
    else:
        assert result.iloc[0] == expected_value  # NOTE: only a trailing all-zero decimal is removed; meaningful dotted IDs survive.


def test_clean_id_columns_cleans_multiple_selected_columns_and_copies_input():
    source = pd.DataFrame(
        {
            "student_id": [" 123.0 "],
            "course_id": [" 12.111 "],
            "description": ["  keep me  "],
        }
    )
    original = source.copy(deep=True)

    result = clean_id_columns(source, ["student_id", "course_id"])

    assert result["student_id"].tolist() == ["123"]  # NOTE: every requested ID column must share clean_id's '.0' rule.
    assert result["course_id"].tolist() == ["12.111"]  # NOTE: a meaningful decimal component must remain intact.
    assert result["description"].tolist() == ["  keep me  "]  # NOTE: unrelated columns must not be normalized as a side effect.
    assert_frame_equal(source, original)  # NOTE: clean_id_columns explicitly copies before assigning cleaned columns.


@pytest.mark.parametrize(
    "raw_value, expected_value",
    [
        ("123.111", "111"),
        ("55.222", "222"),
        (" 123.111 ", "111"),
        ("123", pd.NA),
        ("none", pd.NA),
        ("", pd.NA),
    ],
)
def test_extract_university_id_extracts_after_final_dot_without_inventing_validation(
    raw_value,
    expected_value,
):
    result = extract_university_id(pd.Series([raw_value], name="identifier"))

    assert str(result.dtype) == "string"  # NOTE: extracted university IDs use the same nullable string representation as cleaned IDs.
    if expected_value is pd.NA:
        assert pd.isna(result.iloc[0])  # NOTE: IDs without a dot or null-like IDs have no extractable university component.
    else:
        assert result.iloc[0] == expected_value  # NOTE: extraction is defined by the text after the final dot.


def test_to_integer_converts_numeric_inputs_to_nullable_int64():
    source = pd.Series([1, 2.0, "3", None])

    result = to_integer(source)

    expected = pd.Series([1, 2, 3, pd.NA], dtype="Int64")
    assert_series_equal(result, expected)  # NOTE: nullable Int64 preserves whole-number semantics and missing values.


def test_to_float_converts_numeric_and_decimal_inputs_to_nullable_float64():
    source = pd.Series([1, 2.5, "3.75", None])

    result = to_float(source)

    expected = pd.Series([1.0, 2.5, 3.75, pd.NA], dtype="Float64")
    assert_series_equal(result, expected)  # NOTE: nullable Float64 preserves decimal credits/points and missing values.


@pytest.mark.parametrize("converter", [to_integer, to_float])
def test_numeric_converters_keep_current_invalid_value_failure(converter):
    with pytest.raises(ValueError):  # NOTE: pd.to_numeric currently raises instead of silently coercing bad data to missing.
        converter(pd.Series(["not-a-number"]))
