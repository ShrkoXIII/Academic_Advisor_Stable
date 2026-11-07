from collections import Counter
import math
import runpy

import numpy as np
import pandas as pd
import pytest

from src.features.feature_contract import (
    BASE_FEATURES,
    CATEGORICAL_FEATURES,
    CATEGORY_MISSING,
    CATEGORY_UNKNOWN,
    NUMERIC_FEATURES,
)
from src.modeling import train_models


def test_regression_metrics_known_errors_and_inclusive_boundaries():
    # Absolute errors 0, 5, 10, 15: MAE=7.5, MSE=87.5.
    result = train_models.regression_metrics([20, 40, 60, 80], np.array([20, 45, 50, 95]))
    assert result == pytest.approx(
        {"mae": 7.5, "rmse": math.sqrt(87.5), "within_5": 0.5, "within_10": 0.75}
    )


def test_classification_metrics_known_ranking_and_probabilities():
    result = train_models.classification_metrics([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
    # Positive ranks 1 and 3 give AP=(1 + 2/3)/2; three of four pairs agree.
    assert result == pytest.approx(
        {
            "pr_auc": 5 / 6,
            "roc_auc": 0.75,
            "brier": 0.158125,
            "log_loss": -math.log(0.9 * 0.6 * 0.35 * 0.8) / 4,
            "calibration_error_10_bins": 0.3375,
        }
    )
    assert all(math.isfinite(value) for value in result.values())


def test_classification_metrics_clips_endpoint_probabilities():
    result = train_models.classification_metrics([0, 1], [0.0, 1.0])
    assert result["log_loss"] == pytest.approx(-math.log(1 - 1e-7))
    assert result["brier"] == pytest.approx(1e-14, abs=1e-20)
    assert result["calibration_error_10_bins"] == pytest.approx(1e-7)


def test_calibration_table_returns_only_populated_bins_with_correct_aggregates():
    rows = train_models.calibration_table(
        [0, 1, 0, 1, 0, 1], [0.0, 0.04, 0.09, 0.2, 0.24, 1.0]
    )
    expected = [
        {"bin": 0, "from_probability": 0.0, "to_probability": 0.1, "rows": 3,
         "mean_predicted_probability": 0.13 / 3, "observed_fail_rate": 1 / 3},
        {"bin": 2, "from_probability": 0.2, "to_probability": 0.3, "rows": 2,
         "mean_predicted_probability": 0.22, "observed_fail_rate": 0.5},
        {"bin": 9, "from_probability": 0.9, "to_probability": 1.0, "rows": 1,
         "mean_predicted_probability": 1.0, "observed_fail_rate": 1.0},
    ]
    assert len(rows) == 3
    for actual, wanted in zip(rows, expected):
        assert actual == pytest.approx(wanted)


def test_shared_parameters_copies_candidate_and_keeps_deterministic_defaults():
    candidate = {
        "name": "synthetic", "num_leaves": 17, "min_data_in_leaf": 9,
        "feature_fraction": 0.7, "bagging_fraction": 0.8, "lambda_l1": 0.3,
        "lambda_l2": 1.7,
    }
    original = candidate.copy()
    assert train_models.shared_parameters(candidate) == {
        "learning_rate": 0.04, "num_leaves": 17, "min_data_in_leaf": 9,
        "feature_fraction": 0.7, "bagging_fraction": 0.8, "bagging_freq": 1,
        "lambda_l1": 0.3, "lambda_l2": 1.7, "max_bin": 255, "verbosity": -1,
        "seed": 42, "feature_fraction_seed": 42, "bagging_seed": 42,
        "data_random_seed": 42, "deterministic": True, "force_col_wise": True,
        "num_threads": 0,
    }
    assert candidate == original


@pytest.fixture
def temporal_frame():
    parts = [20243, 20221, 20231, 20251, 20223, 20241, 20193, 20233]
    categories = ["new_2024", "known", "new_2023", "new_2025",
                  "known", "new_2024", "known", "new_2023"]
    return pd.DataFrame(
        {
            **{column: np.arange(8) for column in NUMERIC_FEATURES},
            **{column: categories for column in CATEGORICAL_FEATURES},
            "part_id": parts,
            "final_mark": [40, 70, 45, 60, 30, 80, 65, 75],
            "is_fail": [1, 0, 1, 0, 1, 0, 0, 0],
        },
        index=[80, 20, 40, 90, 30, 70, 10, 50],
    )


def test_prepare_folds_preserves_temporal_boundaries_targets_and_weights(temporal_frame):
    original = temporal_frame.copy(deep=True)
    folds = train_models.prepare_folds(temporal_frame)
    assert [fold["name"] for fold in folds] == [
        "train_through_2022_validate_2023", "train_through_2023_validate_2024"
    ]
    expected = [
        ([20, 30, 10], [40, 50], 20223, 20231, 20233, [1, 1, 0.25]),
        ([20, 40, 30, 10, 50], [80, 70], 20233, 20241, 20243, [1, 1, 1, 0.25, 1]),
    ]
    for fold, (fit_index, valid_index, cutoff, start, end, weights) in zip(folds, expected):
        assert (fold["train_through"], fold["valid_from"], fold["valid_through"]) == (cutoff, start, end)
        assert fold["fit_X"].index.tolist() == fit_index
        assert fold["valid_X"].index.tolist() == valid_index
        assert fold["fit_rows"] == len(fit_index)
        assert fold["valid_rows"] == len(valid_index)
        assert temporal_frame.loc[fit_index, "part_id"].le(cutoff).all()
        assert temporal_frame.loc[valid_index, "part_id"].between(start, end).all()
        for split, index in [("fit", fit_index), ("valid", valid_index)]:
            assert fold[f"{split}_X"].columns.tolist() == BASE_FEATURES
            np.testing.assert_array_equal(fold[f"{split}_grade"], temporal_frame.loc[index, "final_mark"])
            np.testing.assert_array_equal(fold[f"{split}_fail"], temporal_frame.loc[index, "is_fail"])
        np.testing.assert_array_equal(fold["fit_weight"], weights)
        assert fold["fit_weight"].dtype == np.dtype("float32")
    pd.testing.assert_frame_equal(temporal_frame, original)


def test_prepare_folds_learns_categories_only_from_each_fit_subset(temporal_frame):
    first, second = train_models.prepare_folds(temporal_frame)
    for column in CATEGORICAL_FEATURES:
        for fold, learned in [(first, ["known"]), (second, ["known", "new_2023"])]:
            expected = [CATEGORY_MISSING, CATEGORY_UNKNOWN, *learned]
            assert fold["fit_X"][column].cat.categories.tolist() == expected
            assert fold["valid_X"][column].cat.categories.tolist() == expected
            assert fold["valid_X"][column].tolist() == [CATEGORY_UNKNOWN, CATEGORY_UNKNOWN]
        assert second["fit_X"].loc[[40, 50], column].tolist() == ["new_2023", "new_2023"]


@pytest.mark.parametrize(
    ("task", "winner", "primary"),
    [("grade", "capacity_63", "mae"), ("fail", "regularized_47", "log_loss")],
)
def test_tune_model_evaluates_every_candidate_fold_and_selects_mean_metric(
    monkeypatch, temporal_frame, task, winner, primary
):
    folds = train_models.prepare_folds(temporal_frame)
    calls = []
    # The best first fold does not win the mean; grade's best last fold also loses.
    errors = {31: [1.0, 9.0], 63: [4.0, 4.0], 47: [8.0, 2.0]}
    correct_probabilities = {31: [0.95, 0.2], 63: [0.6, 0.6], 47: [0.75, 0.75]}

    def fake_train_one(fit_X, fit_y, fit_weight, parameters, valid_X, valid_y):
        fold_number = next(i for i, fold in enumerate(folds) if fold["fit_X"] is fit_X)
        fold = folds[fold_number]
        leaves = parameters["num_leaves"]
        calls.append((leaves, fold["name"]))
        assert valid_X is fold["valid_X"]
        assert fit_y is fold[f"fit_{task}"]
        assert valid_y is fold[f"valid_{task}"]
        assert fit_weight is fold["fit_weight"]
        assert parameters["objective"] == ("regression" if task == "grade" else "binary")
        assert parameters["metric"] == ("l1" if task == "grade" else "binary_logloss")

        class FakeModel:
            best_iteration = 10 + 2 * fold_number

            def predict(self, matrix, num_iteration):
                assert matrix is valid_X
                assert num_iteration == self.best_iteration
                if task == "grade":
                    return valid_y + errors[leaves][fold_number]
                correct = correct_probabilities[leaves][fold_number]
                return np.where(valid_y == 1, correct, 1 - correct)

        return FakeModel()

    monkeypatch.setattr(train_models, "train_one", fake_train_one)
    best, reports = train_models.tune_model(folds, task)
    assert Counter(calls) == Counter(
        (leaves, name)
        for leaves in [31, 63, 47]
        for name in ["train_through_2022_validate_2023", "train_through_2023_validate_2024"]
    )
    assert len(calls) == 6
    assert len(reports) == 3
    assert best["candidate"]["name"] == winner
    for report in reports:
        leaves = report["candidate"]["num_leaves"]
        scores = errors[leaves] if task == "grade" else [
            -math.log(p) for p in correct_probabilities[leaves]
        ]
        assert report["mean_primary_metric"] == pytest.approx(sum(scores) / 2)
        assert report["mean_best_iteration"] == 11
        assert len(report["folds"]) == 2
        for i, fold_report in enumerate(report["folds"]):
            assert fold_report["fold"] == folds[i]["name"]
            assert fold_report["fit_rows"] == folds[i]["fit_rows"]
            assert fold_report["valid_rows"] == folds[i]["valid_rows"]
            assert fold_report["best_iteration"] == 10 + 2 * i
            assert fold_report["metrics"][primary] == pytest.approx(scores[i])


class FakeImportanceModel:
    def __init__(self, gains):
        self.gains = gains

    def feature_name(self):
        return [f"feature_{i}" for i in range(len(self.gains))]

    def feature_importance(self, importance_type):
        assert importance_type == "gain"
        return self.gains


def test_feature_importance_sorts_descending_and_normalizes_gain():
    result = train_models.feature_importance(FakeImportanceModel([2, 6, 0]))
    assert [row["feature"] for row in result] == ["feature_1", "feature_0", "feature_2"]
    assert [row["gain"] for row in result] == [6, 2, 0]
    assert [row["gain_share"] for row in result] == pytest.approx([0.75, 0.25, 0.0])
    assert sum(row["gain_share"] for row in result) == pytest.approx(1.0)


def test_feature_importance_returns_top_25_without_renormalizing():
    result = train_models.feature_importance(FakeImportanceModel(list(range(1, 31))))
    assert len(result) == 25
    assert [row["feature"] for row in result] == [f"feature_{i}" for i in range(29, 4, -1)]
    assert [row["gain"] for row in result] == list(range(30, 5, -1))
    # Total gain is 465; the omitted five features contribute 15.
    assert sum(row["gain_share"] for row in result) == pytest.approx(450 / 465)


def test_trainer_imports_as_a_script_without_running_training(monkeypatch):
    monkeypatch.syspath_prepend(str(train_models.PROJECT_ROOT / "src" / "modeling"))
    namespace = runpy.run_path(train_models.__file__, run_name="import_smoke_test")
    assert namespace["PROJECT_ROOT"] == train_models.PROJECT_ROOT
    assert namespace["TARGET_GRADE"] == "final_mark"
