from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
from src.modeling.training_config import TARGET_FAIL, TARGET_GRADE, training_weights
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)

try:
    from src.features.feature_contract import (
        CATEGORICAL_FEATURES,
        FEATURE_ENGINEERING_VERSION,
        BASE_FEATURES,
        NUMERIC_FEATURES,
        learn_category_levels,
        prepare_model_matrix,
        require_current_features,
        save_category_levels,
    )
    from ..paths import (
        CATEGORY_LEVELS_PATH,
        FAIL_MODEL_PATH,
        GRADE_MODEL_PATH,
        MODEL_METADATA_PATH,
        PROJECT_ROOT,
        TEMPORAL_TEST_FEATURES_PATH,
        TEMPORAL_TRAIN_FEATURES_PATH,
    )
except ImportError:
    from src.features.feature_contract import (
        CATEGORICAL_FEATURES,
        FEATURE_ENGINEERING_VERSION,
        BASE_FEATURES,
        NUMERIC_FEATURES,
        learn_category_levels,
        prepare_model_matrix,
        require_current_features,
        save_category_levels,
    )
    from src.paths import (
        CATEGORY_LEVELS_PATH,
        FAIL_MODEL_PATH,
        GRADE_MODEL_PATH,
        MODEL_METADATA_PATH,
        PROJECT_ROOT,
        TEMPORAL_TEST_FEATURES_PATH,
        TEMPORAL_TRAIN_FEATURES_PATH,
    )


SEED = 42
MAX_BOOST_ROUNDS = 900
EARLY_STOPPING_ROUNDS = 75

TEMPORAL_FOLDS = [
    {
        "name": "train_through_2022_validate_2023",
        "train_through": 20223,
        "valid_from": 20231,
        "valid_through": 20233,
    },
    {
        "name": "train_through_2023_validate_2024",
        "train_through": 20233,
        "valid_from": 20241,
        "valid_through": 20243,
    },
]

PARAMETER_CANDIDATES = [
    {
        "name": "balanced_31",
        "num_leaves": 31,
        "min_data_in_leaf": 80,
        "feature_fraction": 0.90,
        "bagging_fraction": 0.90,
        "lambda_l1": 0.10,
        "lambda_l2": 1.00,
    },
    {
        "name": "capacity_63",
        "num_leaves": 63,
        "min_data_in_leaf": 100,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.90,
        "lambda_l1": 0.20,
        "lambda_l2": 2.00,
    },
    {
        "name": "regularized_47",
        "num_leaves": 47,
        "min_data_in_leaf": 160,
        "feature_fraction": 0.80,
        "bagging_fraction": 0.85,
        "lambda_l1": 0.50,
        "lambda_l2": 4.00,
    },
]


def _lightgbm():
    import lightgbm as lgb

    return lgb


def regression_metrics(actual, predicted):
    error = np.abs(np.asarray(actual, dtype="float64") - predicted)
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "within_5": float(np.mean(error <= 5)),
        "within_10": float(np.mean(error <= 10)),
    }


def classification_metrics(actual, probability):
    probability = np.clip(np.asarray(probability, dtype="float64"), 1e-7, 1 - 1e-7)
    actual_array = np.asarray(actual, dtype="int64")
    bin_id = np.minimum((probability * 10).astype("int64"), 9)
    calibration_error = 0.0
    for current_bin in range(10):
        in_bin = bin_id == current_bin
        if in_bin.any():
            calibration_error += float(in_bin.mean()) * abs(
                float(probability[in_bin].mean())
                - float(actual_array[in_bin].mean())
            )
    return {
        "pr_auc": float(average_precision_score(actual, probability)),
        "roc_auc": float(roc_auc_score(actual, probability)),
        "brier": float(brier_score_loss(actual, probability)),
        "log_loss": float(log_loss(actual, probability, labels=[0, 1])),
        "calibration_error_10_bins": calibration_error,
    }


def calibration_table(actual, probability):
    probability = np.clip(np.asarray(probability, dtype="float64"), 0, 1)
    actual = np.asarray(actual, dtype="int64")
    bin_id = np.minimum((probability * 10).astype("int64"), 9)
    rows = []
    for current_bin in range(10):
        in_bin = bin_id == current_bin
        if in_bin.any():
            rows.append(
                {
                    "bin": current_bin,
                    "from_probability": current_bin / 10,
                    "to_probability": (current_bin + 1) / 10,
                    "rows": int(in_bin.sum()),
                    "mean_predicted_probability": float(
                        probability[in_bin].mean()
                    ),
                    "observed_fail_rate": float(actual[in_bin].mean()),
                }
            )
    return rows


def shared_parameters(candidate):
    return {
        "learning_rate": 0.04,
        "num_leaves": candidate["num_leaves"],
        "min_data_in_leaf": candidate["min_data_in_leaf"],
        "feature_fraction": candidate["feature_fraction"],
        "bagging_fraction": candidate["bagging_fraction"],
        "bagging_freq": 1,
        "lambda_l1": candidate["lambda_l1"],
        "lambda_l2": candidate["lambda_l2"],
        "max_bin": 255,
        "verbosity": -1,
        "seed": SEED,
        "feature_fraction_seed": SEED,
        "bagging_seed": SEED,
        "data_random_seed": SEED,
        "deterministic": True,
        "force_col_wise": True,
        "num_threads": 0,
    }


def prepare_folds(train):
    prepared = []
    for fold in TEMPORAL_FOLDS:
        fit_rows = train["part_id"].le(fold["train_through"])
        valid_rows = train["part_id"].between(
            fold["valid_from"], fold["valid_through"]
        )
        fit = train.loc[fit_rows]
        valid = train.loc[valid_rows]
        levels = learn_category_levels(fit)
        prepared.append(
            {
                **fold,
                "fit_X": prepare_model_matrix(fit, levels),
                "valid_X": prepare_model_matrix(valid, levels),
                "fit_grade": pd.to_numeric(fit[TARGET_GRADE]).to_numpy(
                    dtype="float64"
                ),
                "valid_grade": pd.to_numeric(valid[TARGET_GRADE]).to_numpy(
                    dtype="float64"
                ),
                "fit_fail": pd.to_numeric(fit[TARGET_FAIL]).to_numpy(
                    dtype="int64"
                ),
                "valid_fail": pd.to_numeric(valid[TARGET_FAIL]).to_numpy(
                    dtype="int64"
                ),
                "fit_weight": training_weights(fit).to_numpy(dtype="float32"),
                "fit_rows": int(fit_rows.sum()),
                "valid_rows": int(valid_rows.sum()),
            }
        )
    return prepared


def train_one(
    fit_X,
    fit_y,
    fit_weight,
    parameters,
    valid_X=None,
    valid_y=None,
    num_boost_round=MAX_BOOST_ROUNDS,
):
    lgb = _lightgbm()
    train_set = lgb.Dataset(
        fit_X,
        label=fit_y,
        weight=fit_weight,
        categorical_feature=CATEGORICAL_FEATURES,
        free_raw_data=False,
    )
    valid_sets = None
    callbacks = [lgb.log_evaluation(period=0)]
    if valid_X is not None:
        valid_set = lgb.Dataset(
            valid_X,
            label=valid_y,
            reference=train_set,
            categorical_feature=CATEGORICAL_FEATURES,
            free_raw_data=False,
        )
        valid_sets = [valid_set]
        callbacks.append(
            lgb.early_stopping(
                EARLY_STOPPING_ROUNDS,
                first_metric_only=True,
                verbose=False,
            )
        )

    return lgb.train(
        parameters,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=valid_sets,
        callbacks=callbacks,
    )


def tune_model(prepared_folds, task):
    reports = []
    for candidate in PARAMETER_CANDIDATES:
        fold_reports = []
        for fold in prepared_folds:
            if task == "grade":
                fit_y = fold["fit_grade"]
                valid_y = fold["valid_grade"]
                task_parameters = {
                    "objective": "regression",
                    "metric": "l1",
                }
                metric_function = regression_metrics
            else:
                fit_y = fold["fit_fail"]
                valid_y = fold["valid_fail"]
                task_parameters = {
                    "objective": "binary",
                    "metric": "binary_logloss",
                }
                metric_function = classification_metrics

            parameters = {**shared_parameters(candidate), **task_parameters}
            model = train_one(
                fold["fit_X"],
                fit_y,
                fold["fit_weight"],
                parameters,
                fold["valid_X"],
                valid_y,
            )
            prediction = model.predict(
                fold["valid_X"],
                num_iteration=model.best_iteration,
            )
            metrics = metric_function(valid_y, prediction)
            fold_reports.append(
                {
                    "fold": fold["name"],
                    "fit_rows": fold["fit_rows"],
                    "valid_rows": fold["valid_rows"],
                    "best_iteration": int(model.best_iteration),
                    "metrics": metrics,
                }
            )
            primary = metrics["mae" if task == "grade" else "log_loss"]
            print(
                f"{task} | {candidate['name']} | {fold['name']} | "
                f"best_iteration={model.best_iteration} | score={primary:.6f}"
            )

        primary_name = "mae" if task == "grade" else "log_loss"
        reports.append(
            {
                "candidate": candidate,
                "folds": fold_reports,
                "mean_primary_metric": float(
                    np.mean(
                        [report["metrics"][primary_name] for report in fold_reports]
                    )
                ),
                "mean_best_iteration": int(
                    round(
                        np.mean(
                            [report["best_iteration"] for report in fold_reports]
                        )
                    )
                ),
            }
        )
    return min(reports, key=lambda report: report["mean_primary_metric"]), reports


def feature_importance(model):
    importance = pd.DataFrame(
        {
            "feature": model.feature_name(),
            "gain": model.feature_importance(importance_type="gain"),
        }
    ).sort_values("gain", ascending=False)
    total = importance["gain"].sum()
    importance["gain_share"] = importance["gain"] / total
    return importance.head(25).to_dict(orient="records")


def _json_default(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def main():
    data_columns = list(
        dict.fromkeys(["part_id", TARGET_GRADE, TARGET_FAIL, *BASE_FEATURES])
    )
    train = pd.read_parquet(TEMPORAL_TRAIN_FEATURES_PATH, columns=data_columns)
    test = pd.read_parquet(TEMPORAL_TEST_FEATURES_PATH, columns=data_columns)
    require_current_features(train.attrs)
    require_current_features(test.attrs)

    prepared_folds = prepare_folds(train)
    best_grade, grade_candidates = tune_model(prepared_folds, "grade")
    best_fail, fail_candidates = tune_model(prepared_folds, "fail")

    final_levels = learn_category_levels(train)
    final_train_X = prepare_model_matrix(train, final_levels)
    final_test_X = prepare_model_matrix(test, final_levels)
    final_weight = training_weights(train).to_numpy(dtype="float32")

    grade_parameters = {
        **shared_parameters(best_grade["candidate"]),
        "objective": "regression",
        "metric": "l1",
    }
    fail_parameters = {
        **shared_parameters(best_fail["candidate"]),
        "objective": "binary",
        "metric": "binary_logloss",
    }

    grade_model = train_one(
        final_train_X,
        pd.to_numeric(train[TARGET_GRADE]).to_numpy(dtype="float64"),
        final_weight,
        grade_parameters,
        num_boost_round=max(1, best_grade["mean_best_iteration"]),
    )
    fail_model = train_one(
        final_train_X,
        pd.to_numeric(train[TARGET_FAIL]).to_numpy(dtype="int64"),
        final_weight,
        fail_parameters,
        num_boost_round=max(1, best_fail["mean_best_iteration"]),
    )

    grade_prediction = np.clip(grade_model.predict(final_test_X), 0, 100)
    fail_probability = np.clip(fail_model.predict(final_test_X), 0, 1)
    grade_test_metrics = regression_metrics(test[TARGET_GRADE], grade_prediction)
    fail_test_metrics = classification_metrics(test[TARGET_FAIL], fail_probability)

    GRADE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    grade_model.save_model(str(GRADE_MODEL_PATH))
    fail_model.save_model(str(FAIL_MODEL_PATH))
    save_category_levels(final_levels, CATEGORY_LEVELS_PATH)

    metadata = {
        "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_family": "LightGBM",
        "feature_contract": {
            "model_features": BASE_FEATURES,
            "numeric_features": NUMERIC_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
            "feature_count": len(BASE_FEATURES),
        },
        "targets": {
            "grade_regressor": "final_mark",
            "fail_risk_classifier": "(final_mark < 50).astype(int)",
        },
        "training_weight": {
            "before_2022": 0.25,
            "from_2022": 1.0,
            "applied_only_during_fit": True,
        },
        "course_history": {
            "training_walk_forward": True,
            "initial_history_cutoff": 20243,
            "test_protocol": "sequential_roll_forward",
            "test_history_cutoffs": {"20251": 20243, "20252": 20251},
            "update_after_finalized_outcomes": True,
            "smoothing_k": 20,
        },
        "temporal_validation": TEMPORAL_FOLDS,
        "grade_regressor": {
            "selected_candidate": best_grade,
            "all_candidates": grade_candidates,
            "parameters": grade_parameters,
            "final_boost_rounds": best_grade["mean_best_iteration"],
            "test_2025_metrics": grade_test_metrics,
            "top_feature_importance": feature_importance(grade_model),
        },
        "fail_risk_classifier": {
            "selected_candidate": best_fail,
            "all_candidates": fail_candidates,
            "parameters": fail_parameters,
            "final_boost_rounds": best_fail["mean_best_iteration"],
            "uses_class_weights": False,
            "test_2025_metrics": fail_test_metrics,
            "test_2025_calibration": calibration_table(
                test[TARGET_FAIL], fail_probability
            ),
            "top_feature_importance": feature_importance(fail_model),
        },
        "artifacts": {
            "grade_model": GRADE_MODEL_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "fail_model": FAIL_MODEL_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "category_levels": CATEGORY_LEVELS_PATH.relative_to(
                PROJECT_ROOT
            ).as_posix(),
            "model_metadata": MODEL_METADATA_PATH.relative_to(PROJECT_ROOT).as_posix(),
        },
    }
    MODEL_METADATA_PATH.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        ),
        encoding="utf-8",
    )

    print("\nSelected grade candidate:", best_grade["candidate"]["name"])
    print("2025 grade metrics:", grade_test_metrics)
    print("Selected fail candidate:", best_fail["candidate"]["name"])
    print("2025 fail metrics:", fail_test_metrics)
    print("Saved:", GRADE_MODEL_PATH)
    print("Saved:", FAIL_MODEL_PATH)
    print("Saved:", CATEGORY_LEVELS_PATH)
    print("Saved:", MODEL_METADATA_PATH)


if __name__ == "__main__":
    main()
