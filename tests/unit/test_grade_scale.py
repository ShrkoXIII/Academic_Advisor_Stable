"""Grade version rejection and unchanged passing-band conversion contracts."""
import numpy as np
import pandas as pd
import pytest

from src.grade_scale import GradeScale


@pytest.fixture
def grade_scale():
    return GradeScale(pd.DataFrame({
        "grade_version_id": [1.111, 1.111, 1.111, 2.111, 2.111, 2.111],
        "from_percent": [90., 60., 75., 90., 50., 70.],
        "points": [4., 1., 3., 4., 1., 2.],
        "grade_show": ["A", "D", "B", "A", "D", "C"],
    }))


def test_supported_versions_convert_passing_marks(grade_scale):
    points, labels = grade_scale.convert([75., 70.], [1.111, "2.111"])
    np.testing.assert_array_equal(points, [3., 2.])
    np.testing.assert_array_equal(labels, ["B", "C"])


def test_supported_versions_keep_failing_marks_at_zero_and_f(grade_scale):
    points, labels = grade_scale.convert([59.999, 49.999], [1.111, 2.111])
    np.testing.assert_array_equal(points, [0., 0.])
    np.testing.assert_array_equal(labels, ["F", "F"])


@pytest.mark.parametrize("version", [999, None, "invalid-version", "", np.nan, pd.NA, np.inf, -np.inf])
def test_convert_rejects_invalid_version_even_in_a_mixed_batch(grade_scale, version):
    with pytest.raises(ValueError) as exc:
        grade_scale.convert([75., 90.], [1.111, version])
    assert "grade_version_id" in str(exc.value)
    assert repr(version) in str(exc.value)


def test_convert_rejects_missing_version_argument(grade_scale):
    with pytest.raises(ValueError, match="grade_version_id.*None"):
        grade_scale.convert([90.], None)


@pytest.mark.parametrize("versions", [[], [1.111, 2.111]])
def test_convert_requires_one_version_per_mark(grade_scale, versions):
    with pytest.raises(ValueError, match="grade_version_id"):
        grade_scale.convert([90.], versions)


def test_convert_keeps_empty_batches_valid(grade_scale):
    points, labels = grade_scale.convert([], [])
    assert points.size == labels.size == 0


@pytest.mark.parametrize("version, marks, expected_points, expected_labels", [
    (1.111, [0., 59.999, 60., 74.999, 75., 89.999, 90., 100.],
     [0., 0., 1., 1., 3., 3., 4., 4.], ["F", "F", "D", "D", "B", "B", "A", "A"]),
    (2.111, [0., 49.999, 50., 69.999, 70., 89.999, 90., 100.],
     [0., 0., 1., 1., 2., 2., 4., 4.], ["F", "F", "D", "D", "C", "C", "A", "A"]),
])
def test_supported_version_boundaries_remain_unchanged(
        grade_scale, version, marks, expected_points, expected_labels):
    points, labels = grade_scale.convert(marks, [version] * len(marks))
    np.testing.assert_array_equal(points, expected_points)
    np.testing.assert_array_equal(labels, expected_labels)


def test_version_with_only_failing_bands_is_unsupported(tmp_path):
    path = tmp_path / "grades.parquet"
    pd.DataFrame({
        "finish_status": ["P", "F"], "grade_version_id": [1.111, 999],
        "from_percent": [60., 0.], "points": [1., 0.], "grade_show": ["D", "F"],
    }).to_parquet(path, index=False)
    scale = GradeScale.from_parquet(path)
    with pytest.raises(ValueError, match="grade_version_id.*999"):
        scale.convert([0.], [999])


def test_empty_pass_bands_cannot_accept_a_version(grade_scale):
    scale = GradeScale(grade_scale.pass_bands.iloc[:0])
    with pytest.raises(ValueError, match="grade_version_id.*1.111"):
        scale.convert([90.], [1.111])
