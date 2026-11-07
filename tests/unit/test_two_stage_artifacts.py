"""Synthetic artifact promotion and load tests; never fit or score real students."""
import ast
import builtins
import hashlib
import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.features.feature_contract import BASE_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES
from src.features.temporal_features import PLAN_CONTEXT_COLUMNS


SOURCE_DIR = "models/shortlist_training"
PROMOTED_DIR = "models/shortlist"
OFFICIAL_ARTIFACTS = {
    "grade_model": "models/grade_regressor.txt",
    "fail_model": "models/fail_risk_classifier.txt",
    "category_levels": "data/artifacts/category_levels.json",
    "model_metadata": "models/model_metadata.json",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def expected_contract(stage):
    features = [name for name in BASE_FEATURES if stage == "stage2" or name not in PLAN_CONTEXT_COLUMNS]
    contract = {
        "model_features": features,
        "numeric_features": [name for name in NUMERIC_FEATURES if name in features],
        "categorical_features": list(CATEGORICAL_FEATURES),
        "feature_count": len(features),
    }
    if stage == "stage1":
        contract["removed_features"] = sorted(PLAN_CONTEXT_COLUMNS)
    return contract


class FakeBooster:
    """A serialized model fixture exposing LightGBM's inspection/predict API."""

    def __init__(self, model_file):
        self.payload = read_json(Path(model_file))
        self.pandas_categorical = self.payload["categories"]
        self.params = {"objective": self.payload["objective"]}

    def feature_name(self):
        return self.payload["features"]

    def num_feature(self):
        return self.payload.get("feature_count", len(self.payload["features"]))

    def dump_model(self):
        return {"objective": self.payload["objective"], "feature_names": self.feature_name(),
                "pandas_categorical": self.pandas_categorical}

    def predict(self, matrix, **kwargs):
        return self.payload["constant"] + np.asarray(matrix.iloc[:, 0], dtype="float64") * .125


@pytest.fixture
def artifact_root(tmp_path, monkeypatch):
    """Reproduce the source metadata layouts using tiny local synthetic files."""
    import lightgbm

    monkeypatch.setattr(lightgbm, "Booster", FakeBooster)
    levels = {name: ["__MISSING__", "__UNKNOWN__", f"{name}_1", f"{name}_2"] for name in CATEGORICAL_FEATURES}
    for stage, directory, grade_name, fail_name, category_path in [
        ("stage1", SOURCE_DIR, "grade_regressor.txt", "fail_risk_classifier.txt", f"{SOURCE_DIR}/category_levels.json"),
        ("stage2", "models", "grade_regressor.txt", "fail_risk_classifier.txt", OFFICIAL_ARTIFACTS["category_levels"]),
    ]:
        for name, objective, constant in [(grade_name, "regression", 60), (fail_name, "binary", .2)]:
            write_json(tmp_path / directory / name, {
                "features": expected_contract(stage)["model_features"],
                "categories": [levels[name] for name in CATEGORICAL_FEATURES],
                "objective": objective, "constant": constant,
            })
        write_json(tmp_path / category_path, levels)
    official = {
        "feature_engineering_version": 2,
        "feature_contract": expected_contract("stage2"),
        "targets": {"grade_regressor": "final_mark", "fail_risk_classifier": "(final_mark < 50).astype(int)"},
        "course_history": {"initial_history_cutoff": 20243, "test_state_frozen_after_part": 20251},
        "grade_regressor": {"selected_candidate": {"candidate": {"name": "capacity_63"}}, "parameters": {"objective": "regression"}},
        "fail_risk_classifier": {"selected_candidate": {"candidate": {"name": "balanced_31"}}, "parameters": {"objective": "binary"}},
        "artifacts": OFFICIAL_ARTIFACTS,
    }
    for section in ("grade_regressor", "fail_risk_classifier"):
        official[section]["selected_candidate"]["mean_primary_metric"] = 1.0
        official[section]["all_candidates"] = [official[section]["selected_candidate"]]
    write_json(tmp_path / OFFICIAL_ARTIFACTS["model_metadata"], official)
    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"finish_status": ["F", "P", "P"], "grade_version_id": [1, 1, 1],
                  "from_percent": [0, 50, 80], "points": [0, 2, 4], "grade_show": ["F", "C", "A"]}).to_parquet(
        tmp_path / "data/raw/v_acs_grade.parquet", index=False,
    )
    sources = {
        "src/modeling/train_models.py": "# Synthetic trainer source; never imported.\n",
        "src/modeling/training_config.py": "TARGET_GRADE = 'final_mark'\nTARGET_FAIL = 'is_fail'\n",
        "src/features/feature_contract.py": "# Synthetic original feature-contract source snapshot.\n",
        "src/features/build_temporal_features.py": "frame['is_fail'] = frame['final_mark'].lt(50).astype(int)\n",
        "src/modeling/train_shortlist_models.py": "# Synthetic course-only trainer source; never imported.\n",
        "src/modeling/shortlist_features.py": "# Synthetic course-only matrix source.\n",
        "src/grade_scale.py": "# Synthetic GradeScale source evidence.\n",
        "data/features/temporal_train_features.parquet": "synthetic training dataset bytes",
        "data/features/temporal_test_features.parquet": "synthetic holdout dataset bytes",
    }
    for relative, contents in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    signed_inputs = [
        "data/features/temporal_train_features.parquet", "data/features/temporal_test_features.parquet",
        "src/modeling/train_models.py", "src/modeling/training_config.py", "src/features/feature_contract.py",
        "src/modeling/train_shortlist_models.py", "src/modeling/shortlist_features.py",
        *OFFICIAL_ARTIFACTS.values(),
    ]
    first_contract = expected_contract("stage1")
    source = {
        "experiment": "course_only_recommendation", "dataset_version": "V2", "feature_engineering_version": 2,
        "feature_contract": {key: first_contract[key] for key in ["model_features", "feature_count", "removed_features"]},
        "training_as_of_part": 20243,
        "grade": {"selected_candidate": {"candidate": {"name": "capaciy_63"}}, "parameters": {"objective": "regression"}},
        "fail": {"selected_candidate": {"candidate": {"name": "balanced_31"}}, "parameters": {"objective": "binary"}},
        "input_sha256": {relative: digest(tmp_path / relative) for relative in signed_inputs},
        "artifact_sha256": {name: digest(tmp_path / SOURCE_DIR / name)
                            for name in ["grade_regressor.txt", "fail_risk_classifier.txt", "category_levels.json"]},
    }
    write_json(tmp_path / SOURCE_DIR / "model_metadata.json", source)
    history = tmp_path / "data/artifacts/history/as_of_20243/course_history_state.pkl"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_bytes(b"synthetic protected Frozen History")
    return tmp_path


def promote(root):
    return importlib.import_module("src.modeling.build_artifact_manifest").promote_shortlist_artifacts(project_root=root)


def load(root, target_part=20251):
    return importlib.import_module("src.recommendation.two_stage_artifacts").load_two_stage_artifacts(
        project_root=root, target_part=target_part,
    )


def promoted_files(root):
    return {path.name: digest(path) for path in (root / PROMOTED_DIR).iterdir() if path.is_file()}


def refresh_model_hash(root, stage, role):
    path = root / PROMOTED_DIR / "manifest.json"
    manifest = read_json(path)
    model = manifest["stages"][stage]["models"][role]
    model["sha256"] = digest(root / model["path"])
    write_json(path, manifest)


def mutate_manifest(root, mutation):
    path = root / PROMOTED_DIR / "manifest.json"
    manifest = read_json(path)
    mutation(manifest)
    write_json(path, manifest)


def test_stage_contracts_derive_33_and_47_from_the_official_order():
    artifacts = importlib.import_module("src.recommendation.two_stage_artifacts")
    first = artifacts.stage_feature_contract("stage1")
    second = artifacts.stage_feature_contract("stage2")
    assert first["model_features"] == [name for name in BASE_FEATURES if name not in PLAN_CONTEXT_COLUMNS]
    assert first["numeric_features"] == [name for name in NUMERIC_FEATURES if name not in PLAN_CONTEXT_COLUMNS]
    assert first["categorical_features"] == CATEGORICAL_FEATURES
    assert first["feature_count"] == 33
    assert set(first["removed_features"]) == set(PLAN_CONTEXT_COLUMNS)
    assert second == {"model_features": BASE_FEATURES, "numeric_features": NUMERIC_FEATURES,
                      "categorical_features": CATEGORICAL_FEATURES, "feature_count": 47}


def test_promotion_copies_exact_bytes_and_archives_original_provenance(artifact_root):
    root = artifact_root
    before = {path.relative_to(root).as_posix(): digest(path) for path in root.rglob("*") if path.is_file()}
    source_metadata = read_json(root / SOURCE_DIR / "model_metadata.json")
    manifest = promote(root)
    assert set(promoted_files(root)) == {"grade_model.txt", "fail_model.txt", "category_levels.json", "manifest.json"}
    for original, copied in [("grade_regressor.txt", "grade_model.txt"), ("fail_risk_classifier.txt", "fail_model.txt"),
                             ("category_levels.json", "category_levels.json")]:
        assert (root / SOURCE_DIR / original).read_bytes() == (root / PROMOTED_DIR / copied).read_bytes()
    assert {name: digest(root / name) for name in before} == before
    assert manifest == read_json(root / PROMOTED_DIR / "manifest.json")
    assert manifest["manifest_version"] == 1
    assert manifest["dataset_version"] == "V2"
    assert manifest["feature_engineering_version"] == 2
    for stage in ["stage1", "stage2"]:
        entry = manifest["stages"][stage]
        assert entry["feature_contract"] == expected_contract(stage)
        assert entry["training_as_of_part"] == 20243
        assert entry["training_cutoff_basis"]
        assert entry["models"]["grade"]["target"] == "final_mark"
        assert entry["models"]["grade"]["objective"] == "regression"
        assert entry["models"]["fail"]["target"] == "is_fail"
        assert entry["models"]["fail"]["target_definition"] == "final_mark < 50"
        assert entry["models"]["fail"]["objective"] == "binary"
    evidence = manifest["stages"]["stage1"]["provenance"]
    assert evidence["metadata"] == source_metadata
    assert evidence["metadata_sha256"] == digest(root / SOURCE_DIR / "model_metadata.json")
    assert evidence["input_sha256_at_promotion"] == source_metadata["input_sha256"]
    assert evidence["metadata"]["grade"]["selected_candidate"]["candidate"]["name"] == "capaciy_63"
    grade_scale_hash = digest(root / "data/raw/v_acs_grade.parquet")
    assert manifest["grade_scale"]["grade_scale_sha256"] == grade_scale_hash
    assert manifest["grade_scale"]["grade_scale_version"] == f"sha256:{grade_scale_hash}"
    assert manifest["prediction_contract"] == {
        "grade": {"clip": [0, 100], "expected_points_method": "predicted_mark_to_grade_scale"},
        "fail": {"clip": [0, 1]}, "reject_non_finite": True, "reject_wrong_shape": True,
    }
    assert manifest["ranking_approval"] == {"stage1_shortlist_strategy": "UNAPPROVED",
                                          "final_ranking_strategy": "UNAPPROVED", "combination": "UNAPPROVED"}


def test_promoted_pair_produces_the_same_synthetic_predictions(artifact_root):
    root = artifact_root
    promote(root)
    bundle = load(root)
    rows = pd.DataFrame({name: [1, 2, 4] for name in expected_contract("stage1")["model_features"]})
    for role, original in [("grade", "grade_regressor.txt"), ("fail", "fail_risk_classifier.txt")]:
        original_model = FakeBooster(root / SOURCE_DIR / original)
        copied_model = getattr(bundle.stage1, f"{role}_model")
        np.testing.assert_array_equal(original_model.predict(rows), copied_model.predict(rows))
    assert bundle.stage1.grade_model.num_feature() == 33
    assert bundle.stage2.grade_model.num_feature() == 47
    assert bundle.stage1.category_levels == bundle.stage2.category_levels
    points, labels = bundle.grade_scale.convert([49, 60, 90], [1, 1, 1])
    assert points.tolist() == [0, 2, 4]
    assert labels.tolist() == ["F", "C", "A"]
    assert bundle.manifest["ranking_approval"]["combination"] == "UNAPPROVED"


def test_repeat_promotion_refuses_overwrite_and_preserves_published_bytes(artifact_root):
    promote(artifact_root)
    before = promoted_files(artifact_root)
    with pytest.raises(FileExistsError):
        promote(artifact_root)
    assert promoted_files(artifact_root) == before


def test_manifest_is_deterministic_for_the_same_verified_artifacts(artifact_root):
    promotion = importlib.import_module("src.modeling.build_artifact_manifest")
    first = promotion.build_promotion_manifest(artifact_root)
    second = promotion.build_promotion_manifest(artifact_root)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert promote(artifact_root) == first


def test_artifact_loading_does_not_accept_ranking_approval_in_phase1(artifact_root):
    promote(artifact_root)
    mutate_manifest(artifact_root, lambda m: m["ranking_approval"].__setitem__("combination", "APPROVED"))
    with pytest.raises(ValueError, match="ranking activation"):
        load(artifact_root)


@pytest.mark.parametrize("failure_at", ["copy", "validate", "publish"])
def test_failed_promotion_leaves_no_partial_bundle_or_source_changes(artifact_root, monkeypatch, failure_at):
    promotion = importlib.import_module("src.modeling.build_artifact_manifest")
    before = {path.relative_to(artifact_root).as_posix(): digest(path)
              for path in artifact_root.rglob("*") if path.is_file()}

    def fail(*args, **kwargs):
        raise OSError("Synthetic publication failure")

    if failure_at == "copy":
        monkeypatch.setattr(promotion.shutil, "copyfile", fail)
    elif failure_at == "validate":
        monkeypatch.setattr(promotion, "load_manifest_assets", fail)
    else:
        monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(OSError, match="Synthetic publication failure"):
        promote(artifact_root)
    after = {path.relative_to(artifact_root).as_posix(): digest(path)
             for path in artifact_root.rglob("*") if path.is_file()}
    assert after == before
    assert not (artifact_root / PROMOTED_DIR).exists()
    assert not list((artifact_root / "models").glob(".shortlist-*"))


@pytest.mark.parametrize("relative", ["src/modeling/train_models.py", "data/features/temporal_train_features.parquet"])
def test_promotion_rejects_stale_input_or_source_signature(artifact_root, relative):
    (artifact_root / relative).write_bytes(b"changed after fitting")
    with pytest.raises(ValueError):
        promote(artifact_root)
    assert not (artifact_root / PROMOTED_DIR / "manifest.json").exists()


def test_promotion_rejects_changed_source_model_bytes(artifact_root):
    model = artifact_root / SOURCE_DIR / "grade_regressor.txt"
    model.write_bytes(model.read_bytes() + b" ")
    with pytest.raises(ValueError):
        promote(artifact_root)
    assert not (artifact_root / PROMOTED_DIR / "manifest.json").exists()


def test_promotion_rejects_incompatible_source_model_even_if_its_hash_is_resigned(artifact_root):
    root = artifact_root
    model_path = root / SOURCE_DIR / "grade_regressor.txt"
    model = read_json(model_path)
    model["features"][0] = "wrong_feature"
    write_json(model_path, model)
    metadata_path = root / SOURCE_DIR / "model_metadata.json"
    metadata = read_json(metadata_path)
    metadata["artifact_sha256"]["grade_regressor.txt"] = digest(model_path)
    write_json(metadata_path, metadata)
    with pytest.raises(ValueError):
        promote(root)
    assert not (root / PROMOTED_DIR / "manifest.json").exists()


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
@pytest.mark.parametrize("mutation", ["name", "order", "count", "categories", "objective"])
def test_loader_checks_model_header_semantics_even_with_matching_hashes(artifact_root, stage, mutation):
    promote(artifact_root)
    manifest = read_json(artifact_root / PROMOTED_DIR / "manifest.json")
    path = artifact_root / manifest["stages"][stage]["models"]["grade"]["path"]
    payload = read_json(path)
    if mutation == "name":
        payload["features"][0] = "wrong_feature"
    elif mutation == "order":
        payload["features"][0], payload["features"][1] = payload["features"][1], payload["features"][0]
    elif mutation == "count":
        payload["feature_count"] = len(payload["features"]) - 1
    elif mutation == "categories":
        payload["categories"][0] = list(reversed(payload["categories"][0]))
    else:
        payload["objective"] = "binary"
    write_json(path, payload)
    refresh_model_hash(artifact_root, stage, "grade")
    with pytest.raises(ValueError):
        load(artifact_root)


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
def test_loader_checks_fail_model_objective_even_with_matching_hash(artifact_root, stage):
    promote(artifact_root)
    manifest = read_json(artifact_root / PROMOTED_DIR / "manifest.json")
    path = artifact_root / manifest["stages"][stage]["models"]["fail"]["path"]
    payload = read_json(path)
    payload["objective"] = "regression"
    write_json(path, payload)
    refresh_model_hash(artifact_root, stage, "fail")
    with pytest.raises(ValueError):
        load(artifact_root)


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
def test_loader_checks_the_order_of_categorical_columns_in_model_metadata(artifact_root, stage):
    promote(artifact_root)
    manifest = read_json(artifact_root / PROMOTED_DIR / "manifest.json")
    path = artifact_root / manifest["stages"][stage]["models"]["grade"]["path"]
    payload = read_json(path)
    payload["categories"].reverse()
    write_json(path, payload)
    refresh_model_hash(artifact_root, stage, "grade")
    with pytest.raises(ValueError):
        load(artifact_root)


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
@pytest.mark.parametrize("field,value", [("target", "points"), ("objective", "regression"),
                                          ("target_definition", "previous_finish_status == F")])
def test_loader_rejects_reinterpreted_fail_targets_or_objectives(artifact_root, stage, field, value):
    promote(artifact_root)
    mutate_manifest(artifact_root, lambda m: m["stages"][stage]["models"]["fail"].__setitem__(field, value))
    with pytest.raises(ValueError):
        load(artifact_root)


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
def test_loader_rejects_reinterpreted_grade_target(artifact_root, stage):
    promote(artifact_root)
    mutate_manifest(artifact_root, lambda m: m["stages"][stage]["models"]["grade"].__setitem__("target", "points"))
    with pytest.raises(ValueError):
        load(artifact_root)


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
@pytest.mark.parametrize("field", ["model_features", "numeric_features", "categorical_features", "feature_count"])
def test_loader_rejects_corrupt_manifest_feature_contract(artifact_root, stage, field):
    promote(artifact_root)
    def mutate(manifest):
        contract = manifest["stages"][stage]["feature_contract"]
        contract[field] = 999 if field == "feature_count" else list(reversed(contract[field]))
    mutate_manifest(artifact_root, mutate)
    with pytest.raises(ValueError):
        load(artifact_root)


@pytest.mark.parametrize("target_part", [20243, 20241])
def test_loader_rejects_current_or_future_training_cutoff(artifact_root, target_part):
    promote(artifact_root)
    with pytest.raises(ValueError):
        load(artifact_root, target_part=target_part)


@pytest.mark.parametrize("relative", [f"{PROMOTED_DIR}/grade_model.txt", f"{PROMOTED_DIR}/fail_model.txt",
                                     OFFICIAL_ARTIFACTS["grade_model"], OFFICIAL_ARTIFACTS["fail_model"],
                                     "data/raw/v_acs_grade.parquet"])
def test_loader_rejects_changed_model_or_grade_scale_hash(artifact_root, relative):
    promote(artifact_root)
    path = artifact_root / relative
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        load(artifact_root)


def test_loader_rejects_changed_official_metadata_after_promotion(artifact_root):
    promote(artifact_root)
    path = artifact_root / OFFICIAL_ARTIFACTS["model_metadata"]
    metadata = read_json(path)
    metadata["targets"]["grade_regressor"] = "points"
    write_json(path, metadata)
    with pytest.raises(ValueError):
        load(artifact_root)


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
@pytest.mark.parametrize("matching_hash", [False, True])
def test_loader_rejects_changed_category_bytes_or_order(artifact_root, stage, matching_hash):
    promote(artifact_root)
    manifest_path = artifact_root / PROMOTED_DIR / "manifest.json"
    manifest = read_json(manifest_path)
    entry = manifest["stages"][stage]["category_levels"]
    path = artifact_root / entry["path"]
    levels = read_json(path)
    levels[CATEGORICAL_FEATURES[0]].reverse()
    write_json(path, levels)
    if matching_hash:
        entry["sha256"] = digest(path)
        entry["levels"] = levels
        write_json(manifest_path, manifest)
    with pytest.raises(ValueError):
        load(artifact_root)


def test_missing_promoted_model_never_falls_back_to_experimental_or_official_model(artifact_root):
    promote(artifact_root)
    (artifact_root / PROMOTED_DIR / "grade_model.txt").unlink()
    assert (artifact_root / SOURCE_DIR / "grade_regressor.txt").is_file()
    assert (artifact_root / OFFICIAL_ARTIFACTS["grade_model"]).is_file()
    with pytest.raises(FileNotFoundError):
        load(artifact_root)


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
def test_loader_rejects_an_unpinned_model_path_even_with_identical_bytes(artifact_root, stage):
    promote(artifact_root)
    manifest = read_json(artifact_root / PROMOTED_DIR / "manifest.json")
    model = manifest["stages"][stage]["models"]["grade"]
    alternative = artifact_root / "models/alternative_model.txt"
    alternative.write_bytes((artifact_root / model["path"]).read_bytes())
    mutate_manifest(artifact_root, lambda m: m["stages"][stage]["models"]["grade"].__setitem__("path", "models/alternative_model.txt"))
    with pytest.raises(ValueError):
        load(artifact_root)


def test_runtime_load_needs_no_experiment_or_training_file_reads_or_imports(artifact_root, monkeypatch):
    root = artifact_root
    promote(root)
    original_open = Path.open
    original_import = builtins.__import__
    def guarded_open(path, *args, **kwargs):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = ""
        if relative.startswith(("models/experiments/", "data/features/", "src/")):
            raise AssertionError(f"Serving opened a training/experimental file: {relative}")
        return original_open(path, *args, **kwargs)
    def guarded_import(name, *args, **kwargs):
        if name.startswith(("src.experiments", "src.modeling.train_models", "src.modeling.training_config")):
            raise AssertionError(f"Serving imported a trainer/experiment: {name}")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert load(root).stage1.grade_model.num_feature() == 33


@pytest.mark.parametrize("field,value", [("dataset_version", "V1"), ("feature_engineering_version", 1), ("manifest_version", 99)])
def test_loader_rejects_incompatible_manifest_version(artifact_root, field, value):
    promote(artifact_root)
    mutate_manifest(artifact_root, lambda m: m.__setitem__(field, value))
    with pytest.raises(ValueError):
        load(artifact_root)


def test_runtime_module_has_no_direct_experiment_or_trainer_import():
    module = importlib.import_module("src.recommendation.two_stage_artifacts")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith(("src.experiments", "src.modeling")) for name in imports)


@pytest.mark.parametrize("field", ["metadata_path", "metadata_sha256",
                                    "source_artifact_sha256_at_promotion", "source_evidence_sha256_at_promotion"])
def test_loader_requires_archived_original_provenance(artifact_root, field):
    promote(artifact_root)
    mutate_manifest(artifact_root, lambda m: m["stages"]["stage1"]["provenance"].pop(field))
    with pytest.raises(ValueError):
        load(artifact_root)


def test_loader_rejects_malformed_archived_metadata_hash(artifact_root):
    promote(artifact_root)
    mutate_manifest(artifact_root, lambda m: m["stages"]["stage1"]["provenance"].__setitem__("metadata_sha256", "missing"))
    with pytest.raises(ValueError):
        load(artifact_root)
