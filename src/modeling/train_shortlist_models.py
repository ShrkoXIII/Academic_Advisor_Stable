"""Reuse official V2 training mechanics; write exclusively experiment artifacts."""
from datetime import datetime, timezone
import json
from time import perf_counter

import lightgbm as lgb
import numpy as np
import pandas as pd

from src.features.feature_contract import (
    BASE_FEATURES, FEATURE_ENGINEERING_VERSION, learn_category_levels,
    load_category_levels, prepare_model_matrix, require_current_features, save_category_levels,
)
from src.features.frozen_history import file_sha256
from src.modeling import train_models as official
from src.modeling.training_config import TARGET_FAIL, TARGET_GRADE, training_weights
from src.paths import (
    CATEGORY_LEVELS_PATH, COURSE_ONLY_EVALUATION_DIR, COURSE_ONLY_MODEL_DIR,
    FAIL_MODEL_PATH, GRADE_MODEL_PATH, MODEL_METADATA_PATH, PROJECT_ROOT,
    TEMPORAL_TEST_FEATURES_PATH, TEMPORAL_TRAIN_FEATURES_PATH,
)
from .shortlist_features import COURSE_ONLY_FEATURES, REMOVED_CONTEXT_FEATURES, prepare_course_matrix


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    def encode(obj):
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, (pd.Series, pd.DataFrame)):
            return json.loads(obj.to_json())
        if obj is pd.NA:
            return None
        raise TypeError(type(obj).__name__)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=encode), encoding="utf-8")


def training_signature():
    sources = [TEMPORAL_TRAIN_FEATURES_PATH, TEMPORAL_TEST_FEATURES_PATH,
               PROJECT_ROOT / "src/modeling/train_models.py", PROJECT_ROOT / "src/modeling/training_config.py",
               PROJECT_ROOT / "src/features/feature_contract.py", PROJECT_ROOT / "src/modeling/train_shortlist_models.py",
               PROJECT_ROOT / "src/modeling/shortlist_features.py", GRADE_MODEL_PATH,
               FAIL_MODEL_PATH, CATEGORY_LEVELS_PATH, MODEL_METADATA_PATH]
    return {p.relative_to(PROJECT_ROOT).as_posix(): file_sha256(p) for p in sources}


def prepare_course_folds(train):
    """Keep official labels/weights/fold levels, selecting only 33 X columns."""
    folds = official.prepare_folds(train)
    for fold in folds:
        for name in ["fit_X", "valid_X"]:
            fold[name] = fold[name][COURSE_ONLY_FEATURES].copy()
    return folds


def train_experiment():
    """Same finite candidate grid, with CV selection before one 2025 holdout pass."""
    started = perf_counter()
    signature = training_signature()
    columns = list(dict.fromkeys(["student_id", "degree_id", "course_id", "part_id", TARGET_GRADE, TARGET_FAIL, *BASE_FEATURES]))
    train = pd.read_parquet(TEMPORAL_TRAIN_FEATURES_PATH, columns=columns)
    test = pd.read_parquet(TEMPORAL_TEST_FEATURES_PATH, columns=columns)
    require_current_features(train.attrs)
    require_current_features(test.attrs)
    if train.part_id.max() >= test.part_id.min():
        raise ValueError("Training and holdout temporal cutoffs overlap.")
    COURSE_ONLY_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if (COURSE_ONLY_MODEL_DIR / "model_metadata.json").exists():
        raise FileExistsError("Experiment already fitted; use --skip-training after verifying its signature.")
    prepared = prepare_course_folds(train)
    selections = {}
    for task in ["grade", "fail"]:
        print(f"Starting 33-feature {task} validation: same three candidates / two folds", flush=True)
        best, reports = official.tune_model(prepared, task)
        selections[task] = best
        write_json(COURSE_ONLY_EVALUATION_DIR / f"{task}_validation.json", {"best": best, "all_candidates": reports})
    levels = learn_category_levels(train)
    train_x, test_x = prepare_course_matrix(train, levels), prepare_course_matrix(test, levels)
    weight = training_weights(train).to_numpy(dtype="float32")
    metadata = {
        "experiment": "course_only_recommendation", "dataset_version": "V2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
        "feature_contract": {"model_features": COURSE_ONLY_FEATURES, "feature_count": 33,
                             "removed_features": sorted(REMOVED_CONTEXT_FEATURES)},
        "training_as_of_part": int(train.part_id.max()), "train_rows": len(train), "test_rows": len(test),
        "temporal_folds": official.TEMPORAL_FOLDS,
        "training_weight": {"before_2022": .25, "from_2022": 1., "fit_only": True},
        "seed": official.SEED, "input_sha256": signature,
        "holdout_history_protocol": "existing_V2_features_sequential_roll_forward",
    }
    predictions = test[["student_id", "degree_id", "course_id", "part_id", TARGET_GRADE, TARGET_FAIL]].copy()
    official_levels = load_category_levels(CATEGORY_LEVELS_PATH)
    official_x = prepare_model_matrix(test, official_levels)
    baseline_metadata = json.loads(MODEL_METADATA_PATH.read_text(encoding="utf-8"))
    for task, target, model_path, baseline_path, section, metric in [
        ("grade", TARGET_GRADE, "grade_regressor.txt", GRADE_MODEL_PATH, "grade_regressor", official.regression_metrics),
        ("fail", TARGET_FAIL, "fail_risk_classifier.txt", FAIL_MODEL_PATH, "fail_risk_classifier", official.classification_metrics),
    ]:
        selected = selections[task]
        task_params = {"objective": "regression", "metric": "l1"} if task == "grade" else {"objective": "binary", "metric": "binary_logloss"}
        params = {**official.shared_parameters(selected["candidate"]), **task_params}
        y = pd.to_numeric(train[target]).to_numpy(dtype="float64" if task == "grade" else "int64")
        model = official.train_one(train_x, y, weight, params, num_boost_round=max(1, selected["mean_best_iteration"]))
        if model.feature_name() != COURSE_ONLY_FEATURES:
            raise ValueError("Fitted model does not match the ordered 33-feature contract.")
        model.save_model(str(COURSE_ONLY_MODEL_DIR / model_path))
        maximum = 100 if task == "grade" else 1
        experimental = np.clip(model.predict(test_x, num_threads=4), 0, maximum)
        baseline = np.clip(lgb.Booster(model_file=str(baseline_path)).predict(official_x, num_threads=4), 0, maximum)
        metadata[task] = {"selected_candidate": selected, "parameters": params,
                          "final_boost_rounds": max(1, selected["mean_best_iteration"]),
                          "experimental_test_metrics": metric(test[target], experimental),
                          "official_test_metrics_fresh": metric(test[target], baseline),
                          "official_cv_mean_saved": baseline_metadata[section]["selected_candidate"]["mean_primary_metric"],
                          "official_cv_provenance": "saved official metadata; not retrained in this experiment",
                          "feature_importance": official.feature_importance(model)}
        predictions[f"{task}_prediction_33"] = experimental
        predictions[f"{task}_prediction_47"] = baseline
        print(task, metadata[task]["experimental_test_metrics"], flush=True)
    save_category_levels(levels, COURSE_ONLY_MODEL_DIR / "category_levels.json")
    metadata["training_seconds"] = perf_counter() - started
    metadata["artifact_sha256"] = {p.name: file_sha256(p) for p in COURSE_ONLY_MODEL_DIR.iterdir() if p.is_file()}
    write_json(COURSE_ONLY_MODEL_DIR / "model_metadata.json", metadata)
    predictions.to_parquet(COURSE_ONLY_EVALUATION_DIR / "holdout_predictions.parquet", index=False)
    write_json(COURSE_ONLY_EVALUATION_DIR / "model_comparison.json", metadata)
    return metadata


def load_experiment():
    metadata = json.loads((COURSE_ONLY_MODEL_DIR / "model_metadata.json").read_text(encoding="utf-8"))
    require_current_features(metadata)
    if metadata["feature_contract"]["model_features"] != COURSE_ONLY_FEATURES or metadata["input_sha256"] != training_signature():
        raise ValueError("Experiment feature contract or input/source signature changed; refuse stale models.")
    for name, digest in metadata["artifact_sha256"].items():
        if file_sha256(COURSE_ONLY_MODEL_DIR / name) != digest:
            raise ValueError(f"Experimental artifact changed: {name}")
    grade = lgb.Booster(model_file=str(COURSE_ONLY_MODEL_DIR / "grade_regressor.txt"))
    fail = lgb.Booster(model_file=str(COURSE_ONLY_MODEL_DIR / "fail_risk_classifier.txt"))
    if grade.feature_name() != COURSE_ONLY_FEATURES or fail.feature_name() != COURSE_ONLY_FEATURES:
        raise ValueError("Experimental model headers must contain exactly the ordered 33 features.")
    return grade, fail, load_category_levels(COURSE_ONLY_MODEL_DIR / "category_levels.json"), metadata


if __name__ == "__main__":
    train_experiment()
