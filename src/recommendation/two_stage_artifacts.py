"""Pinned artifact and approval contracts for the two-stage engine.

This module loads model assets only. Ranking approval and engine orchestration
remain separate; successful artifact loading does not approve a ranking policy.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from src.features.feature_contract import (
    BASE_FEATURES, CATEGORICAL_FEATURES, CATEGORY_MISSING, CATEGORY_UNKNOWN,
    FEATURE_ENGINEERING_VERSION, NUMERIC_FEATURES, require_current_features,
)
from src.features.frozen_history import file_sha256
from src.features.temporal_features import PLAN_CONTEXT_COLUMNS
from src.grade_scale import GradeScale
from src import paths
from .ranking_policy import UNAPPROVED_RANKING, validate_ranking_policy


MANIFEST_VERSION = 1
PREDICTION_CONTRACT = {
    "grade": {"clip": [0, 100], "expected_points_method": "predicted_mark_to_grade_scale"},
    "fail": {"clip": [0, 1]}, "reject_non_finite": True, "reject_wrong_shape": True,
}


@dataclass(frozen=True)
class ModelPair:
    grade_model: object
    fail_model: object
    category_levels: dict


@dataclass(frozen=True)
class TwoStageArtifacts:
    stage1: ModelPair
    stage2: ModelPair
    grade_scale: GradeScale
    manifest: dict


def stage_feature_contract(stage):
    """Derive Stage 1 by removing current plan context from the official order."""
    if stage not in {"stage1", "stage2"}:
        raise ValueError(f"Unknown model stage: {stage!r}")
    removed = set(PLAN_CONTEXT_COLUMNS) if stage == "stage1" else set()
    features = [name for name in BASE_FEATURES if name not in removed]
    if (len(BASE_FEATURES) != 47 or len(set(BASE_FEATURES)) != 47
            or len(PLAN_CONTEXT_COLUMNS) != 14 or len(set(PLAN_CONTEXT_COLUMNS)) != 14
            or not set(PLAN_CONTEXT_COLUMNS).issubset(NUMERIC_FEATURES)
            or len(features) != (33 if stage == "stage1" else 47)):
        raise ValueError("Two-stage artifacts require the approved 47-minus-14 contract.")
    contract = {
        "model_features": features,
        "numeric_features": [name for name in NUMERIC_FEATURES if name in features],
        "categorical_features": CATEGORICAL_FEATURES.copy(),
        "feature_count": len(features),
    }
    if stage == "stage1":
        contract["removed_features"] = sorted(removed)
    return contract


def artifact_relative_paths(stage): ## save location not hardpath
    """Keep canonical deployment paths centralized in src.paths."""
    selected = {
        "stage1": (paths.SHORTLIST_GRADE_MODEL_PATH, paths.SHORTLIST_FAIL_MODEL_PATH,
                   paths.SHORTLIST_CATEGORY_LEVELS_PATH),
        "stage2": (paths.GRADE_MODEL_PATH, paths.FAIL_MODEL_PATH,
                   paths.CATEGORY_LEVELS_PATH),
    }[stage]
    return dict(zip(("grade", "fail", "category_levels"),
                    (path.relative_to(paths.PROJECT_ROOT).as_posix() for path in selected)))


def project_file(root, relative):
    """Resolve a portable, root-relative artifact reference within the project."""
    root = Path(root).resolve()
    value = Path(relative)
    path = (root / value).resolve()
    if value.is_absolute() or ".." in value.parts or not path.is_relative_to(root):
        raise ValueError(f"Artifact reference escapes project root: {relative!r}")
    return path


def read_artifact_json(path):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)


def _is_sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def verify_artifact_hash(path, expected):
    """Require existence and a full SHA-256 match before interpreting any file."""
    if not Path(path).is_file():
        raise FileNotFoundError(f"Required two-stage artifact missing: {path}")
    if not _is_sha256(expected) or file_sha256(path) != expected:
        raise ValueError(f"Artifact SHA-256 mismatch: {path}")


def validate_stage_metadata(stage, metadata):
    """Validate original evidence without changing or normalizing that evidence."""
    require_current_features(metadata)
    if metadata.get("dataset_version", "V2" if stage == "stage2" else None) != "V2":
        raise ValueError(f"{stage} metadata must identify V2.")
    expected = stage_feature_contract(stage)
    recorded = metadata.get("feature_contract", {})
    checked = ("model_features", "feature_count", "removed_features") if stage == "stage1" else expected
    if any(recorded.get(key) != expected[key] for key in checked):
        raise ValueError(f"{stage} metadata feature contract mismatch.")
    if stage == "stage1":
        sections = ("grade", "fail")
        cutoff = metadata["training_as_of_part"]
        basis = "original_metadata.training_as_of_part"
    else:
        sections = ("grade_regressor", "fail_risk_classifier")
        if metadata.get("targets") != {
            "grade_regressor": "final_mark", "fail_risk_classifier": "(final_mark < 50).astype(int)",
        }:
            raise ValueError("Official V2 target definitions mismatch.")
        expected_paths = artifact_relative_paths(stage)
        expected_metadata_paths = {
            "grade_model": expected_paths["grade"], "fail_model": expected_paths["fail"],
            "category_levels": expected_paths["category_levels"],
            "model_metadata": paths.MODEL_METADATA_PATH.relative_to(paths.PROJECT_ROOT).as_posix(),
        }
        if metadata.get("artifacts") != expected_metadata_paths:
            raise ValueError("Official V2 metadata artifact paths mismatch.")
        for section in sections:
            selected = metadata[section]["selected_candidate"]
            candidates = metadata[section].get("all_candidates", [])
            if (not candidates or selected not in candidates
                    or selected != min(candidates, key=lambda item: item["mean_primary_metric"])):
                raise ValueError("Official V2 selected candidate mismatch.")
        cutoff = metadata["course_history"]["initial_history_cutoff"]
        basis = "original_metadata.course_history.initial_history_cutoff"
    for section, objective in zip(sections, ("regression", "binary")):
        if metadata[section]["parameters"]["objective"] != objective:
            raise ValueError(f"{stage} original model objective mismatch.")
    return paths.academic_part(cutoff), basis


def load_model_pair(entry, model_paths):
    """Inspect actual LightGBM headers and category order, using pinned assets."""
    import lightgbm as lgb

    levels_entry = entry["category_levels"]
    verify_artifact_hash(model_paths["category_levels"], levels_entry["sha256"])
    levels = read_artifact_json(model_paths["category_levels"])
    if (levels != levels_entry["levels"] or set(levels) != set(CATEGORICAL_FEATURES)
            or any(not isinstance(values, list) or not all(isinstance(value, str) for value in values)
                   or len(values) != len(set(values))
                   or CATEGORY_MISSING not in values or CATEGORY_UNKNOWN not in values
                   for values in levels.values())):
        raise ValueError("Category levels must match the complete ordered category contract.")
    models = []
    for role in ("grade", "fail"):
        specification = entry["models"][role]
        verify_artifact_hash(model_paths[role], specification["sha256"])
        model = lgb.Booster(model_file=str(model_paths[role]))
        contract = entry["feature_contract"]
        if (model.feature_name() != contract["model_features"]
                or model.num_feature() != contract["feature_count"]):
            raise ValueError(f"{role} model feature names/order/count mismatch.")
        if model.pandas_categorical != [levels[name] for name in CATEGORICAL_FEATURES]:
            raise ValueError(f"{role} model embedded category order mismatch.")
        actual_objective = model.dump_model()["objective"]
        allowed = {"regression"} if role == "grade" else {"binary", "binary sigmoid:1"}
        if actual_objective not in allowed:
            raise ValueError(f"{role} model binary header objective mismatch.")
        models.append(model)
    return ModelPair(*models, levels)


def validate_archived_provenance(stage, evidence):
    """Require original evidence without reopening fitting inputs during serving."""
    relative = Path(evidence["metadata_path"])
    if (relative.is_absolute() or ".." in relative.parts
            or relative.name not in {"model_metadata.json", paths.MODEL_METADATA_PATH.name}
            or not _is_sha256(evidence["metadata_sha256"])):
        raise ValueError("Original metadata path/hash provenance is incomplete.")
    for field in ("dataset_version_basis", "target_basis"):
        if not isinstance(evidence[field], str) or not evidence[field]:
            raise ValueError(f"Missing original provenance basis: {field}")
    source_evidence = evidence["source_evidence_sha256_at_promotion"]
    if (set(source_evidence) != {"src/modeling/training_config.py", "src/features/build_temporal_features.py",
                                "src/grade_scale.py"}
            or not all(_is_sha256(value) for value in source_evidence.values())):
        raise ValueError("Archived target/GradeScale source fingerprints are incomplete.")
    if stage == "stage1":
        signature = evidence["input_sha256_at_promotion"]
        if (signature != evidence["metadata"]["input_sha256"] or len(signature) != 11
                or not all(_is_sha256(value) for value in signature.values())
                or signature.get("src/modeling/training_config.py") != source_evidence["src/modeling/training_config.py"]):
            raise ValueError("Original training input/source fingerprints are incomplete.")
        original_artifacts = evidence["source_artifact_sha256_at_promotion"]
        expected = {
            (relative.parent / name).as_posix(): value
            for name, value in evidence["metadata"]["artifact_sha256"].items()
        }
        if original_artifacts != expected or not all(_is_sha256(value) for value in original_artifacts.values()):
            raise ValueError("Original source artifact fingerprints are incomplete.")


def validate_artifact_manifest(manifest):
    """Validate the deployment contract; this does not approve ranking activation."""
    if (manifest["manifest_version"] != MANIFEST_VERSION or manifest["dataset_version"] != "V2"
            or manifest["feature_engineering_version"] != FEATURE_ENGINEERING_VERSION):
        raise ValueError("Incompatible two-stage manifest version.")
    if manifest["prediction_contract"] != PREDICTION_CONTRACT:
        raise ValueError("Prediction processing contract mismatch.")
    validate_ranking_policy(manifest)
    for stage in ("stage1", "stage2"):
        entry = manifest["stages"][stage]
        validate_archived_provenance(stage, entry["provenance"])
        if entry["feature_contract"] != stage_feature_contract(stage):
            raise ValueError(f"{stage} manifest feature contract mismatch.")
        cutoff, basis = validate_stage_metadata(stage, entry["provenance"]["metadata"])
        if entry["training_as_of_part"] != cutoff or entry["training_cutoff_basis"] != basis:
            raise ValueError(f"{stage} training cutoff disagrees with original metadata.")
        expected_paths = artifact_relative_paths(stage)
        if entry["category_levels"]["path"] != expected_paths["category_levels"]:
            raise ValueError(f"{stage} category path is outside its approved namespace.")
        for role, target, objective in (("grade", "final_mark", "regression"), ("fail", "is_fail", "binary")):
            model = entry["models"][role]
            if (model["path"] != expected_paths[role] or model["target"] != target
                    or model["objective"] != objective
                    or (role == "fail" and model["target_definition"] != "final_mark < 50")):
                raise ValueError(f"{stage} {role} model path/target/objective mismatch.")
    scale = manifest["grade_scale"]
    if (scale["path"] != paths.GRADE_SCALE_PATH.relative_to(paths.PROJECT_ROOT).as_posix()
            or scale["grade_scale_version"] != f"sha256:{scale['grade_scale_sha256']}"):
        raise ValueError("GradeScale path/content version mismatch.")


def load_manifest_assets(manifest, *, project_root, shortlist_directory=None, target_part=None):
    """Shared validation for publication staging and ordinary artifact loading."""
    validate_artifact_manifest(manifest)
    if target_part is not None:
        target = paths.academic_part(target_part)
        if any(entry["training_as_of_part"] >= target for entry in manifest["stages"].values()):
            raise ValueError("Model training must precede the target semester.")
    pairs = []
    for stage in ("stage1", "stage2"):
        entry = manifest["stages"][stage]
        relative = artifact_relative_paths(stage)
        selected = {key: project_file(project_root, value) for key, value in relative.items()}
        if stage == "stage1" and shortlist_directory is not None:
            selected = {key: Path(shortlist_directory) / Path(value).name for key, value in relative.items()}
        pairs.append(load_model_pair(entry, selected))
        evidence = entry["provenance"]
        if stage == "stage1":
            original = evidence["metadata"]
            if evidence["input_sha256_at_promotion"] != original["input_sha256"]:
                raise ValueError("Original training signature was not preserved.")
            for key, source_name in (("grade", "grade_regressor.txt"), ("fail", "fail_risk_classifier.txt"),
                                     ("category_levels", "category_levels.json")):
                pinned = entry["category_levels"] if key == "category_levels" else entry["models"][key]
                if pinned["sha256"] != original["artifact_sha256"][source_name]:
                    raise ValueError("Promoted bytes disagree with original artifact provenance.")
        else:
            relative_metadata = paths.MODEL_METADATA_PATH.relative_to(paths.PROJECT_ROOT).as_posix()
            if evidence["metadata_path"] != relative_metadata:
                raise ValueError("Official V2 metadata path mismatch.")
            metadata_path = project_file(project_root, relative_metadata)
            verify_artifact_hash(metadata_path, evidence["metadata_sha256"])
            if read_artifact_json(metadata_path) != evidence["metadata"]:
                raise ValueError("Official V2 metadata disagrees with archived evidence.")
    scale = manifest["grade_scale"]
    scale_path = project_file(project_root, scale["path"])
    verify_artifact_hash(scale_path, scale["grade_scale_sha256"])
    return TwoStageArtifacts(*pairs, GradeScale.from_parquet(scale_path), manifest)


def load_two_stage_artifacts(*, project_root=paths.PROJECT_ROOT, target_part=None):
    """Load all four pinned models without experiments, trainers, or history I/O.

No fallback or asset generation is performed. The future engine must still
enforce ranking approval and history compatibility before serving requests.
"""
    relative = paths.TWO_STAGE_MANIFEST_PATH.relative_to(paths.PROJECT_ROOT).as_posix()
    manifest = read_artifact_json(project_file(project_root, relative))
    try:
        return load_manifest_assets(manifest, project_root=project_root, target_part=target_part)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"Incomplete two-stage artifact manifest: {error}") from error
